"""Synthetic reproductions of workload, discovery, OCR and inventory incidents."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge import academic_intelligence, parser_sandbox
from canvas_bridge.academic_intelligence import academic_request
from canvas_bridge.academic_rules import deadline_findings
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.course_files import list_files, read_file, search_files
from canvas_bridge.document_diagnostics import diagnostics
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_worker import extract
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Material
from tests.test_academic_intelligence import academic as academic
from tests.test_academic_intelligence import source_doc
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running

NOW = datetime(2026, 10, 23, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    "submission,types,expected,action,section",
    [
        (
            {"workflow_state": "submitted", "submitted_at": "2026-10-21T12:00:00Z"},
            ["online_upload"],
            "submitted",
            "none_indicated",
            "submitted",
        ),
        (
            {"workflow_state": "submitted", "submitted_at": "2026-10-21T12:00:00Z", "attempt": 2},
            ["online_upload"],
            "resubmitted",
            "none_indicated",
            "resubmitted",
        ),
        (
            {
                "workflow_state": "graded",
                "submitted_at": "2026-10-21T12:00:00Z",
                "posted_at": "2026-10-22T12:00:00Z",
            },
            ["online_upload"],
            "graded",
            "none_indicated",
            "graded",
        ),
        (
            {"workflow_state": "unsubmitted"},
            ["online_upload"],
            "not_submitted",
            "submit",
            "overdue",
        ),
        (None, ["online_upload"], "unknown", "unknown", "past_due_unknown"),
        (
            {"workflow_state": "unsubmitted", "submitted_at": "2026-10-21T12:00:00Z"},
            ["online_upload"],
            "unknown",
            "unknown",
            "past_due_unknown",
        ),
        (
            {"workflow_state": "submitted"},
            ["online_upload"],
            "unknown",
            "unknown",
            "past_due_unknown",
        ),
        (
            {"workflow_state": "unsubmitted"},
            ["on_paper"],
            "not_applicable",
            "unknown",
            "past_due_unknown",
        ),
        (
            {"workflow_state": "unsubmitted"},
            ["none"],
            "not_applicable",
            "unknown",
            "past_due_unknown",
        ),
        (
            {"workflow_state": "unsubmitted", "excused": True},
            ["online_upload"],
            "excused",
            "none_indicated",
            "excused",
        ),
        (
            {"workflow_state": "graded", "posted_at": "2026-10-22T12:00:00Z"},
            ["online_upload"],
            "graded",
            "unknown",
            "graded",
        ),
        (
            {"workflow_state": "unsubmitted", "user_id": 999},
            ["online_upload"],
            "unknown",
            "unknown",
            "past_due_unknown",
        ),
    ],
)
async def test_workload_past_due_is_not_a_submission_instruction(
    bridge, owner, seeded, monkeypatch, submission, types, expected, action, section
):
    monkeypatch.setattr("canvas_bridge.service.utcnow", lambda: NOW)
    monkeypatch.setattr("canvas_bridge.authorization.utcnow", lambda: NOW)
    raw = {
        "id": 1001,
        "name": "Synthetic task",
        "due_at": "2026-10-21T12:00:00Z",
        "submission_types": types,
    }
    if submission is not None:
        raw["submission"] = {"user_id": 101, **submission}
    bridge.synthetic.data["assignments"] = {"11": [raw]}
    result = await bridge.workload(owner, seeded, NOW, NOW + timedelta(days=14), "America/New_York")
    item = result.data["items"][0]
    assert item["due_date_relationship"] == "past_due"
    assert item["window_relationship"] == "before_window"
    assert item["work_status"] == expected
    assert item["outstanding_action"] == action
    assert item["section"] == section
    assert item["source"]["url"] and result.sources
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_future_window_does_not_make_unfinished_work_overdue(
    bridge, owner, seeded, monkeypatch
):
    monkeypatch.setattr("canvas_bridge.service.utcnow", lambda: NOW)
    monkeypatch.setattr("canvas_bridge.authorization.utcnow", lambda: NOW)
    bridge.synthetic.data["assignments"] = {
        "11": [
            {
                "id": 1001,
                "name": "Next week",
                "due_at": "2026-10-25T12:00:00Z",
                "submission_types": ["online_upload"],
                "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
            }
        ]
    }
    result = await bridge.workload(
        owner, seeded, NOW + timedelta(days=4), NOW + timedelta(days=14), "UTC"
    )
    assert result.data["items"][0]["section"] == "upcoming"
    assert result.data["items"][0]["due_date_relationship"] == "not_yet_due"
    omitted = await bridge.workload(
        owner,
        seeded,
        NOW + timedelta(days=4),
        NOW + timedelta(days=14),
        "UTC",
        include_overdue=False,
    )
    assert not omitted.data["items"]


def schedule_pdf(bridge, text="Exam 1: November 12, 2026"):
    body = scientific_pdf([text])
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["files"]["11"][0].update(
        display_name="Course Schedule_rev092926.pdf",
        filename="Course_Schedule_rev092926.pdf",
        size=len(body),
    )


@pytest.mark.parametrize("hint", ["title", "filename", "module", "module_only"])
async def test_schedule_discovery_names_and_modules(
    bridge, owner, seeded, academic, readable, hint
):
    course, file_id = readable
    schedule_pdf(bridge)
    file = bridge.synthetic.data["files"]["11"][0]
    if hint != "title":
        file["display_name"] = "Document.pdf"
    if hint in {"module", "module_only"}:
        file["filename"] = "document.pdf"
        bridge.synthetic.data["module_items"]["11"][0]["title"] = "Course_Schedule_rev092926.pdf"
    if hint == "module_only":
        bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    result = await academic_request(bridge, owner, seeded, course.id)
    discovery = result.data["material_discovery"]
    assert discovery["state"] == "schedule_reviewed_with_candidates"
    reviewed = next(d for d in discovery["documents"] if d["material_id"] == file_id)
    assert reviewed["state"] == "reviewed"
    assert reviewed["source_version"] and reviewed["content_hash"]
    evidence = next(
        o["evidence"] for o in result.data["obligations"] if o["evidence"]["source_id"] == file_id
    )
    assert evidence["locator"] == "PDF page 1"
    assert evidence["document_version"] == reviewed["content_hash"]
    assert evidence["source_version"] == reviewed["source_version"]
    if hint == "module_only":
        assert not discovery["inventory_complete"]
        assert result.data["inventory_coverage"]["files"] == "partial"
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_discovery_absent_and_reviewed_without_obligations_differ(
    bridge, owner, seeded, academic, readable
):
    course, _ = readable
    # The synthetic page inventory contains a syllabus title, so remove it here.
    bridge.synthetic.failures["/api/v1/courses/11/pages"] = 403
    absent = await academic_request(bridge, owner, seeded, course.id)
    assert absent.data["material_discovery"]["state"] == "no_schedule_discovered"
    schedule_pdf(bridge, "November 12, 2026: Motivation and discussion.")
    reviewed = await academic_request(bridge, owner, seeded, course.id)
    assert (
        reviewed.data["material_discovery"]["state"] == "schedule_reviewed_no_matching_obligations"
    )


async def test_discovery_limits_prioritize_pdf_and_report_unread(
    bridge, owner, seeded, academic, readable, monkeypatch
):
    course, file_id = readable
    schedule_pdf(bridge)
    monkeypatch.setattr(academic_intelligence, "MAX_DOCUMENTS", 1)
    result = await academic_request(bridge, owner, seeded, course.id)
    documents = result.data["material_discovery"]["documents"]
    assert documents[0]["material_id"] == file_id and documents[0]["state"] == "reviewed"
    assert any(d.get("reason_code") == "MATERIAL_DOCUMENT_LIMIT" for d in documents[1:])
    assert len([r for r in bridge.synthetic.requests if r.url.path.endswith("/download")]) == 1


@pytest.mark.parametrize("failure", ["timeout", "budget", "permission", "parse"])
async def test_discovery_failures_are_not_empty_review(
    bridge, owner, seeded, academic, readable, monkeypatch, failure
):
    course, file_id = readable
    schedule_pdf(bridge)

    async def fail(*args, **kwargs):
        if failure == "timeout":
            await asyncio.Event().wait()
        raise DomainError(
            "permission_denied" if failure == "permission" else "retry_later",
            "Synthetic failure",
            reason_code="SYNTHETIC_FAILURE",
        )

    if failure == "budget":
        monkeypatch.setattr(academic_intelligence, "MATERIAL_SECONDS", 0)
    else:
        monkeypatch.setattr(academic_intelligence, "fetch_material", fail)
    monkeypatch.setattr(academic_intelligence, "MATERIAL_READ_SECONDS", 0.01)
    result = await academic_request(bridge, owner, seeded, course.id, material_ids=[file_id])
    discovery = result.data["material_discovery"]
    assert discovery["state"] == "schedule_not_reviewed"
    status = discovery["documents"][0]
    assert status["reason_code"] == {
        "timeout": "MATERIAL_READ_TIMEOUT",
        "budget": "MATERIAL_TIME_BUDGET",
    }.get(failure, "SYNTHETIC_FAILURE")


def test_classroom_activities_do_not_become_assignment_deadlines():
    result = deadline_findings(
        [
            source_doc(
                "Lab discussion: November 12, 2026\nProject workshop: November 13, 2026\nReport due: November 14, 2026"
            )
        ],
        [],
        "UTC",
        True,
    )
    assert len(result["classroom_activities"]) == 2
    assert len(result["obligations"]) == 1
    assert all(not o["assignment_deadline_confirmed"] for o in result["obligations"])
    assert len(result["findings"]) == 1


def ocr_worker(monkeypatch, page_count, failure_pages=()):
    data = scientific_pdf([""] * page_count)

    def worker(body, kind, root, **kwargs):
        if not kwargs.get("visual"):
            return extract(body, kind)
        page = kwargs["visual"]["page"]
        if page in failure_pages:
            raise DomainError(
                "retry_later",
                "Worker timed out.",
                reason_code="DOCUMENT_WORKER_TIMEOUT",
                processing_stage="worker_execution",
            )
        return {
            "pixels": [612, 792],
            "ocr": {
                "text": "Motivation: synthetic course schedule text.",
                "mean_confidence": 88.5,
                "method": "tesseract",
                "words": [],
            },
        }

    monkeypatch.setattr(parser_sandbox, "extract_isolated", worker)
    return data


@pytest.mark.parametrize(
    "pages,failures,accepted,failed,skipped",
    [(1, (), 1, 0, 0), (2, (2,), 1, 1, 0), (6, (), 4, 0, 2)],
)
async def test_ocr_success_partial_and_budget_diagnostics(
    settings, tmp_path, monkeypatch, pages, failures, accepted, failed, skipped
):
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path / "parser"
    settings.ocr_root = tmp_path / "ocr"
    data = ocr_worker(monkeypatch, pages, failures)
    result = await parser_sandbox.extract_document(data, "pdf", settings)
    info = diagnostics(result["pages"], result["warnings"], result["page_count"])
    assert not any("No readable text" in w for w in info["limitations"])
    assert info["ocr_coverage"]["accepted_pages"] == accepted
    assert info["ocr_coverage"]["failed_pages"] == failed
    assert info["ocr_coverage"]["skipped_budget_pages"] == skipped
    assert info["ocr_confidence"]["pages"][0]["mean_confidence"] == 88.5
    assert info["parser_warnings"]
    assert bool(info["document_diagnostics"]) == bool(failed or skipped)
    assert result["coverage"] == "partial"  # Confidence never claims verified interpretation.


@pytest.mark.parametrize("failed", [False, True])
async def test_ocr_search_preserves_success_or_timeout_failure(
    bridge, owner, seeded, readable, tmp_path, monkeypatch, failed
):
    course, _ = readable
    bridge.settings.parser_root = tmp_path / "parser"
    bridge.settings.ocr_root = tmp_path / "ocr"
    data = ocr_worker(monkeypatch, 1, (1,) if failed else ())
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    monkeypatch.setattr(
        "canvas_bridge.course_files.extract_document", parser_sandbox.extract_document
    )
    result = await search_files(bridge, owner, seeded, course.id, "Motivation", include_unread=True)
    status = result.data["document_statuses"][0]
    if failed:
        assert status["state"] == "failed"
        assert status["reason_code"] == "DOCUMENT_WORKER_TIMEOUT"
        assert status["search_outcome"] == "failed"
        assert not status["document_search_finished"]
        assert not result.data["results"]
    else:
        assert result.data["results"][0]["ocr_confidence"] == 88.5
        assert status["search_outcome"] == "matched"
        assert status["ocr_coverage"]["accepted_pages"] == 1
        assert "No readable text" not in result.model_dump_json()


@pytest.mark.parametrize("branch", [Endpoint.PAGES, Endpoint.FILES, Endpoint.MODULES])
async def test_inventory_branch_timeout_keeps_valid_files(
    bridge, owner, seeded, readable, monkeypatch, branch
):
    course, _ = readable
    original = CanvasClient._get
    bridge.settings.refresh_budget_seconds = 0.5

    async def get(client, url):
        if url.split("?", 1)[0] == client.url(branch, course="11"):
            await asyncio.Event().wait()
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", get)
    result = await list_files(bridge, owner, seeded, course.id)
    assert len(result.data["files"]) == 1
    assert result.status == "partial_data"
    failure = next(iter(result.data["inventory_reason_codes"].values()))
    assert failure["reason_code"] == "INVENTORY_BRANCH_TIMEOUT"
    assert result.data["files"][0]["inventory_freshness"] == "fresh"
    assert result.data["inventory_status"]["completeness"] == "partial"


async def test_retained_references_propagate_coverage_and_require_fresh_access(
    bridge, owner, seeded, academic, readable, monkeypatch
):
    course, file_id = readable
    schedule_pdf(bridge)
    await read_file(bridge, owner, seeded, file_id)
    before = await list_files(bridge, owner, seeded, course.id)
    checked_at = before.data["files"][0]["inventory_checked_at"]
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    original = CanvasClient.one

    async def one(client, endpoint, **ids):
        if endpoint == Endpoint.FILE:
            raise DomainError(
                "retry_later", "Synthetic metadata outage", reason_code="UPSTREAM_UNAVAILABLE"
            )
        return await original(client, endpoint, **ids)

    monkeypatch.setattr(CanvasClient, "one", one)
    retained = await list_files(bridge, owner, seeded, course.id)
    file = retained.data["files"][0]
    assert file["access_state"] == "not_rechecked"
    assert file["inventory_freshness"] == "retained"
    assert file["reference_origin"] == "previously_discovered_module_file"
    assert file["inventory_checked_at"] == checked_at
    assert retained.data["inventory_status"]["retained_file_count"] == 1
    planned = await academic_request(bridge, owner, seeded, course.id)
    assert planned.data["inventory_status"]["completeness"] == "partial"
    assert any(
        c.resource == "materials_inventory" and c.state == "partial" for c in planned.meta.coverage
    )
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, file_id)
    with bridge.store.transaction() as session:
        assert not session.get(Material, file_id).text
    search = await search_files(bridge, owner, seeded, course.id, "Exam", include_unread=True)
    assert search.status == "partial_data" and not search.data["results"]
    assert not search.data["text_coverage_complete_in_bounded_inventory"]


async def test_workload_continuation_keeps_status_time_and_sort_order(
    bridge, owner, seeded, monkeypatch
):
    clock = [NOW]
    monkeypatch.setattr("canvas_bridge.service.utcnow", lambda: clock[0])
    monkeypatch.setattr("canvas_bridge.authorization.utcnow", lambda: clock[0])
    bridge.synthetic.data["assignments"] = {
        "11": [
            {
                "id": i,
                "name": f"Task {i}",
                "due_at": (NOW + timedelta(seconds=i)).isoformat(),
                "submission_types": ["online_upload"],
                "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
            }
            for i in range(1, 4)
        ]
    }
    first = await bridge.workload(owner, seeded, NOW, NOW + timedelta(days=1), "UTC", limit=1)
    clock[0] += timedelta(seconds=30)
    second = await bridge.workload(
        owner, seeded, NOW, NOW + timedelta(days=1), "UTC", limit=1, cursor=first.meta.next_cursor
    )
    assert second.data["status_as_of"] == first.data["status_as_of"]
    assert second.data["items"][0]["section"] == "upcoming"
    assert second.data["items"][0]["id"] != first.data["items"][0]["id"]


async def test_old_ocr_cache_is_reprocessed(bridge, owner, seeded, readable, tmp_path, monkeypatch):
    _, file_id = readable
    bridge.settings.parser_root = tmp_path / "parser"
    bridge.settings.ocr_root = tmp_path / "ocr"
    data = ocr_worker(monkeypatch, 1)
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    monkeypatch.setattr(
        "canvas_bridge.course_files.extract_document", parser_sandbox.extract_document
    )
    await read_file(bridge, owner, seeded, file_id)
    with bridge.store.transaction() as session:
        row = session.get(Material, file_id)
        row.file_state = {k: v for k, v in row.file_state.items() if k != "ocr_diagnostics_version"}
        row.limitations = [
            "No readable text was extracted. Do not infer this document's subject from its filename."
        ]
    before = len([r for r in bridge.synthetic.requests if r.url.path.endswith("/download")])
    result = await read_file(bridge, owner, seeded, file_id)
    assert "No readable text" not in result.model_dump_json()
    assert (
        len([r for r in bridge.synthetic.requests if r.url.path.endswith("/download")])
        == before + 1
    )


@pytest.mark.contract
async def test_incident_fields_through_authenticated_mcp(
    running, bridge, owner, seeded, academic, readable, token_factory
):
    course, _ = readable
    schedule_pdf(bridge)
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["due_at"] = "2026-10-21T12:00:00Z"
    raw["submission"] = {
        "user_id": 101,
        "workflow_state": "submitted",
        "submitted_at": "2026-10-22T12:00:00Z",
    }
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                common = {"connection_id": seeded, "course_id": course.id}
                calls = [
                    (
                        "get_workload",
                        {
                            "connection_id": seeded,
                            "course_ids": [course.id],
                            "start": NOW.isoformat(),
                            "end": (NOW + timedelta(days=14)).isoformat(),
                            "timezone": "UTC",
                        },
                    ),
                    ("list_course_files", common),
                    ("reconcile_course_deadlines", common),
                    ("search_course_files", {**common, "query": "Exam", "include_unread": True}),
                ]
                results = []
                catalog = {tool.name: tool for tool in (await session.list_tools()).tools}
                for name, args in calls:
                    assert catalog[name].annotations.readOnlyHint
                    response = await session.call_tool(name, args)
                    assert not response.isError
                    results.append(response.structuredContent["data"])
                assert results[0]["items"][0]["section"] == "submitted"
                assert results[1]["inventory_status"]["content_reads_require_fresh_authorization"]
                assert (
                    results[2]["material_discovery"]["state"] == "schedule_reviewed_with_candidates"
                )
                assert results[3]["document_statuses"][0]["search_outcome"] == "matched"
                assert "parser_warnings" in results[3]["document_statuses"][0]
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
