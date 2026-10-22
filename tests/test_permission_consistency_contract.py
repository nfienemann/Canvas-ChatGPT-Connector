import asyncio
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.app import create_app
from canvas_bridge.authorization import SCOPES
from canvas_bridge.course_files import list_files
from canvas_bridge.policy import Endpoint
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Store
from tests.conftest import seed
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency import course, stored_state


@asynccontextmanager
async def client_session(url, token):
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
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
        assert denied["data"] == {"reason_code": "CONNECTION_OWNERSHIP_MISMATCH"}
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
        assert result["data"] == {"reason_code": "COURSE_NOT_SELECTED"}
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
    bridge, owner, token_factory, tmp_path
):
    url = "sqlite:///" + (tmp_path / "restart-fixture.sqlite").as_posix()
    store = Store(url)
    store.create_fixture_schema()
    first = Bridge(bridge.settings, store, bridge.vault, bridge.registry, bridge.synthetic)
    ref = await seed(first, owner)
    snapshots = []
    try:
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
