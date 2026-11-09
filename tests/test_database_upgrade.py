"""Synthetic upgrade safety checks; never select an installed database."""

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from canvas_bridge import database_upgrade as db
from canvas_bridge.deployment import require_ready


def test_explicit_deployment_ignores_repository_env(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("BRIDGE_"):
            monkeypatch.delenv(key)
    repo = tmp_path / "repo"
    service = tmp_path / "service with spaces"
    repo.mkdir()
    service.mkdir()
    (repo / ".env").write_text("BRIDGE_DATABASE_URL=sqlite:///wrong.db\n")
    (service / ".env").write_text(
        "BRIDGE_PROFILE=personal\nBRIDGE_PERSONAL_SUBJECT=fixture-owner\nBRIDGE_DATABASE_URL=postgresql+psycopg://fixture:secret@127.0.0.1:55555/fixture\n"
        "BRIDGE_RESOURCE_URL=https://bridge.invalid\nBRIDGE_ISSUER_URL=https://issuer.invalid\nBRIDGE_JWKS_URL=https://issuer.invalid/jwks\n"
    )
    monkeypatch.chdir(repo)
    settings = db.load_deployment(service)
    assert db.fingerprint(settings)["database"] == "fixture"
    assert "secret" not in json.dumps(db.fingerprint(settings))
    assert Path.cwd() == service
    assert not (repo / "wrong.db").exists()
    monkeypatch.setenv("BRIDGE_DATABASE_URL", "sqlite:///wrong.db")
    with pytest.raises(db.UpgradeBlocked, match="AMBIENT"):
        db.load_deployment(service)
    monkeypatch.delenv("BRIDGE_DATABASE_URL")
    monkeypatch.setenv("PGOPTIONS", "-c search_path=wrong_schema")
    with pytest.raises(db.UpgradeBlocked, match="LIBPQ"):
        db.load_deployment(service)


def test_migration_path_has_source_based_encryption_risk(settings):
    head, steps = db.migration_plan(settings, "62ab7d391c04")
    assert steps[-1]["revision"] == head
    encryption = next(s for s in steps if s["revision"] == "c7d9130b42ae")
    assert "EXISTING_KEY_REQUIRED_ONE_WAY_ENCRYPTION" in encryption["risks"]
    assert len(encryption["sha256"]) == 64
    assert db.migration_plan(settings, head) == (head, [])
    for revision in (None, "unknown"):
        with pytest.raises(db.UpgradeBlocked):
            db.migration_plan(settings, revision)


def test_startup_maintenance_hold_precedes_database_access(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".database-maintenance").touch()
    with pytest.raises(RuntimeError, match="DATABASE_MAINTENANCE"):
        require_ready(settings)


@pytest.fixture
def orchestration(tmp_path, monkeypatch, settings):
    root = tmp_path / "service"
    root.mkdir()
    settings.database_url = "postgresql+psycopg://fixture:secret@127.0.0.1:55555/fixture"
    plan = dict(
        database=db.fingerprint(settings),
        current="old",
        head="new",
        pending=[{"revision": "new"}],
        blockers=[],
        server_major=17,
    )
    args = argparse.Namespace(
        deployment_root=root,
        backup_dir=tmp_path,
        pg_bin=tmp_path,
        status=False,
        backup_only=False,
        backup_and_apply=True,
        stop_application=False,
        expected_target=plan["database"]["target"],
    )
    monkeypatch.setattr(db, "load_deployment", lambda root: settings)
    monkeypatch.setattr(db, "service_status", lambda *a: {"state": "synthetic"})
    monkeypatch.setattr(db, "inspect_database", lambda settings: plan.copy())
    monkeypatch.setattr(db, "confirm", lambda phrase: None)
    monkeypatch.setattr(db, "security_snapshot", lambda *a: ["unchanged"])
    monkeypatch.setattr(db, "verify_backup", lambda *a: None)
    monkeypatch.setattr(db, "logical_backup", lambda *a: {"archive": "fixture.dump"})

    @contextmanager
    def maintenance(settings):
        yield Mock()

    monkeypatch.setattr(db, "maintenance", maintenance)
    return args, plan


@pytest.mark.parametrize(
    "failure", ["target", "security", "backup", "migration", "postflight", "concurrent"]
)
def test_failures_never_restart_or_remove_hold(orchestration, monkeypatch, capsys, failure):
    args, plan = orchestration
    calls = []

    def migrate(*unused):
        calls.append("migration")
        if failure == "migration":
            raise RuntimeError("secret academic content")

    monkeypatch.setattr(db.command, "upgrade", migrate)
    if failure == "target":
        args.expected_target = "wrong"
    if failure == "security":
        plan["blockers"] = ["ESTABLISHED_JOURNAL_MISSING"]
    if failure == "backup":

        def bad_backup(*unused):
            raise RuntimeError("secret academic content")

        monkeypatch.setattr(db, "logical_backup", bad_backup)
    if failure == "concurrent":
        (args.deployment_root / ".database-maintenance").touch()
    assert db.run(args) == 1
    if failure in {"target", "security", "backup", "concurrent"}:
        assert calls == []
    assert "secret academic content" not in capsys.readouterr().out
    if failure in {"backup", "migration", "postflight", "concurrent"}:
        assert (args.deployment_root / ".database-maintenance").exists()


def test_success_verified_before_hold_removed(orchestration, monkeypatch):
    args, plan = orchestration

    def migrate(*unused):
        assert (args.deployment_root / ".database-maintenance").exists()
        plan.update(current="new", pending=[])

    monkeypatch.setattr(db.command, "upgrade", migrate)
    assert db.run(args) == 0
    assert not (args.deployment_root / ".database-maintenance").exists()
    assert (
        json.loads((args.deployment_root / "database-upgrade-result.json").read_text())["result"]
        == "verified"
    )
    assert db.run(args) == 0  # idempotent; no new backup or maintenance state


@pytest.mark.parametrize("failure", ["dump", "empty", "listing", "version", None])
def test_backup_checks_and_child_secret_isolation(settings, tmp_path, monkeypatch, failure):
    settings.database_url = "postgresql+psycopg://fixture:private-password@127.0.0.1:55555/fixture"
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("pg_dump", "pg_restore"):
        (tmp_path / (name + suffix)).touch()
    destination = tmp_path / "backup"
    monkeypatch.setattr(db, "private_directory", lambda p: p.mkdir())

    def process(args, env=None):
        assert "private-password" not in str(args)
        if "--version" in args:
            return (
                b"pg_dump (PostgreSQL) 16.1"
                if failure == "version"
                else b"pg_dump (PostgreSQL) 17.1"
            )
        assert env["PGPASSWORD"] == "private-password"
        if "-Fc" in args:
            if failure == "dump":
                raise db.UpgradeBlocked("BACKUP_OR_SERVICE_PROCESS_FAILED")
            (destination / "database.dump").write_bytes(
                b"" if failure == "empty" else b"fixture archive"
            )
            return b""
        if failure == "listing":
            raise db.UpgradeBlocked("BACKUP_OR_SERVICE_PROCESS_FAILED")
        return b"fixture archive listing"

    monkeypatch.setattr(db, "run_process", process)
    plan = dict(server_major=17, database=db.fingerprint(settings), current="fixture")
    if failure:
        with pytest.raises(db.UpgradeBlocked):
            db.logical_backup(settings, plan, destination, tmp_path)
    else:
        result = db.logical_backup(settings, plan, destination, tmp_path)
        assert result["verification"] == "archive_listing_only_not_test_restore"
        assert "private-password" not in json.dumps(result)
        assert len(result["sha256"]) == 64


def test_no_noninteractive_consent(monkeypatch):
    monkeypatch.setattr(db.sys.stdin, "isatty", lambda: False)
    with pytest.raises(db.UpgradeBlocked, match="CONFIRMATION"):
        db.confirm("APPLY")


def test_synced_backup_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path))
    with pytest.raises(db.UpgradeBlocked, match="OUTSIDE"):
        db.backup_destination(tmp_path)


def test_service_probe_uses_only_loopback_metadata(settings, tmp_path, monkeypatch):
    client = Mock()
    response = client.getresponse.return_value
    response.status = 200
    response.read.return_value = json.dumps({"resource": settings.resource_url}).encode()
    factory = Mock(return_value=client)
    monkeypatch.setattr(db.http.client, "HTTPConnection", factory)
    result = db.service_status(tmp_path, settings)
    assert result["state"] == "matching_service"
    factory.assert_called_once_with("127.0.0.1", settings.port, timeout=2)
    client.request.assert_called_once_with("GET", "/.well-known/oauth-protected-resource")
    client.close.assert_called_once()
