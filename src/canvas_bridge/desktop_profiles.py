"""Edition isolation, conservative local deletion and atomic desktop schema upgrades."""

import contextlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import URL, make_url

from canvas_bridge.onboarding import DESKTOP_VERSION, SetupError

MARKER = "edition.json"
OWNED_FILES = {
    MARKER,
    "launcher.lock",
    "bridge.db",
    "bridge.db-wal",
    "bridge.db-shm",
    "vault.key",
    "issuer-private.pem",
    "jwks.json",
    "demo-token",
    "deletions.jsonl",
    "preferences.json",
    "upgrade-backup.enc",
}
OWNED_DIRECTORIES = {"original-delivery"}


def assert_plain_directory(folder):
    folder = Path(folder).absolute()
    if folder == Path(folder.anchor) or folder == Path.home() or len(folder.parts) < 3:
        raise SetupError("UNSAFE_PROFILE_PATH", "Choose a dedicated application data folder.")
    if any(p.is_symlink() or p.is_junction() for p in (folder, *folder.parents)):
        raise SetupError(
            "LINKED_PROFILE_PATH", "Use a regular local folder, not a shortcut or linked directory."
        )
    return folder.resolve()


def prepare_profile(folder, edition):
    if edition not in {"offline", "synthetic"}:
        raise SetupError(
            "EDITION_NOT_LOCAL", "Institutional services cannot be enabled in a local profile."
        )
    folder = assert_plain_directory(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(p.is_symlink() or p.is_junction() for p in folder.iterdir()):
        raise SetupError(
            "LINKED_PROFILE_CONTENT",
            "This data folder contains linked files. Choose a regular application folder; no links will be followed.",
        )
    path = folder / MARKER
    if path.exists():
        if path.is_symlink() or path.stat().st_size > 8192:
            raise SetupError(
                "PROFILE_MARKER_INVALID", "This data folder needs review before it can be opened."
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema") != "desktop-profile-1" or record.get("edition") != edition:
                raise ValueError()
        except (ValueError, AttributeError) as exc:
            raise SetupError(
                "EDITION_MISMATCH",
                "Keep offline and synthetic data in separate folders. Choose the matching edition or another folder.",
            ) from exc
    else:
        # Never adopt a directory containing unrelated user files or a live profile.
        entries = {p.name for p in folder.iterdir()}
        if entries - (OWNED_FILES | OWNED_DIRECTORIES) or (edition == "offline" and entries):
            raise SetupError(
                "UNRECOGNIZED_DATA_FOLDER",
                "Choose an empty folder or the existing synthetic demo folder. Other files are preserved.",
            )
        if "bridge.db" in entries:
            with contextlib.closing(
                sqlite3.connect(f"{(folder / 'bridge.db').as_uri()}?mode=ro", uri=True)
            ) as db:
                tables = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "connections" in tables:
                    institutions = {r[0] for r in db.execute("SELECT institution FROM connections")}
                    if institutions - {"synthetic"}:
                        raise SetupError(
                            "INSTITUTIONAL_PROFILE_REFUSED",
                            "This launcher cannot adopt an institutional database.",
                        )
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(
                    {
                        "schema": "desktop-profile-1",
                        "edition": edition,
                        "created_by": DESKTOP_VERSION,
                    },
                    stream,
                )
        except FileExistsError:
            return prepare_profile(folder, edition)
    return folder


def deletion_inventory(folder):
    folder = assert_plain_directory(folder)
    path = folder / MARKER
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8192:
        raise SetupError(
            "DATA_REMOVAL_NOT_VERIFIED",
            "This is not a verified application data folder. No files were removed.",
        )
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != "desktop-profile-1" or record.get("edition") not in {
        "offline",
        "synthetic",
    }:
        raise SetupError("DATA_REMOVAL_NOT_VERIFIED", "The data folder edition is not recognized.")
    entries = []
    for path in folder.iterdir():
        valid_file = path.name in OWNED_FILES and path.is_file()
        valid_cache = path.name in OWNED_DIRECTORIES and path.is_dir()
        children = []
        pending = [path] if valid_cache else []
        while pending:
            directory = pending.pop()
            if directory.is_symlink() or directory.is_junction():
                break
            for child in directory.iterdir():
                children.append(child)
                if child.is_dir() and not child.is_symlink() and not child.is_junction():
                    pending.append(child)
        candidates = [path, *children]
        if not (valid_file or valid_cache) or any(
            p.is_symlink() or p.is_junction() or not p.resolve().is_relative_to(folder)
            for p in candidates
        ):
            raise SetupError(
                "DATA_REMOVAL_REQUIRES_REVIEW",
                "This folder contains additional files or links. Nothing was deleted. Review it in your file manager.",
            )
        entries.extend(candidates)
    entries.sort(key=lambda p: len(p.parts), reverse=True)
    return folder, entries


def remove_profile(folder, *, confirmed=False):
    if not confirmed:
        raise SetupError(
            "EXPLICIT_DELETION_REQUIRED",
            "Choose Remove local data only after reviewing the displayed folder and deletion limits.",
        )
    from canvas_bridge.desktop import ProfileLock

    folder, _ = deletion_inventory(folder)
    lock = ProfileLock(folder)
    try:
        _, entries = deletion_inventory(folder)
        for path in entries:
            if path.name != "launcher.lock":
                path.rmdir() if path.is_dir() else path.unlink()
    except OSError as exc:
        raise SetupError(
            "DATA_REMOVAL_INCOMPLETE",
            "Removal stopped before completion. Some files may already be removed. Close other applications and review the remaining data folder before trying again.",
        ) from exc
    finally:
        lock.close()
    (folder / "launcher.lock").unlink(missing_ok=True)
    folder.rmdir()
    return {
        "local_data": "removed",
        "credentials": "removed",
        "external_copies": "outside_application_control",
    }


def _security_state(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    queries = {
        "connections": "SELECT id,state,epoch,credential FROM connections ORDER BY id",
        "courses": "SELECT id,selected,accessible FROM courses ORDER BY id",
        "local_records": "SELECT id,kind,key,version,payload FROM local_records ORDER BY id",
        "independent_resources": "SELECT id,kind,version_hash,content,provenance FROM independent_resources ORDER BY id",
    }
    # Preservation proof stays in memory and is never included in diagnostics.
    return {name: list(db.execute(query)) for name, query in queries.items() if name in tables}


def migrate_profile(settings, *, acknowledged=False):
    """Offline copy-first migration. The previous database remains intact on failure.

    Only local synthetic profiles are accepted. No downgrade/restore of used data
    or approval changes is permitted. All SQLite connections close before replace.
    """
    if not acknowledged or settings.profile != "synthetic" or settings.live_access_enabled:
        raise SetupError(
            "LOCAL_UPGRADE_CONFIRMATION_REQUIRED",
            "Review and explicitly approve the local data upgrade first.",
        )
    from canvas_bridge.desktop import ProfileLock

    folder = prepare_profile(settings.vault_key_file.parent, "synthetic")
    database = make_url(settings.database_url)
    if (
        database.get_backend_name() != "sqlite"
        or Path(database.database or "").resolve() != folder / "bridge.db"
    ):
        raise SetupError(
            "UPGRADE_DATABASE_MISMATCH",
            "The database must belong to this local profile. No data was changed.",
        )
    lock = ProfileLock(folder)
    try:
        return _migrate_locked(settings, folder)
    finally:
        lock.close()


def _migrate_locked(settings, folder):
    from canvas_bridge.deployment import preflight, require_ready
    from canvas_bridge.resources import migrate

    original = folder / "bridge.db"
    if (
        original.is_symlink()
        or not original.is_file()
        or original.stat().st_size > 128 * 1024 * 1024
    ):
        raise SetupError(
            "UPGRADE_DATA_SIZE_OR_PATH",
            "This data store needs operator-assisted migration; the original is unchanged.",
        )
    before = preflight(settings)
    if set(before["findings"]) - {"SCHEMA_UPGRADE_REQUIRED"}:
        raise SetupError(
            "UPGRADE_SECURITY_STATE_INVALID",
            "Restore the existing key and deletion journal through approved recovery. An update cannot replace them.",
        )
    with tempfile.TemporaryDirectory(prefix="bridge-upgrade-", dir=folder.parent) as temporary:
        candidate = Path(temporary) / "bridge.db"
        with (
            contextlib.closing(sqlite3.connect(original)) as source,
            contextlib.closing(sqlite3.connect(candidate)) as copy,
        ):
            source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            source.backup(copy)
            baseline = _security_state(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SetupError(
                    "DATABASE_INTEGRITY_FAILED",
                    "Database verification failed. The original was kept.",
                )
        staged_settings = settings.model_copy(
            update={
                "database_url": URL.create("sqlite", database=str(candidate)).render_as_string()
            }
        )
        migrate(staged_settings.database_url, settings.vault_key_file)
        require_ready(staged_settings)
        with contextlib.closing(sqlite3.connect(candidate)) as copy:
            current = _security_state(copy)
            if (
                copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or any(current.get(name) != rows for name, rows in baseline.items())
                or any(rows for name, rows in current.items() if name not in baseline)
            ):
                raise SetupError(
                    "UPGRADE_PRESERVATION_FAILED",
                    "The upgrade changed protected preferences or access state. The original was kept.",
                )
        if (folder / "bridge.db-wal").exists() and (folder / "bridge.db-wal").stat().st_size:
            raise SetupError(
                "DATABASE_STILL_ACTIVE", "Close the local application before upgrading data."
            )
        os.replace(candidate, original)
    return {
        "migration": "verified",
        "preferences": "preserved",
        "access_state": "preserved",
        "failure_recovery": "original_kept_until_verified_atomic_replacement",
        "retained_backup": False,
    }
