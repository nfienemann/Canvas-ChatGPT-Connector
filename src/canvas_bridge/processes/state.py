"""Bounded encrypted state, atomic revisions, dependency invalidation and recovery.

Uses the existing encrypted IndependentResource container with its own kind and
schema. That container is storage, not an independent-source permission grant.
Every content read/write/export calls the trusted source authorizer anew.
"""

from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge.domain import DomainError
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import (
    AcademicRecord,
    ChangePreview,
    ProcessState,
    StateRevision,
)
from canvas_bridge.storage import IndependentResource, aware

KIND = "academic_process_state"


def failure(code, message="Refresh the process state and review the proposed change."):
    raise DomainError("source_changed", message, reason_code=code)


def indexed(records, **fields):
    dependents = {key: [] for key in records}
    for key, record in records.items():
        for parent in record.depends_on:
            if parent not in dependents:
                failure("PROCESS_DEPENDENCY_MISSING")
            dependents[parent].append(key)
    return ProcessState(
        records=records, dependents={k: tuple(sorted(v)) for k, v in dependents.items()}, **fields
    )


def descendants(state, record_id):
    pending, found = [record_id], set()
    while pending:
        for child in state.dependents.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return tuple(sorted(found))


def affected_records(state, before, after):
    if before is None:
        return ()
    if after is not None:
        changes = {
            k
            for k in before.data.keys() | after.data.keys()
            if before.data.get(k) != after.data.get(k)
        }
        same_sources = {s.key for s in before.sources} == {s.key for s in after.sources}
        if changes <= {"title"} and same_sources and before.depends_on == after.depends_on:
            return ()
    return descendants(state, before.id)


def preview(state, owner, record_id, after, reason, *, now):
    before = state.records.get(record_id)
    if (reason == "delete") != (after is None) or (reason == "create") != (before is None):
        failure("PROCESS_CHANGE_KIND_MISMATCH")
    if after is None and before is None:
        failure("PROCESS_RECORD_UNAVAILABLE")
    if after is not None:
        if after.id != record_id or after.scope.principal != owner or after.state != "valid":
            failure("PROCESS_SCOPE_MISMATCH")
        expected = before.revision + 1 if before else 1
        if after.revision != expected or (before and after.scope != before.scope):
            failure("PROCESS_REVISION_MISMATCH")
        inherited = {s.key for s in after.sources}
        for parent in after.depends_on:
            record = state.records.get(parent)
            if record is None or record.state != "valid" or record.scope.principal != owner:
                failure("PROCESS_DEPENDENCY_UNAVAILABLE")
            if not {s.key for s in record.sources} <= inherited:
                failure("PROCESS_LINEAGE_MISSING")
        indexed(state.records | {record_id: after})  # Validate cycle and bounds before preview.
    if before and before.scope.principal != owner:
        failure("PROCESS_SCOPE_MISMATCH")
    fields = dict(
        state_version=state.version,
        actor=owner,
        reason=reason,
        before=before,
        after=after,
        affected=affected_records(state, before, after),
        expires_at=now + timedelta(minutes=15),
    )
    provisional = ChangePreview(id="pending", **fields)
    return provisional.model_copy(
        update={"id": fingerprint(provisional.model_dump(mode="json", exclude={"id"}))}
    )


def apply(state, change, *, now):
    """Pure transition; repository authenticates, authorizes and commits atomically."""
    if change.state_version != state.version or now >= change.expires_at:
        failure("PROCESS_PREVIEW_STALE")
    expected = fingerprint(change.model_dump(mode="json", exclude={"id"}))
    if expected != change.id:
        failure("PROCESS_PREVIEW_MISMATCH")
    target = change.after or change.before
    if (
        state.records.get(target.id) != change.before
        or affected_records(state, change.before, change.after) != change.affected
    ):
        failure("PROCESS_PREVIEW_MISMATCH")
    records = dict(state.records)
    purged = {target.id, *change.affected} if change.after is None else set()
    if change.after:
        records[target.id] = change.after
        for key in change.affected:
            old = records[key]
            records[key] = old.model_copy(
                update={"state": "stale", "revision": old.revision + 1, "updated_at": now}
            )
    else:
        records = {k: v for k, v in records.items() if k not in purged}
    history = tuple(
        r
        for r in state.revisions
        if not purged
        or not (
            (r.before and r.before.id in purged)
            or (r.after and r.after.id in purged)
            or set(r.affected) & purged
        )
    )
    # Deletion receipts contain only IDs/counts; no deleted before image survives.
    from canvas_bridge.processes.impact import impact_proposals

    impacts = (
        tuple(impact_proposals(state, change.before, change.after, now=now))
        if change.before and change.after
        else ()
    )
    revision = StateRevision(
        id=change.id,
        actor=change.actor,
        reason=change.reason,
        before=change.before if not purged else None,
        after=change.after,
        affected=change.affected,
        created_at=now,
        impacts=impacts,
    )
    return indexed(
        records,
        version=state.version + 1,
        revisions=(history + (revision,))[-500:],
        receipts=state.receipts,
    )


class ProcessRepository:
    def __init__(self, store, *, clock, authorize):
        self.store, self.clock, self.authorize = store, clock, authorize

    @staticmethod
    def identity(owner):
        return fingerprint(["academic-process-state", owner])

    def _load(self, session, owner):
        row = session.scalar(
            select(IndependentResource).where(
                IndependentResource.id == self.identity(owner), IndependentResource.owner == owner
            )
        )
        if not row:
            return None, ProcessState()
        if row.kind != KIND or row.provenance.get("owner") != owner:
            failure("PROCESS_STORAGE_SCOPE_MISMATCH")
        if aware(row.expires_at) <= self.clock():
            # Expired state is never silently overwritten by an old/new client.
            failure(
                "PROCESS_STATE_EXPIRED",
                "Remove expired process state through retention before starting again.",
            )
        if row.content.get("schema_version") != "academic-processes-1":
            failure(
                "PROCESS_SCHEMA_UNSUPPORTED",
                "This client cannot safely read or write this process schema.",
            )
        if fingerprint(row.content) != row.version_hash:
            failure("PROCESS_STATE_CORRUPT")
        try:
            state = ProcessState.model_validate(row.content)
        except ValidationError:
            failure("PROCESS_STATE_CORRUPT")
        if any(r.scope.principal != owner for r in state.records.values()):
            failure("PROCESS_STORAGE_SCOPE_MISMATCH")
        return row, state

    def _save(self, session, owner, row, state):
        payload = state.model_dump(mode="json")
        if len(state.model_dump_json().encode()) > 2_000_000:
            failure(
                "PROCESS_STORAGE_BUDGET", "Export or delete old process records before adding more."
            )
        if row is None:
            row = IndependentResource(
                id=self.identity(owner),
                owner=owner,
                kind=KIND,
                created_at=self.clock(),
                expires_at=self.clock() + timedelta(days=30),
            )
            session.add(row)
        # Updates do not extend original retention or resurrect expired sources.
        row.content, row.version_hash = payload, fingerprint(payload)
        row.provenance = {
            "owner": owner,
            "source_type": KIND,
            "authorization": "recheck_each_source",
            "retention_class": "sanitized_analysis_results",
        }

    def _require(
        self, session, owner, record, purpose="read", *, allow_stale=False, historical=False
    ):
        if record.scope.principal != owner or record.state not in (
            {"valid", "stale"} if allow_stale else {"valid"}
        ):
            failure("PROCESS_RECORD_NOT_VALID")
        for source in record.sources:
            if historical and source.origin == "institutional":
                # Retained history may participate in a local correction only
                # after current access to the exact resource is reauthorized.
                # This does not release an old source version to a recipient.
                self.authorize(session, owner, source, "history")
                continue
            if (
                source.scope.principal != owner
                or not source.observed_at <= self.clock() < source.expires_at
            ):
                failure("PROCESS_SOURCE_STALE")
            self.authorize(session, owner, source, purpose)

    def read(self, owner, record_id):
        with self.store.transaction() as session:
            _, state = self._load(session, owner)
            record = state.records.get(record_id)
            if record is None:
                failure("PROCESS_RECORD_UNAVAILABLE")
            self._require(session, owner, record)
            return record

    def propose(self, owner, record_id, after, reason):
        with self.store.transaction() as session:
            self.store.principal(session, owner)
            _, state = self._load(session, owner)
            before = state.records.get(record_id)
            if before and reason != "delete":
                self._require(session, owner, before, allow_stale=True, historical=True)
            if after:
                self._require(session, owner, after)
            return preview(state, owner, record_id, after, reason, now=self.clock())

    def commit(self, owner, change, *, confirmed, idempotency_key, expected_generation=None):
        if not confirmed or change.actor != owner or not 1 <= len(idempotency_key) <= 100:
            failure("PROCESS_CONFIRMATION_REQUIRED")
        request_hash = fingerprint(change.model_dump(mode="json"))
        key = fingerprint([owner, idempotency_key])
        with self.store.transaction() as session:
            principal = self.store.principal(session, owner)
            if expected_generation is not None and principal.generation != expected_generation:
                failure("PROCESS_ACCOUNT_CHANGED")
            row, state = self._load(session, owner)
            prior = state.receipts.get(key)
            if prior:
                if prior["request_hash"] != request_hash:
                    failure("PROCESS_IDEMPOTENCY_CONFLICT")
                # Receipt is content-free and grants no restored access.
                return prior
            if change.before and change.reason != "delete":
                self._require(session, owner, change.before, allow_stale=True, historical=True)
            if change.after:
                self._require(session, owner, change.after, "write")
                for parent in change.after.depends_on:
                    record = state.records.get(parent)
                    if not record:
                        failure("PROCESS_DEPENDENCY_UNAVAILABLE")
                    self._require(session, owner, record)
            rebuilt = preview(
                state,
                owner,
                (change.after or change.before).id,
                change.after,
                change.reason,
                now=change.expires_at - timedelta(minutes=15),
            )
            if rebuilt != change:
                failure("PROCESS_PREVIEW_MISMATCH")
            updated = apply(state, change, now=self.clock())
            receipt = {
                "request_hash": request_hash,
                "revision_id": change.id,
                "version": updated.version,
                "affected_count": len(change.affected),
                "external_writes": False,
            }
            # Keep bounded replay receipts without making a full journal prevent
            # correction or deletion. Evicted previews still cannot be replayed:
            # their original state_version is older than the committed state.
            receipts = dict(list((state.receipts | {key: receipt}).items())[-500:])
            updated = ProcessState.model_validate(updated.model_dump() | {"receipts": receipts})
            self._save(session, owner, row, updated)
            return receipt

    def rollback_preview(self, owner, revision_id):
        with self.store.transaction() as session:
            _, state = self._load(session, owner)
            revision = next((r for r in state.revisions if r.id == revision_id), None)
            if not revision or not revision.before:
                failure("PROCESS_ROLLBACK_UNAVAILABLE")
            old = revision.before
            current = state.records.get(old.id)
            if not current:
                failure("PROCESS_ROLLBACK_UNAVAILABLE")
            restored = old.model_copy(
                update={"revision": current.revision + 1, "updated_at": self.clock()}
            )
            self._require(session, owner, restored, "write")
            return preview(state, owner, old.id, restored, "rollback", now=self.clock())

    def revoke(self, owner, source_id, *, delete=True, session=None):
        """Trusted revocation/deletion hook. Caller does not need revoked read access."""
        if session is None:
            with self.store.transaction() as active:
                self.store.principal(active, owner)
                return self.revoke(owner, source_id, delete=delete, session=active)
        row, state = self._load(session, owner)
        direct = {r.id for r in state.records.values() if any(s.id == source_id for s in r.sources)}
        affected = direct | {key for ident in direct for key in descendants(state, ident)}
        if not affected:
            return {"affected_count": 0, "state": "unchanged"}
        records = {k: v for k, v in state.records.items() if not delete or k not in affected}
        if not delete:
            for key in affected:
                old = records[key]
                records[key] = old.model_copy(
                    update={
                        "state": "quarantined",
                        "revision": old.revision + 1,
                        "updated_at": self.clock(),
                    }
                )
        # Purge historical payloads too; rollback cannot resurrect revoked content.
        history = tuple(
            r
            for r in state.revisions
            if not any(
                image and (image.id in affected or any(s.id == source_id for s in image.sources))
                for image in (r.before, r.after)
            )
        )
        updated = indexed(
            records, version=state.version + 1, revisions=history, receipts=state.receipts
        )
        self._save(session, owner, row, updated)
        return {
            "affected_count": len(affected),
            "state": "deleted" if delete else "quarantined",
            "external_copies": "outside_bridge_control",
        }

    def inventory(self, owner):
        with self.store.transaction() as session:
            _, state = self._load(session, owner)
            rows = []
            for record in state.records.values():
                try:
                    self._require(session, owner, record)
                except DomainError:
                    rows.append({"id": record.id, "state": "unavailable"})
                else:
                    rows.append(
                        {
                            "id": record.id,
                            "kind": record.kind,
                            "course": record.scope.course,
                            "state": record.state,
                            "revision": record.revision,
                            "origins": sorted({s.origin for s in record.sources}),
                            "sensitivity": sorted({s.sensitivity for s in record.sources}),
                            "updated_at": record.updated_at.isoformat(),
                            "sources": [
                                {"id": s.id, "version": s.version, "locator": s.locator}
                                for s in record.sources
                            ],
                        }
                    )
            return {
                "schema_version": state.schema_version,
                "version": state.version,
                "records": rows,
            }

    def impacts(self, owner, record_id):
        with self.store.transaction() as session:
            _, state = self._load(session, owner)
            result = []
            for revision in state.revisions:
                if revision.after and revision.after.id == record_id:
                    for image in (revision.before, revision.after):
                        if image:
                            self._require(session, owner, image, allow_stale=True)
                    result.extend(revision.impacts)
            return result

    def export(self, owner, record_ids):
        with self.store.transaction() as session:
            _, state = self._load(session, owner)
            if not record_ids or len(record_ids) > 500:
                failure("PROCESS_EXPORT_SCOPE_REQUIRED")
            records = []
            for ident in dict.fromkeys(record_ids):
                record = state.records.get(ident)
                if not record:
                    failure("PROCESS_RECORD_UNAVAILABLE")
                self._require(session, owner, record, "export")
                records.append(record.model_dump(mode="json"))
            return {
                "schema_version": "academic-process-export-1",
                "records": records,
                "authority": "portable_evidence_only",
                "external_transfer": False,
            }


def read_portable_export(payload, *, owner):
    """Validate portable records without importing them or granting source rights."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "records", "authority", "external_transfer"}
        or payload["schema_version"] != "academic-process-export-1"
        or payload["authority"] != "portable_evidence_only"
        or payload["external_transfer"] is not False
    ):
        failure("PROCESS_EXPORT_SCHEMA_UNSUPPORTED")
    if not isinstance(payload["records"], list) or len(payload["records"]) > 500:
        failure("PROCESS_EXPORT_BUDGET")
    from copy import deepcopy

    bound = deepcopy(payload["records"])
    for record in bound:
        if not isinstance(record, dict) or not isinstance(record.get("scope"), dict):
            failure("PROCESS_EXPORT_SCHEMA_UNSUPPORTED")
        # Recipient exports omit internal principal IDs. Bind only that omitted
        # field locally; existing conflicting identities still fail validation.
        record["scope"].setdefault("principal", owner)
        if not isinstance(record.get("sources"), list):
            failure("PROCESS_EXPORT_SCHEMA_UNSUPPORTED")
        for source in record["sources"]:
            if not isinstance(source, dict) or not isinstance(source.get("scope"), dict):
                failure("PROCESS_EXPORT_SCHEMA_UNSUPPORTED")
            source["scope"].setdefault("principal", owner)
    try:
        records = tuple(AcademicRecord.model_validate(r) for r in bound)
    except ValidationError:
        failure("PROCESS_EXPORT_SCHEMA_UNSUPPORTED")
    if len({r.id for r in records}) != len(records) or any(
        r.scope.principal != owner for r in records
    ):
        failure("PROCESS_SCOPE_MISMATCH")
    return records
