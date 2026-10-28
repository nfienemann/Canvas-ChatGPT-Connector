import asyncio
import re
import socket
from datetime import timedelta

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.app import create_app
from canvas_bridge.domain import utcnow


@pytest.fixture
async def running(bridge, settings, seeded):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    settings.resource_url = f"http://127.0.0.1:{port}"
    app = create_app(settings, bridge)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    async with asyncio.timeout(10):
        while not server.started:  # noqa: ASYNC110 - uvicorn exposes a startup flag, not an event.
            await asyncio.sleep(0.01)
    try:
        yield settings.resource_url
    finally:
        server.should_exit = True
        await task
        sock.close()


@pytest.mark.contract
async def test_T12_T21_T36_real_http_mcp_read_and_write_scope(running, token_factory, seeded):
    async with httpx.AsyncClient() as client:
        denied = await client.post(
            running + "/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        )
        assert denied.status_code == 401
        assert "resource_metadata" in denied.headers["www-authenticate"]
        discovery = await client.get(running + "/.well-known/oauth-protected-resource")
        assert discovery.status_code == 200
        assert discovery.json()["resource"] == running
        assert discovery.json()["authorization_servers"] == ["https://fixture-issuer.invalid"]
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                catalog = await session.list_tools()
                names = {tool.name for tool in catalog.tools}
                assert {"get_workload", "propose_study_plan", "get_course_outline"} <= names
                assert (
                    not {
                        "apply_calendar_changes",
                        "send_notification",
                        "submit_assignment",
                        "http_proxy",
                        "link_personal_token",
                    }
                    & names
                )
                workload = await session.call_tool(
                    "get_workload",
                    {
                        "connection_id": seeded,
                        "start": utcnow().isoformat(),
                        "end": (utcnow() + timedelta(days=7)).isoformat(),
                        "timezone": "UTC",
                    },
                )
                assert not workload.isError
                assert workload.structuredContent["status"] == "ok"
                assert len(workload.structuredContent["data"]["items"]) == 5
                saved = await session.call_tool(
                    "update_study_preferences",
                    {
                        "connection_id": seeded,
                        "expected_version": 0,
                        "preferences": {"timezone": "UTC"},
                    },
                )
                assert saved.structuredContent["status"] == "permission_denied"
                for tool in catalog.tools:
                    if tool.name == "update_study_preferences":
                        assert tool.annotations.readOnlyHint is False
                    assert "student_id" not in tool.inputSchema.get("properties", {})


@pytest.mark.contract
async def test_T19_T43_settings_flow_csrf_and_disconnect(running, bridge, token_factory, seeded):
    bridge.settings.local_jwks_file.with_name("demo-token").write_text(token_factory())
    async with httpx.AsyncClient(base_url=running, follow_redirects=True) as client:
        home = await client.get("/settings")
        assert 'lang="en"' in home.text and "Open synthetic settings" in home.text
        assert home.headers["cache-control"] == "no-store"
        csrf = re.search(r'name="csrf" value="([^"]+)"', home.text)[1]
        # Browser POSTs under Referrer-Policy: no-referrer can send Origin: null.
        login = await client.post(
            "/settings/demo",
            data={"csrf": csrf},
            headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
        )
        assert "Selected courses" in login.text
        assert "HttpOnly" in client.cookies.jar._cookies["127.0.0.1"]["/"]["bridge_session"]._rest
        csrf = re.search(r'name="csrf" value="([^"]+)"', login.text)[1]
        forged = await client.post(
            "/settings/disconnect",
            data={
                "connection": seeded,
                "csrf": "forged",
            },
            headers={"Origin": running},
        )
        assert forged.status_code == 403
        result = await client.post(
            "/settings/disconnect",
            data={
                "connection": seeded,
                "csrf": csrf,
            },
            headers={"Origin": running},
        )
        assert result.status_code == 200
        assert "Local access disabled" in result.text


@pytest.mark.contract
async def test_T21_T38_personal_browser_and_mcp_reject_other_users_and_public_linking(
    running, bridge, token_factory, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient

    provider = bridge.synthetic
    bridge.settings.local_jwks_file.with_name("demo-token").write_text(token_factory())
    async with httpx.AsyncClient(base_url=running, follow_redirects=True) as client:
        home = await client.get("/settings")
        csrf = re.search(r'name="csrf" value="([^"]+)"', home.text)[1]
        login = await client.post(
            "/settings/demo", data={"csrf": csrf}, headers={"Origin": running}
        )
        assert "Selected courses" in login.text
        from tests.approval_fixtures import install_approvals

        install_approvals(bridge)
        bridge.settings.profile = "personal"
        bridge.settings.live_access_enabled = True  # Fictional approved provider only.
        bridge.settings.personal_subject = "student-one"
        bridge.registry.entries["synthetic"].status = "personal_testing"
        bridge.synthetic = None

        def fixture_client(institution, token, settings, *args):
            result = CanvasClient(institution, token, settings, http=provider.client())
            result.owns_http = True
            return result

        monkeypatch.setattr("canvas_bridge.service.CanvasClient", fixture_client)
        settings = await client.get("/settings")
        assert "Private developer test" in settings.text
        assert "Selected courses" in settings.text
        assert 'action="/settings/link"' not in settings.text
        assert 'name="token"' not in settings.text
        csrf = re.search(r'name="csrf" value="([^"]+)"', settings.text)[1]
        denied = await client.post(
            "/settings/link",
            data={"csrf": csrf, "institution": "synthetic"},
            headers={"Origin": running},
        )
        assert denied.status_code == 403
        assert "operator-only" in denied.text
        denied = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer " + token_factory(sub="another-student")},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert denied.status_code == 401


@pytest.mark.contract
async def test_T18_T19_delete_account_requires_confirmation_and_revokes_session(
    running, bridge, token_factory, seeded
):
    bridge.settings.local_jwks_file.with_name("demo-token").write_text(token_factory())
    async with httpx.AsyncClient(base_url=running, follow_redirects=True) as client:
        home = await client.get("/settings")
        csrf = re.search(r'name="csrf" value="([^"]+)"', home.text)[1]
        login = await client.post(
            "/settings/demo", data={"csrf": csrf}, headers={"Origin": running}
        )
        csrf = re.search(r'name="csrf" value="([^"]+)"', login.text)[1]
        unconfirmed = await client.post(
            "/settings/delete-account", data={"csrf": csrf}, headers={"Origin": running}
        )
        assert unconfirmed.status_code == 403
        result = await client.post(
            "/settings/delete-account",
            data={"csrf": csrf, "confirm": "delete"},
            headers={"Origin": running},
        )
        assert result.status_code == 200 and "All local account records deleted" in result.text
        assert "bridge_session" not in client.cookies
        replay = await client.post(
            "/settings/delete-account",
            data={"csrf": csrf, "confirm": "delete"},
            headers={"Origin": running},
        )
        assert replay.status_code == 403
