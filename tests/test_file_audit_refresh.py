"""Failed membership refreshes retain the actual cause without granting scope."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from canvas_bridge.domain import DomainError, Result


def test_inventory_projection_keeps_safe_failure_evidence():
    from canvas_bridge.egress_sources import minimize

    result = Result(
        status="partial_data",
        summary="",
        data={
            "files": [],
            "coverage": {"files": "partial"},
            "inventory_reason_codes": {
                "files": {
                    "reason_code": "RESOURCE_PERMISSION_DENIED",
                    "upstream_http_status": 403,
                    "url": "PRIVATE",
                    "source_text": "PRIVATE",
                }
            },
        },
    )
    clean, _ = minimize(result, "list_course_files", live=True)
    assert clean.data["coverage"]["files"] == "partial"
    assert (
        clean.data["inventory_reason_codes"]["files"]["reason_code"] == "RESOURCE_PERMISSION_DENIED"
    )
    assert "PRIVATE" not in clean.model_dump_json()


async def test_inventory_privacy_binding_uses_canvas_subject_not_connection_object(
    bridge, owner, seeded
):
    from canvas_bridge.egress_sources import resolve_sources

    _, courses = bridge.selected(owner, seeded)
    _, subject = resolve_sources(
        bridge.egress,
        owner,
        {
            "connection_id": seeded,
            "course_id": courses[0].id,
        },
        Result(summary="", data={"files": []}),
        "list_course_files",
    )
    assert subject == "101"


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("partial_data", "OWNER_RATE_LIMITED", "retry_later"),
        ("partial_data", "UPSTREAM_REQUEST_TIMEOUT", "retry_later"),
        ("permission_denied", "RESOURCE_PERMISSION_DENIED", "permission_denied"),
        ("reconnect_required", "UPSTREAM_AUTH_EXPIRED", "reconnect_required"),
    ],
)
async def test_refresh_preserves_cause(bridge, monkeypatch, status, reason, expected):
    monkeypatch.setattr(
        bridge,
        "list_courses",
        AsyncMock(
            return_value=Result(status=status, summary="incomplete", data={"reason_code": reason})
        ),
    )
    with pytest.raises(DomainError) as error:
        await bridge.refresh_course_access("owner", "connection")
    assert error.value.status == expected
    assert error.value.reason_code == reason


async def test_successful_renewal_still_uses_actual_membership(bridge, owner, seeded):
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, seeded).entitlement_at = None
    await bridge.refresh_course_access(owner, seeded)
    assert bridge.selected(owner, seeded)[1]


async def test_empty_failed_listing_has_bound_source_and_safe_cause(bridge, owner, seeded):
    from canvas_bridge.egress_sources import minimize, resolve_sources

    result = Result(
        status="partial_data",
        summary="untrusted summary",
        data={"courses": [], "reason_code": "OWNER_RATE_LIMITED", "private": "must disappear"},
    )
    sources, _ = resolve_sources(
        bridge.egress, owner, {"connection_id": seeded}, result, "list_courses"
    )
    assert len(sources) == 1
    assert sources[0].source_id == seeded
    assert sources[0].kind == "course"
    clean, minimized = minimize(result, "list_courses", live=True)
    assert minimized
    assert clean.data["reason_code"] == "OWNER_RATE_LIMITED"
    assert "private" not in clean.data


async def test_later_course_is_explicitly_not_refreshed(bridge, owner, seeded, monkeypatch):
    from canvas_bridge.canvas import CanvasClient
    from canvas_bridge.policy import Endpoint

    _, courses = bridge.selected(owner, seeded)
    assert len(courses) > 1
    original = CanvasClient.collection

    async def slow(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS:
            await asyncio.sleep(0.2)
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", slow)
    bridge.settings.refresh_budget_seconds = 0.05
    snapshot = await bridge.refresh(owner, seeded)
    assert not snapshot.complete
    assert snapshot.coverage[0]["state"] == "unavailable"
    assert snapshot.coverage[-1]["state"] == "not_refreshed"
    assert {row["course_ref"] for row in snapshot.coverage} == {c.id for c in courses}


async def test_retry_after_survives_collection_refresh_and_safe_release(
    bridge, owner, seeded, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient, upstream_error
    from canvas_bridge.egress_errors import safe_error_result

    async def throttle(*args, **kwargs):
        raise upstream_error(429, {"Retry-After": "180.2"})

    monkeypatch.setattr(CanvasClient, "_get", throttle)
    with pytest.raises(DomainError) as error:
        await bridge.refresh_course_access(owner, seeded)
    assert error.value.data["retry_after_seconds"] == 181
    clean = safe_error_result(
        Result(status=error.value.status, summary="hidden", data=error.value.data)
    )
    assert clean.data["retry_after_seconds"] == 181
    assert clean.data["reason_code"] == "UPSTREAM_THROTTLED"
