"""Offline operator commands. No HTTP/MCP entry point, signing keys or credentials.

Mutations require an Ed25519 signature by a separately provisioned budget operator.
The service receives only public trust keys, stored outside the repository with OS ACLs.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, Field

from canvas_bridge.usage.ledger import UpstreamUsageGovernor, digest
from canvas_bridge.usage.policy import Identifier, Model, PartnerBudgetContract, Units, canonical


class VendorStatement(Model):
    statement_id: Identifier
    provider: Identifier = "canvas"
    contract_id: Identifier
    cycle: str = Field(pattern=r"^[a-f0-9]{64}$")
    unit: Literal["commercial_transaction"] = "commercial_transaction"
    total_units: Units
    as_of: AwareDatetime
    status: Literal["verified", "final"]
    settlements: dict[Identifier, Units] = Field(default_factory=dict, max_length=1000)
    release_restore_hold: bool = False
    release_external_buffer: bool = False
    spend: Decimal | None = Field(
        default=None, ge=0, allow_inf_nan=False, max_digits=18, decimal_places=4
    )
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Identifier


class OperatorCommand(Model):
    action: Literal["apply", "reconcile"]
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    expected_policy: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    payload: dict


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256000:
        raise ValueError("Invalid operator input file.")
    return json.loads(path.read_text(encoding="utf-8"))


def verify(envelope, trust, action, now):
    if set(envelope) != {"key_id", "command", "signature"}:
        raise ValueError("Invalid operator envelope.")
    key = trust.get("keys", {}).get(envelope["key_id"])
    if not key or key.get("role") != "budget_operator":
        raise ValueError("A trusted budget operator is required.")
    expires = datetime.fromisoformat(key["expires_at"])
    if expires.tzinfo is None or expires <= now:
        raise ValueError("Operator key expired.")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(key["public_key"], validate=True)).verify(
        base64.b64decode(envelope["signature"], validate=True), canonical(envelope["command"])
    )
    command = OperatorCommand.model_validate(envelope["command"])
    if (
        command.action != action
        or not command.issued_at <= now < command.expires_at
        or command.expires_at - command.issued_at > timedelta(hours=24)
    ):
        raise ValueError("Operator command is expired or not applicable.")
    return command, envelope["key_id"]


def apply_envelope(governor, envelope, trust, action):
    command, actor = verify(envelope, trust, action, datetime.fromtimestamp(governor.clock(), UTC))
    if action == "apply":
        policy = PartnerBudgetContract.model_validate(command.payload)
        return governor.activate(policy, actor, expected_digest=command.expected_policy)
    statement = VendorStatement.model_validate(command.payload)
    return governor.reconcile(statement, actor)


def preview(policy, previous=None):
    old = previous.model_dump(mode="json") if previous else {}
    current = policy.model_dump(mode="json")
    return {
        "read_only": True,
        "policy_digest": policy.digest,
        "usable_units": policy.usable,
        "targets": policy.targets(),
        "paid_overages": "disabled",
        "authorizes_provider_access": False,
        "changes": {
            k: {"before": old.get(k), "after": v} for k, v in current.items() if old.get(k) != v
        },
        "policy": current,
    }


def simulate(policy, requests):
    """Pure conservative planning simulation; durable race tests are a separate gate."""
    if not 1 <= requests <= 1000000:
        raise ValueError("Simulation must contain 1..1000000 fictional requests.")
    targets = policy.targets()
    booked = dict.fromkeys(targets, 0)
    admitted = dict.fromkeys(targets, 0)
    available = max(0, policy.usable - policy.billing.external_usage_buffer_units)
    classes = ("interactive", "interactive", "scheduled_sync", "interactive", "exploratory")
    for n in range(requests):
        own = classes[n % len(classes)]
        units = policy.billing.default_units
        if units > available or policy.billing.status == "unconfigured" or policy.kill_switch:
            continue
        pools = (
            [own]
            if policy.allocation.pool_mode == "strict_pools"
            else [own] + [p for p in classes if p != own]
        )
        plan, remaining = {}, units
        for pool in dict.fromkeys(pools):
            floor = (
                int(targets[pool] * policy.allocation.lender_floor_pct / 100) if pool != own else 0
            )
            take = min(remaining, max(0, targets[pool] - booked[pool] - floor))
            plan[pool], remaining = take, remaining - take
        if remaining:
            continue
        for pool, take in plan.items():
            booked[pool] += take
        available -= units
        admitted[own] += 1
    return {
        "mode": "offline_synthetic",
        "read_only": True,
        "network_attempts": 0,
        "simulated_requests": requests,
        "admitted_by_class": admitted,
        "booked_units": booked,
        "remaining_global_units": available,
        "limitations": "Allocation planning only; task, fairness, technical and database concurrency verified by acceptance tests.",
    }


def arguments(sub):
    root = sub.add_parser(
        "budget", help="Operator-only upstream accounting; never grants source access."
    )
    commands = root.add_subparsers(dest="budget_action", required=True)
    for action in ("status", "report", "propose", "simulate", "apply", "reconcile"):
        parser = commands.add_parser(action)
        parser.add_argument("--provider", default="canvas")
        if action in {"propose", "simulate"}:
            parser.add_argument("--policy", required=True, type=Path)
        if action == "propose":
            parser.add_argument("--allowance", type=int)
        if action == "simulate":
            parser.add_argument("--requests", type=int, default=100000)
        if action in {"apply", "reconcile"}:
            parser.add_argument("--approved-command", required=True, type=Path)
        if action == "report":
            parser.add_argument("--cycle")
            parser.add_argument(
                "--html", type=Path, help="Write an aggregate local operator dashboard."
            )


def run(args, settings):
    from canvas_bridge.storage import Store

    if args.budget_action in {"propose", "simulate"}:
        data = read_json(args.policy)
        if args.budget_action == "propose" and args.allowance is not None:
            data["billing"]["monthly_allowance"] = args.allowance
        policy = PartnerBudgetContract.model_validate(data)
        if policy.provider != args.provider:
            raise ValueError("Provider mismatch.")
        return (
            preview(policy) if args.budget_action == "propose" else simulate(policy, args.requests)
        )
    store = Store(settings.database_url)
    try:
        governor = UpstreamUsageGovernor(store.engine)
        if args.budget_action in {"status", "report"}:
            report = governor.report(args.provider, getattr(args, "cycle", None))
            if getattr(args, "html", None):
                from canvas_bridge.usage.dashboard import render

                args.html.write_text(render(report), encoding="utf-8")
            return report
        if settings.budget_trust_file is None:
            raise ValueError("No trusted budget operator is configured.")
        envelope = read_json(args.approved_command)
        if envelope.get("command", {}).get("payload", {}).get("provider") != args.provider:
            raise ValueError("Provider mismatch.")
        result = apply_envelope(
            governor, envelope, read_json(settings.budget_trust_file), args.budget_action
        )
        return {
            "result": result,
            "authorizes_provider_access": False,
            "command_sha256": digest(envelope),
        }
    finally:
        store.close()
