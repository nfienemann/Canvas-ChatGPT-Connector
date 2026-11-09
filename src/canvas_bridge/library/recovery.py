"""Separate encrypted library backups. No sessions, working grants or derivatives restored."""

import hashlib
import zipfile
from datetime import datetime, timedelta

from sqlalchemy import DateTime, select

from canvas_bridge.domain import opaque_id
from canvas_bridge.library.contracts import fail
from canvas_bridge.library.models import Account, Grant, Item, Legacy, Version
from canvas_bridge.lifecycle import journal_delete, read_journal
from canvas_bridge.storage import aware

TABLES = (Account, Item, Version, Grant, Legacy)


def backup(library, owner, destination):
    """Operator-only, owner-qualified snapshot. Destination must not already exist."""
    if destination.exists():
        raise ValueError("Backup destination already exists.")
    anchor = "library-backup:" + owner + ":" + opaque_id()
    now = library.now
    journal_delete(
        library.bridge.settings.deletion_journal, library.bridge.vault.key, anchor, 1, now=now
    )
    tables, objects = {}, []
    with library.transaction(owner) as (session, account, principal):
        library.account(account)
        # Owner lock prevents publication/deletion while metadata and original objects are copied.
        for cls in TABLES:
            rows = session.scalars(select(cls).where(cls.owner == owner))
            tables[cls.__tablename__] = [
                {
                    column.name: (
                        getattr(row, column.key).isoformat()
                        if isinstance(getattr(row, column.key), datetime)
                        else getattr(row, column.key)
                    )
                    for column in cls.__table__.columns
                }
                for row in rows
            ]
        try:
            with zipfile.ZipFile(destination, "x", zipfile.ZIP_STORED) as archive:
                for version in session.scalars(
                    select(Version).where(Version.owner == owner, Version.state == "available")
                ):
                    if version.expires_at and aware(version.expires_at) <= now:
                        continue
                    for _ in library.objects.read(
                        owner, version.object_key, version.size, version.digest
                    ):
                        pass
                    parts = []
                    for part, raw in library.objects.sealed_parts(owner, version.object_key):
                        arcname = version.object_key + "/" + part
                        archive.writestr(arcname, raw)
                        parts.append(
                            {
                                "name": arcname,
                                "bytes": len(raw),
                                "sha256": hashlib.sha256(raw).hexdigest(),
                            }
                        )
                    objects.append(
                        {"version": version.id, "key": version.object_key, "parts": parts}
                    )
                manifest = {
                    "format": "private-library-backup-1",
                    "owner": owner,
                    "anchor": anchor,
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "tables": tables,
                    "objects": objects,
                }
                archive.writestr(
                    "manifest.sealed", library.bridge.vault.seal(manifest, owner, "library-backup")
                )
            destination.chmod(0o600)
        except Exception:
            if destination.exists():
                destination.unlink()
            raise
    return {
        "encrypted": True,
        "originals": len(objects),
        "expires_at": manifest["expires_at"],
        "sessions_included": False,
    }


def restore(library, owner, source, journal):
    """Empty, isolated target only; current independent journal is mandatory."""
    from canvas_bridge.library.models import Base

    library.enabled()
    with library.bridge.store.transaction() as session:
        if any(session.execute(select(t).limit(1)).first() for t in Base.metadata.sorted_tables):
            raise ValueError("Library restore requires an empty isolated library database.")
    # Persist hold before opening any external recovery input; failures stay visibly held.
    with library.bridge.store.transaction() as session:
        session.add(Account(owner=owner, state="restore_hold"))
    try:
        fences = read_journal(journal, library.bridge.vault.key)
        with zipfile.ZipFile(source) as archive:
            if len(archive.infolist()) > 20000:
                raise ValueError
            with archive.open("manifest.sealed") as stream:
                raw = stream.read(16_000_001)
            if len(raw) > 16_000_000:
                raise ValueError
            payload = library.bridge.vault.open(raw.decode(), owner, "library-backup")
            now = library.now
            created, expires = (
                datetime.fromisoformat(payload[k]) for k in ("created_at", "expires_at")
            )
            if (
                payload["format"] != "private-library-backup-1"
                or payload["owner"] != owner
                or not created <= now < expires <= created + timedelta(days=30)
                or payload["anchor"] not in fences
            ):
                raise ValueError
            account_deleted = "library-account:" + owner in fences
            items = {
                r["id"]: r
                for r in payload["tables"][Item.__tablename__]
                if r["owner"] == owner
                and r["state"] == "available"
                and "library-item:" + owner + ":" + r["id"] not in fences
                and not account_deleted
            }
            versions = {
                r["id"]: r
                for r in payload["tables"][Version.__tablename__]
                if r["owner"] == owner
                and r["item"] in items
                and r["state"] == "available"
                and "library-version:" + owner + ":" + r["id"] not in fences
                and (not r["expires_at"] or datetime.fromisoformat(r["expires_at"]) > now)
            }
            items = {k: v for k, v in items.items() if v["current"] in versions}
            versions = {k: v for k, v in versions.items() if v["item"] in items}
            total = sum(v["size"] for v in versions.values())
            if (
                total > library.bridge.settings.library_quota_bytes
                or len(items) > library.bridge.settings.library_item_limit
            ):
                raise ValueError
            restored = set()
            for obj in payload["objects"]:
                version = versions.get(obj["version"])
                if version is None:
                    continue
                if version["object_key"] != obj["key"]:
                    raise ValueError
                for part in obj["parts"]:
                    name = part["name"].split("/")
                    if (
                        len(name) != 2
                        or name[0] != obj["key"]
                        or (name[1] != "manifest" and not name[1].isdigit())
                        or part["bytes"] > 8 * 1024 * 1024 + 1024
                    ):
                        raise ValueError
                    with archive.open(part["name"]) as stream:
                        raw = stream.read(part["bytes"] + 1)
                    if (
                        len(raw) != part["bytes"]
                        or hashlib.sha256(raw).hexdigest() != part["sha256"]
                    ):
                        raise ValueError
                    library.objects.restore_part(owner, obj["key"], name[1], raw)
                for _ in library.objects.read(
                    owner, obj["key"], version["size"], version["digest"]
                ):
                    pass
                restored.add(version["id"])
            if restored != set(versions):
                raise ValueError
            # Reconcile again immediately before publication, including deletion during recovery.
            if read_journal(journal, library.bridge.vault.key) != fences:
                raise ValueError
            with library.transaction(owner) as (session, account, principal):
                for cls, records in ((Item, items.values()), (Version, versions.values())):
                    for raw in records:
                        values = dict(raw)
                        for column in cls.__table__.columns:
                            if isinstance(column.type, DateTime) and values.get(column.name):
                                values[column.name] = datetime.fromisoformat(values[column.name])
                        if cls is Version:
                            values["processing"] = "not_requested"
                        session.add(cls(**values))
                    session.flush()
                for version in versions.values():
                    session.add(
                        Grant(
                            owner=owner,
                            id=version["id"],
                            revision=1,
                            payload={
                                "allow_processing": False,
                                "recipients": [],
                                "purpose": "document_reading",
                                "policy_version": "private-library-1",
                                "action_receipt": "restore-requires-new-consent",
                            },
                        )
                    )
                account.state, account.committed, account.slots = "active", total, len(items)
                account.revision += 1
                account.generation += 1
        library.metric("restore", "ok")
        return {
            "restored_originals": len(versions),
            "restored_items": len(items),
            "grants_restored": False,
            "sessions_restored": False,
            "deletion_fences_applied": len(fences),
        }
    except Exception:
        library.metric("restore", "held")
        fail("RESTORE_ON_HOLD", "retry_later")
