"""Authenticated library settings; mutations are intentionally absent from model tools."""

import asyncio
import functools
import hashlib
import html
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.responses import JSONResponse, StreamingResponse

from canvas_bridge.domain import DomainError
from canvas_bridge.library.contracts import (
    CHUNK,
    ExportRequest,
    IntakeRequest,
    MetadataChange,
    PermissionChange,
    Replacement,
    VersionExpectation,
    fail,
)


class ManagedStreamingResponse(StreamingResponse):
    def __init__(self, stream, **kwargs):
        self.resource = stream
        super().__init__(stream, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.resource.close()


def register(bridge, route, identity, page):
    if not bridge.settings.library_enabled:
        return
    library = bridge.library

    def api(path, methods):
        def decorator(fn):
            @functools.wraps(fn)
            async def safe(request):
                started, outcome, result = time.monotonic(), "failed", None
                try:
                    browser = await identity(request, request.method not in {"GET", "HEAD"})
                    if request.method not in {"GET", "HEAD"}:
                        root = urlsplit(bridge.settings.resource_url)
                        if request.headers.get(
                            "origin"
                        ) != f"{root.scheme}://{root.netloc}" or not secrets.compare_digest(
                            request.headers.get("x-bridge-csrf", ""), browser.csrf
                        ):
                            fail("CONSENT_REQUIRED")
                    result = await fn(request, browser)
                    request.state.validate_bridge_session()
                    if not isinstance(result, (JSONResponse, StreamingResponse)):
                        result = JSONResponse(result)
                    result.headers.update(
                        {
                            "Cache-Control": "no-store",
                            "X-Content-Type-Options": "nosniff",
                            "Referrer-Policy": "no-referrer",
                        }
                    )
                    outcome = "ok"
                    return result
                except (ValidationError, ValueError, KeyError, TypeError):
                    return JSONResponse(
                        {
                            "reason_code": "INVALID_REQUEST",
                            "retryable": False,
                            "next_action": "Review the selection and reload the library.",
                            "correlation_id": secrets.token_hex(16),
                        },
                        status_code=400,
                    )
                except DomainError as exc:
                    outcome = "denied"
                    if exc.reason_code == "CHECKSUM_MISMATCH":
                        library.metric("checksum", "failed")
                    status = {
                        "AUTH_REQUIRED": 401,
                        "RESOURCE_UNAVAILABLE": 404,
                        "SOURCE_CHANGED": 409,
                        "TRANSFER_EXPIRED": 409,
                        "UPLOAD_TOO_LARGE": 413,
                        "UNSUPPORTED_MEDIA": 415,
                        "UNSAFE_ARCHIVE": 415,
                        "QUOTA_EXCEEDED": 429,
                        "CAPACITY_UNAVAILABLE": 429,
                        "PROCESSING_BUSY": 429,
                        "RATE_LIMITED": 429,
                        "SCAN_UNAVAILABLE": 503,
                        "STORAGE_UNAVAILABLE": 503,
                        "RESTORE_ON_HOLD": 503,
                    }.get(exc.reason_code, 403)
                    return JSONResponse(
                        {
                            "reason_code": exc.reason_code or "RESOURCE_UNAVAILABLE",
                            "retryable": status in {429, 503},
                            "next_action": exc.message,
                            "correlation_id": secrets.token_hex(16),
                            **exc.details,
                        },
                        status_code=status,
                        headers={"Cache-Control": "no-store"},
                    )
                except (TimeoutError, OSError):
                    return JSONResponse(
                        {
                            "reason_code": "STORAGE_UNAVAILABLE",
                            "retryable": True,
                            "next_action": "Check the existing intake receipt before retrying.",
                            "correlation_id": secrets.token_hex(16),
                        },
                        status_code=503,
                        headers={"Cache-Control": "no-store"},
                    )
                finally:
                    if outcome != "ok" and isinstance(result, ManagedStreamingResponse):
                        result.resource.close()
                    library.metric(
                        "request", outcome, milliseconds=int((time.monotonic() - started) * 1000)
                    )

            return route(path, methods)(safe)

        return decorator

    async def body(request):
        raw = bytearray()
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 64000:
                    fail("UPLOAD_TOO_LARGE", "needs_input")
        return json.loads(raw)

    @route("/settings/library", ["GET"])
    async def library_page(request):
        browser = await identity(request)
        nonce = secrets.token_urlsafe(24)
        status = library.status(browser.owner).data
        profile = bridge.independent.profile()
        content = "<p>Save your own permitted files for later chats, even without an LMS connection. Attaching a file to chat does not save it here.</p>"
        content += "<p>New originals remain until you delete them or choose an expiry. Existing temporary imports keep their 24-hour limit. Replacement keeps up to five versions and superseded originals for up to 30 days.</p>"
        content += f'<p><span id="storage-quota">Storage: {status["quota"]["committed_bytes"]:,} bytes used; {status["quota"]["reserved_bytes"]:,} reserved; {status["quota"]["maximum_bytes"]:,} allowed.</span> Documents: 100 MiB; images: 25 MiB; ZIP: 50,000,000 bytes. Extraction: 10 MB (PPTX: 25 MB). Larger safe files can be stored without extraction.</p>'
        content += """<form id="library-upload" class="card"><label>Files (up to 20)<input id="files" type="file" multiple accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.zip" required></label>
<ul id="selection"></ul><label>Collection (optional)<input id="collection" type="text" maxlength="100"></label>
<label>Retention<select id="retention"><option value="until_deleted">Until I delete</option><option value="expires_at">Expire on a date</option></select></label><label>Expiry date and time<input id="expiry" type="datetime-local"></label>
<label><input id="own" type="checkbox" required>I have permission to store these independently supplied files. They are not restricted institutional material, confidential research, an exam or someone else's educational record. Necessary type and safety checks run locally.</label>
<label><input id="processing" type="checkbox">Allow local text extraction and indexing</label>
<label>Processing purpose<select id="purpose"><option value="document_reading">Read documents</option><option value="study">Study</option><option value="grade_planning">Grade planning</option><option value="schedule">Schedule proposals</option></select></label>
<fieldset><legend>Share with the configured recipient (optional)</legend>"""
        content += (
            "<p>"
            + html.escape(
                profile.policy_id
                if profile
                else "No reviewed recipient configured; owner storage remains available."
            )
            + "</p>"
        )
        for channel in ("metadata", "text", "visual", "original"):
            disabled = "" if profile and channel in profile.channels else " disabled"
            content += f'<label><input type="checkbox" class="channel" value="{channel}"{disabled}>Allow {channel}</label>'
        content += """</fieldset><button id="save">Save to private library</button> <button id="cancel" type="button" disabled>Cancel unfinished uploads</button> <button id="retry" type="button" disabled>Retry / check receipt</button>
<label for="progress">Transferred bytes</label><progress id="progress" value="0" max="1"></progress><p id="status" role="status" aria-live="polite" tabindex="-1"></p></form>
<section class="card"><h2>Private files</h2><p>Original downloads use your signed-in session. Deletion stops Bridge access; prior downloads and chat copies are controlled separately.</p>
<form id="library-filter" aria-label="Filter private files"><label>Title contains<input id="filter-query" type="search" maxlength="200"></label><label>Exact tag<input id="filter-tag" maxlength="80"></label><label>Collection<input id="filter-collection" maxlength="80"></label><button>Filter files</button><button id="clear-filter" type="button">Clear filters</button></form><p id="list-status" role="status" aria-live="polite"></p><div id="items"></div><button type="button" id="more" hidden>More files</button></section>"""
        config = {
            "csrf": browser.csrf,
            "action": hashlib.sha256(browser.csrf.encode()).hexdigest(),
            "profile": profile.policy_id if profile else None,
            "channels": list(profile.channels) if profile else [],
            "chunk": CHUNK,
        }
        script = Path(__file__).with_name("upload.js").read_text(encoding="utf-8")
        content += f'<script nonce="{nonce}">const libraryConfig={json.dumps(config).replace("<", chr(92) + "u003c")};\n{script}</script>'
        response = page("Private library", content)
        response.headers["Content-Security-Policy"] += (
            f"; script-src 'nonce-{nonce}'; connect-src 'self'"
        )
        return response

    @api("/api/library/status", ["GET"])
    async def status(request, browser):
        return library.status(browser.owner).data

    @api("/api/library/intakes", ["POST"])
    async def create(request, browser):
        return library.create_intake(browser, IntakeRequest.model_validate(await body(request)))

    @api("/api/library/intakes/{intake}", ["GET", "DELETE"])
    async def intake(request, browser):
        if request.method == "GET":
            return library.receipt(browser.owner, request.path_params["intake"])
        return library.cancel(
            browser, request.path_params["intake"], (await body(request))["expected_revision"]
        )

    @api("/api/library/intakes/{intake}/files/{selection}/chunks", ["PUT"])
    async def chunk(request, browser):
        raw = bytearray()
        with library.operation(browser.owner, "ingress") as valid_lease:
            async with asyncio.timeout(bridge.settings.library_idle_seconds):
                async for part in request.stream():
                    if len(raw) + len(part) > CHUNK:
                        fail("UPLOAD_TOO_LARGE", "needs_input")
                    raw.extend(part)
            request.state.validate_bridge_session()
            valid_lease()
            result = library.put_chunk(
                browser,
                request.path_params["intake"],
                request.path_params["selection"],
                int(request.headers["upload-offset"]),
                request.headers["x-chunk-sha256"],
                bytes(raw),
            )
            library.metric("upload", "ok", size=0 if result.get("replayed") else len(raw))
            return result

    @api("/api/library/intakes/{intake}/complete", ["POST"])
    async def complete(request, browser):
        hashes = (await body(request))["hashes"]
        if not isinstance(hashes, dict) or len(hashes) > 20:
            raise ValueError
        return await library.complete(
            browser, request.path_params["intake"], hashes, request.state.validate_bridge_session
        )

    @api("/api/library/items", ["GET"])
    async def items(request, browser):
        return library.list(
            browser.owner,
            limit=int(request.query_params.get("limit", "20")),
            cursor=request.query_params.get("cursor"),
            collection=request.query_params.get("collection"),
            tag=request.query_params.get("tag"),
            query=request.query_params.get("query"),
            browser=True,
        ).data

    @api("/api/library/items/{item}/retry-processing", ["POST"])
    async def retry_processing(request, browser):
        return library.retry_processing(
            browser,
            request.path_params["item"],
            VersionExpectation.model_validate(await body(request)),
        )

    @api("/api/library/items/{item}", ["GET", "PATCH", "DELETE"])
    async def item(request, browser):
        ident = request.path_params["item"]
        if request.method == "GET":
            return library.get(
                browser.owner, ident, request.query_params.get("version"), browser=True
            ).data
        if request.method == "PATCH":
            return library.update_metadata(
                browser, ident, MetadataChange.model_validate(await body(request))
            )
        return library.delete_item(
            browser, ident, VersionExpectation.model_validate(await body(request))
        )

    @api("/api/library/items/{item}/versions", ["POST"])
    async def replace(request, browser):
        value = Replacement.model_validate(await body(request))
        return library.create_intake(
            browser,
            value.selection,
            replacement={
                "item_id": request.path_params["item"],
                **value.model_dump(exclude={"selection"}),
            },
        )

    @api("/api/library/items/{item}/grants", ["POST"])
    async def grants(request, browser):
        return library.update_grants(
            browser,
            request.path_params["item"],
            PermissionChange.model_validate(await body(request)),
        )

    @api("/api/library/items/{item}/versions/{version}/original", ["GET"])
    async def original(request, browser):
        item_id, version_id = request.path_params["item"], request.path_params["version"]
        _, version, _ = library.require(browser.owner, item_id, version_id)
        start, end = 0, version.size - 1
        selected = request.headers.get("range")
        if selected:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", selected)
            if not match or not any(match.groups()):
                return JSONResponse(
                    {"reason_code": "INVALID_RANGE"},
                    status_code=416,
                    headers={"Content-Range": f"bytes */{version.size}"},
                )
            if match[1]:
                start, end = int(match[1]), min(end, int(match[2])) if match[2] else end
            else:
                start = max(0, version.size - int(match[2]))
            if start > end or start >= version.size:
                return JSONResponse(
                    {"reason_code": "INVALID_RANGE"},
                    status_code=416,
                    headers={"Content-Range": f"bytes */{version.size}"},
                )
        _, stream = library.original(
            browser.owner,
            item_id,
            version_id,
            start=start,
            end=end,
            validate=request.state.validate_bridge_session,
        )
        headers = {
            "Content-Disposition": f'attachment; filename="{version.id}.{version.kind}"',
            "Content-Length": str(end - start + 1),
            "Accept-Ranges": "bytes",
            "ETag": '"' + version.digest + '"',
        }
        if selected:
            headers["Content-Range"] = f"bytes {start}-{end}/{version.size}"
        return StreamingResponse(
            stream,
            status_code=206 if selected else 200,
            media_type="application/octet-stream",
            headers=headers,
        )

    @api("/api/library/deletions/{receipt}", ["GET"])
    async def deletion(request, browser):
        return library.deletion(browser.owner, request.path_params["receipt"])

    @api("/api/library/deliveries/{delivery}", ["GET"])
    async def delivery(request, browser):
        ident = request.path_params["delivery"]
        item_id, version_id = library.delivery(browser.owner, ident)

        def check():
            request.state.validate_bridge_session()
            library.delivery(browser.owner, ident)

        version, stream = library.original(browser.owner, item_id, version_id, validate=check)
        return StreamingResponse(
            stream,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{version.id}.{version.kind}"',
                "Content-Length": str(version.size),
            },
        )

    @api("/api/library/exports", ["POST"])
    async def export(request, browser):
        return library.create_export(browser, ExportRequest.model_validate(await body(request)))

    @api("/api/library/exports/{export}", ["GET"])
    async def download_export(request, browser):
        return ManagedStreamingResponse(
            library.export_stream(
                browser.owner, request.path_params["export"], request.state.validate_bridge_session
            ),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="private-library-export.zip"'},
        )

    @api("/api/library/legacy/{document}", ["POST"])
    async def legacy(request, browser):
        return await library.save_legacy(
            browser,
            request.path_params["document"],
            IntakeRequest.model_validate(await body(request)),
            request.state.validate_bridge_session,
        )
