"""Read-only evidence acquisition and orchestration for the native MCP grade tools."""

import asyncio
import re

from canvas_bridge.course_files import page_label
from canvas_bridge.domain import DomainError, Result, Source, utcnow
from canvas_bridge.grading_engine import (
    GradeAssessment,
    GradeGroup,
    GradePolicy,
    GradeScenario,
    Mode,
    PolicyReview,
    calculate,
    digest,
    number,
    reconcile,
)
from canvas_bridge.grading_policy import extract_policy
from canvas_bridge.normalize import canonical_id, fact_date, normalize_assignment, plain_text
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material

MAX_ASSESSMENTS = 60
MAX_DOCUMENTS = 3
VISIBLE_GRADE_FIELDS = (
    "current_score",
    "final_score",
    "current_grade",
    "final_grade",
    "current_points",
)


def visible_grade(value, field):
    """Preserve valid reported scalars, never nested payloads or hidden fields."""
    if field.endswith("grade"):
        return value if isinstance(value, str) and len(value) <= 100 else None
    return value if number(value) is not None and isinstance(value, (str, int, float)) else None


def assessment(raw, owner, ref, conn, course, origin):
    item = normalize_assignment(
        raw,
        owner=owner,
        connection=ref,
        institution=conn.institution,
        course=course.id,
        canvas_course=course.source_id,
        canvas_user=conn.canvas_user,
        origin=origin,
    )
    sub = raw.get("submission")
    own = (
        isinstance(sub, dict)
        and str(sub.get("user_id")) == conn.canvas_user
        and str(sub.get("assignment_id", raw["id"])) == str(raw["id"])
    )
    sub = sub if own else {}
    score, state = None, "unavailable"
    if sub.get("excused") is True:
        state = "excused"
    elif fact_date(sub, "posted_at").timestamp and number(sub.get("score")) is not None:
        score, state = number(sub["score"]), "posted"
    elif sub.get("score") is None and sub.get("workflow_state") in {
        "submitted",
        "pending_review",
        "unsubmitted",
    }:
        state = "ungraded"
    restricted = (
        raw.get("published") is False
        or raw.get("hidden_to_user") is True
        or sub.get("assignment_visible") is False
    )
    excluded = (
        "unpublished_or_restricted"
        if restricted
        else "omitted_from_final_grade"
        if raw.get("omit_from_final_grade") is True
        else "not_graded"
        if raw.get("grading_type") == "not_graded"
        else None
    )
    if restricted:
        score, state = None, "unavailable"
    group = raw.get("assignment_group_id")
    group_id = (
        canonical_id(owner, ref, "grade_group", f"{course.source_id}:{source_id(group)}")
        if group is not None
        else None
    )
    result = GradeAssessment(
        id=item.id,
        title="Restricted assessment" if restricted else item.title,
        group_id=group_id,
        possible=None if restricted else number(raw.get("points_possible")),
        score=score,
        score_state=state,
        excluded_reason=excluded,
        eligibility_verified=type(raw.get("omit_from_final_grade")) is bool
        and isinstance(raw.get("grading_type"), str),
        submission_state=item.submission_state if own else "unknown",
        missing=sub.get("missing") if type(sub.get("missing")) is bool else None,
        late=sub.get("late") if type(sub.get("late")) is bool else None,
        source_url=item.source.url,
    )
    result.source_version = digest(
        {
            "record": result.model_dump(mode="json"),
            "updated_at": raw.get("updated_at"),
            "posted_at": sub.get("posted_at"),
        }
    )
    return result


async def collect(bridge, owner, ref, course_ref):
    entitlement = await bridge.refresh_course_access(owner, ref)
    conn, courses = bridge.selected(
        owner, ref, [course_ref], resource_type="grades", operation="read"
    )
    course = courses[0]
    limitations, blockers = [], []
    async with bridge.client(owner, ref, course_ref=course_ref) as client:
        origin = client.institution.origin
        try:
            config = await client.one(Endpoint.COURSE, course=course.source_id)
            if str(config.get("id")) != course.source_id:
                raise DomainError("partial_data", "Course configuration identity mismatch.")
        except DomainError as exc:
            config = {}
            blockers.append("Course grading configuration unavailable: " + exc.status)
        groups = await client.collection(Endpoint.ASSIGNMENT_GROUPS, course=course.source_id)
        assignments = await client.collection(Endpoint.ASSIGNMENTS, course=course.source_id)
        enrollments = await client.collection(Endpoint.ENROLLMENTS)
        complete = entitlement.status == "ok" and assignments.complete and groups.complete
        if not complete:
            blockers.append("Course, assignment, or grading-group collection is incomplete.")
        policy = GradePolicy(
            method="weighted"
            if config.get("apply_assignment_group_weights") is True
            else "points"
            if config.get("apply_assignment_group_weights") is False
            else "unknown",
            empty_categories="renormalize",
        )
        for group in groups.items[:60]:
            try:
                gid = source_id(group["id"])
                rules = group.get("rules")
                if "rules" not in group:
                    blockers.append("A category's drop-rule configuration was not returned.")
                if rules is None:
                    rules = {}
                if not isinstance(rules, dict) or any(
                    k not in {"drop_lowest", "drop_highest", "never_drop"} for k in rules
                ):
                    raise ValueError("Unknown grading rule")
                policy.groups.append(
                    GradeGroup(
                        id=canonical_id(owner, ref, "grade_group", f"{course.source_id}:{gid}"),
                        name=plain_text(str(group.get("name", "Unnamed category")), 300),
                        weight=number(group.get("group_weight")),
                        drop_lowest=rules.get("drop_lowest", 0),
                        drop_highest=rules.get("drop_highest", 0),
                        never_drop=[
                            canonical_id(
                                owner, ref, "assignment", f"{course.source_id}:{source_id(i)}"
                            )
                            for i in rules.get("never_drop", [])
                        ],
                    )
                )
            except (ValueError, KeyError, TypeError, DomainError):
                blockers.append("A grading group or drop rule could not be interpreted safely.")
        if len(groups.items) > 60 or len(assignments.items) > MAX_ASSESSMENTS:
            blockers.append("Grade evidence exceeds the 60-group/60-assessment comparison budget.")
            complete = False
        records = []
        inconsistencies = []
        for raw in assignments.items[:MAX_ASSESSMENTS]:
            try:
                row = assessment(raw, owner, ref, conn, course, origin)
                if not row.excluded_reason:
                    try:
                        detail = await client.one(
                            Endpoint.ASSIGNMENT,
                            course=course.source_id,
                            assignment=source_id(raw["id"]),
                        )
                        other = assessment(detail, owner, ref, conn, course, origin)
                        ignore = {"title", "source_version", "source_url"}
                        if row.model_dump(exclude=ignore) != other.model_dump(exclude=ignore):
                            row.score, row.score_state = None, "conflicting"
                            inconsistencies.append(row.id)
                            limitations.append(
                                "Assignment-list and detail evidence disagree; refresh before calculating."
                            )
                    except DomainError as exc:
                        if exc.status == "reconnect_required":
                            raise
                        row.score, row.score_state = None, "unavailable"
                        limitations.append(
                            "An assignment detail could not be verified: " + exc.status
                        )
                records.append(row)
            except (ValueError, KeyError, TypeError) as exc:
                complete = False
                blockers.append(
                    "An assessment has invalid or incomplete evidence: " + type(exc).__name__
                )
        own = [
            e
            for e in enrollments.items
            if str(e.get("user_id")) == conn.canvas_user
            and str(e.get("course_id")) == course.source_id
            and e.get("type") == "StudentEnrollment"
        ]
        reported_rows = [
            {k: visible_grade(e["grades"].get(k), k) for k in VISIBLE_GRADE_FIELDS}
            for e in own
            if isinstance(e.get("grades"), dict)
        ]
        reported = reported_rows[0] if reported_rows else {k: None for k in VISIBLE_GRADE_FIELDS}
        reported_conflict = any(r != reported for r in reported_rows)
        if reported_conflict:
            limitations.append(
                "Own enrollment summaries disagree; no single reported grade is selected."
            )
            reported = {k: None for k in VISIBLE_GRADE_FIELDS}
        override = [
            {
                k: visible_grade(e.get(k), k)
                for k in (
                    "override_score",
                    "override_grade",
                    "current_period_override_score",
                    "current_period_override_grade",
                )
                if e.get(k) is not None
            }
            for e in own
        ]
        override = [o for o in override if o]
        periods = config.get("grading_periods")
        has_periods = config.get("has_grading_periods")
        if has_periods is True or periods:
            blockers.append(
                "Multiple grading periods require period-specific policy calculations, which are not yet supported."
            )
        elif has_periods is not False and periods != []:
            blockers.append(
                "Grading-period configuration was not returned; comparable scope is unverified."
            )
        if override:
            limitations.append(
                "Canvas returned an instructor override. It is preserved separately; the engine cannot infer its rationale."
            )
        if config.get("hide_final_grades") is True:
            reported = {k: None for k in VISIBLE_GRADE_FIELDS}
            override = []
            limitations.append(
                "Course grade totals are restricted; no totals are exposed or reconstructed."
            )
            blockers.append("Canvas hides course grade totals.")
        if not enrollments.complete:
            limitations.append("Reported-grade enrollment retrieval is incomplete.")
        policy.blockers = list(dict.fromkeys(blockers))
        policy.version = digest(policy.model_dump(mode="json"))
    current, _ = bridge.selected(owner, ref, [course_ref])
    if current.epoch != conn.epoch:
        raise DomainError("source_changed", "Connection scope changed during grade retrieval.")
    sources = [
        Source(
            id=course.id,
            url=f"{origin}/courses/{course.source_id}/grades",
            title=f"{course.name}: own visible grades",
            retrieved_at=utcnow(),
        )
    ]
    return {
        "course": course,
        "connection": conn,
        "config": config,
        "origin": origin,
        "policy": policy,
        "assessments": records,
        "sources": sources,
        "complete": complete,
        "reported_comparable": bool(
            reported_rows
            and not reported_conflict
            and not override
            and enrollments.complete
            and not policy.blockers
        ),
        "reported": reported,
        "canvas_evidence": {
            "classification": "source_fact",
            "reported": reported,
            "reported_rows": reported_rows if not config.get("hide_final_grades") else [],
            "reported_field_presence": sorted(
                {k for e in own for k in VISIBLE_GRADE_FIELDS if k in (e.get("grades") or {})}
            ),
            "reported_possible_points": None,
            "possible_points_status": "not_returned_by_enrollment_API",
            "manual_adjustments": override,
            "grading_periods": [
                {k: p.get(k) for k in ("id", "title", "start_date", "end_date", "weight")}
                for p in periods[:20]
                if isinstance(p, dict)
            ]
            if isinstance(periods, list)
            else None,
            "has_grading_periods": has_periods,
            "grade_totals_hidden": config.get("hide_final_grades"),
            "period_scope": "whole_course_enrollment_API",
            "summary_detail_conflicts": inconsistencies,
            "limitations": list(dict.fromkeys(limitations)),
            "retrieved_at": utcnow().isoformat(),
        },
    }


async def syllabus_documents(bridge, owner, ref, evidence, material_ids):
    course, config = evidence["course"], evidence["config"]
    documents, limits = [], []
    html = config.get("syllabus_body")
    if isinstance(html, str) and html.strip():
        text = plain_text(html, 100_001)
        documents.append(
            {
                "id": course.id + "_syllabus",
                "title": "Canvas course syllabus",
                "url": f"{evidence['origin']}/courses/{course.source_id}/assignments/syllabus",
                "version": digest(html),
                "complete": len(text) <= 100_000 and len(html) <= 400_000,
                "parts": [{"locator": "HTML syllabus text", "text": text[:100_000]}],
            }
        )
    refs = list(dict.fromkeys(material_ids or []))
    if material_ids is None:
        listing = await outline(bridge, owner, ref, course.id)
        refs = [
            m["id"]
            for m in listing.data.get("materials", [])
            if re.search(r"syllabus|grading polic", m["title"], re.I)
        ]
        if listing.status != "ok":
            # Discovery limitations stay explicit but a supplied complete policy may
            # still be reviewed. This is not proof that there are no amendments.
            evidence["canvas_evidence"]["limitations"].append(
                "Syllabus discovery inventory is incomplete; supply explicit material references when needed."
            )
    if len(refs) > MAX_DOCUMENTS:
        limits.append(
            "More than three syllabus candidates exist; request explicit applicable documents. No newest-version precedence inferred."
        )
    for material_ref in refs[:MAX_DOCUMENTS]:
        with bridge.store.transaction() as session:
            row = bridge.store.owned(session, Material, owner, ref, material_ref)
            if row.course_id != course.id:
                raise DomainError("permission_denied", "Syllabus reference is outside this course.")
        try:
            result = await fetch_material(bridge, owner, ref, material_ref, length=1)
            if result.data.get("coverage") not in {"text_only", "partial"}:
                limits.append(f"{material_ref}: syllabus format is unsupported or unreadable.")
                continue
            with bridge.store.transaction() as session:
                row = bridge.store.owned(session, Material, owner, ref, material_ref)
                if not row.version_hash or row.version_hash != result.data.get("content_hash"):
                    raise DomainError("source_changed", "Syllabus changed while collecting rules.")
                documents.append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "url": row.url,
                        "version": row.version_hash,
                        "complete": result.data.get("coverage") == "text_only",
                        "parts": [
                            {
                                "locator": page_label(row, p["page"])
                                if "page" in p
                                else p.get("locator", "document text"),
                                "text": p["text"],
                            }
                            for p in row.locators
                        ],
                    }
                )
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            limits.append(f"{material_ref}: syllabus retrieval failed ({exc.status}).")
    return documents, limits


async def grading_request(
    bridge,
    owner,
    ref,
    course_ref,
    action="policy",
    *,
    mode: Mode = "current_graded",
    policy_basis="canvas",
    material_ids=None,
    review: PolicyReview | None = None,
    scenario: GradeScenario | None = None,
):
    # One bounded request, no grade/history persistence and no hidden-work crawl.
    try:
        async with asyncio.timeout(90):
            evidence = await collect(bridge, owner, ref, course_ref)
            policy = evidence["policy"]
            syllabus, syllabus_policy = None, None
            if (
                action in {"policy", "audit"}
                or policy_basis == "syllabus"
                or mode == "syllabus_current"
            ):
                documents, limits = await syllabus_documents(
                    bridge, owner, ref, evidence, material_ids
                )
                syllabus, syllabus_policy = extract_policy(documents, policy, limits, review)
                # Privacy and evidence-scope blockers apply to every calculation basis.
                syllabus_policy.blockers.extend(policy.blockers)
                evidence["sources"].extend(
                    Source(id=d["id"], title=d["title"], url=d["url"], retrieved_at=utcnow())
                    for d in documents
                )
            data = {
                "engine": "grade-audit-1",
                "course_id": course_ref,
                "canvas": evidence["canvas_evidence"],
                "canvas_policy": policy.model_dump(mode="json"),
                "syllabus_policy": syllabus,
                "assessment_evidence": [a.model_dump(mode="json") for a in evidence["assessments"]],
                "notifications": "disabled_not_implemented",
                "data_boundary": "untrusted_source_data",
                "coverage": {
                    "visible_assignment_collection_complete": evidence["complete"],
                    "instructor_hidden_work": "not_accessible",
                    "unknown_scores_are_zero": False,
                },
            }
            complete = evidence["complete"]
            if action == "audit":
                reproduced = calculate(policy, evidence["assessments"], evidence_complete=complete)
                estimate = calculate(
                    syllabus_policy,
                    evidence["assessments"],
                    "syllabus_current",
                    evidence_complete=complete,
                )
                data.update(
                    canvas_calculation=reproduced,
                    syllabus_calculation=estimate,
                    reconciliation=reconcile(
                        evidence["reported"],
                        reproduced,
                        estimate,
                        policy,
                        syllabus_policy,
                        reported_comparable=evidence["reported_comparable"],
                    ),
                )
                status = (
                    "ok"
                    if data["reconciliation"]["outcome"] != "insufficient_evidence"
                    else "partial_data"
                )
                summary = (
                    "Canvas reports a grade; this audit evaluates consistency with available evidence. "
                    + data["reconciliation"]["outcome"].replace("_", " ")
                    + "."
                )
            elif action == "calculate":
                chosen = (
                    syllabus_policy
                    if policy_basis == "syllabus" or mode == "syllabus_current"
                    else policy
                )
                data["calculation"] = calculate(
                    chosen, evidence["assessments"], mode, scenario, evidence_complete=complete
                )
                status = "partial_data" if data["calculation"]["missing_information"] else "ok"
                summary = (
                    "Deterministic grade calculation: "
                    + data["calculation"]["classification"].replace("_", " ")
                    + ". Hypothetical results are not official grades."
                )
            else:
                status = "partial_data" if policy.blockers or syllabus_policy.blockers else "ok"
                summary = "Visible Canvas grading evidence and source-backed syllabus rule candidates; review uncertainty before calculating."
            current, _ = bridge.selected(owner, ref, [course_ref])
            if current.epoch != evidence["connection"].epoch:
                raise DomainError(
                    "source_changed", "Connection scope changed during the grade audit."
                )
            return Result(
                status=status,
                summary=summary,
                data=data,
                sources=evidence["sources"],
                meta=bridge.meta(),
            )
    except TimeoutError:
        return Result(
            status="partial_data",
            summary="Grade evidence exceeded the request time budget. No precise grade was calculated.",
            data={
                "classification": "indeterminate",
                "missing_information": ["Grade evidence request timed out."],
            },
        )
