"""Short-lived original files, independent of extraction and host presentation.

One process owns a private staging directory. Grants are memory-only, so restart
revokes every reference. Possession of a separate random capability permits an
HTTP download; a delivery ID or digest never does. Every redemption rechecks the
original principal's current Canvas access and pinned source version.
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
import unicodedata
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from starlette.responses import JSONResponse, Response, StreamingResponse

from canvas_bridge.auth import READ_SCOPE, principal_id
from canvas_bridge.authorization import (
    RequestAuthorization,
    request_authorization,
    validate_request_authorization,
)
from canvas_bridge.course_files import authorized, checked_row
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.file_download import file_version, stream_original

HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}
OBJECT = re.compile(r"obj_[0-9a-f]{32}\.(?:part|blob)\Z")


def failure(code, message, status="retry_later"):
    return DomainError(status, message, reason_code=code, processing_stage="original_delivery")


def safe_filename(value):
    name = unicodedata.normalize("NFC", str(value or "download"))
    name = "".join(
        "_" if c in '/\\<>:"|?*' or unicodedata.category(c).startswith("C") else c for c in name
    )
    name = name.strip(" .") or "download"
    if name.split(".", 1)[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }:
        name = "_" + name
    suffix = Path(name).suffix[:24]
    stem = name[: -len(suffix)] if suffix else name
    while len((stem + suffix).encode("utf-8")) > 180:
        stem = stem[:-1]
    return stem + suffix


def delivery_mime(metadata):
    mime = str(metadata.get("content-type", "")).split(";", 1)[0].strip().lower()
    return (
        mime
        if re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", mime)
        else "application/octet-stream"
    )


def _secure_directory(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.is_junction():
        raise OSError("Staging cannot be a link")
    if os.name == "nt":
        import csv

        from canvas_bridge.windows_sandbox import acl

        # No shell, no user-provided command, no credential output.
        result = subprocess.run(  # noqa: S603
            [
                str(Path(os.environ["SystemRoot"]) / "System32/whoami.exe"),
                "/user",
                "/fo",
                "csv",
                "/nh",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        sid = next(csv.reader([result.stdout.strip()]))[1]
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise OSError("Unverified service identity")
        acl(root, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")
    else:
        root.chmod(0o700)


@dataclass(repr=False)
class Delivery:
    id: str
    owner: str
    connection: str
    institution: str
    course: str
    file: str
    epoch: int
    path: Path
    data: dict
    origin: str
    wall_start: float
    mono_start: float
    ttl: int
    active: int = 0
    revoked: bool = False
    capability_digest: str | None = field(default=None, repr=False)


class OriginalFiles:
    def __init__(self, bridge):
        self.bridge = bridge
        self.settings = bridge.settings
        self.root = None
        self.lockfile = None
        self.records = {}
        self.capabilities = {}
        self.active = {}
        self.reserved = 0
        self.pending = set()
        self.last_wall, self.last_mono = time.time(), time.monotonic()

    def start(self):
        if self.root is not None:
            return
        root = (
            self.settings.file_delivery_root
            or self.settings.vault_key_file.parent / "original-delivery"
        ).absolute()
        lock = None
        try:
            _secure_directory(root)
            lock = (root / ".lock").open("a+b")
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Exclusive ownership: no other process can have a legitimate transfer.
            for path in root.iterdir():
                if OBJECT.fullmatch(path.name) and path.is_file() and not path.is_symlink():
                    path.unlink()
            self.root, self.lockfile = root, lock
        except (OSError, DomainError, subprocess.SubprocessError) as exc:
            if lock:
                lock.close()
            raise failure(
                "STAGING_UNAVAILABLE", "Private download staging is unavailable."
            ) from exc

    def _expired(self, item):
        wall, mono = time.time(), time.monotonic()
        elapsed = mono - item.mono_start
        return (
            item.revoked
            or elapsed < 0
            or wall < item.wall_start
            or abs((wall - item.wall_start) - elapsed) > 5
            or max(wall - item.wall_start, elapsed) >= item.ttl
            or item.origin != self.settings.resource_url.rstrip("/")
        )

    def cleanup(self):
        wall, mono = time.time(), time.monotonic()
        jump = (
            wall < self.last_wall
            or mono < self.last_mono
            or abs((wall - self.last_wall) - (mono - self.last_mono)) > 5
        )
        self.last_wall, self.last_mono = wall, mono
        for item in list(self.records.values()):
            if jump:
                item.revoked = True
            if self._expired(item) and not item.active:
                self.revoke(item)
        if self.root is not None:
            retained = {item.path for item in self.records.values()} | self.pending
            for path in self.root.iterdir():
                if OBJECT.fullmatch(path.name) and path not in retained:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass  # Retry at next sweep; quota accounts for leftovers.

    def revoke(self, item):
        item.revoked = True
        if item.capability_digest:
            self.capabilities.pop(item.capability_digest, None)
        if not item.active:
            try:
                item.path.unlink(missing_ok=True)
            except OSError:
                return  # Retain the record; next periodic sweep retries Windows cleanup.
            self.records.pop(item.id, None)

    def close(self):
        for item in list(self.records.values()):
            self.revoke(item)
        if self.lockfile:
            self.lockfile.close()
            self.lockfile = None
        self.root = None

    @asynccontextmanager
    async def slot(self, owner):
        if sum(self.active.values()) >= 4 or self.active.get(owner, 0) >= 2:
            raise failure(
                "RATE_LIMITED",
                "Two downloads per person and four per server may run at once. Retry shortly.",
            )
        self.active[owner] = self.active.get(owner, 0) + 1
        try:
            yield
        finally:
            self.active[owner] -= 1
            if not self.active[owner]:
                del self.active[owner]

    async def prepare(
        self, owner, connection, file, expected_source_version=None, expected_bytes_sha256=None
    ):
        if not self.settings.file_delivery_enabled:
            raise failure(
                "HOST_DELIVERY_UNSUPPORTED",
                "Original file delivery is disabled on this server.",
                "unsupported_feature",
            )
        self.start()
        self.cleanup()
        path = None
        reserved = 0
        async with self.slot(owner):
            try:
                async with asyncio.timeout(self.settings.file_delivery_budget_seconds):
                    row, course, metadata, epoch = await authorized(
                        self.bridge, owner, connection, file
                    )
                    version = file_version(metadata)
                    if (
                        not version
                        or expected_source_version
                        and version != expected_source_version
                    ):
                        raise failure(
                            "SOURCE_CHANGED",
                            "Source version changed or cannot be verified. Request a fresh file.",
                            "source_changed",
                        )
                    size = metadata.get("size")
                    if (
                        type(size) is not int
                        or not 0 <= size <= self.settings.file_delivery_max_bytes
                    ):
                        raise DomainError(
                            "unsupported_feature",
                            "The original exceeds the configured download limit.",
                            reason_code="FILE_TOO_LARGE",
                            details={
                                "limit_bytes": self.settings.file_delivery_max_bytes,
                                "observed_size": size if type(size) is int else None,
                            },
                        )
                    used = sum(
                        p.stat().st_size
                        for p in self.root.iterdir()
                        if OBJECT.fullmatch(p.name) and p not in self.pending
                    )
                    if (
                        len(self.records) >= 256
                        or used + self.reserved + size > self.settings.file_delivery_staging_bytes
                        or shutil.disk_usage(self.root).free < size + 1024 * 1024
                    ):
                        raise failure(
                            "STAGING_UNAVAILABLE",
                            "Download staging is full. Retry after existing downloads expire.",
                        )
                    reserved = size
                    self.reserved += reserved
                    path = self.root / ("obj_" + uuid4().hex + ".part")
                    self.pending.add(path)
                    async with self.bridge.client(owner, connection) as client:
                        with path.open("xb") as sink:
                            async with (
                                self.bridge.synthetic.client()
                                if self.bridge.synthetic
                                else nullcontext(None) as http
                            ):
                                fetched = await stream_original(
                                    client,
                                    course.source_id,
                                    row.source_id,
                                    metadata,
                                    sink,
                                    max_bytes=self.settings.file_delivery_max_bytes,
                                    budget=self.settings.file_delivery_budget_seconds,
                                    http=http,
                                )
                            sink.flush()
                    if expected_bytes_sha256 and fetched.bytes_sha256 != expected_bytes_sha256:
                        raise failure(
                            "INTEGRITY_MISMATCH",
                            "The original bytes do not match the requested fingerprint.",
                            "source_changed",
                        )
                    current, _, after, after_epoch = await authorized(
                        self.bridge, owner, connection, file
                    )
                    if epoch != after_epoch or version != file_version(after):
                        raise failure(
                            "SOURCE_CHANGED",
                            "The source changed during retrieval. Request a fresh file.",
                            "source_changed",
                        )
                    with self.bridge.store.transaction() as session:
                        checked_row(self.bridge, session, owner, connection, file, epoch)
                        conn = self.bridge.store.connection(session, owner, connection)
                        institution = conn.institution
                    name = safe_filename(metadata.get("filename"))
                    now = utcnow()
                    ident = uuid4().hex
                    data = {
                        "file_id": file,
                        "course_id": course.id,
                        "course_name": course.name,
                        "filename": name,
                        "mime_type": delivery_mime(metadata),
                        "mime_origin": "authorized_canvas_metadata",
                        "byte_size": fetched.byte_size,
                        "bytes_sha256": fetched.bytes_sha256,
                        "source_version": version,
                        "source_url": current.url.split("?", 1)[0].split("#", 1)[0],
                        "source_checked_at": now.isoformat(),
                        "source_binding": {
                            "method": "metadata_before_and_after",
                            "upstream_validator_sha256": fetched.upstream_validator,
                        },
                        "original": True,
                        "delivery_id": ident,
                        "acquisition_state": "staged",
                        "delivery_state": "prepared",
                        "host_handoff": "not_attempted",
                        "transport_candidates": ["authenticated_http", "external_expiring_download"]
                        + (
                            ["host_embedded_resource"]
                            if size <= self.settings.file_delivery_inline_bytes
                            else ["host_resource_link"]
                        ),
                        "expires_at": (
                            now + timedelta(seconds=self.settings.file_delivery_ttl_seconds)
                        ).isoformat(),
                        "requires_server_online": True,
                        "limitations": [
                            "Metadata checks do not establish an immutable upstream snapshot.",
                            "Prepared bytes do not establish a user download or conversation attachment.",
                        ],
                    }
                    if name != metadata.get("filename"):
                        data["source_filename"] = str(metadata.get("filename", ""))[:1000]
                    promoted = path.with_suffix(".blob")
                    path.replace(promoted)
                    self.pending.discard(path)
                    path = promoted
                    item = Delivery(
                        ident,
                        owner,
                        connection,
                        institution,
                        course.id,
                        file,
                        epoch,
                        promoted,
                        data,
                        self.settings.resource_url.rstrip("/"),
                        time.time(),
                        time.monotonic(),
                        self.settings.file_delivery_ttl_seconds,
                    )
                    self.records[ident] = item
                    path = None
                    return Result(
                        summary="Original file prepared. Use Download original to request delivery; no download or attachment has been confirmed.",
                        data=data,
                    )
            except TimeoutError as exc:
                raise failure(
                    "UPSTREAM_UNAVAILABLE", "Original retrieval timed out. Retry the preparation."
                ) from exc
            except OSError as exc:
                raise failure(
                    "STAGING_UNAVAILABLE", "Private download staging is unavailable."
                ) from exc
            finally:
                self.reserved -= reserved
                if path is not None:
                    self.pending.discard(path)
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass  # Normal cleanup retries; preserve the original error.

    def lookup(self, ident, owner=None, connection=None):
        self.cleanup()
        if not self.settings.file_delivery_enabled:
            raise failure("DELIVERY_REVOKED", "Original delivery is disabled.", "permission_denied")
        item = self.records.get(ident)
        if not item or owner is not None and (item.owner != owner or item.connection != connection):
            raise failure(
                "DELIVERY_EXPIRED",
                "Download unavailable or expired. Get a fresh download.",
                "permission_denied",
            )
        if self._expired(item):
            raise failure(
                "DELIVERY_EXPIRED", "Download expired. Get a fresh download.", "permission_denied"
            )
        return item

    async def validate(self, item):
        try:
            row, course, metadata, epoch = await authorized(
                self.bridge, item.owner, item.connection, item.file
            )
            if epoch != item.epoch or course.id != item.course:
                raise failure(
                    "DELIVERY_REVOKED",
                    "The selected scope changed. Get a fresh download.",
                    "permission_denied",
                )
            if file_version(metadata) != item.data["source_version"]:
                raise failure(
                    "SOURCE_CHANGED",
                    "The file changed. Get a fresh download for the current original.",
                    "source_changed",
                )
            self.lookup(item.id, item.owner, item.connection)
            with self.bridge.store.transaction() as session:
                checked_row(
                    self.bridge, session, item.owner, item.connection, item.file, item.epoch
                )
                conn = self.bridge.store.connection(session, item.owner, item.connection)
                if conn.institution != item.institution:
                    raise failure(
                        "DELIVERY_REVOKED", "The connection changed.", "permission_denied"
                    )
            # A private object can still be damaged locally. Hash before sending any bytes.
            with item.path.open("rb") as stream:
                if (
                    os.fstat(stream.fileno()).st_size != item.data["byte_size"]
                    or hashlib.file_digest(stream, "sha256").hexdigest()
                    != item.data["bytes_sha256"]
                ):
                    raise failure(
                        "INTEGRITY_MISMATCH",
                        "The staged original failed its integrity check.",
                        "source_changed",
                    )
            return row
        except (DomainError, OSError):
            self.revoke(item)
            raise

    async def payload(self, owner, connection, ident):
        item = self.lookup(ident, owner, connection)
        async with self.slot(owner):
            item.active += 1
            try:
                await self.validate(item)
                capability = secrets.token_urlsafe(32)
                if item.capability_digest:
                    self.capabilities.pop(item.capability_digest, None)
                item.capability_digest = hashlib.sha256(capability.encode()).hexdigest()
                self.capabilities[item.capability_digest] = item.id
                url = item.origin + "/course-file-download/" + capability
                resource = {
                    "type": "resource_link",
                    "uri": url,
                    "name": item.data["filename"],
                    "mimeType": item.data["mime_type"],
                    "size": item.data["byte_size"],
                }
                if item.data["byte_size"] <= self.settings.file_delivery_inline_bytes:
                    resource = {
                        "type": "resource",
                        "resource": {
                            "uri": "canvas-file://delivery/"
                            + item.id
                            + "/"
                            + quote(item.data["filename"], safe=""),
                            "mimeType": item.data["mime_type"],
                            "blob": base64.b64encode(item.path.read_bytes()).decode("ascii"),
                        },
                    }
                return Result(
                    summary="Original payload prepared for a host handoff; download is not confirmed.",
                    data=item.data,
                ), {"resource": resource, "external_url": url}
            finally:
                item.active -= 1
                self.cleanup()


class DownloadLogFilter(logging.Filter):
    def filter(self, record):
        return "/course-file-download/" not in record.getMessage()


class OriginalResponse(StreamingResponse):
    """Release the lease even if the ASGI consumer fails before reading a chunk."""

    def __init__(self, content, headers, manager, item, slot):
        super().__init__(content, headers=headers)
        self.manager, self.item, self.slot = manager, item, slot

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(self.manager.settings.file_delivery_budget_seconds):
                await super().__call__(scope, receive, send)
        finally:
            try:
                await self.body_iterator.aclose()
            finally:
                self.item.active -= 1
                await self.slot.__aexit__(None, None, None)
                self.manager.cleanup()


def register_download_routes(mcp, bridge, verifier):
    manager = bridge.original_files
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, DownloadLogFilter) for f in access.filters):
        access.addFilter(DownloadLogFilter())

    async def serve(request, *, bearer):
        context = RequestAuthorization("download_original")
        context_token = request_authorization.set(context)
        stack = None
        item = None
        entered = False
        streaming = False
        try:
            if bearer:
                cap = request.path_params["capability"]
                if not re.fullmatch(r"[a-zA-Z0-9_-]{43}", cap):
                    raise failure(
                        "DELIVERY_EXPIRED", "Download unavailable or expired.", "permission_denied"
                    )
                ident = manager.capabilities.get(hashlib.sha256(cap.encode()).hexdigest())
                item = manager.lookup(ident)
            else:
                header = request.headers.get("authorization", "")
                token = (
                    await verifier.verify_token(header[7:])
                    if header.startswith("Bearer ")
                    else None
                )
                if (
                    not token
                    or READ_SCOPE not in token.scopes
                    or not token.subject
                    or not token.claims
                ):
                    return JSONResponse(
                        {"reason_code": "CONNECTION_NOT_AUTHORIZED"},
                        status_code=401,
                        headers={**HEADERS, "WWW-Authenticate": "Bearer"},
                    )
                owner = principal_id(token.claims["iss"], token.subject)
                candidate = manager.records.get(request.path_params["delivery_id"])
                item = manager.lookup(
                    request.path_params["delivery_id"],
                    owner,
                    candidate.connection if candidate else "",
                )
            stack = manager.slot(item.owner)
            await stack.__aenter__()
            entered = True
            item.active += 1
            await manager.validate(item)
            validate_request_authorization(bridge)
            headers = {
                **HEADERS,
                "Content-Type": item.data["mime_type"],
                "Content-Length": str(item.data["byte_size"]),
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(item.data["filename"], safe=""),
                "Accept-Ranges": "none",
            }
            # Deliberately serve a complete immutable representation for Range requests.
            # HEAD and retries never consume or renew a grant.
            if request.method == "HEAD":
                return Response(headers=headers)

            async def body(item=item):
                with item.path.open("rb") as stream:
                    while chunk := stream.read(64 * 1024):
                        yield chunk
                        await asyncio.sleep(0)

            response = OriginalResponse(body(), headers, manager, item, stack)
            streaming = True
            return response
        except DomainError as exc:
            status = (
                409
                if exc.status == "source_changed"
                else 403
                if exc.status in {"permission_denied", "reconnect_required"}
                else 503
            )
            return JSONResponse(
                {"status": exc.status, "summary": exc.message, **exc.data},
                status_code=status,
                headers=HEADERS,
            )
        except OSError:
            return JSONResponse(
                {"reason_code": "STAGING_UNAVAILABLE"}, status_code=503, headers=HEADERS
            )
        finally:
            if entered and not streaming:
                item.active -= 1
                await stack.__aexit__(None, None, None)
                manager.cleanup()
            request_authorization.reset(context_token)

    @mcp.custom_route("/course-file-download/{capability}", methods=["GET", "HEAD"])
    async def capability_download(request):
        return await serve(request, bearer=True)

    @mcp.custom_route("/course-file-original/{delivery_id}", methods=["GET", "HEAD"])
    async def authenticated_download(request):
        return await serve(request, bearer=False)
