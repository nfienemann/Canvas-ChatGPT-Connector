"""Fault injection at the installed MCP dispatch boundary, using only synthetic inputs."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp import types

from canvas_bridge import egress_transport, failure_events
from canvas_bridge.domain import DomainError
from canvas_bridge.failure_diagnostics import current
from canvas_bridge.integrity.models import Activity, AssistanceRequest, Scope
from canvas_bridge.privacy.transport import receipts
from tests.test_integrity_workflows import imported
from tests.test_mcp_contract import running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally

pytestmark = pytest.mark.usefixtures("parsed_locally")

MARKER = "PRIVATE_SYNTHETIC_DO_NOT_RELEASE"
CHECK = "check_academic_assistance_permission"
PREPARE = "prepare_academic_assistance"


@pytest.fixture
async def server(settings, bridge, seeded, monkeypatch):
    # Wrap the installed SDK handler before the production fence freezes it.
    fault = SimpleNamespace(mode=None)
    fence = egress_transport.fence_mcp_outputs

    def install(mcp, engine):
        handlers = mcp._mcp_server.request_handlers
        original = handlers[types.CallToolRequest]

        async def inject(req):
            if req.params.name not in {CHECK, PREPARE} or fault.mode is None:
                return await original(req)
            if fault.mode == "ambiguous_401":
                from canvas_bridge.canvas import upstream_error

                raise upstream_error(401, {})
            if fault.mode in {"access", "unavailable", "expired"}:
                from httpx import Headers

                from canvas_bridge.canvas import upstream_error

                raise upstream_error(
                    {"access": 403, "unavailable": 404, "expired": 401}[fault.mode],
                    Headers({"WWW-Authenticate": 'Bearer error="invalid_token"'}),
                )
            if fault.mode == "upstream":
                from canvas_bridge.canvas import upstream_error

                raise upstream_error(403, {"Retry-After": "17"}, throttled=True)
            if fault.mode == "cooldown":
                raise DomainError(
                    "retry_later",
                    MARKER,
                    reason_code="UPSTREAM_THROTTLED",
                    details={"retry_after_seconds": 23, "blocking_scope": "cooldown"},
                )
            if fault.mode == "conversion":
                raise DomainError(
                    "retry_later",
                    MARKER,
                    reason_code="DOCUMENT_WORKER_TIMEOUT",
                    details={"timeout_stage": "pptx_conversion", "elapsed_ms": 1234},
                )
            if fault.mode == "throw":
                raise RuntimeError(MARKER)
            if fault.mode == "sdk":
                return types.ServerResult(
                    types.CallToolResult(
                        isError=True, content=[types.TextContent(type="text", text=MARKER)]
                    )
                )
            if fault.mode == "invalid":
                return object()
            if fault.mode == "unknown":
                raise DomainError("retry_later", MARKER, reason_code="EGRESS_" + MARKER)
            if fault.mode == "domain":
                raise DomainError("retry_later", MARKER, reason_code="UPSTREAM_THROTTLED")
            result = await original(req)
            if fault.mode == "typed_sdk":
                return types.ServerResult(
                    types.CallToolResult(
                        isError=True, content=[types.TextContent(type="text", text=MARKER)]
                    )
                )
            if fault.mode == "missing":
                receipts.get().clear()
            elif fault.mode == "mismatch":
                result.root.content.append(types.TextContent(type="text", text=MARKER))
            return result

        handlers[types.CallToolRequest] = inject
        fence(mcp, engine)

    monkeypatch.setattr(egress_transport, "fence_mcp_outputs", install)
    async for url in running.__wrapped__(bridge, settings, seeded):
        yield url, fault


@pytest.mark.contract
async def test_synthetic_reader_and_assistance_boundaries(
    server, bridge, owner, token_factory, caplog, monkeypatch
):
    url, fault = server
    bridge.settings.egress_mode = "permissive"
    doc = await imported(bridge, owner, "Fictional notes on diffusion across a membrane.")
    args = {
        "request": AssistanceRequest(
            scope=Scope(document_ids=[doc]), activity=Activity.BRAINSTORM
        ).model_dump(mode="json")
    }
    ids = set()
    async with client_session(url, token_factory()) as client:
        read = await client.call_tool("read_local_document", {"document_id": doc})
        assert "diffusion across a membrane" in read.model_dump_json()
        for mode, code in [
            ("ambiguous_401", "UNKNOWN_AUTHORIZATION_FAILURE"),
            ("access", "RESOURCE_PERMISSION_DENIED"),
            ("unavailable", "RESOURCE_UNAVAILABLE"),
            ("expired", "UPSTREAM_CREDENTIAL_REJECTED"),
            ("upstream", "UPSTREAM_THROTTLED"),
            ("cooldown", "UPSTREAM_THROTTLED"),
            ("conversion", "DOCUMENT_WORKER_TIMEOUT"),
            ("missing", "RESPONSE_INSPECTION_RECEIPT_MISSING"),
            ("mismatch", "RESPONSE_INSPECTION_RECEIPT_MISMATCH"),
            ("sdk", "TOOL_RESULT_FAILED"),
            ("invalid", "TOOL_RESPONSE_INVALID"),
            ("throw", "TOOL_EXECUTION_FAILED"),
            ("domain", "UPSTREAM_THROTTLED"),
            ("unknown", "UNCLASSIFIED_FAILURE"),
        ]:
            fault.mode = mode
            results = await asyncio.gather(
                *(client.call_tool(name, args) for name in (CHECK, PREPARE))
            )
            for name, response in zip((CHECK, PREPARE), results, strict=True):
                payload = response.structuredContent
                diagnostic = payload["data"]["diagnostic"]
                ident = diagnostic["request_id"]
                assert ident == payload["meta"]["request_id"] and ident not in ids
                ids.add(ident)
                assert diagnostic["requested_operation"] == name
                assert diagnostic["code"] == code
                assert diagnostic["sanitized_error_release"] == "allow"
                assert diagnostic["content_delivery"] == "none"
                if mode in {"access", "expired", "ambiguous_401", "upstream"}:
                    auth = diagnostic["authentication_diagnostic"]
                    assert auth["correlation_id"] == ident and auth["canvas_reached"] == "yes"
                    assert auth["observation_source"] == "canvas_response"
                    assert auth["failure_layer"] == "canvas_api"
                    assert auth["attribution"] == (
                        "unknown" if mode == "ambiguous_401" else "confirmed"
                    )
                if mode == "ambiguous_401":
                    assert (
                        diagnostic["origin"] == "canvas_api"
                        and diagnostic["certainty"] == "unknown"
                    )
                    assert diagnostic["upstream_http_status"] == 401
                    assert payload["status"] == "operation_failed"
                if mode in {"access", "unavailable", "expired"}:
                    assert diagnostic["category"] == "upstream"
                    assert (
                        diagnostic["upstream_http_status"]
                        == {"access": 403, "unavailable": 404, "expired": 401}[mode]
                    )
                    assert diagnostic["next_action"] == (
                        "reconnect_then_refresh"
                        if mode == "expired"
                        else "check_resource_access_in_canvas"
                    )
                if mode == "upstream":
                    assert diagnostic["upstream_http_status"] == 403
                    assert diagnostic["retry_after_seconds"] == 17
                    assert diagnostic["blocking_scope"] == "provider_capacity"
                if mode == "cooldown":
                    assert diagnostic["retry_after_seconds"] == 23
                    assert diagnostic["blocking_scope"] == "cooldown"
                    assert "upstream_http_status" not in diagnostic
                if mode == "conversion":
                    assert diagnostic["stage"] == "pptx_conversion"
                    assert diagnostic["elapsed_ms"] == 1234
                    assert diagnostic["operation_state"] == "unknown"
                if mode == "unknown":
                    assert (
                        diagnostic["certainty"] == "unknown" and diagnostic["category"] == "unknown"
                    )
                if mode == "throw":
                    assert diagnostic["requested_content_policy"] == "not_evaluated"
                    assert diagnostic["category"] == "internal"
                    assert payload["status"] == "operation_failed"
                assert payload["meta"]["egress"]["reason_code"] == "EGRESS_PERMISSIVE_MODE"
                events = list(failure_events.lookup(failure_events.journal(bridge.settings), ident))
                assert events[-1]["code"] == code
                assert MARKER not in response.model_dump_json() + json.dumps(events)
        # SDK normalization can discard a typed error block. Only the independently
        # inspected server-local projection is eligible for reconstruction.
        with monkeypatch.context() as patch:
            patch.setattr(
                bridge.integrity,
                "check",
                AsyncMock(
                    side_effect=DomainError("retry_later", MARKER, reason_code="UPSTREAM_THROTTLED")
                ),
            )
            fault.mode = "typed_sdk"
            typed = await client.call_tool(CHECK, args)
            assert typed.structuredContent["data"]["diagnostic"]["code"] == "UPSTREAM_THROTTLED"
            assert MARKER not in typed.model_dump_json()
        fault.mode = None
        with monkeypatch.context() as patch:
            from canvas_bridge.privacy import transport

            original_finalize = transport.finalize

            def unexpected_block(returned, **kwargs):
                if current.get().diagnostic is None:
                    returned = types.CallToolResult(
                        structuredContent=returned.model_dump(mode="json"),
                        content=[types.TextContent(type="text", text=MARKER)],
                    )
                return original_finalize(returned, **kwargs)

            patch.setattr(transport, "finalize", unexpected_block)
            rejected = await client.call_tool(CHECK, args)
            assert (
                rejected.structuredContent["data"]["diagnostic"]["code"]
                == "PRIVACY_OUTPUT_UNVERIFIED"
            )
            assert rejected.structuredContent["status"] == "permission_denied"
            assert MARKER not in rejected.model_dump_json()
        fault.mode = None
        unknown = await client.call_tool(MARKER, {})
        assert unknown.structuredContent["data"]["diagnostic"]["requested_operation"] is None
        invalid = await client.call_tool(
            CHECK,
            {"request": {"activity": {"value": MARKER}, "scope": {"local_course": "fixture"}}},
        )
        assert invalid.structuredContent["data"]["diagnostic"]["code"] == "TOOL_INPUT_INVALID"
        assert MARKER not in unknown.model_dump_json() + invalid.model_dump_json()
        fault.mode = "throw"
        monkeypatch.setattr(
            failure_events, "append_event", lambda *_: (_ for _ in ()).throw(OSError(MARKER))
        )
        assert (await client.call_tool(CHECK, args)).structuredContent["data"]["diagnostic"][
            "code"
        ] == "TOOL_EXECUTION_FAILED"
        monkeypatch.setattr(
            bridge.egress, "safe_error", lambda *_: (_ for _ in ()).throw(ValueError(MARKER))
        )
        emergency = await client.call_tool(CHECK, args)
        assert emergency.isError and emergency.structuredContent is None
        assert (
            "Report request" in emergency.content[0].text
            and MARKER not in emergency.model_dump_json()
        )
    assert MARKER not in caplog.text


@pytest.mark.contract
async def test_stale_read_retries_once_under_one_request(
    server, bridge, seeded, owner, token_factory, monkeypatch
):
    url, _ = server
    course = bridge.selected(owner, seeded)[1][0].id
    attempts = []

    async def stale(*args):
        attempts.append((current.get().request_id, current.get().attempt_id))
        raise DomainError("permission_denied", MARKER, reason_code="STALE_SCOPE_SNAPSHOT")

    # The real gradebook always refreshes membership before fetching grades.
    refresh = AsyncMock(side_effect=stale)
    monkeypatch.setattr(bridge, "refresh_course_access", refresh)
    async with client_session(url, token_factory()) as client:
        result = await client.call_tool(
            "get_gradebook", {"connection_id": seeded, "course_id": course}
        )
    assert len(attempts) == 2 and attempts[0][1] != attempts[1][1]
    assert attempts[0][0] == attempts[1][0] == result.structuredContent["meta"]["request_id"]
    assert result.structuredContent["data"]["diagnostic"]["code"] == "STALE_SCOPE_SNAPSHOT"
    assert refresh.await_count == 2  # Initial read and exactly one recovery attempt.


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("oversized", "BUFFERED_OUTPUT_TOO_LARGE"),
        ("malformed", "TRANSPORT_FAILED"),
        ("bad_request", "PROTOCOL_INPUT_INVALID"),
        ("stream", "TRANSPORT_FAILED"),
    ],
)
async def test_http_transport_reports_actual_delivery(mode, expected, bridge):
    ids = []
    sent = []

    async def application(scope, receive, send):
        ids.append(current.get().request_id)
        await send(
            {
                "type": "http.response.start",
                "status": 400 if mode == "bad_request" else 200,
                "headers": [
                    (
                        b"content-type",
                        b"text/event-stream" if mode == "stream" else b"application/json",
                    )
                ],
            }
        )
        if mode == "stream":
            await send(
                {"type": "http.response.body", "body": b"synthetic content", "more_body": True}
            )
            raise OSError(MARKER)
        body = {
            "oversized": b"x" * 4_000_001,
            "malformed": MARKER.encode(),
            "bad_request": json.dumps(
                {"jsonrpc": "2.0", "id": "rpc-id", "error": {"code": -32602, "data": MARKER}}
            ).encode(),
        }[mode]
        await send({"type": "http.response.body", "body": body})

    app = egress_transport.McpErrorEgressMiddleware(application, bridge.egress)

    async def capture(message):
        sent.append(message)

    scope = {"type": "http", "path": "/mcp"}
    if mode == "stream":
        with pytest.raises(RuntimeError, match="interrupted"):
            await app(scope, None, capture)
        assert len(sent) == 2
    else:
        await app(scope, None, capture)
        payload = json.loads(sent[-1]["body"])
        assert MARKER not in str(payload)
        assert payload["error"]["data"]["diagnostic"]["code"] == expected
        assert payload["error"]["data"]["diagnostic"]["request_id"] == ids[0]
        if mode == "bad_request":
            assert payload["id"] == "rpc-id"
    (event,) = failure_events.lookup(failure_events.journal(bridge.settings), ids[0])
    assert event["content_delivery"] == ("unknown" if mode == "stream" else "none")
    assert event["code"] == expected


def test_failure_event_retention_and_size_limits(tmp_path, bridge, monkeypatch):
    from datetime import timedelta

    from canvas_bridge.domain import utcnow

    root = tmp_path / "journal"
    old = utcnow() - timedelta(days=8)
    monkeypatch.setattr(failure_events, "utcnow", lambda: old)
    failure_events.append_event(root, {"request_id": "0" * 32, "timestamp": old.isoformat()})
    monkeypatch.setattr(failure_events, "utcnow", utcnow)
    failure_events.expire_events(root)
    assert not failure_events.segments(root)
    monkeypatch.setattr(failure_events, "MAX_BYTES", 500)
    monkeypatch.setattr(failure_events, "SEGMENT_BYTES", 180)
    for _ in range(12):
        failure_events.append_event(
            root, {"request_id": "0" * 32, "timestamp": utcnow().isoformat()}
        )
    assert sum(p.stat().st_size for p in failure_events.segments(root)) <= 500


@pytest.mark.contract
async def test_sdk_envelope_validation_redacts_default_logs(server, token_factory, caplog, bridge):
    url, _ = server
    # Valid JSON-RPC, invalid MCP params. The installed SDK logs its ValidationError
    # to the root logger before any registered handler receives this request.
    headers = {
        "Authorization": "Bearer " + token_factory(),
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(headers=headers) as client:
        response = await client.post(
            url + "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": "caller-id",
                "method": "tools/call",
                "params": {"name": {"secret": MARKER}},
            },
        )
    payload = response.json()
    assert payload["id"] == "caller-id"
    diagnostic = payload["error"]["data"]["diagnostic"]
    assert diagnostic["code"] == "PROTOCOL_INPUT_INVALID"
    assert diagnostic["request_id"] != "caller-id" and diagnostic["requested_operation"] is None
    events = list(
        failure_events.lookup(failure_events.journal(bridge.settings), diagnostic["request_id"])
    )
    assert events and MARKER not in response.text + caplog.text + json.dumps(events)


def test_asgi_exception_logger_drops_traceback_after_context_reset(caplog):
    import logging

    from canvas_bridge.domain import opaque_id
    from canvas_bridge.failure_diagnostics import StreamInterrupted

    egress_transport.protect_sdk_logs()
    ident = opaque_id()
    try:
        raise StreamInterrupted(ident)
    except StreamInterrupted:
        logging.getLogger("uvicorn.error").exception(MARKER)
    entry = caplog.records[-1]
    assert entry.exc_info is None and ident in entry.getMessage() and MARKER not in caplog.text


@pytest.mark.parametrize("malformed", [True, False])
async def test_final_http_bytes_must_match_reviewed_result(bridge, malformed):
    from canvas_bridge.privacy.transport import payload_digest

    async def changed_after_sdk(scope, receive, send):
        current.get().wire_digest = payload_digest({"content": []})
        payload = (
            [MARKER]
            if malformed
            else {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": MARKER}]},
            }
        )
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(payload).encode()})

    sent = []

    async def capture(msg):
        sent.append(msg)

    app = egress_transport.McpErrorEgressMiddleware(changed_after_sdk, bridge.egress)
    await app({"type": "http", "path": "/mcp"}, None, capture)
    result = json.loads(sent[-1]["body"])
    assert MARKER not in str(result)
    diagnostic = result["error"]["data"]["diagnostic"]
    assert diagnostic["code"] == (
        "TRANSPORT_FAILED" if malformed else "RESPONSE_INSPECTION_RECEIPT_MISMATCH"
    )
    assert diagnostic["content_delivery"] == "none"
