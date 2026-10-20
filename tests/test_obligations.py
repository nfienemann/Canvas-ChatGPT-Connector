"""Synthetic regression coverage for canonical, read-only activity discovery."""

from copy import deepcopy
from datetime import datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.obligations import course_obligations
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Connection
from tests.conftest import seed
from tests.test_mcp_contract import running as running


@pytest.fixture
def activities(bridge):
    now = utcnow().replace(microsecond=0)
    base = {"published": True, "locked_for_user": False, "updated_at": now.isoformat()}
    due = (now + timedelta(days=2)).isoformat()
    assignment = {
        **base,
        "id": 1,
        "name": "Quiz 3",
        "quiz_id": 10,
        "due_at": due,
        "description": "",
        "submission_types": ["online_quiz"],
        "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
    }
    quiz = {
        **base,
        "id": 10,
        "title": "Quiz 3",
        "quiz_type": "assignment",
        "due_at": due,
        "description": "<p>Read the methods section before this quiz.</p>",
        "time_limit": 20,
        "access_code": "DO-NOT-EXPOSE",
        "all_dates": [{"student_ids": [999]}],
        "preview_url": "https://secret.invalid",
        "questions": ["DO-NOT-EXPOSE"],
    }
    discussion = {
        **base,
        "id": 20,
        "title": "Ungraded discussion",
        "posted_at": now.isoformat(),
        "message": "<p>Discuss the controls; initial post and replies have separate instructions.</p>",
        "entries": [{"message": "DO-NOT-EXPOSE"}],
        "participants": [{"id": 999}],
        "podcast_url": "https://secret.invalid",
        "lock_at": due,
    }
    event = {
        "id": 30,
        "title": "Laboratory meeting",
        "context_code": "course_11",
        "start_at": due,
        "end_at": (now + timedelta(days=2, hours=1)).isoformat(),
        "workflow_state": "active",
        "hidden": False,
        "description": "Bring a notebook.",
        "child_events": [{"user": {"name": "DO-NOT-EXPOSE"}}],
    }
    calendar_assignment = {
        "id": "assignment_1",
        "title": "Different label",
        "context_code": "course_11",
        "start_at": due,
        "workflow_state": "published",
        "description": "",
        "assignment": {"submission": {"score": 99, "user_id": 999}},
        "assignment_overrides": [{"student_ids": [999]}],
    }
    bridge.synthetic.data.update(
        assignments={"11": [assignment], "12": []},
        quizzes={"11": [quiz]},
        discussion_topics={"11": [discussion]},
        calendar_event={"11": [event]},
        calendar_assignment={"11": [calendar_assignment]},
    )
    return now


async def read(bridge, owner, ref, now, **kwargs):
    course = bridge.selected(owner, ref)[1][0]
    return await course_obligations(
        bridge, owner, ref, course.id, now, now + timedelta(days=7), "America/New_York", **kwargs
    )


async def test_T10_T46_linked_quiz_calendar_one_obligation_and_safe_instructions(
    bridge, owner, seeded, activities
):
    result = await read(bridge, owner, seeded, activities)
    assert len(result.data["items"]) == 3
    quiz = next(i for i in result.data["items"] if i["title"] == "Quiz 3")
    assert len(quiz["source_aliases"]) == 3
    assert quiz["submission_state"] == "not_submitted"
    assert quiz["conflicts"] == []
    aliases = {a["source_type"]: a for a in quiz["source_aliases"]}
    assert aliases["assignments"]["requirements_coverage"]["state"] == "empty_in_canvas"
    assert "methods section" in aliases["classic_quizzes"]["requirements_text"]
    assert aliases["classic_quizzes"]["time_limit_minutes"] == 20
    body = result.model_dump_json()
    for prohibited in (
        "DO-NOT-EXPOSE",
        "secret.invalid",
        "student_ids",
        "fixture-provider-token",
        '"score":',
    ):
        assert prohibited not in body
    assert all(s.content_hash and s.course_id for s in result.sources)
    assert result.evidence
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
    assert not any(
        "/questions" in r.url.path or "/entries" in r.url.path or "/take" in r.url.path
        for r in bridge.synthetic.requests
    )


async def test_T04_T10_conflicting_dates_do_not_override_effective_assignment(
    bridge, owner, seeded, activities
):
    bridge.synthetic.data["quizzes"]["11"][0]["due_at"] = (
        activities + timedelta(days=5)
    ).isoformat()
    result = await read(bridge, owner, seeded, activities)
    item = next(i for i in result.data["items"] if i["title"] == "Quiz 3")
    assert item["effective_due"]["raw"] == (activities + timedelta(days=2)).isoformat()
    assert item["conflicts"][0]["kind"] == "source_deadline_difference"
    bridge.synthetic.data["assignments"]["11"][0]["due_at"] = None
    item = next(
        i
        for i in (await read(bridge, owner, seeded, activities)).data["items"]
        if i["title"] == "Quiz 3"
    )
    assert item["schedule_relation"] == "unknown"
    assert item["effective_due"]["kind"] == "known_none"


async def test_T07_T46_same_titles_without_links_stay_distinct_unknown(
    bridge, owner, seeded, activities
):
    quiz = deepcopy(bridge.synthetic.data["quizzes"]["11"][0])
    quiz.update(id=11, quiz_type="practice_quiz", due_at=None)
    bridge.synthetic.data["quizzes"]["11"].append(quiz)
    result = await read(bridge, owner, seeded, activities)
    items = [i for i in result.data["items"] if i["title"] == "Quiz 3"]
    assert len(items) == 2
    standalone = next(i for i in items if not i["work_id"])
    assert standalone["required_status"] == "not_established"
    assert standalone["submission_state"] == "unknown"
    assert standalone["schedule_relation"] == "unknown"


async def test_T10_conflicting_explicit_links_never_guess(bridge, owner, seeded, activities):
    bridge.synthetic.data["quizzes"]["11"][0]["assignment_id"] = 2
    result = await read(bridge, owner, seeded, activities)
    item = next(i for i in result.data["items"] if i["kind"] == "classic_quizzes")
    assert item["work_id"] is None
    assert item["source_aliases"][0]["link_status"] == "conflicting_links"


@pytest.mark.parametrize(
    "change",
    [
        {"published": False},
        {"locked_for_user": True},
        {"course_id": 12},
        {"published": None},
    ],
)
async def test_T21_T24_restricted_quiz_content_omitted(bridge, owner, seeded, activities, change):
    bridge.synthetic.data["quizzes"]["11"][0].update(change)
    result = await read(bridge, owner, seeded, activities)
    assert "methods section" not in result.model_dump_json()
    assert (
        next(c for c in result.meta.coverage if c.resource == "classic_quizzes").state == "partial"
    )


async def test_T21_hidden_assignment_blocks_linked_aliases(bridge, owner, seeded, activities):
    bridge.synthetic.data["assignments"]["11"][0]["published"] = False
    result = await read(bridge, owner, seeded, activities)
    assert "Quiz 3" not in result.model_dump_json()


@pytest.mark.parametrize(
    "change",
    [
        {"context_code": "course_12"},
        {"context_code": "user_101"},
        {"context_code": "group_1", "effective_context_code": "course_11"},
        {"appointment_group_id": 7},
        {"user": {"id": 999}},
        {"hidden": True},
    ],
)
async def test_T13_T21_calendar_other_scope_and_reservations_omitted(
    bridge, owner, seeded, activities, change
):
    bridge.synthetic.data["calendar_event"]["11"][0].update(change)
    result = await read(bridge, owner, seeded, activities)
    assert "Laboratory meeting" not in result.model_dump_json()


async def test_T04_T46_all_day_precision_and_section_scope(bridge, owner, seeded, activities):
    event = bridge.synthetic.data["calendar_event"]["11"][0]
    event.update(
        all_day=True,
        all_day_date=(activities + timedelta(days=2)).date().isoformat(),
        context_code="course_section_22",
        effective_context_code="course_11",
    )
    result = await read(bridge, owner, seeded, activities)
    item = next(i for i in result.data["items"] if i["title"] == "Laboratory meeting")
    assert item["effective_due"]["kind"] == "not_returned"
    assert item["source_aliases"][0]["event_start"]["kind"] == "local_date"
    assert item["submission_state"] == "unknown"
    assert item["schedule_relation"] == "unknown"


async def test_T01_T10_query_scope_is_fixed_and_never_expands_includes(
    bridge, owner, seeded, activities
):
    await read(bridge, owner, seeded, activities)
    calendars = [r for r in bridge.synthetic.requests if r.url.path == Endpoint.CALENDAR_EVENTS]
    assert len(calendars) == 2
    for request in calendars:
        query = parse_qs(request.url.query.decode())
        assert query["context_codes[]"] == ["course_11"]
        assert set(query["excludes[]"]) == {"child_events", "assignment"}
        assert "all_events" not in query and "includes[]" not in query
    for request in bridge.synthetic.requests:
        if request.url.path.endswith(("/quizzes", "/discussion_topics")):
            assert dict(request.url.params) == {"per_page": "100"}


async def test_T13_user_and_course_isolation_and_stale_lease_refresh(
    bridge, owner, seeded, activities
):
    with pytest.raises(DomainError):
        await read(bridge, "someone-else", seeded, activities)
    second = await seed(bridge, "someone-else", "other-connection")
    one = await read(bridge, owner, seeded, activities)
    two = await read(bridge, "someone-else", second, activities)
    assert {i["id"] for i in one.data["items"]}.isdisjoint(i["id"] for i in two.data["items"])
    with pytest.raises(DomainError):
        await read(bridge, owner, seeded, activities, obligation_id=two.data["items"][0]["id"])
    course_id = bridge.selected(owner, seeded)[1][0].id
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).entitlement_at = activities - timedelta(hours=1)
    refreshed = await course_obligations(
        bridge, owner, seeded, course_id, activities, activities + timedelta(days=7), "UTC"
    )
    assert refreshed.data["items"]


async def test_T01_T15_pagination_version_and_changed_source(bridge, owner, seeded, activities):
    first = await read(bridge, owner, seeded, activities, limit=1)
    second = await read(
        bridge,
        owner,
        seeded,
        activities,
        offset=1,
        limit=1,
        expected_version=first.data["inventory_version"],
    )
    assert second.data["items"][0]["id"] != first.data["items"][0]["id"]
    repeated = await read(bridge, owner, seeded, activities, limit=1)
    assert first.data["inventory_version"] == repeated.data["inventory_version"]
    bridge.synthetic.data["quizzes"]["11"][0]["description"] += " Different instructions."
    with pytest.raises(DomainError, match="Inventory changed"):
        await read(
            bridge,
            owner,
            seeded,
            activities,
            offset=1,
            expected_version=first.data["inventory_version"],
        )
    with pytest.raises(DomainError, match="requires"):
        await read(bridge, owner, seeded, activities, offset=1)


async def test_T15_partial_denied_and_timeout_are_not_empty_success(
    bridge, owner, seeded, activities, monkeypatch
):
    original = CanvasClient.collection

    async def incomplete(client, endpoint, **kwargs):
        if endpoint == Endpoint.QUIZZES:
            return Collection([], False, 1, "request_budget")
        if endpoint == Endpoint.DISCUSSIONS:
            raise TimeoutError
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", incomplete)
    bridge.synthetic.failures["/api/v1/calendar_events"] = 403
    result = await read(bridge, owner, seeded, activities)
    states = {c.resource: c.state for c in result.meta.coverage}
    assert states == {
        "assignments": "complete",
        "classic_quizzes": "partial",
        "discussion_topics": "partial",
        "calendar_events": "permission_denied",
        "calendar_assignments": "permission_denied",
    }
    assert result.status == "partial_data"
    bridge.synthetic.failures["/api/v1/courses/11/assignments"] = 403
    with pytest.raises(DomainError):
        await read(bridge, owner, seeded, activities)


async def test_T14_T43_expired_authorization_discards_all_inventory(
    bridge, owner, seeded, activities, monkeypatch
):
    original = CanvasClient.collection

    async def expired(client, endpoint, **kwargs):
        if endpoint == Endpoint.QUIZZES:
            return Collection(failure="reconnect_required")
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", expired)
    with pytest.raises(DomainError, match="reconnected"):
        await read(bridge, owner, seeded, activities)


async def test_T43_selection_changed_mid_read_is_fenced(
    bridge, owner, seeded, activities, monkeypatch
):
    original = CanvasClient.collection

    async def changed(client, endpoint, **kwargs):
        result = await original(client, endpoint, **kwargs)
        if endpoint == Endpoint.DISCUSSIONS:
            with bridge.store.transaction() as session:
                session.get(Connection, seeded).epoch += 1
        return result

    monkeypatch.setattr(CanvasClient, "collection", changed)
    with pytest.raises(DomainError, match="selection changed"):
        await read(bridge, owner, seeded, activities)


async def test_T01_T23_calendar_pagination_cannot_widen_context(
    bridge, owner, seeded, activities, monkeypatch
):
    original = bridge.synthetic.handle

    def handler(request):
        if request.url.path == Endpoint.CALENDAR_EVENTS:
            target = str(request.url).replace("course_11", "course_12")
            return httpx.Response(
                200,
                json=[bridge.synthetic.data["calendar_event"]["11"][0]],
                headers={"Link": f'<{target}>; rel="next"'},
            )
        return original(request)

    monkeypatch.setattr(bridge.synthetic, "handle", handler)
    result = await read(bridge, owner, seeded, activities)
    assert "Laboratory meeting" not in result.model_dump_json()
    assert (
        next(c for c in result.meta.coverage if c.resource == "calendar_events").state
        == "permission_denied"
    )


async def test_T01_T35_large_inventory_bounded_and_duplicate_changes_visible(
    bridge, owner, seeded, activities
):
    template = bridge.synthetic.data["quizzes"]["11"][0]
    bridge.synthetic.data["quizzes"]["11"] = [
        {**template, "id": n + 100, "description": "x" * 10000} for n in range(120)
    ]
    result = await read(bridge, owner, seeded, activities, limit=20)
    assert len(result.model_dump_json().encode()) <= 220000
    assert result.data["next_offset"] is not None
    assert (
        next(c for c in result.meta.coverage if c.resource == "classic_quizzes").state == "partial"
    )


@pytest.mark.parametrize("all_day", [False, True])
async def test_T04_calendar_half_open_window_across_dst(bridge, owner, seeded, activities, all_day):
    start = datetime.fromisoformat("2026-11-01T00:00:00-04:00")
    end = datetime.fromisoformat("2026-11-02T00:00:00-05:00")
    event = bridge.synthetic.data["calendar_event"]["11"][0]
    event.update(start_at=end.isoformat(), all_day=all_day, all_day_date="2026-11-02")
    course = bridge.selected(owner, seeded)[1][0]
    result = await course_obligations(
        bridge, owner, seeded, course.id, start, end, "America/New_York"
    )
    assert "Laboratory meeting" not in result.model_dump_json()
    event.update(start_at="2026-11-01T01:30:00-05:00", all_day_date="2026-11-01")
    result = await course_obligations(
        bridge, owner, seeded, course.id, start, end, "America/New_York"
    )
    assert "Laboratory meeting" in result.model_dump_json()


async def test_T21_invalid_scope_window_fails_before_academic_reads(
    bridge, owner, seeded, activities
):
    course = bridge.selected(owner, seeded)[1][0]
    requests = len(bridge.synthetic.requests)
    with pytest.raises(DomainError):
        await course_obligations(
            bridge, owner, seeded, course.id, activities, activities + timedelta(days=32), "UTC"
        )
    assert len(bridge.synthetic.requests) == requests
    with pytest.raises(DomainError):
        await course_obligations(
            bridge,
            owner,
            seeded,
            "unselected-course",
            activities,
            activities + timedelta(days=1),
            "UTC",
        )
    assert not any(r.url.path.endswith("/quizzes") for r in bridge.synthetic.requests)
    template = bridge.synthetic.data["quizzes"]["11"][0]
    bridge.synthetic.data["quizzes"]["11"] = [
        template,
        {**template, "description": "Changed during pagination"},
    ]
    result = await read(bridge, owner, seeded, activities)
    assert "Changed during pagination" not in result.model_dump_json()
    assert (
        next(c for c in result.meta.coverage if c.resource == "classic_quizzes").state == "partial"
    )


@pytest.mark.contract
async def test_T30_read_only_mcp_obligation_tool(
    running, bridge, owner, seeded, activities, token_factory
):
    course = bridge.selected(owner, seeded)[1][0]
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tool = next(
                    t
                    for t in (await session.list_tools()).tools
                    if t.name == "get_course_obligations"
                )
                assert tool.annotations.readOnlyHint
                response = await session.call_tool(
                    tool.name,
                    {
                        "connection_id": seeded,
                        "course_id": course.id,
                        "start": activities.isoformat(),
                        "end": (activities + timedelta(days=7)).isoformat(),
                        "timezone": "UTC",
                    },
                )
                assert not response.isError
                assert len(response.structuredContent["data"]["items"]) == 3
                assert response.structuredContent["evidence"]


async def test_T46_missing_posting_time_has_specific_coverage_reason(
    bridge, owner, seeded, activities
):
    bridge.synthetic.data["discussion_topics"]["11"][0]["posted_at"] = None
    result = await read(bridge, owner, seeded, activities)
    assert result.data["omission_reasons"]["discussion_topics"] == {
        "discussion_posting_time_unavailable": 1
    }
    assert "Discuss the controls" not in result.model_dump_json()
    coverage = next(c for c in result.meta.coverage if c.resource == "discussion_topics")
    assert "discussion_posting_time_unavailable=1" in coverage.warning
