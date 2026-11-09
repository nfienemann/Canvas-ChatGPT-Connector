"""Existing encrypted snapshot and local-state adapters. No upstream requests."""

from datetime import UTC

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import load_only

from canvas_bridge.analytics.measurements import (
    Action,
    Actual,
    FindingSample,
    Forecast,
    Instrumentation,
    Schedule,
    Span,
)
from canvas_bridge.analytics.observations import (
    Declaration,
    Due,
    History,
    Outcome,
    version_id,
    work_facts,
)
from canvas_bridge.domain import DomainError, WorkItem
from canvas_bridge.storage import LocalRecord, Snapshot, Work, aware

OBS = "analytics_observation"
REPORT = "analytics_report"
TYPES = {
    "findings": ("findings", FindingSample),
    "due": ("dues", Due),
    "outcome": ("outcomes", Outcome),
    "instrumentation": ("instrumentation", Instrumentation),
    "progress": ("progress", Declaration),
    "forecast": ("forecasts", Forecast),
    "schedule": ("schedules", Schedule),
    "actual": ("actuals", Actual),
    "action": ("actions", Action),
}
RECORD_LIMIT = 2000
SNAPSHOT_LIMIT = 64
ITEM_LIMIT = 5000


def store_observation(session, owner, ref, kind, fact):
    session.add(
        LocalRecord(
            owner=owner,
            connection_id=ref,
            kind=OBS,
            key=version_id(kind, fact.course_ids, fact.key, fact.version),
            payload={"kind": kind, "fact": fact.model_dump(mode="json")},
            updated_at=fact.observed_at.astimezone(UTC),
        )
    )


def frozen_plan(snapshot, payload, key, when, version, *, state="accepted"):
    request, proposal = payload["request"], payload["proposal"]
    stamp = dict(
        key=key,
        version=version,
        observed_at=when,
        course_ids=snapshot.course_ids,
        source_ref=key,
        basis="accepted_plan" if state == "accepted" else "proposed_plan",
    )

    def spans(rows):
        return [
            Span(
                key=version_id(row.get("work_id"), row["start"], row["end"]),
                start=row["start"],
                end=row["end"],
            )
            for row in rows
        ]

    busy = request.get("busy_times", [])
    calendar = payload.get("review_busy_snapshot")
    if calendar:
        busy = calendar["busy_times"]
    bindings = [
        {
            "course_id": raw["course_id"],
            "work_id": raw["id"],
            "source_version": raw["source"].get("content_hash") or "",
        }
        for raw in snapshot.items
    ]
    yield (
        "schedule",
        Schedule(
            **stamp,
            state=state,
            busy_version=version_id(calendar or busy),
            parent_sources=bindings,
            coverage_start=calendar["start"] if calendar else None,
            coverage_end=calendar["end"] if calendar else None,
            busy_coverage=(
                "complete"
                if calendar and calendar["complete"]
                else "partial"
                if calendar or busy
                else "unavailable"
            ),
            blocks=spans(proposal.get("blocks", [])),
            busy=spans(busy),
            capacity_shortfall_minutes=proposal.get("known_shortfall_minutes"),
        ),
    )
    accounting = proposal.get("work_accounting", {})
    ignored = set(proposal.get("effort_summary", {}).get("receipt_verification_work_ids", []))
    eligible = {
        key for key, value in accounting.items() if value.get("state") != "omitted"
    } - ignored
    for raw in snapshot.items:
        item = WorkItem.model_validate(raw)
        if item.id not in eligible:
            continue
        estimate = request.get("effort_overrides", {}).get(item.id)
        if estimate is None and item.effort_remaining:
            estimate = item.effort_remaining.model_dump(mode="json")
        if estimate and item.instruction_hash:
            forecast_id = version_id(key, item.id)
            yield (
                "forecast",
                Forecast(
                    **(stamp | {"key": forecast_id, "course_ids": [item.course_id]}),
                    parent=item.id,
                    work_revision=item.instruction_hash,
                    unit_id=item.id,
                    parent_sources=[
                        {
                            "course_id": item.course_id,
                            "work_id": item.id,
                            "source_version": item.source.content_hash or "",
                        }
                    ],
                    scope_kind="remaining_work",
                    scope_id=forecast_id,
                    minimum=estimate["minimum_minutes"],
                    maximum=estimate["maximum_minutes"],
                    budget=(
                        estimate["maximum_minutes"]
                        if accounting[item.id].get("state") in {"allocated", "unmet"}
                        else None
                    ),
                    point=estimate.get("point_estimate_minutes"),
                    estimated_at=estimate.get("as_of"),
                    origin=estimate["origin"],
                    assumptions=estimate.get("assumptions", ""),
                ),
            )


def saved_facts(session, row, *, legacy=False):
    when = aware(row.updated_at)
    key = version_id(row.id, row.version)
    if row.kind in {"plan", "plan_candidate"}:
        snapshot = session.scalar(
            select(Snapshot).where(
                Snapshot.owner == row.owner,
                Snapshot.connection_id == row.connection_id,
                Snapshot.id == row.payload["snapshot_id"],
            )
        )
        if snapshot:
            yield from frozen_plan(
                snapshot,
                row.payload,
                key,
                when,
                row.version,
                state="accepted" if row.kind == "plan" else "proposed",
            )
    elif row.kind == "semester_state":
        for operation, receipt in row.payload.get("confirmed_deliveries", {}).items():
            yield (
                "action",
                Action(
                    key=operation,
                    course_ids=receipt["course_ids"],
                    effective_at=receipt["delivered_at"],
                    observed_at=receipt["observed_at"],
                    source_ref=receipt["receipt_hash"],
                    effect_key=operation,
                    basis="confirmed_action_receipt",
                    kind="confirmed_effect",
                ),
            )
    elif row.kind == "progress":
        work = session.scalar(
            select(Work).where(
                Work.owner == row.owner, Work.connection_id == row.connection_id, Work.id == row.key
            )
        )
        if work:
            yield (
                "progress",
                Declaration(
                    key=row.key,
                    version=row.version,
                    observed_at=when,
                    course_ids=[work.course_id],
                    source_ref=key,
                    basis="student_declaration",
                    status=row.payload["status"],
                    revision_state="unknown"
                    if legacy
                    else work.payload.get("revision_state", "unknown"),
                ),
            )


def capture_save(session, row):
    refs = []
    for kind, fact in saved_facts(session, row):
        store_observation(session, row.owner, row.connection_id, kind, fact)
        if kind in {"schedule", "forecast"}:
            refs.append(
                {
                    "kind": kind,
                    "id": fact.key,
                    **(
                        {
                            "work_id": fact.parent,
                            "work_revision": fact.work_revision,
                            "scope_id": fact.scope_id,
                            "unit_id": fact.unit_id,
                        }
                        if kind == "forecast"
                        else {}
                    ),
                }
            )
    session.flush()
    return refs


def later_submissions(session, owner, ref, request, history):
    """Only an exact own submission can backfill an earlier state from a later capture.
    Canvas assignment updated_at does not date the effective deadline change.
    """
    if request.evidence_cutoff <= request.as_of or "deadline_outcomes" not in request.families:
        return
    parents = {(d.course_ids[0], d.key) for d in history.dues}
    later = session.scalars(
        select(Snapshot)
        .where(
            Snapshot.owner == owner,
            Snapshot.connection_id == ref,
            Snapshot.created_at > request.as_of,
            Snapshot.created_at <= request.evidence_cutoff,
        )
        .options(load_only(Snapshot.id, Snapshot.course_ids, Snapshot.created_at))
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        .limit(SNAPSHOT_LIMIT + 1)
    ).all()
    if len(later) > SNAPSHOT_LIMIT:
        history.limitations.append("late_submission_history_scan_limit")
    seen = set()
    for snapshot in later[:SNAPSHOT_LIMIT]:
        if not set(snapshot.course_ids).intersection(request.course_ids):
            continue
        for raw in snapshot.items:
            parent = raw.get("course_id"), raw.get("id")
            if (
                parent not in parents
                or parent in seen
                or not raw.get("submitted_at")
                or raw.get("availability_state") == "inaccessible"
            ):
                continue
            try:
                item = WorkItem.model_validate(raw)
            except ValidationError:
                continue
            if (
                item.submission_state not in {"submitted", "resubmitted"}
                or item.submission_evidence != "returned"
                or item.submitted_at > request.as_of
            ):
                continue
            history.outcomes.append(
                Outcome(
                    key=item.id,
                    course_ids=[item.course_id],
                    observed_at=aware(snapshot.created_at),
                    effective_at=item.submitted_at,
                    source_ref=snapshot.id + "/" + item.id,
                    basis="provider_observation",
                    state="unknown",
                    submitted_at=item.submitted_at,
                )
            )
            history.bindings.add((item.course_id, item.id, item.source.content_hash or ""))
            seen.add(parent)
        if seen == parents:
            break


def load_history(bridge, owner, ref, request):
    conn, courses = bridge.selected(
        owner, ref, request.course_ids, resource_type="assignments", operation="read"
    )
    allowed = {c.id for c in courses}
    if allowed != set(request.course_ids):
        raise DomainError("permission_denied", "Review scope is unavailable.")
    history = History()
    with bridge.store.transaction() as session:
        base = select(Snapshot).where(
            Snapshot.owner == owner,
            Snapshot.connection_id == ref,
            Snapshot.created_at <= request.as_of,
        )
        snapshots = session.scalars(
            base.options(load_only(Snapshot.id, Snapshot.course_ids, Snapshot.created_at))
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
            .limit(SNAPSHOT_LIMIT + 1)
        ).all()
        missing = set(allowed)
        history.scanned = {"inventory_snapshots_scanned": 0, "observations_scanned": 0}
        for snapshot in snapshots[:SNAPSHOT_LIMIT]:
            history.scanned["inventory_snapshots_scanned"] += 1
            selected = missing.intersection(snapshot.course_ids)
            if not selected:
                continue
            counts = {course: 0 for course in selected}
            omitted = {course: 0 for course in selected}
            invalid = set()
            for raw in snapshot.items:
                course = raw.get("course_id")
                if course not in selected or raw.get("availability_state") == "inaccessible":
                    continue
                if len(history.dues) >= ITEM_LIMIT:
                    omitted[course] += 1
                    continue
                try:
                    item = WorkItem.model_validate(raw)
                    work_facts(history, item, snapshot.id, aware(snapshot.created_at))
                except ValidationError:
                    invalid.add(course)
                    omitted[course] += 1
                    continue
                counts[course] += 1
            for course in sorted(selected):
                cov = [
                    c
                    for c in snapshot.coverage
                    if c.get("course_ref") == course and c.get("resource") == "assignments"
                ]
                complete = (
                    all(c.get("state") == "complete" and c.get("pagination_complete") for c in cov)
                    if cov
                    else snapshot.complete
                )
                history.coverage.append(
                    {
                        "course_id": course,
                        "snapshot_id": snapshot.id,
                        "captured_at": aware(snapshot.created_at).isoformat(),
                        "retrieved": counts[course],
                        "omitted_count": omitted[course] if complete else None,
                        "state": "complete" if complete and not omitted[course] else "partial",
                        "pagination_complete": complete,
                        "invalid_source_records": course in invalid,
                        "pages_consumed": sum(c.get("pages_consumed", 0) for c in cov),
                    }
                )
            missing -= selected
            if not missing:
                break
        for course in sorted(missing):
            history.coverage.append(
                {
                    "course_id": course,
                    "state": "unavailable",
                    "retrieved": 0,
                    "reason": "snapshot_scan_limit"
                    if len(snapshots) > SNAPSHOT_LIMIT
                    else "no_retained_inventory",
                }
            )
        later_submissions(session, owner, ref, request, history)
        rows = session.scalars(
            select(LocalRecord)
            .where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind.in_([OBS, "progress", "plan", "plan_candidate", "semester_state"]),
                or_(
                    LocalRecord.kind == "semester_state",
                    LocalRecord.updated_at <= request.evidence_cutoff,
                ),
            )
            .order_by(LocalRecord.updated_at.desc(), LocalRecord.id.desc())
            .limit(RECORD_LIMIT + 1)
        ).all()
        if len(rows) > RECORD_LIMIT:
            history.limitations.append("owned_observation_scan_limit")
        history.scanned["observations_scanned"] = min(len(rows), RECORD_LIMIT)
        captured = {
            row.payload.get("fact", {}).get("source_ref")
            for row in rows[:RECORD_LIMIT]
            if row.kind == OBS
        }
        for row in rows[:RECORD_LIMIT]:
            try:
                if row.kind == OBS:
                    kind = row.payload["kind"]
                    dest, cls = TYPES[kind]
                    if set(row.payload["fact"]["course_ids"]) <= allowed:
                        getattr(history, dest).append(cls.model_validate(row.payload["fact"]))
                else:
                    if version_id(row.id, row.version) in captured:
                        continue
                    for kind, fact in saved_facts(session, row, legacy=True):
                        if set(fact.course_ids) <= allowed:
                            getattr(history, TYPES[kind][0]).append(fact)
            except (KeyError, TypeError, ValidationError):
                history.limitations.append(
                    "incomplete_retained_" + ("observation" if row.kind == OBS else row.kind)
                )
    history.limitations = sorted(set(history.limitations))
    return history, conn.epoch
