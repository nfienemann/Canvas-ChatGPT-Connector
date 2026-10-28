"""Course-scoped file metadata and bounded, credential-separated downloads.

This transport never parses documents. Text extraction remains gated on an
OS-isolated parser; original delivery streams separately into private staging.
Signed download URLs stay transient and never become sources.
"""

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx

from canvas_bridge.document_policy import SOURCE_BYTES
from canvas_bridge.domain import DomainError
from canvas_bridge.network import GuardedHTTP, public_client
from canvas_bridge.policy import Endpoint, source_id, validate_https

MAX_FILE_BYTES = SOURCE_BYTES
_reading_slot = threading.BoundedSemaphore(1)
MAX_REDIRECTS = 3
FILE_TYPES = {
    "application/pdf": ("pdf", ".pdf"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", ".docx"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("pptx", ".pptx"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("xlsx", ".xlsx"),
    "text/plain": ("txt", ".txt"),
    "text/markdown": ("md", ".md"),
    "text/x-markdown": ("md", ".md"),
    "text/html": ("html", ".html"),
}


def file_format(metadata: dict) -> str | None:
    """One metadata allowlist shared by status and the authenticated download."""
    mime = str(metadata.get("content-type", "")).split(";", 1)[0].strip().lower()
    name = metadata.get("filename")
    if not isinstance(name, str):
        return None
    supported = FILE_TYPES.get(mime)
    if mime in {"text/plain", "application/octet-stream"} and name.lower().endswith(".md"):
        supported = ("md", ".md")
    # Canvas sometimes uses the generic binary MIME for an OOXML workbook.
    # The ZIP signature and workbook structure are checked before accepting text.
    if mime == "application/octet-stream":
        for extension in ("xlsx", "pptx"):
            if name.lower().endswith("." + extension):
                supported = (extension, "." + extension)
    return supported[0] if supported and name.lower().endswith(supported[1]) else None


def file_version(metadata: dict) -> str | None:
    # Signed URLs rotate independently of document contents and are excluded.
    if not metadata.get("updated_at"):
        return None
    fields = {
        key: metadata.get(key)
        for key in ("id", "uuid", "updated_at", "modified_at", "size", "filename", "content-type")
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def file_visible(metadata: dict) -> bool:
    # Explicit current-user fields are required. More powerful credentials must
    # not turn hidden/locked course files into a student capability.
    return (
        metadata.get("locked_for_user") is False
        and metadata.get("hidden_for_user") is False
        and metadata.get("locked") is not True
        and metadata.get("hidden") is not True
    )


async def file_metadata(client, course: str, file: str) -> dict:
    course, file = source_id(course), source_id(file)
    metadata = await client.one(Endpoint.FILE, course=course, file=file)
    if str(metadata.get("id", "")) != file:
        raise DomainError(
            "permission_denied",
            "The course file is unavailable; its reference could not be verified.",
            reason_code="IDENTIFIER_MAPPING_FAILURE",
        )
    if not file_visible(metadata):
        denied = any(
            metadata.get(flag) is True
            for flag in ("locked_for_user", "hidden_for_user", "locked", "hidden")
        )
        raise DomainError(
            "permission_denied",
            "The course file is currently unavailable.",
            reason_code="RESOURCE_PERMISSION_DENIED" if denied else "UNKNOWN_AUTHORIZATION_FAILURE",
        )
    return metadata


@dataclass(frozen=True, repr=False)
class DownloadedFile:
    # repr=False prevents accidental log output of private file bytes.
    data: bytes
    kind: str
    revision: str | None = None
    byte_size: int = 0
    bytes_sha256: str | None = None
    upstream_validator: str | None = None


def download_destination(url: str, client, course: str, file: str) -> bool:
    """Return whether this is the reviewed institution download route."""
    if len(url) > 8192 or any(ord(c) < 33 for c in url):
        raise DomainError("permission_denied", "Unsafe file download destination.")
    origins = {
        client.institution.origin,
        *client.institution.download_origins,
        *(
            t.replace("{file_id}", source_id(file))
            for t in client.institution.download_origin_templates
        ),
    }
    try:
        validate_https(url, origins)
        parsed = urlsplit(url)
        same_origin = f"https://{parsed.hostname}" == client.institution.origin
    except ValueError as exc:
        raise DomainError("permission_denied", "Unsafe file download destination.") from exc
    if same_origin and parsed.path not in {
        f"/files/{file}/download",
        f"/courses/{course}/files/{file}/download",
    }:
        raise DomainError("permission_denied", "Unexpected Canvas file download route.")
    return same_origin


async def _download_once(
    client,
    course: str,
    file: str,
    *,
    http=None,
    sink: BinaryIO | None = None,
    metadata: dict | None = None,
    max_bytes=None,
    budget=None,
) -> DownloadedFile:
    """Only fresh metadata from a course-qualified API can supply a download URL.

    An injected HTTP client is for synthetic transport tests. Production creates
    a fresh public-only, DNS-pinned client, separate from the Canvas API session.
    """
    course, file = source_id(course), source_id(file)
    owned_http = http is None
    download_http = http or public_client(client.settings.request_timeout_seconds)
    raw_http = download_http

    def check_download(method, url):
        client.require_offline()
        if client.settings.profile == "synthetic" and not isinstance(
            raw_http._transport, httpx.MockTransport
        ):
            raise DomainError(
                "permission_denied",
                "Synthetic file reads require a mock transport.",
                reason_code="SYNTHETIC_NETWORK_DISABLED",
            )
        if method != "GET":
            raise DomainError("permission_denied", "Only file reads are permitted.")
        download_destination(url, client, course, file)
        client.authorize(Endpoint.FILE, {"course": course, "file": file}, "files")

    download_http = GuardedHTTP(download_http, check_download)
    try:
        async with asyncio.timeout(budget or client.settings.refresh_budget_seconds):
            metadata = (
                metadata if metadata is not None else await file_metadata(client, course, file)
            )
            mime = str(metadata.get("content-type", "")).split(";", 1)[0].strip().lower()
            kind = file_format(metadata)
            if max_bytes is None:
                max_bytes = (
                    client.settings.pptx_source_max_bytes if kind == "pptx" else MAX_FILE_BYTES
                )
            if not kind and sink is None:
                raise DomainError(
                    "unsupported_feature",
                    "The course file format is unsupported.",
                    reason_code="UNSUPPORTED_FILE_FORMAT",
                )
            size = metadata.get("size")
            if size is not None and (type(size) is not int or size < 0):
                raise DomainError(
                    "source_changed",
                    "Invalid source size metadata.",
                    reason_code="INVALID_SOURCE_SIZE",
                )

            def check_size(observed):
                if observed > max_bytes:
                    raise DomainError(
                        "unsupported_feature",
                        "The source file exceeds this workflow's byte limit.",
                        reason_code="FILE_TOO_LARGE",  # Schema 1.0 compatibility.
                        details={
                            "budget_code": "SOURCE_FILE_TOO_LARGE"
                            if sink is None
                            else "ORIGINAL_DELIVERY_LIMIT",
                            "limit_bytes": max_bytes,
                            "observed_size": observed,
                            "observed": observed,
                            "limit": max_bytes,
                            "retryable": False,
                        },
                    )

            if size is not None:
                check_size(size)
            url = metadata.get("url")
            if not isinstance(url, str):
                raise DomainError(
                    "unsupported_feature", "No approved course file download is available."
                )
            seen = set()
            for hop in range(MAX_REDIRECTS + 1):
                same_origin = download_destination(url, client, course, file)
                if url in seen:
                    raise DomainError("retry_later", "Course file redirects did not complete.")
                seen.add(url)
                headers = {"Accept-Encoding": "identity", "User-Agent": "CanvasBridge/0.1"}
                if hop == 0 and same_origin:
                    headers["Authorization"] = f"Bearer {client.token}"
                # Construct the request directly: no client cookies, default
                # Authorization, Referer or HTTP-auth fallback can cross hosts.
                request = httpx.Request("GET", url, headers=headers)
                from canvas_bridge.workflow_budget import active_budget, count_bytes, count_request

                if workflow_budget := active_budget.get():
                    workflow_budget.document(course, file)
                count_request()
                response = await download_http.send(
                    request, stream=True, auth=None, follow_redirects=False
                )
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            raise DomainError(
                                "retry_later", "Course file redirects did not complete."
                            )
                        # urljoin normalizes controls; reject before normalization.
                        if len(location) > 8192 or any(ord(c) < 33 for c in location):
                            raise DomainError("permission_denied", "Unsafe file redirect.")
                        url = urljoin(url, location)
                        continue
                    if response.status_code in {401, 403, 404}:
                        raise DomainError(
                            "permission_denied", "Course file download is unavailable."
                        )
                    if response.status_code != 200:
                        retry = response.headers.get("retry-after", "")
                        raise DomainError(
                            "retry_later",
                            "Course file download did not complete.",
                            reason_code="RATE_LIMITED"
                            if response.status_code == 429
                            else "UPSTREAM_UNAVAILABLE",
                            details={"retry_after_seconds": min(int(retry), 3600)}
                            if retry.isdecimal()
                            else {},
                        )
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise DomainError(
                            "unsupported_feature",
                            "Encoded file transfers are unsupported.",
                            reason_code="UNEXPECTED_UPSTREAM_CONTENT",
                        )
                    actual_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                    )
                    expected_types = {mime, "application/octet-stream"}
                    if kind in {"xlsx", "pptx"}:
                        expected_types.add(
                            "application/vnd.openxmlformats-officedocument."
                            + (
                                "spreadsheetml.sheet"
                                if kind == "xlsx"
                                else "presentationml.presentation"
                            )
                        )
                    if actual_type not in expected_types:
                        raise DomainError(
                            "source_changed",
                            "File type differs from its current metadata.",
                            reason_code="UNEXPECTED_UPSTREAM_CONTENT",
                        )
                    declared = response.headers.get("content-length")
                    if declared is not None and (not declared.isdecimal() or len(declared) > 20):
                        raise DomainError(
                            "source_changed",
                            "Invalid transfer size.",
                            reason_code="INCOMPLETE_TRANSFER",
                        )
                    declared = int(declared) if declared is not None else None
                    if declared is not None:
                        check_size(declared)
                    if declared is not None and size is not None and declared != size:
                        raise DomainError(
                            "source_changed",
                            "File size differs from its current metadata.",
                            reason_code="INCOMPLETE_TRANSFER",
                        )
                    data = bytearray()
                    prefix = bytearray()
                    digest = hashlib.sha256()
                    count = 0
                    async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                        count_bytes(len(chunk), document=True)
                        check_size(count + len(chunk))
                        if size is not None and count + len(chunk) > size:
                            raise DomainError(
                                "source_changed",
                                "File exceeded its declared size.",
                                reason_code="INCOMPLETE_TRANSFER",
                            )
                        prefix.extend(chunk[: max(0, 1024 - len(prefix))])
                        digest.update(chunk)
                        count += len(chunk)
                        if sink is None:
                            data.extend(chunk)
                        else:
                            sink.write(chunk)
                    if (size is not None and count != size) or (
                        declared is not None and count != declared
                    ):
                        raise DomainError(
                            "source_changed",
                            "The course file transfer is incomplete.",
                            reason_code="INCOMPLETE_TRANSFER",
                        )
                    start = bytes(prefix).lstrip().lower()
                    # Detect mislabelled login/error bodies without parsing or repairing
                    # legitimate HTML, JSON, malformed or encrypted originals.
                    binary_document = kind in {"pdf", "docx", "pptx", "xlsx"} or str(
                        metadata.get("filename", "")
                    ).lower().endswith(
                        (".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".docm", ".pptm")
                    )
                    if binary_document and start.startswith(
                        (b"<!doctype html", b"<html", b"{", b"[")
                    ):
                        raise DomainError(
                            "source_changed",
                            "Unexpected upstream error content.",
                            reason_code="UNEXPECTED_UPSTREAM_CONTENT",
                        )
                    if sink is None and (
                        (kind == "pdf" and not data.startswith(b"%PDF-"))
                        or (kind in {"docx", "pptx", "xlsx"} and not data.startswith(b"PK\x03\x04"))
                    ):
                        raise DomainError(
                            "unsupported_feature", "The file signature is unsupported."
                        )
                    validator = response.headers.get("etag") or response.headers.get(
                        "last-modified"
                    )
                    # Keep only a fingerprint of untrusted upstream validators in diagnostics.
                    return DownloadedFile(
                        bytes(data),
                        kind or "opaque",
                        file_version(metadata),
                        count,
                        digest.hexdigest(),
                        hashlib.sha256(validator.encode()).hexdigest() if validator else None,
                    )
                finally:
                    await response.aclose()
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        raise DomainError("retry_later", "The course file could not be downloaded safely.") from exc
    finally:
        if owned_http:
            await download_http.aclose()
    raise DomainError("retry_later", "Course file download budget exhausted.")


async def stream_original(client, course, file, metadata, sink, *, max_bytes, budget, http=None):
    """Stream authorized original bytes using the reader's credential-separated transport.

    The caller owns the private sink and deletes it on any failure/cancellation.
    Metadata is supplied only by the authorization service, never tool arguments.
    No parser, signature repair, content decoder or extraction cache is involved.
    """
    try:
        return await _download_once(
            client,
            course,
            file,
            http=http,
            sink=sink,
            metadata=metadata,
            max_bytes=max_bytes,
            budget=budget,
        )
    except DomainError as exc:
        if exc.reason_code is None:
            exc.reason_code = (
                "UNSAFE_UPSTREAM_LOCATION"
                if exc.status == "permission_denied" and "unavailable" not in exc.message.lower()
                else "UPSTREAM_UNAVAILABLE"
            )
        exc.processing_stage = "file_download"
        raise


async def download_file(client, course: str, file: str, *, http=None) -> DownloadedFile:
    """Renew an expired storage link once via freshly authorized Canvas metadata."""
    if not _reading_slot.acquire(blocking=False):
        raise DomainError(
            "retry_later",
            "Another source download is in progress.",
            reason_code="DOCUMENT_DOWNLOAD_BUSY",
            processing_stage="file_download",
        )
    try:
        metadata = await file_metadata(client, course, file)
        budget = (
            client.settings.pptx_download_budget_seconds
            if file_format(metadata) == "pptx"
            else client.settings.refresh_budget_seconds
        )
        async with asyncio.timeout(budget):
            for attempt in range(2):
                try:
                    return await _download_once(
                        client,
                        course,
                        file,
                        http=http,
                        metadata=metadata if attempt == 0 else None,
                        budget=budget,
                    )
                except DomainError as exc:
                    if (
                        attempt
                        or exc.status != "permission_denied"
                        or exc.message != "Course file download is unavailable."
                    ):
                        raise
    except DomainError as exc:
        if exc.processing_stage is None:
            exc.processing_stage = "file_download"
        if exc.reason_code is None:
            exc.reason_code = "DOCUMENT_DOWNLOAD_FAILED"
        raise
    except TimeoutError as exc:
        raise DomainError(
            "retry_later",
            "Course file download exceeded its total retry budget.",
            reason_code="DOCUMENT_DOWNLOAD_TIMEOUT",
            processing_stage="file_download",
        ) from exc
    finally:
        _reading_slot.release()
    raise DomainError(
        "retry_later",
        "Course file download did not complete.",
        reason_code="DOCUMENT_DOWNLOAD_FAILED",
        processing_stage="file_download",
    )
