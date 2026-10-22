"""Bounded, authorized course evidence shared by academic comparison workflows."""

import asyncio
import re
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from canvas_bridge.academic_rules import (
    citation,
    deadline_findings,
    instruction_findings,
    normalized,
    repeated_concepts,
)
from canvas_bridge.domain import Coverage, DomainError, Result, Source, utcnow
from canvas_bridge.evidence import attach, fingerprint, reconcile_states
from canvas_bridge.normalize import (
    assignment_requirements,
    fact_date,
    normalize_assignment,
    plain_text,
)
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material, aware

MAX_ASSIGNMENTS = 30
MAX_DOCUMENTS = 3


def document(source, text, locator="HTML text", *, complete=True, parts=None):
    return {
        "id": source.id,
        "title": source.title,
        "url": source.url,
        "course_id": source.course_id,
        "source_type": source.source_type,
        "version": source.content_hash or fingerprint(text),
        "retrieved_at": source.retrieved_at.isoformat(),
        "source_updated_at": source.source_updated_at.isoformat()
        if source.source_updated_at
        else None,
        "complete": complete,
        "parts": parts if parts is not None else [{"locator": locator, "text": text}],
    }


def source_for(course, origin, kind, key, title, text, updated=None):
    return Source(
        id=key,
        url=f"{origin}/courses/{course.source_id}/"
        + (
            "assignments/syllabus"
            if kind == "syllabus"
            else "discussion_topics/" + key.rsplit("-", 1)[-1]
        ),
        title=title,
        retrieved_at=utcnow(),
        source_updated_at=updated,
        source_type=kind,
        course_id=course.id,
        resource_id=key,
        content_hash=fingerprint(text),
        extraction_status="html_text",
    )


async def collect_course(
    bridge, owner, ref, course_ref, material_ids=None, purpose=None, work_id=None
):
    await bridge.refresh_course_access(owner, ref)
    conn, courses = bridge.selected(owner, ref, [course_ref])
    course, now = courses[0], utcnow()
    bundle = {
        "course": course,
        "connection": conn,
        "items": [],
        "assignments": {},
        "documents": [],
        "sources": [],
        "coverage": [],
        "limitations": [],
        "submission_conflicts": [],
        "inaccessible_materials": [],
        "timezone": None,
        "assignments_complete": False,
        "outline": None,
    }
    async with bridge.client(owner, ref) as client:
        origin = client.institution.origin
        assignments = await client.collection(Endpoint.ASSIGNMENTS, course=course.source_id)
        bundle["assignments_complete"] = (
            assignments.complete and len(assignments.items) <= MAX_ASSIGNMENTS
        )
        bundle["coverage"].append(
            Coverage(
                course_ref=course_ref,
                resource="assignments",
                state="complete" if bundle["assignments_complete"] else "partial",
                pagination_complete=assignments.complete,
                pages_consumed=assignments.pages,
                warning=assignments.failure
                or (
                    "30-assignment detail budget"
                    if len(assignments.items) > MAX_ASSIGNMENTS
                    else None
                ),
            )
        )
        for raw in assignments.items[:MAX_ASSIGNMENTS]:
            if raw.get("published") is False or raw.get("locked_for_user") is True:
                bundle["limitations"].append(
                    "A restricted assessment was omitted; no hidden content was retrieved."
                )
                continue
            initial = normalize_assignment(
                raw,
                owner=owner,
                connection=ref,
                institution=conn.institution,
                course=course_ref,
                canvas_course=course.source_id,
                canvas_user=conn.canvas_user,
                origin=origin,
            )
            details_complete = True
            try:
                fresh = await client.one(
                    Endpoint.ASSIGNMENT, course=course.source_id, assignment=source_id(raw["id"])
                )
                if str(fresh.get("id")) != str(raw["id"]):
                    raise DomainError("partial_data", "Assignment identity mismatch.")
                if fresh.get("published") is False or fresh.get("locked_for_user") is True:
                    bundle["limitations"].append(
                        "An assessment became inaccessible during retrieval."
                    )
                    continue
            except DomainError as exc:
                if exc.status in {"reconnect_required", "permission_denied"}:
                    if exc.status == "reconnect_required":
                        raise
                    bundle["limitations"].append(
                        "An assignment detail was inaccessible; its contents were omitted."
                    )
                    continue
                fresh, details_complete = raw, False
                bundle["limitations"].append(
                    "An assignment detail could not be checked; collection evidence is partial."
                )
            current = normalize_assignment(
                fresh,
                owner=owner,
                connection=ref,
                institution=conn.institution,
                course=course_ref,
                canvas_course=course.source_id,
                canvas_user=conn.canvas_user,
                origin=origin,
            )
            observations = [
                {
                    "state": i.submission_state,
                    "source": label,
                    "evidence": i.source.model_dump(mode="json"),
                }
                for i, label in (
                    (initial, "assignment_collection"),
                    (current, "assignment_details"),
                )
            ]
            state = reconcile_states(observations)
            if state["conflict"]:
                state.update(
                    work_id=current.id,
                    kind="inconsistent_submission_states",
                    certainty="unresolved",
                    impact="Submission status is not consistently established.",
                    next_action="Check Canvas submission history before treating this work as missing.",
                )
                bundle["submission_conflicts"].append(state)
                current.submission_state = "unknown"
                current.submission_evidence = "conflicting"
                current.submission_state_basis = state["basis"]
            requirement = assignment_requirements(fresh)
            rubric_raw = fresh.get("rubric")
            rubric = rubric_raw if isinstance(rubric_raw, list) else []
            rubric_text = "\n".join(
                plain_text(str(r.get(k, "")), 2000)
                for r in rubric[:50]
                if isinstance(r, dict)
                for k in ("description", "long_description")
            )
            instructions = document(
                current.source.model_copy(update={"source_type": "assignment_description"}),
                requirement["text"],
                "Assignment instructions",
                complete=details_complete
                and requirement["state"] in {"present", "empty_in_canvas"},
            )
            rubric_source = current.source.model_copy(
                update={
                    "id": current.id + "-rubric",
                    "source_type": "assignment_rubric",
                    "content_hash": fingerprint(rubric_text),
                }
            )
            rubric_doc = document(
                rubric_source,
                rubric_text,
                "Rubric criteria",
                complete=details_complete
                and isinstance(rubric_raw, list)
                and len(rubric_raw) <= 50,
            )
            bundle["items"].append(current.model_dump(mode="json"))
            bundle["sources"].extend([current.source, rubric_source])
            bundle["assignments"][current.id] = {
                "instructions": instructions,
                "rubric": rubric_doc,
                "requirements_state": requirement["state"],
                "detail_complete": details_complete,
                "allowed_extensions": [
                    v[:30] for v in fresh.get("allowed_extensions", [])[:30] if isinstance(v, str)
                ]
                if isinstance(fresh.get("allowed_extensions"), list)
                else None,
            }
        try:
            raw_course = await client.one(
                Endpoint.COURSE, course=course.source_id, course_content="syllabus"
            )
            if str(raw_course.get("id")) != course.source_id:
                raise DomainError("partial_data", "Course identity mismatch.")
            zone = raw_course.get("time_zone")
            if isinstance(zone, str):
                try:
                    ZoneInfo(zone)
                    bundle["timezone"] = zone
                except (ValueError, ZoneInfoNotFoundError):
                    pass
            body = raw_course.get("syllabus_body")
            if isinstance(body, str) and body.strip():
                text = plain_text(body, 50_001)
                src = source_for(
                    course,
                    origin,
                    "syllabus",
                    course_ref + "-syllabus",
                    "Course syllabus",
                    text,
                    fact_date(raw_course, "updated_at").timestamp,
                )
                bundle["sources"].append(src)
                bundle["documents"].append(
                    document(
                        src, text[:50_000], complete=len(text) <= 50_000 and len(body) <= 200_000
                    )
                )
            else:
                bundle["limitations"].append(
                    "Course syllabus HTML is empty or unavailable; no policy absence is inferred."
                )
        except DomainError as exc:
            if exc.status == "reconnect_required":
                raise
            bundle["limitations"].append("Course syllabus/configuration could not be retrieved.")
        announcements = await client.collection(Endpoint.ANNOUNCEMENTS, course=course.source_id)
        bundle["coverage"].append(
            Coverage(
                course_ref=course_ref,
                resource="announcements_last_180_days",
                state="complete"
                if announcements.complete and len(announcements.items) <= 10
                else "partial",
                pagination_complete=announcements.complete,
                pages_consumed=announcements.pages,
                warning=announcements.failure
                or "Only the last 180 days and at most 10 accessible announcements are inspected.",
            )
        )
        for raw in announcements.items[:10]:
            posted = fact_date(raw, "posted_at").timestamp
            delayed = fact_date(raw, "delayed_post_at").timestamp
            if (
                raw.get("context_code") != "course_" + course.source_id
                or not posted
                or posted > now
                or posted < now - timedelta(days=180)
                or delayed
                and delayed > now
                or raw.get("published") is False
                or raw.get("locked_for_user") is True
            ):
                continue
            text = plain_text(str(raw.get("message", "")), 10_001)
            src = source_for(
                course,
                origin,
                "announcement",
                course_ref + "-" + source_id(raw["id"]),
                plain_text(str(raw.get("title", "Announcement")), 500),
                text,
                fact_date(raw, "updated_at").timestamp,
            )
            bundle["sources"].append(src)
            bundle["documents"].append(document(src, text[:10_000], complete=len(text) <= 10_000))
    listing = await outline(bridge, owner, ref, course_ref)
    bundle["outline"] = listing.data
    bundle["coverage"].append(
        Coverage(
            course_ref=course_ref,
            resource="materials_inventory",
            state="complete" if listing.status == "ok" else "partial",
            pagination_complete=listing.status == "ok",
            warning="Only selected or title-discovered documents are read; an outline is not document content.",
        )
    )
    resources = listing.data.get("materials", [])
    for module in listing.data.get("modules", []):
        for entry in module.get("items", []):
            if entry.get("material_availability") == "not_in_accessible_inventory":
                bundle["inaccessible_materials"].append(
                    {
                        "kind": "unresolved_reading_access",
                        "module_id": module["id"],
                        "title": entry.get("title"),
                        "source_url": listing.sources[0].url if listing.sources else None,
                        "certainty": "reference_not_resolved",
                        "required_reading_status": "unknown",
                        "impact": "A module reading reference could not be resolved to authorized readable content.",
                        "next_action": "Check the Canvas reference; module inclusion alone does not establish whether it is required.",
                    }
                )
    if material_ids is None:
        targets = [
            r["id"]
            for r in resources
            if re.search(r"\b(?:syllabus|schedule|calendar)\b", r["title"], re.I)
        ]
        if purpose == "exam":
            chosen = exam_pack(bundle, work_id)
            # Same-module evidence identifies candidate readings, never proves
            # exam coverage. Fetch text so ChatGPT has more than filenames.
            targets = list(
                dict.fromkeys(
                    [c["material_id"] for c in chosen.get("candidate_readings", [])] + targets
                )
            )
    else:
        targets = list(dict.fromkeys(material_ids))
    if len(targets) > MAX_DOCUMENTS:
        bundle["limitations"].append(
            "Only three source documents can be read in one request; additional versions remain unchecked."
        )
    for material_id in targets[:MAX_DOCUMENTS]:
        with bridge.store.transaction() as session:
            row = bridge.store.owned(session, Material, owner, ref, material_id)
            if row.course_id != course_ref:
                raise DomainError("permission_denied", "Document is outside the requested course.")
        try:
            fetched = await fetch_material(bridge, owner, ref, material_id, length=1000)
            bundle["sources"].extend(fetched.sources[:1])
            if not fetched.data.get("content_hash"):
                raise DomainError(
                    "unsupported_feature", "No extracted document content is available."
                )
            with bridge.store.transaction() as session:
                row = bridge.store.owned(session, Material, owner, ref, material_id)
                if row.version_hash != fetched.data["content_hash"]:
                    raise DomainError("source_changed", "Document changed during comparison.")
                from canvas_bridge.course_files import page_label

                parts = [
                    {
                        "locator": page_label(row, p["page"])
                        if "page" in p
                        else p.get("locator", "HTML text"),
                        "text": p["text"],
                    }
                    for p in row.locators
                ]
                src = Source(
                    id=row.id,
                    title=row.title,
                    url=row.url,
                    retrieved_at=aware(row.retrieved_at),
                    source_type="canvas_" + row.kind,
                    course_id=course_ref,
                    resource_id=row.id,
                    content_hash=row.version_hash,
                    extraction_status=fetched.data.get("coverage", "unknown"),
                )
                bundle["documents"].append(
                    document(
                        src,
                        row.text,
                        parts=parts,
                        complete=fetched.data.get("coverage") == "text_only",
                    )
                )
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            bundle["inaccessible_materials"].append(
                {
                    "material_id": material_id,
                    "kind": "inaccessible_reading",
                    "certainty": "retrieval_limitation",
                    "impact": "Requested source text could not be read.",
                    "reason": exc.message,
                    "next_action": "Check access or use a supported source; do not infer the document contents.",
                }
            )
    current, _ = bridge.selected(owner, ref, [course_ref])
    if current.epoch != conn.epoch:
        raise DomainError("source_changed", "Selected scope changed during evidence retrieval.")
    bundle["limitations"].extend(
        [
            "Only student-visible selected-course sources are inspected. Missing data is not proof of absence.",
            "Natural-language implications and amendments need review. Unread, hidden and external resources are not covered.",
            "Announcements are limited to 180 days; notifications are disabled.",
        ]
    )
    return bundle


def related_documents(bundle, item):
    target = normalized(item["title"])
    result = []
    for doc in bundle["documents"]:
        parts = []
        for part in doc["parts"]:
            # Explicit assignment-title mentions only. General course policies
            # may need manual interpretation, never silently applied to all work.
            lines = [
                line for line in part["text"].splitlines() if target and target in normalized(line)
            ]
            if lines:
                parts.append({"locator": part["locator"], "text": "\n".join(lines)})
        if parts:
            result.append({**doc, "parts": parts})
    return result


def instruction_report(bundle, work_id, draft=None):
    item = next((i for i in bundle["items"] if i["id"] == work_id), None)
    if item is None:
        raise DomainError(
            "permission_denied", "Assignment is not available in this course evidence."
        )
    assignment = bundle["assignments"][work_id]
    docs = [assignment["instructions"], assignment["rubric"], *related_documents(bundle, item)]
    result = instruction_findings(docs, draft)
    result.update(
        work_id=work_id,
        requirements_state=assignment["requirements_state"],
        rubric_coverage="complete"
        if assignment["rubric"]["complete"]
        else "unavailable_or_partial",
        allowed_extensions=assignment["allowed_extensions"],
        source_passages=[
            citation(d, p, p["text"][:1500]) for d in docs for p in d["parts"] if p["text"]
        ][:20],
    )
    # Deadline contradictions use the same dated-obligation engine.
    result["deadline_comparison"] = deadline_findings(
        related_documents(bundle, item), [item], bundle["timezone"], bundle["assignments_complete"]
    )
    return result


def exam_pack(bundle, work_id=None):
    from canvas_bridge.domain import WorkItem
    from canvas_bridge.planning import is_actionable

    now = utcnow()
    eligible = [
        i
        for i in bundle["items"]
        if re.search(r"\b(?:quiz|exam|test|midterm|final)\b", i["title"], re.I)
        and is_actionable(WorkItem.model_validate(i))
    ]
    if work_id:
        exam = next((i for i in bundle["items"] if i["id"] == work_id), None)
        if not exam:
            raise DomainError("permission_denied", "Assessment is outside this course evidence.")
    else:
        future = [
            i
            for i in eligible
            if i["effective_due"]["kind"] == "timestamp"
            and fact_date({"due": i["effective_due"]["timestamp"]}, "due").timestamp > now
        ]
        exam = min(future, key=lambda i: i["effective_due"]["timestamp"]) if future else None
    if exam is None:
        return {
            "status": "needs_input",
            "assessment": None,
            "candidates": [
                {"work_id": i["id"], "title": i["title"], "date": i["effective_due"]}
                for i in eligible
            ],
            "reason": "No reliably dated next assessment; choose an assessment. Undated or old records were not assumed upcoming.",
        }
    docs = bundle["documents"]
    assigned, candidates, objectives = [], [], []
    instructions = bundle["assignments"][exam["id"]]["instructions"]
    for doc in [instructions, *related_documents(bundle, exam)]:
        for part in doc["parts"]:
            for line in part["text"].splitlines():
                if re.search(
                    r"\b(?:covers|coverage|includes|read|reading|required|study)\b", line, re.I
                ):
                    assigned.append(citation(doc, part, line))
                if re.search(
                    r"\b(?:objective|learn|explain|compare|describe|analyze)\b", line, re.I
                ):
                    objectives.append(citation(doc, part, line))
    for module in (bundle["outline"] or {}).get("modules", []):
        if any(
            normalized(i.get("title", "")) == normalized(exam["title"])
            for i in module.get("items", [])
        ):
            candidates.extend(
                {
                    "material_id": i["material_ref"],
                    "title": i.get("title"),
                    "basis": "same_module_as_assessment",
                    "exam_coverage_confirmed": False,
                }
                for i in module["items"]
                if i.get("material_ref")
            )
    excerpts, remaining = [], 16_000
    for doc in docs:
        for part in doc["parts"]:
            text = part["text"][: min(4000, remaining)]
            if text:
                excerpts.append(
                    {
                        **citation(doc, part, text),
                        "text": text,
                        "truncated": len(text) < len(part["text"]),
                    }
                )
                remaining -= len(text)
    return {
        "status": "ok",
        "assessment": {"work_id": exam["id"], "title": exam["title"], "source": exam["source"]},
        "explicit_coverage_passages": assigned[:10],
        "learning_objective_passages": objectives[:10],
        "candidate_readings": candidates[:20],
        "material_excerpts": excerpts,
        "repeated_concepts": repeated_concepts(docs),
        "coverage_status": "explicit_passages_need_interpretation"
        if assigned
        else "not_established",
        "next_step": "ChatGPT can build a cited guide and practice questions from these excerpts. Label inferred relevance; request additional chunks or candidate readings before claiming comprehensive preparation.",
        "figure_interpretation": "unsupported",
        "generated_study_guide": None,
    }


async def academic_request(
    bridge,
    owner,
    ref,
    course_id,
    action="deadlines",
    *,
    material_ids=None,
    work_id=None,
    draft=None,
    include_grades=False,
):
    try:
        async with asyncio.timeout(90):
            bundle = await collect_course(
                bridge, owner, ref, course_id, material_ids, action, work_id
            )
            deadlines = deadline_findings(
                bundle["documents"],
                bundle["items"],
                bundle["timezone"],
                bundle["assignments_complete"],
            )
            if action == "deadlines":
                data = deadlines
            elif action == "instructions":
                data = instruction_report(bundle, work_id, draft)
            elif action == "exam":
                data = exam_pack(bundle, work_id)
            elif action == "audit":
                findings = [
                    *deadlines["findings"],
                    *bundle["submission_conflicts"],
                    *bundle["inaccessible_materials"],
                ]
                matched = {
                    f.get("work_id") for f in findings if f["kind"] == "missing_canvas_deadline"
                }
                for item in bundle["items"]:
                    if item["effective_due"]["kind"] == "known_none" and item["id"] not in matched:
                        findings.append(
                            {
                                "kind": "missing_canvas_due_date",
                                "work_id": item["id"],
                                "evidence": item["source"],
                                "certainty": "confirmed_field_absence",
                                "impact": "Timing is unknown; this may be historical or scheduled elsewhere.",
                                "next_action": "Check the course schedule before treating it as upcoming.",
                            }
                        )
                    instructions = instruction_report(bundle, item["id"])
                    findings.extend({**f, "work_id": item["id"]} for f in instructions["conflicts"])
                    if instructions["requirements_state"] != "present":
                        findings.append(
                            {
                                "kind": "assessment_requirements_unavailable",
                                "work_id": item["id"],
                                "state": instructions["requirements_state"],
                                "evidence": item["source"],
                                "certainty": "description_field_only",
                                "impact": "This description does not establish the full requirements.",
                                "next_action": "Inspect the rubric, quiz instructions and relevant readings.",
                            }
                        )
                grade = None
                if include_grades:
                    from canvas_bridge.grade_audit import grading_request

                    grade_result = await grading_request(
                        bridge, owner, ref, course_id, "audit", material_ids=material_ids
                    )
                    grade = {
                        k: grade_result.data.get(k)
                        for k in (
                            "canvas",
                            "canvas_calculation",
                            "syllabus_calculation",
                            "reconciliation",
                        )
                    }
                    outcome = (grade.get("reconciliation") or {}).get("outcome")
                    if outcome and outcome != "consistent":
                        findings.append(
                            {
                                "kind": "grade_reconciliation",
                                "certainty": outcome,
                                "impact": "Grade consistency needs further evidence or explanation.",
                                "evidence": grade["reconciliation"],
                                "next_action": "Use audit_course_grade and review cited policy rules.",
                            }
                        )
                    bundle["sources"].extend(grade_result.sources)
                priorities = {
                    "conflicting_deadlines": 0,
                    "instruction_conflict": 0,
                    "inconsistent_submission_states": 0,
                    "missing_canvas_deadline": 1,
                    "inaccessible_reading": 1,
                }
                for f in findings:
                    f["priority"] = priorities.get(f["kind"], 2)
                    f["id"] = fingerprint(f)
                findings.sort(key=lambda f: (f["priority"], f["kind"], f["id"]))
                data = {
                    "findings": findings[:60],
                    "findings_truncated": len(findings) > 60,
                    "grade_audit": grade,
                    "checks": {
                        "deadlines": "bounded_sources_checked",
                        "requirements": "explicit_counts_formats_checked",
                        "submission_consistency": "list_and_detail_checked",
                        "grades": "checked" if include_grades else "not_requested",
                        "external_hidden_readings": "not_accessible",
                        "course_schedule_conflicts": "dated_obligations_only; no meeting timetable",
                        "qualitative_rubric_criteria": "requires_source_grounded_interpretation",
                    },
                }
            else:
                raise DomainError("needs_input", "Unknown academic workflow.")
            current, _ = bridge.selected(owner, ref, [course_id])
            if current.epoch != bundle["connection"].epoch:
                raise DomainError("source_changed", "Course selection changed during comparison.")
            data.update(
                course_id=course_id,
                limitations=bundle["limitations"] + data.get("limitations", []),
                unread_materials=True,
                content_boundary="untrusted_source_data",
                source_documents=[
                    {k: d[k] for k in ("id", "title", "version", "complete", "url")}
                    for d in bundle["documents"]
                ],
            )
            return attach(
                Result(
                    status="needs_input" if data.get("status") == "needs_input" else "partial_data",
                    summary="Source-grounded academic evidence. Read coverage before drawing conclusions; no Canvas or calendar records were changed.",
                    data=data,
                    sources=bundle["sources"],
                    meta=bridge.meta(coverage=bundle["coverage"], warnings=bundle["limitations"]),
                )
            )
    except TimeoutError:
        return Result(
            status="partial_data",
            summary="Academic evidence request timed out; no complete audit is available.",
            data={
                "checks": "incomplete",
                "findings": [],
                "absence_of_findings_proves_no_issues": False,
            },
        )
