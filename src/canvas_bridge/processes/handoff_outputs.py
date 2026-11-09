"""Optional exact-output adapter boundary. The default connector is local-only."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import effort_service as effort
from canvas_bridge.processes import handoff_service as handoff
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.readiness import Digest
from canvas_bridge.processes.state import failure


class Receipt(Model):
    operation_id: Ref
    content_hash: Digest
    destination_ref: Ref
    recipient_ids: tuple[Ref, ...] = Field(max_length=24)
    object_id: Ref
    revision: Ref
    locator: Ref | None = None


class Adapter(Protocol):
    """A deployment must resolve actual destinations and verify exact-source recipient grants."""

    async def authorize(self, owner, kind, destination, recipients, sources) -> bool: ...
    async def lookup(self, owner, operation_id) -> Receipt | None: ...
    async def create_if_absent(self, owner, operation, payload) -> Receipt: ...


class Finish(effort.Mutation):
    operation_id: Ref
    state: Literal["confirmed", "uncertain", "conflict"]
    receipt: Receipt | None
    reconciled_existing: bool
    attempt_id: Ref


def exported(data, packet_id, output_id):
    row = next(
        (
            r
            for r in data.get("handoff_outputs", [])
            if (r["output_id"], r["packet_id"]) == (output_id, packet_id)
        ),
        None,
    )
    if not row:
        failure("HANDOFF_OUTPUT_UNAVAILABLE")
    return row


def find(data, opid):
    return next((o for o in data.get("handoff_operations", []) if o["operation_id"] == opid), None)


async def operate(service, owner, req):
    record, journal = await effort.authorize(service, owner, req.record_id)
    history = handoff.packets(journal.data if journal else {}, record.id, req.handoff_id)
    p = handoff.select(history, req.packet_id)
    recipients = tuple(sorted(req.recipient_ids))
    if (
        req.kind == "delivery"
        and (list(recipients) != p["responsibility"]["recipient_ids"] or not recipients)
    ) or (req.kind == "downloadable_artifact" and recipients):
        failure("HANDOFF_DESTINATION_SCOPE")
    output = exported(journal.data, p["packet_id"], req.output_id)
    opid = fingerprint(
        [record.id, p["packet_id"], req.output_id, req.kind, req.destination_ref, recipients]
    )
    adapter = getattr(service, "handoff_output_adapter", None)
    if adapter is None:
        failure("HANDOFF_ADAPTER_UNAVAILABLE")
    if not await adapter.authorize(
        owner, req.kind, req.destination_ref, recipients, journal.sources
    ):
        failure("HANDOFF_DESTINATION_SCOPE")

    def begin(data, now):
        current = handoff.select(handoff.packets(data, record.id, req.handoff_id))
        old = find(data, opid)
        if old and req.expected_destination_revision != old.get("expected_destination_revision"):
            failure("HANDOFF_OUTPUT_CONFLICT")
        if old and old["status"] == "confirmed":
            return
        if req.reconcile_only and not old:
            failure("HANDOFF_OUTPUT_UNAVAILABLE")
        if not req.reconcile_only:
            view = handoff.render(data, record, p, now, current["packet_id"] == p["packet_id"])
            if not req.confirmed:
                failure("PROCESS_CONFIRMATION_REQUIRED")
            if not view["current_basis"]:
                failure("HANDOFF_BASIS_CHANGED")
            if req.kind == "delivery" and (
                view["next_action_state"] == "needs_identity"
                or view["condition_states"]["transfer"] != "ready"
            ):
                failure("HANDOFF_DESTINATION_SCOPE")
        if not old:
            ops = data.setdefault("handoff_operations", [])
            if len(ops) >= 100:
                failure("PROCESS_STORAGE_BUDGET")
            old = dict(
                operation_id=opid,
                packet_id=p["packet_id"],
                output_id=req.output_id,
                output_kind=req.kind,
                expected_destination_revision=req.expected_destination_revision,
                semantic_basis_id=p["semantic_basis_id"],
                packet_revision=p["packet_revision"],
                expected_work_revision=record.revision,
                destination_ref=req.destination_ref,
                recipient_ids=list(recipients),
                content_hash=output["content_hash"],
                attempts=[],
                created_at=now.isoformat(),
            )
            ops.append(old)
        if old.get("status") == "conflict":
            failure("HANDOFF_OUTPUT_CONFLICT")
        if len(old["attempts"]) >= 20:
            failure("PROCESS_STORAGE_BUDGET")
        old.update(status="issued", updated_at=now.isoformat())
        old["attempts"].append(
            dict(
                attempt_id=fingerprint([opid, req.idempotency_key]),
                started_at=now.isoformat(),
                state="issued",
            )
        )

    intent = effort.mutate(service, owner, record, req, begin)
    record, journal = await effort.authorize(service, owner, req.record_id)
    op = find(journal.data, opid)
    if op["status"] == "confirmed":
        return Result(
            summary="Retrieved confirmed output receipt.",
            data=dict(
                operation_id=opid,
                status="confirmed",
                receipt=op["receipt"],
                journal_revision=journal.revision,
            ),
            sources=service.citations(owner, journal.sources),
        )
    receipt = None
    recovered = False
    state = "uncertain"
    try:
        receipt = await adapter.lookup(owner, opid)
        recovered = receipt is not None
        if receipt is None and not req.reconcile_only:
            if intent["revision"] != journal.revision or req.work_revision != record.revision:
                failure("HANDOFF_BASIS_CHANGED")
            if not await adapter.authorize(
                owner, req.kind, req.destination_ref, recipients, journal.sources
            ):
                failure("HANDOFF_DESTINATION_SCOPE")
            receipt = await adapter.create_if_absent(owner, op, output["payload"])
        if receipt is not None:
            receipt = Receipt.model_validate(receipt)
            state = (
                "confirmed"
                if (
                    receipt.operation_id,
                    receipt.content_hash,
                    receipt.destination_ref,
                    sorted(receipt.recipient_ids),
                )
                == (opid, output["content_hash"], req.destination_ref, list(recipients))
                and (req.kind != "downloadable_artifact" or receipt.locator)
                else "conflict"
            )
    except (TimeoutError, ConnectionError):
        pass
    final = Finish(
        record_id=record.id,
        work_revision=record.revision,
        journal_revision=journal.revision,
        idempotency_key=fingerprint([req.idempotency_key, "finish", state]),
        operation_id=opid,
        state=state,
        receipt=receipt,
        reconciled_existing=recovered,
        attempt_id=fingerprint([opid, req.idempotency_key]),
    )

    def finish(data, now):
        stored = find(data, opid)
        if stored["status"] == "confirmed":
            return
        attempt = next(a for a in stored["attempts"] if a["attempt_id"] == final.attempt_id)
        attempt.update(state=state, reconciled_existing=recovered, known_at=now.isoformat())
        stored.update(status=state, updated_at=now.isoformat())
        if state == "confirmed":
            stored["receipt"] = receipt.model_dump(mode="json")

    try:
        result = effort.mutate(service, owner, record, final, finish)
    except DomainError as exc:
        if exc.reason_code not in {"PROCESS_REVISION_MISMATCH", "PROCESS_IDEMPOTENCY_CONFLICT"}:
            raise
        # A retry can confirm the same provider effect while the original reply is in flight.
        record, journal = await effort.authorize(service, owner, req.record_id)
        saved = find(journal.data, opid)
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
                operation_id=opid,
                status="confirmed",
                receipt=saved["receipt"],
                journal_revision=journal.revision,
            ),
            sources=service.citations(owner, journal.sources),
        )
    return Result(
        summary="Recorded the exact output operation outcome.",
        data=result
        | dict(
            operation_id=opid,
            status=state,
            receipt=receipt.model_dump(mode="json") if state == "confirmed" else None,
        ),
        sources=service.citations(owner, journal.sources),
    )


async def observe(service, owner, req):
    record, _ = await effort.authorize(service, owner, req.record_id)
    handoff.verify_anchor(service, owner, record, req.evidence)

    def save(data, now):
        p = handoff.select(handoff.packets(data, record.id, req.handoff_id), req.packet_id)
        output = exported(data, p["packet_id"], req.output_id)
        if (
            req.content_hash != output["content_hash"]
            or sorted(req.recipient_ids) != p["responsibility"]["recipient_ids"]
        ):
            failure("HANDOFF_DESTINATION_SCOPE")
        if req.observed_at > now or req.observed_at < datetime.fromisoformat(output["known_at"]):
            failure("HANDOFF_RESPONSE_TIME")
        reports = data.setdefault("handoff_delivery_reports", [])
        r = dict(
            packet_id=p["packet_id"],
            output_id=req.output_id,
            receipt_ref=req.receipt_ref,
            destination_ref=req.destination_ref,
            recipient_ids=sorted(req.recipient_ids),
            content_hash=req.content_hash,
            observed_at=req.observed_at.isoformat(),
            evidence_basis="supplied_receipt",
            recorded_by=fingerprint(owner),
        )
        prior = next((row for row in reports if row["receipt_ref"] == req.receipt_ref), None)
        if prior:
            if any(prior[k] != v for k, v in r.items()):
                failure("HANDOFF_OUTPUT_CONFLICT")
        else:
            if len(reports) >= 100:
                failure("PROCESS_STORAGE_BUDGET")
            reports.append(r | dict(known_at=now.isoformat()))

    return Result(
        summary="Recorded the supplied delivery evidence.",
        data=effort.mutate(service, owner, record, req, save),
    )
