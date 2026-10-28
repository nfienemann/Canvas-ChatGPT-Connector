"""Read-only startup diagnostics and explicit, target-bound offline upgrades."""

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.engine import make_url

from canvas_bridge.domain import utcnow
from canvas_bridge.lifecycle import read_journal
from canvas_bridge.resources import migrate, resource_root
from canvas_bridge.storage import Base, Store
from canvas_bridge.vault import Vault


def target_id(url):
    parsed = make_url(url)
    # Password rotation does not change the database identity. No endpoint or user is emitted.
    return hashlib.sha256(
        parsed.set(password=None).render_as_string(hide_password=True).encode()
    ).hexdigest()


def migration_head():
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def key_binding(connection, vault, tables):
    if "deployment_state" in tables:
        table = Table("deployment_state", MetaData(), autoload_with=connection)
        value = connection.execute(
            select(table.c.payload).where(table.c.id == "security-history")
        ).scalar()
        if value:
            return vault.open(value, "deployment", "security-history")
    # Validate against existing encrypted data even before the binding migration.
    from canvas_bridge.storage_crypto import PREFIX

    verified = False
    for name in tables & set(Base.metadata.tables):
        table = Table(name, MetaData(), autoload_with=connection)
        for field in table.columns:
            if field.name in {"credential", "payload", "source_id", "canvas_user", "text", "csrf"}:
                row = (
                    connection.execute(select(table).where(field.is_not(None)).limit(1))
                    .mappings()
                    .first()
                )
                if not row:
                    continue
                value = row[field.name]
                if isinstance(value, str) and value.startswith(PREFIX):
                    vault.open(value[len(PREFIX) :], "database-field", f"{name}.{field.name}")
                    verified = True
                elif field.name == "credential" and value and name == "connections":
                    vault.open(value, row["owner"], row["id"])
                    verified = True
    return {"history": "unknown", "key_verified_against_records": verified}


def preflight(settings, *, store=None):
    result = {
        "schema_version": "deployment-preflight-1",
        "database_target": target_id(settings.database_url),
        "expected_revision": migration_head(),
        "service_health": "BLOCKED",
        "approval_health": "INDEPENDENT_REVIEW_REQUIRED",
        "findings": [],
        "historical_deletion_assurance": "unknown",
    }
    owns_store = store is None
    url = make_url(settings.database_url)
    absent_sqlite = (
        url.get_backend_name() == "sqlite"
        and url.database not in {None, "", ":memory:"}
        and not Path(url.database).exists()
    )
    store = store or Store("sqlite:///:memory:" if absent_sqlite else settings.database_url)
    try:
        with store.engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            result["new_installation"] = not tables
            result["revision"] = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if "alembic_version" in tables
                else None
            )
            missing = [
                name + "." + col.name
                for name, table in Base.metadata.tables.items()
                for col in table.columns
                if name not in tables
                or col.name not in {c["name"] for c in inspector.get_columns(name)}
            ]
            result["missing_schema_fields"] = sorted(missing)
            if result["revision"] != result["expected_revision"] or missing:
                result["findings"].append("SCHEMA_UPGRADE_REQUIRED")
            vault = None
            try:
                if settings.vault_key_file.is_symlink():
                    raise ValueError()
                vault = Vault(settings.vault_key_file)
                binding = key_binding(connection, vault, tables)
                result["historical_deletion_assurance"] = binding["history"]
                result["key_binding"] = (
                    "verified"
                    if binding.get("key_verified_against_records")
                    or binding.get("canary") == "bridge-security-history-v1"
                    else "unbound"
                )
            except FileNotFoundError:
                result["findings"].append("VAULT_KEY_MISSING")
            except Exception:
                result["findings"].append("VAULT_KEY_UNREADABLE_OR_MISMATCH")
            if not settings.deletion_journal.is_file():
                result["findings"].append(
                    "NEW_INSTALLATION_JOURNAL_REQUIRED"
                    if not tables
                    else "ESTABLISHED_JOURNAL_MISSING"
                )
            elif vault:
                try:
                    if settings.deletion_journal.is_symlink():
                        raise ValueError()
                    read_journal(settings.deletion_journal, vault.key)
                except Exception:
                    result["findings"].append("DELETION_JOURNAL_INVALID")
            if not result["findings"]:
                result["service_health"] = "READY"
    except Exception:
        result["findings"].append("DATABASE_INSPECTION_FAILED")
    finally:
        if owns_store:
            store.close()
    result["recovery_action"] = (
        "Stop service and workers; confirm database_target, preserve the existing key and journal, then use deployment-upgrade with an exclusive encrypted backup. Never regenerate lost security material."
    )
    return result


def require_ready(settings):
    status = preflight(settings)
    if status["service_health"] != "READY":
        raise RuntimeError(
            "Startup preflight blocked: "
            + ", ".join(status["findings"])
            + ". Run canvas-bridge doctor."
        )
    return status


def _bind(store, vault, history):
    table = Base.metadata.tables["deployment_state"]
    with store.engine.begin() as connection:
        value = vault.seal(
            {
                "canary": "bridge-security-history-v1",
                "history": history,
                "key_verified_against_records": True,
            },
            "deployment",
            "security-history",
        )
        connection.execute(table.delete().where(table.c.id == "security-history"))
        connection.execute(table.insert().values(id="security-history", payload=value))


def upgrade(
    settings, expected_target, backup_path: Path, *, new_installation=False, create_key=False
):
    if target_id(settings.database_url) != expected_target:
        raise ValueError("DEPLOYMENT_TARGET_MISMATCH")
    if backup_path.exists():
        raise FileExistsError("BACKUP_DESTINATION_EXISTS")
    before = preflight(settings)
    fresh = before.get("new_installation", False)
    if new_installation != fresh:
        raise ValueError("INSTALLATION_KIND_MISMATCH")
    if create_key and (not fresh or settings.vault_key_file.exists()):
        raise ValueError("REFUSING_KEY_REPLACEMENT")
    if fresh and create_key:
        Vault.create(settings.vault_key_file)
    vault = Vault(settings.vault_key_file)
    if fresh and not settings.deletion_journal.exists():
        with settings.deletion_journal.open("x", encoding="utf-8"):
            pass
        settings.deletion_journal.chmod(0o600)
    # Existing missing journals are never bootstrapped by an upgrade.
    read_journal(settings.deletion_journal, vault.key)
    store = Store(settings.database_url)
    try:
        with store.engine.connect() as connection:
            if store.engine.dialect.name == "postgresql":
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                tables = set(inspect(connection).get_table_names())
                binding = key_binding(connection, vault, tables)
                snapshot = {}
                for name in sorted(tables):
                    table = Table(name, MetaData(), autoload_with=connection)
                    query = select(table)
                    if name == "independent_resources":
                        query = query.where(table.c.kind == "institutional_lineage")
                    snapshot[name] = [dict(r) for r in connection.execute(query).mappings()]
        payload = {
            "format": "bridge-preupgrade-1",
            "target": expected_target,
            "revision": before.get("revision"),
            "created_at": utcnow().isoformat(),
            "expires_at": (utcnow() + timedelta(days=30)).isoformat(),
            "tables": json.loads(json.dumps(snapshot, default=str)),
            "restoration": "Operator-reviewed schema-specific recovery only; never reactivate credentials or omit current deletion fences.",
        }
        sealed = vault.seal(payload, "operator", "preupgrade")
        # Exclusive creation, then decrypt/read-back verification before any schema mutation.
        with os.fdopen(
            os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
        ) as stream:
            stream.write(sealed)
            stream.flush()
            os.fsync(stream.fileno())
        if vault.open(backup_path.read_text(encoding="utf-8"), "operator", "preupgrade") != payload:
            raise ValueError("BACKUP_VERIFICATION_FAILED")
        migrate(settings.database_url, settings.vault_key_file)
        _bind(store, vault, "fresh_installation" if fresh else binding.get("history", "unknown"))
    finally:
        store.close()
    after = require_ready(settings)
    return {"upgrade": "completed", "backup": "encrypted_and_verified", "preflight": after}


def recover_journal(settings, expected_target, *, acknowledge_history_loss=False):
    if expected_target != target_id(settings.database_url) or not acknowledge_history_loss:
        raise ValueError("EXPLICIT_RECOVERY_ACKNOWLEDGEMENT_REQUIRED")
    if settings.deletion_journal.exists():
        raise ValueError("REFUSING_JOURNAL_REPLACEMENT")
    vault = Vault(settings.vault_key_file)
    store = Store(settings.database_url)
    try:
        with store.engine.connect() as connection:
            key_binding(connection, vault, set(inspect(connection).get_table_names()))
        # The persisted marker makes the history loss visible and forbids restore.
        _bind(store, vault, "unknown_after_explicit_recovery")
        with settings.deletion_journal.open("x", encoding="utf-8"):
            pass
        settings.deletion_journal.chmod(0o600)
    finally:
        store.close()
    return {
        "journal": "recreated_after_explicit_acknowledgement",
        "historical_deletion_assurance": "unknown",
        "backup_restore": "blocked",
    }
