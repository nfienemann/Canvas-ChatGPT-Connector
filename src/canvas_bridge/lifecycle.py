"""Encrypted backup and restore with a separately retained deletion journal."""

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import DateTime, select

from canvas_bridge.domain import utcnow
from canvas_bridge.retention_policy import (
    ANALYSIS_LIFETIME,
    BACKUP_LIFETIME,
    CONNECTION_LIFETIME,
    FENCE_LIFETIME,
)
from canvas_bridge.storage import (
    Base,
    BrowserSession,
    OAuthState,
    PrincipalState,
    Tombstone,
    aware,
)


@contextmanager
def locked_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # r+b semantics are required for authenticated compaction; O_APPEND would
    # silently append after seek(0), retaining the old entries indefinitely.
    with os.fdopen(os.open(path, os.O_RDWR, 0o600), "r+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            # Lock one byte even when the file is empty.
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield stream
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def journal_delete(path: Path, key: bytes, connection: str, epoch: int, *, now=None):
    entry = {
        "connection_id": connection,
        "epoch": epoch,
        "deleted_at": (now or utcnow()).isoformat(),
    }
    payload = json.dumps(entry, sort_keys=True)
    entry["mac"] = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    with locked_file(path) as stream:
        stream.seek(0, 2)
        stream.write((json.dumps(entry) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def read_journal(path: Path, key: bytes) -> dict[str, dict]:
    # Missing or damaged deletion history must never silently permit a restore.
    return _decode_journal(path.read_text(encoding="utf-8"), key)


def _decode_journal(content, key):
    records = {}
    for line in content.splitlines():
        entry = json.loads(line)
        mac = entry.pop("mac")
        expected = hmac.new(
            key, json.dumps(entry, sort_keys=True).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("Deletion journal integrity check failed.")
        records[entry["connection_id"]] = entry
    return records


def prune_journal(path: Path, key: bytes, now):
    # Same OS lock as appends. A bounded backup cannot outlive a removed fence.
    # Verify the entire log before modifying it, including entries being pruned.
    if not path.is_file():
        raise FileNotFoundError("Deletion journal is required for retention cleanup.")
    with locked_file(path) as stream:
        stream.seek(0)
        entries = _decode_journal(stream.read().decode("utf-8"), key)
        kept = []
        for entry in entries.values():
            if aware(datetime.fromisoformat(entry["deleted_at"])) + FENCE_LIFETIME > now:
                entry["mac"] = hmac.new(
                    key, json.dumps(entry, sort_keys=True).encode(), hashlib.sha256
                ).hexdigest()
                kept.append(json.dumps(entry))
        stream.seek(0)
        stream.write(("\n".join(kept) + ("\n" if kept else "")).encode())
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def retained(table, row, now):
    if table == "independent_resources":
        return (
            row["kind"] == "institutional_lineage"
            and aware(datetime.fromisoformat(row["expires_at"])) > now
        )
    if table == "deployment_state":
        return False  # Machine key bindings are never restored.
    timestamp = {
        "work_items": "observed_at",
        "snapshots": "created_at",
        "local_records": "updated_at",
    }.get(table)
    if timestamp and aware(datetime.fromisoformat(row[timestamp])) + ANALYSIS_LIFETIME <= now:
        return False
    if (
        table == "connections"
        and aware(datetime.fromisoformat(row["created_at"])) + CONNECTION_LIFETIME <= now
    ):
        return False
    return True


def strip_ephemeral(table, row):
    if table == "materials":
        row.update(
            text="", locators=[], version_hash="", limitations=[], file_state={"stage": "available"}
        )
    if table == "connections":
        # No restoration can reactivate a token, even with a stale journal.
        row.update(
            credential=None,
            token_expires_at=None,
            refresh_lease_until=None,
            entitlement_at=None,
            last_success=None,
            state="disconnected",
            authentication_state="unverified",
            epoch=row["epoch"] + 1,
        )


def backup(bridge, destination: Path) -> dict:
    if destination.exists():
        raise ValueError("Backup destination already exists.")
    records = {}
    now = bridge.retention.clock()
    with bridge.store.engine.connect() as connection:
        # A repeatable read prevents a cross-table inconsistent logical snapshot.
        if bridge.store.engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            for table in Base.metadata.sorted_tables:
                if table.name in {
                    OAuthState.__tablename__,
                    BrowserSession.__tablename__,
                    PrincipalState.__tablename__,
                    Tombstone.__tablename__,
                    "jobs",
                }:
                    continue
                rows = connection.execute(select(table)).mappings().all()
                records[table.name] = [
                    {
                        key: value.isoformat() if isinstance(value, datetime) else value
                        for key, value in row.items()
                    }
                    for row in rows
                ]
                records[table.name] = [
                    row for row in records[table.name] if retained(table.name, row, now)
                ]
                for row in records[table.name]:
                    strip_ephemeral(table.name, row)
    valid = {r["id"] for r in records.get("connections", [])}
    for name, rows in records.items():
        records[name] = [
            r
            for r in rows
            if "connection_id" not in r
            or name == "deletion_tombstones"
            or r["connection_id"] in valid
        ]
    payload = {
        "format": "bridge-backup-2",
        "created_at": now.isoformat(),
        "expires_at": (now + BACKUP_LIFETIME).isoformat(),
        "tables": records,
    }
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(bridge.vault.seal(payload, "operator", "backup"))
    destination.chmod(0o600)
    return {
        "tables": len(records),
        "encrypted": True,
        "expires_at": payload["expires_at"],
        "credentials_included": False,
    }


def restore(bridge, source: Path, journal: Path) -> dict:
    if bridge.settings.profile != "synthetic":
        from canvas_bridge.deployment import preflight

        if (
            preflight(bridge.settings, store=bridge.store)["historical_deletion_assurance"]
            != "fresh_installation"
        ):
            raise ValueError("RESTORE_BLOCKED_UNKNOWN_DELETION_HISTORY")
    bridge.store.protect(bridge.vault)
    bridge.store.now = lambda: bridge.retention.clock()
    bridge.store.raw_file_lifetime = lambda: timedelta(hours=bridge.settings.file_cache_hours)
    fences = read_journal(journal, bridge.vault.key)
    payload = bridge.vault.open(source.read_text(encoding="utf-8"), "operator", "backup")
    if payload.get("format") != "bridge-backup-2":
        raise ValueError("Unsupported backup format.")
    now = bridge.retention.clock()
    created, expires = (
        aware(datetime.fromisoformat(payload[k])) for k in ("created_at", "expires_at")
    )
    if not created <= now < expires <= created + BACKUP_LIFETIME:
        raise ValueError("Backup has expired or has an invalid retention window.")
    principal_fences = {
        ref.removeprefix("principal:"): record
        for ref, record in fences.items()
        if ref.startswith("principal:")
    }
    connection_fences = {
        ref: record for ref, record in fences.items() if not ref.startswith("principal:")
    }
    excluded = set(connection_fences)
    for row in payload["tables"].get("connections", []):
        if not retained("connections", row, now):
            excluded.add(row["id"])
        fence = principal_fences.get(row["owner"])
        if fence and aware(datetime.fromisoformat(row["created_at"])) <= datetime.fromisoformat(
            fence["deleted_at"]
        ):
            excluded.add(row["id"])
    with bridge.store.transaction() as session:
        for table in Base.metadata.sorted_tables:
            if table.name == "deployment_state":
                continue  # Keep the target's key/history binding, never restore an old one.
            if session.execute(select(table).limit(1)).first():
                raise ValueError("Restore requires an empty migrated target database.")
        for table in Base.metadata.sorted_tables:
            if table.name in {
                OAuthState.__tablename__,
                BrowserSession.__tablename__,
                PrincipalState.__tablename__,
                Tombstone.__tablename__,
                "jobs",
            }:
                continue
            for raw in payload["tables"].get(table.name, []):
                row = dict(raw)
                if not retained(table.name, row, now):
                    continue
                strip_ephemeral(table.name, row)
                ref = row.get(
                    "connection_id", row.get("id") if table.name == "connections" else None
                )
                if ref in excluded:
                    continue
                for column in table.columns:
                    if isinstance(column.type, DateTime) and row.get(column.name):
                        row[column.name] = datetime.fromisoformat(row[column.name])
                session.execute(table.insert().values(**row))
        for ref, record in connection_fences.items():
            session.add(
                Tombstone(
                    connection_id=ref,
                    epoch=record["epoch"],
                    deleted_at=datetime.fromisoformat(record["deleted_at"]),
                )
            )
        for owner, record in principal_fences.items():
            principal = session.get(PrincipalState, owner)
            if principal is None:
                session.add(
                    PrincipalState(
                        owner=owner,
                        generation=record["epoch"],
                        tokens_valid_after=datetime.fromisoformat(record["deleted_at"]),
                    )
                )
            else:
                principal.generation = max(principal.generation, record["epoch"])
                cutoff = datetime.fromisoformat(record["deleted_at"])
                if not principal.tokens_valid_after or aware(principal.tokens_valid_after) < cutoff:
                    principal.tokens_valid_after = cutoff
    return {"restored": True, "deletion_fences_applied": len(fences), "jobs_resumed": False}
