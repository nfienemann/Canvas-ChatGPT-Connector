"""Synthetic schedule evidence: source precision, midnight and DST must survive MCP."""

from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.academic_dates import DATES, parse_candidate
from canvas_bridge.academic_intelligence import academic_request
from canvas_bridge.academic_rules import dated_obligations, deadline_findings
from canvas_bridge.domain import DomainError, FactDate
from tests.test_academic_intelligence import academic as academic
from tests.test_academic_intelligence import ooxml, source_doc
from tests.test_course_files import file_record
from tests.test_domain_planning import NOW, task
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


def candidate(text):
    matches = list(DATES.finditer(text))
    assert len(matches) == 1
    return parse_candidate(matches[0])


def comparison(text, due, zone="America/New_York"):
    item = task("a")
    item.title = "Exam 1"
    item.effective_due = FactDate.model_validate(due)
    return deadline_findings(
        [source_doc("Exam 1: " + text)], [item.model_dump(mode="json")], zone, True
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Nov. 12, 2026", "2026-11-12"),
        ("12th November 2026", "2026-11-12"),
        ("Sept 1st 2026", "2026-09-01"),
        ("2026-11-12T19:00:00Z", "2026-11-12T19:00:00+00:00"),
        ("12 Nov. 2026 at 2 p.m. America/New_York", "2026-11-12T14:00:00-05:00"),
        ("Nov 12, 2026 at 14:00 +0530", "2026-11-12T14:00:00+05:30"),
        ("Nov 12, 2026 at 12 AM UTC", "2026-11-12T00:00:00+00:00"),
        ("Nov 12, 2026 at 12 PM GMT", "2026-11-12T12:00:00+00:00"),
    ],
)
def test_T11_T15_explicit_date_grammar(text, expected):
    value = candidate(text)
    assert value["date"] == expected and value["raw_date"] == text
    assert value["normalization_status"] == "normalized"


@pytest.mark.parametrize(
    "text,reason",
    [
        ("November 12", "Year"),
        ("Nov. 12, 2026 at 2 PM", "timezone"),
        ("Nov 12, 2026 at 2 PM EST", "abbreviation"),
        ("11/12/2026", "order"),
        ("11/12/26", "order"),
        ("Feb 30, 2026", "range"),
        ("Nov 12, 2026 at 25:00 UTC", "hour"),
        ("Nov 12, 2026 at 13 PM UTC", "12-hour"),
        ("2026-11-12T14:00-00:00", "unknown"),
        ("2026-11-12T14:00+05:90", "offset"),
        ("Nov 12, 2026 at 14:00 Invalid/Zone", "recognized"),
        ("Nov 1, 2026 at 01:30 America/New_York", "daylight-saving"),
        ("Mar 8, 2026 at 02:30 America/New_York", "daylight-saving"),
    ],
)
def test_T11_T15_uncertainty_is_not_a_date(text, reason):
    value = candidate(text)
    assert value["date"] is None and value["normalization_status"] == "unresolved"
    assert any(reason in warning for warning in value["uncertainty"])
    result = comparison(text, {"kind": "timestamp", "timestamp": "2026-11-12T19:00:00Z"})
    assert result["findings"][0]["kind"] == "source_date_unresolved"
    assert result["comparisons"][0]["outcome"] == "indeterminate"


def test_T11_T15_equal_instants_and_source_zone_preserved():
    result = comparison(
        "12 Nov 2026 at 14:00 America/New_York",
        {"kind": "timestamp", "timestamp": "2026-11-12T19:00:00Z"},
    )
    assert not result["findings"]
    assert result["comparisons"][0]["outcome"] == "same_at_available_precision"
    assert result["obligations"][0]["timezone"] == "America/New_York"
    conflict = comparison(
        "12 Nov 2026 at 14:00 America/New_York",
        {"kind": "timestamp", "timestamp": "2026-11-12T20:00:00Z"},
    )
    assert conflict["findings"][0]["kind"] == "conflicting_deadlines"


@pytest.mark.parametrize(
    "text,due",
    [
        ("2026-11-13T01:00Z", {"kind": "local_date", "local_date": "2026-11-12"}),
        ("Nov 12, 2026", {"kind": "timestamp", "timestamp": "2026-11-13T01:00Z"}),
    ],
)
def test_T15_midnight_date_comparison_normalizes_either_timestamp(text, due):
    result = comparison(text, due)
    assert not result["findings"]
    evidence = result["comparisons"][0]
    assert evidence["source_calendar_date"] == evidence["canvas_calendar_date"] == "2026-11-12"
    assert evidence["time_agreement_established"] is False
    missing = comparison(text, due, None)
    assert missing["findings"][0]["kind"] == "timezone_unresolved"
    invalid = comparison(text, due, "Invalid/Zone")
    assert invalid["findings"][0]["kind"] == "timezone_unresolved"


def test_T11_stable_obligation_identity_and_exact_offsets():
    text = "  Exam 1: Nov. 12, 2026 at 2 PM UTC\n  Quiz 2: 13 Nov 2026"
    doc = source_doc(text)
    first = dated_obligations([doc])
    refreshed = deepcopy(doc)
    refreshed["retrieved_at"] = (NOW + timedelta(minutes=5)).isoformat()
    assert [o["id"] for o in first] == [o["id"] for o in dated_obligations([refreshed])]
    for o in first:
        assert text[o["date_offset"] : o["date_offset"] + len(o["raw_date"])] == o["raw_date"]
        e = o["evidence"]
        assert text[e["offset"] : e["offset"] + len(e["passage"])] == e["passage"]
    for field in ("version", "course_id", "id"):
        altered = {**doc, field: "different"}
        assert dated_obligations([altered])[0]["id"] != first[0]["id"]


async def test_T11_T15_html_schedule_missing_due_and_refreshed_versions(
    bridge, owner, seeded, academic
):
    raw = bridge.synthetic.data["course_details"]["11"]
    raw["syllabus_body"] = "<p>Exam 1: Nov. 12, 2026 at 2 PM America/New_York</p>"
    result = await academic_request(bridge, owner, seeded, academic.id)
    finding = result.data["findings"][0]
    assert finding["kind"] == "missing_canvas_deadline"
    assert finding["obligation"]["date"] == "2026-11-12T14:00:00-05:00"
    again = await academic_request(bridge, owner, seeded, academic.id)
    assert again.data["obligations"][0]["id"] == result.data["obligations"][0]["id"]
    raw["syllabus_body"] = "<p>Exam 1: Nov. 13, 2026 at 2 PM America/New_York</p>"
    fresh = await academic_request(bridge, owner, seeded, academic.id)
    assert fresh.data["obligations"][0]["date"].startswith("2026-11-13")
    assert fresh.data["obligations"][0]["id"] != result.data["obligations"][0]["id"]
    with pytest.raises(DomainError):
        await academic_request(bridge, "other-owner", seeded, academic.id)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_T11_T21_http_mcp_date_evidence(
    running, bridge, owner, seeded, academic, token_factory
):
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] = (
        "<p>Exam 1: Nov. 12, 2026 at 2 PM UTC</p>"
    )
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "reconcile_course_deadlines",
                    {"connection_id": seeded, "course_id": academic.id},
                )
                assert not result.isError
                data = result.structuredContent
                assert (
                    data["data"]["findings"][0]["obligation"]["date"] == "2026-11-12T14:00:00+00:00"
                )
                assert (
                    data["evidence"] and data["data"]["content_boundary"] == "untrusted_source_data"
                )
                denied = await session.call_tool(
                    "reconcile_course_deadlines",
                    {"connection_id": "foreign", "course_id": academic.id},
                )
                assert denied.structuredContent["status"] == "permission_denied"


@pytest.mark.parametrize(
    "kind,mime",
    [
        ("pdf", "application/pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ],
)
async def test_T11_authenticated_schedule_document_dates(
    bridge, owner, seeded, academic, monkeypatch, kind, mime
):
    from canvas_bridge.parser_worker import extract

    text = "Exam 1: 12 Nov 2026 at 14:00 America/New_York"
    body = scientific_pdf([text]) if kind == "pdf" else ooxml(kind, [text])
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] = ""
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                display_name="Schedule." + kind,
                filename="schedule." + kind,
                size=len(body),
                updated_at=NOW.isoformat(),
                url="https://canvas.synthetic.invalid/files/51/download",
                **{"content-type": mime},
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": body}
    bridge.synthetic.data["file_types"] = {"51": mime}
    bridge.settings.file_reading_enabled = True

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    result = await academic_request(bridge, owner, seeded, academic.id)
    finding = next(f for f in result.data["findings"] if f["kind"] == "missing_canvas_deadline")
    obligation = finding["obligation"]
    assert obligation["date"] == "2026-11-12T14:00:00-05:00"
    assert ("page" if kind == "pdf" else "section") in obligation["evidence"]["locator"].lower()
    assert obligation["evidence"]["document_version"] and text in obligation["evidence"]["passage"]
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_T11_T14_schedule_pagination_denied_source_and_duplicate_course(
    bridge, owner, seeded, academic, monkeypatch
):
    rows = bridge.synthetic.data["assignments"]["11"]
    exam = deepcopy(rows[0])
    rows[:] = [{**exam, "id": n, "name": "Other " + str(n)} for n in (2, 3)] + [exam]
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] = "<p>Exam 1: Nov 12, 2026</p>"
    bridge.synthetic.data["course_details"]["12"] = {
        "id": 12,
        "syllabus_body": "<p>Exam 1: Dec 14, 2026</p>",
    }
    result = await academic_request(bridge, owner, seeded, academic.id)
    assert result.data["findings"][0]["kind"] == "missing_canvas_deadline"
    assert all(o["date"] == "2026-11-12" for o in result.data["obligations"])
    assert any(
        r.url.params.get("page") == "2"
        for r in bridge.synthetic.requests
        if r.url.path.endswith("/assignments")
    )
    original = bridge.synthetic.handle

    def denied(request):
        if (
            request.url.path == "/api/v1/courses/11/assignments"
            and request.url.params.get("page") == "2"
        ):
            return httpx.Response(403)
        return original(request)

    monkeypatch.setattr(bridge.synthetic, "handle", denied)
    partial = await academic_request(bridge, owner, seeded, academic.id)
    assert partial.status == "partial_data"
    assert partial.data["findings"][0]["collection_complete"] is False
    bridge.synthetic.failures["/api/v1/courses/11"] = 403
    missing = await academic_request(bridge, owner, seeded, academic.id)
    assert not missing.data["obligations"]
    assert any("could not be retrieved" in text for text in missing.data["limitations"])


def test_T11_date_only_comparison_does_not_invent_clock_agreement():
    result = comparison("Nov 12, 2026", {"kind": "local_date", "local_date": "2026-11-12"}, None)
    assert not result["findings"]
    assert result["comparisons"][0]["time_agreement_established"] is False
    assert result["obligations"][0]["timezone"] is None
    assert result["obligations"][0]["precision"] == "date"
