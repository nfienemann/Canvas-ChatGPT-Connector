"""Synthetic acceptance and security checks for selected course activity planning."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge import activity_planning
from canvas_bridge.activity_planning import (
    ActivityPlanRequest,
    CoursePlanningScope,
    propose_course_plan,
)
from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.domain import DomainError, FactDate
from canvas_bridge.planning_dates import resolve_timing
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Connection, LocalRecord
from tests.conftest import seed
from tests.test_domain_planning import task
from tests.test_mcp_contract import running as running
from tests.test_obligations import activities as activities
from tests.test_obligations import read


@pytest.fixture
def planning_now(activities, monkeypatch):
    monkeypatch.setattr(activity_planning, "utcnow", lambda: activities)
    return activities


def request_for(items, now, *, basis="student_request", effort=True, **overrides):
    return ActivityPlanRequest.model_validate(
        {
            "activities": [
                {
                    "obligation_id": i["id"],
                    "intent": "event_preparation"
                    if i["kind"] == "calendar_events"
                    else "remaining_work",
                    "basis": basis,
                }
                for i in items
            ],
            "windows": [{"start": now + timedelta(hours=1), "end": now + timedelta(hours=5)}],
            "effort_overrides": {
                i["id"]: {
                    "minimum_minutes": 30,
                    "maximum_minutes": 30,
                    "origin": "student_estimate",
                }
                for i in items
            }
            if effort
            else {},
            **overrides,
        }
    )


async def plan(bridge, owner, ref, now, inventory, request, *, scopes=None):
    scopes = scopes or [
        CoursePlanningScope(
            course_id=inventory.data["course_id"],
            inventory_version=inventory.data["inventory_version"],
        )
    ]
    return await propose_course_plan(
        bridge, owner, ref, scopes, now, now + timedelta(days=7), "America/New_York", request
    )


async def test_T08_T09_T10_T46_selected_mixed_activities_share_capacity_and_preserve_unknowns(
    bridge, owner, seeded, planning_now
):
    quiz = deepcopy(bridge.synthetic.data["quizzes"]["11"][0])
    quiz.update(id=11, quiz_type="practice_quiz", title="Practice optional")
    bridge.synthetic.data["quizzes"]["11"].append(quiz)
    bridge.synthetic.data["discussion_topics"]["11"][0]["locked"] = False
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now)
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    again = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert result.data == again.data
    assert len(result.data["selected_activities"]) == 4
    blocks = result.data["blocks"]
    assert len(blocks) == 4 and sum(b["minutes"] for b in blocks) == 120
    assert all(a["end"] <= b["start"] for a, b in zip(blocks, blocks[1:], strict=False))
    assert result.data["feasibility"] == "provisional"
    assert not result.data["provider_writes_executed"]
    assert len(result.evidence) == 4 and len(result.meta.coverage) == 5
    for row in result.data["selected_activities"]:
        assert row["required_status"] == "not_established"
        if row["title"] == "Quiz 3":
            assert row["source_alias_count"] == 3
        else:
            assert row["submission_state"] == "unknown"
    event = next(i for i in inventory.data["items"] if i["kind"] == "calendar_events")
    timing = result.data["timing_constraints"][event["id"]]
    assert timing["source_due"]["kind"] == "not_returned"
    assert timing["preparation_target"]["timestamp"]
    assert timing["planning_finish_by"] == (planning_now + timedelta(days=2)).isoformat()
    assert not timing["overdue_recovery"]
    body = result.model_dump_json()
    assert "DO-NOT-EXPOSE" not in body and "fixture-provider-token" not in body
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(LocalRecord)))


async def test_T07_T08_suggestion_is_review_not_mandatory_work(bridge, owner, seeded, planning_now):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now, basis="suggested_review")
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert result.status == "needs_input"
    assert not result.data["blocks"] and not result.data["selected_activities"]
    assert len(result.data["needs_review"]) == 3
    assert all(r["planning_inputs_not_applied"] for r in result.data["needs_review"])
    assert all(
        r["selection_classification"] == "assistant_inference" for r in result.data["needs_review"]
    )


async def test_T08_T09_quiz_duration_never_becomes_effort(bridge, owner, seeded, planning_now):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now, effort=False)
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert not result.data["blocks"]
    assert {r["reason"] for r in result.data["unmet_work"]} == {"effort_unknown"}
    assert all(r["effort_remaining"] is None for r in result.data["recommendations"])


@pytest.mark.parametrize(
    "field,value", [("due_at", None), ("description", "Changed"), ("published", False)]
)
async def test_T15_T20_stale_inventory_refuses_plan(
    bridge, owner, seeded, planning_now, field, value
):
    inventory = await read(bridge, owner, seeded, planning_now)
    bridge.synthetic.data["quizzes"]["11"][0][field] = value
    with pytest.raises(DomainError) as error:
        await plan(
            bridge,
            owner,
            seeded,
            planning_now,
            inventory,
            request_for(inventory.data["items"], planning_now),
        )
    assert error.value.status == "source_changed"


async def test_T04_T10_conflict_preserves_both_source_dates(bridge, owner, seeded, planning_now):
    bridge.synthetic.data["quizzes"]["11"][0]["due_at"] = (
        planning_now + timedelta(days=4)
    ).isoformat()
    inventory = await read(bridge, owner, seeded, planning_now)
    item = next(i for i in inventory.data["items"] if i["work_id"])
    result = await plan(
        bridge, owner, seeded, planning_now, inventory, request_for([item], planning_now)
    )
    assert not result.data["blocks"]
    review = result.data["needs_review"][0]
    assert review["reason"] == "unresolved_source_relationship_or_deadline"
    assert len({a["due"]["raw"] for a in review["source_relationships"]}) == 2
    assert {a["source_id"] for a in review["source_relationships"]} == {
        s.id for s in result.sources
    }


@pytest.mark.parametrize("state", ["submitted", "excused", "graded"])
async def test_T06_T07_completed_assignments_excluded(bridge, owner, seeded, planning_now, state):
    bridge.synthetic.data["assignments"]["11"][0]["submission"].update(
        workflow_state="submitted" if state == "excused" else state,
        excused=state == "excused",
        score=10 if state == "graded" else None,
        submitted_at=planning_now.isoformat(),
        posted_at=planning_now.isoformat() if state == "graded" else None,
    )
    inventory = await read(bridge, owner, seeded, planning_now)
    item = next(i for i in inventory.data["items"] if i["work_id"])
    result = await plan(
        bridge, owner, seeded, planning_now, inventory, request_for([item], planning_now)
    )
    assert not result.data["blocks"]
    assert len(result.data["excluded_activities"]) == 1


async def test_T07_T13_personal_progress_is_scoped_and_not_written(
    bridge, owner, seeded, planning_now
):
    inventory = await read(bridge, owner, seeded, planning_now)
    item = next(i for i in inventory.data["items"] if i["work_id"])
    with bridge.store.transaction() as session:
        session.add(
            LocalRecord(
                owner=owner,
                connection_id=seeded,
                kind="progress",
                key=item["id"],
                version=2,
                payload={
                    "status": "in_progress",
                    "remaining_effort": {
                        "minimum_minutes": 45,
                        "maximum_minutes": 45,
                        "origin": "student_estimate",
                    },
                },
            )
        )
    result = await plan(
        bridge,
        owner,
        seeded,
        planning_now,
        inventory,
        request_for([item], planning_now, effort=False),
    )
    assert sum(b["minutes"] for b in result.data["blocks"]) == 45
    assert result.data["selected_activities"][0]["personal_progress"]["version"] == 2
    with bridge.store.transaction() as session:
        assert list(session.scalars(select(LocalRecord)))[0].version == 2


async def test_T13_T21_foreign_scope_and_alias_ids_rejected(bridge, owner, seeded, planning_now):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now)
    with pytest.raises(DomainError):
        await plan(bridge, "another-owner", seeded, planning_now, inventory, request)
    other_ref = await seed(bridge, "another-owner", "other-connection")
    other = await read(bridge, "another-owner", other_ref, planning_now)
    assert {i["id"] for i in inventory.data["items"]}.isdisjoint(
        i["id"] for i in other.data["items"]
    )
    request.activities[0].obligation_id = other.data["items"][0]["id"]
    with pytest.raises(DomainError) as error:
        await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert error.value.status == "permission_denied"
    request.activities[0].obligation_id = inventory.data["items"][0]["source_aliases"][0][
        "source_id"
    ]
    with pytest.raises(DomainError):
        await plan(bridge, owner, seeded, planning_now, inventory, request)


async def test_T20_T21_override_and_duplicate_scope_validation(bridge, owner, seeded, planning_now):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now)
    request.date_only_timezones["not-selected"] = "UTC"
    with pytest.raises(DomainError, match="outside the chosen set"):
        await plan(bridge, owner, seeded, planning_now, inventory, request)
    scope = CoursePlanningScope(
        course_id=inventory.data["course_id"], inventory_version=inventory.data["inventory_version"]
    )
    with pytest.raises(DomainError, match="distinct"):
        await plan(bridge, owner, seeded, planning_now, inventory, request, scopes=[scope, scope])
    data = request.model_dump()
    data["activities"].append(data["activities"][0])
    with pytest.raises(ValidationError, match="only once"):
        ActivityPlanRequest.model_validate(data)


async def test_T15_partial_coverage_keeps_known_selection_provisional(
    bridge, owner, seeded, planning_now, monkeypatch
):
    original = CanvasClient.collection

    async def incomplete(client, endpoint, **kwargs):
        if endpoint == Endpoint.QUIZZES:
            return Collection([], False, 1, "request_budget")
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", incomplete)
    bridge.synthetic.failures["/api/v1/calendar_events"] = 403
    inventory = await read(bridge, owner, seeded, planning_now)
    result = await plan(
        bridge,
        owner,
        seeded,
        planning_now,
        inventory,
        request_for(inventory.data["items"], planning_now),
    )
    assert result.status == "partial_data" and result.data["feasibility"] == "provisional"
    assert result.data["blocks"]
    assert {c.state for c in result.meta.coverage} == {"complete", "partial", "permission_denied"}
    assert all(e["coverage"] for e in result.evidence)


@pytest.mark.parametrize("failure", ["permission_denied", "reconnect_required"])
async def test_T14_T21_failed_authorization_discards_plan(
    bridge, owner, seeded, planning_now, monkeypatch, failure
):
    inventory = await read(bridge, owner, seeded, planning_now)
    original = CanvasClient.collection

    async def denied(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS:
            return Collection(failure=failure)
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", denied)
    with pytest.raises(DomainError) as error:
        await plan(
            bridge,
            owner,
            seeded,
            planning_now,
            inventory,
            request_for(inventory.data["items"], planning_now),
        )
    assert error.value.status == failure


async def test_T43_selection_race_discards_plan(bridge, owner, seeded, planning_now, monkeypatch):
    inventory = await read(bridge, owner, seeded, planning_now)
    original = activity_planning.propose

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).epoch += 1
        return result

    monkeypatch.setattr(activity_planning, "propose", changed)
    with pytest.raises(DomainError, match="selection changed"):
        await plan(
            bridge,
            owner,
            seeded,
            planning_now,
            inventory,
            request_for(inventory.data["items"], planning_now),
        )


async def test_T15_T35_timeout_cancels_refresh_and_large_response_refuses(
    bridge, owner, seeded, planning_now, monkeypatch
):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now)
    cancelled = asyncio.Event()
    original = activity_planning.collect_inventory

    async def slow(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(activity_planning, "collect_inventory", slow)
    bridge.settings.refresh_budget_seconds = 0.01
    with pytest.raises(DomainError) as error:
        await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert error.value.status == "retry_later" and cancelled.is_set()
    monkeypatch.setattr(activity_planning, "collect_inventory", original)
    bridge.settings.refresh_budget_seconds = 30
    monkeypatch.setattr(
        activity_planning,
        "propose",
        lambda *a, **k: {"feasibility": "provisional", "large": "x" * 200000},
    )
    with pytest.raises(DomainError, match="response budget"):
        await plan(bridge, owner, seeded, planning_now, inventory, request)


async def test_T04_T46_all_day_event_requires_explicit_timezone_and_keeps_date(
    bridge, owner, seeded, planning_now
):
    day = (planning_now + timedelta(days=2)).date().isoformat()
    bridge.synthetic.data["calendar_event"]["11"][0].update(all_day=True, all_day_date=day)
    inventory = await read(bridge, owner, seeded, planning_now)
    event = next(i for i in inventory.data["items"] if i["kind"] == "calendar_events")
    request = request_for([event], planning_now)
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert not result.data["blocks"]
    assert result.data["unmet_work"][0]["reason"] == "date_only_timezone_required"
    request.date_only_timezones[event["id"]] = "America/New_York"
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert result.data["blocks"]
    timing = result.data["timing_constraints"][event["id"]]
    assert timing["preparation_target"]["local_date"] == day
    assert timing["preparation_target"]["timestamp"] is None
    assert timing["source_due"]["kind"] == "not_returned"


def test_T04_event_preparation_past_dst_and_missing_target_are_not_due_dates():
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
    item = task("event", 30, None)
    item.effective_due = FactDate()
    target = FactDate(
        kind="timestamp", timestamp=datetime.fromisoformat("2026-11-01T01:30:00-05:00")
    )
    timing = resolve_timing(item, now, preparation_target=target)
    assert timing.deadline == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert timing.evidence(item)["source_due"]["timestamp"] is None
    assert (
        resolve_timing(item, timing.deadline, preparation_target=target).blocked
        == "event_preparation_bound_passed"
    )
    assert (
        resolve_timing(item, now, preparation_target=FactDate()).blocked
        == "event_start_unavailable"
    )


async def test_T01_T13_same_title_across_courses_and_later_inventory_page(
    bridge, owner, seeded, planning_now
):
    bridge.synthetic.data["assignments"]["12"] = deepcopy(
        bridge.synthetic.data["assignments"]["11"]
    )
    courses = bridge.selected(owner, seeded)[1]
    from canvas_bridge.obligations import course_obligations

    first = await read(bridge, owner, seeded, planning_now, limit=1)
    later = await read(
        bridge,
        owner,
        seeded,
        planning_now,
        offset=1,
        expected_version=first.data["inventory_version"],
    )
    second = await course_obligations(
        bridge,
        owner,
        seeded,
        courses[1].id,
        planning_now,
        planning_now + timedelta(days=7),
        "America/New_York",
    )
    items = first.data["items"] + later.data["items"] + second.data["items"]
    scopes = [
        CoursePlanningScope(
            course_id=i.data["course_id"], inventory_version=i.data["inventory_version"]
        )
        for i in (first, second)
    ]
    result = await plan(
        bridge, owner, seeded, planning_now, first, request_for(items, planning_now), scopes=scopes
    )
    assert len(result.data["selected_activities"]) == 4
    assert len({b["work_id"] for b in result.data["blocks"]}) == 4
    quizzes = [r for r in result.data["selected_activities"] if r["title"] == "Quiz 3"]
    assert len(quizzes) == 2 and quizzes[0]["work_id"] != quizzes[1]["work_id"]
    assert len(result.meta.coverage) == 10


@pytest.mark.parametrize("intent", ["remaining_work", "event_preparation"])
async def test_T46_wrong_activity_intent_needs_review(bridge, owner, seeded, planning_now, intent):
    inventory = await read(bridge, owner, seeded, planning_now)
    item = next(
        i
        for i in inventory.data["items"]
        if (i["kind"] == "calendar_events") == (intent == "remaining_work")
    )
    request = request_for([item], planning_now)
    request.activities[0].intent = intent
    result = await plan(bridge, owner, seeded, planning_now, inventory, request)
    assert not result.data["blocks"] and result.data["needs_review"]


@pytest.mark.parametrize("closed", [True, False])
async def test_T07_T46_discussion_participation_is_not_completion(
    bridge, owner, seeded, planning_now, closed
):
    bridge.synthetic.data["discussion_topics"]["11"][0]["locked"] = closed
    inventory = await read(bridge, owner, seeded, planning_now)
    topic = next(i for i in inventory.data["items"] if i["kind"] == "discussion_topics")
    result = await plan(
        bridge, owner, seeded, planning_now, inventory, request_for([topic], planning_now)
    )
    assert bool(result.data["blocks"]) is not closed
    rows = result.data["excluded_activities"] if closed else result.data["selected_activities"]
    assert rows[0]["submission_state"] == "unknown"
    bridge.synthetic.data["discussion_topics"]["11"][0]["locked"] = not closed
    with pytest.raises(DomainError) as error:
        await plan(
            bridge, owner, seeded, planning_now, inventory, request_for([topic], planning_now)
        )
    assert error.value.status == "source_changed"


@pytest.mark.contract
async def test_T20_T30_T36_readonly_mcp_activity_plan(
    running, bridge, owner, seeded, token_factory, planning_now
):
    inventory = await read(bridge, owner, seeded, planning_now)
    request = request_for(inventory.data["items"], planning_now)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tool = next(
                    t
                    for t in (await session.list_tools()).tools
                    if t.name == "propose_course_study_plan"
                )
                assert tool.annotations.readOnlyHint
                result = await session.call_tool(
                    tool.name,
                    {
                        "connection_id": seeded,
                        "courses": [
                            {
                                "course_id": inventory.data["course_id"],
                                "inventory_version": inventory.data["inventory_version"],
                            }
                        ],
                        "start": planning_now.isoformat(),
                        "end": (planning_now + timedelta(days=7)).isoformat(),
                        "timezone": "America/New_York",
                        "request": request.model_dump(mode="json"),
                    },
                )
                assert not result.isError
                assert len(result.structuredContent["data"]["blocks"]) == 3
                assert result.structuredContent["evidence"]
