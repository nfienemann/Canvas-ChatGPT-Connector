"""Resource planning generations in the same owner and source-bound Phase D journal."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from canvas_bridge.domain import Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import effort_service as effort
from canvas_bridge.processes import readiness as rd
from canvas_bridge.processes import resource_engine, study_plan
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.requests import ProcessScope
from canvas_bridge.processes.resource_effects import intents
from canvas_bridge.processes.resource_models import (
    Block,
    Candidate,
    Inventory,
    Process,
    Schedule,
    Span,
)
from canvas_bridge.processes.state import failure


class StudyBinding(Model):
    block_id: Ref
    step_id: Ref
    phase: Literal["active", "setup", "cleanup"] = "active"


class Save(effort.Mutation):
    study_blocks: tuple[StudyBinding, ...] = Field(default=(), max_length=64)
    forecast_id: Ref
    process: Process
    inventory: Inventory
    schedule: Schedule
    evidence: tuple[rd.Anchor, ...] = Field(default=(), max_length=20)
    expected_generation: Ref | None = None
    study_generation: Ref | None = None
    trigger: Literal[
        "initial_plan", "source_change", "access_change", "supply_change", "progress", "refresh"
    ] = "initial_plan"


def previous(data, record_id, process_id):
    return next(
        (
            g
            for g in reversed(data.get("resource_generations", []))
            if g["record_id"] == record_id and g["process"]["id"] == process_id
        ),
        None,
    )


def impacted(prior, proc, inv):
    steps = {s["id"]: s for s in proc["steps"]}
    if not prior:
        return sorted(steps)
    old = prior["process"]

    def changed(a, b):
        first = {r["id"]: r for r in a}
        second = {r["id"]: r for r in b}
        return {k for k in first.keys() | second.keys() if first.get(k) != second.get(k)}

    affected = changed(old["steps"], proc["steps"])
    resource_ids = changed(prior["inventory"]["resources"], inv["resources"])
    calendar_ids = changed(prior["inventory"]["calendars"], inv["calendars"])
    for r in inv["resources"] + prior["inventory"]["resources"]:
        if {
            r[k] for k in ("access_calendar_ref", "occupancy_calendar_ref", "run_calendar_ref")
        } & calendar_ids:
            resource_ids.add(r["id"])
    for step in steps.values():
        if set((step.get("resource_requirement") or {}).get("resource_ids", [])) & resource_ids:
            affected.add(step["id"])
    supplies = changed(old["supplies"], proc["supplies"])
    for row in old["supplies"] + proc["supplies"]:
        if row["id"] in supplies or (row.get("lead") or {}).get("calendar_ref") in calendar_ids:
            affected.add(row["step_id"])
    edges = old["dependencies"] + proc["dependencies"]
    for e in edges:
        if (
            e not in old["dependencies"]
            or e not in proc["dependencies"]
            or e["calendar_ref"] in calendar_ids
        ):
            affected.add(e["to_step"])
    while True:
        updated = affected | {e["to_step"] for e in edges if e["from_step"] in affected}
        if affected == updated:
            return sorted(affected)
        affected = updated


def bind_forecast(data, req, record, now):
    f = next(
        (
            row
            for row in reversed(data["forecasts"])
            if row["forecast_id"] == req.forecast_id and row["record_id"] == record.id
        ),
        None,
    )
    work = effort.eligible(record).get(f["work_id"]) if f else None
    if (
        not work
        or f["episode_id"] != effort.episode(work, record.id)
        or f["work_revision"] != record.revision
        or effort.stale_forecast(data, f, now)
    ):
        failure("PLAN_FORECAST_STALE")
    current = next(
        row
        for row in reversed(data["forecasts"])
        if (row["episode_id"], row["scope_id"]) == (f["episode_id"], f["scope_id"])
    )
    if f != current:
        failure("PLAN_FORECAST_STALE")
    return f, work


def inherited_schedule(schedule, prior, study, now, links, work, process):
    boundary = max(schedule.planning_boundary, now)
    if schedule.deadline_at <= boundary:
        failure("RESOURCE_HORIZON_PASSED")
    base = {b.id: b for b in schedule.base_blocks}
    candidates = list(schedule.candidates)
    if prior:
        accepted = (
            prior["result"].get("blocks", [])
            if prior["result"].get("selected_candidate_id")
            else prior["schedule"]["base_blocks"]
        )
        for b in accepted:
            old = Block(
                id=b["id"],
                step_id=b["step_id"],
                episode_id=b["episode_id"],
                start_at=b["start_at"],
                end_at=b["end_at"],
                protected=b.get("protected", False)
                or b["id"] in prior["result"].get("protected_block_ids", []),
            )
            if old.end_at <= boundary:
                continue
            if old.id in base and base[old.id] != old:
                failure("RESOURCE_BASE_CHANGED")
            base[old.id] = old
        if prior["result"].get("placements"):
            candidates.insert(
                0,
                Candidate(
                    id="retained-" + prior["generation_id"][:16],
                    placements=prior["result"]["placements"],
                ),
            )
    busy = list(schedule.busy)
    bindings = {link.block_id: link for link in links}
    if len(bindings) != len(links):
        failure("RESOURCE_BASE_CHANGED")
    step_ids = {s.id for s in process.steps if s.scope_state == "current"}
    matched = set()
    if study:
        for b in study["selected_blocks"]:
            link = bindings.get(b["block_id"])
            if link:
                if (
                    link.step_id not in step_ids
                    or b["task_id"] != work["work_id"]
                    or b["episode_id"] != work["episode_id"]
                ):
                    failure("EFFORT_SCOPE_MISMATCH")
                # Preserve the Phase D block mapping separately from the physical allocation.
                key = link.step_id + "/" + link.phase
                original = study_plan.Block.model_validate(b)
                if key in matched:
                    failure("RESOURCE_BASE_CHANGED")
                matched.add(key)
                bound = Block(
                    id=key,
                    step_id=link.step_id,
                    episode_id=b["episode_id"],
                    start_at=original.start,
                    end_at=original.end,
                    protected=original.protected(boundary),
                )
                if key not in base or bound.protected:
                    base[key] = bound
            elif b["task_id"] == work["work_id"] and datetime.fromisoformat(b["end"]) > boundary:
                failure("RESOURCE_STUDY_BINDING_REQUIRED")
            else:
                busy.append(Span(start_at=b["start"], end_at=b["end"]))
    if set(bindings) - {b["block_id"] for b in (study or {}).get("selected_blocks", [])}:
        failure("RESOURCE_BASE_CHANGED")
    return schedule.model_copy(
        update=dict(
            planning_boundary=boundary,
            base_blocks=tuple(base.values()),
            busy=tuple(busy),
            candidates=tuple(candidates),
        )
    )


def make_handoff(record, f, work, g):
    result = g["result"]
    artifacts = [
        b for b in record.data["bindings"] if b.get("role") == "artifact" and b.get("document_id")
    ]
    refs = [
        dict(
            artifact_id=b["document_id"],
            artifact_version=b["content_hash"],
            locator=b["logical_id"],
            content_fingerprint=b["content_hash"],
            scope_locator=work["requirement_id"],
            availability_state="available",
        )
        for b in artifacts
    ]
    items = []
    for step in g["process"]["steps"]:
        if step["scope_state"] != "current":
            continue
        sid = step["id"]
        allocations = [a for a in g["allocations"] if a["step_id"] == sid]
        blockers = [
            dict(
                blocker_id=a["allocation_id"],
                affected_step_id=sid,
                kind="resource_reservation",
                state="conditional",
                source_ref=a["resource_ref"],
                effective_time=a["start_at"],
                next_action="Obtain a scoped confirmation from the resource owner.",
                resolution_evidence_ref=None,
            )
            for a in allocations
            if a["booking_required"] and not a["covered_booking_id"]
        ]
        if not result.get("selected_candidate_id"):
            blockers.append(
                dict(
                    blocker_id=fingerprint([g["generation_id"], sid]),
                    affected_step_id=sid,
                    kind="schedule",
                    state="unresolved",
                    source_ref=g["constraint_version"],
                    effective_time=g["known_at"],
                    next_action="Review the reported constraints and missing inputs.",
                    resolution_evidence_ref=None,
                )
            )
        items.append(
            dict(
                handoff_basis_id=fingerprint([g["generation_id"], sid]),
                assignment_id=record.id,
                work_lineage_id=f.get("lineage_id") or f["work_id"],
                work_episode_id=f["episode_id"],
                work_occurrence_id=f["work_id"],
                process_id=g["process"]["id"],
                process_revision=g["process"]["revision"],
                step_id=sid,
                required_artifact_refs=refs,
                requirement_version_refs=[record.data["requirement_set_revision"]],
                current_constraint_refs=[
                    g["constraint_version"],
                    *[
                        fingerprint(edge)
                        for edge in g["process"]["dependencies"]
                        if sid in (edge["from_step"], edge["to_step"])
                    ],
                    *[
                        s["id"] + "@" + s["revision"]
                        for s in g["process"]["supplies"]
                        if s["step_id"] == sid
                    ],
                ],
                resource_allocation_refs=[a["allocation_id"] for a in allocations],
                reservation_support_refs=[
                    a["booking_evidence_ref"] for a in allocations if a["covered_booking_id"]
                ],
                blocker_refs=blockers,
                readiness_basis_refs=[record.id + "@" + str(record.revision)],
                plan_id=g["generation_id"],
                plan_revision=str(g["journal_revision"]),
                source_known_at=g["known_at"],
                logical_receipt_refs=[],
            )
        )
    return items


async def save(service, owner, req):
    record, _ = await effort.authorize(service, owner, req.record_id)

    if req.evidence:
        bindings = [rd.Binding.model_validate(b) for b in record.data["bindings"]]
        entries = service.load(
            owner,
            ProcessScope(
                document_ids=tuple(b.document_id for b in bindings if b.document_id),
                local_course=record.scope.course,
                term=record.scope.term,
            ),
        )
        bound = rd.bind(entries, bindings)
        for anchor in req.evidence:
            rd.check_anchor(anchor, bound, entries)

    def update(data, now):
        f, work = bind_forecast(data, req, record, now)
        if any(
            r.known_at and r.known_at > now
            for r in (*req.inventory.resources, *req.inventory.calendars)
        ):
            failure("RESOURCE_BASE_CHANGED")
        prior = previous(data, record.id, req.process.id)
        if (prior and prior["generation_id"]) != req.expected_generation:
            failure("RESOURCE_BASE_CHANGED")
        if prior and any(
            o["status"] in {"uncertain", "issued", "host_issued"} for o in prior["operations"]
        ):
            failure("PLAN_OPERATION_UNRESOLVED")
        study = study_plan.latest(data, record.id)
        if (study and study["generation_id"]) != req.study_generation:
            failure("PLAN_GENERATION_STALE")
        if any(
            s.episode_id != f["episode_id"] for s in req.process.steps if s.scope_state == "current"
        ):
            failure("EFFORT_SCOPE_MISMATCH")
        proc = req.process.model_dump(mode="json")
        inv = req.inventory.model_dump(mode="json")
        if prior:
            for collection in ("calendars", "resources"):
                old_rows = {r["id"]: r for r in prior["inventory"][collection]}
                for row in inv[collection]:
                    old = old_rows.get(row["id"])
                    if old and old != row and old["revision"] == row["revision"]:
                        failure("RESOURCE_BASE_CHANGED")
        mapping = req.process.active_demand_mapping
        if not mapping or (
            mapping.parent_forecast_ref,
            mapping.active_demand_scope_id,
            mapping.parent_remaining_minutes,
        ) != (f["forecast_id"], f["scope_id"], f["planning_budget_minutes"]):
            failure("EFFORT_SCOPE_MISMATCH")
        schedule = inherited_schedule(
            req.schedule,
            prior,
            study,
            now,
            req.study_blocks,
            work | dict(episode_id=f["episode_id"]),
            req.process,
        )
        result = resource_engine.plan(req.process, req.inventory, schedule)
        if prior and prior["process"] != proc and prior["process"]["revision"] == proc["revision"]:
            failure("RESOURCE_BASE_CHANGED")
        g = dict(
            generation_id=fingerprint([record.id, req.idempotency_key]),
            record_id=record.id,
            owner_key=fingerprint(owner),
            work_revision=record.revision,
            journal_revision=req.journal_revision + 1,
            forecast_id=f["forecast_id"],
            work_id=f["work_id"],
            work_episode_id=f["episode_id"],
            study_generation=req.study_generation,
            known_at=now.isoformat(),
            process=proc,
            inventory=inv,
            constraint_version=fingerprint([proc, inv, schedule.model_dump(mode="json")]),
            schedule=schedule.model_dump(mode="json"),
            study_blocks=[b.model_dump(mode="json") for b in req.study_blocks],
            trigger=req.trigger,
            result=result,
            affected_step_ids=impacted(prior, proc, inv),
            evidence=[a.model_dump(mode="json") for a in req.evidence],
            source_basis="declared_with_verified_passages"
            if req.evidence
            else "user_supplied_planning_inputs",
            allocations=[],
            operations=[],
        )
        by_step = {s.id: s for s in req.process.steps}
        by_resource = {r.id: r for r in req.inventory.resources}
        for a in result.get("occupancies", []):
            rid = a["resource_id"]
            key = fingerprint([record.id, proc["id"], a["episode_id"], a["placement_id"]])
            booking = next(
                (b for b in by_resource[rid].reservations if b.id == a["covered_booking_id"]), None
            )
            g["allocations"].append(
                a
                | dict(
                    allocation_id=key,
                    booking_evidence_ref=(booking.source_ref or rid)
                    + "/"
                    + booking.id
                    + "@"
                    + booking.revision
                    if booking
                    else None,
                    resource_ref=rid + "@" + by_resource[rid].revision,
                    booking_required=by_step[a["step_id"]].resource_requirement.booking_required,
                )
            )
        g["handoff"] = make_handoff(record, f, work, g)
        g["operations"] = intents(
            g, data.get("resource_generations", []), getattr(service, "resource_provider", None)
        )
        all_plans = data.setdefault("resource_generations", [])
        if len(all_plans) >= 32:
            failure("PROCESS_STORAGE_BUDGET")
        all_plans.append(g)

    return Result(
        summary="Saved the resource plan and its access requirements.",
        data=effort.mutate(service, owner, record, req, update),
    )


def projection(g, history):
    if not g:
        return None
    successful = [o for o in g["operations"] if o["status"] == "confirmed"]
    unresolved = [
        o["operation_id"]
        for o in g["operations"]
        if o["status"] not in {"confirmed", "supplied_confirmation"}
    ]
    confirmed = [o["receipt"] for o in successful]
    handoff = []
    for row in g["handoff"]:
        receipts = [o for o in successful if o["step_id"] == row["step_id"]]
        reservations = {
            o["after"]["allocation_id"]: o["receipt"]["object_id"]
            for o in receipts
            if o["kind"] == "reservation" and o["after"]
        }
        blockers = [b for b in row["blocker_refs"] if b["blocker_id"] not in reservations]
        handoff.append(
            row
            | dict(
                blocker_refs=blockers,
                reservation_support_refs=row["reservation_support_refs"]
                + list(reservations.values()),
                logical_receipt_refs=[o["operation_id"] for o in receipts],
            )
        )
    statuses = {o["status"] for o in g["operations"]}
    status = (
        "partially_applied"
        if confirmed and unresolved
        else "applied"
        if g["operations"] and not unresolved
        else "needs_review"
        if "conflict" in statuses
        else "applying"
        if statuses & {"issued", "uncertain"}
        else "accepted"
    )
    objects = {}
    for generation in history:
        if (generation["record_id"], generation["process"]["id"]) != (
            g["record_id"],
            g["process"]["id"],
        ):
            continue
        for op in generation["operations"]:
            identity = op["kind"], op["logical_id"]
            if op["status"] == "confirmed":
                if op["after"] is None:
                    objects.pop(identity, None)
                else:
                    objects[identity] = dict(
                        kind=op["kind"],
                        logical_id=op["logical_id"],
                        object_id=op["receipt"]["object_id"],
                        provider_revision=op["receipt"]["provider_revision"],
                        fields=op["after"],
                        verification="last_confirmed",
                    )
            elif op["status"] in {"conflict", "uncertain", "host_issued"} and identity in objects:
                objects[identity]["verification"] = "current_state_unverified"
        if generation["generation_id"] == g["generation_id"]:
            break
    return {k: v for k, v in g.items() if k != "owner_key"} | dict(
        apply_status=status,
        handoff_schema_version="phase-e-to-f-handoff.v1",
        handoff=handoff,
        current_effects=confirmed,
        confirmed_effect_count=len(confirmed),
        unresolved_operation_ids=unresolved,
        provider_attempt_count=sum(len(o["attempts"]) for o in g["operations"]),
        confirmed_reservations=sum(o["kind"] == "reservation" for o in successful),
        confirmed_study_events=sum(o["kind"] == "calendar" for o in successful),
        confirmed_objects=list(objects.values()),
        fully_applied_objects=None if unresolved else list(objects.values()),
    )


async def view(service, owner, record_id, process_id, generation_id=None):
    record, journal = await effort.authorize(service, owner, record_id)
    g = previous(journal.data, record_id, process_id) if journal else None
    is_current = True
    if generation_id and (not g or g["generation_id"] != generation_id):
        g = next(
            (
                old
                for old in (journal.data.get("resource_generations", []) if journal else [])
                if old["record_id"] == record_id
                and old["process"]["id"] == process_id
                and old["generation_id"] == generation_id
            ),
            None,
        )
        if not g:
            failure("PLAN_GENERATION_STALE")
        is_current = False
    return Result(
        summary="Resource plan, access evidence and handoff for this assignment.",
        data=dict(
            journal_revision=journal.revision if journal else 0,
            work_revision=record.revision,
            generation=projection(g, journal.data["resource_generations"] if g else []),
            current_generation=is_current,
            current_work_basis=bool(g and g["work_revision"] == record.revision),
        ),
        sources=service.citations(owner, (journal or record).sources),
    )
