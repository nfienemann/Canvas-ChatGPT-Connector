"""Course-scoped file metadata and bounded, credential-separated downloads.

This transport never parses documents. Binary MCP retrieval remains gated on an
OS-isolated parser. Signed download URLs stay transient and never become sources.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from canvas_bridge.domain import DomainError
from canvas_bridge.network import public_client
from canvas_bridge.policy import Endpoint, source_id, validate_https

MAX_FILE_BYTES = 10_000_000
MAX_REDIRECTS = 3
FILE_TYPES = {
    "application/pdf": ("pdf", ".pdf"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", ".docx"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("pptx", ".pptx"),
    "text/plain": ("txt", ".txt"),
    "text/markdown": ("md", ".md"),
    "text/x-markdown": ("md", ".md"),
    "text/html": ("html", ".html"),
}


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
    if source_id(metadata.get("id", "")) != file or not file_visible(metadata):
        raise DomainError("permission_denied", "The course file is currently unavailable.")
    return metadata


@dataclass(frozen=True, repr=False)
class DownloadedFile:
    # repr=False prevents accidental log output of private file bytes.
    data: bytes
    kind: str
    revision: str | None = None


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


async def _download_once(client, course: str, file: str, *, http=None) -> DownloadedFile:
    """Only fresh metadata from a course-qualified API can supply a download URL.

    An injected HTTP client is for synthetic transport tests. Production creates
    a fresh public-only, DNS-pinned client, separate from the Canvas API session.
    """
    course, file = source_id(course), source_id(file)
    owned_http = http is None
    download_http = http or public_client(client.settings.request_timeout_seconds)
    try:
        async with asyncio.timeout(client.settings.refresh_budget_seconds):
            metadata = await file_metadata(client, course, file)
            mime = str(metadata.get("content-type", "")).split(";", 1)[0].strip().lower()
            supported = FILE_TYPES.get(mime)
            name = metadata.get("filename")
            if (
                mime in {"text/plain", "application/octet-stream"}
                and isinstance(name, str)
                and name.lower().endswith(".md")
            ):
                supported = ("md", ".md")
            if (
                not supported
                or not isinstance(name, str)
                or not name.lower().endswith(supported[1])
            ):
                raise DomainError("unsupported_feature", "The course file format is unsupported.")
            size = metadata.get("size")
            if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
                raise DomainError("unsupported_feature", "The course file exceeds download limits.")
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
                        raise DomainError("retry_later", "Course file download did not complete.")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise DomainError(
                            "unsupported_feature", "Encoded file transfers are unsupported."
                        )
                    actual_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                    )
                    if actual_type not in {mime, "application/octet-stream"}:
                        raise DomainError(
                            "source_changed", "File type differs from its current metadata."
                        )
                    declared = response.headers.get("content-length")
                    if declared is not None and (not declared.isdecimal() or int(declared) != size):
                        raise DomainError(
                            "source_changed", "File size differs from its current metadata."
                        )
                    data = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(data) + len(chunk) > min(size, MAX_FILE_BYTES):
                            raise DomainError("source_changed", "File exceeded its declared size.")
                        data.extend(chunk)
                    if len(data) != size:
                        raise DomainError(
                            "source_changed", "The course file transfer is incomplete."
                        )
                    kind = supported[0]
                    if (kind == "pdf" and not data.startswith(b"%PDF-")) or (
                        kind in {"docx", "pptx"} and not data.startswith(b"PK\x03\x04")
                    ):
                        raise DomainError(
                            "unsupported_feature", "The file signature is unsupported."
                        )
                    return DownloadedFile(bytes(data), kind, file_version(metadata))
                finally:
                    await response.aclose()
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        raise DomainError("retry_later", "The course file could not be downloaded safely.") from exc
    finally:
        if owned_http:
            await download_http.aclose()
    raise DomainError("retry_later", "Course file download budget exhausted.")


async def download_file(client, course: str, file: str, *, http=None) -> DownloadedFile:
    """Renew an expired storage link once via freshly authorized Canvas metadata."""
    try:
        async with asyncio.timeout(client.settings.refresh_budget_seconds):
            for attempt in range(2):
                try:
                    return await _download_once(client, course, file, http=http)
                except DomainError as exc:
                    if (
                        attempt
                        or exc.status != "permission_denied"
                        or exc.message != "Course file download is unavailable."
                    ):
                        raise
    except TimeoutError as exc:
        raise DomainError(
            "retry_later", "Course file download exceeded its total retry budget."
        ) from exc
    raise DomainError("retry_later", "Course file download did not complete.")
