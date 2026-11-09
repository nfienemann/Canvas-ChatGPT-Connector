"""Assignment audit scheduling, using only fictional courses and the mock Canvas transport."""

import asyncio
from datetime import timedelta
from time import monotonic

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.planning import PlanRequest
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Snapshot
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


async def select_fixture(bridge, owner, ref, count=5):
    data = bridge.synthetic.data
    names = ["Seminar", "Ethics", "Guide", "Omics", "Stem Cell"]
    template = data["courses"][0]
    for index in range(count + 1):
        number = 11 + index
        course = dict(template, id=number, name=f"Fixture {names[index % 5]} {index}")
        if index < 2:
            data["courses"][index] = course
        else:
            data["courses"].append(course)
        data["assignments"][str(number)] = [{"id": 1, "name": "Fixture assignment"}]
    listed = await bridge.list_courses(owner, ref)
    selected = [row["id"] for row in listed.data["courses"] if row["name"] != course["name"]]
    bridge.select_courses(owner, ref, selected, "UTC")
    return selected


def track_reads(bridge, monkeypatch, on_request):
    provider = bridge.synthetic
    paths = []

    async def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/assignments"):
            response = await on_request(request)
            if response is not None:
                return response
        return provider.handle(request)

    monkeypatch.setattr(
        provider, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    return paths


def window():
    start = utcnow()
    return start, start + timedelta(days=7)


@pytest.mark.parametrize("pages,failure", [(0, None), (1, "retry_later")])
async def test_complete_flag_requires_pages_and_no_failure(
    bridge, owner, seeded, monkeypatch, pages, failure
):
    original = CanvasClient.collection

    async def inconsistent(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS:
            return Collection(complete=True, pages=pages, failure=failure)
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", inconsistent)
    result = await bridge.workload(owner, seeded, *window(), "UTC")
    assert (
        result.status == "partial_data" and not result.data["workload_scope"]["collection_complete"]
    )
    assert all(c.state == "partial" and not c.pagination_complete for c in result.meta.coverage)
    assert all(c.warning == (failure or "missing_page_evidence") for c in result.meta.coverage)


@pytest.mark.contract
async def test_five_course_old_and_new_budget(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    selected = await select_fixture(bridge, owner, seeded)
    assert bridge.settings.refresh_budget_seconds == 12
    assert bridge.settings.workload_refresh_budget_seconds == 3 * 12

    async def latency(request):
        await asyncio.sleep(3.25)

    paths = track_reads(bridge, monkeypatch, latency)
    old = await bridge.refresh(owner, seeded)
    assert not old.complete
    assert any(row["state"] == "not_refreshed" for row in old.coverage)
    assert any(row["warning"] == "refresh_budget_exhausted" for row in old.coverage)
    paths.clear()
    start, end = window()
    async with client_session(
        running, token_factory(scope="academic:read"), read_timeout=75
    ) as session:
        started = monotonic()
        result = (
            await session.call_tool(
                "get_workload",
                {
                    "connection_id": seeded,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": "UTC",
                    "limit": 1,
                },
            )
        ).structuredContent
        elapsed = monotonic() - started
    coverage = result["meta"]["coverage"]
    assert result["status"] == "ok" and result["meta"]["next_cursor"]
    assert {c["course_ref"] for c in coverage} == set(selected)
    assert all(c["state"] == "complete" and c["pages_consumed"] == 1 for c in coverage)
    assert sorted(p for p in paths if p.endswith("/assignments")) == [
        f"/api/v1/courses/{i}/assignments" for i in range(11, 16)
    ]
    print(
        f"Five-course MCP fixture: {elapsed:.2f}s, {len(paths)} provider GETs, five complete sources."
    )


@pytest.mark.contract
async def test_denied_audit_identifies_input_without_releasing_records(
    running, bridge, owner, seeded, token_factory
):
    selected = await select_fixture(bridge, owner, seeded)
    denied = bridge.selected(owner, seeded)[1][0]
    ordered = [course for course in selected if course != denied.id] + [denied.id]
    path = f"/api/v1/courses/{denied.source_id}/assignments"
    bridge.synthetic.failures[path] = 403
    start, end = window()
    async with client_session(running, token_factory(scope="academic:read")) as session:
        error = (
            await session.call_tool(
                "get_workload",
                {
                    "connection_id": seeded,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": "UTC",
                    "course_ids": ordered,
                },
            )
        ).structuredContent
    assert error["status"] == "permission_denied"
    assert error["data"]["reason_code"] == "RESOURCE_PERMISSION_DENIED"
    assert (error["data"]["course_position"], error["data"]["course_order"]) == (5, "request_order")
    assert not error["sources"] and "items" not in error["data"]
    assert sum(req.url.path == path for req in bridge.synthetic.requests) == 1


async def test_larger_scope_retains_pages_and_planning_uncertainty(
    bridge, owner, seeded, monkeypatch
):
    selected = await select_fixture(bridge, owner, seeded, count=10)
    courses = bridge.selected(owner, seeded)[1]
    slow = courses[0]
    bridge.synthetic.data["assignments"][slow.source_id] *= 3
    bridge.settings.refresh_budget_seconds = 2
    cancelled = asyncio.Event()

    async def slow_second_page(request):
        if request.url.params.get("page") == "2":
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()

    paths = track_reads(bridge, monkeypatch, slow_second_page)
    start, end = window()
    result = await bridge.workload(owner, seeded, start, end, "UTC")
    assert cancelled.is_set()
    assert result.status == "partial_data" and result.meta.next_cursor is None
    assert result.data["workload_scope"]["collection_complete"] is False
    by_id = {c.course_ref: c for c in result.meta.coverage}
    assert set(by_id) == set(selected)
    row = by_id.pop(slow.id)
    assert (row.state, row.pages_consumed, row.pagination_complete) == ("partial", 1, False)
    assert row.warning == "refresh_budget_exhausted"
    assert row.reason_code == "INVENTORY_BRANCH_TIMEOUT"
    assert all(c.state == "complete" for c in by_id.values())
    assert sum(p.endswith("/assignments") for p in paths) == 11
    proposal = bridge.study_plan(owner, seeded, result.meta.snapshot_id, PlanRequest())
    assert proposal.status == "partial_data" and proposal.data["feasibility"] == "partial_workload"
    assert proposal.meta.coverage == result.meta.coverage


async def test_page_cap_and_snapshot_cursor_are_independent(bridge, owner, seeded):
    refs = await select_fixture(bridge, owner, seeded)
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["assignments"][course.source_id] = [
        {"id": i, "name": "Fixture assignment"} for i in range(1, 4)
    ]
    bridge.settings.max_pages = 1
    start, end = window()
    args = (owner, seeded, start, end, "UTC", refs)
    first = await bridge.workload(*args, limit=1)
    assert first.status == "partial_data" and first.meta.next_cursor
    row = next(row for row in first.meta.coverage if row.course_ref == course.id)
    assert row.pages_consumed == 1 and not row.pagination_complete
    assert row.reason_code == "TASK_BUDGET_EXCEEDED"
    sent = len(bridge.synthetic.requests)
    second = await bridge.workload(*args, limit=1, cursor=first.meta.next_cursor)
    assert second.status == "partial_data" and second.meta.coverage == first.meta.coverage
    assert second.meta.freshness == "cached" and second.meta.snapshot_id == first.meta.snapshot_id
    assert len(bridge.synthetic.requests) == sent
    bridge.settings.max_pages = 2
    complete = await bridge.workload(*args)
    row = next(row for row in complete.meta.coverage if row.course_ref == course.id)
    assert complete.status == "ok" and row.pagination_complete and row.pages_consumed == 2


async def test_cancelled_workload_releases_client_and_lock(bridge, owner, seeded, monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()

    async def stall(request):
        if not entered.is_set():
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                closed.set()

    paths = track_reads(bridge, monkeypatch, stall)
    start, end = window()
    task = asyncio.create_task(bridge.workload(owner, seeded, start, end, "UTC"))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and sum(p.endswith("/assignments") for p in paths) == 1
    with bridge.store.transaction() as db:
        assert not db.scalar(select(Snapshot))
    result = await asyncio.wait_for(bridge.workload(owner, seeded, start, end, "UTC"), 10)
    assert result.status == "ok"


async def test_exhaustion_gives_each_course_a_turn_and_scoped_retry_a_full_budget(
    bridge, owner, seeded, monkeypatch
):
    selected = await select_fixture(bridge, owner, seeded)
    bridge.settings.refresh_budget_seconds = 1

    async def slow_source(request):
        await asyncio.sleep(1.25)

    paths = track_reads(bridge, monkeypatch, slow_source)
    start, end = window()
    result = await bridge.workload(owner, seeded, start, end, "UTC")
    assert result.status == "partial_data" and result.meta.next_cursor is None
    assert {row.course_ref for row in result.meta.coverage} == set(selected)
    assert all(
        row.state == "unavailable" and row.warning == "refresh_budget_exhausted"
        for row in result.meta.coverage
    )
    assert len(set(p for p in paths if p.endswith("/assignments"))) == 5
    paths.clear()
    # Five interrupted provider attempts open the normal circuit. A narrower
    # query must also honor its cooldown before doing any upstream work.
    with pytest.raises(DomainError) as blocked:
        await bridge.workload(owner, seeded, start, end, "UTC", [selected[-1]])
    assert blocked.value.reason_code == "UPSTREAM_THROTTLED" and not paths
    after_cooldown = bridge.usage.clock() + blocked.value.details["retry_after_seconds"] + 1
    monkeypatch.setattr(bridge.usage, "clock", lambda: after_cooldown)
    retried = await bridge.workload(owner, seeded, start, end, "UTC", [selected[-1]])
    assert retried.status == "ok"
    assert [row.course_ref for row in retried.meta.coverage] == [selected[-1]]
    assert len(paths) == 2


@pytest.mark.parametrize("status", [403, 429])
async def test_upstream_stop_conditions(bridge, owner, seeded, monkeypatch, status):
    await select_fixture(bridge, owner, seeded)

    async def limited(request):
        return httpx.Response(status, headers={"Retry-After": "90"})

    paths = track_reads(bridge, monkeypatch, limited)
    start, end = window()
    if status == 403:
        with pytest.raises(DomainError) as exc:
            await bridge.workload(owner, seeded, start, end, "UTC")
        assert exc.value.status == "permission_denied" and exc.value.upstream_http_status == 403
        with bridge.store.transaction() as db:
            assert not db.scalar(select(Snapshot))
    else:
        result = await bridge.workload(owner, seeded, start, end, "UTC")
        assert result.status == "partial_data" and result.meta.freshness == "not_refreshed"
        assert len(result.meta.coverage) == 5
        assert all(
            c.reason_code == "UPSTREAM_THROTTLED" and c.retry_after_seconds
            for c in result.meta.coverage
        )
    assert sum(p.endswith("/assignments") for p in paths) == 1


@pytest.mark.contract
@pytest.mark.parametrize("cross_course", [False, True])
async def test_rejected_workload_continuation_has_public_recovery_guidance(
    running, bridge, owner, seeded, token_factory, monkeypatch, cross_course
):
    course = bridge.selected(owner, seeded)[1][0]
    start, end = window()
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        link = str(request.url.copy_set_param("page", 2))
        if cross_course:
            link = link.replace(f"/courses/{course.source_id}/", "/courses/999/")
        else:
            link += "&page=3"
        return httpx.Response(
            200,
            json=[{"id": 42, "name": "Fixture", "due_at": end.isoformat()}],
            headers={"Link": f'<{link}>; rel="next"'},
        )

    track_reads(bridge, monkeypatch, handle)
    async with client_session(running, token_factory(scope="academic:read")) as client:
        reply = await client.call_tool(
            "get_workload",
            {
                "connection_id": seeded,
                "course_ids": [course.id],
                "start": start.isoformat(),
                "end": (end + timedelta(days=1)).isoformat(),
                "timezone": "UTC",
            },
        )
    body = reply.structuredContent
    assert calls == [f"/api/v1/courses/{course.source_id}/assignments"]
    if cross_course:
        assert body["status"] == "permission_denied" and not body["data"].get("items")
        assert body["data"]["reason_code"] == "PAGINATION_SCOPE_CHANGED"
        assert body["data"]["recommended_action"] == "report_request_id"
        assert bridge.selected(owner, seeded, [course.id])[1][0].accessible
    else:
        assert body["status"] == "partial_data" and len(body["data"]["items"]) == 1
        assert body["data"]["workload_scope"]["collection_complete"] is False
        coverage = body["meta"]["coverage"][0]
        assert coverage["reason_code"] == "PAGINATION_LINK_INVALID"
        assert "continuation" in coverage["warning"].lower()
