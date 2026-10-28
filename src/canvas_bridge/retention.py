"""Central retention rules and owner-authorized lifecycle operations."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select, update

from canvas_bridge.domain import DomainError, opaque_id, utcnow
from canvas_bridge.retention_policy import (
    ANALYSIS_LIFETIME,
    CONNECTION_LIFETIME,
    DIAGNOSTIC_LIFETIME,
    FENCE_LIFETIME,
    JOB_LIFETIME,
    RAW_PAGE_LIFETIME,
)
from canvas_bridge.storage import (
    BrowserSession,
    Connection,
    Course,
    IndependentResource,
    Job,
    LocalRecord,
    Material,
    OAuthState,
    PrincipalState,
    Snapshot,
    Tombstone,
    Work,
    aware,
)

logger = logging.getLogger("canvas_bridge.retention")


@dataclass(frozen=True)
class Rule:
    purpose: str
    expiry: str
    deletion: str


RULES = {
    "authentication_credentials": Rule(
        "Identity-bound access",
        "Token/session expiry; connection maximum 90 days",
        "Revoke locally; purge secret; separately report upstream outcome",
    ),
    "active_connection_configuration": Rule(
        "Explicit course selection and account mapping",
        "90 days from explicit connection creation",
        "Disconnect and purge; new explicit connection required",
    ),
    "temporary_processing_artifacts": Rule(
        "Isolated extraction and original-file delivery",
        "Job completion or failure; orphan threshold 10 minutes; delivery default 5 minutes, configured maximum 15 minutes; PDF memory cache 10 minutes",
        "Terminate bounded worker; remove private workspace/link; clear memory",
    ),
    "sanitized_analysis_results": Rule(
        "Workload changes and user-saved study state",
        "30 days from observation or explicit save",
        "Delete expired snapshots, work, plans and progress",
    ),
    "restricted_raw_records": Rule(
        "Current academic facts and repeat document analysis",
        "Normalized academic facts 30 days; independently imported bytes and extraction at most 24 hours; extracted institutional file text 24 hours maximum; page text 1 hour; source inventory at most the 90-day connection lifetime",
        "Delete expired facts; clear text, locators and derived file state; purge inventory on disconnection",
    ),
    "operational_diagnostics": Rule(
        "Minimal deletion verification and troubleshooting",
        "7 days; no source text or credentials",
        "Expire local receipts; operator must bound external log sinks",
    ),
    "authorization_evidence": Rule(
        "Enforce independently obtained approvals and prevent restoration",
        "Approval evidence: explicit signed expiry plus administrator disposal schedule; deletion fences: backup horizon plus one day; non-content institutional digest restrictions: 91 days",
        "Approval evidence stays encrypted and administrator-owned; prune obsolete restoration fences only after backup horizon",
    ),
}


class Retention:
    def __init__(self, bridge, clock=utcnow):
        self.bridge, self.clock = bridge, clock
        self.receipts = {}  # Minimal process-local receipts, never academic payloads.

    def inventory(self, owner):
        with self.bridge.store.transaction() as session:
            connections = list(session.scalars(select(Connection).where(Connection.owner == owner)))
            counts = {
                cls.__tablename__: session.scalar(
                    select(func.count())
                    .select_from(cls)
                    .where(cls.owner == owner)
                    .execution_options(retention_admin=True)
                )
                for cls in (Course, Work, Material, Snapshot, LocalRecord, Job, IndependentResource)
            }
        return {
            "sources": [
                {
                    "id": c.id,
                    "institution": c.institution,
                    "state": c.state,
                    "retention_expires_at": (aware(c.created_at) + CONNECTION_LIFETIME).isoformat(),
                }
                for c in connections
            ],
            "stored_categories": counts,
            "policies": {key: vars(rule) for key, rule in RULES.items()},
            "outside_control": "Canvas records, ChatGPT conversations, user downloads, external logs and immutable/host backups need their controlling service's deletion controls.",
        }

    def receipt(self, owner, operation, counts, pending=0):
        now = self.clock()
        result = {
            "receipt_id": opaque_id(),
            "operation": operation,
            "completed_at": now.isoformat(),
            "deleted_rows": counts,
            "pending_temporary_cleanup": pending,
            "local_deletion": "completed" if not pending else "access_blocked_cleanup_pending",
            "physical_erasure": "not_guaranteed",
            "other_services": "unchanged",
            "backup_copies": "not_physically_erased; restoration fenced",
        }
        self.receipts[result["receipt_id"]] = (owner, now, result)
        logger.info("local_deletion_completed operation=%s pending_cleanup=%d", operation, pending)
        self.expire_receipts()
        return result

    def expire_receipts(self):
        for key, (_, at, _) in list(self.receipts.items()):
            if not timedelta(0) <= self.clock() - at < DIAGNOSTIC_LIFETIME:
                del self.receipts[key]

    def delete_local(self, owner, ref, *, academic=False, confirmed=False, generation=None):
        if confirmed is not True:
            raise DomainError("needs_input", "Explicit deletion confirmation is required.")
        from canvas_bridge.lifecycle import journal_delete

        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if generation is not None and principal.generation != generation:
                raise DomainError("permission_denied", "This settings session was revoked.")
            conn = self.bridge.store.connection(session, owner, ref, lock=True)
            from canvas_bridge.processes.purge import purge_sources

            purge_sources(session, owner, connection=ref)
            journal_delete(
                self.bridge.settings.deletion_journal,
                self.bridge.vault.key,
                ref,
                conn.epoch + 1,
                now=self.clock(),
            )
            conn.epoch += 1
            conn.entitlement_at = None
            counts = {}
            classes = (
                (Material, Job, Snapshot, Work, LocalRecord, Course)
                if academic
                else (Material, Job, Snapshot, Work)
            )
            for cls in classes:
                result = session.execute(
                    delete(cls).where(cls.owner == owner, cls.connection_id == ref)
                )
                counts[cls.__tablename__] = result.rowcount
        self.bridge.invalidate_access(owner, ref)
        pending = self.bridge.original_files.pending_cleanup(owner, ref)
        from canvas_bridge.worker_storage import pending as pending_workers

        pending += pending_workers(owner, ref, namespace=self.bridge.processing_namespace)
        return self.receipt(
            owner, "delete_academic_records" if academic else "delete_caches", counts, pending
        )

    async def sweep(self):
        now = self.clock()
        self.bridge.independent.sweep()
        with self.bridge.store.transaction() as session:
            expired = [
                (c.owner, c.id)
                for c in session.scalars(
                    select(Connection).where(
                        (Connection.state == "active")
                        | ~Connection.id.in_(select(Tombstone.connection_id)),
                        Connection.created_at <= now - CONNECTION_LIFETIME,
                    )
                )
            ]
        from canvas_bridge.linking import disconnect

        for owner, ref in expired:
            await disconnect(self.bridge, owner, ref)
        with self.bridge.store.transaction() as session:
            for cls, field in (
                (Work, Work.observed_at),
                (Snapshot, Snapshot.created_at),
                (LocalRecord, LocalRecord.updated_at),
            ):
                session.execute(delete(cls).where(field <= now - ANALYSIS_LIFETIME))
            session.execute(delete(Job).where(Job.available_at <= now - JOB_LIFETIME))
            for cls in (OAuthState, BrowserSession):
                session.execute(delete(cls).where(cls.expires_at <= now))
            for kind, lifetime in (
                ("file", timedelta(hours=self.bridge.settings.file_cache_hours)),
                ("page", RAW_PAGE_LIFETIME),
            ):
                session.execute(
                    update(Material)
                    .where(Material.kind == kind, Material.retrieved_at <= now - lifetime)
                    .values(
                        text="",
                        locators=[],
                        limitations=[],
                        version_hash="",
                        file_state={"stage": "available"},
                    )
                )
            old_fences = select(Tombstone.connection_id).where(
                Tombstone.deleted_at <= now - FENCE_LIFETIME
            )
            session.execute(
                delete(Connection).where(
                    Connection.state != "active", Connection.id.in_(old_fences)
                )
            )
            session.execute(delete(Tombstone).where(Tombstone.deleted_at <= now - FENCE_LIFETIME))
            for principal in session.scalars(select(PrincipalState)):
                if (
                    principal.tokens_valid_after
                    and aware(principal.tokens_valid_after) > now - FENCE_LIFETIME
                ):
                    continue
                if any(
                    session.scalar(select(cls.owner).where(cls.owner == principal.owner).limit(1))
                    for cls in (Connection, BrowserSession, OAuthState, IndependentResource)
                ):
                    continue
                session.delete(principal)
        self.bridge.original_files.cleanup()
        self.bridge.presentation_derivatives.cleanup()
        # Weak lock entries expire after both holders and scheduled waiters release
        # their references. Removing an unlocked lock here could split a queue.
        self.expire_receipts()
        from canvas_bridge.worker_storage import sweep_orphans

        if self.bridge.settings.parser_root:
            sweep_orphans(self.bridge.settings.parser_root, now=now.timestamp())
        from canvas_bridge.lifecycle import prune_journal

        prune_journal(self.bridge.settings.deletion_journal, self.bridge.vault.key, now)
