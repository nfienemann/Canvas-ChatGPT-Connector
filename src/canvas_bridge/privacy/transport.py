"""Request-local evidence of inspection of the exact final MCP response.

Nothing is serialized as a trust token. A forged `meta.egress`/`meta.privacy`
object cannot create this receipt. ContextVars isolate concurrent requests.
"""

import hashlib
import json
from contextvars import ContextVar

from mcp import types

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.privacy.output import filter_output, metadata
from canvas_bridge.privacy_text import inspect_text

receipts: ContextVar[set | None] = ContextVar("privacy_serialization_receipts", default=None)


def digest(response):
    return hashlib.sha256(
        json.dumps(
            response.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).digest()


def deny():
    raise DomainError(
        "permission_denied",
        "Privacy inspection could not be established.",
        reason_code="PRIVACY_OUTPUT_UNVERIFIED",
    )


def inspect_descriptors(value, *, binary=False, depth=0):
    if depth > 10:
        deny()
    if isinstance(value, dict):
        allowed = {
            "canvas_bridge_page",
            "canvas_bridge_download",
            "png",
            "resource",
            "external_url",
            "type",
            "uri",
            "name",
            "mimeType",
            "size",
            "blob",
        }
        if set(value) - allowed:
            deny()
        for key, item in value.items():
            if key in {"png", "blob"}:
                if not binary or not isinstance(item, str) or len(item) > 2_000_000:
                    deny()
                continue
            inspect_descriptors(item, binary=binary, depth=depth + 1)
    elif isinstance(value, list):
        deny()
    elif isinstance(value, str) and inspect_text(value)[1]:
        deny()


def finalize(returned, *, binary=False):
    response = (
        returned
        if isinstance(returned, types.CallToolResult)
        else types.CallToolResult(structuredContent=returned.model_dump(mode="json"), content=[])
    )
    payload = response.structuredContent
    if not payload or not payload.get("meta", {}).get("privacy"):
        deny()
    cleaned, changed, third_party, hidden = filter_output(payload)
    if third_party or hidden:
        deny()
    result = Result.model_validate(cleaned)
    result.meta.privacy = metadata(
        changed or bool(payload["meta"]["privacy"].get("filtered")),
        content=result.model_dump_json(),
    )
    # There is exactly one text representation, reconstructed from the inspected
    # Result. Additional text, audio, links or resource blocks cannot bypass it.
    content = [types.TextContent(type="text", text=result.model_dump_json())]
    for item in response.content:
        if item.type == "text":
            # image_response emits this exact representation before final edits.
            if item.text != Result.model_validate(payload).model_dump_json():
                deny()
        elif binary and item.type == "image" and item.mimeType == "image/png":
            if item.meta is not None or item.annotations is not None:
                deny()
            content.append(types.ImageContent(type="image", data=item.data, mimeType="image/png"))
        else:
            deny()
    inspect_descriptors(response.meta or {}, binary=binary)
    final = types.CallToolResult(
        structuredContent=result.model_dump(mode="json"),
        content=content,
        _meta=response.meta,
        isError=response.isError,
    )
    current = receipts.get()
    if current is not None:
        current.add(digest(final))
    return final
