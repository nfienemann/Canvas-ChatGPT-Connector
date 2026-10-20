"""Encrypted backup and restore with a separately retained deletion journal."""

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, select

from canvas_bridge.domain import utcnow
from canvas_bridge.storage import Base, BrowserSession, OAuthState, PrincipalState, Tombstone, aware


@contextmanager
def locked_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
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


def journal_delete(path: Path, key: bytes, connection: str, epoch: int):
    entry = {"connection_id": connection, "epoch": epoch, "deleted_at": utcnow().isoformat()}
    payload = json.dumps(entry, sort_keys=True)
    entry["mac"] = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    with locked_file(path) as stream:
        stream.seek(0, 2)
        stream.write((json.dumps(entry) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def read_journal(path: Path, key: bytes) -> dict[str, dict]:
    # Missing or damaged deletion history must never silently permit a restore.
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        mac = entry.pop("mac")
        expected = hmac.new(
            key, json.dumps(entry, sort_keys=True).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("Deletion journal integrity check failed.")
        records[entry["connection_id"]] = entry
    return records


def backup(bridge, destination: Path) -> dict:
    if destination.exists():
        raise ValueError("Backup destination already exists.")
    records = {}
    with bridge.store.engine.connect() as connection:
        # A repeatable read prevents a cross-table inconsistent logical snapshot.
        if bridge.store.engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            for table in Base.metadata.sorted_tables:
                if table.name in {OAuthState.__tablename__, BrowserSession.__tablename__}:
                    continue
                rows = connection.execute(select(table)).mappings().all()
                records[table.name] = [
                    {
                        key: value.isoformat() if isinstance(value, datetime) else value
                        for key, value in row.items()
                    }
                    for row in rows
                ]
    payload = {"format": "bridge-backup-1", "created_at": utcnow().isoformat(), "tables": records}
    destination.write_text(bridge.vault.seal(payload, "operator", "backup"), encoding="utf-8")
    return {"tables": len(records), "encrypted": True}


def restore(bridge, source: Path, journal: Path) -> dict:
    fences = read_journal(journal, bridge.settings.vault_key_file.read_bytes())
    payload = bridge.vault.open(source.read_text(encoding="utf-8"), "operator", "backup")
    if payload.get("format") != "bridge-backup-1":
        raise ValueError("Unsupported backup format.")
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
        fence = principal_fences.get(row["owner"])
        if fence and aware(datetime.fromisoformat(row["created_at"])) <= datetime.fromisoformat(
            fence["deleted_at"]
        ):
            excluded.add(row["id"])
    with bridge.store.transaction() as session:
        for table in Base.metadata.sorted_tables:
            if session.execute(select(table).limit(1)).first():
                raise ValueError("Restore requires an empty migrated target database.")
        for table in Base.metadata.sorted_tables:
            for raw in payload["tables"].get(table.name, []):
                row = dict(raw)
                ref = row.get(
                    "connection_id", row.get("id") if table.name == "connections" else None
                )
                if ref in excluded:
                    continue
                for column in table.columns:
                    if isinstance(column.type, DateTime) and row.get(column.name):
                        row[column.name] = datetime.fromisoformat(row[column.name])
                if table.name == "jobs":
                    # No autonomous work is resumed merely by restoring a backup.
                    row["state"] = "cancelled"
                    row["lease_until"] = None
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
                session.add(PrincipalState(owner=owner, generation=record["epoch"]))
            else:
                principal.generation = max(principal.generation, record["epoch"])
    return {"restored": True, "deletion_fences_applied": len(fences), "jobs_resumed": False}
