"""Authorized on-demand semester orchestration. No background worker or scheduler."""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from canvas_bridge.academic_rules import deadline_findings
from canvas_bridge.domain import Coverage, DomainError, Result, Source, WorkItem, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.grade_audit import collect, syllabus_documents
from canvas_bridge.grading_policy import extract_policy
from canvas_bridge.normalize import canonical_id, plain_text
from canvas_bridge.policy import Endpoint
from canvas_bridge.semester_engine import analyze, finding
from canvas_bridge.semester_models import SemesterPreferences, SemesterRequest
from canvas_bridge.semester_notifications import notification_decision
from canvas_bridge.storage import LocalRecord, Snapshot


async def prerequisite_evidence(bridge, owner, ref, course):
    """Inspect visible module requirements without fetching restricted material."""
    async with bridge.client(owner, ref, course_ref=course.id) as client:
        modules = await client.collection(
            Endpoint.MODULES, course=course.source_id, budget_seconds=3
        )
    by_id = {str(m.get("id")): m for m in modules.items}
    found, sources = [], []
    conn, _ = bridge.selected(owner, ref, [course.id])
    origin = bridge.registry.entries[conn.institution].origin
    for module in modules.items[:100]:
        if module.get("published") is False or module.get("state") == "locked":
            continue
        required = module.get("prerequisite_module_ids") or []
        unavailable = sum(
            1
            for ident in required
            if str(ident) not in by_id
            or by_id[str(ident)].get("state") == "locked"
            or by_id[str(ident)].get("published") is False
        )
        if not unavailable:
            continue
        ident = canonical_id(owner, ref, "module", f"{course.source_id}:{module['id']}")
        details = {
            "module_id": ident,
            "unavailable_prerequisite_count": unavailable,
            "module_coverage_complete": modules.complete and len(modules.items) <= 100,
            "availability_status": "not_visible_or_locked_not_proof_of_deletion",
        }
        source = Source(
            id=ident,
            url=f"{origin}/courses/{course.source_id}/modules",
            title=plain_text(module.get("name", "Module requirement")),
            source_type="module_requirement",
            course_id=course.id,
            content_hash=fingerprint([module, details]),
            retrieved_at=utcnow(),
            locator="Visible module prerequisite_module_ids and module availability",
        )
        sources.append(source)
        found.append(
            finding(
                "prerequisite_material_unavailable",
                [course.id],
                [],
                source.title,
                details,
                [source.model_dump(mode="json")],
                "Check access to this module's required prerequisites before planning dependent work; do not assume a missing record was deleted.",
                status="uncertain",
            )
        )
    return found, sources


def verified_weights(evidence):
    policy, assessments = evidence["policy"], evidence["assessments"]
    if not evidence["complete"] or policy.blockers or policy.method == "unknown":
        return {}
    if any(g.drop_lowest or g.drop_highest for g in policy.groups):
        return {}
    eligible = [a for a in assessments if not a.excluded_reason and a.score_state != "excused"]
    if not eligible or any(
        not a.eligibility_verified or a.possible is None or a.possible <= 0 for a in eligible
    ):
        return {}
    groups = {g.id: g for g in policy.groups}
    if policy.method == "weighted" and (
        any(g.weight is None or g.weight < 0 for g in groups.values())
        or sum(g.weight for g in groups.values()) != 100
        or any(a.group_id not in groups for a in eligible)
    ):
        return {}
    weights = {}
    for a in eligible:
        members = (
            eligible
            if policy.method == "points"
            else [x for x in eligible if x.group_id == a.group_id]
        )
        share = Decimal(100) if policy.method == "points" else groups[a.group_id].weight
        percent = share * a.possible / sum(x.possible for x in members)
        weights[a.id] = {
            "percent": float(percent),
            "policy_version": policy.version,
            "basis": "Structural share of verified visible assessment points; not an expected grade change.",
            "denominator_points": str(sum(x.possible for x in members)),
            "assessment_version": a.source_version,
        }
    return weights


async def course_evidence(bridge, owner, ref, course, snapshot_items, timezone):
    raw = await collect(bridge, owner, ref, course.id)
    # HTML syllabus only: bounded reads do not silently crawl every course file.
    async with bridge.client(owner, ref, course_ref=course.id) as client:
        config = await client.one(
            Endpoint.COURSE, course=course.source_id, course_content="syllabus"
        )
    if str(config.get("id")) != course.source_id:
        raise DomainError("source_changed", "Course evidence identity changed.")
    raw["config"] = raw["config"] | {"syllabus_body": config.get("syllabus_body")}
    documents, limits = await syllabus_documents(bridge, owner, ref, raw, [])
    syllabus, _ = extract_policy(documents, raw["policy"], limits, None)
    report = deadline_findings(
        documents, snapshot_items, config.get("time_zone") or timezone, raw["complete"]
    )
    sources = [
        s.model_copy(
            update={
                "course_id": course.id,
                "source_type": "grades",
                "content_hash": raw["policy"].version,
            }
        )
        for s in raw["sources"]
    ]
    sources += [
        Source(
            id=d["id"],
            title=d["title"],
            url=d["url"],
            course_id=course.id,
            source_type="syllabus",
            content_hash=d["version"],
            retrieved_at=utcnow(),
            locator="HTML syllabus text",
        )
        for d in documents
    ]
    findings = []
    accessible = {i["id"]: i for i in snapshot_items}
    for entry in report["findings"]:
        if entry["kind"] != "conflicting_deadlines" or entry.get("work_id") not in accessible:
            continue
        item = accessible[entry["work_id"]]
        findings.append(
            finding(
                "conflicting_deadlines",
                [course.id],
                [item["id"]],
                item["title"],
                {
                    "canvas_due": item["effective_due"],
                    "source_date": entry["obligation"]["date"],
                    "comparison": entry["comparison"],
                },
                [item["source"], entry["obligation"]["evidence"]],
                entry["next_action"],
                status="source_difference_applicability_unverified",
            )
        )
    groups = {g.id: g for g in raw["policy"].groups}
    for rule in syllabus["rules"]:
        if rule["rule_type"] != "category_weight" or not rule["supported"]:
            continue
        group = groups.get(rule["value"]["group_id"])
        if group and group.weight is not None and group.weight != Decimal(rule["value"]["weight"]):
            findings.append(
                finding(
                    "grade_weighting_discrepancy",
                    [course.id],
                    [],
                    course.name,
                    {
                        "category": group.name,
                        "canvas_weight": str(group.weight),
                        "syllabus_weight": rule["value"]["weight"],
                        "applicability": "requires_policy_review",
                    },
                    [sources[0].model_dump(mode="json"), rule],
                    "Check the cited policy and ask which weighting applies; no grade loss is inferred.",
                    status="source_difference_applicability_unverified",
                )
            )
    from canvas_bridge.academic.services import calculate_grade
    from canvas_bridge.providers.canvas import AuthorizedCanvasProvider

    provider = AuthorizedCanvasProvider(bridge, owner, ref)
    calculated = calculate_grade(provider.gateway, provider.calculation_input(raw, raw["policy"]))[
        "calculation"
    ]
    missing = calculated.get("missing_information", [])
    weights = verified_weights(raw)
    if missing or not weights:
        findings.append(
            finding(
                "grade_projection_uncertainty",
                [course.id],
                [],
                course.name,
                {"missing_information": missing, "assessment_weights_available": bool(weights)},
                [s.model_dump(mode="json") for s in sources[:1]],
                "Review missing policy, denominator and posted-score information before making grade projections.",
                status="uncertain",
            )
        )
    position = {
        "course_id": course.id,
        "reported": raw["reported"],
        "calculation": {
            k: calculated.get(k)
            for k in ("classification", "calculated_percentage", "missing_information", "mode")
        },
        "basis": "Current visible grade evidence, never a passing probability or guaranteed final grade.",
        "policy_version": raw["policy"].version,
        "coverage": "HTML syllabus and visible grading inputs; linked files, announcements and prerequisite materials are not comprehensively checked.",
    }
    prerequisites, prerequisite_sources = await prerequisite_evidence(bridge, owner, ref, course)
    findings.extend(prerequisites)
    sources.extend(prerequisite_sources)
    return findings, weights, position, sources


def read_state(bridge, owner, ref):
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref)
        row = session.scalar(
            select(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind == "semester_state",
                LocalRecord.key == "default",
            )
        )
        return (row.payload, row.version) if row else ({"acknowledged": {}, "delivered": {}}, 0)


def cited_ids(value):
    """Keep every returned citation bound to the egress gateway, even after truncation."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "source_id", "course_id"} and isinstance(child, str):
                yield child
            elif isinstance(child, (dict, list)):
                yield from cited_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from cited_ids(child)


async def overview(bridge, owner, ref, request=None):
    request = request or SemesterRequest()
    snapshot = await bridge.refresh(owner, ref, request.course_ids)
    conn, courses = bridge.selected(owner, ref, snapshot.course_ids)
    now = utcnow()
    start, end = (
        (request.start, request.end)
        if request.start
        else (now - timedelta(days=30), now + timedelta(days=120))
    )
    saved = bridge.independent.preferences(owner).data
    with bridge.store.transaction() as session:
        if not saved["version"]:
            legacy = session.scalar(
                select(LocalRecord).where(
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == ref,
                    LocalRecord.kind == "preferences",
                    LocalRecord.key == "default",
                )
            )
            if legacy:
                saved = {"version": legacy.version, "value": legacy.payload}
        previous = list(
            session.scalars(
                select(Snapshot)
                .where(
                    Snapshot.owner == owner,
                    Snapshot.connection_id == ref,
                    Snapshot.id != snapshot.id,
                )
                .order_by(Snapshot.created_at.desc())
                .limit(60)
            )
        )
        baseline = next(
            (s for s in previous if sorted(s.course_ids) == sorted(snapshot.course_ids)), None
        )
        plans = [
            r.payload
            for r in session.scalars(
                select(LocalRecord).where(
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == ref,
                    LocalRecord.kind == "plan",
                )
            )
        ]
    preferences = SemesterPreferences.model_validate(saved["value"].get("semester") or {})
    timezone = (
        request.timezone
        or (saved["value"].get("timezone") if saved["version"] else None)
        or conn.timezone
    )
    state, state_version = read_state(bridge, owner, ref)
    findings, weights, positions, sources, coverage = [], {}, [], [], []
    started = asyncio.get_running_loop().time()
    for course in courses:
        remaining = 60 - (asyncio.get_running_loop().time() - started)
        if not request.include_course_evidence or remaining <= 0:
            coverage.append(
                {
                    "course_id": course.id,
                    "state": "not_refreshed",
                    "reason": "course_evidence_not_requested_or_budget_exhausted",
                }
            )
            continue
        try:
            async with asyncio.timeout(min(15, remaining)):
                result = await course_evidence(
                    bridge,
                    owner,
                    ref,
                    course,
                    [
                        i
                        for i in snapshot.items
                        if i["course_id"] == course.id and i["availability_state"] != "inaccessible"
                    ],
                    timezone,
                )
            found, course_weights, grade, cited = result
            findings.extend(found)
            weights.update(course_weights)
            positions.append(grade)
            sources.extend(cited)
            coverage.append(
                {"course_id": course.id, "state": "partial", "reason": grade["coverage"]}
            )
        except (TimeoutError, DomainError) as exc:
            if isinstance(exc, DomainError) and exc.status in {
                "permission_denied",
                "reconnect_required",
                "source_changed",
            }:
                raise
            coverage.append(
                {
                    "course_id": course.id,
                    "state": "unavailable",
                    "reason": "bounded_course_evidence_unavailable",
                }
            )
    now = utcnow()
    report = analyze(
        snapshot,
        baseline,
        now=now,
        start=start,
        end=end,
        timezone=timezone,
        preferences=preferences,
        busy=request.busy_times,
        weights=weights,
        supplemental=findings,
        acknowledgements=state.get("acknowledged", {}),
        plans=plans,
    )
    report.update(
        courses=[{"course_id": c.id, "name": c.name} for c in courses],
        grade_positions=positions,
        course_evidence_coverage=coverage,
        preferences_version=saved["version"],
        state_version=state_version,
        planning_preferences=preferences.model_dump(mode="json"),
        background_monitoring=False,
    )
    report["outstanding_uncertainties"].append(
        "Prerequisite material coverage and non-HTML course amendments are incomplete; no missing dependency is invented."
    )
    if baseline is None:
        report["outstanding_uncertainties"].append(
            "No previous comparable observation exists; no event is claimed newly created."
        )
    total_findings, total_obligations = len(report["findings"]), len(report["current_obligations"])
    report["findings"] = report["findings"][:60]
    report["current_obligations"] = [
        {
            k: i[k]
            for k in (
                "id",
                "course_id",
                "title",
                "effective_due",
                "submission_state",
                "effort_remaining",
                "source",
            )
        }
        for i in report["current_obligations"][:100]
    ]
    while len(json.dumps(report, default=str).encode()) > 140_000 and (
        report["current_obligations"] or report["findings"]
    ):
        (report["current_obligations"] or report["findings"]).pop()
    report["coverage_counts"] = {
        "total_findings": total_findings,
        "returned_findings": len(report["findings"]),
        "total_obligations": total_obligations,
        "returned_obligations": len(report["current_obligations"]),
    }
    retained = {f["issue_key"] for f in report["findings"]}
    report["recommended_priorities"] = [
        i for i in report["recommended_priorities"] if i in retained
    ]
    report["notifications"] = notification_decision(
        report,
        preferences.notifications,
        now,
        timezone,
        delivered=state.get("delivered"),
        last_delivery=state.get("last_delivery"),
    )
    report["acknowledgment_receipt"] = bridge.vault.seal(
        {
            "purpose": "semester_ack",
            "snapshot_id": snapshot.id,
            "course_ids": snapshot.course_ids,
            "epoch": conn.epoch,
            "state_version": state_version,
            "findings": {
                f["issue_key"]: f["finding_revision"]
                for f in report["findings"]
                if f["lifecycle"] != "resolved_finding"
            },
            "expires": (now + timedelta(minutes=15)).isoformat(),
        },
        owner,
        ref,
    )
    # Fresh access and scope fence every aggregate, including partial/fallback results.
    await bridge.refresh_course_access(owner, ref)
    current, _ = bridge.selected(owner, ref, snapshot.course_ids)
    if current.epoch != conn.epoch:
        raise DomainError("source_changed", "Course scope changed during semester analysis.")
    sources += [
        WorkItem.model_validate(i).source
        for i in snapshot.items
        if i["availability_state"] != "inaccessible"
    ]
    referenced = set(cited_ids(report))
    return Result(
        status="partial_data",
        summary="On-demand semester overview with traceable findings, transparent priorities and explicit uncertainties.",
        data=report,
        sources=list({s.id: s for s in sources if s.id in referenced}.values()),
        meta=bridge.meta(
            snapshot_id=snapshot.id,
            display_timezone=timezone,
            coverage=[Coverage.model_validate(c) for c in snapshot.coverage],
            warnings=[
                "No background monitoring or notification was started.",
                "A source read and a saved preference do not authorize a host schedule.",
            ],
        ),
    )


async def acknowledge(bridge, owner, ref, receipt, issue_keys, acknowledged=True):
    try:
        proof = bridge.vault.open(receipt, owner, ref)
        if (
            proof["purpose"] != "semester_ack"
            or datetime.fromisoformat(proof["expires"]) <= utcnow()
        ):
            raise ValueError()
        if (
            not issue_keys
            or len(issue_keys) > 60
            or len(set(issue_keys)) != len(issue_keys)
            or set(issue_keys) - proof["findings"].keys()
        ):
            raise ValueError()
    except Exception as exc:
        raise DomainError(
            "needs_input", "Use the current semester report and its finding identifiers."
        ) from exc
    await bridge.refresh_course_access(owner, ref)
    conn, _ = bridge.selected(owner, ref, proof["course_ids"])
    if conn.epoch != proof["epoch"]:
        raise DomainError(
            "source_changed", "Course selection changed; request a new semester report."
        )
    bridge.snapshot(owner, ref, proof["snapshot_id"])
    state, version = read_state(bridge, owner, ref)
    if version != proof["state_version"]:
        raise DomainError("source_changed", "Acknowledgments changed; request a current report.")
    acknowledgments = dict(state.get("acknowledged", {}))
    for key in issue_keys:
        if acknowledged:
            acknowledgments[key] = proof["findings"][key]
        else:
            acknowledgments.pop(key, None)
    state = state | {"acknowledged": dict(list(acknowledgments.items())[-1000:])}
    saved = bridge.store.save_local(
        owner, ref, "semester_state", "default", state, version, expected_epoch=proof["epoch"]
    )
    return Result(
        summary="Requested finding acknowledgments saved; observations and grades are unchanged.",
        data=saved | {"course_ids": proof["course_ids"]},
    )
