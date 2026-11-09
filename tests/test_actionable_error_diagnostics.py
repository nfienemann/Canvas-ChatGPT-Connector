"""Public diagnostics identify actionable causes without echoing private errors."""

import pytest

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_errors import safe_error_result
from canvas_bridge.usage.ledger import UpstreamUsageGovernor
from tests.test_mcp_contract import running as running
from tests.test_usage_governor import ctx, policy, reserve
from tests.test_usage_governor import ledger as ledger


@pytest.mark.parametrize(
    "warning,expected",
    [
        ("refresh_budget_exhausted", "Retry this course separately"),
        ("request_budget", "request budget"),
        ("permission_denied", "Check this resource's availability in Canvas"),
        ("PRIVATE upstream body", "Coverage limitation reported."),
    ],
)
def test_minimized_coverage_retains_safe_recovery_steps(warning, expected):
    from canvas_bridge.domain import Coverage
    from canvas_bridge.egress_sources import minimize

    original = Result(status="partial_data", summary="", data={"items": []})
    original.meta.coverage = [
        Coverage(course_ref="fixture", resource="assignments", state="partial", warning=warning)
    ]
    clean, _ = minimize(original, "get_workload", live=True)
    assert expected in clean.meta.coverage[0].warning
    assert "PRIVATE" not in clean.model_dump_json()
    repeated, _ = minimize(clean, "get_workload", live=True)
    assert repeated.meta.coverage == clean.meta.coverage


@pytest.mark.contract
async def test_coverage_recovery_survives_final_mcp_privacy_boundary(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    from unittest.mock import AsyncMock

    from canvas_bridge.domain import Coverage
    from canvas_bridge.egress_sources import minimize
    from tests.test_permission_consistency_contract import client_session

    course_id = bridge.selected(owner, seeded)[1][0].id
    original = Result(status="partial_data", summary="", data={"items": []})
    original.meta.coverage = [
        Coverage(
            course_ref=course_id,
            resource="assignments",
            state="not_refreshed",
            warning="refresh_budget_exhausted",
        )
    ]
    clean, _ = minimize(original, "get_workload", live=True)
    monkeypatch.setattr(bridge, "workload", AsyncMock(return_value=clean))
    async with client_session(running, token_factory()) as session:
        response = await session.call_tool(
            "get_workload",
            {
                "connection_id": seeded,
                "course_ids": [course_id],
                "start": "2026-11-03T00:00:00Z",
                "end": "2026-11-04T00:00:00Z",
                "timezone": "UTC",
            },
        )
    result = response.structuredContent
    assert result["status"] == "partial_data"
    assert "Retry this course separately" in result["meta"]["coverage"][0]["warning"]
    assert result["meta"]["coverage"][0]["pagination_complete"] is False


@pytest.mark.contract
async def test_all_course_workload_discloses_unchecked_obligation(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient, Collection
    from canvas_bridge.policy import Endpoint
    from tests.test_permission_consistency_contract import client_session

    courses = bridge.selected(owner, seeded)[1]
    affected = courses[-1]
    bridge.synthetic.data["assignments"][affected.source_id] = [
        {"id": 9123, "name": "Synthetic omitted obligation"}
    ]
    original = CanvasClient.collection

    async def limited(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS and kwargs.get("course") == affected.source_id:
            return Collection(
                failure="retry_later",
                reason_code="UPSTREAM_THROTTLED",
                upstream_http_status=429,
                retry_after_seconds=33,
            )
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", limited)
    async with client_session(running, token_factory(scope="academic:read")) as session:
        result = (
            await session.call_tool(
                "get_workload",
                {
                    "connection_id": seeded,
                    "start": "2026-11-03T00:00:00Z",
                    "end": "2026-11-04T00:00:00Z",
                    "timezone": "UTC",
                },
            )
        ).structuredContent
    assert result["status"] == "partial_data"
    branch = next(b for b in result["meta"]["coverage"] if b["course_ref"] == affected.id)
    assert branch["state"] == "partial" and not branch["pagination_complete"]
    assert branch["reason_code"] == "UPSTREAM_THROTTLED" and branch["retry_after_seconds"] == 33
    assert "Synthetic omitted obligation" not in str(result["data"])


def test_local_concurrency_is_not_reported_as_provider_throttling(ledger):
    governor = UpstreamUsageGovernor(
        ledger, fixture_policy=policy(limits={"max_concurrency_per_token": 1})
    )
    reserve(governor, ctx(token_key="same-token"))
    with pytest.raises(DomainError) as caught:
        reserve(governor, ctx(token_key="same-token"))
    assert caught.value.reason_code == "LOCAL_REQUEST_BUSY"
    assert caught.value.details["reservation_state"] == "expiration_pending"
    clean = safe_error_result(Result(status="retry_later", summary="", data=caught.value.data))
    assert clean.data["error_origin"] == "bridge_admission"
    assert clean.data["retry_condition"] == "active_request_finished"
    assert "reconnect" in clean.summary.lower()


@pytest.mark.parametrize(
    "code,origin,action",
    [
        ("UNSUPPORTED_FILE_FORMAT", "document_parser", "use_supported_text_format"),
        ("AUTHORIZATION_BUSY", "bridge_authorization", "wait_for_active_request_then_retry"),
        ("STALE_SCOPE_SNAPSHOT", "bridge_authorization", "refresh_course_list_then_retry"),
        (
            "EGRESS_CLASSIFICATION_UNKNOWN",
            "content_governance",
            "request_source_classification_review",
        ),
        (
            "EGRESS_CONTENT_HASH_REVIEW_REQUIRED",
            "content_governance",
            "review_current_source_version",
        ),
        ("RENDER_DEPENDENCY_UNAVAILABLE", "document_runtime", "check_renderer_installation"),
        (
            "INVENTORY_PAGINATION_CYCLE",
            "upstream_inventory",
            "retain_partial_inventory_and_report_request_id",
        ),
    ],
)
def test_actionable_diagnostics_are_reconstructed_from_fixed_codes(code, origin, action):
    clean = safe_error_result(
        Result(
            status="retry_later",
            summary="PRIVATE source text",
            data={
                "reason_code": code,
                "error_origin": "PRIVATE credential",
                "recommended_action": "PRIVATE URL",
            },
        )
    )
    assert clean.data["error_origin"] == origin
    assert clean.data["recommended_action"] == action
    assert "PRIVATE" not in clean.model_dump_json()
    assert safe_error_result(clean).data == clean.data


def test_coverage_never_echoes_unknown_reason():
    from canvas_bridge.domain import Coverage

    c = Coverage(
        course_ref="fictional",
        resource="assignments",
        state="partial",
        reason_code="PRIVATE secret",
    )
    assert c.reason_code == "UNCLASSIFIED_FAILURE" and "PRIVATE" not in c.model_dump_json()


def test_unknown_error_cannot_inject_diagnostic_guidance():
    clean = safe_error_result(
        Result(
            status="retry_later",
            summary="PRIVATE",
            data={
                "reason_code": "PRIVATE_CODE",
                "error_origin": "PRIVATE",
                "recommended_action": "PRIVATE",
            },
        )
    )
    assert clean.data["reason_code"] == "EGRESS_ERROR_REDACTED"
    assert "PRIVATE" not in clean.model_dump_json()


def test_classification_failure_survives_repeated_error_projection():
    clean = safe_error_result(
        Result(
            status="permission_denied",
            summary="PRIVATE",
            data={
                "reason_code": "EGRESS_CLASSIFICATION_UNKNOWN",
                "egress": {"decision": "REQUIRES_AUTHORIZED_REVIEW", "source": "PRIVATE"},
                "processing_stage": "PRIVATE",
            },
        )
    )
    assert clean.data["processing_stage"] == "source_classification"
    assert clean.data["content_decision"] == "REQUIRES_AUTHORIZED_REVIEW"
    assert safe_error_result(clean).data == clean.data
    assert "PRIVATE" not in clean.model_dump_json()


@pytest.mark.contract
@pytest.mark.parametrize(
    "code",
    [
        "LOCAL_REQUEST_BUSY",
        "UPSTREAM_THROTTLED",
        "STALE_SCOPE_SNAPSHOT",
        "EGRESS_CLASSIFICATION_UNKNOWN",
    ],
)
async def test_diagnostics_survive_real_mcp_and_final_privacy_projection(
    running, bridge, seeded, token_factory, monkeypatch, code
):
    from unittest.mock import AsyncMock

    from tests.test_permission_consistency_contract import client_session

    monkeypatch.setattr(
        bridge,
        "list_courses",
        AsyncMock(
            side_effect=DomainError(
                "retry_later",
                "PRIVATE upstream body",
                reason_code=code,
                details={
                    "credential": "PRIVATE",
                    "recommended_action": "PRIVATE",
                    "retry_after_seconds": 37,
                },
            )
        ),
    )
    async with client_session(running, token_factory()) as session:
        response = await session.call_tool("list_courses", {"connection_id": seeded})
    result = response.structuredContent
    assert result["data"]["reason_code"] == code
    assert result["data"]["error_origin"]
    assert result["data"]["recommended_action"]
    assert result["data"]["retry_condition"]
    assert result["data"]["retry_after_seconds"] == 37
    assert result["meta"]["request_id"]
    assert "PRIVATE" not in str(result)


@pytest.mark.contract
async def test_unexpected_failure_request_id_matches_safe_operator_log(
    running, bridge, seeded, token_factory, monkeypatch, caplog
):
    from unittest.mock import AsyncMock

    from tests.test_permission_consistency_contract import client_session

    monkeypatch.setattr(
        bridge, "list_courses", AsyncMock(side_effect=RuntimeError("PRIVATE credential"))
    )
    async with client_session(running, token_factory()) as session:
        response = await session.call_tool("list_courses", {"connection_id": seeded})
    result = response.structuredContent
    records = [r.getMessage() for r in caplog.records if "tool_failed" in r.getMessage()]
    assert any(result["meta"]["request_id"] in message for message in records)
    assert "PRIVATE" not in str(result)
    assert all("PRIVATE" not in message for message in records)
