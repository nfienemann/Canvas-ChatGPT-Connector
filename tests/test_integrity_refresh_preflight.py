from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.integrity.surfaces import before_tool


async def test_reader_preflight_reports_rate_limit_instead_of_stale_scope():
    bridge = SimpleNamespace(
        refresh_course_access=AsyncMock(
            return_value=Result(
                status="partial_data",
                summary="Refresh incomplete",
                data={"reason_code": "OWNER_RATE_LIMITED"},
            )
        )
    )
    with pytest.raises(DomainError) as error:
        await before_tool(
            bridge, "owner", "get_assignment_details", {"connection_id": "connection"}
        )
    assert error.value.reason_code == "OWNER_RATE_LIMITED"
    bridge.refresh_course_access.assert_awaited_once_with("owner", "connection")


async def test_reader_preflight_renews_invalidated_membership(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    with bridge.store.transaction() as db:
        row = bridge.store.connection(db, owner, seeded)
        row.entitlement_at = None
    # Mock only the policy decision to isolate membership renewal; source reads
    # and production policy evaluation remain covered by integrity contract tests.
    bridge.integrity.evaluate = AsyncMock(
        return_value=(SimpleNamespace(require=lambda: None), None)
    )
    await before_tool(
        bridge,
        owner,
        "get_assignment_details",
        {"connection_id": seeded, "course_id": courses[0].id},
    )
    bridge.selected(owner, seeded, [courses[0].id])
    bridge.integrity.evaluate.assert_awaited_once()


async def test_integrity_discovery_does_not_fetch_unrelated_assignment_details(
    bridge, owner, seeded, monkeypatch
):
    from canvas_bridge.academic_intelligence import collect_course
    from canvas_bridge.canvas import CanvasClient
    from canvas_bridge.policy import Endpoint

    _, courses = bridge.selected(owner, seeded)
    calls = []
    original = CanvasClient.one

    async def tracked(self, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENT:
            calls.append(kwargs.get("assignment"))
        return await original(self, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "one", tracked)
    bundle = await collect_course(bridge, owner, seeded, courses[0].id, purpose="integrity")
    assert not calls
    assert not bundle["assignments"]
    assert bundle["coverage"]


@pytest.mark.parametrize(
    "reason", ["UPSTREAM_THROTTLED", "TASK_BUDGET_EXCEEDED", "OWNER_RATE_LIMITED"]
)
async def test_nested_membership_refresh_preserves_failure_reason(reason):
    from canvas_bridge.service import Bridge

    bridge = SimpleNamespace(
        list_courses=AsyncMock(
            return_value=Result(
                status="partial_data", summary="Incomplete", data={"reason_code": reason}
            )
        )
    )
    with pytest.raises(DomainError) as error:
        await Bridge.refresh_course_access(bridge, "owner", "connection")
    assert error.value.status == "retry_later"
    assert error.value.reason_code == reason
