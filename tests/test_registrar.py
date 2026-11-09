"""Synthetic Bridge-side tests; these do not certify a host's email interpretation."""

import json
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from canvas_bridge.academic.independent_models import IndependentRequest
from canvas_bridge.academic_intelligence import academic_request
from canvas_bridge.calendar_sync import CalendarEvent, marker, propose_sync
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.independent_intelligence import run
from canvas_bridge.privacy.output import filter_output
from canvas_bridge.registrar import RegistrarLookup, final_gaps, lookup_handoff
from tests.test_academic_intelligence import academic as academic  # noqa: F401
from tests.test_academic_intelligence import context, source_doc
from tests.test_domain_planning import task
from tests.test_independent_intelligence import imported, input_data
from tests.test_independent_intelligence import independent_recipient as independent_recipient  # noqa: F401
from tests.test_mcp_contract import running as running  # noqa: F401
from tests.test_recovery_independence import parsed_locally as parsed_locally  # noqa: F401


def scope(course="course"):
    return RegistrarLookup(
        term="Fall 2026",
        term_start="2026-08-20",
        term_end="2026-12-22",
        courses=[{"course_id": course, "course_code": "ETH101", "crn": "12345"}],
    )


def final(title="Final presentation", **updates):
    return task("final").model_copy(update={"title": title, **updates}).model_dump(mode="json")


def test_undated_passage_and_distinct_presentation_survive_without_invented_identifiers():
    gaps = final_gaps([final()], [source_doc("Stem Cell final presentation during finals week.")])
    result = lookup_handoff(gaps, allowed_courses=["course"])
    assert result["status"] == "term_context_needed"
    assert result["term"] is None
    assert result["courses"][0]["crn"] is None
    assert result["courses"][0]["course_code"] is None
    assert len(result["assessments"]) == 2
    assert all(g["activity_type"] == "presentation" for g in gaps)
    assert gaps[1]["work_id"] is None  # Never merge passage and assignment by guess.
    assert result["search_execution"] == "not_performed_by_bridge"


def test_one_term_handoff_and_known_upload_deadline_is_not_exam_slot():
    assert final_gaps([final("Final project upload")]) == []
    assert lookup_handoff([], scope(), allowed_courses=["course"]) is None
    gaps = final_gaps([final(), final("Final exam", id="ethics", course_id="ethics")])
    result = lookup_handoff(gaps, scope(), allowed_courses=["course", "ethics"])
    assert len(result["courses"]) == 2
    assert result["courses"][0]["crn"] == "12345"
    assert result["courses"][1]["crn"] is None
    assert len(result["assessments"]) == 2
    assert (
        lookup_handoff(gaps, scope(), allowed_courses=["course", "ethics"])["lookup_id"]
        == result["lookup_id"]
    )


def test_conflict_priority_and_no_cross_course_identifiers():
    gaps = final_gaps([final()], findings=[{"kind": "conflicting_deadlines", "work_id": "final"}])
    assert gaps[0]["gap_reason"] == "conflicting_sources"
    with pytest.raises(DomainError, match="selected courses"):
        lookup_handoff(gaps, scope("foreign"), allowed_courses=["course"])
    # Even an empty result does not allow foreign metadata to slip through.
    with pytest.raises(DomainError):
        lookup_handoff([], scope("foreign"), allowed_courses=["course"])


def test_schema_forbids_email_import_and_unbounded_term():
    payload = scope().model_dump(mode="json")
    for extra in ("messages", "sender", "access_token", "transfer_permitted", "notices"):
        with pytest.raises(ValidationError):
            RegistrarLookup.model_validate({**payload, extra: "not allowed"})
    with pytest.raises(ValidationError):
        RegistrarLookup.model_validate({**payload, "term_end": "2030-01-01"})


@pytest.mark.parametrize("capability", ["deadlines", "consistency", "calendar"])
async def test_independent_sources_have_same_host_boundary(
    bridge, owner, parsed_locally, independent_recipient, capability
):
    data = input_data()
    data["work"][0]["title"] = "Final presentation"
    dataset = await imported(bridge, owner, json.dumps(data))
    schedule = await imported(bridge, owner, "Final presentation during finals week.")
    now = utcnow()
    calendar = context().model_copy(
        update={
            "retrieved_at": now,
            "window_start": now,
            "window_end": now + timedelta(days=7),
        }
    )
    request = IndependentRequest(
        capability=capability,
        dataset=dataset,
        documents=[schedule],
        calendar=calendar,
        registrar_lookup=scope(dataset["document_id"]),
    )
    result = await run(bridge, owner, request)
    handoff = result.data["registrar_lookup"]
    assert handoff["evidence_transfer"] == "host_only_no_email_import"
    assert handoff["assessments"][0]["activity_type"] == "presentation"
    if capability == "calendar":
        assert result.data["proposals"] == []
        assert handoff["assessments"][0]["calendar_review"]["bridge_marker"]
    else:
        assert len(handoff["assessments"]) == 2
        assert handoff["assessments"][1]["course_id"] == schedule["document_id"]


def test_handoff_privacy_projection_preserves_contract_and_bounds_candidates():
    documents = [
        source_doc("\n".join(f"Final presentation {i} during finals week" for i in range(150)))
    ]
    result = lookup_handoff(final_gaps([], documents), scope(), allowed_courses=["course"])
    assert len(result["assessments"]) == 100
    filtered, _, _, _ = filter_output({"registrar_lookup": result})
    assert filtered["registrar_lookup"] == result


@pytest.mark.parametrize("action", ["deadlines", "audit"])
async def test_integrated_audit_returns_host_request(bridge, owner, seeded, academic, action):
    bridge.synthetic.data["assignments"]["11"][0]["name"] = "Final presentation"
    result = await academic_request(
        bridge, owner, seeded, academic.id, action, registrar_lookup=scope(academic.id)
    )
    handoff = result.data["registrar_lookup"]
    assert handoff["status"] == "host_lookup_needed"
    assert handoff["courses"][0]["crn"] == "12345"
    assert handoff["assessments"][0]["activity_type"] == "presentation"
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_calendar_holds_final_and_preserves_existing_identity(bridge, owner, seeded):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["name"] = "Final presentation"
    now = utcnow()
    raw["due_at"] = (now + timedelta(days=2)).isoformat()
    snap = await bridge.refresh(owner, seeded)
    item = next(i for i in bridge.scoped_snapshot_items(snap) if i.title == "Final presentation")
    tag = marker(owner, seeded, item)
    calendar = context().model_copy(
        update={
            "retrieved_at": now,
            "window_start": now,
            "window_end": now + timedelta(days=7),
            "events": [
                CalendarEvent(
                    id="existing-final",
                    title=item.title,
                    bridge_marker=tag,
                    start=now + timedelta(days=1),
                    status="confirmed",
                    version="v1",
                )
            ],
        }
    )
    for _ in range(2):
        result = await propose_sync(
            bridge, owner, seeded, snap.id, calendar, registrar_lookup=scope(item.course_id)
        )
        assert all(p["work_id"] != item.id for p in result.data["proposals"])
        review = result.data["registrar_lookup"]["assessments"][0]["calendar_review"]
        assert review["bridge_marker"] == tag
        assert review["existing_event_ids"] == ["existing-final"]
        assert result.data["deletions"] == []
        assert result.data["provider_writes_executed"] is False


@pytest.mark.contract
async def test_host_handoff_survives_real_mcp_filter(running, bridge, owner, seeded, token_factory):
    bridge.synthetic.data["assignments"]["11"][0]["name"] = "Final presentation"
    course = bridge.selected(owner, seeded)[1][0]
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "reconcile_course_deadlines",
                    {
                        "connection_id": seeded,
                        "course_id": course.id,
                        "registrar_lookup": scope(course.id).model_dump(mode="json"),
                    },
                )
                assert not result.isError
                handoff = result.structuredContent["data"]["registrar_lookup"]
                assert handoff["courses"][0]["crn"] == "12345"
                assert handoff["assessments"][0]["activity_type"] == "presentation"
                assert len(handoff["result_rules"]) == 5
                assert handoff["evidence_transfer"] == "host_only_no_email_import"
