"""Reproducible orchestration regressions over fictional authorized records."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from canvas_bridge import workflow_operations, workflows
from canvas_bridge.calendar_sync import CalendarContext
from canvas_bridge.domain import DomainError, Result, Source, utcnow
from canvas_bridge.storage import Connection
from canvas_bridge.workflow_budget import Budget, active_budget, count_bytes, count_request
from canvas_bridge.workflow_registry import WORKFLOWS, Limits, WorkflowRequest
from canvas_bridge.workflows import run_workflow
from tests.test_academic_intelligence import academic as academic
from tests.test_figure_inspection import visual_source as visual_source
from tests.test_file_reading import readable as readable
from tests.test_grade_audit import grade_data as grade_data
from tests.test_mcp_contract import running as running


def request(name, **kwargs):
    now = utcnow()
    return WorkflowRequest(workflow=name, start=now, end=now + timedelta(days=7), **kwargs)


def calendar(req):
    return CalendarContext(
        calendar_id="fictional",
        timezone="UTC",
        retrieved_at=utcnow(),
        window_start=req.start,
        window_end=req.end,
        pagination_complete=True,
        availability_complete=True,
        mapping_search_complete=True,
        events=[],
    )


def section(result, name):
    return next(s for s in result.data["sections"] if s["step"] == name)


@pytest.mark.parametrize("name", list(WORKFLOWS))
async def test_every_workflow_has_real_bounded_execution(bridge, owner, seeded, academic, name):
    result = await run_workflow(bridge, owner, seeded, request(name, course_ids=[academic.id]))
    assert result.status in {"ok", "partial_data"}
    assert result.data["actions_executed"] is False
    assert {t["step"] for t in result.data["execution"]["trace"]} == {
        s.name for s in WORKFLOWS[name].steps
    }
    assert result.data["execution"]["http_calls"] <= Limits().http_calls
    assert len(result.model_dump_json().encode()) <= Limits().output_bytes
    assert all(s.course_id in {None, academic.id} for s in result.sources)


async def test_one_workload_read_and_missing_calendar_preserves_priorities(
    bridge, owner, seeded, monkeypatch
):
    original, calls = bridge.workload, []

    async def counted(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(bridge, "workload", counted)
    result = await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
    assert len(calls) == 1
    assert result.status == "partial_data"
    assert section(result, "priorities")["data"]
    assert section(result, "availability")["data"]["reason_code"] == "CALENDAR_UNAVAILABLE"
    assert "not free time" in " ".join(section(result, "priorities")["data"]["assumptions"])


async def test_unavailable_course_and_absent_baseline_are_explicit(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0].id
    result = await run_workflow(
        bridge,
        owner,
        seeded,
        request("daily_academic_brief", course_ids=[course, "unknown-course"]),
    )
    assert result.data["unavailable_course_count"] == 1
    assert result.data["course_ids"] == [course]
    assert section(result, "changes")["data"]["reason_code"] == "BASELINE_NOT_REQUESTED"
    assert result.status == "partial_data"


async def test_grade_evidence_is_shared_with_scenario(
    bridge, owner, seeded, grade_data, monkeypatch
):
    course = bridge.selected(owner, seeded)[1][0].id
    original, calls = workflow_operations.collect, []

    async def counted(*args):
        calls.append(1)
        return await original(*args)

    monkeypatch.setattr(workflow_operations, "collect", counted)
    result = await run_workflow(
        bridge,
        owner,
        seeded,
        request(
            "grade_outlook",
            course_ids=[course],
            scenario={"target_percent": 90, "acknowledge_visible_scope": True},
            scenario_mode="required_score",
        ),
    )
    assert len(calls) == 1
    assert (
        section(result, "current_grade")["data"]["calculation"]["calculated_percentage"]
        == "86.0000"
    )
    assert "calculation" in section(result, "scenario")["data"]


@pytest.mark.parametrize(
    "status,code", [("retry_later", "RATE_LIMITED"), ("partial_data", "WORKFLOW_BUDGET_EXHAUSTED")]
)
async def test_failed_retrieval_blocks_dependents_without_invention(
    bridge, owner, seeded, monkeypatch, status, code
):
    async def fail(*args, **kwargs):
        raise DomainError(status, "private upstream detail", reason_code=code)

    monkeypatch.setattr(bridge, "workload", fail)
    result = await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
    assert section(result, "priorities")["data"]["reason_code"] == "DEPENDENCY_UNAVAILABLE"
    assert not result.sources
    assert "private upstream" not in result.model_dump_json()


async def test_timeout_preserves_independent_calendar(bridge, owner, seeded, monkeypatch):
    async def timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(bridge, "workload", timeout)
    req = request("weekly_course_priorities")
    req.calendar = calendar(req)
    result = await run_workflow(bridge, owner, seeded, req)
    assert section(result, "obligations")["data"]["reason_code"] == "WORKFLOW_STEP_TIMEOUT"
    assert section(result, "availability")["status"] == "ok"


async def test_expired_authorization_and_mid_workflow_revocation_withhold(
    bridge, owner, seeded, monkeypatch
):
    original = bridge.workload

    async def revoke(*args, **kwargs):
        result = await original(*args, **kwargs)
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).epoch += 1
        return result

    monkeypatch.setattr(bridge, "workload", revoke)
    with pytest.raises(DomainError) as exc:
        await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
    assert exc.value.status in {"source_changed", "permission_denied"}
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).token_expires_at = utcnow() - timedelta(days=1)
    with pytest.raises(DomainError):
        await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))


async def test_wrong_source_reference_is_detected(bridge, owner, seeded, monkeypatch):
    async def wrong(*args, **kwargs):
        return Result(
            summary="Unverified claim",
            sources=[
                Source(
                    id="invented",
                    title="Fake",
                    url="https://example.invalid/fake",
                    retrieved_at=utcnow(),
                )
            ],
        )

    monkeypatch.setattr(bridge, "workload", wrong)
    result = await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
    assert not result.sources
    assert section(result, "obligations")["data"]["reason_code"] == "WORKFLOW_SOURCE_MISMATCH"
    assert "Unverified claim" not in result.summary


async def test_concurrent_requests_keep_isolated_budgets(bridge, owner, seeded):
    results = await asyncio.gather(
        *(
            run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
            for _ in range(2)
        )
    )
    assert all(len(r.data["execution"]["trace"]) == 3 for r in results)
    assert active_budget.get() is None
    assert bridge.request_limits.active == 0


async def test_lecture_reading_never_claims_unseen_pixels(bridge, owner, seeded, readable):
    course, file = readable
    result = await run_workflow(
        bridge,
        owner,
        seeded,
        request("lecture_comprehension", course_ids=[course.id], material_ids=[file, file]),
    )
    assert len(section(result, "reading")["data"]["documents"]) == 1
    assert (
        section(result, "interpretation")["data"]["comprehension_status"]
        == "awaiting_client_inspection"
    )
    assert result.status == "partial_data"


async def test_calendar_proposals_repeat_without_creating_events(bridge, owner, seeded):
    req = request("calendar_preparation")
    req.calendar = calendar(req)
    first = await run_workflow(bridge, owner, seeded, req)
    second = await run_workflow(bridge, owner, seeded, req)
    # Freshness and observed source versions can change on repeated retrieval;
    # provider mapping identities must remain stable.
    a = section(first, "event_proposals")["data"]["proposals"]
    b = section(second, "event_proposals")["data"]["proposals"]
    assert [(p["work_id"], p["action"]) for p in a] == [(p["work_id"], p["action"]) for p in b]
    assert first.data["actions_executed"] is False


def test_limits_and_untrusted_graph_inputs():
    for invalid in (
        {"workflow": "write_calendar"},
        {"workflow": "daily_academic_brief", "steps": []},
        {"workflow": "daily_academic_brief", "timezone": "not-a-zone"},
    ):
        with pytest.raises(ValidationError):
            WorkflowRequest.model_validate(invalid)
    budget = Budget(replace(Limits(), http_calls=1, api_bytes=2))
    token = active_budget.set(budget)
    try:
        count_request()
        count_bytes(2)
        with pytest.raises(DomainError):
            count_request()
        with pytest.raises(DomainError):
            count_bytes(3)
    finally:
        active_budget.reset(token)


async def test_workflow_real_mcp_contract(running, token_factory, seeded):
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tool = next(
                    t
                    for t in (await session.list_tools()).tools
                    if t.name == "run_academic_workflow"
                )
                assert tool.annotations.readOnlyHint
                result = await session.call_tool(
                    tool.name,
                    {
                        "connection_id": seeded,
                        "request": request("weekly_course_priorities").model_dump(mode="json"),
                    },
                )
                payload = result.structuredContent
                assert payload["status"] == "partial_data"
                assert payload["data"]["workflow"] == "weekly_course_priorities"
                assert payload["data"]["execution"]["trace"]
                assert payload["data"]["sections"]


async def test_corrupt_document_retains_independent_course_scope(
    bridge, owner, seeded, readable, monkeypatch
):
    course, file = readable

    async def corrupt(*args, **kwargs):
        raise DomainError("unsupported_feature", "Corrupt fictional document")

    monkeypatch.setattr(workflow_operations, "fetch_material", corrupt)
    result = await run_workflow(
        bridge,
        owner,
        seeded,
        request("lecture_comprehension", course_ids=[course.id], material_ids=[file]),
    )
    assert section(result, "materials")["status"] == "ok"
    assert section(result, "reading")["data"]["documents"][0]["status"] == "unsupported_feature"
    assert result.status == "partial_data"


async def test_optional_capability_denial_does_not_call_it(bridge, owner, seeded, monkeypatch):
    original = workflows.capability

    def capability(ctx, operation, **kwargs):
        if operation == "changes":
            raise DomainError(
                "permission_denied", "Not supported", reason_code="MISSING_RESOURCE_CAPABILITY"
            )
        return original(ctx, operation, **kwargs)

    def forbidden(*args):
        pytest.fail("Unsupported operation must not execute")

    monkeypatch.setattr(workflows, "capability", capability)
    monkeypatch.setattr(bridge, "changes", forbidden)
    result = await run_workflow(
        bridge, owner, seeded, request("daily_academic_brief", since=utcnow() - timedelta(days=1))
    )
    assert section(result, "obligations")["data"]["items"]
    assert section(result, "changes")["data"]["reason_code"] == "MISSING_RESOURCE_CAPABILITY"


async def test_output_budget_marks_whole_omitted_sections(bridge, owner, seeded, monkeypatch):
    original = WORKFLOWS["weekly_course_priorities"]
    monkeypatch.setattr(
        workflows,
        "WORKFLOWS",
        {original.name: replace(original, limits=replace(original.limits, output_bytes=6000))},
    )
    result = await run_workflow(bridge, owner, seeded, request(original.name))
    assert len(result.model_dump_json().encode()) <= 6000
    assert result.status == "partial_data"
    assert any(
        t["reason_code"] == "WORKFLOW_OUTPUT_LIMIT" for t in result.data["execution"]["trace"]
    )
    retained = {s for section in result.data["sections"] for s in section["source_ids"]}
    assert {s.id for s in result.sources} <= retained


async def test_transport_budget_is_actually_enforced(bridge, owner, seeded, monkeypatch):
    original = WORKFLOWS["weekly_course_priorities"]
    monkeypatch.setattr(
        workflows,
        "WORKFLOWS",
        {original.name: replace(original, limits=replace(original.limits, http_calls=1))},
    )
    budgets = []

    def capture(limits):
        budget = Budget(limits)
        budgets.append(budget)
        return budget

    monkeypatch.setattr(workflows, "Budget", capture)
    # Exhausting the membership refresh also invalidates its lease. The aggregate
    # must then be withheld instead of returning facts under stale authorization.
    with pytest.raises(DomainError):
        await run_workflow(bridge, owner, seeded, request(original.name))
    assert budgets[0].http_calls == 1 and budgets[0].exhausted
    assert active_budget.get() is None


async def test_partial_workload_has_partial_priorities(bridge, owner, seeded, monkeypatch):
    original = bridge.workload

    async def partial(*args, **kwargs):
        result = await original(*args, **kwargs)
        result.status = "partial_data"
        result.meta.next_cursor = "fictional-continuation"
        return result

    monkeypatch.setattr(bridge, "workload", partial)
    result = await run_workflow(bridge, owner, seeded, request("weekly_course_priorities"))
    assert result.status == "partial_data"
    assert section(result, "obligations")["status"] == "partial_data"


async def test_exam_outline_respects_calendar_busy_times(bridge, owner, seeded):
    from canvas_bridge.planning import PlanRequest, Window
    from canvas_bridge.workflows import Context

    course = bridge.selected(owner, seeded)[1][0].id
    req = request("exam_preparation_pack", course_ids=[course])
    req.plan = PlanRequest(
        windows=[Window(start=req.start + timedelta(hours=1), end=req.start + timedelta(hours=2))],
        buffer_minutes=0,
    )
    req.calendar = calendar(req)
    req.calendar.busy_times = [
        Window(start=req.start + timedelta(hours=1), end=req.start + timedelta(hours=1, minutes=30))
    ]
    ctx = Context(bridge, owner, seeded, req, [course], bridge.selected(owner, seeded)[0].epoch)
    result = await workflow_operations.exam_outline(
        ctx,
        course,
        {
            "assessment": Result(
                summary="Synthetic assessment", data={"assessment": {"work_id": "fictional"}}
            )
        },
    )
    block = result.data["study_blocks"][0]
    assert block["minutes"] == 30
    assert block["start"] == req.calendar.busy_times[0].end.isoformat()


async def test_lecture_resumes_with_attributed_visual_report(
    bridge, owner, seeded, readable, visual_source
):
    from canvas_bridge.figure_inspection import inspect_figure
    from tests.test_scientific_comprehension import visible

    rendered, _ = await inspect_figure(bridge, owner, seeded, visual_source, page=4)
    result = await run_workflow(
        bridge,
        owner,
        seeded,
        request(
            "lecture_comprehension",
            course_ids=[readable[0].id],
            material_ids=[visual_source],
            visual_reports=[
                {
                    "file_id": visual_source,
                    "render_receipt": rendered.data["render_receipt"],
                    "observation": visible(),
                }
            ],
        ),
    )
    report = section(result, "interpretation")["data"]["reports"][0]
    assert report["interpretation_verified"] is False
    assert report["file_id"] == visual_source
    assert result.status == "partial_data" and result.data["actions_executed"] is False
    assert all(
        "document_model" not in d["data"] for d in section(result, "reading")["data"]["documents"]
    )
