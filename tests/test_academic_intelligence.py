"""Synthetic acceptance courses: no real coursework, calendar records or grades."""

import io
import os
import zipfile
from copy import deepcopy
from datetime import timedelta
from xml.etree.ElementTree import ParseError

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.academic_intelligence import academic_request, collect_course, document
from canvas_bridge.academic_rules import deadline_findings, instruction_findings
from canvas_bridge.calendar_sync import (
    CalendarContext,
    CalendarEvent,
    calendar_proposal,
    marker,
    propose_sync,
)
from canvas_bridge.course_files import list_files, read_file, search_files
from canvas_bridge.domain import Coverage, DomainError, FactDate, Source, utcnow
from canvas_bridge.evidence import attach, fingerprint, reconcile_states
from canvas_bridge.grading_engine import GradeGroup, GradePolicy, calculate, reconcile
from canvas_bridge.parser_sandbox import extract_isolated
from canvas_bridge.parser_worker import extract
from canvas_bridge.planning import Importance, PlanRequest, Window, propose
from canvas_bridge.storage import Snapshot, aware
from tests.conftest import seed
from tests.test_course_files import file_record
from tests.test_domain_planning import NOW, task
from tests.test_file_reading import scientific_pdf
from tests.test_grade_audit import doc, graded, reviewed
from tests.test_mcp_contract import running as running


def source_doc(text, kind="syllabus", id="source", complete=True):
    source = Source(
        id=id,
        url="https://canvas.synthetic.invalid/courses/11/" + id,
        title=id,
        retrieved_at=NOW,
        source_type=kind,
        course_id="course",
        content_hash=fingerprint(text),
    )
    return document(source, text, complete=complete)


def ooxml(kind, texts=None):
    texts = texts or [
        "Exam 1: November 12, 2026",
        "Methods: mesenchymal differentiation in controlled cultures.",
    ]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        if kind == "docx":
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + "".join("<w:p><w:r><w:t>" + t + "</w:t></w:r></w:p>" for t in texts)
                + "</w:body></w:document>",
            )
        else:
            archive.writestr(
                "ppt/presentation.xml",
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>'
                + "".join(f'<p:sldId id="{i}" r:id="r{i}"/>' for i in range(len(texts), 0, -1))
                + "</p:sldIdLst></p:presentation>",
            )
            archive.writestr(
                "ppt/_rels/presentation.xml.rels",
                "<Relationships>"
                + "".join(
                    f'<Relationship Id="r{i}" Type="http://example/slide" Target="slides/slide{i}.xml"/>'
                    for i in range(1, len(texts) + 1)
                )
                + "</Relationships>",
            )
            for i, text in enumerate(texts, 1):
                archive.writestr(
                    f"ppt/slides/slide{i}.xml",
                    '<p:sld xmlns:p="urn:ppt" xmlns:a="urn:drawing"><a:p><a:r><a:t>'
                    + text
                    + "</a:t></a:r></a:p></p:sld>",
                )
    return stream.getvalue()


@pytest.fixture
async def academic(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["assignments"]["11"] = [
        {
            "id": 1,
            "name": "Exam 1",
            "due_at": None,
            "unlock_at": None,
            "lock_at": None,
            "locked_for_user": False,
            "published": True,
            "points_possible": 100,
            "submission_types": ["online_upload"],
            "description": "<p>Write 1,000 words.</p>",
            "rubric": [
                {"description": "Required length", "long_description": "Write 1,500 words."}
            ],
            "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
        }
    ]
    bridge.synthetic.data["course_details"] = {
        "11": {
            "id": 11,
            "time_zone": "America/New_York",
            "syllabus_body": "<p>Exam 1: November 12, 2026</p>",
        }
    }
    bridge.synthetic.data["announcements"] = {"11": []}
    return course


def test_evidence_versions_coverage_and_unknown_reconciliation():
    source = Source(id="a", url="https://example.invalid/a", title="A", retrieved_at=NOW)
    from canvas_bridge.domain import Result

    response = attach(Result(summary="Fixture", sources=[source]))
    assert response.evidence[0]["uncertainty"] and not response.evidence[0]["coverage"]
    assert response.evidence[0]["interpretation_status"] == "uninterpreted_source"
    state = reconcile_states([{"state": "not_submitted"}, {"state": "unknown"}])
    assert state["state"] == "unknown" and state["conflict"]
    source.course_id, source.content_hash = "course", "version"
    covered = attach(
        Result(
            summary="Fixture",
            sources=[source],
            meta={
                "coverage": [
                    Coverage(
                        course_ref="course",
                        resource="assignments",
                        state="partial",
                        pagination_complete=False,
                    )
                ]
            },
        )
    )
    assert covered.evidence[0]["coverage"][0]["pagination_complete"] is False


@pytest.mark.parametrize("kind", ["docx", "pptx"])
def test_office_extraction_order_locators_and_security(kind):
    result = extract(ooxml(kind), kind)
    assert result["content_hash"] and result["coverage"] == "text_only"
    assert result["pages"][0]["locator_kind"] == ("slide" if kind == "pptx" else "section")
    if kind == "pptx":
        assert "Methods" in result["pages"][0]["text"]
        assert "Exam 1" in result["pages"][1]["text"]
    else:
        assert "not rendered pages" in " ".join(result["warnings"])
    malicious = ooxml(kind, ['<!DOCTYPE test [<!ENTITY x SYSTEM "file:///secret">]>&x;'])
    if kind == "pptx":
        rejected = extract(malicious, kind)
        assert rejected["coverage"] == "partial"
        assert rejected["pages"][0]["state"] == "unreadable"
        assert rejected["pages"][0]["text"] == ""
    else:
        with pytest.raises(ParseError):
            extract(malicious, kind)
    data = io.BytesIO(ooxml(kind))
    with zipfile.ZipFile(data, "a") as archive:
        archive.writestr("word/vbaProject.bin", b"never execute")
    with pytest.raises(ValueError, match="active_office_content"):
        extract(data.getvalue(), kind)


@pytest.mark.skipif(os.name != "nt", reason="Live extractor fails closed outside Windows")
@pytest.mark.parametrize("kind", ["docx", "pptx"])
def test_office_real_appcontainer(kind, tmp_path):
    result = extract_isolated(ooxml(kind), kind, tmp_path / "parser")
    assert any("differentiation" in p["text"] for p in result["pages"])


@pytest.mark.parametrize(
    "kind,mime",
    [
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ],
)
async def test_authorized_office_read_search_and_isolation(
    bridge, owner, seeded, academic, monkeypatch, kind, mime
):
    data = ooxml(kind)
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                display_name="Schedule." + kind,
                filename="schedule." + kind,
                size=len(data),
                **{"content-type": mime},
                updated_at=NOW.isoformat(),
                url="https://canvas.synthetic.invalid/files/51/download",
            )
        ]
    }
    bridge.synthetic.data["file_bodies"], bridge.synthetic.data["file_types"] = (
        {"51": data},
        {"51": mime},
    )
    bridge.settings.file_reading_enabled = True

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    files = await list_files(bridge, owner, seeded, academic.id)
    file_id = files.data["files"][0]["file_id"]
    result = await read_file(bridge, owner, seeded, file_id, length=20)
    assert result.data["text"] and result.data["continuation"]
    assert ("Slide" if kind == "pptx" else "Section") in result.sources[0].locator
    searched = await search_files(bridge, owner, seeded, academic.id, "differentiation")
    assert searched.data["results"]
    compared = await academic_request(bridge, owner, seeded, academic.id, material_ids=[file_id])
    assert any(f["kind"] == "missing_canvas_deadline" for f in compared.data["findings"])
    await seed(bridge, "other", "other-connection")
    with pytest.raises(DomainError):
        await read_file(bridge, "other", "other-connection", file_id)


async def test_deadline_acceptance_and_exact_source(bridge, owner, seeded, academic):
    result = await academic_request(bridge, owner, seeded, academic.id)
    finding = result.data["findings"][0]
    assert finding["kind"] == "missing_canvas_deadline"
    assert finding["obligation"]["date"] == "2026-11-12"
    assert finding["obligation"]["precision"] == "date"
    assert finding["obligation"]["evidence"]["passage"] == "Exam 1: November 12, 2026"
    assert finding["certainty"] == "confirmed_field_absence"
    assert result.evidence and result.data["unread_materials"]


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Exam 1: November 12", None),
        ("Exam 1: February 30, 2026", None),
        ("Exam 1: 2026-11-12T10:30:00-05:00", "2026-11-12T10:30:00-05:00"),
    ],
)
def test_dates_never_invent_year_or_timezone(line, expected):
    item = task("a")
    item.title = "Exam 1"
    item.effective_due = FactDate(kind="known_none")
    result = deadline_findings([source_doc(line)], [item.model_dump(mode="json")], None, True)
    assert result["obligations"][0]["date"] == expected
    assert result["obligations"][0]["raw_date"]


def test_deadline_ambiguous_titles_versions_and_timezone():
    item = task("a")
    item.title = "Exam 1"
    item.effective_due = FactDate(kind="timestamp", timestamp=NOW)
    payload = item.model_dump(mode="json")
    unknown = deadline_findings([source_doc("Exam 1: November 12, 2026")], [payload], None, True)
    assert unknown["findings"][0]["kind"] == "timezone_unresolved"
    duplicate = deadline_findings(
        [source_doc("Exam 1: November 12, 2026")], [payload, {**payload, "id": "b"}], "UTC", True
    )
    assert duplicate["findings"][0]["kind"] == "ambiguous_match"
    conflict = deadline_findings(
        [source_doc("Exam 1: November 12, 2026"), source_doc("Exam 1: November 15, 2026", id="v2")],
        [payload],
        "UTC",
        True,
    )
    assert len(conflict["findings"]) == 2
    assert all("supersede" in f["interpretation"] for f in conflict["findings"])


async def test_changes_earliest_observation_and_dedupe(bridge, owner, seeded):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["due_at"] = "2026-10-28T12:00:00Z"
    baseline = await bridge.refresh(owner, seeded)
    raw.update(
        due_at="2026-10-30T12:00:00Z",
        unlock_at="2026-10-21T10:00:00Z",
        points_possible=50,
        description="<p>Updated instructions</p>",
        submission_types=["online_text_entry"],
        updated_at="2026-10-20T10:00:00Z",
    )
    changed = await bridge.refresh(owner, seeded)
    await bridge.refresh(owner, seeded)
    result = bridge.changes(owner, seeded, aware(baseline.created_at))
    again = bridge.changes(owner, seeded, aware(baseline.created_at))
    assert result.data["changes"] == again.data["changes"]
    changes = result.data["changes"]
    assert {
        "effective_due",
        "available_from",
        "points_possible",
        "instruction_hash",
        "submission_requirement",
    } <= {c.get("field") for c in changes}
    due = next(c for c in changes if c.get("field") == "effective_due")
    assert due["observed_at"] == aware(changed.created_at).isoformat()
    assert "2026-10-28" in due["old"]["timestamp"] and "2026-10-30" in due["new"]["timestamp"]
    assert due["notification_key"] and due["source_modified_at"] != due["observed_at"]
    assert "disabled" in result.data["notification_delivery"]


def test_grade_84_vs_91_acceptance():
    policy = GradePolicy(
        method="weighted",
        empty_categories="renormalize",
        groups=[
            GradeGroup(id="exam", name="Exams", weight=80),
            GradeGroup(id="lab", name="Labs", weight=20),
        ],
    )
    _, syllabus = reviewed([doc("Exams: 45%\nLabs: 55%")], policy)
    rows = [graded(), graded("b", "lab", 100, 100)]
    canvas, independent = calculate(policy, rows), calculate(syllabus, rows, "syllabus_current")
    assert canvas["calculated_percentage"] == "84.0000"
    assert independent["calculated_percentage"] == "91.0000"
    result = reconcile(
        {"current_score": 84}, canvas, independent, policy, syllabus, reported_comparable=True
    )
    assert result["outcome"] == "explainable_difference"
    assert result["difference_percentage_points"] == "7.0000"


async def test_instruction_conflict_and_draft_acceptance(bridge, owner, seeded, academic):
    bundle = await collect_course(bridge, owner, seeded, academic.id)
    work_id = bundle["items"][0]["id"]
    result = await academic_request(
        bridge, owner, seeded, academic.id, "instructions", work_id=work_id, draft="word " * 1000
    )
    assert len(result.data["conflicts"]) == 1
    conflict = result.data["conflicts"][0]
    assert conflict["left"]["minimum"] == 1000 and conflict["right"]["minimum"] == 1500
    assert result.data["draft_review"]["word_count"] == 1000
    assert result.data["draft_review"]["grade_prediction"] is None


def test_optional_ranges_formats_amendments():
    result = instruction_findings([source_doc("Write 1000 words.\nSuggested length: 1500 words.")])
    assert not result["conflicts"]
    assert not instruction_findings(
        [source_doc("Write 1000-1500 words.\nWrite at least 1200 words.")]
    )["conflicts"]
    amended = instruction_findings(
        [
            source_doc(
                "Submit PDF format.\nUpdated requirement: submit DOCX instead of the old format."
            )
        ]
    )
    assert amended["conflicts"][0]["certainty"] == "amendment_candidate"
    criteria = instruction_findings([source_doc("Analysis: 40%\nAnalysis: 60%")])
    assert criteria["conflicts"][0]["rule_type"] == "criterion_weight"
    ambiguous = instruction_findings(
        [source_doc("Write 1000 words.\nDo not write 1500 words.\nBetween 1000 and 1500 words.")]
    )
    assert not ambiguous["conflicts"]


async def test_current_detail_conflict_preserves_missing_evidence(
    bridge, owner, seeded, monkeypatch
):
    snap = await bridge.refresh(owner, seeded)
    item = next(i for i in snap.items if i["submission_state"] == "not_submitted")
    original = bridge.synthetic.handle

    def handler(request):
        response = original(request)
        if request.url.path.endswith("/assignments/" + item["source_id"]):
            payload = response.json()
            payload.pop("submission", None)
            return httpx.Response(200, json=payload)
        return response

    monkeypatch.setattr(bridge.synthetic, "handle", handler)
    details = await bridge.assignment_details(owner, seeded, item["id"])
    assert details.data["submission_consistency"]["conflict"]
    assert details.data["item"]["submission_evidence"] == "not_returned"
    assert details.data["item"]["submission_state"] == "unknown"


async def test_foreign_submission_identity_rejected(bridge, owner, seeded, academic):
    bridge.synthetic.data["assignments"]["11"][0]["submission"]["assignment_id"] = 999
    evidence = await collect_course(bridge, owner, seeded, academic.id)
    assert evidence["items"][0]["submission_state"] == "unknown"
    assert evidence["items"][0]["submission_evidence"] == "identity_mismatch"


async def test_partial_pagination_is_not_proof_of_absence(bridge, owner, seeded, academic):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    bridge.synthetic.data["assignments"]["11"] = [
        {**deepcopy(raw), "id": i, "name": f"Exam {i}"} for i in range(1, 5)
    ]
    bridge.settings.max_pages = 1
    result = await academic_request(bridge, owner, seeded, academic.id, "audit")
    coverage = next(c for c in result.meta.coverage if c.resource == "assignments")
    assert not coverage.pagination_complete and coverage.state == "partial"
    assert result.status == "partial_data"


async def test_academic_scope_fence_and_timeout(bridge, owner, seeded, academic, monkeypatch):
    from canvas_bridge import academic_intelligence as module
    from canvas_bridge.storage import Connection

    original = module.outline

    async def withdraw(*args):
        result = await original(*args)
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).epoch += 1
        return result

    monkeypatch.setattr(module, "outline", withdraw)
    with pytest.raises(DomainError, match="scope changed"):
        await academic_request(bridge, owner, seeded, academic.id)

    async def timeout(*args):
        raise TimeoutError

    monkeypatch.setattr(module, "collect_course", timeout)
    result = await academic_request(bridge, owner, seeded, academic.id)
    assert result.data["absence_of_findings_proves_no_issues"] is False


async def test_html_schedule_discovery_unauthorized_file_reference(bridge, owner, seeded, academic):
    bridge.synthetic.data["pages"] = {
        "11": [{"page_id": 31, "url": "syllabus", "title": "Schedule", "published": True}]
    }
    # Synthetic page bodies are read through the same authorization path.
    listing = await list_files(bridge, owner, seeded, academic.id)
    assert listing.data["files"] == []
    with pytest.raises(DomainError):
        await academic_request(
            bridge, owner, seeded, academic.id, material_ids=["foreign-material"]
        )


def test_calendar_unknown_dates_duplicate_titles_and_no_deletion():
    item = task("a")
    ctx = context()
    ctx.events = [CalendarEvent(id="manual", title=item.title, start=NOW + timedelta(days=1))]
    result = calendar_proposal([item], ctx, "owner", "ref", NOW)
    assert result["ambiguous_matches"] and not result["proposals"]
    item.effective_due = FactDate(kind="known_none")
    result = calendar_proposal([item], ctx, "owner", "ref", NOW)
    assert not result["deletions"] and not result["proposals"]
    assert result["ignored"][0]["reason"] == "date_unknown_no_event_invented"


def test_zip_expansion_and_external_slide_fail_closed():
    data = io.BytesIO(ooxml("docx"))
    with zipfile.ZipFile(data, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", "x" * 1_000_000)
    with pytest.raises(ValueError, match="office_resource_limit"):
        extract(data.getvalue(), "docx")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="urn:p" xmlns:r="urn:r"><p:sldId r:id="r1"/></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships><Relationship Id="r1" Type="urn:slide/slide" TargetMode="External" Target="https://private.invalid/slide"/></Relationships>',
        )
    with pytest.raises(ValueError, match="invalid_slide_reference"):
        extract(data.getvalue(), "pptx")


def test_prioritization_urgency_importance_effort_and_overrides():
    items = [
        task("a", 60, NOW + timedelta(hours=30)),
        task("b", 30, NOW + timedelta(hours=40)),
        task("c", None, NOW + timedelta(hours=5)),
        task("done", 10),
    ]
    items[-1].assessment_state = "graded"
    request = PlanRequest(
        importance={
            "b": Importance(
                grade_weight_percent=30, explanation="Student verified syllabus weight"
            ),
            "a": Importance(grade_weight_percent=5, explanation="Student supplied weight"),
        }
    )
    result = propose(items, request, NOW)
    assert [i["work_id"] for i in result["recommendations"]] == ["c", "b", "a"]
    assert result["recommendations"][0]["effort_remaining"] is None
    request.priority_overrides = {"a": 0}
    assert propose(items, request, NOW)["recommendations"][0]["work_id"] == "a"
    request.priority_overrides = {"foreign": 0}
    with pytest.raises(ValueError):
        propose(items, request, NOW)
    done = task("online", 60)
    done.personal_progress, done.submission_state = "student_marked_done", "not_submitted"
    verification = propose(
        [done], PlanRequest(windows=[Window(start=NOW, end=NOW + timedelta(hours=2))]), NOW
    )
    assert "Verify" in verification["recommendations"][0]["first_action"]
    assert verification["blocks"] == []


async def test_exam_reads_associated_pdf_without_inventing_coverage(
    bridge, owner, seeded, academic, monkeypatch
):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw.update(
        name="Quiz 1",
        due_at=(utcnow() + timedelta(days=3)).isoformat(),
        description="<p>Quiz 1 covers membrane transport. Read Paper 3.</p>",
    )
    pdf = scientific_pdf()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                size=len(pdf),
                updated_at=NOW.isoformat(),
                url="https://canvas.synthetic.invalid/files/51/download",
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": pdf}
    bridge.synthetic.data["module_items"] = {
        "11": [
            {"type": "Assignment", "title": "Quiz 1", "content_id": 1},
            {"type": "File", "title": "Paper 3", "content_id": 51},
        ]
    }
    bridge.settings.file_reading_enabled = True

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    result = await academic_request(bridge, owner, seeded, academic.id, "exam")
    assert result.data["explicit_coverage_passages"]
    assert any("differentiation" in e["text"] for e in result.data["material_excerpts"])
    assert not result.data["candidate_readings"][0]["exam_coverage_confirmed"]
    raw["due_at"] = None
    unknown = await academic_request(bridge, owner, seeded, academic.id, "exam")
    assert unknown.status == "needs_input" and unknown.data["assessment"] is None


def context(**updates):
    return CalendarContext(
        calendar_id="student-calendar",
        timezone="America/New_York",
        retrieved_at=NOW,
        window_start=NOW,
        window_end=NOW + timedelta(days=20),
        pagination_complete=True,
        mapping_search_complete=True,
        events=[],
        **updates,
    )


def test_calendar_three_deadlines_one_existing_acceptance_and_reproducibility():
    items = [task(str(i), 20, NOW + timedelta(days=i)) for i in range(1, 4)]
    for i in items:
        i.source.url += "/" + i.id
    evidence = context()
    evidence.events = [
        CalendarEvent(
            id="existing",
            title=items[0].title,
            start=items[0].effective_due.timestamp,
            bridge_marker=marker("owner", "ref", items[0]),
            status="confirmed",
        )
    ]
    result = calendar_proposal(items, evidence, "owner", "ref", NOW)
    assert len(result["proposals"]) == 2 and len(result["mappings"]) == 1
    assert all(p["requires_explicit_confirmation"] for p in result["proposals"])
    assert not result["provider_writes_executed"]
    assert result == calendar_proposal(items, evidence, "owner", "ref", NOW)
    assert marker("other", "ref", items[0]) != marker("owner", "ref", items[0])


def test_calendar_changed_due_stale_duplicates_unknown_and_dst():
    item = task("a", 30, NOW.replace(month=11, day=2, hour=15))
    evidence = context()
    evidence.events = [
        CalendarEvent(
            id="event",
            title=item.title,
            start=NOW + timedelta(days=1),
            bridge_marker=marker("owner", "ref", item),
            status="confirmed",
            version="v1",
        )
    ]
    proposal = calendar_proposal([item], evidence, "owner", "ref", NOW)["proposals"][0]
    assert proposal["action"] == "update" and proposal["timing"]["start"].endswith("-05:00")
    evidence.events.append(evidence.events[0].model_copy(update={"id": "duplicate"}))
    duplicate = calendar_proposal([item], evidence, "owner", "ref", NOW)
    assert not duplicate["proposals"] and duplicate["ambiguous_matches"]
    evidence.retrieved_at = NOW - timedelta(minutes=6)
    assert calendar_proposal([item], evidence, "owner", "ref", NOW)["status"] == "needs_input"
    evidence.retrieved_at = NOW
    evidence.pagination_complete = False
    assert not calendar_proposal([item], evidence, "owner", "ref", NOW)["proposals"]


@pytest.mark.parametrize("action", ["deadlines", "instructions", "exam", "audit"])
async def test_all_academic_workflows_owner_selection_and_missing(
    bridge, owner, seeded, academic, action
):
    with pytest.raises(DomainError):
        await academic_request(bridge, "another-owner", seeded, academic.id, action)
    bundle = await collect_course(bridge, owner, seeded, academic.id)
    work_id = bundle["items"][0]["id"]
    bridge.synthetic.failures["/api/v1/courses/11/assignments"] = 403
    if action == "instructions":
        with pytest.raises(DomainError):
            await academic_request(bridge, owner, seeded, academic.id, action, work_id=work_id)
    else:
        result = await academic_request(bridge, owner, seeded, academic.id, action)
        assert result.status != "ok"
    bridge.select_courses(owner, seeded, [], "UTC")
    with pytest.raises(DomainError):
        await academic_request(bridge, owner, seeded, academic.id, action)


async def test_calendar_snapshot_auth_scope_stale_and_busy(bridge, owner, seeded):
    snap = await bridge.refresh(owner, seeded)
    now = utcnow()
    calendar = context().model_copy(
        update={
            "retrieved_at": now,
            "window_start": now,
            "window_end": now + timedelta(days=7),
            "availability_complete": True,
            "busy_times": [Window(start=now, end=now + timedelta(hours=1))],
        }
    )
    with pytest.raises(DomainError):
        await propose_sync(bridge, "other", seeded, snap.id, calendar)
    request = PlanRequest(windows=[Window(start=now, end=now + timedelta(hours=3))])
    result = await propose_sync(bridge, owner, seeded, snap.id, calendar, request)
    assert result.data["provider_writes_executed"] is False
    for block in result.data["study_plan"]["blocks"]:
        assert block["start"] >= (now + timedelta(hours=1)).isoformat()
    with bridge.store.transaction() as session:
        session.get(Snapshot, snap.id).created_at = now - timedelta(minutes=6)
    with pytest.raises(DomainError, match="Refresh"):
        await propose_sync(bridge, owner, seeded, snap.id, calendar)


async def test_integrated_five_supported_findings_no_false_error_claim(
    bridge, owner, seeded, academic, monkeypatch
):
    rows = bridge.synthetic.data["assignments"]["11"]
    rows.append(
        {
            **deepcopy(rows[0]),
            "id": 2,
            "name": "Quiz 2",
            "due_at": "2026-11-15T17:00:00Z",
            "description": "",
            "rubric": [],
        }
    )
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] += (
        "<p>Quiz 2: November 16, 2026</p>"
    )
    original = bridge.synthetic.handle

    def inconsistent(request):
        response = original(request)
        if request.url.path == "/api/v1/courses/11/assignments/2":
            data = response.json()
            data.pop("submission", None)
            return httpx.Response(200, json=data)
        return response

    monkeypatch.setattr(bridge.synthetic, "handle", inconsistent)
    result = await academic_request(bridge, owner, seeded, academic.id, "audit")
    kinds = [f["kind"] for f in result.data["findings"]]
    assert sorted(kinds) == sorted(
        [
            "missing_canvas_deadline",
            "instruction_conflict",
            "conflicting_deadlines",
            "assessment_requirements_unavailable",
            "inconsistent_submission_states",
        ]
    )
    assert result.data["checks"]["grades"] == "not_requested"
    assert all(f["impact"] and f["next_action"] for f in result.data["findings"])
    conflict = next(
        f for f in result.data["findings"] if f["kind"] == "inconsistent_submission_states"
    )
    assert conflict["state"] == "unknown"


async def test_announcements_scope_hidden_stale_and_untrusted(bridge, owner, seeded, academic):
    now = utcnow()
    base = {
        "id": 1,
        "context_code": "course_11",
        "posted_at": now.isoformat(),
        "title": "Updated date",
        "message": "<p>Exam 1: November 13, 2026</p><script>steal()</script>",
    }
    bridge.synthetic.data["announcements"]["11"] = [
        base,
        {**base, "id": 2, "context_code": "course_12"},
        {**base, "id": 3, "posted_at": (now - timedelta(days=181)).isoformat()},
        {**base, "id": 4, "posted_at": (now + timedelta(days=1)).isoformat()},
    ]
    result = await academic_request(bridge, owner, seeded, academic.id)
    assert len(result.data["obligations"]) == 2
    assert "steal()" not in result.model_dump_json()
    requests = [r for r in bridge.synthetic.requests if r.url.path == "/api/v1/announcements"]
    assert requests and all(r.url.params["context_codes[]"] == "course_11" for r in requests)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_http_mcp_new_tools_acceptance_and_auth(
    running, bridge, owner, seeded, academic, token_factory
):
    expected = {
        "reconcile_course_deadlines",
        "review_assignment_requirements",
        "prepare_for_assessment",
        "propose_calendar_sync",
        "audit_course_consistency",
    }
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert expected <= {t.name for t in tools}
                assert all(t.annotations.readOnlyHint for t in tools if t.name in expected)
                snap = await bridge.refresh(owner, seeded)
                work = next(i for i in snap.items if i["course_id"] == academic.id)
                reviewed = await session.call_tool(
                    "review_assignment_requirements",
                    {"connection_id": seeded, "course_id": academic.id, "work_id": work["id"]},
                )
                assert not reviewed.isError and reviewed.structuredContent["data"]["conflicts"]
                now = utcnow()
                calendar = context().model_copy(
                    update={
                        "retrieved_at": now,
                        "window_start": now,
                        "window_end": now + timedelta(days=7),
                    }
                )
                proposed = await session.call_tool(
                    "propose_calendar_sync",
                    {
                        "connection_id": seeded,
                        "snapshot_id": snap.id,
                        "calendar": calendar.model_dump(mode="json"),
                    },
                )
                assert (
                    not proposed.isError
                    and not proposed.structuredContent["data"]["provider_writes_executed"]
                )
                for name in (
                    "reconcile_course_deadlines",
                    "audit_course_consistency",
                    "prepare_for_assessment",
                ):
                    result = await session.call_tool(
                        name, {"connection_id": seeded, "course_id": academic.id}
                    )
                    assert not result.isError and result.structuredContent["evidence"]
                    denied = await session.call_tool(
                        name, {"connection_id": "foreign", "course_id": academic.id}
                    )
                    assert denied.structuredContent["status"] == "permission_denied"
