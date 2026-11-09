"""Assessment review over synthetic provider reads, including partial and denied sources."""

import asyncio
from datetime import timedelta
from time import monotonic

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge import academic_intelligence as academic_api
from canvas_bridge.course_files import read_file
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.parser_worker import extract
from tests.test_academic_intelligence import academic as academic
from tests.test_course_files import file_record
from tests.test_domain_planning import NOW
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


@pytest.fixture
def papers(bridge, academic):
    text = "Dr. Cedar Linden. Office hours Monday. Membrane diffusion regulates transport. "
    bodies = {i: scientific_pdf([text * 9] * (13 if i == 51 else 1)) for i in range(51, 59)}
    bodies[58] = scientific_pdf([" "])
    # Distinct bytes identify the slow document without changing the reader or access checks.
    bodies[56] = scientific_pdf(["delayed parser"])
    data = bridge.synthetic.data
    data["assignments"]["11"][0].update(
        due_at=(utcnow() + timedelta(days=2)).isoformat(),
        description='<p>See the <a href="/courses/11/files/51">linked article</a>.</p>',
    )
    data["files"] = {
        "11": [
            file_record(
                id=i,
                display_name=f"Reading {i}.pdf",
                filename=f"reading{i}.pdf",
                size=len(body),
                updated_at=NOW.isoformat(),
                url=f"https://canvas.synthetic.invalid/files/{i}/download",
            )
            for i, body in bodies.items()
        ]
    }
    data["file_bodies"] = {str(i): body for i, body in bodies.items()}
    data["module_items"] = {
        "11": [
            {"type": "Assignment", "title": "Exam 1", "content_id": 1},
            *[{"type": "File", "title": f"Reading {i}", "content_id": i} for i in reversed(bodies)],
        ]
    }
    bridge.settings.file_reading_enabled = True
    bridge.synthetic.failures["/api/v1/courses/11/files/57"] = 403
    return bodies


async def test_thorough_breadth_depth_and_excerpt_resume(
    bridge, owner, seeded, academic, papers, monkeypatch
):
    bodies = papers
    calls = []

    slow = True

    async def parser(data, kind, settings, page_range=None):
        calls.append((data, page_range))
        if slow and data == bodies[56]:
            await asyncio.sleep(5)
        await asyncio.sleep(0.01)
        return extract(data, kind, page_range)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    # Stop after breadth and one depth batch to exercise both continuation paths.
    monkeypatch.setattr(academic_api, "THOROUGH_BATCH_LIMIT", 10)
    monkeypatch.setattr(academic_api, "EXAM_BATCH_SECONDS", 1.0)
    start = monotonic()
    result = await academic_api.academic_request(
        bridge, owner, seeded, academic.id, "exam", review_mode="thorough"
    )
    review = result.data["material_discovery"]
    records = review["documents"]
    first = records[0]
    print(
        "assessment seconds",
        round(monotonic() - start, 2),
        "fixture bytes",
        sum(map(len, bodies.values())),
        "provider calls",
        len(bridge.synthetic.requests),
        "parser calls",
        len(calls),
        "candidates",
        len(records),
        "states",
        [r["state"] for r in records],
        "extracted pages",
        [r.get("extracted_pages") for r in records],
    )
    assert first["discovery_basis"] == ["explicit_assignment_link"]
    assert result.status == "partial_data" and len(records) > 6
    assert first["state"] == "partially_reviewed" and first["extracted_pages"][:4] == [1, 2, 3, 4]
    assert all(window[0] == 1 for _, window in calls[:-1])
    assert sum(r["state"] == "reviewed" for r in records) >= 4
    assert any(r.get("reason_code") == "MATERIAL_READ_TIMEOUT" for r in records)
    assert any(r["state"] == "inaccessible" for r in records)
    assert any(r["state"] == "unreadable" for r in records)
    assert (
        first["excerpt_truncated"]
        and first["excerpt_characters"] < first["total_extracted_characters"]
    )
    assert all(not r["exam_coverage_confirmed"] for r in result.data["candidate_readings"])
    concepts = {c["term"]: c for c in result.data["repeated_concepts"]}
    assert (
        concepts["diffusion"]["evidence"] and not concepts["diffusion"]["exam_coverage_confirmed"]
    )
    assert not {"cedar", "linden", "hours", "monday"} & concepts.keys()
    assert result.data["coverage_status"] == "not_established"

    async def resume(args):
        args = dict(args)
        return await read_file(
            bridge, owner, args.pop("connection_id"), args.pop("file_id"), **args
        )

    previous = len(calls)
    chunk = await resume(first["excerpt_continuation"])
    assert chunk.data["text"] and len(calls) == previous
    chunk = await resume(first["extraction_continuation"])
    assert chunk.data["page_start"] == first["extracted_pages"][-1] + 1
    assert len(calls) == previous + 1
    pending = review["continuation"]["material_ids"]
    assert first["material_id"] not in pending
    assert not any(
        r["material_id"] in pending for r in records if r["state"] in {"inaccessible", "reviewed"}
    )

    slow = False
    args = dict(review["continuation"])
    previous = len(calls)
    resumed = await academic_api.academic_request(
        bridge, owner, args.pop("connection_id"), args.pop("course_id"), "exam", **args
    )
    assert [d["material_id"] for d in resumed.data["material_discovery"]["documents"]] == pending
    assert len(calls) == previous + 1 and calls[-1][0] == bodies[56]

    # A shared task denial in the middle of breadth defers the suffix without more attempts.
    original = academic_api.fetch_material
    touched = []

    async def limited(*args, **kwargs):
        touched.append(args[3])
        if len(touched) == 2:
            raise DomainError(
                "partial_data", "Fixture task exhausted.", reason_code="TASK_BUDGET_EXCEEDED"
            )
        return await original(*args, **kwargs)

    monkeypatch.setattr(academic_api, "fetch_material", limited)
    selected = [r["material_id"] for r in records if r["state"] == "reviewed"]
    limited_pack = await academic_api.academic_request(
        bridge,
        owner,
        seeded,
        academic.id,
        "exam",
        material_ids=selected,
        work_id=result.data["assessment"]["work_id"],
    )
    limited_review = limited_pack.data["material_discovery"]
    assert touched == selected[:2]
    assert limited_review["documents"][0]["state"] == "reviewed"
    assert limited_review["continuation"]["material_ids"] == selected[1:]


async def test_default_budgets_finish_long_pdf(
    bridge, owner, seeded, academic, papers, monkeypatch
):
    async def parser(data, kind, settings, page_range=None):
        return extract(data, kind, page_range)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    for mode, expected, pages in [("standard", 6, 4), ("thorough", 12, 13)]:
        before = len(bridge.synthetic.requests)
        start = monotonic()
        result = await academic_api.academic_request(
            bridge, owner, seeded, academic.id, "exam", review_mode=mode
        )
        review = result.data["material_discovery"]
        first = review["documents"][0]
        assert review["document_limit"] == expected and first["usable_pages"] == list(
            range(1, pages + 1)
        )
        print(
            mode,
            "elapsed",
            round(monotonic() - start, 2),
            "requests",
            len(bridge.synthetic.requests) - before,
            "batches",
            review["batches_attempted"],
            "long PDF",
            first["total_extracted_characters"],
            "extracted",
            first["excerpt_characters"],
            "excerpt characters",
        )
        if mode == "standard":
            assert (
                sum(d["reason_code"] == "MATERIAL_DOCUMENT_LIMIT" for d in review["documents"]) == 3
            )
        else:
            assert first["state"] == "reviewed" and "extraction_continuation" not in first
            assert first["excerpt_truncated"] and first["excerpt_continuation"]


async def test_mcp_shared_task_budget_and_scoped_resume(
    running, bridge, owner, seeded, academic, papers, token_factory, monkeypatch
):
    async def parser(data, kind, settings, page_range=None):
        return extract(data, kind, page_range)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                args = dict(connection_id=seeded, course_id=academic.id, review_mode="thorough")
                before = len(bridge.synthetic.requests)
                start = monotonic()
                response = await session.call_tool("prepare_for_assessment", args)
                assert not response.isError
                result = response.structuredContent
                review = result["data"]["material_discovery"]
                print(
                    "MCP elapsed",
                    round(monotonic() - start, 2),
                    result["status"],
                    "requests",
                    len(bridge.synthetic.requests) - before,
                    "states",
                    [(d["state"], d.get("reason_code")) for d in review["documents"]],
                )
                assert result["status"] == "partial_data"
                assert review["review_mode"] == "thorough"
                first = review["documents"][0]
                assert first["usable_pages"] == [1, 2, 3, 4]
                assert first["extraction_continuation"]["expected_hash"] == first["content_hash"]
                assert any(
                    d.get("reason_code") == "TASK_BUDGET_EXCEEDED" for d in review["documents"]
                )
                pending = review["continuation"]
                assert first["material_id"] not in pending["material_ids"]
                resumed = await session.call_tool("prepare_for_assessment", pending)
                assert not resumed.isError
                rows = resumed.structuredContent["data"]["material_discovery"]["documents"]
                assert [d["material_id"] for d in rows] == pending["material_ids"]
                assert any(d["state"] == "reviewed" for d in rows)


async def test_withheld_text_and_denied_anchor(
    bridge, owner, seeded, academic, papers, monkeypatch
):
    data = bridge.synthetic.data
    data["assignments"]["11"][0]["description"] += (
        '<a href="/courses/11/files/57">Additional article</a>'
    )
    body = scientific_pdf(["Professor Cedar Linden."])
    data["file_bodies"]["51"] = body
    data["files"]["11"][0]["size"] = len(body)

    async def parser(data, kind, settings, page_range=None):
        return extract(data, kind, page_range)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    result = await academic_api.academic_request(bridge, owner, seeded, academic.id, "exam")
    first = result.data["material_discovery"]["documents"][0]
    assert first["usable_pages"] == [] and first["total_extracted_characters"] == 0
    assert first["state"] == "unreadable" and first["reason_code"] == "MATERIAL_CONTENT_WITHHELD"
    assert first["material_id"] not in {e["source_id"] for e in result.data["material_excerpts"]}
    denied = next(
        r for r in result.data["linked_materials"]["references"] if r["state"] == "denied"
    )
    assert denied["reason_code"] == "RESOURCE_PERMISSION_DENIED" and not denied["content_reviewed"]
