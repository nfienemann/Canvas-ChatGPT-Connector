"""Fence SDK-generated errors and the fixed MCP catalog as well as tool outputs."""

import asyncio
import json
import logging
import math
import re

from mcp import types
from mcp.shared.exceptions import McpError

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.failure_diagnostics import Attempt, StreamInterrupted, current, describe
from canvas_bridge.failure_events import record
from canvas_bridge.file_delivery_ui import DOWNLOAD_URI
from canvas_bridge.policy_surfaces import OFFLINE_TOOLS, TOOL_CATEGORIES
from canvas_bridge.visual_ui import PAGE_URI


class RequestLogFilter(logging.Filter):
    """The SDK logs some Pydantic failures (including input) directly to root."""

    def filter(self, record):
        attempt = current.get()
        ident = attempt.request_id if attempt else None
        if record.name == "uvicorn.error" and record.exc_info:
            # The ASGI server logs propagated stream failures after request-local
            # context was released. Keep its correlation without a traceback.
            ident = getattr(record.exc_info[1], "bridge_request_id", None)
        if isinstance(ident, str) and re.fullmatch(r"[0-9a-f]{32}", ident):
            record.msg = "Bridge transport event request_id=%s"
            record.args = (ident,)
            record.exc_info = record.exc_text = record.stack_info = None
        return True


def protect_sdk_logs():
    for name in (
        "",
        "mcp.server.lowlevel.server",
        "mcp.server.streamable_http",
        "mcp.server.streamable_http_manager",
        "uvicorn.error",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RequestLogFilter) for f in logger.filters):
            logger.addFilter(RequestLogFilter())


def emergency_message(engine, exc):
    attempt = current.get()
    ident = attempt.request_id
    message = "Bridge withheld the response."
    if re.fullmatch(r"[0-9a-f]{32}", ident):
        message += f" Report request {ident} to the operator."
    try:
        attempt.capture(exc)
        result = Result(summary="", data={"reason_code": "DIAGNOSTIC_SERIALIZATION_FAILED"})
        describe(result, "not_evaluated")
        record(engine)
    except Exception:
        return message
    return message


def inspected_failure(engine, code, *, sdk_error=True, source=None):
    from canvas_bridge.privacy.transport import digest, finalize, receipts

    result = (
        source
        if source is not None
        else Result(status="operation_failed", summary="", data={"reason_code": code})
    )
    clean = engine.safe_error(result)
    candidate = types.CallToolResult(
        structuredContent=clean.model_dump(mode="json"), content=[], isError=sdk_error
    )
    verified = finalize(candidate)
    if digest(verified) not in receipts.get():
        raise ValueError("Diagnostic verification failed")
    return verified


def protocol_error(engine, code, rpc_code, ident, *, delay=None):
    from canvas_bridge.privacy.transport import receipts

    token = receipts.set(set())
    try:
        facts = {"reason_code": code}
        if code == "TRANSPORT_TIMEOUT":
            facts.update(
                deadline_seconds=current.get().transport_deadline,
                elapsed_ms=current.get().transport_elapsed_ms,
            )
        if code == "TRANSPORT_BUSY" and delay is not None:
            facts["retry_after_seconds"] = delay
        safe = inspected_failure(
            engine, code, source=Result(status="operation_failed", summary="", data=facts)
        ).structuredContent
        error = {
            "code": rpc_code,
            "message": safe["summary"],
            "data": {"diagnostic": safe["data"]["diagnostic"]},
        }
    except Exception as exc:
        error = {"code": -32603, "message": emergency_message(engine, exc)}
    finally:
        receipts.reset(token)
    return {"jsonrpc": "2.0", "id": ident, "error": error}


class McpErrorEgressMiddleware:
    """Sanitize protocol validation failures that occur before an MCP handler.

    This server uses stateless JSON responses. File streams are not buffered.
    The SDK's HTTP and JSON-RPC errors can contain Pydantic input values.
    """

    def __init__(self, app, engine):
        self.app, self.engine = app, engine

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)
        from canvas_bridge.auth import last_rejection

        rejection_token = last_rejection.set(None)
        token = current.set(Attempt())
        try:
            return await self.handle(scope, receive, send)
        finally:
            current.reset(token)
            last_rejection.reset(rejection_token)

    async def handle(self, scope, receive, send):
        start = None
        sent_start = False
        delivery = "none"
        chunks = bytearray()
        buffered = False
        oversized = False

        async def guarded_send(message):
            nonlocal start, buffered, oversized, sent_start, delivery
            if message["type"] == "http.response.start":
                start = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-bridge-request-id", current.get().request_id.encode("ascii")),
                    ],
                }
                message = start
                headers = dict(message.get("headers", []))
                buffered = message["status"] >= 400 or b"application/json" in headers.get(
                    b"content-type", b""
                )
                if not buffered:
                    sent_start = True
                    await send(message)
                return
            if message["type"] != "http.response.body" or not buffered:
                if message.get("body"):
                    delivery = "unknown"  # Streaming frames may also be protocol metadata.
                await send(message)
                return
            body = message.get("body", b"")
            oversized = oversized or len(chunks) + len(body) > 4_000_000
            if not oversized:
                chunks.extend(body)
            if message.get("more_body"):
                return
            malformed = False
            try:
                payload = json.loads(chunks) if chunks else {}
            except (ValueError, UnicodeError, RecursionError):
                payload = {}
                malformed = True
            status = start["status"]
            error = payload.get("error") if isinstance(payload, dict) else None
            mismatch = False
            if chunks and not oversized and status < 400 and error is None:
                malformed = malformed or not (
                    isinstance(payload, dict)
                    and set(payload) == {"jsonrpc", "id", "result"}
                    and payload["jsonrpc"] == "2.0"
                    and type(payload["id"]) in {str, int}
                    and isinstance(payload["result"], dict)
                )
                if not malformed and current.get().wire_digest is not None:
                    from canvas_bridge.privacy.transport import payload_digest

                    mismatch = payload_digest(payload["result"]) != current.get().wire_digest
            if oversized or malformed or mismatch or status >= 400 or error is not None:
                rpc_code = error.get("code") if isinstance(error, dict) else None
                if type(rpc_code) is not int or rpc_code not in {
                    -32700,
                    -32600,
                    -32601,
                    -32602,
                    -32603,
                }:
                    rpc_code = -32603
                if oversized:
                    code = "BUFFERED_OUTPUT_TOO_LARGE"
                elif mismatch:
                    code = "RESPONSE_INSPECTION_RECEIPT_MISMATCH"
                elif current.get().protocol_cause is not None:
                    code = current.get().protocol_cause
                elif status == 429:
                    code = "TRANSPORT_BUSY"
                elif status in {401, 403}:
                    code = "TRANSPORT_ACCESS_DENIED"
                elif status in {400, 406, 415} or rpc_code in {-32700, -32600, -32602}:
                    code = "PROTOCOL_INPUT_INVALID"
                else:
                    code = "TRANSPORT_FAILED"
                ident = payload.get("id") if isinstance(payload, dict) else None
                ident = (
                    ident
                    if type(ident) is int or (isinstance(ident, str) and len(ident) <= 256)
                    else None
                )
                delay = None
                if code == "TRANSPORT_BUSY":
                    from canvas_bridge.request_limits import retry_after

                    raw = dict(start.get("headers", [])).get(b"retry-after", b"")
                    seconds = retry_after(raw.decode("ascii", errors="replace"))
                    if seconds is not None and seconds <= 86400:
                        delay = math.ceil(seconds)
                challenge = dict(start["headers"]).get(b"www-authenticate", b"")
                sdk_auth = (
                    status in {401, 403}
                    and challenge.startswith(b"Bearer ")
                    and isinstance(payload, dict)
                    and (
                        (payload.get("error"), payload.get("error_description"))
                        in (
                            ("invalid_token", "Authentication required"),
                            ("insufficient_scope", "Required scope: academic:read"),
                        )
                    )
                )
                if sdk_auth:
                    from canvas_bridge.auth import last_rejection
                    from canvas_bridge.auth_diagnostics import transport_observation

                    missing = not any(
                        k.lower() == b"authorization" and v[:7].lower() == b"bearer "
                        for k, v in scope.get("headers", [])
                    )
                    current.get().auth_observation = transport_observation(
                        "SDK_SCOPE_DENIED" if status == 403 else last_rejection.get(),
                        missing,
                        current.get().request_id,
                    )
                    oauth = {k: payload[k] for k in ("error", "error_description")}
                payload = protocol_error(self.engine, code, rpc_code, ident, delay=delay)
                if sdk_auth:
                    # Keep the SDK OAuth response shape, status and discovery challenge.
                    payload = {**oauth, **payload["error"].get("data", {})}
                chunks[:] = json.dumps(payload).encode()
            headers = [
                (k, v)
                for k, v in start.get("headers", [])
                if k.lower() not in {b"content-length", b"content-type"}
            ]
            headers += [
                (b"content-length", str(len(chunks)).encode()),
                (b"content-type", b"application/json"),
            ]
            sent_start = True
            await send({**start, "headers": headers})
            requested_body = bool(
                current.get().operation and not current.get().diagnostic and chunks
            )
            if requested_body:
                delivery = "unknown"
            await send({"type": "http.response.body", "body": bytes(chunks)})

            if requested_body:
                delivery = "complete"

        try:
            await self.app(scope, receive, guarded_send)
        except asyncio.CancelledError:
            attempt = current.get()
            attempt.delivery = delivery
            describe(
                Result(summary="", data={"reason_code": "TRANSPORT_INTERRUPTED"}), "not_evaluated"
            )
            record(self.engine)
            raise
        except Exception as exc:
            attempt = current.get()
            attempt.capture(exc)
            attempt.delivery = delivery
            code = "TRANSPORT_TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT_FAILED"
            if sent_start:
                describe(
                    Result(
                        summary="",
                        data={
                            k: v
                            for k, v in {
                                "reason_code": code,
                                "deadline_seconds": attempt.transport_deadline,
                                "elapsed_ms": attempt.transport_elapsed_ms,
                            }.items()
                            if v is not None
                        },
                    ),
                    "not_evaluated",
                )
                record(self.engine)
                # HTTP headers are committed. Terminate rather than append JSON to a stream.
                raise StreamInterrupted(attempt.request_id) from None
            payload = protocol_error(self.engine, code, -32603, None)
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-bridge-request-id", attempt.request_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": json.dumps(payload).encode()})


def fence_mcp_outputs(mcp, engine):
    # The installed MCP SDK normalizes exceptions and validation errors outside
    # FastMCP tools. Those messages can echo the rejected input verbatim.
    protect_sdk_logs()
    handlers = mcp._mcp_server.request_handlers
    original_call = handlers[types.CallToolRequest]
    original_read = handlers[types.ReadResourceRequest]
    known_tools = set(TOOL_CATEGORIES) | OFFLINE_TOOLS
    # Freeze the registered public catalog before any client request. Provider
    # content and later helper mutations cannot add arbitrary metadata channels.
    tool_catalog = [
        types.Tool(
            name=t.name,
            title=t.title,
            description=t.description,
            inputSchema=t.parameters,
            outputSchema=t.output_schema,
            annotations=t.annotations,
            icons=t.icons,
            _meta=t.meta,
        ).model_copy(deep=True)
        for t in mcp._tool_manager.list_tools()
    ]
    resource_catalog = [
        types.Resource(
            uri=r.uri,
            name=r.name or "",
            title=r.title,
            description=r.description,
            mimeType=r.mime_type,
            icons=r.icons,
            annotations=r.annotations,
            _meta=r.meta,
        ).model_copy(deep=True)
        for r in mcp._resource_manager.list_resources()
    ]
    static_resources = {
        str(r.uri): types.TextResourceContents(
            uri=r.uri, mimeType=r.mime_type, text=r.fn(), _meta=r.meta
        ).model_copy(deep=True)
        for r in mcp._resource_manager.list_resources()
        if str(r.uri) in {PAGE_URI, DOWNLOAD_URI}
    }

    schemas = {t.name: t.inputSchema for t in tool_catalog}

    def safe_failure(code, *, source=None, sdk_error=True):
        try:
            response = inspected_failure(engine, code, source=source, sdk_error=sdk_error)
        except Exception as exc:
            response = types.CallToolResult(
                content=[types.TextContent(type="text", text=emergency_message(engine, exc))],
                isError=True,
            )
        return types.ServerResult(response)

    async def call(request):
        from canvas_bridge.input_diagnostics import input_error, registered_input_error
        from canvas_bridge.privacy.transport import digest, receipts

        attempt = current.get() or Attempt()
        context_token = current.set(attempt)
        token = receipts.set(set())
        try:
            name = request.params.name
            if name not in schemas or name not in known_tools:
                return safe_failure("TOOL_NOT_REGISTERED")
            attempt.operation = name
            diagnostic = input_error(name, request.params.arguments)
            if diagnostic is not None:
                return safe_failure(None, source=diagnostic, sdk_error=False)
            response = await original_call(request)
            if attempt.emergency:
                return types.ServerResult(
                    types.CallToolResult(
                        content=[types.TextContent(type="text", text=attempt.emergency)],
                        isError=True,
                    )
                )
            root = getattr(response, "root", None)
            if not isinstance(root, types.CallToolResult):
                return safe_failure("TOOL_RESPONSE_INVALID")
            if root.isError:
                if digest(root) in receipts.get() and attempt.diagnostic:
                    return response
                if attempt.inspected_error is not None:
                    return safe_failure(None, source=attempt.inspected_error)
                # The SDK normalizes validation exceptions to strings. Recheck the
                # registered schema; never parse or release the SDK's message.
                if registered_input_error(schemas[name], request.params.arguments, attempt):
                    return safe_failure("TOOL_INPUT_INVALID")
                return safe_failure("TOOL_RESULT_FAILED")
            if not receipts.get():
                return safe_failure("RESPONSE_INSPECTION_RECEIPT_MISSING")
            if digest(root) not in receipts.get():
                return safe_failure("RESPONSE_INSPECTION_RECEIPT_MISMATCH")
            return response
        except DomainError as exc:
            attempt.capture(exc)
            attempt.domain_status = exc.status
            status = (
                exc.status
                if exc.status in Result.model_fields["status"].annotation.__args__
                else "operation_failed"
            )
            return safe_failure(None, source=Result(status=status, summary="", data=exc.data))
        except Exception as exc:
            attempt.capture(exc)
            return safe_failure("TOOL_EXECUTION_FAILED")
        finally:
            receipts.reset(token)
            current.reset(context_token)

    async def read(request):
        try:
            if str(request.params.uri) not in {PAGE_URI, DOWNLOAD_URI}:
                raise DomainError("needs_input", "", reason_code="RESOURCE_NOT_REGISTERED")
            response = await original_read(request)
            if any(
                not isinstance(c, types.TextResourceContents)
                or c != static_resources.get(str(request.params.uri))
                for c in response.root.contents
            ):
                raise DomainError("permission_denied", "", reason_code="PRIVACY_OUTPUT_UNVERIFIED")
            engine.static_metadata(response.model_dump_json())
            return response
        except Exception as exc:
            code = (
                exc.reason_code
                if isinstance(exc, DomainError)
                and exc.reason_code in {"RESOURCE_NOT_REGISTERED", "PRIVACY_OUTPUT_UNVERIFIED"}
                else "TOOL_EXECUTION_FAILED"
            )
            if attempt := current.get():
                attempt.protocol_cause = code
            # The HTTP fence builds the public diagnostic once, from server-local evidence.
            raise McpError(types.ErrorData(code=-32602, message="Resource unavailable.")) from None

    def catalog_handler(original, kind):
        async def catalog(request):
            try:
                return await checked_catalog(request)
            except Exception as exc:
                if attempt := current.get():
                    attempt.capture(exc)
                    attempt.protocol_cause = (
                        "PRIVACY_OUTPUT_UNVERIFIED"
                        if isinstance(exc, DomainError)
                        else "TOOL_RESPONSE_INVALID"
                    )
                raise McpError(
                    types.ErrorData(code=-32603, message="Catalog unavailable.")
                ) from None

        async def checked_catalog(request):
            response = await original(request)
            root = response.root
            valid = (
                root.tools == tool_catalog and all(t.name in known_tools for t in root.tools)
                if kind == "tools"
                else root.resources == resource_catalog
                and all(str(r.uri) in static_resources for r in root.resources)
                if kind == "resources"
                else not root.resourceTemplates
            )
            engine.static_metadata(response.model_dump_json(), authorized=valid)
            return response

        return catalog

    def bind_wire_result(handler):
        async def bound(request):
            from canvas_bridge.privacy.transport import digest

            response = await handler(request)
            if attempt := current.get():
                # Verify the SDK's buffered JSON representation before HTTP send.
                attempt.wire_digest = digest(response.root)
            return response

        return bound

    handlers[types.CallToolRequest] = bind_wire_result(call)
    handlers[types.ReadResourceRequest] = bind_wire_result(read)
    for request_type, kind in (
        (types.ListToolsRequest, "tools"),
        (types.ListResourcesRequest, "resources"),
        (types.ListResourceTemplatesRequest, "templates"),
    ):
        handlers[request_type] = bind_wire_result(catalog_handler(handlers[request_type], kind))
