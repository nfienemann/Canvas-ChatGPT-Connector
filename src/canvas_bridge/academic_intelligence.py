"""Bounded, authorized course evidence shared by academic comparison workflows."""

import asyncio
import re
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from canvas_bridge.academic_rules import (
    citation,
    deadline_findings,
    instruction_findings,
    normalized,
    repeated_concepts,
)
from canvas_bridge.assignment_links import resolve_links
from canvas_bridge.domain import Coverage, DomainError, Result, Source, utcnow
from canvas_bridge.evidence import attach, fingerprint, reconcile_states
from canvas_bridge.material_discovery import discovery_outcome, schedule_candidates
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
MATERIAL_SECONDS = 35
MATERIAL_READ_SECONDS = 15


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
        "policy_discovery": [],
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
                "linked_materials": (
                    await resolve_links(
                        bridge, owner, ref, course, client, fresh.get("description")
                    )
                    if current.id == work_id
                    else {"references": [], "truncated": False}
                ),
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
                bundle["policy_discovery"].append({"kind": "syllabus", "state": "NOT_FOUND"})
                bundle["limitations"].append(
                    "Course syllabus HTML is empty or unavailable; no policy absence is inferred."
                )
        except DomainError as exc:
            if exc.status == "reconnect_required":
                raise
            bundle["policy_discovery"].append(
                {
                    "kind": "syllabus",
                    "state": "ACCESS_DENIED" if exc.status == "permission_denied" else "UNREADABLE",
                }
            )
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
    bundle["limitations"].extend(listing.meta.warnings)
    bundle["inventory_status"] = listing.data["inventory_status"]
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
            if entry.get("material_availability") in {
                "not_in_accessible_inventory",
                "not_resolved_in_this_inventory",
                "inaccessible",
                "previously_discovered_access_not_rechecked",
            }:
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
        candidates = schedule_candidates(resources, listing.data.get("modules", []))
        if purpose == "integrity":
            from canvas_bridge.integrity.discovery import POLICY_NAMES

            candidates = [
                {"material_id": r["id"], "discovery_basis": ["policy_filename_hint_not_evidence"]}
                for r in resources
                if POLICY_NAMES.search(r.get("title", ""))
            ] + candidates
        linked = bundle["assignments"].get(work_id, {}).get("linked_materials", {})
        explicit = [
            {
                "material_id": link["material_id"],
                "title": link["title"],
                "source_version": link.get("source_version"),
                "discovery_basis": ["explicit_assignment_link"],
            }
            for link in linked.get("references", [])
            if link["state"] == "resolved"
        ]
        unique_candidates = {}
        for candidate in [*explicit, *candidates]:
            unique_candidates.setdefault(candidate["material_id"], candidate)
        candidates = list(unique_candidates.values())
        targets = [c["material_id"] for c in candidates]
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
        candidates = [
            {"material_id": target, "discovery_basis": ["explicit_selection"]} for target in targets
        ]
    discovery = {
        "mode": "automatic" if material_ids is None else "explicit",
        "candidate_count": len(targets),
        "document_limit": MAX_DOCUMENTS,
        "time_budget_seconds": MATERIAL_SECONDS,
        "inventory_complete": listing.status == "ok",
        "documents": [],
    }
    bundle["material_discovery"] = discovery
    hints = {c["material_id"]: c for c in candidates}
    if len(targets) > MAX_DOCUMENTS:
        bundle["limitations"].append(
            "Only three source documents can be read in one request; additional versions remain unchecked."
        )
    deadline = asyncio.get_running_loop().time() + MATERIAL_SECONDS
    for index, material_id in enumerate(targets):
        record = {**hints.get(material_id, {"material_id": material_id}), "state": "pending"}
        discovery["documents"].append(record)
        if index >= MAX_DOCUMENTS:
            record.update(state="skipped", reason_code="MATERIAL_DOCUMENT_LIMIT")
            continue
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            record.update(state="skipped", reason_code="MATERIAL_TIME_BUDGET")
            continue
        with bridge.store.transaction() as session:
            row = bridge.store.owned(session, Material, owner, ref, material_id)
            if row.course_id != course_ref:
                raise DomainError("permission_denied", "Document is outside the requested course.")
        try:
            async with asyncio.timeout(min(remaining, MATERIAL_READ_SECONDS)):
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

                if row.kind == "file":
                    from canvas_bridge.course_files import checked_row

                    row = checked_row(bridge, session, owner, ref, material_id, conn.epoch)

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
                    source_updated_at=fact_date(row.file_state, "source_updated_at").timestamp,
                )
                doc = document(
                    src,
                    row.text,
                    parts=parts,
                    complete=fetched.data.get("coverage") == "text_only",
                )
                doc["source_version"] = row.file_state.get("version")
                bundle["documents"].append(doc)
                usable = bool(row.text.strip())
                record.update(
                    state="reviewed"
                    if doc["complete"] and usable
                    else "partially_reviewed"
                    if usable
                    else "unreadable",
                    reason_code=None if usable else "MATERIAL_NO_USABLE_TEXT",
                    source_version=doc["source_version"],
                    content_hash=row.version_hash,
                    extraction_coverage=fetched.data.get("coverage"),
                    locators=[p["locator"] for p in parts],
                )
        except TimeoutError:
            record.update(state="failed", status="retry_later", reason_code="MATERIAL_READ_TIMEOUT")
            bundle["limitations"].append(
                "A selected material exceeded its read budget; it was not reviewed."
            )
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            record.update(
                state="inaccessible" if exc.status == "permission_denied" else "failed",
                status=exc.status,
                reason_code=exc.reason_code or "MATERIAL_READ_FAILED",
            )
            bundle["inaccessible_materials"].append(
                {
                    "material_id": material_id,
                    "kind": "inaccessible_reading",
                    "certainty": "retrieval_limitation",
                    "impact": "Requested source text could not be read.",
                    "reason": exc.message,
                    "reason_code": exc.reason_code or "MATERIAL_READ_FAILED",
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
    links = bundle["assignments"].get(item["id"], {}).get("linked_materials", {})
    linked_ids = {
        link["material_id"] for link in links.get("references", []) if link["state"] == "resolved"
    }
    for doc in bundle["documents"]:
        if doc["id"] in linked_ids:
            result.append(doc)
            continue
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
    links = deepcopy(assignment.get("linked_materials", {"references": [], "truncated": False}))
    readings = {
        r["material_id"]: r for r in bundle.get("material_discovery", {}).get("documents", [])
    }
    for link in links["references"]:
        reading = readings.get(link["material_id"])
        link["reading_state"] = reading["state"] if reading else "not_reviewed"
        link["content_reviewed"] = bool(
            reading and reading["state"] in {"reviewed", "partially_reviewed"}
        )
        if reading and reading.get("reason_code"):
            link["reading_reason_code"] = reading["reason_code"]
    links["linked_content_reviewed"] = any(link["content_reviewed"] for link in links["references"])
    linked_ids = {
        link["material_id"] for link in links["references"] if link["state"] == "resolved"
    }
    result = instruction_findings(docs, draft)
    result.update(
        work_id=work_id,
        requirements_state=assignment["requirements_state"],
        linked_materials=links,
        instruction_document_review={
            "description_present": bool(assignment["instructions"]["parts"][0]["text"]),
            "documents": [
                record
                for record in bundle.get("material_discovery", {}).get("documents", [])
                if record["material_id"] in linked_ids
            ],
            "scope": "Explicit linked documents have individual reading outcomes; a filename is not reviewed instructions.",
        },
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
    from canvas_bridge.academic.independent_engine import bounded_excerpts

    excerpts = bounded_excerpts(docs)
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
    include_discussions=False,
):
    try:
        async with asyncio.timeout(90):
            bundle = await collect_course(
                bridge, owner, ref, course_id, material_ids, action, work_id
            )
            integrity_decision = None
            if action == "exam":
                from canvas_bridge.integrity.models import Activity, AssistanceRequest, Scope

                integrity_decision, _ = await bridge.integrity.evaluate(
                    owner,
                    AssistanceRequest(
                        scope=Scope(connection_id=ref, course_id=course_id, assessment_id=work_id),
                        activity=Activity.EXAM_PREPARATION,
                    ),
                    bundle=bundle,
                )
                integrity_decision.require()
            deadlines = deadline_findings(
                bundle["documents"],
                bundle["items"],
                bundle["timezone"],
                bundle["assignments_complete"],
            )
            bundle["material_discovery"] = discovery_outcome(
                bundle["material_discovery"], deadlines["obligations"]
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
                discussion_report = None
                if include_discussions:
                    from canvas_bridge.discussion_integration import discussion_audit

                    discussion_report, discussion_sources = await discussion_audit(
                        bridge, owner, ref, course_id, bundle["items"]
                    )
                    findings.extend(discussion_report["findings"])
                    bundle["sources"].extend(discussion_sources)
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
                    "discussion_audit": discussion_report,
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
            if action in {"deadlines", "audit"}:
                from canvas_bridge.academic_evidence import course_deadline_graph

                data["evidence_graph"] = course_deadline_graph(
                    bridge, owner, ref, bundle, deadlines
                )
            data.update(
                course_id=course_id,
                academic_integrity=integrity_decision.model_dump(mode="json")
                if integrity_decision
                else {
                    "activity": "administration_or_requirements",
                    "completion_permission": "not_granted",
                },
                limitations=bundle["limitations"] + data.get("limitations", []),
                unread_materials=True,
                content_boundary="untrusted_source_data",
                material_discovery=bundle["material_discovery"],
                inventory_status=bundle["inventory_status"],
                inventory_coverage=bundle["outline"]["inventory_coverage"],
                inventory_failures=bundle["outline"]["inventory_failures"],
                source_documents=[
                    {
                        k: d.get(k)
                        for k in (
                            "id",
                            "title",
                            "version",
                            "source_version",
                            "source_updated_at",
                            "complete",
                            "url",
                        )
                    }
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
