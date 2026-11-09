"""Creates its own disposable loopback cluster; no configured PostgreSQL is used."""

import argparse
import json
import os
import socket
import subprocess
import time

import psycopg
import pytest
from alembic import command
from sqlalchemy import text

from canvas_bridge import database_upgrade as db
from canvas_bridge.deployment import require_ready
from canvas_bridge.maintenance import upgrade_connection
from canvas_bridge.resources import resource_root
from canvas_bridge.storage import Store
from canvas_bridge.storage_crypto import PREFIX
from canvas_bridge.vault import Vault


@pytest.fixture
def disposable_postgres(tmp_path, settings):
    pg_bin = resource_root() / ".tools/pgsql/bin"
    suffix = ".exe" if os.name == "nt" else ""
    if not (pg_bin / ("initdb" + suffix)).is_file():
        pytest.skip("Bundled PostgreSQL unavailable; no external database fallback")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    data = tmp_path / "cluster with spaces"
    db.run_process(
        [
            str(pg_bin / ("initdb" + suffix)),
            "-D",
            str(data),
            "-U",
            "fixture",
            "-A",
            "trust",
            "--no-locale",
            "--encoding=UTF8",
        ]
    )
    with (tmp_path / "postgres.log").open("wb") as log:
        process = subprocess.Popen(  # noqa: S603 - disposable bundled server
            [
                str(pg_bin / ("postgres" + suffix)),
                "-D",
                str(data),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
            ],
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            for _ in range(100):
                try:
                    with psycopg.connect(
                        host="127.0.0.1",
                        port=port,
                        user="fixture",
                        dbname="postgres",
                        connect_timeout=1,
                        autocommit=True,
                    ) as conn:
                        conn.execute("CREATE DATABASE fixture")
                    break
                except psycopg.OperationalError:
                    time.sleep(0.1)
            else:
                pytest.fail("Disposable PostgreSQL startup failed")
            settings.database_url = f"postgresql+psycopg://fixture@127.0.0.1:{port}/fixture"
            yield settings, pg_bin
        finally:
            db.run_process(
                [str(pg_bin / ("pg_ctl" + suffix)), "stop", "-D", str(data), "-m", "fast", "-w"]
            )
            process.wait(timeout=15)


def test_real_archive_upgrade_restore_and_writer_fence(disposable_postgres, tmp_path, monkeypatch):
    # Optional test-runtime locations are not deployment overrides. Keep them
    # outside this CLI invocation, which intentionally rejects ambient BRIDGE_*
    # values. Actual deployment overrides must still fail closed.
    for name in tuple(os.environ):
        if name.startswith("BRIDGE_TEST_"):
            monkeypatch.delenv(name)
    settings, pg_bin = disposable_postgres
    key_before = settings.vault_key_file.read_bytes()
    command.upgrade(db.migration_config(settings), "62ab7d391c04")
    seed = Store(settings.database_url)
    with seed.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO connections (id,owner,institution,canvas_user,state,epoch,credential,timezone,created_at) "
                "VALUES ('fixture','fixture','synthetic','101','disabled',0,:credential,'UTC',CURRENT_TIMESTAMP)"
            ),
            {
                "credential": Vault(settings.vault_key_file).seal(
                    {"access_token": "fictional-revoked-token"}, "fixture", "fixture"
                )
            },
        )
    seed.close()
    before = db.inspect_database(settings)
    assert before["pending"] and not before["blockers"]
    assert before["key_binding"] == "verified"
    with pytest.raises(RuntimeError, match="DATABASE_MIGRATION_REQUIRED"):
        require_ready(settings)
    writer = Store(settings.database_url)
    with writer.engine.connect():
        with pytest.raises(db.UpgradeBlocked, match="STILL_ACTIVE"):
            with db.maintenance(settings):
                pytest.fail("Live writer was not fenced")
    writer.close()
    with db.maintenance(settings):
        token = upgrade_connection.set(False)
        blocked = Store(settings.database_url)
        try:
            with pytest.raises(RuntimeError, match="DATABASE_MAINTENANCE"):
                with blocked.engine.connect():
                    pytest.fail("New writer entered maintenance")
        finally:
            blocked.close()
            upgrade_connection.reset(token)
    root = tmp_path / "personal with spaces"
    root.mkdir()
    (root / ".env").write_text(
        "BRIDGE_PROFILE=personal\nBRIDGE_PERSONAL_SUBJECT=fictional-owner\n"
        "BRIDGE_RESOURCE_URL=https://bridge.invalid\nBRIDGE_ISSUER_URL=https://issuer.invalid\n"
        "BRIDGE_JWKS_URL=https://issuer.invalid/jwks\n"
        f"BRIDGE_DATABASE_URL={settings.database_url}\n"
        f"BRIDGE_VAULT_KEY_FILE={settings.vault_key_file.as_posix()}\n"
        f"BRIDGE_DELETION_JOURNAL={settings.deletion_journal.as_posix()}\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "service_status", lambda *a: {"state": "synthetic"})
    monkeypatch.setattr(db, "confirm", lambda phrase: None)  # synthetic operator fixture only
    args = argparse.Namespace(
        deployment_root=root,
        backup_dir=tmp_path,
        pg_bin=pg_bin,
        status=False,
        backup_only=False,
        backup_and_apply=True,
        stop_application=False,
        expected_target=before["database"]["target"],
    )
    assert db.run(args) == 0
    archive = json.loads((root / "database-upgrade-result.json").read_text())["backup"]
    assert not (root / ".database-maintenance").exists()
    after = db.inspect_database(settings)
    assert after["current"] == before["head"] and not after["blockers"]
    assert not after["pending"]
    assert settings.vault_key_file.read_bytes() == key_before
    assert db.inspect_database(settings) == after
    verification = Store(settings.database_url)
    with verification.engine.connect() as conn:
        row = conn.execute(
            text("SELECT state,authentication_state,canvas_user FROM connections")
        ).one()
        assert row[0:2] == ("disabled", "unverified")
        assert row[2].startswith(PREFIX)
        assert Vault(settings.vault_key_file).open(
            row[2][len(PREFIX) :], "database-field", "connections.canvas_user"
        ) == {"value": "101"}
    verification.close()
    # Stronger than listing: restore into a different, disposable database.
    url = db.make_url(settings.database_url)
    with psycopg.connect(
        host=url.host, port=url.port, user=url.username, dbname="postgres", autocommit=True
    ) as conn:
        conn.execute("CREATE DATABASE restored")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST=url.host, PGPORT=str(url.port), PGUSER=url.username, PGDATABASE="restored")
    suffix = ".exe" if os.name == "nt" else ""
    db.run_process(
        [
            str(pg_bin / ("pg_restore" + suffix)),
            "--exit-on-error",
            "--dbname",
            "restored",
            archive["archive"],
        ],
        env=env,
    )
    with psycopg.connect(
        host=url.host, port=url.port, user=url.username, dbname="restored"
    ) as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == before["current"]
        )
        restored = conn.execute("SELECT state,credential FROM connections").fetchone()
        assert restored[0] == "disabled"
        assert (
            Vault(settings.vault_key_file).open(restored[1], "fixture", "fixture")["access_token"]
            == "fictional-revoked-token"
        )
    # Multiple revisions fail closed even when one happens to be the current head.
    store = Store(settings.database_url)
    with store.engine.begin() as conn:
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown')"))
    store.close()
    with pytest.raises(db.UpgradeBlocked, match="MULTIPLE"):
        db.inspect_database(settings)
