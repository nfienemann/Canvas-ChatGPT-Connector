"""Wire-level auth evidence. All keys, names and provider responses are fixtures."""

import asyncio
import re
from unittest.mock import AsyncMock

import httpx
import pytest

from canvas_bridge.app import create_app
from canvas_bridge.auth import JWTVerifier
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session

MARKER = "private-fixture-must-not-escape"


async def test_sdk_challenges_are_request_local(settings, bridge, token_factory, caplog):
    app = create_app(settings, bridge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=settings.resource_url
    ) as client:

        async def check(raw, code):
            headers = {"Authorization": "Bearer " + raw} if raw else {}
            headers["X-Bridge-Request-ID"] = MARKER
            denied = await client.post("/mcp", headers=headers, json={})
            assert denied.status_code == 401
            assert "resource_metadata" in denied.headers["www-authenticate"]
            assert denied.json()["error"] == "invalid_token"
            auth = denied.json()["diagnostic"]["authentication_diagnostic"]
            ident = denied.headers["x-bridge-request-id"]
            assert auth["correlation_id"] == ident and re.fullmatch("[0-9a-f]{32}", ident)
            assert auth["code"] == code and auth["canvas_reached"] == "no"
            assert auth["canvas_authentication"] == "not_checked"
            assert MARKER not in denied.text and (not raw or raw not in denied.text)
            return ident

        inputs = [
            (None, "MCP_CREDENTIAL_MISSING"),
            (MARKER, "MCP_CREDENTIAL_REJECTED"),
            (token_factory(exp=1), "MCP_TOKEN_EXPIRED"),
            (token_factory(aud=MARKER), "MCP_AUDIENCE_MISMATCH"),
            (token_factory(iss=MARKER), "MCP_ISSUER_MISMATCH"),
            (token_factory(scope="offline_access"), "MCP_SCOPE_DENIED"),
        ]
        ids = await asyncio.gather(*(check(*case) for case in inputs))
        assert len(set(ids)) == len(inputs)
        assert MARKER not in caplog.text


async def test_outage_preserves_challenge(settings, bridge, token_factory, monkeypatch):
    monkeypatch.setattr(JWTVerifier, "_keys", AsyncMock(side_effect=httpx.ConnectError(MARKER)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": "Bearer " + token_factory()})
        auth = response.json()["diagnostic"]["authentication_diagnostic"]
        assert response.status_code == 401 and "www-authenticate" in response.headers
        assert auth["failure_layer"] == "authentication_service"
        assert auth["mcp_authentication"] == "unknown" and auth["retry"] == "after_delay_once"
        assert MARKER not in response.text


@pytest.mark.parametrize(
    "subject,expected",
    [("student-one", "CONNECTION_STATUS_CHECKED"), ("another-owner", "CANVAS_CONNECTION_MISSING")],
)
async def test_fresh_status_is_local(running, token_factory, subject, expected):
    async with client_session(running, token_factory(sub=subject)) as client:
        response = await client.call_tool("get_connection_status", {})
        payload = response.structuredContent
        auth = payload["data"]["authentication_diagnostic"]
        assert auth["correlation_id"] == payload["meta"]["request_id"]
        assert auth["code"] == expected and auth["canvas_reached"] == "no"
        assert auth["mcp_authentication"] == auth["bridge_authorization"] == "passed"
        assert auth["canvas_authorization"] == auth["canvas_authentication"] == "not_checked"


@pytest.mark.parametrize(
    "status,headers,expected,action",
    [
        (401, {}, "UNKNOWN_AUTHORIZATION_FAILURE", "contact_operator"),
        (
            401,
            {"WWW-Authenticate": 'Bearer error="invalid_token"'},
            "UPSTREAM_CREDENTIAL_REJECTED",
            "review_secure_canvas_setup",
        ),
        (
            403,
            {"WWW-Authenticate": 'Bearer error_description="private-fixture-must-not-escape"'},
            "RESOURCE_PERMISSION_DENIED",
            "review_resource_permission",
        ),
        (
            403,
            {"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
            "UPSTREAM_SCOPE_INSUFFICIENT",
            "review_resource_permission",
        ),
        (429, {"Retry-After": "2"}, "UPSTREAM_THROTTLED", "wait_or_contact_operator"),
        (503, {}, "UPSTREAM_UNAVAILABLE", "wait_or_contact_operator"),
    ],
)
async def test_canvas_failure_stays_in_tool_result(
    running, bridge, token_factory, monkeypatch, status, headers, expected, action
):
    from canvas_bridge.canvas import upstream_error

    def fail(owner):
        raise upstream_error(status, httpx.Headers(headers))

    # Fault injection at tool execution with the production Canvas response classifier.
    monkeypatch.setattr(bridge, "connection_status", fail)
    async with httpx.AsyncClient(base_url=running) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer " + token_factory(),
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_connection_status", "arguments": {}},
            },
        )
        assert response.status_code == 200 and "www-authenticate" not in response.headers
        result = response.json()["result"]
        assert "mcp/www_authenticate" not in str(result) and MARKER not in response.text
        auth = result["structuredContent"]["data"]["diagnostic"]["authentication_diagnostic"]
        assert auth["code"] == expected and auth["recovery_action"] == action
        assert auth["canvas_reached"] == "yes" and auth["bridge_authorization"] == "passed"
        assert auth["correlation_id"] == response.headers["x-bridge-request-id"]


async def test_mapping_is_indistinguishable_from_unavailable(running, token_factory, seeded):
    async with client_session(running, token_factory(sub="another-owner")) as client:
        for ref in (seeded, "f" * 32):
            result = await client.call_tool("list_courses", {"connection_id": ref})
            auth = result.structuredContent["data"]["diagnostic"]["authentication_diagnostic"]
            assert (
                auth["failure_layer"] == "account_mapping"
                and auth["recovery_action"] == "select_correct_account"
            )
            assert ref not in result.model_dump_json()


async def test_missing_provenance_is_unknown():
    from canvas_bridge.auth_diagnostics import tool_observation
    from canvas_bridge.failure_diagnostics import Attempt

    auth = tool_observation("RESOURCE_PERMISSION_DENIED", 403, Attempt(), {})
    assert auth.code == "AUTH_ORIGIN_UNKNOWN" and auth.canvas_reached == "unknown"


async def test_key_outage_is_single_flight(settings, token_factory, monkeypatch):
    from pathlib import Path

    original_read = Path.read_text
    calls = 0

    def unavailable(path, *args, **kwargs):
        nonlocal calls
        if path == settings.local_jwks_file:
            calls += 1
            raise OSError(MARKER)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unavailable)
    verifier = JWTVerifier(settings)
    raw = token_factory()
    assert await asyncio.gather(*(verifier.verify_token(raw) for _ in range(12))) == [None] * 12
    assert calls == 1


@pytest.mark.parametrize("tool", ["audit_permission_consistency", "list_courses"])
async def test_returned_collection_failure_preserves_coverage(
    running, bridge, owner, seeded, token_factory, tool, monkeypatch
):
    from tests.test_permission_consistency import course

    target = course(bridge, owner, seeded)
    args = {"connection_id": seeded}
    if tool == "audit_permission_consistency":
        args.update(
            course_id=target.id, resource_types=["files", "modules"], include_upstream_checks=True
        )
    monkeypatch.setattr(
        bridge.synthetic,
        "handle",
        lambda req: httpx.Response(
            401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ),
    )
    async with client_session(running, token_factory()) as client:
        result = (await client.call_tool(tool, args)).structuredContent
        assert result["status"] == "reconnect_required"
        auth = result["data"]["authentication_diagnostic"]
        assert auth["code"] == "UPSTREAM_CREDENTIAL_REJECTED"
        assert auth["correlation_id"] == result["meta"]["request_id"]
        if tool == "audit_permission_consistency":
            assert result["data"]["checks"][1]["result"] == "not_checked"
        else:
            assert not result["data"]["courses"]
