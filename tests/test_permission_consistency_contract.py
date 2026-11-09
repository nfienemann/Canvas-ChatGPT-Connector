import asyncio
import socket
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.app import create_app
from canvas_bridge.authorization import SCOPES
from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.course_files import list_files
from canvas_bridge.domain import utcnow
from canvas_bridge.permission_recovery import DEFINITIONS
from canvas_bridge.policy import Endpoint
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Connection, Store
from tests.conftest import seed
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency import course, stored_state


@asynccontextmanager
async def client_session(url, token, *, read_timeout=30):
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token},
        # Contract tests verify response semantics, not a five-second latency
        # SLA. Keep connect bounded while allowing instrumented authorization.
        timeout=httpx.Timeout(read_timeout, connect=5),
    ) as http:
        async with streamable_http_client(url + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


@pytest.mark.contract
async def test_discoverable_readonly_schema_and_oct21_error_contract(
    running, bridge, owner, seeded, token_factory
):
    target = course(bridge, owner, seeded)
    before = stored_state(bridge)
    bridge.settings.mcp_read_only = True
    async with client_session(running, token_factory(scope="academic:read")) as session:
        catalog = await session.list_tools()
        assert {a.tool_name for a in DEFINITIONS.values() if a.tool_name} <= {
            t.name for t in catalog.tools
        }
        tool = next(t for t in catalog.tools if t.name == "audit_permission_consistency")
        assert tool.annotations.readOnlyHint and tool.annotations.idempotentHint
        assert not tool.annotations.destructiveHint
        assert set(tool.inputSchema["properties"]) == {
            "connection_id",
            "course_id",
            "resource_types",
            "include_upstream_checks",
        }
        assert tool.inputSchema["properties"]["include_upstream_checks"]["default"] is False
        assert "principal" not in tool.inputSchema["properties"]
        status = (await session.call_tool("get_connection_status")).structuredContent
        audit = (
            await session.call_tool("audit_permission_consistency", {"connection_id": seeded})
        ).structuredContent
        assert audit["status"] == "ok" and len(audit["data"]["checks"]) == 14
        assert (
            audit["data"]["scope_snapshot_version"]
            == status["data"]["connections"][0]["scope_snapshot_version"]
        )
        assert audit["data"]["correlation_id"] == status["data"]["connections"][0]["correlation_id"]
        assert stored_state(bridge) == before
        for tool_name in ("audit_permission_consistency", "list_course_files"):
            denied = (
                await session.call_tool(
                    tool_name, {"connection_id": seeded, "course_id": target.id[:-1]}
                )
            ).structuredContent
            assert denied["status"] == "permission_denied"
            if tool_name == "audit_permission_consistency":
                assert denied["data"]["checks"][0]["reason_code"] == "IDENTIFIER_MAPPING_FAILURE"
            else:
                assert denied["data"]["reason_code"] == "IDENTIFIER_MAPPING_FAILURE"
                assert "files" not in denied["data"]
        invalid = await session.call_tool(
            "audit_permission_consistency",
            {"connection_id": seeded, "resource_types": ["quiz_answers"]},
        )
        assert invalid.isError


@pytest.mark.contract
async def test_mcp_principal_is_authenticated_not_client_supplied(
    running, bridge, owner, seeded, token_factory
):
    target = course(bridge, owner, seeded)
    async with client_session(running, token_factory(sub="other-student")) as session:
        denied = (
            await session.call_tool(
                "audit_permission_consistency",
                {"connection_id": seeded, "course_id": target.id, "include_upstream_checks": True},
            )
        ).structuredContent
        assert denied["status"] == "permission_denied"
        assert set(denied["data"]) == {"reason_code", "diagnostic"}
        diagnostic = denied["data"]["diagnostic"]
        assert (
            diagnostic["code"] == denied["data"]["reason_code"] == "CONNECTION_OWNERSHIP_MISMATCH"
        )
        assert (
            diagnostic["category"] == "authorization" and diagnostic["content_delivery"] == "none"
        )
        assert diagnostic["request_id"] == denied["meta"]["request_id"]
        assert "upstream_http_status" not in diagnostic
        assert target.id not in json_text(denied) and target.name not in json_text(denied)


def json_text(value):
    import json

    return json.dumps(value)


@pytest.mark.contract
async def test_final_mcp_boundary_blocks_content_after_concurrent_deselection(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    target = course(bridge, owner, seeded)

    async def racing(*args, **kwargs):
        result = await list_files(*args, **kwargs)
        bridge.select_courses(owner, seeded, [], "UTC")
        return result

    monkeypatch.setattr("canvas_bridge.app.list_files", racing)
    async with client_session(running, token_factory()) as session:
        result = (
            await session.call_tool(
                "list_course_files", {"connection_id": seeded, "course_id": target.id}
            )
        ).structuredContent
        assert result["status"] == "permission_denied"
        assert set(result["data"]) == {"reason_code", "diagnostic"}
        diagnostic = result["data"]["diagnostic"]
        assert diagnostic["code"] == result["data"]["reason_code"] == "COURSE_NOT_SELECTED"
        assert (
            diagnostic["category"] == "authorization" and diagnostic["content_delivery"] == "none"
        )
        assert diagnostic["request_id"] == result["meta"]["request_id"]
        assert "upstream_http_status" not in diagnostic
        assert result["sources"] == []


@pytest.mark.contract
async def test_grade_denied_even_after_course_authorization(
    running, bridge, owner, seeded, token_factory
):
    target = course(bridge, owner, seeded)
    bridge.registry.entries["synthetic"].scopes = [SCOPES[Endpoint.COURSE]]
    async with client_session(running, token_factory()) as session:
        for name in ("get_gradebook", "audit_course_grade", "get_course_grading_policy"):
            result = (
                await session.call_tool(name, {"connection_id": seeded, "course_id": target.id})
            ).structuredContent
            assert result["status"] == "permission_denied"
            assert result["data"]["reason_code"] == "MISSING_RESOURCE_CAPABILITY"
            assert result["sources"] == []


@asynccontextmanager
async def restarted_server(bridge):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    bridge.settings.resource_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(create_app(bridge.settings, bridge), log_level="error", access_log=False)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    async with asyncio.timeout(10):
        while not server.started:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    try:
        yield bridge.settings.resource_url
    finally:
        server.should_exit = True
        await task
        sock.close()


@pytest.mark.contract
async def test_mcp_reconnect_after_server_restart_reads_persisted_scope(
    bridge, owner, token_factory, tmp_path, monkeypatch
):
    url = "sqlite:///" + (tmp_path / "restart-fixture.sqlite").as_posix()
    store = Store(url)
    store.create_fixture_schema()
    first = Bridge(bridge.settings, store, bridge.vault, bridge.registry, bridge.synthetic)
    ref = await seed(first, owner)
    snapshots = []
    try:
        checked_at = utcnow()
        monkeypatch.setattr("canvas_bridge.permission_audit.utcnow", lambda: checked_at)
        for iteration in range(2):
            if iteration:
                store.close()
                store = Store(url)
                first = Bridge(
                    bridge.settings, store, bridge.vault, bridge.registry, bridge.synthetic
                )
            async with restarted_server(first) as server_url:
                async with client_session(server_url, token_factory()) as session:
                    result = (
                        await session.call_tool(
                            "audit_permission_consistency", {"connection_id": ref}
                        )
                    ).structuredContent
                    assert result["status"] == "ok"
                    snapshots.append(result["data"])
        assert snapshots[0] == snapshots[1]
    finally:
        store.close()


@pytest.mark.contract
@pytest.mark.parametrize("outcome", ["complete", "partial", "revoked"])
async def test_follow_stale_lease_recovery_through_mcp(
    running, bridge, owner, seeded, token_factory, monkeypatch, outcome
):
    target = course(bridge, owner, seeded)
    args = {"connection_id": seeded, "course_id": target.id, "resource_types": ["files"]}
    with bridge.store.transaction() as db:
        db.get(Connection, seeded).entitlement_at = utcnow() - timedelta(hours=1)
    async with client_session(running, token_factory()) as session:

        async def call(name, arguments):
            result = await session.call_tool(name, arguments)
            assert not result.isError
            return result.structuredContent

        report = await call("audit_permission_consistency", args)
        (action,) = report["data"]["recovery_actions"]
        assert report["data"]["recommended_actions"] == [action["action_id"]]
        assert action["action_id"] == "refresh_course_list_then_retry"
        assert action["tool_name"] == "list_courses"

        if outcome == "partial":

            async def incomplete(*args, **kwargs):
                return Collection(reason_code="UPSTREAM_THROTTLED", retry_after_seconds=60)

            monkeypatch.setattr(CanvasClient, "collection", incomplete)
        elif outcome == "revoked":
            bridge.synthetic.data["courses"] = []
        listing = await call(action["tool_name"], {"connection_id": seeded})
        assert listing["status"] == ("partial_data" if outcome == "partial" else "ok")
        if outcome == "partial":
            assert listing["data"]["reason_code"] == "UPSTREAM_THROTTLED"
        audited = await call("audit_permission_consistency", args)
        (check,) = audited["data"]["checks"]
        assert check["scope_authorized"] is (outcome == "complete")
        if outcome == "complete":
            assert audited["data"]["recovery_actions"] == []
        elif outcome == "partial":
            assert check["recommended_action"] == action["action_id"]
        else:
            assert audited["status"] != "ok"
            assert check["reason_code"] in {"COURSE_NOT_SELECTED", "SELECTED_SCOPE_MISMATCH"}


@pytest.mark.contract
async def test_follow_scope_change_recovery_through_mcp(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    target = course(bridge, owner, seeded)
    original = CanvasClient.probe_metadata

    async def racing(client, resource, upstream):
        status = await original(client, resource, upstream)
        bridge.select_courses(owner, seeded, [], "UTC")
        bridge.select_courses(owner, seeded, [target.id], "UTC")
        return status

    monkeypatch.setattr(CanvasClient, "probe_metadata", racing)
    args = {
        "connection_id": seeded,
        "course_id": target.id,
        "resource_types": ["files"],
        "include_upstream_checks": True,
    }
    async with client_session(running, token_factory()) as session:
        tool = "audit_permission_consistency"
        for _ in range(2):
            response = (await session.call_tool(tool, args)).structuredContent
            assert response["status"] == "partial_data"
            (check,) = response["data"]["checks"]
            assert (check["course_id"], check["resource"]) == (target.id, "files")
            data = response["data"]
            assert (
                data["scope_evaluated_at"]
                <= check["scope_evaluated_at"]
                <= data["current_scope_evaluated_at"]
            )
            assert (
                check["scope_snapshot_version"]
                == data["scope_snapshot_version"]
                != data["current_scope_snapshot_version"]
            )
            assert (
                check["upstream_permission"] == "unknown" and check["upstream_http_status"] is None
            )
            (action,) = response["data"]["recovery_actions"]
            assert action["action_id"] == check["recommended_action"] == "repeat_permission_audit"
            assert "once" in action["instruction"] and "wait" in action["retry_condition"]
            tool = action["tool_name"]
            assert tool == "audit_permission_consistency"


@pytest.mark.contract
async def test_five_course_membership_clock_through_mcp(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    from canvas_bridge import authorization, permission_audit, service
    from canvas_bridge.storage import aware

    clock = utcnow()
    for module in (authorization, permission_audit, service):
        monkeypatch.setattr(module, "utcnow", lambda: clock)
    for identifier in range(13, 16):
        bridge.synthetic.data["courses"].append(
            dict(bridge.synthetic.data["courses"][0], id=identifier)
        )
    listed = await bridge.list_courses(owner, seeded)
    bridge.select_courses(
        owner, seeded, [c["id"] for c in listed.data["courses"]], "America/New_York"
    )
    await bridge.refresh(owner, seeded)
    clock += timedelta(seconds=301)
    async with client_session(running, token_factory()) as session:

        async def call(tool, args):
            returned = await session.call_tool(tool, args)
            assert not returned.isError
            return returned.structuredContent

        args = {"connection_id": seeded, "resource_types": ["files"]}
        before = await call("audit_permission_consistency", args)
        assert len(before["data"]["checks"]) == 5
        assert all(c["reason_code"] == "STALE_SCOPE_SNAPSHOT" for c in before["data"]["checks"])
        status = (await call("get_connection_status", {}))["data"]["connections"][0]
        listing = await call(
            before["data"]["recovery_actions"][0]["tool_name"], {"connection_id": seeded}
        )
        assert listing["data"]["membership_evidence_renewed"]
        after = await call("audit_permission_consistency", args)
        assert len({x["meta"]["request_id"] for x in [before, listing, after]}) == 3
        assert after["data"]["membership_lease_state"] == "within_lease"
        assert after["data"]["membership_evidence_at"] == clock.isoformat()
        assert after["data"]["scope_evaluated_at"] == clock.isoformat()
        assert after["data"]["scope_snapshot_version"] == before["data"]["scope_snapshot_version"]
        assert after["data"]["correlation_id"] == before["data"]["correlation_id"]
        current = (await call("get_connection_status", {}))["data"]["connections"][0]
        assert current["last_complete_assignment_refresh_at"] == status["last_successful_refresh"]
        with bridge.store.transaction() as db:
            row = db.get(Connection, seeded)
            assert (
                current["last_complete_course_list_at"]
                == aware(row.last_complete_course_list_at).isoformat()
            )


@pytest.mark.contract
async def test_workload_cursor_returns_original_snapshot_time(
    running, bridge, owner, seeded, token_factory
):
    args = {
        "connection_id": seeded,
        "start": utcnow().isoformat(),
        "end": (utcnow() + timedelta(days=7)).isoformat(),
        "timezone": "America/New_York",
        "limit": 1,
    }
    async with client_session(running, token_factory()) as session:
        first = (await session.call_tool("get_workload", args)).structuredContent["meta"]
        args["cursor"] = first["next_cursor"]
        assert args["cursor"]
        second = (await session.call_tool("get_workload", args)).structuredContent["meta"]
        assert second["freshness"] == "cached" and second["display_timezone"] == "America/New_York"
        assert second["workload_snapshot_created_at"] == first["workload_snapshot_created_at"]
        assert second["response_generated_at"] > first["response_generated_at"]
