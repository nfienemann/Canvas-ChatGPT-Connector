"""Actual local MCP/HTTP transport, fictional data and signed test approvals only."""

import json

import httpx
import pytest

from canvas_bridge.policy_surfaces import OFFLINE_TOOLS, TOOL_CATEGORIES
from tests.approval_fixtures import install_approvals
from tests.egress_fixtures import install_governance, recipient_claims
from tests.test_approval_policy import live_fixture
from tests.test_file_delivery import original as original
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


@pytest.mark.contract
async def test_all_mcp_surfaces_classified_and_no_approval_mutation(running, token_factory, bridge):
    from canvas_bridge.processes.surfaces import TOOLS as PROCESS_TOOLS

    async with client_session(running, token_factory()) as session:
        tools = (await session.list_tools()).tools
        expected = set(TOOL_CATEGORIES) | OFFLINE_TOOLS
        if not bridge.settings.process_features_enabled:
            expected -= PROCESS_TOOLS
        assert {tool.name for tool in tools} == expected
        for tool in tools:
            properties = tool.inputSchema.get("properties", {})
            assert (
                not {"approval", "policy", "recipient", "administrator", "provider_authorization"}
                & properties.keys()
            )


@pytest.mark.contract
async def test_cached_live_tools_and_alternate_readers_deny_without_network(
    running, token_factory, bridge, seeded, owner
):
    async with client_session(running, token_factory()) as session:
        live_fixture(bridge)
        before = len(bridge.synthetic.requests)
        calls = [
            ("list_courses", {}),
            ("get_saved_study_state", {"include_institutional": True}),
            ("get_course_outline", {"course_id": "fixture"}),
            ("get_gradebook", {"course_id": "fixture"}),
            ("audit_permission_consistency", {"include_upstream_checks": True}),
            ("fetch_course_material", {"material_id": "fixture"}),
            ("read_course_file", {"file_id": "fixture"}),
            ("prepare_course_file_download", {"file_id": "fixture"}),
            ("get_course_file_download_payload", {"delivery_id": "fixture"}),
        ]
        for name, args in calls:
            response = await session.call_tool(name, {"connection_id": seeded, **args})
            assert response.structuredContent["status"] == "permission_denied", (name, response)
            assert response.structuredContent["data"]["reason_code"] == "APPROVAL_NOT_ASSESSED"
        status = (await session.call_tool("get_connection_status")).structuredContent
        assert status["data"]["connections"][0]["live_integration"] == "disabled"
        assert "selected_courses" not in status["data"]["connections"][0]
        preferences = await session.call_tool(
            "update_study_preferences",
            {
                "connection_id": seeded,
                "preferences": {"timezone": "UTC"},
                "expected_version": 0,
            },
        )
        assert preferences.structuredContent["status"] == "ok"
        assert len(bridge.synthetic.requests) == before


@pytest.mark.contract
async def test_approval_revoked_after_tool_runs_suppresses_response(
    running, token_factory, bridge, seeded, monkeypatch
):
    async with client_session(running, token_factory()) as session:
        approvals = install_approvals(bridge)
        live_fixture(bridge)
        real_list = bridge.list_courses

        async def revoke_after_read(*args):
            result = await real_list(*args)
            approvals.records[0]["state"] = "REVOKED"
            approvals.save()
            return result

        monkeypatch.setattr(bridge, "list_courses", revoke_after_read)
        response = await session.call_tool("list_courses", {"connection_id": seeded})
        data = response.structuredContent
        assert (
            data["status"] == "permission_denied"
            and data["data"]["reason_code"] == "APPROVAL_REVOKED"
        )
        assert "courses" not in data["data"]
        assert "CONFIDENTIAL-FICTIONAL-REFERENCE" not in json.dumps(data)


@pytest.mark.contract
@pytest.mark.parametrize("client_id", [None, "unreviewed-client"])
async def test_signed_token_does_not_identify_an_approved_recipient(
    running, token_factory, bridge, seeded, client_id
):
    async with client_session(running, token_factory(azp=client_id)) as session:
        install_approvals(bridge)
        live_fixture(bridge)
        before = len(bridge.synthetic.requests)
        response = await session.call_tool("list_courses", {"connection_id": seeded})
        assert response.structuredContent["status"] == "permission_denied"
        assert response.structuredContent["data"]["reason_code"] == "APPROVAL_SCOPE_MISMATCH"
        assert len(bridge.synthetic.requests) == before
        status = (await session.call_tool("get_connection_status")).structuredContent
        assert "selected_courses" not in status["data"]["connections"][0]


@pytest.mark.contract
async def test_http_download_recipient_and_revocation_are_enforced(
    running, token_factory, bridge, seeded, owner, original
):
    _, file_id, contents = original
    access_token = token_factory(**recipient_claims())
    async with client_session(running, access_token) as session:
        approvals = install_approvals(bridge)
        live_fixture(bridge)
        await bridge.original_files.prepare(owner, seeded, file_id)
        install_governance(bridge, approvals, review_materials=True)
        prepared = await session.call_tool(
            "prepare_course_file_download",
            {
                "connection_id": seeded,
                "file_id": file_id,
            },
        )
        assert prepared.structuredContent["status"] == "ok"
        delivery_id = prepared.structuredContent["data"]["delivery_id"]
        payload = await session.call_tool(
            "get_course_file_download_payload",
            {
                "connection_id": seeded,
                "delivery_id": delivery_id,
            },
        )
        assert payload.meta["canvas_bridge_download"]["external_url"] is None
        url = running + "/course-file-original/" + delivery_id
        approvals.records[2]["recipients"] = ["local", "chatgpt"]
        approvals.save()
        async with httpx.AsyncClient() as http:
            denied = await http.get(url, headers={"Authorization": "Bearer " + access_token})
        assert denied.status_code == 403 and denied.content != contents
        assert denied.json()["reason_code"] == "APPROVAL_SCOPE_MISMATCH"
        approvals.records[0]["state"] = "REVOKED"
        approvals.save()
        payload = await session.call_tool(
            "get_course_file_download_payload",
            {
                "connection_id": seeded,
                "delivery_id": delivery_id,
            },
        )
        assert payload.structuredContent["data"]["reason_code"] == "APPROVAL_REVOKED"
        assert not payload.meta
