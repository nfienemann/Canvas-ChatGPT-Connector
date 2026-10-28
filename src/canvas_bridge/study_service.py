"""Source-bound study sessions and explicitly requested local practice results."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import select

from canvas_bridge.authorization import (
    RequestAuthorization,
    request_authorization,
    validate_request_authorization,
)
from canvas_bridge.domain import DomainError, Result, opaque_id, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_sources import resolve_sources
from canvas_bridge.figure_observations import record_observation
from canvas_bridge.policy_surfaces import authorize_tool
from canvas_bridge.retrieval import fetch_material
from canvas_bridge.storage import LocalRecord, Material
from canvas_bridge.study_engine import (
    evaluate,
    extract_concepts,
    questions,
    relationships,
    review_recommendation,
)
from canvas_bridge.study_models import PracticeSubmission, StudyPreferences, StudyRequest
from canvas_bridge.workflow_budget import Budget, active_budget
from canvas_bridge.workflow_registry import Limits


def check(bridge, owner, ref, courses, epoch, tool):
    authorize_tool(bridge, owner, tool, {"connection_id": ref})
    conn, _ = bridge.selected(owner, ref, courses)
    if conn.epoch != epoch:
        raise DomainError("source_changed", "Course scope changed; start a new study session.")
    validate_request_authorization(bridge)


def permitted(bridge, owner, ref, result, tool):
    from canvas_bridge.integrity.surfaces import guard_result

    guard_result(bridge, owner, tool, {"connection_id": ref}, result)
    contexts, _ = resolve_sources(bridge.egress, owner, {"connection_id": ref}, result, tool)
    if any(
        c.classification
        in {
            CC.RESTRICTED_ASSESSMENT,
            CC.THIRD_PARTY_EDUCATIONAL_RECORD,
            CC.CONFIDENTIAL_RESEARCH,
            CC.UNKNOWN_OR_UNCLASSIFIED,
        }
        for c in contexts
    ):
        raise DomainError(
            "permission_denied",
            "This source is not permitted for study reuse.",
            reason_code="STUDY_SOURCE_RESTRICTED",
        )
    # Derived practice and receipt contents inherit the original sources' policy.
    bridge.egress.release(result, owner, {"connection_id": ref}, tool_name=tool)


async def read_documents(bridge, owner, ref, ids, tool, expected=None):
    await bridge.refresh_course_access(owner, ref)
    courses = []
    with bridge.store.transaction() as session:
        for ident in ids:
            row = bridge.store.owned(session, Material, owner, ref, ident)
            courses.append(row.course_id)
    courses = list(dict.fromkeys(courses))
    if len(courses) > 3:
        raise DomainError("needs_input", "Choose materials from at most three selected courses.")
    conn, _ = bridge.selected(owner, ref, courses)
    from canvas_bridge.integrity.surfaces import before_tool

    for course in courses:
        await before_tool(bridge, owner, tool, {"connection_id": ref, "course_id": course})
    documents, sources, limitations = [], [], []
    for ident in ids:
        check(bridge, owner, ref, courses, conn.epoch, tool)
        try:
            async with asyncio.timeout(20):
                result = await fetch_material(
                    bridge,
                    owner,
                    ref,
                    ident,
                    length=12_000,
                    expected_hash=(expected or {}).get(ident),
                )
            if result.status not in {"ok", "partial_data"} or not result.sources:
                raise DomainError("partial_data", "Document content is unavailable.")
            with bridge.store.transaction() as session:
                row = bridge.store.owned(session, Material, owner, ref, ident)
                content_hash = result.data.get("content_hash")
                if not content_hash or content_hash != row.version_hash:
                    raise DomainError(
                        "source_changed", "Source version could not be bound to the study passage."
                    )
                if expected and content_hash != expected[ident]:
                    raise DomainError(
                        "source_changed", "Source changed since the practice question was prepared."
                    )
                source = result.sources[0].model_copy(
                    update={
                        "course_id": row.course_id,
                        "content_hash": content_hash,
                        "resource_id": row.id,
                    }
                )
                passages = result.data.get("passages") or [
                    {"text": result.data.get("text", ""), "locator": source.locator}
                ]
                passages = [
                    {
                        "text": p["text"],
                        "locator": p.get("locator")
                        or (f"Page {p['page']}" if "page" in p else source.locator),
                    }
                    for p in passages
                ]
                documents.append(
                    {
                        "material_id": ident,
                        "course_id": row.course_id,
                        "title": row.title,
                        "source_id": source.id,
                        "content_hash": content_hash,
                        "passages": passages,
                    }
                )
            permitted(bridge, owner, ref, result.model_copy(update={"sources": [source]}), tool)
            sources.append(source)
            if result.status != "ok" or result.data.get("next_offset") is not None:
                limitations.append(
                    "A selected document has incomplete extraction or additional unread text; questions cover only quoted passages."
                )
        except TimeoutError:
            limitations.append("A selected document timed out and was omitted.")
        except DomainError as exc:
            if (
                exc.status in {"permission_denied", "reconnect_required", "source_changed"}
                or expected
            ):
                raise
            limitations.append("A selected document could not be read and was omitted.")
        check(bridge, owner, ref, courses, conn.epoch, tool)
    return conn.epoch, courses, documents, sources, limitations


def history(bridge, owner, ref, concept_ids):
    with bridge.store.transaction() as session:
        rows = session.scalars(
            select(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind == "practice",
                LocalRecord.key.in_(concept_ids),
            )
        ).all()
        return {r.key: {**r.payload, "version": r.version} for r in rows}


async def prepare(bridge, owner, ref, request: StudyRequest):
    tool = "prepare_study_session"
    authorize_tool(bridge, owner, tool, {"connection_id": ref})
    epoch, courses, documents, sources, limitations = await read_documents(
        bridge, owner, ref, request.material_ids, tool
    )
    concepts = extract_concepts(documents, request.concept_names)
    links = relationships(concepts, documents)
    if len(concepts) == 40:
        limitations.append(
            "The 40-concept limit was reached; narrow the selection for fuller coverage."
        )
    state = (
        history(bridge, owner, ref, [c["id"] for c in concepts]) if request.include_history else {}
    )
    if request.mode == "focused_review" and request.include_history:
        rank = {
            "attempted_incorrect": 0,
            "attempted_unresolved": 0,
            "correct_with_assistance": 1,
            "not_attempted": 2,
            "correct_independently": 3,
        }
        concepts.sort(
            key=lambda c: (
                rank.get(state.get(c["id"], {}).get("practice_state", "not_attempted"), 2),
                c["id"],
            )
        )
    bank = questions(concepts, request.preferences)
    if len(concepts) >= 40:
        bank = []  # Unexamined definitions could make a supposedly unique answer ambiguous.
    if request.mode == "figure_practice":
        bank = []
        for report in request.visual_reports:
            if report.file_id not in request.material_ids:
                raise DomainError("permission_denied", "The figure is outside this study session.")
            result = await record_observation(
                bridge, owner, ref, report.render_receipt, report.observation
            )
            if result.data.get("file_id") != report.file_id:
                raise DomainError(
                    "permission_denied", "Figure receipt does not match the requested material."
                )
            permitted(bridge, owner, ref, result, tool)
            if result.data.get("fallback_reason"):
                limitations.append(
                    "A figure was reported unreadable; no question was generated for it."
                )
                continue
            source = result.sources[0]
            if not any(
                d["material_id"] == report.file_id and d["content_hash"] == source.content_hash
                for d in documents
            ):
                raise DomainError(
                    "source_changed",
                    "The figure and study text do not refer to the same document version.",
                )
            from canvas_bridge.evidence import fingerprint

            ident = fingerprint([source.id, source.content_hash, source.locator])[:40]
            bank.append(
                {
                    "id": ident,
                    "concept_id": ident,
                    "course_id": source.course_id,
                    "material_id": report.file_id,
                    "source_id": source.id,
                    "locator": source.locator,
                    "prompt": "Inspect this figure. Describe its axes or panels, the visible comparison, and what the image cannot establish.",
                    "generated_practice": True,
                    "not_instructor_exam": True,
                    "format": "figure_open_ended",
                    "expected_answer": "Requires visual review against the cited figure; there is no automatically verified scientific answer.",
                    "source_passage": "",
                    "rubric": [
                        "Identify labels and units only when legible.",
                        "Separate visible features from scientific inference.",
                        "State uncertainty and avoid unsupported numerical precision.",
                    ],
                    "verification": "source_provenance_only_visual_accuracy_unverified",
                }
            )
            sources.append(source)
        if not bank:
            limitations.append(
                "Figure practice requires an inspected permitted figure and its current render receipt."
            )
    practice_mode = request.mode in {
        "active_recall",
        "practice_assessment",
        "focused_review",
        "figure_practice",
    }
    if not practice_mode:
        bank = []
    progress_ids = list(
        dict.fromkeys([*[c["id"] for c in concepts], *[q["concept_id"] for q in bank]])
    )
    if request.mode == "figure_practice" and request.include_history:
        state = history(bridge, owner, ref, progress_ids)
    if request.mode == "figure_practice" and bank:
        limitations.append(
            "Figure accuracy remains unverified; feedback uses an open-ended rubric."
        )
    proof = {
        "purpose": "academic_practice",
        "epoch": epoch,
        "session_id": opaque_id(),
        "expires": (utcnow() + timedelta(minutes=20)).isoformat(),
        "course_ids": courses,
        "materials": {d["material_id"]: d["content_hash"] for d in documents},
        "questions": bank,
        "preferences": request.preferences.model_dump(mode="json"),
    }
    public_questions = [
        {k: v for k, v in q.items() if k not in {"expected_answer", "source_passage"}} for q in bank
    ]
    progress = [
        {
            "concept_id": ident,
            "practice_state": state[ident]["practice_state"]
            if ident in state
            else "not_attempted"
            if request.include_history
            else "not_checked",
            "mastery": "not_established",
            "review_recommendation": review_recommendation(
                state[ident], request.preferences, utcnow()
            )
            if ident in state
            else {"status": "no_recorded_attempt", "scheduled": False},
        }
        for ident in progress_ids
    ]
    result = Result(
        status="partial_data" if limitations or not (bank if practice_mode else concepts) else "ok",
        summary=(
            "Generated practice is ready. Answer before revealing feedback; these are not instructor exam questions."
            if bank
            else "Source-specific concepts are ready for discussion."
            if concepts
            else "No supported definition candidates were found; choose explicit concept names or more relevant permitted passages."
        ),
        data={
            "schema_version": "cross-course-study-1",
            "study_mode": request.mode,
            "generated_practice": practice_mode,
            "questions": public_questions,
            "study_receipt": bridge.vault.seal(proof, owner, ref) if bank else None,
            # Recall responses must not be preceded by an answer-bearing concept list.
            "concepts": [] if practice_mode else concepts,
            "relationships": [] if practice_mode else links,
            "practice_progress": progress,
            "preferences": request.preferences.model_dump(mode="json"),
            "limitations": limitations
            + [
                "Extraction supports explicit English definition sentences and explicitly stated prerequisites; it is not exhaustive semantic understanding.",
                "No viewing or generated explanation establishes mastery. Cross-course terminology never proves equivalence.",
            ],
            "next_actions": [
                "Present questions without answers, wait for the student's voluntary response, then use submit_practice_response."
            ]
            if bank
            else ["Explain only the quoted source context and label any additional inference."],
            "scheduled": False,
            "course_ids": courses,
        },
        sources=sources,
        meta=bridge.meta(freshness="synthetic" if bridge.synthetic else "live"),
    )
    if len(result.model_dump_json().encode()) > 70_000:
        raise DomainError(
            "needs_input",
            "Study output exceeds its size limit; choose fewer concepts or materials.",
        )
    check(bridge, owner, ref, courses, epoch, tool)
    return result


async def submit(bridge, owner, ref, submission: PracticeSubmission):
    tool = "submit_practice_response"
    authorize_tool(bridge, owner, tool, {"connection_id": ref})
    try:
        proof = bridge.vault.open(submission.study_receipt, owner, ref)
        if (
            proof["purpose"] != "academic_practice"
            or datetime.fromisoformat(proof["expires"]) <= utcnow()
        ):
            raise ValueError()
        bank = {q["id"]: q for q in proof["questions"]}
        if any(r.question_id not in bank for r in submission.responses):
            raise ValueError()
    except Exception as exc:
        raise DomainError(
            "needs_input",
            "Use a current study session and its question identifiers.",
            reason_code="STUDY_RECEIPT_INVALID",
        ) from exc
    epoch, courses, documents, sources, _ = await read_documents(
        bridge, owner, ref, list(proof["materials"]), tool, proof["materials"]
    )
    if epoch != proof["epoch"] or set(courses) != set(proof["course_ids"]):
        raise DomainError("source_changed", "Study source scope changed; prepare a new session.")
    if len(documents) != len(proof["materials"]):
        raise DomainError("source_changed", "Study source coverage changed; prepare a new session.")
    preferences = StudyPreferences.model_validate(proof["preferences"])
    # Existing connection lock and optimistic LocalRecord versions serialize voluntary
    # progress updates. No answer text or source passage is persisted in practice state.
    async with bridge.lock("practice:" + ref):
        state = history(
            bridge, owner, ref, [bank[r.question_id]["concept_id"] for r in submission.responses]
        )
        feedback, writes = [], []
        for response in submission.responses:
            question = bank[response.question_id]
            old = state.get(question["concept_id"], {})
            item = evaluate(
                question,
                response,
                old.get("last_session_id") == proof["session_id"]
                and old.get("last_question_id") == question["id"],
            )
            record = {
                "practice_state": item["practice_state"],
                "outcome": item["outcome"],
                "attempted_at": utcnow().isoformat(),
                "last_question_id": question["id"],
                "last_session_id": proof["session_id"],
                "self_reported_confidence": response.self_reported_confidence,
                "course_id": question["course_id"],
                "material_id": question["material_id"],
                "attempt_count": old.get("attempt_count", 0) + 1,
                "mastery": "not_established",
            }
            item["review_recommendation"] = review_recommendation(record, preferences, utcnow())
            feedback.append(item)
            writes.append((question["concept_id"], record, old.get("version", 0)))
        result = Result(
            status="partial_data"
            if any(f["practice_state"] == "attempted_unresolved" for f in feedback)
            else "ok",
            summary="Practice feedback is based on the cited source. Correct recall does not establish mastery.",
            data={
                "feedback": feedback,
                "results_recorded": submission.record_results,
                "scheduled": False,
                "course_ids": courses,
                "limitations": [
                    "Independence and confidence are student-reported. Open-ended answers require review."
                ],
            },
            sources=sources,
        )
        permitted(bridge, owner, ref, result, tool)
        check(bridge, owner, ref, courses, epoch, tool)
        if submission.record_results:
            # Transaction nesting in save_local is deliberately avoided: save all
            # concept outcomes atomically using the existing encrypted record model.
            with bridge.store.transaction() as session:
                conn = bridge.store.connection(session, owner, ref, lock=True)
                if conn.epoch != epoch:
                    raise DomainError("source_changed", "Study permissions changed before saving.")
                for key, value, version in writes:
                    row = session.scalar(
                        select(LocalRecord)
                        .where(
                            LocalRecord.owner == owner,
                            LocalRecord.connection_id == ref,
                            LocalRecord.kind == "practice",
                            LocalRecord.key == key,
                        )
                        .with_for_update()
                    )
                    if (row.version if row else 0) != version:
                        raise DomainError(
                            "source_changed",
                            "Practice state changed; refresh before recording another response.",
                        )
                    if row is None:
                        row = LocalRecord(
                            id=opaque_id(),
                            owner=owner,
                            connection_id=ref,
                            kind="practice",
                            key=key,
                            version=0,
                        )
                        session.add(row)
                    row.payload, row.version, row.updated_at = value, version + 1, utcnow()
        return result


async def study_request(bridge, owner, ref, request):
    """Reuse the request fence and admission; bound study work even outside MCP tests."""
    token, lease = None, None
    budget_token = active_budget.set(Budget(replace(Limits(), files=6)))
    try:
        if request_authorization.get() is None:
            lease = bridge.request_limits.acquire(owner)
            token = request_authorization.set(RequestAuthorization("study"))
        async with asyncio.timeout(90):
            return await (
                submit(bridge, owner, ref, request)
                if isinstance(request, PracticeSubmission)
                else prepare(bridge, owner, ref, request)
            )
    except TimeoutError as exc:
        raise DomainError(
            "retry_later",
            "The study session exceeded its processing budget; narrow the material selection.",
        ) from exc
    finally:
        active_budget.reset(budget_token)
        if token is not None:
            request_authorization.reset(token)
        if lease:
            lease.close()
