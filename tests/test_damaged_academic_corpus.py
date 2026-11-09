"""Permanent controls for the original, deliberately incomplete synthetic corpus."""

import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.academic_rules import instruction_findings
from tests.test_academic_intelligence import source_doc
from tests.test_independent_intelligence import imported
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally

ARCHIVE = (
    Path(__file__).resolve().parents[1]
    / "benchmarks/academic/damaged-business-coursework/business-coursework.zip"
)
ROOT = "Business Student Full Media/"


def test_archive_identity_and_mirrors():
    assert (
        hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        == "6d3322be08e6d449bb32a5f64b0928e6a350eb69aff6866fcab84a2c473cdf51"
    )
    with ZipFile(ARCHIVE) as archive:
        members = {m.filename for m in archive.infolist() if not m.is_dir()}
        records = json.loads(archive.read(ROOT + "MANIFEST.json"))["files"]
        counts = []
        absent = set()
        for record in records:
            paths = [
                prefix + record["path"]
                for prefix in (ROOT, ROOT + "CanvasBridge_Business_Coursework_v1/")
            ]
            copies = [path for path in paths if path in members]
            assert all(
                hashlib.sha256(archive.read(path)).hexdigest() == record["sha256"]
                for path in copies
            )
            counts.append(len(copies))
            if not copies:
                absent.add(record["source_id"])
        assert (len(members), len(records), counts.count(0), counts.count(2)) == (285, 276, 11, 16)
        # Scoring metadata stays here. Only student_text() supplies workflow inputs.
        scenarios = json.loads(
            archive.read(ROOT + "90_EVALUATOR_ONLY/All_Course_Test_Scenarios.json")
        )
        assert sum(bool(absent.intersection(case["evidence"])) for case in scenarios) == 9


def student_text(key):
    with ZipFile(ARCHIVE) as archive:
        (record,) = [
            r
            for r in json.loads(archive.read(ROOT + "MANIFEST.json"))["files"]
            if r.get("source_id") == key and r["path"].startswith("01_STUDENT_MATERIALS/")
        ]
        content = archive.read(ROOT + record["path"])
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        return content.decode()


@pytest.mark.parametrize(
    ("count", "passes"), [(1799, False), (1800, True), (1900, True), (2200, True), (2201, False)]
)
def test_body_boundary_and_archived_rubric(count, passes):
    docs = [source_doc(student_text(key), id=key) for key in ("MGT340-P02", "MGT340-N02")]
    for sources in (docs, list(reversed(docs))):
        result = instruction_findings(sources, "x " * count)
        checks = result["draft_review"]["checks"]
        assert [c["satisfies_stated_count"] for c in checks] == [passes]
        assert any(
            r["interpretation_status"] == "historical"
            for r in result["rules"]
            if r["type"] == "word_count"
        )


def test_required_deliverables_and_separate_bodies():
    rules = instruction_findings([source_doc(student_text("STR410-N02"))])["rules"]
    required = [r for r in rules if r["type"] == "submission_format" and r["mandatory"]]
    assert [r["formats"] for r in required] == [["pdf"], ["xlsx"]]
    assert "memo" in required[0]["scope"] and "workbook" in required[1]["scope"]
    assert any(
        r.get("interpretation_status") == "historical" and r["formats"] == ["pdf"] for r in rules
    )
    alternatives = instruction_findings([source_doc("Submit PDF or DOCX format.")])["rules"]
    assert [r["formats"] for r in alternatives] == [["docx", "pdf"]]
    result = instruction_findings(
        [source_doc("Initial post 250-350 words; reply at least 100 words.")], "x " * 300
    )
    assert not result["conflicts"]
    assert [c["satisfies_stated_count"] for c in result["draft_review"]["checks"]] == [None, None]


async def test_damaged_selection_through_local_mcp(
    bridge, owner, no_lms_running, token_factory, tmp_path, request
):
    if os.environ.get("BRIDGE_TEST_CORPUS_SANDBOX") == "1":
        bridge.settings.file_reading_enabled = True
        root = (
            Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
            if os.name == "nt"
            else tmp_path / "parser"
        )
        bridge.settings.parser_root = bridge.settings.parser_runtime_root = root
    else:
        request.getfixturevalue("parsed_locally")
    selected = await imported(bridge, owner, student_text("MKT320-A05"))
    missing = await imported(bridge, owner, "Disposable synthetic selection.")
    bridge.independent.delete(owner, missing["document_id"])
    async with client_session(no_lms_running, token_factory()) as session:

        async def review(selections):
            result = await session.call_tool(
                "run_independent_academic_workflow",
                {"request": {"capability": "assessment", "documents": selections}},
            )
            return result.structuredContent

        observed = await review([selected])
        assert observed["data"]["coverage_status"] == "selected_excerpts_only"
        assert observed["data"]["excluded_sources"] == []
        mixed = await review([missing, selected])
        assert mixed["status"] == "partial_data", mixed
        assert mixed["data"]["excluded_sources"] == [
            {"selection": 1, "reason_code": "INDEPENDENT_SOURCE_UNAVAILABLE"}
        ]
        assert {(s["id"], s["content_hash"]) for s in mixed["sources"]} == {
            (selected["document_id"], selected["expected_hash"])
        }
        assert {e["document_version"] for e in mixed["data"]["material_excerpts"]} == {
            selected["expected_hash"]
        }
        absent = await review([missing])
        assert absent["status"] == "permission_denied" and not absent["sources"]
        stale = await review([{**selected, "expected_hash": "f" * 64}])
        assert stale["status"] == "source_changed" and not stale["sources"]


def test_scoped_amendment_survives_reordering_and_never_crosses_courses():
    from canvas_bridge.academic_rules import dated_obligations, match_obligation

    docs = [source_doc(student_text(k), id=k) for k in ("FIN310-N02", "FIN310-A03")]
    items = [{"id": "FIN310-A03", "title": "Memo", "course_id": "course"}]
    for ordered in (docs, list(reversed(docs))):
        candidates = [
            o for o in dated_obligations(ordered) if o.get("assessment_id") == "FIN310-A03"
        ]
        assert any(
            o["interpretation_status"] == "historical" and "November 6" in o["raw_date"]
            for o in candidates
        )
        for o in candidates:
            assert match_obligation(o, items)[0] == items[0]
            assert match_obligation(o, [{**items[0], "course_id": "another"}])[0] is None
            assert match_obligation(o, [{**items[0], "id": "FIN310-A04"}])[0] is None


def test_independent_completion_reopens_without_creating_lms_evidence():
    from datetime import timedelta

    from canvas_bridge.academic.independent_engine import analyze, work_items
    from canvas_bridge.academic.independent_models import (
        IndependentAcademicInput,
        IndependentRequest,
    )
    from canvas_bridge.domain import Source
    from tests.test_domain_planning import NOW

    source = Source(
        id="local", title="Selected work", url="", retrieved_at=NOW, content_hash="0" * 64
    )
    request = IndependentRequest(
        capability="calendar",
        dataset={"document_id": "local", "expected_hash": "0" * 64},
        calendar={
            "calendar_id": "synthetic",
            "timezone": "UTC",
            "retrieved_at": NOW,
            "window_start": NOW,
            "window_end": NOW + timedelta(days=2),
            "pagination_complete": True,
            "mapping_search_complete": True,
            "events": [],
        },
    )
    due = {"kind": "timestamp", "timestamp": NOW + timedelta(days=1)}
    for progress, expected in [("student_marked_done", {"b"}), ("in_progress", {"a", "b"})]:
        dataset = IndependentAcademicInput(
            schema_version="independent-academic-1",
            timezone="UTC",
            complete=True,
            work=[
                {"key": "a", "title": "Memo", "due": due, "progress": progress},
                {"key": "b", "title": "Quiz", "due": due},
            ],
        )
        result, _ = analyze(request, dataset, source, [], owner="fixture", now=NOW)
        assert {p["work_id"] for p in result["proposals"]} == expected
        assert all(p["action"] == "create" for p in result["proposals"])
        assert not result["provider_writes_executed"]
        assert all(
            i.submission_state == "unknown" and i.assessment_state == "unknown"
            for i in work_items(dataset, source)
        )


async def test_retryable_storage_failure_through_local_mcp(
    bridge, owner, no_lms_running, token_factory, parsed_locally, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    good = await imported(bridge, owner, student_text("ACC201-N02"))
    transient = await imported(bridge, owner, student_text("FIN310-N02"))
    original = bridge.independent.read

    def read(owner, ident, **kwargs):
        if ident == transient["document_id"] and kwargs.get("study"):
            raise SQLAlchemyError("private synthetic backend details")
        return original(owner, ident, **kwargs)

    monkeypatch.setattr(bridge.independent, "read", read)
    async with client_session(no_lms_running, token_factory()) as session:
        for selections in ([transient], [good, transient]):
            response = await session.call_tool(
                "run_independent_academic_workflow",
                {"request": {"capability": "assessment", "documents": selections}},
            )
            result = response.structuredContent
            assert "private synthetic backend details" not in str(result)
            if len(selections) == 1:
                assert result["status"] == "retry_later" and not result["sources"]
                assert result["data"]["reason_code"] == "LOCAL_STORAGE_UNAVAILABLE"
            else:
                assert result["status"] == "partial_data"
                assert {s["id"] for s in result["sources"]} == {good["document_id"]}
                (excluded,) = result["data"]["excluded_sources"]
                assert (
                    excluded["selection"] == 2
                    and excluded["reason_code"] == "LOCAL_STORAGE_UNAVAILABLE"
                )
                assert excluded["retry_condition"]


async def test_empty_profile_adapter_controls(no_lms_running, token_factory):
    controls = [({}, "needs_input", "TOOL_INPUT_INVALID")]
    controls.extend(
        ({"capability": cap}, "needs_input", "INDEPENDENT_INPUT_MISSING")
        for cap in (
            "planning",
            "calendar",
            "grades",
            "consistency",
            "assessment",
            "requirements",
            "deadlines",
        )
    )
    controls.append(
        (
            {
                "capability": "requirements",
                "documents": [
                    {"document_id": "intentional-absent-synthetic-probe", "expected_hash": "0" * 64}
                ],
            },
            "permission_denied",
            "INDEPENDENT_SOURCE_UNAVAILABLE",
        )
    )
    async with client_session(no_lms_running, token_factory()) as session:
        for request, status, reason in controls:
            result = (
                await session.call_tool("run_independent_academic_workflow", {"request": request})
            ).structuredContent
            assert (result["status"], result["data"]["reason_code"], result["sources"]) == (
                status,
                reason,
                [],
            )
