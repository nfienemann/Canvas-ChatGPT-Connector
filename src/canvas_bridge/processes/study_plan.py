"""Saved study plans and recoverable, host-mediated study-block calendar proposals."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from canvas_bridge.analytics.personal_forecast import evaluate_frozen
from canvas_bridge.calendar_sync import CalendarContext
from canvas_bridge.domain import Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning_dates import day_boundary
from canvas_bridge.processes import effort_service as effort
from canvas_bridge.processes import readiness
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.plan_repair import Block, Constraints, Instant, Task, repair
from canvas_bridge.processes.requests import ProcessScope
from canvas_bridge.processes.state import failure


class SourceDate(Model):
    local_date: date
    course_timezone: Ref
    evidence: readiness.Anchor

    def finish_by(self):
        try:
            return day_boundary(self.local_date, ZoneInfo(self.course_timezone))
        except (ValueError, KeyError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid course timezone and date boundary.") from exc


class Demand(Model):
    forecast_id: Ref
    priority: int = Field(default=5, ge=0, le=100)
    deadline: Instant | None = None
    source_date: SourceDate | None = None
    release: Instant | None = None
    prerequisites: tuple[Ref, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def one_deadline(self):
        if self.source_date:
            if self.deadline is not None:
                raise ValueError("Choose one deadline basis.")
            self.source_date.finish_by()
        return self


class SavePlan(effort.Mutation):
    demands: tuple[Demand, ...] = Field(min_length=1, max_length=24)
    constraints: Constraints
    release_block_ids: tuple[Ref, ...] = Field(
        default=(),
        max_length=100,
        exclude_if=lambda ids: not ids,
        description="Explicitly release the placement of named future pins or manual edits from the saved generation.",
    )
    edited_blocks: tuple[Block, ...] = Field(default=(), max_length=100)
    accepted_blocks: tuple[Block, ...] = Field(default=(), max_length=100)


class CalendarCheck(effort.Mutation):
    generation_id: Ref
    calendar: CalendarContext
    operation_id: Ref | None = None


class Undo(effort.Mutation):
    generation_id: Ref


def ops(owner, generation, before, after):
    old = {b["block_id"]: b for b in before}
    new = {b["block_id"]: b for b in after}
    result = []
    for key in sorted(old.keys() | new.keys()):
        if key in old and key in new:
            # Placement protections belong to the local journal. Toggling one
            # does not change an already confirmed provider event.
            provider_fields = (old[key].keys() | new[key].keys()) - {"locked", "user_edited"}
            if all(old[key].get(field) == new[key].get(field) for field in provider_fields):
                continue
        result.append(
            dict(
                operation_id=fingerprint([generation, key]),
                block_id=key,
                marker="canvas-study:" + fingerprint([owner, key])[:40],
                action="create" if key not in old else "remove" if key not in new else "update",
                before=old.get(key),
                after=new.get(key),
                status="pending",
                attempts=0,
            )
        )
    return result


def append_generation(data, record, request, now, before, after, details):
    if len(data["plans"]) >= 40:
        failure("PROCESS_STORAGE_BUDGET")
    generation = fingerprint([record.id, request.idempotency_key])
    # A saved local plan may have unconfirmed creates. Diff against observed provider
    # state across generations so a replacement proposal does not lose those intents.
    confirmed = {}
    receipts = {}
    for prior in data["plans"]:
        if prior["record_id"] != record.id:
            continue
        for op in prior["operations"]:
            if op["status"] == "observed":
                confirmed[op["block_id"]] = op["after"]
                receipts[op["block_id"]] = op["observed_event"]
    operations = ops(
        record.scope.principal, generation, [b for b in confirmed.values() if b], after
    )
    for op in operations:
        op["expected_event"] = receipts.get(op["block_id"])
    plan = dict(
        generation_id=generation,
        record_id=record.id,
        work_revision=record.revision,
        journal_basis=request.journal_revision,
        created_at=now.isoformat(),
        before=before,
        selected_blocks=after,
        operations=operations,
        **details,
    )
    data["plans"].append(plan)


def latest(data, record_id):
    return next((p for p in reversed(data["plans"]) if p["record_id"] == record_id), None)


async def save(service, owner, request):
    record, _ = await effort.authorize(service, owner, request.record_id)

    source_dates = [d.source_date for d in request.demands if d.source_date]
    if source_dates:
        bindings = [readiness.Binding.model_validate(b) for b in record.data["bindings"]]
        entries = service.load(
            owner,
            ProcessScope(
                document_ids=tuple(b.document_id for b in bindings if b.document_id),
                local_course=record.scope.course,
                term=record.scope.term,
            ),
        )
        verified = readiness.bind(entries, bindings)
        for source in source_dates:
            readiness.check_anchor(source.evidence, verified, entries)
            if source.local_date.isoformat() not in source.evidence.quote:
                failure("PLAN_DEADLINE_SOURCE_MISMATCH")

    def update(data, now):
        work = effort.eligible(record)
        previous = latest(data, record.id)
        if previous and any(o["status"] == "issued" for o in previous["operations"]):
            failure("PLAN_OPERATION_UNRESOLVED")
        if request.accepted_blocks and previous:
            supplied = {b.block_id: b for b in request.accepted_blocks}
            stored = {b["block_id"]: Block.model_validate(b) for b in previous["selected_blocks"]}
            if len(supplied) != len(request.accepted_blocks) or supplied != stored:
                failure("PLAN_GENERATION_STALE")
        if any(
            b.provider_event_id
            or b.provider_revision
            or b.task_id not in work
            or b.episode_id != effort.episode(work[b.task_id], record.id)
            for b in request.accepted_blocks
        ):
            failure("PLAN_BLOCK_SCOPE")
        before = (
            previous["selected_blocks"]
            if previous
            else [b.model_dump(mode="json") for b in request.accepted_blocks]
        )
        accepted = {b["block_id"]: b for b in before}
        for edit in request.edited_blocks:
            b = accepted.get(edit.block_id)
            if not b or (
                edit.task_id,
                edit.episode_id,
                edit.provider_event_id,
                edit.provider_revision,
            ) != (
                b["task_id"],
                b["episode_id"],
                b.get("provider_event_id"),
                b.get("provider_revision"),
            ):
                failure("PLAN_BLOCK_SCOPE")
            if (
                edit.start < now
                or Block.model_validate(b).protected(now)
                and (
                    edit.start != Block.model_validate(b).start
                    or edit.end != Block.model_validate(b).end
                )
            ):
                failure("PLAN_PROTECTED_CONFLICT")
            accepted[edit.block_id] = edit.model_dump(mode="json") | dict(user_edited=True)
        before = list(accepted.values())
        issues = {f["forecast_id"]: f for f in data["forecasts"] if f["record_id"] == record.id}
        tasks = []
        for d in request.demands:
            f = issues.get(d.forecast_id)
            w = work.get(f["work_id"]) if f else None
            if (
                not w
                or f["work_revision"] != record.revision
                or effort.episode(w, record.id) != f["episode_id"]
            ):
                failure("PLAN_FORECAST_STALE")
            newest = next(
                row
                for row in reversed(list(issues.values()))
                if (row["episode_id"], row["scope_id"]) == (f["episode_id"], f["scope_id"])
            )
            if newest["forecast_id"] != f["forecast_id"] or effort.stale_forecast(data, f, now):
                failure("PLAN_FORECAST_STALE")
            tasks.append(
                Task(
                    task_id=w["work_id"],
                    episode_id=f["episode_id"],
                    required_minutes=f["planning_budget_minutes"],
                    deadline=d.source_date.finish_by() if d.source_date else d.deadline,
                    **d.model_dump(exclude={"forecast_id", "source_date", "deadline"}),
                )
            )
        declared = {t.task_id for t in tasks}
        if len(declared) != len(tasks) or any(
            b["task_id"] in work and b["task_id"] not in declared for b in before
        ):
            failure("PLAN_TASK_SELECTION_INCOMPLETE")
        policy = request.constraints.model_copy(
            update={"as_of": max(request.constraints.as_of, now)}
        )
        blocks = [Block.model_validate(b) for b in before]
        release = set(request.release_block_ids)
        if release:
            eligible_releases = {
                b.block_id
                for b in blocks
                if (b.locked or b.user_edited) and not b.started and b.start > policy.as_of
            }
            if (
                not previous
                or len(release) != len(request.release_block_ids)
                or not release <= eligible_releases
                or release.intersection(b.block_id for b in request.edited_blocks)
            ):
                failure("PLAN_PROTECTED_CONFLICT")
            blocks = [
                b.model_copy(update=dict(locked=False, user_edited=False))
                if b.block_id in release
                else b
                for b in blocks
            ]
        proposal = repair(record.id, tasks, blocks, policy)
        if proposal["selection"] is None:
            failure("PLAN_PROTECTED_CONFLICT")
        after = proposal.pop("selected_blocks")
        append_generation(
            data,
            record,
            request,
            now,
            before,
            after,
            dict(
                repair=proposal,
                **({"released_block_ids": sorted(release)} if release else {}),
                demands=[d.model_dump(mode="json") for d in request.demands],
                constraint_version=fingerprint(policy.model_dump(mode="json")),
                constraints=policy.model_dump(mode="json"),
                forecast_ids=[d.forecast_id for d in request.demands],
                history_cutoff=now.isoformat(),
            ),
        )

    return Result(
        summary="Saved study plan. Calendar actions require host confirmation and readback.",
        data=effort.mutate(service, owner, record, request, update),
    )


def restore_blocks(original, current):
    """Three-way inverse: restore only fields still matching the targeted generation."""
    before = {b["block_id"]: b for b in original["before"]}
    after = {b["block_id"]: b for b in original["selected_blocks"]}
    restored = {b["block_id"]: dict(b) for b in current}
    conflicts = []
    for key in sorted(before.keys() | after.keys()):
        old, new, live = before.get(key), after.get(key), restored.get(key)
        if old == new or live == old:
            continue
        if live == new:
            if old is None:
                restored.pop(key, None)
            else:
                restored[key] = dict(old)
            continue
        if not old or not new or not live:
            conflicts.append(key)
            continue
        changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
        # Timing fields are a unit; a later resize must survive a prior move.
        if changed & {"start", "end"}:
            changed.update(("start", "end"))
        if (
            any(live.get(k) != new.get(k) for k in changed)
            or live.get("locked")
            or live.get("started")
        ):
            conflicts.append(key)
            continue
        restored[key] = live | {k: old.get(k) for k in changed}
    return list(restored.values()), conflicts


async def undo(service, owner, request):
    record, _ = await effort.authorize(service, owner, request.record_id)

    def update(data, now):
        current = latest(data, record.id)
        plan = next(
            (
                p
                for p in data["plans"]
                if p["record_id"] == record.id and p["generation_id"] == request.generation_id
            ),
            None,
        )
        if not plan or not current:
            failure("PLAN_GENERATION_STALE")
        if any(p.get("compensates") == request.generation_id for p in data["plans"]):
            failure("PLAN_GENERATION_STALE")
        if any(o["status"] == "issued" for o in current["operations"]):
            failure("PLAN_OPERATION_UNRESOLVED")
        restored, conflicts = restore_blocks(plan, current["selected_blocks"])
        # Stage inverses only for effects the host has actually observed.
        observed = [o for o in plan["operations"] if o["status"] == "observed"]
        append_generation(
            data,
            record,
            request,
            now,
            current["selected_blocks"],
            restored,
            dict(
                compensates=request.generation_id,
                conflicting_block_ids=conflicts,
                history_cutoff=now.isoformat(),
            ),
        )
        inverse = data["plans"][-1]
        applied = {o["block_id"]: o for o in observed}
        inverse["operations"] = [
            o
            for o in inverse["operations"]
            if o["block_id"] in applied and o["block_id"] not in conflicts
        ]
        for o in inverse["operations"]:
            o["expected_event"] = applied[o["block_id"]]["observed_event"]

    return Result(
        summary="Saved compensating plan generation.",
        data=effort.mutate(service, owner, record, request, update),
    )


def matches(event, block):
    if not event or not block:
        return False
    b = Block.model_validate(block)
    return event.start == b.start and event.end == b.end


def reconcile_one(op, calendar, now, *, stale, dispatch):
    prior = op.get("checked_at")
    if prior and datetime.fromisoformat(prior) > calendar.retrieved_at:
        failure("PLAN_CALENDAR_STALE")
    if op["status"] == "observed":
        return
    active = [
        e for e in calendar.events if e.status != "cancelled" and e.bridge_marker == op["marker"]
    ]
    e = active[0] if len(active) == 1 else None
    desired = op["after"]
    expected = op.get("expected_event")
    snapshot = e.model_dump(mode="json") if e else None
    same_id = not expected or bool(e and e.id == expected["id"])
    prior_block = op.get("before")
    if e and prior_block and prior_block.get("provider_event_id"):
        same_id = same_id and e.id == prior_block["provider_event_id"]
        if not op.get("issued_at") and prior_block.get("provider_revision") not in (
            None,
            e.version,
        ):
            same_id = False
    op.update(checked_at=calendar.retrieved_at.isoformat(), calendar_id=calendar.calendar_id)
    if expected and any(
        event.id == expected["id"]
        and event.status != "cancelled"
        and event.bridge_marker != op["marker"]
        for event in calendar.events
    ):
        op["status"] = "conflict"
    elif len(active) > 1:
        op["status"] = "conflict"
    elif (
        op["status"] == "issued"
        and calendar.retrieved_at >= datetime.fromisoformat(op["issued_at"])
        and (
            (not desired and not active)
            or (matches(e, desired) and same_id and e.status == "confirmed")
        )
    ):
        op.update(status="observed", observed_event=snapshot, observed_at=now.isoformat())
    elif stale:
        op["status"] = "rebase_required" if op["status"] != "issued" else "issued"
    elif (
        expected
        and expected != snapshot
        or not same_id
        or (op["before"] and not matches(e, op["before"]))
        or (not op["before"] and active)
    ):
        op["status"] = "conflict"
    elif desired and any(
        b.start < Block.model_validate(desired).end and Block.model_validate(desired).start < b.end
        for b in calendar.busy_times
        if not (e and b.start == e.start and b.end == e.end)
    ):
        op["status"] = "busy_conflict"
    elif dispatch and (not e or e.version):
        if op["status"] == "issued" and calendar.retrieved_at <= datetime.fromisoformat(
            op["issued_at"]
        ):
            return
        # A fresh exhaustive marker search and the original event precondition are
        # required for a new attempt. The host uses the same stable operation ID.
        op.update(
            status="issued",
            expected_event=snapshot,
            issued_at=now.isoformat(),
            attempts=op["attempts"] + 1,
        )


async def check(service, owner, request):
    record, _ = await effort.authorize(service, owner, request.record_id)

    def update(data, now):
        plan = latest(data, record.id)
        if not plan or plan["generation_id"] != request.generation_id:
            failure("PLAN_GENERATION_STALE")
        c = request.calendar
        if (
            not c.mapping_search_complete
            or not c.pagination_complete
            or not c.availability_complete
            or not timedelta(seconds=-30) <= now - c.retrieved_at <= timedelta(minutes=5)
        ):
            failure("PLAN_CALENDAR_STALE")
        if plan.setdefault("calendar_id", c.calendar_id) != c.calendar_id:
            failure("PLAN_CALENDAR_SCOPE")
        if request.operation_id and not any(
            o["operation_id"] == request.operation_id for o in plan["operations"]
        ):
            failure("PLAN_OPERATION_UNKNOWN")
        frozen = {f["forecast_id"]: f for f in data["forecasts"]}
        stale_tasks = {
            frozen[key]["work_id"]
            for key in plan.get("forecast_ids", [])
            if effort.stale_forecast(data, frozen[key], now)
            or any(
                other["episode_id"] == frozen[key]["episode_id"]
                and other["scope_id"] == frozen[key]["scope_id"]
                and other["cutoff"] > frozen[key]["cutoff"]
                for other in frozen.values()
            )
        }
        for op in plan["operations"]:
            spans = [Block.model_validate(b) for b in (op["before"], op["after"]) if b]
            within = all(
                c.window_start <= b.start and b.end <= c.window_end and b.start >= now
                for b in spans
            )
            reconcile_one(
                op,
                c,
                now,
                stale=record.revision != plan["work_revision"]
                or any(b.task_id in stale_tasks for b in spans)
                or not within,
                dispatch=op["operation_id"] == request.operation_id,
            )

    return Result(
        summary="Saved host-supplied calendar observation. Retrieve the generation for exact operations and status.",
        data=effort.mutate(service, owner, record, request, update),
    )


async def view(service, owner, record_id):
    record, journal = await effort.authorize(service, owner, record_id)
    d = journal.data if journal else {}
    plan = latest(d, record.id) if journal else None
    now = service.repository.clock()
    ids = {f["forecast_id"] for f in d.get("forecasts", []) if f["record_id"] == record.id}
    evaluations = (
        [
            e
            for scope in effort.histories(d, now)
            for e in evaluate_frozen(scope, now)
            if e["forecast_id"] in ids
        ]
        if journal
        else []
    )
    if plan:
        states = [o["status"] for o in plan["operations"]]
        plan = plan | dict(
            calendar_status="no_changes"
            if not states
            else "observed"
            if all(s == "observed" for s in states)
            else "partially_observed"
            if "observed" in states
            else "awaiting_readback"
            if "issued" in states
            else "needs_review"
            if any(s != "pending" for s in states)
            else "proposed"
        )
    return Result(
        summary="Saved forecasts, measured work and current study-plan generation.",
        data=dict(
            work_revision=record.revision,
            journal_revision=journal.revision if journal else 0,
            forecasts=[f for f in d.get("forecasts", []) if f["record_id"] == record.id],
            evaluations=evaluations,
            measurements=[
                {k: v for k, v in m.items() if k != "owner_key"}
                for m in d.get("measurements", [])
                if m["record_id"] == record.id
            ],
            plan=plan,
        ),
        sources=service.citations(owner, (journal or record).sources),
    )
