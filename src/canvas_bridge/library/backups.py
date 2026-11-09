"""Opt-in private managed backups. Only generated files in a dedicated root are owned."""

import hashlib
import re
import zipfile
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.library.contracts import fail
from canvas_bridge.library.models import BackupRecord
from canvas_bridge.library.objects import EncryptedDirectory
from canvas_bridge.storage import aware


def directory(library, *, create=True):
    configured = library.bridge.settings.library_backup_root
    if configured is None:
        fail("STORAGE_UNAVAILABLE", "retry_later")
    original = library.bridge.settings.library_root
    if original and (
        configured.resolve().is_relative_to(original.resolve())
        or original.resolve().is_relative_to(configured.resolve())
    ):
        fail("STORAGE_UNAVAILABLE", "retry_later")
    # Reuse the private path, junction and OS-permission boundary, not the object layout.
    return EncryptedDirectory(
        configured,
        library.bridge.vault.key,
        synthetic=library.bridge.settings.profile == "synthetic",
        create=create,
    ).root


def path_for(root, ident):
    if not re.fullmatch(r"[a-f0-9]{32}", ident):
        fail("RESOURCE_UNAVAILABLE")
    path = root / (ident + ".zip")
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        fail("STORAGE_UNAVAILABLE", "retry_later")
    return path


def usage(root):
    total = 0
    for path in root.iterdir():
        if re.fullmatch(r"[a-f0-9]{32}\.zip", path.name):
            path = path_for(root, path.stem)
            if path.is_file():
                total += path.stat().st_size
    return total


def verify(library, owner, path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 20000 or len(names) != len(set(names)):
            raise ValueError("Backup inventory exceeds its bound.")
        for entry in entries:
            bound = 16_000_000 if entry.filename == "manifest.sealed" else 8 * 1024 * 1024 + 1024
            if (
                entry.compress_type != zipfile.ZIP_STORED
                or entry.file_size > bound
                or entry.flag_bits & 1
            ):
                raise ValueError("Backup entry exceeds its bound.")
        if (
            sum(entry.file_size for entry in entries)
            > library.bridge.settings.library_quota_bytes + 32 * 1024 * 1024
        ):
            raise ValueError("Backup exceeds its capacity bound.")
        if archive.testzip() is not None:
            raise ValueError("Backup checksum verification failed.")
        sealed = archive.read("manifest.sealed")
        if len(sealed) > 16_000_000:
            raise ValueError("Backup manifest exceeds its bound.")
        try:
            manifest = library.bridge.vault.open(sealed.decode(), owner, "library-backup")
        except (InvalidTag, ValueError):
            raise ValueError("Backup authentication failed.") from None
        if manifest.get("owner") != owner or manifest.get("format") != "private-library-backup-1":
            raise ValueError("Backup identity verification failed.")
        expected = {"manifest.sealed"}
        for obj in manifest["objects"]:
            for part in obj["parts"]:
                name = part["name"]
                if name in expected:
                    raise ValueError("Backup inventory is duplicated.")
                expected.add(name)
                raw = archive.read(name)
                if len(raw) != part["bytes"] or hashlib.sha256(raw).hexdigest() != part["sha256"]:
                    raise ValueError("Backup authenticated checksum verification failed.")
        if set(names) != expected:
            raise ValueError("Backup inventory is incomplete.")
        return manifest


def create(library, owner):
    from canvas_bridge.library.recovery import backup

    root, ident = directory(library), opaque_id()
    destination = path_for(root, ident)
    with library.operation(owner, "backup") as check:
        with library.transaction(owner) as (session, account, principal):
            library.account(account)
            if (
                usage(root) + account.committed + 32 * 1024 * 1024
                > library.bridge.settings.library_backup_bytes
            ):
                fail("CAPACITY_UNAVAILABLE", "retry_later", retryable=True)
        try:
            receipt = backup(library, owner, destination)
            check()
            verify(library, owner, destination)
            size = destination.stat().st_size
            if usage(root) > library.bridge.settings.library_backup_bytes:
                destination.unlink()
                fail("CAPACITY_UNAVAILABLE", "retry_later")
            with library.transaction(owner) as (session, account, principal):
                session.add(
                    BackupRecord(
                        owner=owner,
                        id=ident,
                        size=size,
                        created_at=library.now,
                        expires_at=library.now + timedelta(days=30),
                    )
                )
            library.metric("backup", "ok", size=size)
            return {"backup_id": ident, "bytes": size, "verified": True, **receipt}
        except Exception:
            # A completed but unrecorded file remains quarantined for at most 24h.
            library.metric("backup", "failed")
            raise


def sweep(library):
    if library.bridge.settings.library_backup_root is None:
        return {"removed": 0, "pending": 0}
    root, removed, pending = directory(library, create=False), 0, 0
    with library.bridge.store.transaction() as session:
        records = list(session.scalars(select(BackupRecord)))
    for record in records:
        if aware(record.expires_at) > library.now:
            continue
        try:
            path_for(root, record.id).unlink(missing_ok=True)
        except (OSError, DomainError):
            pending += 1
            continue
        with library.transaction(record.owner) as (session, account, principal):
            current = session.get(BackupRecord, (record.owner, record.id))
            if current:
                session.delete(current)
        removed += 1
    known = {r.id for r in records}
    for path in root.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}\.zip", path.name) or path.stem in known:
            continue
        checked = path_for(root, path.stem)
        if checked.stat().st_mtime <= library.now.timestamp() - 86400:
            try:
                checked.unlink()
                removed += 1
            except OSError:
                pending += 1
    return {"removed": removed, "pending": pending}


def health(library, *, verify_files=False):
    if library.bridge.settings.library_backup_root is None:
        return {"state": "not_configured", "physical_expiry": "external_operator_policy"}
    try:
        root = directory(library, create=False)
        with library.bridge.store.transaction() as session:
            records = list(session.scalars(select(BackupRecord)))
        pending, failed, verified = 0, 0, 0
        for record in records:
            pending += aware(record.expires_at) <= library.now
            path = path_for(root, record.id)
            try:
                if path.stat().st_size != record.size:
                    raise ValueError("Backup size changed.")
                if verify_files:
                    verify(library, record.owner, path)
                    verified += 1
            except (OSError, ValueError, KeyError, TypeError, DomainError, zipfile.BadZipFile):
                failed += 1
        return {
            "state": "attention_required" if pending or failed else "ok",
            "count": len(records),
            "bytes": usage(root),
            "maximum_bytes": library.bridge.settings.library_backup_bytes,
            "expired_pending_purge": pending,
            "failed": failed,
            "verified": verified,
        }
    except (OSError, DomainError):
        return {"state": "unavailable"}
