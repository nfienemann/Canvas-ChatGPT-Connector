"""Explicit personal PostgreSQL upgrades. Never invoked by application startup."""

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from canvas_bridge.config import Settings
from canvas_bridge.deployment import preflight, target_id
from canvas_bridge.maintenance import LOCK_ID, upgrade_connection
from canvas_bridge.resources import resource_root


class UpgradeBlocked(RuntimeError):
    """Only constant, non-sensitive diagnostic codes cross the CLI boundary."""


def load_deployment(root):
    root = root.resolve(strict=True)
    env = root / ".env"
    if not env.is_file() or env.is_symlink():
        raise UpgradeBlocked("EXPLICIT_DEPLOYMENT_ENV_REQUIRED")
    if any(k.startswith("BRIDGE_") for k in os.environ):
        raise UpgradeBlocked("AMBIENT_BRIDGE_OVERRIDES_FORBIDDEN")
    if any(k.startswith("PG") for k in os.environ):
        raise UpgradeBlocked("AMBIENT_LIBPQ_OVERRIDES_FORBIDDEN")
    values = dotenv_values(env, interpolate=False)
    if values.get("BRIDGE_PROFILE") != "personal" or not values.get("BRIDGE_DATABASE_URL"):
        raise UpgradeBlocked("EXPLICIT_PERSONAL_POSTGRESQL_REQUIRED")
    # Same working directory as the service, including all relative security paths.
    os.chdir(root)
    settings = Settings(_env_file=env)
    url = make_url(settings.database_url)
    if (
        url.drivername != "postgresql+psycopg"
        or not all((url.host, url.port, url.database, url.username))
        or url.query
    ):
        raise UpgradeBlocked("EXPLICIT_POSTGRESQL_ENDPOINT_REQUIRED_NO_URL_OPTIONS")
    return settings


def fingerprint(settings):
    url = make_url(settings.database_url)
    return dict(
        backend=url.get_backend_name(),
        host=url.host,
        port=url.port,
        database=url.database,
        role=url.username,
        profile=settings.profile,
        target=target_id(settings.database_url),
    )


def service_status(root, settings):
    """Bounded local metadata probe only; no Canvas, issuer or tunnel requests."""
    result = {
        "pid_file_present": (root / "service.pid").is_file(),
        "metadata_matches": False,
        "state": "unreachable_or_not_running",
    }
    connection = http.client.HTTPConnection("127.0.0.1", settings.port, timeout=2)
    try:
        connection.request("GET", "/.well-known/oauth-protected-resource")
        response = connection.getresponse()
        payload = response.read(16385)
        if response.status == 200 and len(payload) <= 16384:
            result["metadata_matches"] = (
                json.loads(payload).get("resource") == settings.resource_url
            )
        result["state"] = (
            "matching_service" if result["metadata_matches"] else "unverified_listener"
        )
    except Exception:
        result["state"] = "unreachable_or_invalid_metadata"
    finally:
        connection.close()
    return result


def migration_config(settings):
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    config.attributes.update(
        database_url=settings.database_url, vault_key_file=settings.vault_key_file.resolve()
    )
    return config


def migration_plan(settings, current):
    scripts = ScriptDirectory.from_config(migration_config(settings))
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise UpgradeBlocked("DIVERGENT_MIGRATION_HEADS")
    if not current:
        raise UpgradeBlocked("MISSING_REVISION_PROVISION_OR_RECOVER_EXPLICITLY")
    try:
        scripts.get_revision(current)
        pending = list(reversed(list(scripts.iterate_revisions(heads[0], current))))
    except Exception:
        raise UpgradeBlocked("UNKNOWN_OR_DIVERGENT_DATABASE_REVISION") from None
    if any(step.is_branch_point or step.is_merge_point for step in pending):
        raise UpgradeBlocked("BRANCHED_MIGRATION_PATH_REQUIRES_SEPARATE_REVIEW")
    steps = []
    for step in pending:
        source = Path(step.path).read_bytes()
        # Conservative source review cues, never a certification of migration safety.
        risks = ["OPERATOR_SOURCE_REVIEW_REQUIRED"]
        for pattern, label in (
            (rb"Vault|vault_key|seal\(", "EXISTING_KEY_REQUIRED_ONE_WAY_ENCRYPTION"),
            (rb"drop_|delete\(|DELETE |truncate", "POSSIBLE_DATA_LOSS"),
            (rb"alter_column|UPDATE |\.update\(", "DATA_REWRITE"),
            (rb"authentication|revocation|deployment_state", "SECURITY_STATE_CHANGE"),
            (rb"raise RuntimeError", "DOWNGRADE_MAY_BE_UNSUPPORTED"),
        ):
            if re.search(pattern, source):
                risks.append(label)
        steps.append(
            dict(
                revision=step.revision,
                source=Path(step.path).name,
                sha256=hashlib.sha256(source).hexdigest(),
                risks=risks,
            )
        )
    return heads[0], steps


def inspect_database(settings):
    engine = create_engine(
        settings.database_url, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                raise UpgradeBlocked("MISSING_REVISION_PROVISION_OR_RECOVER_EXPLICITLY")
            revisions = list(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
            if len(revisions) != 1:
                raise UpgradeBlocked("MISSING_OR_MULTIPLE_DATABASE_REVISIONS")
            identity = connection.execute(
                text(
                    "SELECT current_database(), current_user, inet_server_port(), current_setting('server_version_num')"
                )
            ).one()
            url = make_url(settings.database_url)
            if (identity[0], identity[1], identity[2]) != (url.database, url.username, url.port):
                raise UpgradeBlocked("CONNECTED_DATABASE_IDENTITY_MISMATCH")
        head, pending = migration_plan(settings, revisions[0])
        # Diagnostics remain read-only and available while an upgrade hold is present.
        token = upgrade_connection.set(True)
        try:
            state = preflight(settings)
        finally:
            upgrade_connection.reset(token)
        blockers = [f for f in state["findings"] if f != "SCHEMA_UPGRADE_REQUIRED"]
        if not pending and state.get("missing_schema_fields"):
            blockers.append("HEAD_SCHEMA_INVARIANTS_MISSING")
        if not pending and not blockers:
            with engine.connect() as connection:
                connection.execute(text("SELECT authentication_state FROM connections WHERE 1=0"))
                connection.execute(text("SELECT workload_scope FROM snapshots WHERE 1=0"))
        return dict(
            database=fingerprint(settings),
            current=revisions[0],
            head=head,
            pending=pending,
            blockers=blockers,
            server_major=int(identity[3]) // 10000,
            key_binding=state.get("key_binding"),
            historical_deletion_assurance=state["historical_deletion_assurance"],
            approval_health=state["approval_health"],
        )
    finally:
        engine.dispose()


def run_process(arguments, *, env=None):
    # Never relay child output: pg tools can include private connection details.
    result = subprocess.run(  # noqa: S603 - operator-selected local tools, argument arrays only
        arguments,
        env=env,
        capture_output=True,
        timeout=1800,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise UpgradeBlocked("BACKUP_OR_SERVICE_PROCESS_FAILED")
    return result.stdout


def private_directory(path):
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        sid = (
            run_process(
                [
                    str(shell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
                ]
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise UpgradeBlocked("BACKUP_ACL_IDENTITY_FAILED")
        run_process(
            [
                str(Path(os.environ["SystemRoot"]) / "System32/icacls.exe"),
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
            ]
        )


def backup_destination(parent):
    parent = parent.resolve(strict=True)
    excluded = [resource_root().resolve()]
    excluded.extend(
        Path(v).resolve() for k, v in os.environ.items() if k.lower().startswith("onedrive") and v
    )
    if any(parent.is_relative_to(p) for p in excluded) or any(
        "onedrive" in p.lower() for p in parent.parts
    ):
        raise UpgradeBlocked("BACKUP_MUST_BE_OUTSIDE_REPOSITORY_AND_ONEDRIVE")
    return parent / ("bridge-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)


def logical_backup(settings, plan, destination, pg_bin):
    suffix = ".exe" if os.name == "nt" else ""
    dump, restore = (pg_bin / (name + suffix) for name in ("pg_dump", "pg_restore"))
    for tool in (dump, restore):
        if not tool.is_file():
            raise UpgradeBlocked("POSTGRESQL_BACKUP_TOOL_MISSING")
        version = run_process([str(tool), "--version"])
        match = re.search(rb"\b(\d+)\.\d+", version)
        if not match or int(match[1]) != plan["server_major"]:
            raise UpgradeBlocked("POSTGRESQL_BACKUP_TOOL_MAJOR_MISMATCH")
    private_directory(destination)
    archive = destination / "database.dump"
    url = make_url(settings.database_url)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "BRIDGE_"))}
    env.update(
        PGHOST=url.host,
        PGPORT=str(url.port),
        PGDATABASE=url.database,
        PGUSER=url.username,
        PGPASSWORD=url.password or "",
        PGCONNECT_TIMEOUT="5",
    )
    run_process([str(dump), "--no-password", "-Fc", "--file", str(archive)], env=env)
    if not archive.is_file() or archive.stat().st_size == 0:
        raise UpgradeBlocked("BACKUP_MISSING_OR_EMPTY")
    if not run_process([str(restore), "-l", str(archive)], env=env).strip():
        raise UpgradeBlocked("BACKUP_ARCHIVE_UNREADABLE")
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = dict(
        target=plan["database"],
        revision=plan["current"],
        sha256=checksum,
        archive=str(archive),
        verification="archive_listing_only_not_test_restore",
        created_at=datetime.now(UTC).isoformat(),
    )
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


@contextmanager
def maintenance(settings):
    engine = create_engine(
        settings.database_url, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    token = upgrade_connection.set(True)
    try:
        with engine.connect() as connection:
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}):
                raise UpgradeBlocked("APPLICATION_OR_UPGRADE_STILL_ACTIVE")
            try:
                # Also catches older service builds that do not participate in the fence.
                count = connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
                    )
                )
                if count:
                    raise UpgradeBlocked("OTHER_DATABASE_SESSIONS_ACTIVE_STOP_WORKERS")
                yield connection
            finally:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
    finally:
        upgrade_connection.reset(token)
        engine.dispose()


def confirm(phrase):
    if not sys.stdin.isatty() or input(f"Type exactly '{phrase}' to continue: ") != phrase:
        raise UpgradeBlocked("OPERATOR_CONFIRMATION_REQUIRED")


def security_snapshot(root, settings):
    return [
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / ".env", settings.vault_key_file, settings.deletion_journal)
    ]


def verify_backup(metadata):
    with Path(metadata["archive"]).open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != metadata["sha256"]:
            raise UpgradeBlocked("BACKUP_CHANGED_AFTER_VERIFICATION")


def arguments(sub):
    parser = sub.add_parser(
        "database-upgrade", help="Explicit personal deployment; defaults to check-only."
    )
    parser.add_argument("--deployment-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    for name in ("check", "status", "backup-only", "backup-and-apply"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--expected-target")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--pg-bin", type=Path, default=resource_root() / ".tools/pgsql/bin")
    parser.add_argument("--stop-application", action="store_true")


def run(args):
    root = args.deployment_root.resolve(strict=True)
    # Resolve operator paths before switching to the service directory.
    parent = args.backup_dir.resolve() if args.backup_dir else None
    pg_bin = args.pg_bin.resolve()
    marker = root / ".database-maintenance"
    status_path = root / "database-upgrade-result.json"
    modified = False
    backup = None
    try:
        settings = load_deployment(root)
        plan = inspect_database(settings)
        print(
            json.dumps(
                {
                    **plan,
                    "configuration_source": str(root / ".env"),
                    "maintenance_hold": marker.exists(),
                    "application": service_status(root, settings),
                },
                indent=2,
            )
        )
        if args.status:
            if status_path.is_file():
                # Only known fields, never echo arbitrary state-file content.
                previous = json.loads(status_path.read_text(encoding="utf-8"))
                print(
                    json.dumps(
                        {
                            "last_result": previous.get("result")
                            if previous.get("result") in {"verified", "failed"}
                            else "unknown"
                        }
                    )
                )
            return 0 if not plan["blockers"] else 1
        if not (args.backup_only or args.backup_and_apply):
            return 0 if not plan["blockers"] else 1
        if plan["blockers"]:
            raise UpgradeBlocked("SECURITY_PREFLIGHT_BLOCKED")
        if args.expected_target != plan["database"]["target"] or parent is None:
            raise UpgradeBlocked("EXPECTED_TARGET_AND_BACKUP_DIRECTORY_REQUIRED")
        if args.backup_and_apply and not plan["pending"]:
            print("Database already current; no changes made.")
            return 0
        destination = backup_destination(parent)
        print(f"Backup: {destination}. Keep a secure separate copy of the EXISTING vault key.")
        print(
            "Archive listing is not a full restore test. Review all pending migration source hashes and risks."
        )
        confirm("BACKUP " + plan["database"]["target"] + " KEY COPY SECURED")
        if args.backup_only:
            from canvas_bridge.storage import Store

            store = Store(settings.database_url)
            try:
                # Shared fence permits ordinary service activity but excludes an upgrader.
                with store.engine.connect():
                    if inspect_database(settings) != plan:
                        raise UpgradeBlocked("PREFLIGHT_CHANGED")
                    backup = logical_backup(settings, plan, destination, pg_bin)
            finally:
                store.close()
            print(json.dumps(backup, indent=2))
            return 0
        confirm("MAINTENANCE " + plan["database"]["target"])
        security_before = security_snapshot(root, settings)
        # Exclusive creation serializes operators and blocks ordinary startup; failure keeps the hold.
        with marker.open("x", encoding="utf-8") as stream:
            stream.write(
                "Explicit upgrade in progress; on failure preserve backup and review recovery.\n"
            )
        modified = True
        if args.stop_application:
            shell = (
                Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            run_process(
                [
                    str(shell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(resource_root() / "scripts/Stop-BridgeApplication.ps1"),
                    "-DeploymentRoot",
                    str(root),
                    "-Python",
                    sys.executable,
                    "-BasePython",
                    sys._base_executable,
                    "-Port",
                    str(settings.port),
                    "-ResourceUrl",
                    settings.resource_url,
                ]
            )
        with maintenance(settings) as locked_connection:
            if inspect_database(settings) != plan:
                raise UpgradeBlocked("PREFLIGHT_CHANGED")
            backup = logical_backup(settings, plan, destination, pg_bin)
            print(json.dumps(backup, indent=2))
            confirm(
                f"APPLY {plan['database']['target']} {plan['current']} {plan['head']} RISKS REVIEWED"
            )
            if inspect_database(settings) != plan:
                raise UpgradeBlocked("PREFLIGHT_CHANGED")
            if security_snapshot(root, settings) != security_before:
                raise UpgradeBlocked("SECURITY_CONFIGURATION_CHANGED")
            verify_backup(backup)
            # Verify the lock session survived backup/interactive review, then run
            # migrations on that session so a lost connection cannot lose only the fence.
            locked_connection.execute(text("SELECT 1"))
            locked_connection.commit()
            config = migration_config(settings)
            config.attributes["connection"] = locked_connection
            command.upgrade(config, plan["head"])
            after = inspect_database(settings)
            if after["current"] != plan["head"] or after["blockers"] or after["pending"]:
                raise UpgradeBlocked("POSTFLIGHT_FAILED")
            status_path.write_text(
                json.dumps(
                    dict(
                        result="verified",
                        before=plan["current"],
                        after=after["current"],
                        backup=backup,
                    )
                ),
                encoding="utf-8",
            )
            marker.unlink()
        print("Upgrade verified. Restart the application explicitly with the normal launcher.")
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, UpgradeBlocked) else "DATABASE_UPGRADE_BLOCKED_OR_FAILED"
        observed_revision = "unknown; run --status"
        if modified:
            try:
                observed_revision = inspect_database(settings)["current"]
            except Exception:
                observed_revision = "unavailable; preserve backup and run --status"
            try:
                status_path.write_text(
                    json.dumps(dict(result="failed", backup=backup)), encoding="utf-8"
                )
            except OSError:
                pass  # The maintenance hold still fences restart; never print raw file errors.
        print(
            json.dumps(
                dict(
                    error=code,
                    current_revision=observed_revision,
                    maintenance_hold=marker.exists(),
                    recovery="Preserve backup, existing key and deletion journal. Run --status. No retry, downgrade or stamp. Resolve the failure before explicitly removing the maintenance hold.",
                )
            )
        )
        return 1
