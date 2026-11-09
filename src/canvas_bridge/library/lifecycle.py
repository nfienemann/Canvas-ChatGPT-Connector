"""Explicit owner mutations, purge receipts, export and legacy-copy boundaries."""

import base64
import hashlib
import io
import json
import zipfile
from datetime import timedelta

from sqlalchemy import select

from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.library.contracts import CHUNK, TERMINAL, fail
from canvas_bridge.library.models import (
    Account,
    Delivery,
    Export,
    Grant,
    Intake,
    Item,
    Job,
    Legacy,
    Representation,
    Selection,
    Tombstone,
    Version,
)
from canvas_bridge.lifecycle import journal_delete
from canvas_bridge.storage import aware


class Lifecycle:
    def retry_processing(self, browser, item_id, expected):
        with self.transaction(browser.owner) as (session, account, principal):
            self.session(session, browser, principal)
            item, version, grant = self.require_in_session(session, browser.owner, item_id)
            self.expect(item, grant, expected.model_dump())
            if not grant.payload["allow_processing"]:
                fail("CONSENT_REQUIRED")
            job = session.scalar(
                select(Job).where(Job.owner == browser.owner, Job.version == version.id)
            )
            if not job or job.state != "failed" or version.processing != "failed":
                fail("SOURCE_CHANGED", "source_changed")
            if aware(job.available_at) > self.now:
                fail("CAPACITY_UNAVAILABLE", "retry_later", retryable=True)
            job.state, job.attempts, job.lease, job.lease_until = "queued", 0, None, None
            job.generation, job.permission = account.generation, grant.revision
            job.available_at, version.processing = self.now, "queued"
            account.revision += 1
        return self.get(browser.owner, item_id, browser=True).data

    def update_metadata(self, browser, item_id, change):
        if any(not isinstance(t, str) or not 1 <= len(t) <= 60 for t in change.tags):
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        with self.transaction(browser.owner) as (session, account, principal):
            self.session(session, browser, principal)
            item, _, _ = self.require_in_session(session, browser.owner, item_id)
            if item.revision != change.expected_revision:
                fail("SOURCE_CHANGED", "source_changed")
            item.metadata_value = {
                "title": change.title,
                "tags": sorted(set(change.tags)),
                "collection_id": change.collection_id,
            }
            item.revision += 1
            account.revision += 1
        return self.get(browser.owner, item_id, browser=True).data

    def update_grants(self, browser, item_id, change):
        value = self.grants(change, opaque_id())
        with self.transaction(browser.owner) as (session, account, principal):
            self.session(session, browser, principal)
            item, version, grant = self.require_in_session(session, browser.owner, item_id)
            if (
                version.id != change.expected_version_id
                or grant.revision != change.expected_permission_revision
            ):
                fail("SOURCE_CHANGED", "source_changed")
            grant.payload, grant.revision = value, grant.revision + 1
            self.drop_representations(session, account, version.id)
            job = session.scalar(
                select(Job).where(Job.owner == browser.owner, Job.version == version.id)
            )
            if job:
                session.delete(job)
                session.flush()
            if value["allow_processing"]:
                session.add(
                    Job(
                        owner=browser.owner,
                        id=opaque_id(),
                        version=version.id,
                        generation=account.generation,
                        permission=grant.revision,
                        available_at=self.now,
                    )
                )
            version.processing = "queued" if value["allow_processing"] else "not_requested"
            account.revision += 1
        return self.get(browser.owner, item_id, browser=True).data

    def drop_representations(self, session, account, version_id):
        from canvas_bridge.processes.purge import purge_sources
        from canvas_bridge.worker_storage import invalidate

        purge_sources(session, account.owner, source_ids=("lib_" + version_id,))
        invalidate(account.owner, "lib_" + version_id, namespace=self.bridge.processing_namespace)
        for rep in session.scalars(
            select(Representation).where(
                Representation.owner == account.owner, Representation.version == version_id
            )
        ):
            account.derived_bytes -= rep.size
            session.delete(rep)
        for job in session.scalars(
            select(Job).where(Job.owner == account.owner, Job.version == version_id)
        ):
            job.state, job.lease = "cancelled", None

    def delete_item(self, browser, item_id, expected):
        owner = browser.owner
        with self.transaction(owner) as (session, account, principal):
            self.session(session, browser, principal)
            tomb = session.get(Tombstone, (owner, item_id))
            if tomb:
                return self.deletion_projection(tomb)
            item, _, grant = self.require_in_session(session, owner, item_id)
            self.expect(item, grant, expected.model_dump())
            tomb = self.fence_item(session, account, item)
            result = self.deletion_projection(tomb)
        self.purge(owner)
        return self.deletion(owner, result["deletion_id"])

    def fence_item(self, session, account, item):
        journal_delete(
            self.bridge.settings.deletion_journal,
            self.bridge.vault.key,
            "library-item:" + account.owner + ":" + item.id,
            account.revision + 1,
            now=self.now,
        )
        item.state = "deleting"
        account.revision += 1
        for version in session.scalars(
            select(Version).where(
                Version.owner == account.owner, Version.item == item.id, Version.state != "deleted"
            )
        ):
            version.state = "deleting"
            self.drop_representations(session, account, version.id)
        tomb = Tombstone(
            owner=account.owner,
            id=item.id,
            generation=account.revision,
            created_at=self.now,
            payload={
                "access": "disabled",
                "active_store": "pending",
                "backup_expiry": (self.now + timedelta(days=30)).isoformat(),
                "independent_copies": "Previously downloaded or host-conversation copies are controlled separately.",
            },
        )
        session.add(tomb)
        return tomb

    def deletion_projection(self, tomb):
        return {"deletion_id": tomb.id, "deletion_epoch": tomb.generation, **tomb.payload}

    def deletion(self, owner, ident):
        with self.bridge.store.transaction() as session:
            row = session.get(Tombstone, (owner, ident))
            if not row:
                fail("RESOURCE_UNAVAILABLE")
            return self.deletion_projection(row)

    def delete_account_in_session(self, session, owner):
        """Called under the existing principal lock and account-deletion journal fence."""
        account = session.scalar(select(Account).where(Account.owner == owner).with_for_update())
        if not account:
            return
        journal_delete(
            self.bridge.settings.deletion_journal,
            self.bridge.vault.key,
            "library-account:" + owner,
            account.generation + 1,
            now=self.now,
        )
        account.state, account.generation = "deleted", account.generation + 1
        for item in session.scalars(
            select(Item).where(Item.owner == owner, Item.state == "available")
        ):
            self.fence_item(session, account, item)
        for row in session.scalars(select(Selection).where(Selection.owner == owner)):
            if row.state not in TERMINAL:
                self.release_reservation(account, row, "cancelled")

    def purge(self, owner):
        removed, pending = 0, 0
        with self.transaction(owner) as (session, account, principal):
            if not account:
                return
            for version in session.scalars(
                select(Version).where(Version.owner == owner, Version.state == "deleting")
            ):
                try:
                    self.objects.delete(owner, version.object_key)
                except (DomainError, OSError):
                    pending += 1
                    continue
                self.drop_representations(session, account, version.id)
                removed += 1
                account.committed -= version.size
                version.state = "deleted"
                version.provenance = {"schema_version": "deleted", "sha256": version.digest}
                grant = session.get(Grant, (owner, version.id))
                if grant:
                    grant.payload = {
                        "allow_processing": False,
                        "recipients": [],
                        "purpose": "document_reading",
                    }
                    grant.revision += 1
            session.flush()
            for item in session.scalars(
                select(Item).where(Item.owner == owner, Item.state == "deleting")
            ):
                remaining = session.scalar(
                    select(Version.id)
                    .where(
                        Version.owner == owner, Version.item == item.id, Version.state != "deleted"
                    )
                    .limit(1)
                )
                if not remaining:
                    item.state, item.metadata_value = "deleted", {}
                    account.slots -= 1
                    tomb = session.get(Tombstone, (owner, item.id))
                    tomb.payload = {**tomb.payload, "active_store": "purged"}
            for selection in session.scalars(
                select(Selection).where(
                    Selection.owner == owner,
                    Selection.state.in_(["cancelled", "expired", "rejected", "failed"]),
                )
            ):
                try:
                    self.objects.delete(owner, selection.object_key)
                except (DomainError, OSError):
                    continue
                selection.payload = {
                    "selection_id": selection.payload["selection_id"],
                    "declared_bytes": selection.payload["declared_bytes"],
                    "chunks": [],
                    "receipts": [],
                    "reason_code": selection.payload.get("reason_code"),
                }
            # Terminal transfer manifests are not a second durable copy of names,
            # grants or ZIP member paths. Keep only reconciliation-safe receipts.
            for intake in session.scalars(select(Intake).where(Intake.owner == owner)):
                selections = list(
                    session.scalars(
                        select(Selection).where(
                            Selection.owner == owner, Selection.intake == intake.id
                        )
                    )
                )
                for row in selections:
                    if row.state == "published":
                        row.payload = {
                            k: v
                            for k, v in row.payload.items()
                            if k in {"selection_id", "declared_bytes", "reason_code", "receipts"}
                        } | {"chunks": []}
                if all(row.state in TERMINAL for row in selections):
                    intake.payload = {"retention": intake.payload["retention"]}
        if removed or pending:
            self.metric("purge", "partial" if pending else "ok")

    def sweep(self):
        if not self.bridge.settings.library_enabled and not self.bridge.settings.library_root:
            return
        self.sweep_operations()
        with self.bridge.store.transaction() as session:
            owners = list(session.scalars(select(Account.owner)))
        for owner in owners:
            with self.transaction(owner) as (session, account, principal):
                for intake in session.scalars(select(Intake).where(Intake.owner == owner)):
                    if intake.state not in TERMINAL and (
                        aware(intake.expires_at) <= self.now
                        or intake.principal_generation != principal.generation
                        or account.state != "active"
                    ):
                        for selection in session.scalars(
                            select(Selection).where(
                                Selection.owner == owner, Selection.intake == intake.id
                            )
                        ):
                            if selection.state not in TERMINAL:
                                self.release_reservation(account, selection, "expired")
                        intake.state = "expired"
                for item in session.scalars(
                    select(Item).where(Item.owner == owner, Item.state == "available")
                ):
                    versions = list(
                        session.scalars(
                            select(Version)
                            .where(
                                Version.owner == owner,
                                Version.item == item.id,
                                Version.state == "available",
                            )
                            .order_by(Version.created_at.desc())
                        )
                    )
                    for index, version in enumerate(versions):
                        if index >= 5 or (
                            version.expires_at and aware(version.expires_at) <= self.now
                        ):
                            if version.id == item.current:
                                self.fence_item(session, account, item)
                                break
                            journal_delete(
                                self.bridge.settings.deletion_journal,
                                self.bridge.vault.key,
                                "library-version:" + owner + ":" + version.id,
                                account.revision + 1,
                                now=self.now,
                            )
                            version.state = "deleting"
                            account.revision += 1
                            self.drop_representations(session, account, version.id)
                for rep in session.scalars(
                    select(Representation).where(
                        Representation.owner == owner, Representation.expires_at <= self.now
                    )
                ):
                    account.derived_bytes -= rep.size
                    session.delete(rep)
                    job = session.scalar(
                        select(Job).where(Job.owner == owner, Job.version == rep.version)
                    )
                    version = session.get(Version, (owner, rep.version))
                    if (
                        job
                        and version.state == "available"
                        and session.get(Grant, (owner, rep.version)).payload["allow_processing"]
                    ):
                        job.state, job.attempts, job.available_at = "queued", 0, self.now
                        version.processing = "queued"
                    account.revision += 1
                for export in session.scalars(
                    select(Export).where(Export.owner == owner, Export.expires_at <= self.now)
                ):
                    session.delete(export)
                for delivery in session.scalars(
                    select(Delivery).where(Delivery.owner == owner, Delivery.expires_at <= self.now)
                ):
                    session.delete(delivery)
            self.purge(owner)
        if self.bridge.settings.library_root:
            # Reconcile only against server-owned references; never adopt unknown objects.
            with self.bridge.store.transaction() as session:
                known = {
                    (hashlib.sha256(row.owner.encode()).hexdigest(), row.object_key)
                    for cls in (Version, Selection)
                    for row in session.scalars(select(cls))
                    if row.state not in {"deleted", "expired", "cancelled", "rejected", "failed"}
                }
            self.objects.reconcile(known, self.now.timestamp())

    def prepare_download(self, owner, item_id, version_id):
        from canvas_bridge.domain import Result

        if not self.permitted(owner, version_id, "metadata"):
            fail("CONSENT_REQUIRED")
        with self.transaction(owner) as (session, account, principal):
            _, version, grant = self.require_in_session(session, owner, item_id, version_id)
            current = list(
                session.scalars(
                    select(Delivery).where(Delivery.owner == owner, Delivery.expires_at > self.now)
                )
            )
            if len(current) >= 20:
                fail("QUOTA_EXCEEDED", "retry_later")
            row = Delivery(
                owner=owner,
                id=opaque_id(),
                version=version.id,
                permission=grant.revision,
                expires_at=self.now + timedelta(minutes=5),
            )
            session.add(row)
        return Result(
            summary="Open this short-lived route in your signed-in browser to download the exact original. This does not transfer the original to the model.",
            data={
                "delivery_id": row.id,
                "version_id": version_id,
                "expires_at": row.expires_at.isoformat(),
                "download_url": self.bridge.settings.resource_url.rstrip("/")
                + "/api/library/deliveries/"
                + row.id,
                "delivery_channel": "owner_session",
            },
            sources=[self.evidence(owner, version_id)],
        )

    def delivery(self, owner, ident):
        with self.bridge.store.transaction() as session:
            row = session.get(Delivery, (owner, ident))
            if not row or aware(row.expires_at) <= self.now:
                fail("RESOURCE_UNAVAILABLE")
            item, version, grant = self.require_in_session(session, owner, version_id=row.version)
            if grant.revision != row.permission:
                fail("CONSENT_REQUIRED")
            return item.id, version.id

    def create_export(self, browser, request):
        with self.transaction(browser.owner) as (session, account, principal):
            self.session(session, browser, principal)
            self.account(account)
            existing = session.scalar(
                select(Export).where(
                    Export.owner == browser.owner, Export.idempotency == request.idempotency_key
                )
            )
            if existing:
                if existing.payload["requested"] != request.versions:
                    fail("SOURCE_CHANGED", "source_changed")
                return {
                    "export_id": existing.id,
                    "state": "ready",
                    "expires_at": aware(existing.expires_at).isoformat(),
                }
            refs, excluded, size = [], [], 0
            for version_id in dict.fromkeys(request.versions):
                try:
                    _, version, grant = self.require_in_session(
                        session, browser.owner, version_id=version_id
                    )
                except DomainError:
                    excluded.append(
                        {"version_id": version_id, "reason_code": "RESOURCE_UNAVAILABLE"}
                    )
                    continue
                size += version.size
                refs.append({"version_id": version.id, "permission_revision": grant.revision})
            if size > 100 * 1024 * 1024:
                fail("QUOTA_EXCEEDED", "retry_later")
            existing = Export(
                owner=browser.owner,
                id=opaque_id(),
                idempotency=request.idempotency_key,
                payload={"requested": request.versions, "refs": refs, "excluded": excluded},
                expires_at=self.now + timedelta(minutes=15),
            )
            session.add(existing)
            return {
                "export_id": existing.id,
                "state": "ready",
                "excluded": excluded,
                "expires_at": aware(existing.expires_at).isoformat(),
            }

    def export_stream(self, owner, export_id, validate=lambda: None):
        def authorized():
            validate()
            with self.bridge.store.transaction() as session:
                row = session.get(Export, (owner, export_id))
                if not row or aware(row.expires_at) <= self.now:
                    fail("RESOURCE_UNAVAILABLE")
                for ref in row.payload["refs"]:
                    if (
                        self.require_in_session(session, owner, version_id=ref["version_id"])[
                            2
                        ].revision
                        != ref["permission_revision"]
                    ):
                        fail("CONSENT_REQUIRED")
                return row

        row = authorized()
        size = sum(
            self.require(owner, version=ref["version_id"])[1].size for ref in row.payload["refs"]
        )
        lease = self.claim_operation(owner, "export", size + 32 * 1024 * 1024)
        output, manifest = io.BytesIO(), []
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
                for ref in row.payload["refs"]:
                    self.check_operation(owner, lease)
                    item, version, grant = self.require(owner, version=ref["version_id"])
                    filename = version.id + "." + version.kind
                    _, original = self.original(owner, item.id, version.id, validate=authorized)
                    with archive.open(filename, "w") as member:
                        for block in original:
                            member.write(block)
                    manifest.append(
                        {
                            "filename": filename,
                            "metadata": self.projection(owner, item, version, grant, browser=True),
                            "lineage": version.provenance,
                            "grant_description": grant.payload,
                            "citation": "lib_" + version.id,
                        }
                    )
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "schema_version": "library-export-1",
                            "items": manifest,
                            "excluded": row.payload["excluded"],
                            "notice": "Exported grants are descriptions, never reimport authority.",
                        },
                        ensure_ascii=False,
                    ).encode(),
                )
            authorized()
            output.seek(0)
            from canvas_bridge.library.operations import ReservedStream

            return ReservedStream(self, owner, lease, output, authorized)
        except BaseException:
            output.close()
            self.release_operation(owner, lease)
            raise

    async def save_legacy(self, browser, document_id, request, validate=lambda: None):
        if document_id.startswith("lib_"):
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        old = self.bridge.independent.require(browser.owner, document_id)
        with self.bridge.store.transaction() as session:
            mapping = session.get(Legacy, (browser.owner, document_id))
        if mapping:
            item, version, _ = self.require(browser.owner, version=mapping.version)
            return self.get(browser.owner, item.id, version.id, browser=True).data
        data = base64.b64decode(old.content["bytes"])
        if (
            len(request.files) != 1
            or request.files[0].declared_bytes != len(data)
            or hashlib.sha256(data).hexdigest() != old.version_hash
        ):
            fail("SOURCE_CHANGED", "source_changed")
        # Retention is explicitly reviewed; existing temporary rows are never modified.
        for selected in request.recipient_grants:
            if (
                ("text" in selected.channels and not old.provenance.get("share_text"))
                or ("visual" in selected.channels and not old.provenance.get("share_visual"))
                or any(c in {"original", "audio"} for c in selected.channels)
            ):
                fail("CONSENT_REQUIRED")
        if request.purpose not in old.provenance.get("scope", []):
            fail("CONSENT_REQUIRED")
        receipt = self.create_intake(browser, request, legacy=document_id)
        selection = receipt["files"][0]
        for offset in range(selection["offset"], len(data), CHUNK):
            chunk = data[offset : offset + CHUNK]
            self.put_chunk(
                browser,
                receipt["intake_id"],
                selection["selection_id"],
                offset,
                hashlib.sha256(chunk).hexdigest(),
                chunk,
            )

        def current():
            validate()
            source = self.bridge.independent.require(browser.owner, document_id)
            if source.version_hash != old.version_hash:
                fail("SOURCE_CHANGED", "source_changed")

        return await self.complete(
            browser, receipt["intake_id"], {selection["selection_id"]: old.version_hash}, current
        )
