"""Actual backend workflow adapters. These functions never receive gold answers.

Calls are local Python operations, not measured ChatGPT or MCP client calls.
Every upstream-facing authorization case uses the existing fictional provider.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from canvas_bridge.academic import grade_engine
from canvas_bridge.academic.gateway import AcademicRequest
from canvas_bridge.academic_intelligence import exam_pack
from canvas_bridge.academic_rules import citation, deadline_findings, instruction_findings
from canvas_bridge.discussions import DiscussionTopic, ThreadScan
from canvas_bridge.domain import DomainError, Effort, FactDate, Source, WorkItem
from canvas_bridge.normalize import plain_text
from canvas_bridge.parser_worker import extract
from canvas_bridge.planning import PlanRequest, Window, propose
from canvas_bridge.policy import validate_continuation
from canvas_bridge.privacy.discussions import minimize_thread
from canvas_bridge.privacy.identity import PrivacyIdentity
from canvas_bridge.providers.synthetic import SyntheticProvider


def receipt(source):
    return {
        "source_id": source["id"],
        "sha256": source["sha256"],
        "locator": source["locator"],
        "uri": source["uri"],
    }


def document(source):
    return {
        "id": source["id"],
        "title": source["id"],
        "url": source["uri"],
        "version": source["sha256"],
        "source_type": source["kind"],
        "course_id": source["course_id"],
        "retrieved_at": source["observed_at"],
        "complete": source["payload"].get("complete", True),
        "parts": [{"locator": source["locator"], "text": source["payload"].get("text", "")}],
    }


def work(ref, course, now, source, effort=30):
    return WorkItem(
        id=ref,
        connection_id="fictional-connection",
        institution_id="fictional",
        course_id=course,
        source_id=ref,
        title="Exam 1" if ref == "exam" else ref,
        availability_state="available",
        prerequisite_coverage="known",
        effective_due=FactDate(kind="timestamp", timestamp=now + timedelta(days=2)),
        effort_remaining=Effort(
            minimum_minutes=effort, maximum_minutes=effort, origin="student_estimate"
        )
        if effort is not None
        else None,
        source=Source(
            id=source["id"],
            title=ref,
            url=source["uri"],
            retrieved_at=now,
            content_hash=source["sha256"],
        ),
    )


async def execute(task, sources, root, clock):
    """One adapter dispatch; a sanitized trace records what actually ran."""
    selected = [sources[s] for s in task["source_ids"]]
    payload = selected[0]["payload"]
    driver, parameters = task["driver"], task["parameters"]
    now = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    uncertainty, evidence_override, raw = [], None, None
    if driver in {"grade", "grade_target"}:
        policy = grade_engine.GradePolicy.model_validate(payload["policy"])
        assessments = [
            grade_engine.GradeAssessment.model_validate(a) for a in payload["assessments"]
        ]
        if driver == "grade":
            raw = grade_engine.calculate(policy, assessments, evidence_complete=payload["complete"])
            answer = {
                "percentage": raw["calculated_percentage"],
                "classification": raw["classification"],
                "excluded": sorted(a["id"] for a in raw["excluded_assessments"]),
            }
            if raw["missing_information"]:
                uncertainty.append("grade_evidence_indeterminate")
            if any(a["reason"] == "ungraded_not_zero" for a in raw["excluded_assessments"]):
                uncertainty.append("ungraded_not_zero")
        else:
            raw = grade_engine.calculate(
                policy,
                assessments,
                "required_score",
                grade_engine.GradeScenario(
                    target_percent=parameters["target_percent"], acknowledge_visible_scope=True
                ),
                evidence_complete=payload["complete"],
            )
            result = raw.get("required_score", {})
            answer = {
                "required_percent": result.get("uniform_remaining_percent"),
                "status": result.get("status", "indeterminate"),
            }
            uncertainty.append("conditional_visible_inventory")
    elif driver == "deadlines":
        items = (
            []
            if payload["due"] is None
            else [
                {
                    "id": "exam",
                    "title": "Exam 1",
                    "effective_due": payload["due"],
                    "source": receipt(selected[0]),
                }
            ]
        )
        raw = deadline_findings(
            [document(selected[0])], items, "UTC", payload["assignments_complete"]
        )
        answer = {"findings": sorted(f["kind"] for f in raw["findings"])}
        if raw["findings"]:
            uncertainty.append("source_applicability_unresolved")
    elif driver == "requirements":
        raw = instruction_findings([document(s) for s in selected])
        answer = {
            "conflicts": len(raw["conflicts"]),
            "mandatory_word_counts": sum(
                r["type"] == "word_count" and r["mandatory"] for r in raw["rules"]
            ),
        }
        if not raw["rules"]:
            uncertainty.append("qualitative_requirements_not_resolved")
    elif driver == "plan":
        items = [
            work(
                chr(97 + i),
                payload["course_ids"][i % len(payload["course_ids"])],
                now,
                selected[0],
                effort,
            )
            for i, effort in enumerate(payload["efforts"])
        ]
        # Earlier deadlines provide an explicit ordering, not arbitrary points-as-stakes.
        for i, item in enumerate(items):
            item.effective_due.timestamp = now + timedelta(hours=payload["due_hours"][i])
        request = PlanRequest(
            windows=[Window(start=now, end=now + timedelta(minutes=payload["window_minutes"]))],
            busy_times=[
                Window(start=now + timedelta(minutes=a), end=now + timedelta(minutes=b))
                for a, b in payload["busy_minutes"]
            ],
            break_minutes=payload["break_minutes"],
            buffer_minutes=payload["buffer_minutes"],
            max_block_minutes=payload["max_block_minutes"],
        )
        raw = propose(items, request, now)
        blocks = raw["blocks"]
        overlap = any(a["end"] > b["start"] for a, b in zip(blocks, blocks[1:], strict=False))
        overlap = overlap or any(
            datetime.fromisoformat(b["start"]) < busy.end
            and datetime.fromisoformat(b["end"]) > busy.start
            for b in blocks
            for busy in request.busy_times
        )
        answer = {
            "order": [r["work_id"] for r in raw["recommendations"]],
            "allocated_minutes": sum(b["minutes"] for b in blocks),
            "shortfall_minutes": raw["known_shortfall_minutes"],
            "overlap": overlap,
        }
        if any(v is None for v in payload["efforts"]):
            uncertainty.append("effort_unknown")
    elif driver == "prepare":
        doc = document(selected[0])
        item = work("exam", task["course_ids"][0], now, selected[0]).model_dump(mode="json")
        bundle = {
            "items": [item],
            "documents": [doc],
            "assignments": {"exam": {"instructions": doc}},
            "outline": {},
            "course": task["course_ids"][0],
            "timezone": "UTC",
            "assignments_complete": True,
        }
        raw = exam_pack(bundle, "exam")
        answer = {
            "explicit_coverage": bool(raw["explicit_coverage_passages"]),
            "guide_generated": raw["generated_study_guide"] is not None,
            "figure_interpretation": raw["figure_interpretation"],
        }
        uncertainty.append("preparation_scope_not_comprehensive")
    elif driver == "citation":
        doc = document(selected[0])
        raw = citation(doc, doc["parts"][0], payload["text"])
        answer = {"passage": raw["passage"], "untrusted_content": raw["untrusted_content"]}
        evidence_override = [
            {
                "source_id": raw["source_id"],
                "sha256": raw["document_version"],
                "locator": raw["locator"],
                "uri": raw["source_url"],
            }
        ]
    elif driver == "authorization":
        current = [now]
        provider = SyntheticProvider(clock=lambda: current[0])
        request = AcademicRequest(
            principal=parameters.get("principal", "synthetic-student"),
            tenant="fictional",
            connection="demo",
            resource=parameters.get("resource", "course-fictional"),
            recipient=parameters.get("recipient", "local"),
        )
        try:
            authorized = await provider.gateway.retrieve(
                parameters.get("operation", "get_grade_summary"), request
            )
            if parameters.get("expire"):
                current[0] += timedelta(hours=2)
            provider.gateway.release(authorized)
            answer = {"status": "ok"}
        except DomainError as exc:
            answer = {"status": exc.status}
    elif driver == "privacy":
        raw = minimize_thread(payload, PrivacyIdentity(payload["identity"]), full_view=True)
        answer = {
            "self_messages": [r["message_text"] for r in raw["records"] if "message_text" in r],
            "peer_disclosed": "PEER_PRIVATE_CANARY" in json.dumps(raw),
        }
    elif driver == "pagination":
        try:
            validate_continuation(payload["next"], payload["original"])
            answer = {"status": "ok"}
        except DomainError as exc:
            answer = {"status": exc.status}
    elif driver == "sanitize":
        answer = {"text": plain_text(payload["text"])}
    elif driver == "participation":
        identity = PrivacyIdentity(payload["identity"])

        async def fixture_page(endpoint, **kwargs):
            return minimize_thread(payload, identity, full_view=True), None

        client = SimpleNamespace(
            privacy_identity=identity,
            settings=SimpleNamespace(
                discussion_budget_seconds=2,
                discussion_max_entries=100,
                discussion_max_pages=3,
                max_pages=3,
            ),
            discussion_page=fixture_page,
        )
        topic = DiscussionTopic(
            course_id=task["course_ids"][0],
            topic_id="1",
            canvas_url=selected[0]["uri"],
            visibility_restrictions=payload["visibility_restrictions"],
        )
        result = await ThreadScan(client, topic, "1").run()
        raw = result.model_dump(mode="json")
        answer = {
            "state": result.state,
            "top_level_posts": result.top_level_posts,
            "replies": result.replies,
        }
        if not result.coverage.complete:
            uncertainty.append("participation_coverage_incomplete")
    elif driver == "extract":
        path = (root / payload["asset"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Asset escaped corpus root.")
        raw = extract(path.read_bytes(), parameters["format"])
        answer = {
            "parts": len(raw["pages"]),
            "visual_reading_claimed": raw.get("coverage")
            not in {"text_only", "partial_text", "scanned_or_empty"},
        }
        uncertainty.append("pixels_require_visual_review")
    elif driver == "interpretive":
        answer = {"status": "requires_independent_review"}
        uncertainty.append("interpretation_not_scored")
    else:
        raise ValueError("Unregistered benchmark adapter operation.")
    return {
        "scenario_id": task["id"],
        "answer": answer,
        "uncertainty": uncertainty,
        "evidence": {k: evidence_override or [receipt(s) for s in selected] for k in answer},
        "operations": [{"name": driver, "scope": "backend_python", "success": True}],
        "response_text": "",
        "human_correction_steps": 0,
        "tool_calls": 0,
        "network_requests": 0,
        "trace": {
            "measurement_scope": "backend_workflow_not_MCP_or_model",
            "product_output_sha256": hashlib.sha256(
                json.dumps(raw, sort_keys=True, default=str).encode()
            ).hexdigest()
            if raw is not None
            else None,
        },
    }


async def bounded_execute(task, sources, root, clock):
    async with asyncio.timeout(20):
        return await execute(task, sources, root, clock)
