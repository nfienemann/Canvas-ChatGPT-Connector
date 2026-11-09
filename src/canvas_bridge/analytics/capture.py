"""Authorized local measurement writes and optional diagnostic capture."""

from datetime import UTC, datetime

from sqlalchemy import select

from canvas_bridge.analytics.measurements import Action, Actual
from canvas_bridge.analytics.observations import version_id
from canvas_bridge.analytics.storage import store_observation
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.storage import LocalRecord, Work


def record_duration(bridge, owner, ref, measurement, expected_version):
    m = measurement
    now = utcnow()
    event_time = (m.actual.completion or m.actual.start) if m.actual else m.manual.occurred_at
    if event_time > now:
        raise DomainError(
            "needs_input",
            "Recorded work and manual durations require a past or current observation.",
        )
    with bridge.store.transaction() as session:
        bridge.store.principal(session, owner)
        bridge.store.connection(session, owner, ref, lock=True)
        bridge.authorize(owner, ref, m.course_id, "assignments", session=session).require()
        if m.actual:
            work = bridge.store.owned(session, Work, owner, ref, m.work_id)
            if (
                work.course_id != m.course_id
                or work.payload.get("availability_state") == "inaccessible"
            ):
                raise DomainError(
                    "permission_denied", "This work is unavailable in the selected course."
                )
            if (
                work.payload.get("instruction_hash")
                and work.payload["instruction_hash"] != m.actual.work_revision
            ):
                raise DomainError(
                    "source_changed",
                    "Work instructions changed. Record the duration against the verified work revision.",
                )
        # Versions are retained as separate encrypted records, scoped by owner, connection and course.
        key = version_id(m.course_id, m.measurement_id)
        kind = "actual" if m.actual else "action"
        anchor = session.scalar(
            select(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind == "analytics_duration",
                LocalRecord.key == key,
            )
        )
        if anchor and (anchor.payload["kind"], anchor.payload["work_id"]) != (kind, m.work_id):
            raise DomainError(
                "needs_input", "A correction must identify the original measurement scope."
            )
        old = anchor.version if anchor else 0
        digest = version_id(m.model_dump(mode="json"))
        if anchor and anchor.payload["digest"] == digest and expected_version in {old, old - 1}:
            return Result(
                summary="Duration already recorded.", data={"record_id": key, "version": old}
            )
        if old != expected_version:
            raise DomainError(
                "source_changed", "Read the current measurement version before correcting it."
            )
        payload = {"kind": kind, "work_id": m.work_id, "digest": digest}
        if not anchor:
            session.add(
                LocalRecord(
                    owner=owner,
                    connection_id=ref,
                    kind="analytics_duration",
                    key=key,
                    version=1,
                    payload=payload,
                    updated_at=now,
                )
            )
        else:
            anchor.payload, anchor.version, anchor.updated_at = payload, old + 1, now
        stamp = dict(
            key=key,
            version=old + 1,
            observed_at=now,
            effective_at=event_time,
            course_ids=[m.course_id],
            source_ref=key,
            basis="student_declaration",
        )
        fact = (
            Actual(
                **stamp,
                parent=m.work_id,
                parent_sources=[
                    {
                        "course_id": m.course_id,
                        "work_id": work.id,
                        "source_version": work.payload["source"].get("content_hash") or "",
                    }
                ],
                **m.actual.model_dump(),
            )
            if m.actual
            else Action(**stamp, kind="manual_session", manual_minutes=m.manual.minutes)
        )
        store_observation(session, owner, ref, kind, fact)
    return Result(
        summary="Recorded personal duration.", data={"record_id": key, "version": old + 1}
    )


def capture_workflow(ctx, result):
    """One performed workflow execution. Provider effects require separate readback evidence."""
    try:
        now = utcnow()
        with ctx.bridge.store.transaction() as session:
            conn = ctx.bridge.store.connection(session, ctx.owner, ctx.ref, lock=True)
            if conn.epoch != ctx.epoch:
                raise ValueError("Scope changed")
            from canvas_bridge.authorization import request_authorization
            from canvas_bridge.usage.models import attempts
            from canvas_bridge.usage.transport import pseudonym

            context = request_authorization.get()
            logical = context.request_id if context else result.meta.request_id
            stamp = dict(observed_at=now, course_ids=ctx.courses, basis="system_diagnostic")
            store_observation(
                session,
                ctx.owner,
                ctx.ref,
                "action",
                Action(
                    **stamp,
                    key=logical,
                    source_ref=logical,
                    kind="logical_request",
                    effective_at=now,
                    elapsed_ms=result.data["execution"]["elapsed_ms"],
                ),
            )
            key = ctx.bridge.vault.key
            # Only sent governor attempts from this authorized workflow, including failed sends.
            rows = session.execute(
                select(attempts.c.id, attempts.c.created)
                .where(
                    attempts.c.owner == pseudonym(key, "owner", ctx.owner),
                    attempts.c.tenant == pseudonym(key, "tenant", conn.institution),
                    attempts.c.task == pseudonym(key, "task", logical),
                    attempts.c.state.in_(["SENT", "SETTLED", "UNCERTAIN"]),
                )
                .order_by(attempts.c.created, attempts.c.id)
                .limit(251)
            ).all()
            if len(rows) > 250:
                result.meta.warnings.append(
                    "Workflow analytics captured the first 250 transport attempts."
                )
            for row in rows[:250]:
                store_observation(
                    session,
                    ctx.owner,
                    ctx.ref,
                    "action",
                    Action(
                        **stamp,
                        key=row.id,
                        source_ref=row.id,
                        kind="attempt",
                        effective_at=datetime.fromtimestamp(row.created, UTC),
                    ),
                )
    except Exception:
        result.meta.warnings.append("Workflow completed with unavailable analytics capture.")


def finding_sample(report, snapshot):
    from canvas_bridge.analytics.measurements import FindingSample

    selected = [
        f
        for f in report["findings"]
        if f["kind"]
        in {
            "major_assessment_cluster",
            "deadline_cluster",
            "availability_shortfall",
            "study_plan_conflict",
        }
    ]
    active = [f for f in selected if f["lifecycle"] != "resolved_finding"]
    key = version_id(
        snapshot.id,
        report["analysis_window"],
        [(f["finding_revision"], f["lifecycle"]) for f in selected],
    )
    return FindingSample(
        key=key,
        observed_at=report["analysis_as_of"],
        source_ref=snapshot.id,
        course_ids=snapshot.course_ids,
        basis="system_diagnostic",
        start=report["analysis_window"]["start"],
        end=report["analysis_window"]["end"],
        coverage_complete=snapshot.complete,
        deadline_clusters=sum(
            f["kind"] in {"deadline_cluster", "major_assessment_cluster"} for f in active
        ),
        capacity_shortfalls=sum(f["kind"] == "availability_shortfall" for f in active),
        study_plan_conflicts=sum(f["kind"] == "study_plan_conflict" for f in active),
        acknowledged_unresolved=sum(f["acknowledged"] for f in active),
        resolved_findings=len(selected) - len(active),
        parent_sources=[
            {
                "course_id": i["course_id"],
                "work_id": i["id"],
                "source_version": i["source"].get("content_hash") or "",
            }
            for i in snapshot.items
            if i.get("availability_state") != "inaccessible"
        ],
    )


def capture_findings(bridge, owner, ref, epoch, sample, report):
    try:
        with bridge.store.transaction() as session:
            conn = bridge.store.connection(session, owner, ref, lock=True)
            if conn.epoch != epoch:
                raise ValueError("Course scope changed.")
            store_observation(session, owner, ref, "findings", sample)
    except Exception:
        report["limitations"].append("Historical finding measurements could not be retained.")
