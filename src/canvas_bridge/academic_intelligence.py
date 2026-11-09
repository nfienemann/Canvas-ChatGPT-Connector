"""Bounded, authorized course evidence shared by academic comparison workflows."""

import asyncio
import re
from copy import deepcopy
from datetime import timedelta
from time import monotonic
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
    canonical_id,
    fact_date,
    normalize_assignment,
    plain_text,
)
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.privacy_text import WITHHELD
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material, aware

EXAM_TITLE = re.compile(r"\b(?:quiz|exam|test|midterm|final)\b", re.I)
MAX_ASSIGNMENTS = 30
MAX_DOCUMENTS = 3
MATERIAL_SECONDS = 35
MATERIAL_READ_SECONDS = 15
EXAM_BATCH_SECONDS = 20
EXAM_FIRST_FILE_SETUP_SECONDS = 25
THOROUGH_BATCH_LIMIT = 20


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
    bridge,
    owner,
    ref,
    course_ref,
    material_ids=None,
    purpose=None,
    work_id=None,
    *,
    review_mode="standard",
    task_deadline=None,
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
        assignment_candidates = assignments.items[:MAX_ASSIGNMENTS]
        if purpose == "integrity" or (purpose == "exam" and work_id):
            # Course policy discovery needs only this assessment's instructions,
            # not detail requests for every unrelated assignment in the course.
            assignment_candidates = [
                raw
                for raw in assignments.items
                if work_id
                and canonical_id(
                    owner, ref, "assignment", f"{course.source_id}:{source_id(raw['id'])}"
                )
                == work_id
            ][:1]
            bundle["limitations"].append(
                "Assessment-specific discovery inspects details only for the requested assessment; unrelated assignment instructions were not read."
            )
        elif purpose == "exam":
            assignment_candidates = [
                raw for raw in assignments.items if EXAM_TITLE.search(str(raw.get("name", "")))
            ][:MAX_ASSIGNMENTS]
        descriptions = {}
        for raw in assignment_candidates:
            if raw.get("published") is False or raw.get("locked_for_user") is True:
                bundle["assignments_complete"] = False
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
                    bundle["assignments_complete"] = False
                    bundle["limitations"].append(
                        "An assessment became inaccessible during retrieval."
                    )
                    continue
            except DomainError as exc:
                if exc.status in {"reconnect_required", "permission_denied"}:
                    if exc.status == "reconnect_required":
                        raise
                    bundle["assignments_complete"] = False
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
            if purpose == "exam" and not work_id:
                descriptions[current.id] = fresh.get("description")
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
        if purpose == "exam" and not work_id:
            selected_exam, _ = select_exam(bundle)
            if selected_exam:
                work_id = selected_exam["id"]
                bundle["assignments"][work_id]["linked_materials"] = await resolve_links(
                    bridge, owner, ref, course, client, descriptions[work_id]
                )
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
            ]
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
        nearby = []
        if purpose == "exam":
            exam, _ = select_exam(bundle, work_id)
            nearby = [
                {**reading, "discovery_basis": [reading["basis"]]}
                for reading in module_readings(bundle, exam)
            ]
        unique_candidates = {}
        for candidate in [*explicit, *nearby, *candidates]:
            unique_candidates.setdefault(candidate["material_id"], candidate)
        candidates = list(unique_candidates.values())
        targets = list(unique_candidates)
    else:
        targets = list(dict.fromkeys(material_ids))
        candidates = [
            {"material_id": target, "discovery_basis": ["explicit_selection"]} for target in targets
        ]
    thorough = purpose == "exam" and review_mode == "thorough"
    document_limit = (12 if thorough else 6) if purpose == "exam" else MAX_DOCUMENTS
    seconds = (90 if thorough else 60) if purpose == "exam" else MATERIAL_SECONDS
    discovery = {
        "mode": "automatic" if material_ids is None else "explicit",
        "candidate_count": len(targets),
        "document_limit": document_limit,
        "time_budget_seconds": seconds,
        "inventory_complete": listing.status == "ok",
        "documents": [],
    }
    bundle["material_discovery"] = discovery
    hints = {c["material_id"]: c for c in candidates}
    if len(targets) > document_limit:
        bundle["limitations"].append(
            f"At most {document_limit} candidate documents are attempted per pass."
        )
    started = monotonic()
    deadline = min(started + seconds, task_deadline or float("inf"))
    # Queue one batch per candidate before spending any spare slots on PDF depth.
    queue = [(target, None) for target in targets]
    records = {}
    cold_allowance = purpose == "exam"
    blocked = None
    batches = 0
    for material_id, resume in queue:
        if resume is None:
            record = {**hints.get(material_id, {"material_id": material_id}), "state": "pending"}
            discovery["documents"].append(record)
            records[material_id] = record
            if len(records) > document_limit:
                record.update(state="skipped", reason_code="MATERIAL_DOCUMENT_LIMIT")
                continue
        else:
            record = records[material_id]
            if batches >= THOROUGH_BATCH_LIMIT or blocked or monotonic() >= deadline:
                continue
        if blocked:
            record.update(state="skipped", reason_code=blocked)
            continue
        remaining = deadline - monotonic()
        if remaining <= 0:
            record.update(state="skipped", reason_code="MATERIAL_TIME_BUDGET")
            continue
        with bridge.store.transaction() as session:
            row = bridge.store.owned(session, Material, owner, ref, material_id)
            if row.course_id != course_ref:
                raise DomainError("permission_denied", "Document is outside the requested course.")
        try:
            allowance = MATERIAL_READ_SECONDS
            if purpose == "exam":
                # One cold file gets setup headroom. Each later batch has its own slice.
                allowance = EXAM_BATCH_SECONDS
                if cold_allowance and row.kind == "file":
                    allowance += EXAM_FIRST_FILE_SETUP_SECONDS
                    cold_allowance = False
                # When discovery ran long, leave other candidates a turn.
                if resume is None and len(records) < min(document_limit, len(targets)):
                    allowance = min(allowance, remaining / 2)
            batches += 1
            async with asyncio.timeout(min(remaining, allowance)):
                if resume:
                    from canvas_bridge.course_files import read_file

                    fetched = await read_file(bridge, owner, ref, material_id, **resume)
                else:
                    fetched = await fetch_material(bridge, owner, ref, material_id, length=1000)
            if not resume:
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
                withheld = purpose == "exam" and any(WITHHELD in p["text"] for p in parts)
                if withheld:
                    for part in parts:
                        if WITHHELD in part["text"]:
                            part["text"] = ""
                doc = document(
                    src,
                    row.text,
                    parts=parts,
                    complete=fetched.data.get("coverage") == "text_only" and not withheld,
                )
                doc["source_version"] = row.file_state.get("version")
                if resume:
                    bundle["documents"] = [d for d in bundle["documents"] if d["id"] != material_id]
                bundle["documents"].append(doc)
                usable = any(p["text"].strip() for p in parts)
                record.update(
                    state="reviewed"
                    if doc["complete"] and usable
                    else "partially_reviewed"
                    if usable
                    else "unreadable",
                    reason_code="MATERIAL_CONTENT_WITHHELD"
                    if withheld
                    else None
                    if usable
                    else "MATERIAL_NO_USABLE_TEXT",
                    source_version=doc["source_version"],
                    content_hash=row.version_hash,
                    extraction_coverage="partial" if withheld else fetched.data.get("coverage"),
                    locators=[p["locator"] for p in parts],
                )
                if purpose == "exam":
                    next_batch = extraction_progress(row, doc, record, ref)
                    if (
                        thorough
                        and next_batch
                        and (not resume or next_batch["page_start"] > resume["page_start"])
                    ):
                        queue.append((material_id, next_batch))
        except TimeoutError:
            if resume:
                record.update(reason_code="MATERIAL_READ_TIMEOUT")
                continue
            record.update(state="failed", status="retry_later", reason_code="MATERIAL_READ_TIMEOUT")
            bundle["limitations"].append(
                "A selected material exceeded its read budget; it was not reviewed."
            )
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            if purpose == "exam" and exc.reason_code in {
                "TASK_BUDGET_EXCEEDED",
                "UPSTREAM_THROTTLED",
                "RATE_LIMITED",
                "OWNER_RATE_LIMITED",
                "WORKFLOW_BUDGET_EXHAUSTED",
                "UPSTREAM_BUDGET_EXHAUSTED",
            }:
                blocked = exc.reason_code
            if resume and exc.status != "permission_denied":
                record.update(reason_code=exc.reason_code or "MATERIAL_READ_FAILED")
                continue
            if resume:
                bundle["documents"] = [d for d in bundle["documents"] if d["id"] != material_id]
                record.pop("extraction_continuation", None)
                for key in (
                    "total_extracted_characters",
                    "extracted_pages",
                    "usable_pages",
                    "locators",
                    "extraction_coverage",
                ):
                    record.pop(key, None)
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
    if purpose == "exam":
        discovery.update(
            review_mode=review_mode,
            batches_attempted=batches,
            batch_limit=THOROUGH_BATCH_LIMIT if thorough else document_limit,
            elapsed_seconds=round(monotonic() - started, 3),
        )
        if pending := [
            d["material_id"]
            for d in records.values()
            if d["state"] == "skipped"
            or (
                d["state"] == "failed"
                and (
                    d.get("status") == "retry_later"
                    or (blocked is not None and d.get("reason_code") == blocked)
                )
            )
        ]:
            discovery["continuation"] = dict(
                connection_id=ref,
                course_id=course_ref,
                work_id=work_id,
                material_ids=pending[:document_limit],
                review_mode=review_mode,
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


def linked_reading_outcomes(bundle, assignment):
    links = deepcopy(assignment.get("linked_materials", {"references": [], "truncated": False}))
    readings = {
        r["material_id"]: r for r in bundle.get("material_discovery", {}).get("documents", [])
    }
    for link in links["references"]:
        reading = readings.get(link.get("material_id"))
        link["reading_state"] = reading["state"] if reading else "not_reviewed"
        link["content_reviewed"] = bool(
            reading and reading["state"] in {"reviewed", "partially_reviewed"}
        )
        if reading and reading.get("reason_code"):
            link["reading_reason_code"] = reading["reason_code"]
    links["linked_content_reviewed"] = any(link["content_reviewed"] for link in links["references"])
    return links


def instruction_report(bundle, work_id, draft=None):
    item = next((i for i in bundle["items"] if i["id"] == work_id), None)
    if item is None:
        raise DomainError(
            "permission_denied", "Assignment is not available in this course evidence."
        )
    assignment = bundle["assignments"][work_id]
    docs = [assignment["instructions"], assignment["rubric"], *related_documents(bundle, item)]
    links = linked_reading_outcomes(bundle, assignment)
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
        related_documents(bundle, item),
        bundle["items"],
        bundle["timezone"],
        bundle["assignments_complete"],
    )
    return result


def select_exam(bundle, work_id=None):
    from canvas_bridge.domain import WorkItem
    from canvas_bridge.planning import is_actionable

    now = utcnow()
    eligible = [
        i
        for i in bundle["items"]
        if EXAM_TITLE.search(i["title"]) and is_actionable(WorkItem.model_validate(i))
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
    return exam, eligible


def module_readings(bundle, exam):
    candidates = []
    if not exam:
        return candidates
    for module in (bundle["outline"] or {}).get("modules", []):
        if any(
            i.get("type") in {"Assignment", "Quiz"}
            and normalized(i.get("title", "")) == normalized(exam["title"])
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
    return candidates


def extraction_progress(row, doc, record, ref):
    from canvas_bridge.document_policy import PDF_BATCH_PAGES
    from canvas_bridge.parser_worker import MAX_TEXT

    record["total_extracted_characters"] = sum(len(p["text"]) for p in doc["parts"])
    if record["state"] == "partially_reviewed" and not record["reason_code"]:
        record["reason_code"] = "MATERIAL_EXTRACTION_PARTIAL"
    if row.kind != "file":
        return None
    doc["part_pages"] = [p["page"] for p in row.locators]
    if row.file_state.get("format") != "pdf":
        return None
    present = set(doc["part_pages"])
    count = row.file_state["page_count"]
    record.update(
        page_count=count,
        extracted_pages=sorted(present),
        usable_pages=[
            n for n, p in zip(doc["part_pages"], doc["parts"], strict=True) if p["text"].strip()
        ],
    )
    first = next((n for n in range(1, count + 1) if n not in present), None)
    record.pop("extraction_continuation", None)
    if first is None or len(row.text) + 2 > MAX_TEXT:
        return None
    args = dict(
        expected_hash=row.version_hash,
        expected_parser=row.file_state["parser"],
        page_start=first,
        page_end=count,
    )
    record["extraction_continuation"] = dict(connection_id=ref, file_id=row.id, **args)
    # Caller-facing cursor spans the remaining source so read_course_file can return
    # another cursor. Internal turns stop before an already-extracted page.
    return {
        **args,
        "page_end": min(
            count,
            first + PDF_BATCH_PAGES - 1,
            min((n - 1 for n in present if n > first), default=count),
        ),
    }


def assessment_excerpts(bundle):
    """A fair bounded prefix per source, with a reader cursor at its first omission."""
    records = {
        r["material_id"]: r for r in bundle.get("material_discovery", {}).get("documents", [])
    }
    docs = [d for d in bundle["documents"] if any(p["text"] for p in d["parts"])]
    remaining = 16_000
    excerpts = []
    for i, doc in enumerate(docs):
        allowance = min(4000, remaining // (len(docs) - i))
        delivered = 0
        record = records.get(doc["id"])
        for index, part in enumerate(doc["parts"]):
            text = part["text"][:allowance] if index < 4 else ""
            if text:
                excerpts.append(
                    {
                        **citation(doc, part, text),
                        "text": text,
                        "truncated": len(text) < len(part["text"]),
                    }
                )
                delivered += len(text)
                remaining -= len(text)
                allowance -= len(text)
            if len(text) < len(part["text"]):
                if record is not None:
                    args = dict(
                        connection_id=bundle["connection"].id,
                        expected_hash=doc["version"],
                        offset=len(text),
                        length=8000,
                    )
                    if "part_pages" in doc:
                        args.update(
                            file_id=doc["id"],
                            page_start=doc["part_pages"][index],
                            page_end=doc["part_pages"][-1],
                        )
                    else:
                        args.update(material_id=doc["id"])
                    record["excerpt_continuation"] = args
                break
        if record is not None:
            record.update(
                excerpt_characters=delivered,
                excerpt_truncated=delivered < record["total_extracted_characters"],
            )
    return excerpts


def exam_pack(bundle, work_id=None):
    exam, eligible = select_exam(bundle, work_id)
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
    assigned, objectives = [], []
    instructions = bundle["assignments"][exam["id"]]["instructions"]
    for doc in [instructions, *related_documents(bundle, exam)]:
        for part in doc["parts"]:
            for line in part["text"].splitlines():
                assessment_context = doc is instructions or normalized(exam["title"]) in normalized(
                    line
                )
                if (
                    len(assigned) < 10
                    and assessment_context
                    and re.search(
                        r"\b(?:covers|coverage|includes|read|reading|required|study)\b", line, re.I
                    )
                ):
                    assigned.append(citation(doc, part, line))
                if len(objectives) < 10 and re.search(
                    r"\b(?:objective|learn|explain|compare|describe|analyze)\b", line, re.I
                ):
                    objectives.append(citation(doc, part, line))
    candidates = module_readings(bundle, exam)
    excerpts = assessment_excerpts(bundle)
    return {
        "status": "ok",
        "assessment": {"work_id": exam["id"], "title": exam["title"], "source": exam["source"]},
        "linked_materials": linked_reading_outcomes(bundle, bundle["assignments"][exam["id"]]),
        "explicit_coverage_passages": assigned[:10],
        "learning_objective_passages": objectives[:10],
        "candidate_readings": candidates[:20],
        "candidate_readings_truncated": len(candidates) > 20,
        "material_excerpts": excerpts,
        "repeated_concepts": repeated_concepts(
            [d for d in docs if d["source_type"] in {"canvas_file", "canvas_page"}]
        ),
        "coverage_status": "explicit_passages_need_interpretation"
        if assigned
        else "not_established",
        "next_step": "Use material_discovery.continuation with prepare_for_assessment for the next group of deferred documents. Use extraction_continuation with read_course_file for missing PDF pages. Use excerpt_continuation with read_course_file (file_id) or fetch_course_material (material_id) for additional source text. Follow reader continuations. Keyword overlap is a study heuristic; assessment scope requires assessment-specific evidence.",
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
    registrar_lookup=None,
    review_mode="standard",
):
    bundle = None
    try:
        total_seconds = 135 if action == "exam" and review_mode == "thorough" else 90
        async with asyncio.timeout(total_seconds):
            bundle = await collect_course(
                bridge,
                owner,
                ref,
                course_id,
                material_ids,
                action,
                work_id,
                **(
                    {"review_mode": review_mode, "task_deadline": monotonic() + total_seconds - 10}
                    if action == "exam"
                    else {}
                ),
            )
            integrity_decision = None
            if action == "exam":
                from canvas_bridge.integrity.models import Activity, AssistanceRequest, Scope

                selected_exam, _ = select_exam(bundle, work_id)
                if selected_exam:
                    work_id = selected_exam["id"]
                integrity_decision, _ = await bridge.integrity.evaluate(
                    owner,
                    AssistanceRequest(
                        scope=Scope(connection_id=ref, course_id=course_id, assessment_id=work_id),
                        activity=Activity.EXAM_PREPARATION,
                    ),
                    bundle=bundle,
                )
                integrity_decision.require()
                review = bundle["material_discovery"]
                review["state"] = (
                    "no_candidates"
                    if not review["documents"]
                    else "reviewed"
                    if all(d["state"] == "reviewed" for d in review["documents"])
                    else "partial"
                )
            else:
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
                            "classification",
                            "timeout_stage",
                            "missing_information",
                            "reason_code",
                        )
                    }
                    grade["status"] = grade_result.status
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
                    "obligation_groups": deadlines["obligation_groups"],
                    "comparisons": deadlines["comparisons"],
                    "grade_audit": grade,
                    "discussion_audit": discussion_report,
                    "checks": {
                        "requirements": "explicit_counts_formats_checked",
                        "submission_consistency": "list_and_detail_checked",
                        "grades": "not_requested"
                        if grade is None
                        else "checked"
                        if grade["status"] == "ok"
                        else grade["status"],
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
                from canvas_bridge.registrar import final_gaps, lookup_handoff

                handoff = lookup_handoff(
                    final_gaps(bundle["items"], bundle["documents"], deadlines["findings"]),
                    registrar_lookup,
                    allowed_courses=[course_id],
                )
                if handoff:
                    data["registrar_lookup"] = handoff

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
            summary = "Source-grounded academic evidence. Read coverage before drawing conclusions; no Canvas or calendar records were changed."
            if action in {"deadlines", "audit"}:
                coverage = data["evidence_graph"]["audit_coverage"]
                if action == "audit":
                    data["checks"]["deadlines"] = coverage["cross_source_comparison"]
                if coverage["cross_source_comparison"] != "complete_at_available_precision":
                    summary = "Cross-source deadline consistency is not established. Review matched passages, comparison precision and retrieval gaps."
            return attach(
                Result(
                    status="needs_input" if data.get("status") == "needs_input" else "partial_data",
                    summary=summary,
                    data=data,
                    sources=bundle["sources"],
                    meta=bridge.meta(coverage=bundle["coverage"], warnings=bundle["limitations"]),
                )
            )
    except TimeoutError:
        # A timed-out integrity evaluation cannot release source text. Retain counts only.
        progress = {}
        if action == "exam" and bundle:
            discovery = bundle["material_discovery"]
            progress = {
                "candidate_count": discovery["candidate_count"],
                "batches_attempted": discovery["batches_attempted"],
            }
        return Result(
            status="partial_data",
            summary="Academic evidence request timed out; no complete audit is available.",
            data={
                **progress,
                "checks": "incomplete",
                "findings": [],
                "absence_of_findings_proves_no_issues": False,
            },
        )
