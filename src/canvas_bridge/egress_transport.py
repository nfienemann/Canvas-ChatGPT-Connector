"""Fence SDK-generated errors and the fixed MCP catalog as well as tool outputs."""

import json

from mcp import types
from mcp.shared.exceptions import McpError

from canvas_bridge.domain import Result
from canvas_bridge.file_delivery_ui import DOWNLOAD_URI
from canvas_bridge.policy_surfaces import OFFLINE_TOOLS, TOOL_CATEGORIES
from canvas_bridge.visual_ui import PAGE_URI


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
        start = None
        chunks = bytearray()
        buffered = False
        oversized = False

        async def guarded_send(message):
            nonlocal start, buffered, oversized
            if message["type"] == "http.response.start":
                start = message
                headers = dict(message.get("headers", []))
                buffered = message["status"] >= 400 or b"application/json" in headers.get(
                    b"content-type", b""
                )
                if not buffered:
                    await send(message)
                return
            if message["type"] != "http.response.body" or not buffered:
                await send(message)
                return
            body = message.get("body", b"")
            oversized = oversized or len(chunks) + len(body) > 4_000_000
            if not oversized:
                chunks.extend(body)
            if message.get("more_body"):
                return
            try:
                payload = json.loads(chunks) if chunks else {}
            except (ValueError, UnicodeError):
                payload = {}
            if (
                oversized
                or start["status"] >= 400
                or (isinstance(payload, dict) and "error" in payload)
            ):
                safe = self.engine.safe_error(Result(status="permission_denied", summary=""))
                # Only protocol-safe correlation data survives; never error.data.
                ident = payload.get("id") if isinstance(payload, dict) else None
                ident = ident if type(ident) is int else None
                payload = {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "error": {"code": -32602, "message": safe.summary},
                }
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
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": bytes(chunks)})

        await self.app(scope, receive, guarded_send)


def fence_mcp_outputs(mcp, engine):
    # The installed MCP SDK normalizes exceptions and validation errors outside
    # FastMCP tools. Those messages can echo the rejected input verbatim.
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

    def safe_failure():
        clean = engine.safe_error(
            Result(
                status="permission_denied",
                summary="",
                data={"reason_code": "EGRESS_ERROR_REDACTED"},
            )
        )
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=clean.model_dump_json())],
                structuredContent=clean.model_dump(mode="json"),
                isError=True,
            )
        )

    async def call(request):
        from canvas_bridge.input_diagnostics import input_error
        from canvas_bridge.privacy.transport import digest, finalize, receipts

        if request.params.name not in known_tools:
            return safe_failure()
        token = receipts.set(set())
        try:
            diagnostic = input_error(request.params.name, request.params.arguments)
            if diagnostic is not None:
                # Static diagnostics use the same egress and final serializer.
                # No SDK exception string or caller-supplied field is released.
                return types.ServerResult(finalize(engine.safe_error(diagnostic)))
            response = await original_call(request)
            if (
                not isinstance(response.root, types.CallToolResult)
                or response.root.isError
                or digest(response.root) not in receipts.get()
            ):
                return safe_failure()
            return response
        except Exception:
            return safe_failure()
        finally:
            receipts.reset(token)

    async def read(request):
        try:
            if str(request.params.uri) not in {PAGE_URI, DOWNLOAD_URI}:
                raise ValueError("Unregistered resource")
            response = await original_read(request)
            if any(
                not isinstance(c, types.TextResourceContents)
                or c != static_resources.get(str(request.params.uri))
                for c in response.root.contents
            ):
                raise ValueError("Unreviewed resource content")
            engine.static_metadata(response.model_dump_json())
            return response
        except Exception:
            clean = engine.safe_error(Result(status="permission_denied", summary=""))
            raise McpError(types.ErrorData(code=-32602, message=clean.summary)) from None

    def catalog_handler(original, kind):
        async def catalog(request):
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

    handlers[types.CallToolRequest] = call
    handlers[types.ReadResourceRequest] = read
    for request_type, kind in (
        (types.ListToolsRequest, "tools"),
        (types.ListResourcesRequest, "resources"),
        (types.ListResourceTemplatesRequest, "templates"),
    ):
        handlers[request_type] = catalog_handler(handlers[request_type], kind)
