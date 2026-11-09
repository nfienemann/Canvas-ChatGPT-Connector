"""CB-BUDGET-01..06: fictional contracts, durable races and no institution traffic."""

import asyncio
import base64
import json
import multiprocessing
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import create_engine, select

from canvas_bridge.domain import DomainError
from canvas_bridge.network import GuardedHTTP
from canvas_bridge.usage import models as m
from canvas_bridge.usage.admin import VendorStatement, apply_envelope, preview, simulate
from canvas_bridge.usage.cache import AuthorizedCache
from canvas_bridge.usage.ledger import UpstreamUsageGovernor, finite_header
from canvas_bridge.usage.policy import (
    PartnerBudgetContract,
    UsageContext,
    canonical,
    synthetic_policy,
)
from canvas_bridge.usage.transport import OPERATIONS, UsageBinding


def policy(allowance=100, **changes):
    data = synthetic_policy().model_dump(mode="json")
    data["billing"].update(
        monthly_allowance=allowance, signed_allowance=allowance, safety_margin_pct="0"
    )
    data["allocation"].update(
        interactive_pct="100", scheduled_sync_pct="0", exploratory_pct="0", reserve_pct="0"
    )
    data["limits"].update(
        max_global_concurrency=100, max_concurrency_per_tenant=100, max_concurrency_per_owner=20
    )
    for section, values in changes.items():
        if isinstance(values, dict):
            data[section].update(values)
        else:
            data[section] = values
    return PartnerBudgetContract.model_validate(data)


@pytest.fixture
def ledger(tmp_path):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "usage.db"),
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    m.metadata.create_all(engine)
    yield engine
    engine.dispose()


def ctx(**changes):
    return replace(
        UsageContext(
            "canvas",
            None,
            "tenant",
            "owner",
            uuid4().hex,
            "canvas.assignment",
            "interactive",
            "epoch",
            uuid4().hex,
        ),
        **changes,
    )


def reserve(governor, context):
    return governor.reserve(
        context,
        authorize=lambda: None,
        operation=OPERATIONS[context.operation],
        mode="offline_synthetic",
    )


def spend(governor, context=None, status=200, **kwargs):
    context = context or ctx()
    reserve(governor, context)
    governor.sent(context.attempt_id, lambda: None)
    governor.finish(context.attempt_id, status=status, **kwargs)
    return context


def test_unknown_contract_denies_before_send(ledger):
    governor = UpstreamUsageGovernor(ledger)
    with pytest.raises(DomainError) as exc:
        reserve(governor, ctx())
    assert exc.value.reason_code == "BILLING_CONTRACT_UNCONFIGURED"
    assert governor.report()["state"] == "no_usage"


@pytest.mark.parametrize(
    "allowance,total,targets",
    [
        (300000, 285000, [156750, 71250, 28500, 28500]),
        (500000, 475000, [261250, 118750, 47500, 47500]),
    ],
)
def test_allowance_recomputes_percentages(allowance, total, targets):
    p = policy(
        allowance,
        billing={"safety_margin_pct": "5"},
        allocation={
            "interactive_pct": "55",
            "scheduled_sync_pct": "25",
            "exploratory_pct": "10",
            "reserve_pct": "10",
        },
    )
    assert p.usable == total
    assert list(p.targets().values()) == targets


@given(st.integers(min_value=0, max_value=10**9))
def test_rounding_conserves_every_unit(allowance):
    p = policy(
        allowance,
        billing={"safety_margin_pct": "5"},
        allocation={
            "interactive_pct": "55",
            "scheduled_sync_pct": "25",
            "exploratory_pct": "10",
            "reserve_pct": "10",
        },
    )
    assert sum(p.targets().values()) == p.usable <= allowance


@pytest.mark.parametrize(
    "section,change",
    [
        ("billing", {"monthly_allowance": None}),
        ("billing", {"monthly_allowance": -1}),
        ("billing", {"monthly_allowance": 101}),
        ("billing", {"cycle_day": 32}),
        ("billing", {"cycle_timezone": "invalid/time"}),
        ("billing", {"unit": "dollars"}),
        ("billing", {"failed_requests": "unknown"}),
        ("billing", {"paid_overages": "enabled"}),
        ("allocation", {"interactive_pct": "99.9"}),
        ("allocation", {"reserve_pct": "-1"}),
    ],
)
def test_invalid_policy_rejected(section, change):
    with pytest.raises((ValueError, KeyError)):
        policy(**{section: change})


def test_100_contenders_never_double_spend_25_units(ledger):
    p = policy(25)

    # Each thread owns a governor; only the database lock coordinates them.
    def contender(_):
        governor = UpstreamUsageGovernor(ledger, fixture_policy=p)
        started = time.perf_counter()
        try:
            spend(governor, ctx(owner_id=uuid4().hex))
            return True, time.perf_counter() - started
        except DomainError as exc:
            assert exc.reason_code == "UPSTREAM_BUDGET_EXHAUSTED"
            return False, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(contender, range(100)))
    assert sum(ok for ok, _ in results) == 25
    result = UpstreamUsageGovernor(ledger).report()
    assert result["settled"] == 25 and result["reserved"] == result["uncertain"] == 0
    times = sorted(t for _, t in results)
    print(
        f"admission race p50={statistics.median(times) * 1000:.1f}ms p95={times[94] * 1000:.1f}ms"
    )


def process_contender(url, queue):
    engine = create_engine(url, connect_args={"timeout": 30})
    try:
        spend(UpstreamUsageGovernor(engine, fixture_policy=policy(1)))
        queue.put("admitted")
    except DomainError as exc:
        queue.put(exc.reason_code)
    finally:
        engine.dispose()


def test_two_processes_race_last_unit(ledger):
    process = multiprocessing.get_context("spawn")
    queue = process.Queue()
    workers = [
        process.Process(target=process_contender, args=(str(ledger.url), queue)) for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in workers) == [
        "UPSTREAM_BUDGET_EXHAUSTED",
        "admitted",
    ]


def test_crash_before_and_after_send_recovery(ledger):
    now = [time.time()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(2), clock=lambda: now[0])
    before, after = ctx(), ctx()
    reserve(governor, before)
    reserve(governor, after)
    governor.sent(after.attempt_id, lambda: None)
    now[0] += 181
    restarted = UpstreamUsageGovernor(ledger, clock=lambda: now[0])
    restarted.recover()
    result = restarted.report()
    assert (result["reserved"], result["uncertain"], result["available"]) == (0, 1, 1)
    with ledger.connect() as db:
        states = dict(db.execute(select(m.attempts.c.id, m.attempts.c.state)).all())
    assert states[before.attempt_id] == "CANCELLED_BEFORE_SEND"
    assert states[after.attempt_id] == "UNCERTAIN"
    with pytest.raises(DomainError):
        restarted.sent(before.attempt_id, lambda: None)


def test_settlement_idempotency_and_headers_are_not_billing(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    context = spend(governor, headers={"x-request-cost": "892.125"})
    governor.finish(context.attempt_id, status=200)
    assert governor.report()["settled"] == 1
    with ledger.connect() as db:
        assert db.scalar(select(m.attempts.c.throttle_cost)) == 892.125
    with pytest.raises(DomainError):
        reserve(governor, context)


def test_excess_actual_cost_quarantines_contract(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    with pytest.raises(DomainError) as exc:
        spend(governor, actual_units=5)
    assert exc.value.reason_code == "GOVERNOR_UNAVAILABLE"
    assert governor.report()["quarantined"] == 1
    with pytest.raises(DomainError) as exc:
        spend(governor)
    assert exc.value.reason_code == "UPSTREAM_BUDGET_EXHAUSTED"


def test_authorization_always_precedes_accounting(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())

    def revoked():
        raise DomainError("permission_denied", "Revoked")

    with pytest.raises(DomainError, match="Revoked"):
        governor.reserve(
            ctx(),
            authorize=revoked,
            operation=OPERATIONS["canvas.assignment"],
            mode="offline_synthetic",
        )
    assert governor.report()["state"] == "no_usage"


def test_database_outage_fails_closed(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "unmigrated.db"))
    with pytest.raises(DomainError) as exc:
        reserve(UpstreamUsageGovernor(engine, fixture_policy=policy()), ctx())
    assert exc.value.reason_code == "GOVERNOR_UNAVAILABLE"
    engine.dispose()


def test_owner_caps_cannot_reset_by_splitting_tasks(ledger):
    governor = UpstreamUsageGovernor(
        ledger, fixture_policy=policy(limits={"per_owner_minute_attempts": 3})
    )
    for _ in range(3):
        spend(governor)
    with pytest.raises(DomainError) as exc:
        spend(governor, ctx(task_id="new-task"))
    assert exc.value.reason_code == "OWNER_RATE_LIMITED"


def test_task_caps_shared_by_retries_and_pages(ledger):
    governor = UpstreamUsageGovernor(
        ledger, fixture_policy=policy(limits={"max_attempts_per_task": 2})
    )
    for _ in range(2):
        spend(governor, ctx(task_id="same-task"))
    with pytest.raises(DomainError) as exc:
        spend(governor, ctx(task_id="same-task"))
    assert exc.value.reason_code == "TASK_BUDGET_EXCEEDED"


def test_borrowing_records_lenders_but_cannot_consume_reserve(ledger):
    governor = UpstreamUsageGovernor(
        ledger,
        fixture_policy=policy(
            10,
            allocation={
                "interactive_pct": "50",
                "scheduled_sync_pct": "30",
                "reserve_pct": "20",
                "lender_floor_pct": "0",
            },
        ),
    )
    for _ in range(8):
        spend(governor)
    result = governor.report()
    assert next(p for p in result["pools"] if p["name"] == "interactive")["borrowed"] == 3
    with pytest.raises(DomainError) as exc:
        spend(governor)
    assert exc.value.reason_code == "WORKLOAD_POOL_DEFERRED"
    with pytest.raises(DomainError) as exc:
        spend(governor, ctx(workload_class="reserve"))
    assert exc.value.reason_code == "PROVIDER_NOT_AUTHORIZED"


def test_cycle_timezone_dst_and_clamped_month_end():
    p = policy(billing={"cycle_day": 31, "cycle_timezone": "America/New_York"})
    start, end = p.cycle(datetime(2024, 2, 29, 6, tzinfo=UTC))
    assert start == datetime(2024, 2, 29, 5, tzinfo=UTC)
    assert end == datetime(2024, 3, 31, 4, tzinfo=UTC)
    assert p.cycle(end)[0] == end


def test_rollover_keeps_historical_usage(ledger):
    now = [datetime(2026, 1, 31, 23, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(1), clock=lambda: now[0])
    spend(governor)
    previous = governor.report()["id"]
    now[0] += 7200
    spend(governor)
    assert governor.report()["id"] != previous
    assert governor.report(cycle=previous)["settled"] == 1


def signed(command, key):
    return {
        "key_id": "operator",
        "command": command,
        "signature": base64.b64encode(key.sign(canonical(command))).decode(),
    }


def operator(now):
    key = Ed25519PrivateKey.generate()
    return key, {
        "keys": {
            "operator": {
                "role": "budget_operator",
                "public_key": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
                "expires_at": (now + timedelta(days=1)).isoformat(),
            }
        }
    }


def test_signed_apply_and_midcycle_updates_preserve_usage(ledger):
    now = datetime.now(UTC)
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now.timestamp())
    spend(governor)
    old = policy()
    p = policy(500, version=2, effective_at=now, billing={"evidence_sha256": "1" * 64})
    key, trust = operator(now)
    command = {
        "action": "apply",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "expected_policy": old.digest,
        "payload": p.model_dump(mode="json"),
    }
    envelope = signed(command, key)
    assert apply_envelope(governor, envelope, trust, "apply") == p.digest
    spend(governor)
    assert governor.report()["settled"] == 2 and governor.report()["usable"] == 500
    with pytest.raises(ValueError):
        apply_envelope(governor, envelope, trust, "apply")
    tampered = {**envelope, "command": {**command, "expected_policy": p.digest}}
    with pytest.raises(InvalidSignature):
        apply_envelope(governor, tampered, trust, "apply")


def test_preview_simulation_are_read_only():
    p = policy(300000)
    before = p.digest
    assert preview(p)["read_only"] is True
    result = simulate(p, 100000)
    assert result["network_attempts"] == 0
    assert p.digest == before


def test_statement_deduplication_and_historical_cycle_isolation(ledger):
    now = [datetime(2026, 1, 31, 23, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(10), clock=lambda: now[0])
    spend(governor)
    previous = governor.report()["id"]
    now[0] += 7200
    spend(governor)
    statement = VendorStatement(
        statement_id="invoice-one",
        contract_id="synthetic-fixture",
        cycle=previous,
        total_units=5,
        status="verified",
        as_of=datetime.fromtimestamp(now[0], UTC),
        evidence_sha256="2" * 64,
        reason="external_usage",
    )
    assert governor.reconcile(statement, "operator") == "recorded"
    assert governor.reconcile(statement, "operator") == "already_recorded"
    assert governor.report(cycle=previous)["external"] == 4
    assert governor.report()["external"] == 0
    assert governor.report(cycle=previous)["events"]["VENDOR_DISCREPANCY"] == 1


def test_alerts_deduplicate_and_use_usable_denominator(ledger):
    governor = UpstreamUsageGovernor(
        ledger, fixture_policy=policy(10, billing={"safety_margin_pct": "20"})
    )
    for _ in range(5):
        spend(governor)
    report = governor.report()
    assert report["events"]["threshold_50"] == 1
    assert "threshold_70" not in report["events"]
    assert report["vendor_spend"] == "N/A"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1\r\nevil", "9" * 65])
def test_hostile_technical_headers(value):
    assert finite_header(value) is None


async def test_all_requests_require_binding_and_authorization(ledger):
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, json={})
        )
    ) as http:
        with pytest.raises(DomainError) as exc:
            await GuardedHTTP(http, lambda *_: None).send(
                httpx.Request("GET", "https://canvas.invalid/api/v1/courses")
            )
        assert exc.value.reason_code == "GOVERNOR_UNAVAILABLE"
    assert not calls


async def test_transport_charges_each_retry_and_keeps_429_uncertain(bridge):
    from canvas_bridge.canvas import CanvasClient
    from canvas_bridge.policy import Endpoint

    statuses = [429, 503, 200]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                statuses.pop(0), json={"id": 1}, headers={"Retry-After": "0"}
            )
        )
    ) as http:
        client = CanvasClient(
            bridge.registry.require("synthetic", True), "fake", bridge.settings, http
        )
        client.bind_usage(bridge, "fictional")
        assert (await client.one(Endpoint.PROFILE))["id"] == 1
    report = bridge.usage.report()
    assert report["settled"] == 1 and report["uncertain"] == 2


async def test_permission_403_is_never_retried(bridge):
    from canvas_bridge.canvas import CanvasClient
    from canvas_bridge.policy import Endpoint

    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(1) or httpx.Response(403))
    ) as http:
        client = CanvasClient(
            bridge.registry.require("synthetic", True), "fake", bridge.settings, http
        )
        client.bind_usage(bridge, "fictional")
        with pytest.raises(DomainError) as exc:
            await client.one(Endpoint.PROFILE)
        assert exc.value.reason_code == "RESOURCE_PERMISSION_DENIED"
    assert len(calls) == 1 and bridge.usage.report()["uncertain"] == 1


async def test_cache_coalesces_10_callers_and_revocation_blocks_hit():
    cache, calls, allowed = AuthorizedCache(), [], [True]

    def authorize():
        if not allowed[0]:
            raise DomainError("permission_denied", "revoked")

    async def fetch(validators):
        calls.append(validators)
        await asyncio.sleep(0.01)
        return {"assignment": "fictional"}, None, {"etag": "v1"}

    results = await asyncio.gather(
        *(cache.get("owner-epoch-resource", authorize, fetch, ttl=30) for _ in range(10))
    )
    assert len(calls) == 1 and len(results) == 10 and cache.coalesced == 9
    allowed[0] = False
    with pytest.raises(DomainError):
        await cache.get("owner-epoch-resource", authorize, fetch, ttl=30)
    allowed[0] = True
    await cache.get("other-owner-epoch-resource", authorize, fetch, ttl=30)
    assert len(calls) == 2


async def test_conditional_cache_validation_still_invokes_transport():
    now = [0]
    cache, calls = AuthorizedCache(clock=lambda: now[0]), []

    async def fetch(validators):
        calls.append(validators)
        return (None if validators else {"id": 1}), None, {"etag": "v1"}

    await cache.get("key", lambda: None, fetch, ttl=1)
    now[0] = 2
    value, provenance = await cache.get("key", lambda: None, fetch, ttl=1)
    assert len(calls) == 2 and calls[1] == {"If-None-Match": "v1"}
    assert value[0] == {"id": 1} and provenance["source"] == "conditional_revalidation"


def test_ledger_never_stores_sensitive_context(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    usage = UsageBinding(
        governor,
        b"fictional-hmac-key",
        owner="student@example.invalid",
        tenant="Private University",
        token="secret-fake-token",
        mode="offline_synthetic",
    )
    _, context, _, _ = usage("GET", "https://canvas.invalid/api/v1/courses/123/assignments/456")
    spend(governor, context)
    with ledger.connect() as db:
        data = json.dumps([dict(r) for r in db.execute(select(m.attempts)).mappings()])
    assert all(
        value not in data
        for value in ("student@", "Private University", "secret-fake-token", "/courses/123")
    )
