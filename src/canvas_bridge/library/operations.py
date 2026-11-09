"""Shared capacity leases and content-free operator diagnostics. No model tools."""

import logging
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.library.contracts import TERMINAL, fail
from canvas_bridge.library.models import (
    Account,
    Item,
    Job,
    Metric,
    OperationLease,
    Representation,
    Selection,
    Version,
)
from canvas_bridge.lifecycle import read_journal
from canvas_bridge.storage import aware


class ReservedStream:
    """Bounded in-memory archive whose capacity is released on close/disconnect."""

    def __init__(self, library, owner, lease, output, validate):
        self.library, self.owner, self.lease = library, owner, lease
        self.output, self.validate, self.closed = output, validate, False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        try:
            self.library.check_operation(self.owner, self.lease)
            self.validate()
            block = self.output.read(65536)
            if block:
                return block
            self.close()
            raise StopIteration
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            self.output.close()
            self.library.release_operation(self.owner, self.lease)


class Operations:
    def claim_operation(self, owner, kind, size=0):
        limits = {"ingress": (4, 16, 70), "export": (1, 2, 300), "backup": (1, 1, 900)}
        if kind not in limits or size < 0:
            raise ValueError("Unknown operation capacity class.")
        per_owner, deployed, seconds = limits[kind]
        with self.transaction(owner) as (session, account, principal):
            if kind != "ingress":
                self.account(account)
            session.execute(delete(OperationLease).where(OperationLease.expires_at <= self.now))
            leases = list(
                session.scalars(select(OperationLease).where(OperationLease.kind == kind))
            )
            if (
                sum(row.owner == owner for row in leases) >= per_owner
                or len(leases) >= deployed
                or (
                    kind == "export"
                    and sum(row.size for row in leases) + size
                    > self.bridge.settings.library_export_memory_bytes
                )
            ):
                fail("CAPACITY_UNAVAILABLE", "retry_later", retryable=True)
            lease = OperationLease(
                owner=owner,
                id=opaque_id(),
                kind=kind,
                size=size,
                expires_at=self.now + timedelta(seconds=seconds),
            )
            session.add(lease)
        return lease.id

    def check_operation(self, owner, ident):
        with self.bridge.store.transaction() as session:
            lease = session.get(OperationLease, (owner, ident))
            if not lease or aware(lease.expires_at) <= self.now:
                fail("TRANSFER_EXPIRED", "source_changed")

    def release_operation(self, owner, ident):
        with self.transaction(owner) as (session, account, principal):
            session.execute(
                delete(OperationLease).where(
                    OperationLease.owner == owner, OperationLease.id == ident
                )
            )

    @contextmanager
    def operation(self, owner, kind, size=0):
        ident = self.claim_operation(owner, kind, size)
        try:
            yield lambda: self.check_operation(owner, ident)
        finally:
            self.release_operation(owner, ident)

    def metric(self, event, outcome, *, size=0, milliseconds=0):
        if event not in {
            "request",
            "upload",
            "processing",
            "purge",
            "backup",
            "restore",
            "checksum",
        } or outcome not in {"ok", "failed", "denied", "held", "partial"}:
            raise ValueError("Diagnostics accept only reviewed categories.")
        if size < 0 or milliseconds < 0:
            raise ValueError("Diagnostics accept only nonnegative counters.")
        try:
            with self.bridge.store.transaction() as session:
                if session.get_bind().dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                stmt = insert(Metric).values(
                    day=self.now.date().isoformat(),
                    event=event,
                    outcome=outcome,
                    count=1,
                    bytes=size,
                    milliseconds=milliseconds,
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[Metric.day, Metric.event, Metric.outcome],
                        set_={
                            "count": Metric.count + 1,
                            "bytes": Metric.bytes + size,
                            "milliseconds": Metric.milliseconds + milliseconds,
                        },
                    )
                )
        except (SQLAlchemyError, OSError):
            # Diagnostics cannot leak driver exceptions or turn an error into success.
            logging.getLogger(__name__).warning("Library aggregate diagnostics unavailable.")

    def health(self, *, verify_originals=False, verify_backups=False):
        """Read-only operator summary: counts/reasons, no owners, titles, paths or source bytes."""
        alerts, drift, checked, corrupt = set(), 0, 0, 0
        try:
            read_journal(self.bridge.settings.deletion_journal, self.bridge.vault.key)
        except Exception:
            alerts.add("DELETION_JOURNAL_UNAVAILABLE")
        with self.bridge.store.transaction() as session:
            accounts = list(session.scalars(select(Account)))
            versions = list(session.scalars(select(Version).where(Version.state != "deleted")))
            items = list(session.scalars(select(Item).where(Item.state != "deleted")))
            selections = list(
                session.scalars(select(Selection).where(Selection.state.not_in(TERMINAL)))
            )
            reps = list(session.scalars(select(Representation)))
            jobs = list(session.scalars(select(Job)))
            leases = list(session.scalars(select(OperationLease)))
            metrics = [
                {
                    "day": m.day,
                    "event": m.event,
                    "outcome": m.outcome,
                    "count": m.count,
                    "bytes": m.bytes,
                    "milliseconds": m.milliseconds,
                }
                for m in session.scalars(select(Metric))
            ]
        for account in accounts:
            who = account.owner
            expected = (
                sum(v.size for v in versions if v.owner == who),
                sum(s.size for s in selections if s.owner == who),
                sum(i.owner == who for i in items),
                sum(s.reserved_slots for s in selections if s.owner == who),
                sum(r.size for r in reps if r.owner == who),
            )
            actual = (
                account.committed,
                account.reserved,
                account.slots,
                account.reserved_slots,
                account.derived_bytes,
            )
            drift += expected != actual
        if drift:
            alerts.add("QUOTA_DRIFT")
        purge = sum(v.state == "deleting" for v in versions)
        if purge:
            alerts.add("PURGE_BACKLOG")
        if any(j.state == "failed" for j in jobs):
            alerts.add("PROCESSING_FAILURES")
        if any(m["event"] == "checksum" and m["outcome"] == "failed" for m in metrics):
            alerts.add("CHECKSUM_FAILURES")
        if any(a.state == "restore_hold" for a in accounts):
            alerts.add("RESTORE_HOLD")
        if verify_originals:
            from canvas_bridge.library.objects import EncryptedDirectory

            objects = self._objects
            if objects is None and any(v.state == "available" for v in versions):
                try:
                    root = self.bridge.settings.library_root
                    if root is None:
                        fail("STORAGE_UNAVAILABLE", "retry_later")
                    objects = EncryptedDirectory(
                        root,
                        self.bridge.vault.key,
                        synthetic=self.bridge.settings.profile == "synthetic",
                        create=False,
                    )
                except (DomainError, OSError):
                    alerts.add("ORIGINAL_STORAGE_UNAVAILABLE")
            for version in versions:
                if version.state != "available":
                    continue
                try:
                    if objects is None:
                        fail("STORAGE_UNAVAILABLE", "retry_later")
                    for _ in objects.read(
                        version.owner, version.object_key, version.size, version.digest
                    ):
                        pass
                    checked += 1
                except (DomainError, OSError):
                    corrupt += 1
            if corrupt:
                alerts.add("ORIGINAL_VERIFICATION_FAILED")
        from canvas_bridge.library.backups import health as backup_health

        backups = backup_health(self, verify_files=verify_backups)
        if backups["state"] in {"unavailable", "attention_required"}:
            alerts.add("BACKUP_ATTENTION_REQUIRED")
        return {
            "state": "attention_required" if alerts else "ok",
            "alerts": sorted(alerts),
            "accounts": len(accounts),
            "quota_drift_accounts": drift,
            "purge_backlog": purge,
            "queue_waiting": sum(j.state == "queued" for j in jobs),
            "oldest_queue_wait_seconds": max(
                [
                    0,
                    *(
                        max(0, int((self.now - aware(j.available_at)).total_seconds()))
                        for j in jobs
                        if j.state == "queued"
                    ),
                ]
            ),
            "expired_operation_leases": sum(
                aware(lease.expires_at) <= self.now for lease in leases
            ),
            "originals_verified": checked,
            "originals_failed": corrupt,
            "metrics": metrics,
            "backups": backups,
        }

    def sweep_operations(self):
        with self.bridge.store.transaction() as session:
            session.execute(delete(OperationLease).where(OperationLease.expires_at <= self.now))
            session.execute(
                delete(Metric).where(
                    Metric.day < (self.now - timedelta(days=30)).date().isoformat()
                )
            )
        from canvas_bridge.library.backups import sweep as backup_sweep

        try:
            backup_sweep(self)
        except (DomainError, OSError):
            # An absent backup mount must not erase receipts or block original retention.
            self.metric("backup", "failed")
