"""Recovery for study-calendar and reservation effects from an explicitly configured adapter.

Adapters implement authoritative lookup by logical operation ID and conditional, idempotent
apply. Credentials, provider endpoints and productive capabilities never come from tool inputs.
"""

from typing import Literal, Protocol

from pydantic import Field

from canvas_bridge.calendar_sync import CalendarContext
from canvas_bridge.domain import DomainError, Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import effort_service as effort
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.state import failure


class EffectReceipt(Model):
    operation_id: Ref
    payload_hash: Ref
    object_id: Ref
    provider_revision: Ref
    status: Literal["confirmed", "conflict"]


class Provider(Protocol):
    def supports(self, kind: str, resource_id: str | None, action: str) -> bool: ...
    async def lookup(self, owner: str, operation_id: str) -> EffectReceipt | None: ...
    async def apply(self, owner: str, operation: dict) -> EffectReceipt:
        """Atomically enforce provider-held expected bases, object revision, capacity and operation idempotency."""
        ...


class Apply(effort.Mutation):
    process_id: Ref
    generation_id: Ref
    operation_id: Ref
    confirmed: bool


class Finalize(effort.Mutation):
    generation_id: Ref
    operation_id: Ref
    receipt: EffectReceipt | None
    state: Literal["confirmed", "conflict", "uncertain"]
    reconciled: bool


def resource_bases(g, step_id):
    resources = {a["resource_id"] for a in g["allocations"] if a["step_id"] == step_id}
    selected = [r for r in g["inventory"]["resources"] if r["id"] in resources]
    calendars = {
        r[k]
        for r in selected
        for k in ("access_calendar_ref", "run_calendar_ref", "occupancy_calendar_ref")
    }
    return dict(
        work_episode=g["work_episode_id"],
        process_revision=g["process"]["revision"],
        constraint_version=g["constraint_version"],
        resources=[dict(id=r["id"], revision=r["revision"]) for r in selected],
        calendars=[
            dict(id=c["id"], revision=c["revision"])
            for c in g["inventory"]["calendars"]
            if c["id"] in calendars
        ],
        reservations=[
            dict(resource_id=r["id"], id=b["id"], revision=b["revision"])
            for r in selected
            for b in r["reservations"]
        ],
    )


def intents(g, history, provider):
    desired = {}
    for a in g["allocations"]:
        if a["booking_required"]:
            desired["reservation", fingerprint([a["allocation_id"], a["resource_id"]])] = dict(
                allocation_id=a["allocation_id"],
                step_id=a["step_id"],
                resource_id=a["resource_id"],
                unit=a["unit"],
                quantity=a["quantity"],
                start_at=a["start_at"],
                end_at=a["end_at"],
                resource_ref=a["resource_ref"],
                covered_booking_id=a["covered_booking_id"],
            )
    phase_d = {b["step_id"] + "/" + b["phase"]: b["block_id"] for b in g.get("study_blocks", [])}
    for b in g["result"].get("blocks", []):
        key = fingerprint([g["process"]["id"], b["episode_id"], b["id"]])
        desired["calendar", key] = dict(
            step_id=b["step_id"],
            block_id=b["id"],
            study_block_id=phase_d.get(b["id"]),
            episode_id=b["episode_id"],
            start_at=b["start_at"],
            end_at=b["end_at"],
        )
    confirmed = {}
    for prior in history:
        if (prior["record_id"], prior["process"]["id"]) != (g["record_id"], g["process"]["id"]):
            continue
        for o in prior["operations"]:
            if o["status"] == "confirmed":
                key = (o["kind"], o["logical_id"])
                if o["after"] is None:
                    confirmed.pop(key, None)
                else:
                    confirmed[key] = o
    result = []
    # Unresolved or conflicting schedules never authorize deletion of previous effects.
    keys = set(desired)
    if g["result"]["status"] in {"feasible", "provisional"} and not g["result"].get(
        "hard_unknowns"
    ):
        keys.update(confirmed)
    for kind, key in sorted(keys):
        new = desired.get((kind, key))
        old = confirmed.get((kind, key))
        before = old["after"] if old else None
        resource = (new or before).get("resource_id")
        action = "create" if old is None else "remove" if new is None else "update"
        status = (
            "pending"
            if provider and provider.supports(kind, resource, action)
            else "observation_only"
        )
        op = dict(
            kind=kind,
            logical_id=key,
            step_id=(new or before)["step_id"],
            resource_id=resource,
            expected_bases=resource_bases(g, (new or before)["step_id"]),
            expected_provider_revision=old["receipt"]["provider_revision"] if old else None,
            object_id=old["receipt"]["object_id"] if old else None,
            before=before,
            after=new,
            dependencies=[],
            attempts=[],
            action=action,
        )
        op.update(
            operation_id=fingerprint([g["generation_id"], kind, key]),
            payload_hash=fingerprint(op),
            status=status,
            marker="canvas-resource-study:"
            + fingerprint([g["owner_key"], g["record_id"], key])[:40]
            if kind == "calendar"
            else None,
        )
        if kind == "calendar" and new and new.get("study_block_id") and not old:
            # Phase D owns this logical event. Never create a second provider event.
            op.update(status="phase_d_owned", action="review_existing_study_event")
        elif before == new:
            op.update(status="confirmed", action="retain", receipt=old["receipt"])
        elif new and kind == "reservation" and new.get("covered_booking_id"):
            op.update(status="supplied_confirmation", action="observe")
        result.append(op)
    for op in result:
        if op["kind"] == "calendar" and op["after"]:
            op["dependencies"] = [
                dep["operation_id"]
                for dep in result
                if dep["kind"] == "reservation" and dep["after"] and dep["step_id"] == op["step_id"]
            ]
        if op["kind"] == "reservation" and op["after"] is None:
            op["dependencies"] = [
                dep["operation_id"]
                for dep in result
                if dep["step_id"] == op["step_id"]
                and (
                    (dep["kind"] == "calendar" and dep["after"] is None)
                    or (dep["kind"] == "reservation" and dep["after"])
                )
            ]
    return result


def locate(data, record_id, req):
    from canvas_bridge.processes.resource_service import previous

    generation = previous(data, record_id, req.process_id)
    if not generation or generation["generation_id"] != req.generation_id:
        failure("RESOURCE_BASE_CHANGED")
    op = next((o for o in generation["operations"] if o["operation_id"] == req.operation_id), None)
    if op is None:
        failure("PLAN_OPERATION_UNKNOWN")
    return generation, op


async def apply(service, owner, req):
    from types import SimpleNamespace

    from canvas_bridge.processes import study_plan
    from canvas_bridge.processes.resource_service import bind_forecast

    record, _ = await effort.authorize(service, owner, req.record_id)
    provider = getattr(service, "resource_provider", None)

    def begin(data, now):
        g, op = locate(data, record.id, req)
        if op["status"] in {"confirmed", "supplied_confirmation"}:
            return
        if op["status"] == "phase_d_owned":
            failure("RESOURCE_STUDY_BINDING_REQUIRED")
        if not provider or not provider.supports(op["kind"], op["resource_id"], op["action"]):
            failure("RESOURCE_OBSERVATION_ONLY")
        if not req.confirmed:
            failure("PROCESS_CONFIRMATION_REQUIRED")
        if op["status"] not in {"pending", "uncertain", "issued", "observation_only"}:
            failure("RESOURCE_BASE_CHANGED")
        if op["status"] not in {"uncertain", "issued"}:
            bind_forecast(data, SimpleNamespace(forecast_id=g["forecast_id"]), record, now)
            study = study_plan.latest(data, record.id)
            if (
                record.revision != g["work_revision"]
                or (study and study["generation_id"]) != g["study_generation"]
            ):
                failure("RESOURCE_BASE_CHANGED")
            if g["result"]["status"] not in {"feasible", "provisional"} or g["result"].get(
                "hard_unknowns"
            ):
                failure("RESOURCE_BASE_CHANGED")
        statuses = {o["operation_id"]: o["status"] for o in g["operations"]}
        if any(
            statuses[key] not in {"confirmed", "supplied_confirmation"}
            for key in op["dependencies"]
        ):
            failure("RESOURCE_DEPENDENCY_PENDING")
        if len(op["attempts"]) >= 20:
            failure("PROCESS_STORAGE_BUDGET")
        op["attempts"].append(
            dict(
                attempt_id=fingerprint([req.operation_id, req.idempotency_key]),
                started_at=now.isoformat(),
            )
        )
        op["status"] = "issued"

    intent = effort.mutate(service, owner, record, req, begin)
    record, journal = await effort.authorize(service, owner, req.record_id)
    g, op = locate(journal.data, record.id, req)
    if op["status"] in {"confirmed", "supplied_confirmation", "conflict"}:
        return Result(
            summary="Retrieved saved operation status.",
            data=dict(
                operation_id=op["operation_id"],
                status=op["status"],
                journal_revision=journal.revision,
            ),
            sources=service.citations(owner, journal.sources),
        )
    if not provider:
        failure("RESOURCE_OBSERVATION_ONLY")
    # If another request advanced the journal after preparation, require a fresh
    # request/revision. An already committed provider effect is still discoverable.
    receipt = None
    recovered = False
    state = "uncertain"
    try:
        receipt = await provider.lookup(owner, op["operation_id"])
        recovered = receipt is not None
        if not receipt:
            if journal.revision != intent["revision"] or record.revision != g["work_revision"]:
                failure("RESOURCE_BASE_CHANGED")
            bind_forecast(
                journal.data,
                SimpleNamespace(forecast_id=g["forecast_id"]),
                record,
                service.repository.clock(),
            )
            study = study_plan.latest(journal.data, record.id)
            if (study and study["generation_id"]) != g["study_generation"]:
                failure("RESOURCE_BASE_CHANGED")
            receipt = await provider.apply(owner, op)
        receipt = EffectReceipt.model_validate(receipt)
        state = (
            receipt.status
            if (receipt.operation_id, receipt.payload_hash)
            == (op["operation_id"], op["payload_hash"])
            else "conflict"
        )
    except (TimeoutError, ConnectionError):
        pass
    final = Finalize(
        record_id=record.id,
        work_revision=record.revision,
        journal_revision=journal.revision,
        idempotency_key=fingerprint([req.idempotency_key, "finish", state]),
        generation_id=req.generation_id,
        operation_id=req.operation_id,
        state=state,
        receipt=receipt,
        reconciled=recovered,
    )

    def finish(data, now):
        _, updated = locate(data, record.id, req)
        updated["status"] = state
        updated["attempts"][-1].update(
            status=state, reconciled_existing=recovered, known_at=now.isoformat()
        )
        if receipt:
            updated["receipt"] = receipt.model_dump(mode="json")

    try:
        result = effort.mutate(service, owner, record, final, finish)
    except DomainError as exc:
        if exc.reason_code not in {"PROCESS_REVISION_MISMATCH", "PROCESS_IDEMPOTENCY_CONFLICT"}:
            raise
        # A retry can confirm the same provider effect while the original reply is in flight.
        record, journal = await effort.authorize(service, owner, req.record_id)
        _, saved = locate(journal.data, record.id, req)
        if (
            not saved
            or saved["status"] != "confirmed"
            or state == "conflict"
            or (receipt is not None and receipt.model_dump(mode="json") != saved["receipt"])
        ):
            raise
        return Result(
            summary="Retrieved concurrently confirmed provider receipt.",
            data=dict(
                operation_id=req.operation_id,
                status="confirmed",
                receipt=saved["receipt"],
                journal_revision=journal.revision,
            ),
            sources=service.citations(owner, journal.sources),
        )
    return Result(
        summary="Saved provider operation outcome.",
        data=result | dict(operation_id=op["operation_id"], status=state),
        sources=service.citations(owner, journal.sources),
    )


class Compensation(effort.Mutation):
    process_id: Ref
    generation_id: Ref
    operation_ids: tuple[Ref, ...] = Field(min_length=1, max_length=64)


async def compensate(service, owner, req):
    """Prepare scoped conditional inverses of confirmed provider effects."""
    from copy import deepcopy

    from canvas_bridge.processes.resource_service import previous

    record, _ = await effort.authorize(service, owner, req.record_id)

    def prepare(data, now):
        current = previous(data, record.id, req.process_id)
        if (
            not current
            or current["generation_id"] != req.generation_id
            or record.revision != current["work_revision"]
        ):
            failure("RESOURCE_BASE_CHANGED")
        if any(
            o["status"] in {"issued", "uncertain", "host_issued"} for o in current["operations"]
        ):
            failure("PLAN_OPERATION_UNRESOLVED")
        by_id = {o["operation_id"]: o for o in current["operations"]}
        selected = set(req.operation_ids)
        if len(selected) != len(req.operation_ids) or not selected <= by_id.keys():
            failure("PLAN_OPERATION_UNKNOWN")
        if any(
            o["status"] == "confirmed"
            and set(o["dependencies"]) & selected
            and o["operation_id"] not in selected
            for o in by_id.values()
        ):
            failure("RESOURCE_DEPENDENCY_PENDING")
        snapshot = deepcopy(current)
        key = fingerprint([record.id, req.idempotency_key])
        replacements = {ident: fingerprint([key, ident]) for ident in selected}
        for o in snapshot["operations"]:
            ident = o["operation_id"]
            if ident not in selected:
                if (
                    o["status"] not in {"confirmed", "supplied_confirmation"}
                    and set(o["dependencies"]) & selected
                ):
                    o["status"] = "superseded"
                continue
            if o["status"] != "confirmed" or o["action"] == "retain" or o.get("compensates"):
                failure("RESOURCE_BASE_CHANGED")
            receipt = o.pop("receipt")
            o.update(
                compensates=ident,
                operation_id=replacements[ident],
                expected_provider_revision=receipt["provider_revision"],
                object_id=receipt["object_id"],
                before=o["after"],
                after=o["before"],
                attempts=[],
                status="pending",
                action={"create": "remove", "update": "update", "remove": "create"}[o["action"]],
                dependencies=[
                    replacements[successor]
                    for successor in selected
                    if ident in by_id[successor]["dependencies"]
                ],
            )
            o["payload_hash"] = fingerprint(
                [
                    o["logical_id"],
                    o["expected_provider_revision"],
                    o["before"],
                    o["after"],
                    o["dependencies"],
                ]
            )
        snapshot.update(
            generation_id=key,
            compensates=current["generation_id"],
            trigger="compensate_provider_effects",
            known_at=now.isoformat(),
            journal_revision=req.journal_revision + 1,
        )
        for row in snapshot["handoff"]:
            row.update(
                handoff_basis_id=fingerprint([key, row["step_id"]]),
                plan_id=key,
                plan_revision=str(req.journal_revision + 1),
            )
        if len(data["resource_generations"]) >= 32:
            failure("PROCESS_STORAGE_BUDGET")
        data["resource_generations"].append(snapshot)

    return Result(
        summary="Saved a compensating generation. Apply its conditional inverses individually.",
        data=effort.mutate(service, owner, record, req, prepare),
    )


class CalendarReadback(effort.Mutation):
    process_id: Ref
    generation_id: Ref
    operation_id: Ref
    calendar: CalendarContext
    prepare_confirmed_action: bool = False


async def check_calendar(service, owner, req):
    """Use the existing host calendar's complete marker search and exact readback rules."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from canvas_bridge.processes import study_plan
    from canvas_bridge.processes.resource_service import bind_forecast

    record, _ = await effort.authorize(service, owner, req.record_id)

    def update(data, now):
        g, op = locate(data, record.id, req)
        if op["kind"] != "calendar" or op["status"] == "phase_d_owned":
            failure("PLAN_OPERATION_UNKNOWN")
        if op["status"] == "confirmed":
            return
        if op["status"] not in {"pending", "observation_only", "host_issued"}:
            failure("RESOURCE_BASE_CHANGED")
        c = req.calendar
        if (
            not c.mapping_search_complete
            or not c.pagination_complete
            or not c.availability_complete
            or not timedelta(seconds=-30) <= now - c.retrieved_at <= timedelta(minutes=5)
        ):
            failure("PLAN_CALENDAR_STALE")
        if op.setdefault("calendar_id", c.calendar_id) != c.calendar_id:
            failure("PLAN_CALENDAR_SCOPE")
        forecast = next(f for f in data["forecasts"] if f["forecast_id"] == g["forecast_id"])
        marker = op["marker"]

        def block(raw):
            if not raw:
                return None
            return study_plan.Block(
                block_id=op["logical_id"],
                task_id=forecast["work_id"],
                episode_id=forecast["episode_id"],
                start=raw["start_at"],
                end=raw["end_at"],
            ).model_dump(mode="json")

        proxy = dict(
            marker=marker,
            status="issued" if op["status"] == "host_issued" else "pending",
            before=block(op["before"]),
            after=block(op["after"]),
            attempts=len(op["attempts"]),
            expected_event=op.get("expected_event"),
            issued_at=op.get("issued_at"),
            checked_at=op.get("checked_at"),
        )
        stale = record.revision != g["work_revision"] or any(
            not c.window_start
            <= datetime.fromisoformat(b["start"])
            < datetime.fromisoformat(b["end"])
            <= c.window_end
            or datetime.fromisoformat(b["start"]) < now
            for b in (proxy["before"], proxy["after"])
            if b
        )
        if req.prepare_confirmed_action:
            bind_forecast(data, SimpleNamespace(forecast_id=g["forecast_id"]), record, now)
            study = study_plan.latest(data, record.id)
            stale |= (study and study["generation_id"]) != g["study_generation"]
            states = {o["operation_id"]: o["status"] for o in g["operations"]}
            if any(
                states[d] not in {"confirmed", "supplied_confirmation"} for d in op["dependencies"]
            ):
                failure("RESOURCE_DEPENDENCY_PENDING")
            if op["before"] and op.get("expected_provider_revision"):
                current = next(
                    (e for e in c.events if e.bridge_marker == marker and e.status != "cancelled"),
                    None,
                )
                if proxy["status"] != "issued" and (
                    not current
                    or current.version != op["expected_provider_revision"]
                    or current.id != op["object_id"]
                ):
                    op["status"] = "conflict"
                    return
        study_plan.reconcile_one(proxy, c, now, stale=stale, dispatch=req.prepare_confirmed_action)
        op.update(
            marker=marker,
            checked_at=c.retrieved_at.isoformat(),
            expected_event=proxy.get("expected_event"),
        )
        if proxy["status"] == "observed":
            event = proxy.get("observed_event")
            op.update(
                status="confirmed",
                receipt=dict(
                    operation_id=op["operation_id"],
                    payload_hash=op["payload_hash"],
                    object_id=event["id"] if event else op["object_id"],
                    provider_revision=event["version"]
                    if event and event.get("version")
                    else fingerprint([event, op["operation_id"]]),
                    status="confirmed",
                    basis="host_calendar_readback",
                ),
            )
        elif proxy["status"] == "issued":
            if proxy["attempts"] > len(op["attempts"]):
                op["attempts"].append(
                    dict(
                        attempt_id=fingerprint([req.operation_id, req.idempotency_key]),
                        started_at=now.isoformat(),
                    )
                )
            op.update(status="host_issued", issued_at=proxy["issued_at"])
        elif proxy["status"] != "pending":
            op["status"] = proxy["status"]

    return Result(
        summary="Recorded host calendar preconditions and readback.",
        data=effort.mutate(service, owner, record, req, update),
    )
