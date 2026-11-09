"""Versioned artifact handoffs in the existing owner-locked academic process journal."""

import hashlib
import json
from datetime import datetime

from canvas_bridge.domain import Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import (
    effort_service as effort,
)
from canvas_bridge.processes import (
    handoff_projection as hp,
)
from canvas_bridge.processes import (
    readiness as rd,
)
from canvas_bridge.processes.requests import ProcessScope
from canvas_bridge.processes.state import failure


def packets(data, record_id, handoff_id):
    return [
        p
        for p in data.get("handoff_packets", [])
        if p["assignment_id"] == record_id and p["handoff_id"] == handoff_id
    ]


def select(history, packet_id=None):
    row = next(
        (p for p in reversed(history) if packet_id is None or p["packet_id"] == packet_id), None
    )
    if not row:
        failure("HANDOFF_PACKET_UNAVAILABLE")
    return row


def verify_anchor(service, owner, record, anchor):
    if not anchor:
        return
    bindings = [rd.Binding.model_validate(b) for b in record.data["bindings"]]
    docs = tuple(b.document_id for b in bindings if b.document_id)
    entries = service.load(
        owner,
        ProcessScope(document_ids=docs, local_course=record.scope.course, term=record.scope.term),
    )
    rd.check_anchor(anchor, rd.bind(entries, bindings), entries)


def correspondence(previous, current, record):
    """Only the committed C comparison can establish equivalence between different bytes."""
    if previous is None:
        return "initial", []
    before, after = previous["semantic_basis"], current["semantic_basis"]
    if previous["semantic_basis_id"] == current["semantic_basis_id"]:
        return "current_exact", previous["equivalent_basis_ids"]
    stable = (
        "assignment_id",
        "work_episode_id",
        "responsibility",
        "action",
        "conditions",
        "governing_conditions",
        "process_step",
        "process_input_version",
        "input_versions",
        "inventory_complete",
    )
    if any(before[k] != after[k] for k in stable):
        return "material_change", []
    if (
        before["artifact"]["logical_artifact_id"] != after["artifact"]["logical_artifact_id"]
        or before["artifact"]["scope_locator"] != after["artifact"]["scope_locator"]
    ):
        return "material_change", []
    changes = record.data.get("change_report", {})
    if changes.get("applied_revision") != record.revision or previous[
        "work_revision"
    ] > changes.get("base_revision", 0):
        return "unresolved", []
    comparisons = {c["logical_id"]: c for c in changes["comparisons"]}

    def equivalent(source, start, end):
        if start == end:
            return bool(start)
        c = comparisons.get(source, {})
        return bool(
            c.get("before_hash") == start
            and c.get("after_hash") == end
            and c.get("comparison_coverage") == "complete"
            and c.get("change_class") == "content_equivalent"
            and c.get("proof_id")
        )

    if not equivalent(
        before["artifact"]["logical_artifact_id"],
        before["artifact"]["artifact_version"],
        after["artifact"]["artifact_version"],
    ):
        return (
            "unresolved"
            if any(c.get("comparison_coverage") != "complete" for c in comparisons.values())
            else "material_change"
        ), []
    old = {r["requirement_id"]: r for r in before["requirements"]}
    proofs = {r["requirement_id"]: r.get("proof_id") for r in current["assessment"]["criteria"]}
    if set(old) != set(proofs):
        return "material_change", []
    for row in after["requirements"]:
        prior = old[row["requirement_id"]]
        if {k: v for k, v in row.items() if k != "dependencies"} != {
            k: v for k, v in prior.items() if k != "dependencies"
        }:
            return "material_change", []
        if (
            not proofs[row["requirement_id"]]
            or prior["dependencies"].keys() != row["dependencies"].keys()
            or not all(
                equivalent(k, v, row["dependencies"][k]) for k, v in prior["dependencies"].items()
            )
        ):
            return "unresolved", []
    return "carried_equivalent", sorted(
        {previous["semantic_basis_id"], *previous["equivalent_basis_ids"]}
    )


def responses(data, packet, cutoff):
    selected = {}
    for row in data.get("handoff_responses", []):
        if (
            row["assignment_id"] == packet["assignment_id"]
            and row["handoff_id"] == packet["handoff_id"]
            and datetime.fromisoformat(row["known_at"]) <= cutoff
        ):
            old = selected.get(row["observation_id"])
            if not old or row["revision"] > old["revision"]:
                selected[row["observation_id"]] = row
    reviewed = []
    for r in selected.values():
        if r["retracted"]:
            state = "historical"
        elif not r["actor_supported"]:
            state = "unresolved"
        elif not packet.get("current_basis", True):
            state = "unresolved"
        elif r["original_semantic_basis_id"] == packet["semantic_basis_id"]:
            state = "current_exact"
        elif r["original_semantic_basis_id"] in packet["equivalent_basis_ids"]:
            state = "carried_equivalent"
        elif r["original_semantic_basis_id"] in packet.get("unresolved_basis_ids", []):
            state = "unresolved"
        else:
            state = "historical"
        reviewed.append(r | dict(applicability=state))
    members = []
    for member in packet["responsibility"]["recipient_ids"]:
        current = [
            r
            for r in reviewed
            if r["acknowledged_by"] == member
            and r["applicability"] in {"current_exact", "carried_equivalent"}
        ]
        superseded = {r["supersedes"] for r in current if r.get("supersedes")}
        current = [r for r in current if r["observation_id"] not in superseded]
        states = {r["state"] for r in current}
        members.append(
            dict(
                member_id=member,
                state="conflict" if len(states) > 1 else next(iter(states), "none"),
                observation_ids=[r["observation_id"] for r in current],
            )
        )
    states = {m["state"] for m in members}
    return dict(
        responses=reviewed,
        ack_by_member=members,
        current_ack_state="conflict"
        if "conflict" in states
        else "partial"
        if len(states) > 1
        else next(iter(states), "none"),
    )


def append_packet(data, now, record, owner, req):
    history = packets(data, record.id, req.handoff_id)
    prev = history[-1] if history else None
    if (prev and prev["packet_id"]) != req.expected_packet:
        failure("HANDOFF_BASIS_CHANGED")
    work = hp.work_context(record, req.work_id, req.criterion_ids)
    role = req.responsibility.model_dump(mode="json")
    action = req.action.model_dump(mode="json")
    for k in ("prerequisite_ids", "acknowledgment_members"):
        action[k] = sorted(action[k])
    role["recipient_ids"].sort()
    role["members"].sort(key=lambda m: m["member_id"])
    link = req.process.model_dump(mode="json") if req.process else None
    declared = [c.model_dump(mode="json") for c in req.conditions]
    context = hp.context_for(data, record, work, link, declared, now)
    assessed = hp.assess(record, req.artifact_logical_id, req.criterion_ids)
    if (
        (req.expected_artifact_hash and req.expected_artifact_hash != assessed["artifact_version"])
        or (
            req.expected_requirement_revision
            and req.expected_requirement_revision != record.data["requirement_set_revision"]
        )
        or (req.expected_episode_id and req.expected_episode_id != work["work_episode_id"])
    ):
        failure("HANDOFF_BASIS_CHANGED")
    basis = hp.basis(record, assessed, work, role, action, context, link)
    for existing in history:
        for axis, key in (("responsibility", "assignment_ref"), ("action", "action_id")):
            old = existing["semantic_basis"][axis]
            new = basis[axis]
            if (old[key], old["revision"]) == (new[key], new["revision"]) and old != new:
                failure("HANDOFF_BASIS_CHANGED")
    packet = dict(
        handoff_id=req.handoff_id,
        assignment_id=record.id,
        work_revision=record.revision,
        work_id=req.work_id,
        criterion_ids=list(req.criterion_ids),
        **work,
        storage_principal_ref=fingerprint(owner),
        packet_id=fingerprint([record.id, req.handoff_id, req.idempotency_key]),
        packet_revision=len(history) + 1,
        transport_revision=len(history) + 1,
        semantic_basis=basis,
        semantic_basis_id=fingerprint(basis),
        saved_at=now.isoformat(),
        requirement_set_revision=record.data["requirement_set_revision"],
        responsibility=role,
        action=action,
        assessment=assessed,
        process_link=link,
        declared_conditions=declared,
        input_versions=basis["input_versions"],
        process_context=context,
        presentation_note=req.presentation_note,
        local_packet_state="saved",
    )
    packet["correspondence"], packet["equivalent_basis_ids"] = correspondence(prev, packet, record)
    packet["prior_packet_id"] = prev["packet_id"] if prev else None
    status = packet["correspondence"]
    packet["unresolved_basis_ids"] = (
        sorted(
            {
                prev["semantic_basis_id"],
                *prev["equivalent_basis_ids"],
                *prev.get("unresolved_basis_ids", []),
            }
        )
        if prev and status == "unresolved"
        else prev.get("unresolved_basis_ids", [])
        if prev and status in {"current_exact", "carried_equivalent"}
        else []
    )
    packet["changed_axes"] = [k for k in basis if prev and basis[k] != prev["semantic_basis"][k]]
    all_rows = data.setdefault("handoff_packets", [])
    if len(all_rows) >= 80:
        failure("PROCESS_STORAGE_BUDGET")
    all_rows.append(packet)

    return packet


async def prepare(service, owner, req):
    record, _ = await effort.authorize(service, owner, req.record_id)
    verify_anchor(service, owner, record, req.responsibility.evidence)
    for c in req.conditions:
        verify_anchor(service, owner, record, c.evidence)

    def update(data, now):
        p = append_packet(data, now, record, owner, req)
        doc = p["assessment"]["document_id"]
        if doc:
            p["assessment"]["filename"] = service.bridge.independent.require(owner, doc).content[
                "filename"
            ]

    receipt = effort.mutate(service, owner, record, req, update)
    return Result(
        summary="Saved the private handoff packet.",
        data=receipt
        | dict(packet_id=fingerprint([record.id, req.handoff_id, req.idempotency_key])),
    )


async def record_response(service, owner, req):
    record, _ = await effort.authorize(service, owner, req.record_id)
    verify_anchor(service, owner, record, req.evidence)

    def update(data, now):
        p = select(packets(data, record.id, req.handoff_id), req.packet_id)
        if req.observed_at > now or req.observed_at < datetime.fromisoformat(p["saved_at"]):
            failure("HANDOFF_RESPONSE_TIME")
        rows = data.setdefault("handoff_responses", [])
        history = [
            r for r in rows if (r["assignment_id"], r["handoff_id"]) == (record.id, req.handoff_id)
        ]
        versions = [r for r in history if r["observation_id"] == req.observation_id]
        if len(versions) != req.expected_observation_revision:
            failure("PROCESS_REVISION_MISMATCH")
        if versions and (versions[-1]["packet_id"], versions[-1]["acknowledged_by"]) != (
            req.packet_id,
            req.acknowledged_by,
        ):
            failure("HANDOFF_RESPONSE_SCOPE")
        if req.supersedes:
            older = next(
                (r for r in reversed(history) if r["observation_id"] == req.supersedes), None
            )
            if (
                not older
                or versions
                or req.supersedes == req.observation_id
                or (older["original_semantic_basis_id"], older["acknowledged_by"])
                != (p["semantic_basis_id"], req.acknowledged_by)
            ):
                failure("HANDOFF_RESPONSE_SCOPE")
        if len(rows) >= 400:
            failure("PROCESS_STORAGE_BUDGET")
        rows.append(
            dict(
                assignment_id=record.id,
                handoff_id=req.handoff_id,
                packet_id=req.packet_id,
                original_semantic_basis_id=p["semantic_basis_id"],
                observation_id=req.observation_id,
                revision=len(versions) + 1,
                acknowledged_by=req.acknowledged_by,
                recorded_by=fingerprint(owner),
                actor_supported=hp.identity_supported(p["responsibility"])
                and req.acknowledged_by in p["responsibility"]["recipient_ids"],
                state=req.state,
                evidence_basis=req.evidence_basis,
                evidence_ref=req.evidence_ref,
                evidence=req.evidence.model_dump(mode="json") if req.evidence else None,
                observed_at=req.observed_at.isoformat(),
                known_at=now.isoformat(),
                retracted=req.retracted,
                supersedes=req.supersedes or (versions[-1]["supersedes"] if versions else None),
            )
        )

    return Result(
        summary="Recorded the supplied response on its original packet.",
        data=effort.mutate(service, owner, record, req, update),
    )


def render(data, record, p, cutoff, latest, *, historical=False):
    context = p["process_context"]
    work = p
    consistent = not record.data.get("pending_change")
    if latest and not historical:
        if p["work_id"] and p["work_id"] not in {
            w["work_id"]
            for w in rd.project(record.data, record.data["requirements"])["remaining_work"]
        }:
            consistent = False
        else:
            work = hp.work_context(record, p["work_id"], p["criterion_ids"])
            context = hp.context_for(
                data, record, work, p["process_link"], p.get("declared_conditions", []), cutoff
            )
            selected = next(
                (
                    b
                    for b in record.data["bindings"]
                    if b["logical_id"] == p["assessment"]["logical_artifact_id"]
                    and b["role"] == "artifact"
                ),
                None,
            )
            if not selected:
                consistent = False
            else:
                assessment = hp.assess(record, selected["logical_id"], p["criterion_ids"])
                current = hp.basis(
                    record,
                    assessment,
                    work,
                    p["responsibility"],
                    p["action"],
                    context,
                    p["process_link"],
                )
                consistent = (
                    consistent
                    and fingerprint(current) == p["semantic_basis_id"]
                    and selected["document_id"] == p["assessment"]["document_id"]
                )
    packet = p | dict(
        current_basis=bool(latest and (historical or consistent)),
        process_context=context,
        personal_progress=work["personal_progress"],
    )
    result = responses(data, packet, cutoff)
    if not latest:
        # Preserve how observations bind to this archived subject, independently
        # of whether anything about a past packet authorizes current work.
        on_original = responses(data, p | dict(current_basis=True), cutoff)
        result["selected_packet_ack_state"] = on_original["current_ack_state"]
        result["selected_packet_ack_by_member"] = on_original["ack_by_member"]
        original = {r["observation_id"]: r["applicability"] for r in on_original["responses"]}
        for row in result["responses"]:
            row["selected_packet_applicability"] = original[row["observation_id"]]
            if row["selected_packet_applicability"] in {"current_exact", "carried_equivalent"}:
                row["applicability"] = "historical"
    action_state = hp.next_state(
        packet, {r["member_id"]: r["state"] for r in result["ack_by_member"]}
    )
    if action_state == "ready":
        next_step = packet["action"]["description"]
    elif action_state == "needs_identity":
        next_step = "Confirm the responsible contributor, intended recipients and action owner."
    elif action_state == "requires_rebase":
        next_step = "Prepare an updated packet from the current work and artifact."
    elif action_state == "waiting_ack":
        next_step = "Record the required response from the named recipient scope."
    else:
        next_step = next(
            (
                b["next_action"]
                for b in packet["process_context"]["blockers"]
                if b["state"] != "ready"
                and (
                    b["scope"] != "downstream_execution"
                    or packet["action"]["requires_process_context"]
                )
            ),
            None,
        )
        next_step = next_step or next(
            (
                r["next_step"]
                for r in packet["assessment"]["criteria"]
                if r["requirement_id"] in packet["action"]["prerequisite_ids"]
                and r.get("next_step")
            ),
            "Verify the required inputs and current criterion evidence.",
        )
    jobs = [
        j
        for j in data.get("handoff_outputs", [])
        if j["packet_id"] == p["packet_id"] and datetime.fromisoformat(j["known_at"]) <= cutoff
    ]
    ops = []
    for o in data.get("handoff_operations", []):
        if o["packet_id"] != p["packet_id"] or datetime.fromisoformat(o["created_at"]) > cutoff:
            continue
        attempts = [a for a in o["attempts"] if datetime.fromisoformat(a["started_at"]) <= cutoff]
        status = "issued"
        if (
            attempts
            and datetime.fromisoformat(attempts[-1].get("known_at", attempts[-1]["started_at"]))
            <= cutoff
        ):
            status = attempts[-1]["state"]
        ops.append(
            dict(
                operation_id=o["operation_id"],
                output_kind=o["output_kind"],
                status=status,
                destination_ref=o["destination_ref"],
                receipt=o.get("receipt") if status == "confirmed" else None,
                attempt_count=len(attempts),
            )
        )
    reported = [
        r
        for r in data.get("handoff_delivery_reports", [])
        if r["packet_id"] == p["packet_id"] and datetime.fromisoformat(r["known_at"]) <= cutoff
    ]
    older_ids = {
        r["packet_id"]
        for r in packets(data, record.id, p["handoff_id"])
        if r["packet_revision"] < p["packet_revision"]
    }
    outstanding = []
    for op in data.get("handoff_operations", []):
        if op["packet_id"] not in older_ids or datetime.fromisoformat(op["created_at"]) > cutoff:
            continue
        attempts = [a for a in op["attempts"] if datetime.fromisoformat(a["started_at"]) <= cutoff]
        if not attempts:
            continue
        last = attempts[-1]
        state = (
            last["state"]
            if datetime.fromisoformat(last.get("known_at", last["started_at"])) <= cutoff
            else "issued"
        )
        if state in {"issued", "uncertain"}:
            outstanding.append(
                dict(
                    operation_id=op["operation_id"],
                    packet_id=op["packet_id"],
                    output_id=op["output_id"],
                    output_kind=op["output_kind"],
                    destination_ref=op["destination_ref"],
                    recipient_ids=op["recipient_ids"],
                    status=state,
                    recovery_mode="lookup_only",
                )
            )
    delivery_states = {o["status"] for o in ops if o["output_kind"] == "delivery"}
    delivery = (
        "partially_confirmed"
        if "confirmed" in delivery_states and len(delivery_states) > 1
        else next(iter(delivery_states))
        if len(delivery_states) == 1
        else "outcome_unknown"
        if delivery_states
        else "reported_confirmed"
        if reported
        else "not_requested"
    )
    return (
        {k: v for k, v in packet.items() if k not in {"semantic_basis", "equivalent_basis_ids"}}
        | result
        | dict(
            artifact_readiness=p["assessment"]["artifact_readiness"],
            next_action_state=action_state,
            next_step=next_step,
            condition_states=hp.condition_states(
                packet["process_context"], p["action"], p["process_link"]
            ),
            response_cutoff=cutoff.isoformat(),
            response_revisions=[
                {
                    k: r[k]
                    for k in (
                        "observation_id",
                        "revision",
                        "packet_id",
                        "state",
                        "known_at",
                        "observed_at",
                        "retracted",
                    )
                }
                for r in data.get("handoff_responses", [])
                if r["assignment_id"] == p["assignment_id"]
                and r["handoff_id"] == p["handoff_id"]
                and datetime.fromisoformat(r["known_at"]) <= cutoff
            ],
            exports=[{k: v for k, v in j.items() if k != "payload"} for j in jobs],
            operations=ops,
            prior_unresolved_outputs=outstanding,
            export_state="available" if packet["current_basis"] else "requires_rebase",
            current_ack_count=sum(
                m["state"] not in {"none", "conflict"} for m in result["ack_by_member"]
            ),
            delivery_reports=reported,
            delivery_state=delivery,
            view_mode="as_of_saved_packet" if historical else "current" if latest else "historical",
        )
    )


async def view(service, owner, record_id, handoff_id, packet_id=None, as_of=None, output_id=None):
    record, journal = await effort.authorize(service, owner, record_id)
    now = service.repository.clock()
    cutoff = as_of or now
    if cutoff > now:
        failure("HANDOFF_RESPONSE_TIME")
    history = [
        p
        for p in packets(journal.data if journal else {}, record.id, handoff_id)
        if datetime.fromisoformat(p["saved_at"]) <= cutoff
    ]
    p = select(history, packet_id)
    result = render(journal.data, record, p, cutoff, p == history[-1], historical=as_of is not None)
    response = dict(journal_revision=journal.revision, work_revision=record.revision, packet=result)
    if output_id:
        output = next(
            (
                o
                for o in journal.data.get("handoff_outputs", [])
                if o["packet_id"] == p["packet_id"]
                and o["output_id"] == output_id
                and datetime.fromisoformat(o["known_at"]) <= cutoff
            ),
            None,
        )
        if not output:
            failure("HANDOFF_OUTPUT_UNAVAILABLE")
        response["exported_output"] = output
    return Result(
        summary="Retrieved the version-bound local handoff.",
        data=response,
        sources=service.citations(owner, journal.sources),
    )


async def export(service, owner, req):
    record, _ = await effort.authorize(service, owner, req.record_id)
    output_id = fingerprint([record.id, req.packet_id, "export", req.idempotency_key])

    def update(data, now):
        history = packets(data, record.id, req.handoff_id)
        packet = select(history, req.packet_id)
        result = render(data, record, packet, now, packet == history[-1])
        if not result["current_basis"]:
            failure("HANDOFF_BASIS_CHANGED")
        # Export only this packet's shared scope. The private journal also contains personal forecasts.
        shared = {
            k: result[k]
            for k in (
                "handoff_id",
                "packet_id",
                "packet_revision",
                "assignment_id",
                "work_lineage_id",
                "work_occurrence_id",
                "work_episode_id",
                "requirement_set_revision",
                "semantic_basis_id",
                "transport_revision",
                "responsibility",
                "action",
                "assessment",
                "input_versions",
                "condition_states",
                "process_context",
                "next_action_state",
                "next_step",
                "current_ack_state",
                "ack_by_member",
                "delivery_state",
                "presentation_note",
            )
        }
        from canvas_bridge.privacy.output import filter_output

        shared, _, _, hidden = filter_output(shared)
        if hidden:
            failure("HANDOFF_EXPORT_WITHHELD")
        payload = json.dumps(shared, ensure_ascii=False, sort_keys=True, indent=2)
        if req.output_format == "markdown":
            from canvas_bridge.processes.handoff_export import markdown

            payload = markdown(shared)
        outputs = data.setdefault("handoff_outputs", [])
        if len(outputs) >= 80:
            failure("PROCESS_STORAGE_BUDGET")
        outputs.append(
            dict(
                output_id=output_id,
                packet_id=packet["packet_id"],
                known_at=now.isoformat(),
                output_kind="payload",
                output_format=req.output_format,
                content_hash=hashlib.sha256(payload.encode()).hexdigest(),
                payload=payload,
                external_transfer=False,
            )
        )

    receipt = effort.mutate(service, owner, record, req, update)
    _, journal = await effort.authorize(service, owner, record.id)
    output = next(o for o in journal.data["handoff_outputs"] if o["output_id"] == output_id)
    return Result(
        summary="Exported the exact local packet payload.",
        data=receipt | output,
        sources=service.citations(owner, journal.sources),
    )


async def restore(service, owner, req):
    from canvas_bridge.processes.handoff_models import Prepare

    record, journal = await effort.authorize(service, owner, req.record_id)
    history = packets(journal.data if journal else {}, record.id, req.handoff_id)
    target = select(history, req.packet_id)
    index = history.index(target)
    if not index:
        failure("HANDOFF_RESTORE_CONFLICT")
    before = history[index - 1]
    if "responsibility" in req.fields and before["responsibility"]["evidence"]:
        verify_anchor(
            service, owner, record, rd.Anchor.model_validate(before["responsibility"]["evidence"])
        )

    def update(data, now):
        current = select(packets(data, record.id, req.handoff_id))
        if (
            current["packet_id"] != req.expected_packet
            or current["work_episode_id"] != target["work_episode_id"]
        ):
            failure("HANDOFF_BASIS_CHANGED")
        if any(current[k] != target[k] for k in req.fields):
            failure("HANDOFF_RESTORE_CONFLICT")
        args = {
            k: current[k]
            for k in ("work_id", "criterion_ids", "responsibility", "action", "presentation_note")
        }
        args.update({k: before[k] for k in req.fields})
        prepared = Prepare(
            record_id=record.id,
            handoff_id=req.handoff_id,
            work_revision=req.work_revision,
            journal_revision=req.journal_revision,
            idempotency_key=req.idempotency_key,
            expected_packet=current["packet_id"],
            artifact_logical_id=current["assessment"]["logical_artifact_id"],
            process=current["process_link"],
            conditions=current.get("declared_conditions", []),
            **args,
        )
        packet = append_packet(data, now, record, owner, prepared)
        packet["compensates"] = target["packet_id"]
        packet["restored_fields"] = list(req.fields)

    return Result(
        summary="Saved the scoped restoration as a new packet revision.",
        data=effort.mutate(service, owner, record, req, update),
    )
