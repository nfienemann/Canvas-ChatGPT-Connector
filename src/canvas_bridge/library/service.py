"""Durable private library: publication, permission and deletion are separate commits."""

import asyncio
import hashlib
import io
import mimetypes
import re
import threading
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, select

from canvas_bridge.domain import DomainError, Result, opaque_id
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientPolicy
from canvas_bridge.evidence import fingerprint
from canvas_bridge.library import safety
from canvas_bridge.library.contracts import CHUNK, POLICY, TERMINAL, IntakeRequest, fail
from canvas_bridge.library.lifecycle import Lifecycle
from canvas_bridge.library.models import (
    Account,
    Admission,
    Grant,
    Intake,
    Item,
    Job,
    Legacy,
    Representation,
    Selection,
    Version,
)
from canvas_bridge.library.objects import EncryptedDirectory
from canvas_bridge.library.operations import Operations
from canvas_bridge.library.reading import Reading
from canvas_bridge.lifecycle import read_journal
from canvas_bridge.storage import BrowserSession, PrincipalState, aware


class Library(Reading, Lifecycle, Operations):
    def __init__(self, bridge):
        self.bridge = bridge
        self._objects = None
        if not hasattr(bridge.store, "library_lock"):
            bridge.store.library_lock = threading.RLock()

    @property
    def now(self):
        return self.bridge.retention.clock()

    def enabled(self):
        if not self.bridge.settings.library_enabled:
            fail("HOST_TRANSFER_UNAVAILABLE", "unsupported_feature")

    @property
    def objects(self):
        if self._objects is None:
            root = self.bridge.settings.library_root
            if root is None:
                fail("STORAGE_UNAVAILABLE", "retry_later")
            self._objects = EncryptedDirectory(
                root, self.bridge.vault.key, synthetic=self.bridge.settings.profile == "synthetic"
            )
        return self._objects

    @contextmanager
    def transaction(self, owner):
        with self.bridge.store.library_lock, self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if session.get_bind().dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            session.execute(insert(Admission).values(id=1, revision=0).on_conflict_do_nothing())
            session.scalar(select(Admission).where(Admission.id == 1).with_for_update())
            account = session.scalar(
                select(Account).where(Account.owner == owner).with_for_update()
            )
            yield session, account, principal

    def account(self, account):
        if not account or account.state != "active":
            fail(
                "RESTORE_ON_HOLD"
                if account and account.state == "restore_hold"
                else "RESOURCE_UNAVAILABLE"
            )

    @asynccontextmanager
    async def heavy(self, owner):
        lease = opaque_id()
        with self.transaction(owner) as (session, account, principal):
            self.account(account)
            active = session.scalar(
                select(func.count()).select_from(Account).where(Account.heavy_until > self.now)
            )
            if (account.heavy_until and aware(account.heavy_until) > self.now) or active >= 2:
                fail("PROCESSING_BUSY", "retry_later", retryable=True)
            account.heavy_key, account.heavy_until = lease, self.now + timedelta(minutes=5)
        try:
            yield
        finally:
            with self.transaction(owner) as (session, account, principal):
                if account and account.heavy_key == lease:
                    account.heavy_key, account.heavy_until = None, None

    def session(self, session, browser, principal):
        current = session.get(BrowserSession, browser.digest)
        if (
            not current
            or current.owner != browser.owner
            or current.generation != principal.generation
            or aware(current.expires_at) <= self.now
        ):
            fail("AUTH_REQUIRED")

    def status(self, owner):
        self.enabled()
        with self.bridge.store.transaction() as session:
            account = session.get(Account, owner)
        return Result(
            summary="Private library status. A chat attachment is not saved until an upload receipt confirms publication.",
            data={
                "policy_version": POLICY,
                "state": account.state if account else "not_provisioned",
                "quota": {
                    "committed_bytes": account.committed if account else 0,
                    "reserved_bytes": account.reserved if account else 0,
                    "items": account.slots if account else 0,
                    "reserved_items": account.reserved_slots if account else 0,
                    "maximum_bytes": self.bridge.settings.library_quota_bytes,
                    "maximum_items": self.bridge.settings.library_item_limit,
                    "derived_bytes": account.derived_bytes if account else 0,
                    "maximum_derived_bytes": self.bridge.settings.library_derived_bytes,
                },
                "limits": {
                    "document_bytes": 104857600,
                    "image_bytes": 26214400,
                    "chunk_bytes": CHUNK,
                    "selection_files": 20,
                    "extract_document_bytes": 10000000,
                    "extract_pptx_bytes": 25000000,
                    "transfer_seconds": self.bridge.settings.library_transfer_seconds,
                    "idle_seconds": self.bridge.settings.library_idle_seconds,
                    "ingress_requests": 4,
                    "export_original_bytes": 104857600,
                },
                "capabilities": {
                    "device_upload": "supported"
                    if self.bridge.settings.library_root
                    and self.bridge.settings.library_uploads_enabled
                    else "temporarily_unavailable",
                    "host_file_inputs": "unsupported",
                    "host_file_picker": "unverified",
                    "original_download": "supported",
                    "inline_images": "unverified",
                    "audio_video": "unsupported",
                },
                "upload_url": self.bridge.settings.resource_url.rstrip("/") + "/settings/library",
                "retention": {
                    "mode": "until_deleted",
                    "history_versions": 5,
                    "history_days": 30,
                    "temporary_import_hours": self.bridge.settings.independent_retention_hours,
                },
            },
        )

    def grants(self, request, action):
        profile = self.bridge.independent.profile()
        selected = []
        for grant in request.recipient_grants:
            if not profile or grant.recipient_profile_id != profile.policy_id:
                fail("RECIPIENT_UNVERIFIED")
            if "audio" in grant.channels:
                fail("UNSUPPORTED_MEDIA", "unsupported_feature")
            if any(c not in profile.channels for c in grant.channels):
                fail("CONSENT_REQUIRED")
            selected.append(
                {
                    "profile": profile.model_dump(mode="json"),
                    "channels": sorted(set(grant.channels)),
                }
            )
        return {
            "allow_processing": request.allow_processing,
            "purpose": request.purpose,
            "recipients": selected,
            "action_receipt": action,
            "policy_version": POLICY,
        }

    def create_intake(self, browser, request: IntakeRequest, *, replacement=None, legacy=None):
        self.enabled()
        if not self.bridge.settings.library_uploads_enabled:
            fail("STORAGE_UNAVAILABLE", "retry_later")
        owner = browser.owner
        if request.authorization_action_id != hashlib.sha256(browser.csrf.encode()).hexdigest():
            fail("CONSENT_REQUIRED")
        if request.retention.expires_at and request.retention.expires_at <= self.now:
            fail("RETENTION_REVIEW_REQUIRED", "needs_input")
        names = set()
        for file in request.files:
            if (
                file.selection_id in names
                or any(c in file.file_name for c in "/\\:\x00\r\n")
                or file.file_name in {".", ".."}
            ):
                fail("UNSUPPORTED_MEDIA", "needs_input")
            names.add(file.selection_id)
            kind = file.file_name.rsplit(".", 1)[-1].lower()
            if kind not in {
                "pdf",
                "docx",
                "pptx",
                "xlsx",
                "txt",
                "md",
                "png",
                "jpg",
                "jpeg",
                "zip",
            }:
                fail("UNSUPPORTED_MEDIA", "unsupported_feature")
            ceiling = (
                26214400
                if kind in {"png", "jpg", "jpeg"}
                else 50000000
                if kind == "zip"
                else 104857600
            )
            if file.declared_bytes != file.maximum_bytes or file.maximum_bytes > ceiling:
                fail("UPLOAD_TOO_LARGE", "needs_input")
        spec = request.model_dump(mode="json")
        spec.pop("authorization_action_id")
        spec["replacement"], spec["legacy"] = replacement, legacy
        digest = fingerprint(spec)
        action = opaque_id()
        grants = self.grants(request, action)
        with self.transaction(owner) as (session, account, principal):
            self.session(session, browser, principal)
            if account is None:
                account = Account(
                    owner=owner,
                    state="active",
                    generation=0,
                    revision=0,
                    committed=0,
                    reserved=0,
                    slots=0,
                    reserved_slots=0,
                    derived_bytes=0,
                )
                session.add(account)
                session.flush()
            self.account(account)
            existing = session.scalar(
                select(Intake).where(
                    Intake.owner == owner, Intake.idempotency == request.idempotency_key
                )
            )
            if existing:
                if existing.fingerprint != digest:
                    fail("SOURCE_CHANGED", "source_changed")
                return self.receipt_in_session(session, existing)
            if replacement:
                if len(request.files) != 1 or request.files[0].file_name.lower().endswith(".zip"):
                    fail("SOURCE_CHANGED", "needs_input")
                item, version, grant = self.require_in_session(
                    session, owner, replacement["item_id"]
                )
                self.expect(item, grant, replacement)
                # Replacement never widens inherited purpose, processing or recipients.
                grants["allow_processing"] &= grant.payload["allow_processing"]
                if grants["purpose"] != grant.payload["purpose"]:
                    fail("CONSENT_REQUIRED")
                for recipient in grants["recipients"]:
                    old = next(
                        (
                            g
                            for g in grant.payload["recipients"]
                            if RecipientPolicy.model_validate(g["profile"])
                            == RecipientPolicy.model_validate(recipient["profile"])
                        ),
                        None,
                    )
                    recipient["channels"] = sorted(
                        set(recipient["channels"]) & set(old["channels"] if old else [])
                    )
            intake = Intake(
                owner=owner,
                id=opaque_id(),
                idempotency=request.idempotency_key,
                fingerprint=digest,
                session_digest=browser.digest,
                generation=account.generation,
                principal_generation=principal.generation,
                payload={**spec, "grants": grants, "action_receipt": action},
                state="created",
                revision=1,
                created_at=self.now,
                expires_at=min(self.now + timedelta(hours=24), aware(browser.expires_at)),
            )
            session.add(intake)
            session.flush()
            for file in request.files:
                is_zip = file.file_name.lower().endswith(".zip")
                reserve = 200_000_000 if is_zip else file.maximum_bytes
                slots = 20 if is_zip else 0 if replacement else 1
                allowed = (
                    account.committed + account.reserved + reserve
                    <= self.bridge.settings.library_quota_bytes
                    and account.slots + account.reserved_slots + slots
                    <= self.bridge.settings.library_item_limit
                )
                deployed = session.scalar(
                    select(func.coalesce(func.sum(Account.committed + Account.reserved), 0))
                )
                allowed &= deployed + reserve <= self.bridge.settings.library_deployment_bytes
                selection = Selection(
                    owner=owner,
                    id=opaque_id(),
                    intake=intake.id,
                    size=reserve,
                    reserved_slots=slots,
                    offset=0,
                    state="created" if allowed else "rejected",
                    updated_at=self.now,
                    payload={
                        **file.model_dump(mode="json"),
                        "reason_code": None if allowed else "QUOTA_EXCEEDED",
                        "chunks": [],
                        "receipts": [],
                    },
                )
                session.add(selection)
                if allowed:
                    account.reserved += reserve
                    account.reserved_slots += slots
                session.flush()
            session.flush()
            return self.receipt_in_session(session, intake)

    def intake(self, session, owner, ident, browser=None, *, active=False):
        row = session.get(Intake, (owner, ident))
        if row is None:
            fail("RESOURCE_UNAVAILABLE")
        if active:
            account = session.get(Account, owner)
            self.account(account)
            principal = session.get(PrincipalState, owner)
            if browser:
                self.session(session, browser, principal)
            if (
                row.state in TERMINAL
                or row.generation != account.generation
                or row.principal_generation != principal.generation
                or aware(row.expires_at) <= self.now
                or (browser and row.session_digest != browser.digest)
            ):
                fail("TRANSFER_EXPIRED", "source_changed")
        return row

    def receipt_in_session(self, session, intake):
        files = []
        for selection in session.scalars(
            select(Selection)
            .where(Selection.owner == intake.owner, Selection.intake == intake.id)
            .order_by(Selection.id)
        ):
            receipts = []
            for stored in selection.payload.get("receipts", []):
                version = session.get(Version, (intake.owner, stored["version_id"]))
                rep = session.scalar(
                    select(Representation).where(
                        Representation.owner == intake.owner,
                        Representation.version == stored["version_id"],
                        Representation.expires_at > self.now,
                    )
                )
                receipts.append(
                    {
                        **stored,
                        "storage_state": version.state if version else "deleted",
                        "processing_state": version.processing
                        if version and version.state == "available"
                        else "unavailable",
                        "coverage": rep.payload.get("coverage", "unknown")
                        if rep
                        else "not_processed",
                    }
                )
            files.append(
                {
                    "selection_id": selection.id,
                    "client_selection_id": selection.payload["selection_id"],
                    "state": selection.state,
                    "offset": selection.offset,
                    "declared_bytes": selection.payload["declared_bytes"],
                    "reason_code": selection.payload.get("reason_code"),
                    "retryable": selection.state not in TERMINAL,
                    "next_action": "Read the published versions."
                    if receipts
                    else "Resume or cancel this upload.",
                    "items": receipts,
                }
            )
        states = {f["state"] for f in files}
        status = (
            "complete"
            if states == {"published"}
            else "partial"
            if "published" in states
            else intake.state
        )
        return {
            "schema_version": "library-intake-receipt-1",
            "intake_id": intake.id,
            "status": status,
            "retention": intake.payload["retention"],
            "revision": intake.revision,
            "expires_at": aware(intake.expires_at).isoformat(),
            "files": files,
            "correlation_id": intake.id,
        }

    def receipt(self, owner, ident):
        with self.bridge.store.transaction() as session:
            self.account(session.get(Account, owner))
            return self.receipt_in_session(session, self.intake(session, owner, ident))

    def put_chunk(self, browser, ident, selection_id, offset, checksum, data):
        if not data or len(data) > CHUNK or hashlib.sha256(data).hexdigest() != checksum:
            fail("CHECKSUM_MISMATCH", "needs_input")
        with self.transaction(browser.owner) as (session, account, principal):
            intake = self.intake(session, browser.owner, ident, browser, active=True)
            row = session.get(Selection, (browser.owner, selection_id))
            if not row or row.intake != intake.id:
                fail("RESOURCE_UNAVAILABLE")
            chunks = row.payload["chunks"]
            for chunk in chunks:
                if chunk["offset"] == offset:
                    if chunk["sha256"] != checksum or chunk["bytes"] != len(data):
                        fail("SOURCE_CHANGED", "source_changed")
                    return {"offset": row.offset, "replayed": True}
            if row.state not in {"created", "uploading"} or offset != row.offset:
                raise DomainError(
                    "source_changed",
                    "Resume at the authoritative upload offset.",
                    reason_code="SOURCE_CHANGED",
                    details={"offset": row.offset},
                )
            if (
                row.offset
                and (self.now - aware(row.updated_at)).total_seconds()
                > self.bridge.settings.library_idle_seconds
            ):
                fail("TRANSFER_EXPIRED", "source_changed")
            if (
                self.now - aware(intake.created_at)
            ).total_seconds() > self.bridge.settings.library_transfer_seconds:
                fail("TRANSFER_EXPIRED", "source_changed")
            uploads = list(
                session.scalars(
                    select(Selection.id).where(
                        Selection.owner == browser.owner, Selection.state == "uploading"
                    )
                )
            )
            if row.state == "created" and len(uploads) >= 2:
                fail("QUOTA_EXCEEDED", "retry_later", retryable=True)
            if offset + len(data) > row.payload["declared_bytes"] or (
                len(data) != CHUNK and offset + len(data) != row.payload["declared_bytes"]
            ):
                fail("UPLOAD_TOO_LARGE", "needs_input")
            self.objects.put_chunk(browser.owner, row.object_key, offset, data)
            row.payload = {
                **row.payload,
                "chunks": [*chunks, {"offset": offset, "bytes": len(data), "sha256": checksum}],
            }
            row.offset += len(data)
            row.state, row.updated_at = "uploading", self.now
            intake.state, intake.revision = "uploading", intake.revision + 1
            return {"offset": row.offset, "replayed": False}

    async def complete(self, browser, ident, hashes, validate=lambda: None):
        with self.bridge.store.transaction() as session:
            intake = self.intake(session, browser.owner, ident)
            if intake.state in TERMINAL:
                return self.receipt_in_session(session, intake)
            ids = list(
                session.scalars(
                    select(Selection.id).where(
                        Selection.owner == browser.owner, Selection.intake == ident
                    )
                )
            )
        for selection_id in ids:
            if selection_id not in hashes:
                continue
            try:
                await self.publish_selection(
                    browser, ident, selection_id, hashes.get(selection_id), validate
                )
            except DomainError as exc:
                transient = exc.reason_code in {
                    "SCAN_UNAVAILABLE",
                    "STORAGE_UNAVAILABLE",
                    "PROCESSING_BUSY",
                }
                with self.transaction(browser.owner) as (session, account, principal):
                    row = session.get(Selection, (browser.owner, selection_id))
                    if row and row.state not in TERMINAL:
                        row.payload = {
                            **row.payload,
                            "reason_code": exc.reason_code or "RESOURCE_UNAVAILABLE",
                        }
                        if not transient:
                            self.release_reservation(account, row, "rejected")
        with self.transaction(browser.owner) as (session, account, principal):
            intake = self.intake(session, browser.owner, ident)
            rows = list(
                session.scalars(
                    select(Selection).where(
                        Selection.owner == browser.owner, Selection.intake == ident
                    )
                )
            )
            if all(row.state in TERMINAL for row in rows):
                intake.state = (
                    "published" if any(row.state == "published" for row in rows) else "rejected"
                )
            intake.revision += 1
            return self.receipt_in_session(session, intake)

    async def publish_selection(self, browser, ident, selection_id, expected_hash, validate):
        async with self.heavy(browser.owner):
            return await self._publish_selection(
                browser, ident, selection_id, expected_hash, validate
            )

    async def _publish_selection(self, browser, ident, selection_id, expected_hash, validate):
        owner = browser.owner
        with self.transaction(owner) as (session, account, principal):
            intake = self.intake(session, owner, ident, browser, active=True)
            row = session.get(Selection, (owner, selection_id))
            if row.state in TERMINAL:
                return
            if row.offset != row.payload["declared_bytes"] or not re.fullmatch(
                r"[a-f0-9]{64}", expected_hash or ""
            ):
                fail("CHECKSUM_MISMATCH", "needs_input")
            if row.payload.get("expected_sha256") not in {None, expected_hash}:
                fail("CHECKSUM_MISMATCH", "needs_input")
            row.state = "validating"
            key, size, name = row.object_key, row.offset, row.payload["file_name"]
        data = await asyncio.to_thread(
            lambda: b"".join(self.objects.read(owner, key, size, expected_hash, published=False))
        )
        kind = name.rsplit(".", 1)[-1].lower()
        inspection = await safety.scan(data, kind, self.bridge.settings)
        validate()
        bodies = [(name, data, kind, key)]
        published_keys = set()
        if kind == "zip":
            bodies = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in inspection["members"]:
                    body = archive.read(member["member"])
                    if (
                        len(body) != member["bytes"]
                        or hashlib.sha256(body).hexdigest() != member["sha256"]
                    ):
                        fail("CHECKSUM_MISMATCH")
                    bodies.append((member["file_name"], body, member["kind"], opaque_id()))
        with self.transaction(owner) as (session, account, principal):
            intake = self.intake(session, owner, ident, browser, active=True)
            row = session.get(Selection, (owner, selection_id))
            if row.state == "published":
                return
            if row.state != "validating":
                fail("SOURCE_CHANGED", "source_changed")
            replacement = intake.payload.get("replacement")
            if replacement:
                item, _, old_grant = self.require_in_session(session, owner, replacement["item_id"])
                self.expect(item, old_grant, replacement)
            receipts = []
            for filename, body, media, object_key in bodies:
                digest = hashlib.sha256(body).hexdigest()
                self.bridge.independent.reject_institutional_copy(session, owner, digest)
                duplicate = None
                if not replacement and not intake.payload.get("legacy") and kind != "zip":
                    for candidate in session.scalars(
                        select(Version).where(
                            Version.owner == owner,
                            Version.digest == digest,
                            Version.state == "available",
                        )
                    ):
                        previous_item = session.get(Item, (owner, candidate.item))
                        previous_grant = session.get(Grant, (owner, candidate.id))
                        desired = intake.payload["grants"]
                        previous = previous_grant.payload if previous_grant else {}
                        same_recipients = len(previous.get("recipients", [])) == len(
                            desired["recipients"]
                        ) and all(
                            any(
                                RecipientPolicy.model_validate(a["profile"])
                                == RecipientPolicy.model_validate(b["profile"])
                                and set(a["channels"]) == set(b["channels"])
                                for b in desired["recipients"]
                            )
                            for a in previous.get("recipients", [])
                        )
                        if (
                            previous_item
                            and previous_item.state == "available"
                            and previous_item.current == candidate.id
                            and candidate.provenance.get("retention") == intake.payload["retention"]
                            and previous_item.metadata_value.get("collection_id")
                            == intake.payload["collection_id"]
                            and previous.get("allow_processing") == desired["allow_processing"]
                            and previous.get("purpose") == desired["purpose"]
                            and same_recipients
                            and (not candidate.expires_at or aware(candidate.expires_at) > self.now)
                        ):
                            duplicate = candidate
                            break
                if duplicate:
                    receipts.append(
                        {
                            "item_id": duplicate.item,
                            "version_id": duplicate.id,
                            "document_id": "lib_" + duplicate.id,
                            "size_bytes": duplicate.size,
                            "original_sha256": duplicate.digest,
                            "storage_state": "available",
                            "processing_state": duplicate.processing,
                            "coverage": "not_processed",
                            "warnings": [
                                "Identical bytes with the same retention and grants already exist; permissions were not expanded."
                            ],
                        }
                    )
                    continue
                if object_key != key:
                    for offset in range(0, len(body), CHUNK):
                        self.objects.put_chunk(
                            owner, object_key, offset, body[offset : offset + CHUNK]
                        )
                self.objects.publish(owner, object_key, len(body), digest)
                published_keys.add(object_key)
                version_id = opaque_id()
                item = session.get(Item, (owner, replacement["item_id"])) if replacement else None
                if item:
                    old = session.get(Version, (owner, item.current))
                    old.expires_at = (
                        min(aware(old.expires_at), self.now + timedelta(days=30))
                        if old.expires_at
                        else self.now + timedelta(days=30)
                    )
                    item.current, item.revision = version_id, item.revision + 1
                else:
                    item = Item(
                        owner=owner,
                        id=opaque_id(),
                        current=version_id,
                        metadata_value={
                            "title": filename,
                            "tags": [],
                            "collection_id": intake.payload["collection_id"],
                        },
                        created_at=self.now,
                    )
                    session.add(item)
                    account.slots += 1
                    session.flush()
                retention = intake.payload["retention"]
                expires = (
                    datetime.fromisoformat(retention["expires_at"])
                    if retention.get("expires_at")
                    else None
                )
                provenance = {
                    "schema_version": "library-provenance-1",
                    "source_origin": "independent_user_supplied",
                    "owner": owner,
                    "sha256": digest,
                    "acquisition_channel": "browser_upload",
                    "action_receipt": intake.payload["action_receipt"],
                    "policy_version": POLICY,
                    "retention": retention,
                    "filename": filename,
                    "legacy": intake.payload.get("legacy"),
                    "archive_sha256": expected_hash if kind == "zip" else None,
                    "institutional_connection": None,
                    "copyright": "owner_attested",
                }
                grant_data = intake.payload["grants"]
                version = Version(
                    owner=owner,
                    id=version_id,
                    item=item.id,
                    digest=digest,
                    size=len(body),
                    object_key=object_key,
                    kind=media,
                    state="available",
                    processing="queued" if grant_data["allow_processing"] else "not_requested",
                    provenance=provenance,
                    created_at=self.now,
                    expires_at=expires,
                )
                session.add(version)
                session.flush()
                session.add(Grant(owner=owner, id=version.id, revision=1, payload=grant_data))
                if grant_data["allow_processing"]:
                    session.add(
                        Job(
                            owner=owner,
                            id=opaque_id(),
                            version=version.id,
                            generation=account.generation,
                            permission=1,
                            available_at=self.now,
                        )
                    )
                if intake.payload.get("legacy"):
                    previous = session.get(Legacy, (owner, intake.payload["legacy"]))
                    if not previous:
                        session.add(
                            Legacy(
                                owner=owner,
                                id=intake.payload["legacy"],
                                version=version.id,
                                digest=digest,
                            )
                        )
                account.committed += len(body)
                receipts.append(
                    {
                        "item_id": item.id,
                        "version_id": version.id,
                        "document_id": "lib_" + version.id,
                        "size_bytes": version.size,
                        "original_sha256": digest,
                        "storage_state": "available",
                        "processing_state": version.processing,
                        "coverage": "not_processed",
                        "warnings": [],
                    }
                )
            self.release_reservation(account, row, "published")
            row.payload = {
                **row.payload,
                "receipts": receipts,
                "excluded": inspection.get("excluded", []),
                "reason_code": None,
            }
            account.revision += 1
            intake.revision += 1
        if key not in published_keys:
            self.objects.delete(owner, key)

    @staticmethod
    def release_reservation(account, row, state):
        if row.state not in TERMINAL:
            account.reserved -= row.size
            account.reserved_slots -= row.reserved_slots
        row.state = state

    def cancel(self, browser, ident, revision):
        keys = []
        with self.transaction(browser.owner) as (session, account, principal):
            self.session(session, browser, principal)
            intake = self.intake(session, browser.owner, ident)
            if intake.state in TERMINAL:
                return self.receipt_in_session(session, intake)
            if intake.revision != revision:
                fail("SOURCE_CHANGED", "source_changed")
            for row in session.scalars(
                select(Selection).where(Selection.owner == browser.owner, Selection.intake == ident)
            ):
                if row.state not in TERMINAL:
                    self.release_reservation(account, row, "cancelled")
                    keys.append(row.object_key)
            intake.state, intake.revision = "cancelled", intake.revision + 1
            result = self.receipt_in_session(session, intake)
        for key in keys:
            self.objects.delete(browser.owner, key)
        return result

    def require_in_session(self, session, owner, item_id=None, version_id=None):
        self.enabled()
        self.account(session.get(Account, owner))
        if version_id:
            version = session.get(Version, (owner, version_id))
            item = session.get(Item, (owner, version.item)) if version else None
            if item_id and item and item.id != item_id:
                fail("RESOURCE_UNAVAILABLE")
        else:
            item = session.get(Item, (owner, item_id))
            version = session.get(Version, (owner, item.current)) if item else None
        if (
            not item
            or not version
            or item.state != "available"
            or version.state != "available"
            or (version.expires_at and aware(version.expires_at) <= self.now)
        ):
            fail("RESOURCE_UNAVAILABLE")
        try:
            fences = read_journal(self.bridge.settings.deletion_journal, self.bridge.vault.key)
        except Exception:
            fail("RESTORE_ON_HOLD", "retry_later")
        if any(
            ref in fences
            for ref in (
                "library-account:" + owner,
                "library-item:" + owner + ":" + item.id,
                "library-version:" + owner + ":" + version.id,
            )
        ):
            fail("RESOURCE_UNAVAILABLE")
        p = version.provenance
        if (
            p.get("schema_version") != "library-provenance-1"
            or p.get("owner") != owner
            or p.get("sha256") != version.digest
            or p.get("institutional_connection")
            or not p.get("action_receipt")
        ):
            fail("RESOURCE_UNAVAILABLE")
        self.bridge.independent.reject_institutional_copy(session, owner, version.digest)
        grant = session.get(Grant, (owner, version.id))
        if not grant:
            fail("CONSENT_REQUIRED")
        return item, version, grant

    def require(self, owner, item=None, version=None):
        with self.bridge.store.transaction() as session:
            return self.require_in_session(session, owner, item, version)

    @staticmethod
    def expect(item, grant, expected):
        if (
            item.current != expected["expected_version_id"]
            or item.revision != expected["expected_revision"]
            or grant.revision != expected["expected_permission_revision"]
        ):
            fail("SOURCE_CHANGED", "source_changed")

    def permitted(self, owner, version, channel, *, transfer=None, purpose=None):
        _, _, grant = self.require(owner, version=version)
        return self.grant_permitted(grant, channel, transfer=transfer, purpose=purpose)

    def grant_permitted(self, grant, channel, *, transfer=None, purpose=None):
        """Evaluate a loaded grant; callers still enforce current owner/version fences."""
        profile = self.bridge.independent.profile()
        if not profile:
            return False
        from canvas_bridge.authorization import request_authorization

        context = request_authorization.get()
        recipient = transfer.recipient if transfer else getattr(context, "egress_identity", None)
        if not recipient:
            return False
        if self.bridge.settings.profile != "synthetic" and (
            recipient.recipient,
            recipient.issuer,
            recipient.client_id,
            recipient.environment,
            recipient.workspace,
        ) != (
            profile.recipient,
            profile.issuer,
            profile.client_id,
            profile.environment,
            profile.workspace,
        ):
            return False
        if recipient.recipient != profile.recipient:
            return False
        if (
            channel != "metadata"
            and not grant.payload["allow_processing"]
            and channel != "original"
        ):
            return False
        if (
            purpose in {"study", "grade_planning", "schedule"}
            and grant.payload["purpose"] != purpose
        ):
            return False
        if purpose and purpose not in profile.purposes:
            return False
        return any(
            RecipientPolicy.model_validate(g["profile"]) == profile and channel in g["channels"]
            for g in grant.payload["recipients"]
        )

    def projection(self, owner, item, version, grant, *, browser=False):
        with self.bridge.store.transaction() as session:
            rep = session.scalar(
                select(Representation).where(
                    Representation.owner == owner,
                    Representation.version == version.id,
                    Representation.expires_at > self.now,
                )
            )
        ready = bool(rep)
        channels = [
            c
            for c in ("metadata", "text", "visual", "original")
            if browser or self.grant_permitted(grant, c)
        ]
        mime = mimetypes.guess_type(version.provenance["filename"])[0] or "application/octet-stream"
        return {
            "schema_version": "library-item-1",
            "item_id": item.id,
            "version_id": version.id,
            "document_id": "lib_" + version.id,
            "title": item.metadata_value["title"],
            "tags": item.metadata_value.get("tags", []),
            "collection_id": item.metadata_value.get("collection_id"),
            "media_kind": "image" if version.kind in {"png", "jpg", "jpeg"} else "document",
            "mime_type": mime,
            "size_bytes": version.size,
            "original_sha256": version.digest,
            "created_at": aware(version.created_at).isoformat(),
            "storage_state": version.state,
            "processing_state": version.processing
            if ready or version.processing not in {"ready", "partial"}
            else "queued",
            "coverage": rep.payload.get("coverage", "unknown") if rep else "not_processed",
            "retention": {"mode": "expires_at", "expires_at": aware(version.expires_at).isoformat()}
            if version.expires_at
            else {"mode": "until_deleted"},
            "source_origin": version.provenance["source_origin"],
            "acquisition_channel": version.provenance["acquisition_channel"],
            "capabilities": {
                "read_text": "supported" if ready else "temporarily_unavailable",
                "search_text": "supported" if ready else "temporarily_unavailable",
                "render_visual": "supported"
                if version.kind in {"pdf", "png", "jpg", "jpeg"}
                else "unverified"
                if version.kind == "pptx"
                else "unsupported",
                "download_original": "supported",
                "audio_video": "unsupported",
            },
            "permitted_channels": channels,
            "warnings": [
                "Storage, extraction, pixel delivery and model interpretation are separate states."
            ],
            "metadata_revision": item.revision,
            "permission_revision": grant.revision,
        }

    def get(self, owner, item_id, version_id=None, *, browser=False):
        item, version, grant = self.require(owner, item_id, version_id)
        if not browser and not self.permitted(owner, version.id, "metadata"):
            fail("RESOURCE_UNAVAILABLE")
        projection = self.projection(owner, item, version, grant, browser=browser)
        if browser:
            profile = self.bridge.independent.profile()
            projection["sharing"] = {
                "allow_processing": grant.payload["allow_processing"],
                "purpose": grant.payload["purpose"],
                "channels": sorted(
                    {
                        c
                        for g in grant.payload["recipients"]
                        if profile and RecipientPolicy.model_validate(g["profile"]) == profile
                        for c in g["channels"]
                    }
                ),
            }
        result = Result(summary="Private library item and exact original version.", data=projection)
        if not browser:
            result.sources = [self.evidence(owner, version.id)]
        self.require(owner, item_id, version.id)
        return result

    def cursor(self, owner, operation, scope, offset, revision):
        return self.bridge.vault.seal(
            {
                "operation": operation,
                "scope": fingerprint(scope),
                "offset": offset,
                "revision": revision,
                "expires": (self.now + timedelta(minutes=15)).isoformat(),
            },
            owner,
            "library-cursor",
        )

    def read_cursor(self, owner, value, operation, scope, revision):
        if value is None:
            return 0
        try:
            if len(value) > 4000:
                raise ValueError
            record = self.bridge.vault.open(value, owner, "library-cursor")
            if (
                record["operation"] != operation
                or record["scope"] != fingerprint(scope)
                or record["revision"] != revision
                or datetime.fromisoformat(record["expires"]) <= self.now
            ):
                raise ValueError
            return record["offset"]
        except Exception:
            fail("SOURCE_CHANGED", "source_changed")

    def list(
        self, owner, *, limit=20, cursor=None, collection=None, tag=None, query=None, browser=False
    ):
        if not 1 <= limit <= 50 or (query and len(query) > 200):
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        with self.bridge.store.transaction() as session:
            account = session.get(Account, owner)
            if not account:
                return Result(
                    summary="The library is empty.", data={"items": [], "next_cursor": None}
                )
            self.account(account)
            revision = account.revision
            rows = list(
                session.scalars(
                    select(Item)
                    .where(Item.owner == owner, Item.state == "available")
                    .order_by(Item.id)
                    .limit(self.bridge.settings.library_item_limit)
                )
            )
        # Cheap denial before bounded, authoritative checks. Never use this grant
        # snapshot to authorize a returned source; selected versions are reread below.
        with self.bridge.store.transaction() as session:
            grants = (
                {
                    g.id: g
                    for g in session.scalars(
                        select(Grant)
                        .join(Item, (Grant.owner == Item.owner) & (Grant.id == Item.current))
                        .where(Item.owner == owner, Item.state == "available")
                    )
                }
                if not browser
                else {}
            )
        scope = {
            "collection": collection,
            "tag": tag,
            "query": query,
            "browser": browser,
            "paging": 2,
        }
        offset = self.read_cursor(owner, cursor, "list", scope, revision)
        items, sources, eligible, next_offset = [], [], [], None
        for index, row in enumerate(rows[offset:], offset):
            if (
                collection
                and row.metadata_value.get("collection_id") != collection
                or tag
                and tag not in row.metadata_value.get("tags", [])
                or query
                and query.casefold() not in row.metadata_value["title"].casefold()
            ):
                continue
            if not browser and (
                row.current not in grants
                or not self.grant_permitted(grants[row.current], "metadata")
            ):
                continue
            try:
                _, version, grant = self.require(owner, row.id)
                if browser or self.grant_permitted(grant, "metadata"):
                    if len(eligible) == limit:
                        next_offset = index
                        break
                    eligible.append((row, version, grant))
            except DomainError:
                continue
        for item, version, grant in eligible:
            items.append(
                self.get(owner, item.id, version.id, browser=True).data
                if browser
                else self.projection(owner, item, version, grant)
            )
            if not browser:
                sources.append(self.evidence(owner, version.id))
        with self.bridge.store.transaction() as session:
            if session.get(Account, owner).revision != revision:
                fail("SOURCE_CHANGED", "source_changed")
        continuation = (
            self.cursor(owner, "list", scope, next_offset, revision)
            if next_offset is not None
            else None
        )
        return Result(
            summary="Private library items permitted for this recipient.",
            data={"items": items, "next_cursor": continuation},
            sources=sources,
        )

    def evidence(self, owner, version_id, locator=None):
        from canvas_bridge.domain import Source

        _, version, grant = self.require(owner, version=version_id)
        with self.bridge.store.transaction() as session:
            rep = session.scalar(
                select(Representation).where(
                    Representation.owner == owner,
                    Representation.version == version_id,
                    Representation.expires_at > self.now,
                )
            )
            representation = [rep.id, rep.digest] if rep else None
        return Source(
            id="lib_" + version.id,
            resource_id="lib_" + version.id,
            url="",
            title="Private library source",
            retrieved_at=aware(version.created_at),
            locator=locator,
            classification="student_input",
            source_type="local_document",
            content_hash=version.digest,
            semantic_hash=fingerprint([version.id, version.digest, grant.revision, representation]),
            hash_basis="immutable_original_and_permission_revision",
            extraction_status=version.processing,
            uncertainty=[
                "Independent origin is owner attested; assistance permission is separate."
            ],
        )

    def sources(self, owner, result):
        from canvas_bridge.egress_models import SourceContext

        sources = []
        for source in result.sources:
            if not source.id.startswith("lib_"):
                fail("RESOURCE_UNAVAILABLE")
            current = self.evidence(owner, source.id[4:])
            if (
                source.content_hash != current.content_hash
                or source.semantic_hash != current.semantic_hash
            ):
                fail("SOURCE_CHANGED", "source_changed")
            sources.append(
                SourceContext(
                    "__independent__",
                    owner,
                    source.id,
                    current.content_hash,
                    "local_document",
                    CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                    derived=True,
                    content_sha256=current.content_hash,
                )
            )
        return tuple(sources) or (
            SourceContext(
                "__public__", owner, "library-status", "", "safe_status", CC.PUBLIC_OR_APPROVED
            ),
        )
