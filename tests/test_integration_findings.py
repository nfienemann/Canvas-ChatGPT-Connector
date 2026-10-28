"""Synthetic regressions for the owner's live integration findings; no course records."""

from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.course_files import list_files, read_file, search_files
from canvas_bridge.domain import DomainError, Effort, WorkItem, utcnow
from canvas_bridge.planning import PlanRequest, Window, propose
from canvas_bridge.retrieval import fetch_material, outline, search_materials
from canvas_bridge.storage import Snapshot, aware
from tests.test_course_files import file_record
from tests.test_file_reading import readable as readable
from tests.test_mcp_contract import running as running


async def workload(bridge, owner, ref):
    return await bridge.workload(owner, ref, utcnow(), utcnow() + timedelta(days=7), "UTC")


@pytest.mark.parametrize(
    "submission,expected,evidence",
    [
        ({"user_id": 101, "workflow_state": "unsubmitted"}, "not_submitted", "returned"),
        (None, "unknown", "not_returned"),
        ({}, "unknown", "not_returned"),
        ([], "unknown", "invalid"),
        ({"user_id": 999, "workflow_state": "unsubmitted"}, "unknown", "identity_mismatch"),
        ({"workflow_state": "unsubmitted"}, "unknown", "identity_mismatch"),
        (
            {"user_id": 101, "workflow_state": "graded", "posted_at": "2026-10-19T10:00:00Z"},
            "unknown",
            "returned",
        ),
        (
            {
                "user_id": 101,
                "workflow_state": "submitted",
                "submitted_at": "2026-10-19T10:00:00Z",
                "attempt": 2,
            },
            "resubmitted",
            "returned",
        ),
        (
            {"user_id": 101, "workflow_state": "submitted", "submitted_at": "invalid"},
            "unknown",
            "returned",
        ),
        (
            {
                "user_id": 101,
                "workflow_state": "unsubmitted",
                "submitted_at": "2026-10-19T10:00:00Z",
            },
            "unknown",
            "conflicting",
        ),
    ],
)
async def test_T06_same_submission_contract_for_list_and_details(
    bridge, owner, seeded, submission, expected, evidence
):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw.update(submission=submission, submission_types=["online_text_entry"])
    result = await workload(bridge, owner, seeded)
    item = next(i for i in result.data["items"] if i["source_id"] == str(raw["id"]))
    details = await bridge.assignment_details(owner, seeded, item["id"])
    for field in (
        "submission_state",
        "submission_evidence",
        "submission_state_basis",
        "assessment_state",
        "timeliness_state",
    ):
        assert item[field] == details.data["item"][field]
    assert item["submission_state"] == expected
    assert item["submission_evidence"] == evidence
    requests = [r for r in bridge.synthetic.requests if "/assignments" in r.url.path]
    assert requests and all("submission" in r.url.params.get_list("include[]") for r in requests)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_T06_omitted_submission_is_not_filled_from_stale_workload(
    bridge, owner, seeded, monkeypatch
):
    result = await workload(bridge, owner, seeded)
    item = next(i for i in result.data["items"] if i["submission_state"] == "not_submitted")
    original = bridge.synthetic.handle

    def omit(request):
        response = original(request)
        if request.url.path.endswith("/assignments/" + item["source_id"]):
            raw = response.json()
            raw.pop("submission", None)
            return httpx.Response(200, json=raw)
        return response

    monkeypatch.setattr(bridge.synthetic, "handle", omit)
    details = await bridge.assignment_details(owner, seeded, item["id"])
    assert details.status == "partial_data"
    assert details.data["item"]["submission_state"] == "unknown"
    assert details.data["item"]["submission_evidence"] == "not_returned"


@pytest.mark.parametrize(
    "description,state",
    [
        ("<p>Compare the controls.</p>", "present"),
        ("", "empty_in_canvas"),
        (None, "empty_in_canvas"),
        ("  \n", "empty_in_canvas"),
        ("<img src='private.png'>", "no_extractable_text"),
        ({"unexpected": "value"}, "invalid"),
        ("x" * 50_001, "truncated"),
    ],
    ids=["present", "empty", "null", "whitespace", "image-only", "invalid", "truncated"],
)
async def test_T05_requirements_empty_is_not_failed_or_omitted(
    bridge, owner, seeded, description, state
):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["description"] = description
    snapshot = await bridge.refresh(owner, seeded)
    ref = next(i["id"] for i in snapshot.items if i["source_id"] == str(raw["id"]))
    result = await bridge.assignment_details(owner, seeded, ref)
    coverage = result.data["requirements_coverage"]
    assert coverage["state"] == state and coverage["retrieval"] == "succeeded"
    assert coverage["scope"] == "canvas_assignment_description_only"
    assert result.data["requirements_truncated"] == (state == "truncated")
    raw.pop("description")
    missing = await bridge.assignment_details(owner, seeded, ref)
    assert missing.status == "partial_data"
    assert missing.data["requirements_coverage"]["state"] == "not_returned"
    assert not missing.data["requirements_coverage"]["field_returned"]


@pytest.mark.parametrize("http_status", [403, 500])
async def test_T05_failed_requirements_fetch_is_never_empty_success(
    bridge, owner, seeded, http_status
):
    snapshot = await bridge.refresh(owner, seeded)
    item = snapshot.items[0]
    _, courses = bridge.selected(owner, seeded)
    course = next(c for c in courses if c.id == item["course_id"])
    bridge.synthetic.failures[
        f"/api/v1/courses/{course.source_id}/assignments/{item['source_id']}"
    ] = http_status
    with pytest.raises(DomainError) as error:
        await bridge.assignment_details(owner, seeded, item["id"])
    assert error.value.status == ("permission_denied" if http_status == 403 else "retry_later")


async def test_T03_T06_eleven_undated_assessments_are_not_upcoming(bridge, owner, seeded):
    bridge.synthetic.data["assignments"] = {
        "11": [
            {
                "id": 1000 + i,
                "name": f"Historical assessment {i}",
                "due_at": None,
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": "2020-01-02T00:00:00Z",
                "submission_types": ["online_text_entry"],
                "locked_for_user": False,
                "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
            }
            for i in range(11)
        ]
    }
    result = await workload(bridge, owner, seeded)
    assert result.data["undated_count"] == 11
    for item in result.data["items"]:
        assert item["section"] == "undated"
        assert item["due_date_status"] == "no_canvas_due_date"
        assert item["schedule_status"] == "unknown"
        assert item["submission_state"] == "not_submitted"
        assert "offline completion is unknown" in item["submission_state_basis"]
    assert "historical" in result.meta.warnings[0]
    bridge.synthetic.data["assignments"]["11"][0].pop("due_at")
    missing = await workload(bridge, owner, seeded)
    omitted = next(i for i in missing.data["items"] if i["source_id"] == "1000")
    assert omitted["effective_due"]["kind"] == "not_returned"
    assert omitted["due_date_status"] == "unavailable"
    assert omitted["schedule_status"] == "unknown"
    # Old snapshots also get explicit date coverage when validated.
    old = {
        k: v
        for k, v in omitted.items()
        if k
        not in {
            "due_date_status",
            "schedule_status",
            "schedule_basis",
            "section",
            "display_due",
            "due_date_relationship",
            "work_status",
            "outstanding_action",
            "outstanding_action_basis",
            "window_relationship",
        }
    }
    assert WorkItem.model_validate(old).schedule_status == "unknown"


async def test_T03_T20_undated_records_need_relevance_before_automatic_allocation(
    bridge, owner, seeded
):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["due_at"] = raw["lock_at"] = None
    snapshot = await bridge.refresh(owner, seeded)
    item = WorkItem.model_validate(
        next(i for i in snapshot.items if i["source_id"] == str(raw["id"]))
    )
    item.effort_remaining = Effort(
        minimum_minutes=20, maximum_minutes=20, origin="student_estimate"
    )
    now = utcnow()
    request = PlanRequest(windows=[Window(start=now, end=now + timedelta(hours=2))])
    result = propose([item], request, now)
    assert not result["blocks"]
    assert result["unmet_work"][0]["reason"] == "schedule_and_relevance_unknown"
    assert "Confirm when" in result["recommendations"][0]["first_action"]
    request.effort_overrides = {item.id: item.effort_remaining}
    explicit = propose([item], request, now)
    assert explicit["blocks"] and explicit["feasibility"] == "provisional"


async def test_T27_history_reports_baseline_scope_and_incomplete_observations(
    bridge, owner, seeded
):
    since = utcnow() - timedelta(days=1)
    none = bridge.changes(owner, seeded, since)
    assert none.data["reason"] == "no_complete_observation"
    first = await bridge.refresh(owner, seeded)
    early = bridge.changes(owner, seeded, since)
    assert early.data["reason"] == "requested_period_predates_baseline"
    start = aware(first.created_at)
    assert bridge.changes(owner, seeded, start).data["reason"] == "no_later_complete_observation"
    bridge.synthetic.data["assignments"]["11"][0]["name"] = "New observed title"
    second = await bridge.refresh(owner, seeded)
    with bridge.store.transaction() as session:
        session.get(Snapshot, second.id).complete = False
    incomplete = bridge.changes(owner, seeded, start)
    assert incomplete.data["history"] == "not_available" and not incomplete.data["changes"]
    assert not incomplete.data["history_coverage"]["latest_observation_complete"]
    third = await bridge.refresh(owner, seeded)
    observed = bridge.changes(owner, seeded, start)
    assert observed.data["current"] == third.id
    assert observed.data["history_coverage"]["incomplete_observations_since"] == 1
    assert not observed.data["history_coverage"]["exact_change_times_known"]
    later = await bridge.refresh(owner, seeded)
    with bridge.store.transaction() as session:
        session.get(Snapshot, later.id).complete = False
    assert bridge.changes(owner, seeded, start).status == "partial_data"


async def test_T11_T13_unread_pdf_search_and_module_reference_boundaries(
    bridge, owner, seeded, readable
):
    course, ref = readable
    listing = await outline(bridge, owner, seeded, course.id)
    assert not listing.data["document_content_included"]
    assert listing.data["file_reading"]["enabled"]
    module = listing.data["modules"][0]
    assert next(i for i in module["items"] if i["type"] == "File")["material_ref"] == ref
    for reader in (fetch_material, read_file):
        with pytest.raises(DomainError, match="module"):
            await reader(bridge, owner, seeded, module["id"])
    before = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert not before.data["results"] and not before.data["unread_documents_searched"]
    assert before.data["unindexed_documents"]
    assert not any("download" in r.url.path for r in bridge.synthetic.requests)
    await read_file(bridge, owner, seeded, ref)
    after = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert after.data["results"][0]["page"] == 1
    old_search = await search_materials(bridge, owner, seeded, "differentiation")
    assert not old_search.data["file_text_searched"] and not old_search.data["results"]
    assert "search_course_files" in old_search.data["next_step"]
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
    assert any(r.url.path.endswith("/courses/11/files/51") for r in bridge.synthetic.requests)


async def test_T11_narrow_module_resolves_pdf_outside_first_100_inventory_files(
    bridge, owner, seeded, readable
):
    course, ref = readable
    module_id = (await outline(bridge, owner, seeded, course.id)).data["modules"][0]["id"]
    target = bridge.synthetic.data["files"]["11"][0]
    bridge.synthetic.data["files"]["11"] = [file_record(id=1000 + i) for i in range(100)] + [target]
    result = await list_files(bridge, owner, seeded, course.id, module_id)
    assert [f["file_id"] for f in result.data["files"]] == [ref]
    assert result.data["inventory_failures"]["files"] == "module_filtered_inventory"


@pytest.mark.contract
async def test_T06_T05_mcp_assignment_contract_preserves_states(
    running, token_factory, seeded, bridge
):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw.update(description="", due_at=None)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_workload",
                    {
                        "connection_id": seeded,
                        "start": utcnow().isoformat(),
                        "end": (utcnow() + timedelta(days=7)).isoformat(),
                        "timezone": "UTC",
                    },
                )
                item = next(
                    i
                    for i in result.structuredContent["data"]["items"]
                    if i["source_id"] == str(raw["id"])
                )
                details = await session.call_tool(
                    "get_assignment_details", {"connection_id": seeded, "work_id": item["id"]}
                )
                data = details.structuredContent["data"]
                assert (
                    item["submission_state"] == data["item"]["submission_state"] == "not_submitted"
                )
                assert data["requirements_coverage"]["state"] == "empty_in_canvas"
                assert data["item"]["schedule_status"] == "unknown"
