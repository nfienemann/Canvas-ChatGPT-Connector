"""Read-only evidence acquisition and orchestration for the native MCP grade tools."""

import asyncio
import re

from canvas_bridge.course_files import page_label
from canvas_bridge.domain import DomainError, Result, Source, utcnow
from canvas_bridge.grading_engine import (
    GradeScenario,
    Mode,
    PolicyReview,
    digest,
    reconcile,
)
from canvas_bridge.grading_policy import extract_policy
from canvas_bridge.normalize import plain_text
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material

MAX_DOCUMENTS = 3


async def collect(bridge, owner, ref, course_ref):
    from canvas_bridge.providers.canvas_grades import collect as collect_canvas

    return await collect_canvas(bridge, owner, ref, course_ref)


async def syllabus_documents(bridge, owner, ref, evidence, material_ids):
    course, config = evidence["course"], evidence["config"]
    documents, limits = [], []
    html = config.get("syllabus_body")
    if isinstance(html, str) and html.strip():
        text = plain_text(html, 100_001)
        documents.append(
            {
                "id": course.id + "_syllabus",
                "course_id": course.id,
                "source_type": "syllabus",
                "title": "Canvas course syllabus",
                "url": f"{evidence['origin']}/courses/{course.source_id}/assignments/syllabus",
                "version": digest(html),
                "retrieved_at": utcnow().isoformat(),
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
                        "course_id": course.id,
                        "source_type": "canvas_" + row.kind,
                        "title": row.title,
                        "url": row.url,
                        "version": row.version_hash,
                        "retrieved_at": utcnow().isoformat(),
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
                    Source(
                        id=d["id"],
                        title=d["title"],
                        url=d["url"],
                        retrieved_at=utcnow(),
                        course_id=d.get("course_id"),
                        resource_id=d["id"],
                        source_type=d.get("source_type", "unknown"),
                        content_hash=d.get("version"),
                    )
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
            from canvas_bridge.academic.services import calculate_grade
            from canvas_bridge.providers.canvas import AuthorizedCanvasProvider

            provider = AuthorizedCanvasProvider(bridge, owner, ref)

            def normalized_calculation(chosen, mode="current_graded", scenario=None):
                authorized = provider.calculation_input(evidence, chosen)
                result = calculate_grade(provider.gateway, authorized, mode=mode, scenario=scenario)
                data.setdefault("evidence_graphs", []).append(result["evidence_graph"])
                return result["calculation"]

            if action == "audit":
                reproduced = normalized_calculation(policy)
                estimate = normalized_calculation(syllabus_policy, "syllabus_current")
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
                data["calculation"] = normalized_calculation(chosen, mode, scenario)
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
            if syllabus is not None:
                from canvas_bridge.academic_evidence import course_grade_rule_graph

                data["rule_evidence_graph"] = course_grade_rule_graph(
                    bridge, owner, ref, evidence, syllabus, documents
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
