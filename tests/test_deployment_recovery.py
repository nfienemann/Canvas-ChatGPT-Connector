"""Disposable database fixtures only. No configured deployment is modified."""

import os

import pytest
from alembic import command
from alembic.config import Config
from cryptography.exceptions import InvalidTag
from sqlalchemy import text

from canvas_bridge.deployment import preflight, recover_journal, target_id, upgrade
from canvas_bridge.lifecycle import journal_delete
from canvas_bridge.resources import resource_root
from canvas_bridge.storage import Store


def file_database(settings, tmp_path):
    settings.database_url = "sqlite:///" + (tmp_path / "fixture.db").as_posix()
    return target_id(settings.database_url)


def test_new_installation_and_read_only_preflight(settings, tmp_path):
    target = file_database(settings, tmp_path)
    settings.deletion_journal.unlink()
    settings.vault_key_file.unlink()
    before = preflight(settings)
    assert before["new_installation"] and "NEW_INSTALLATION_JOURNAL_REQUIRED" in before["findings"]
    assert not settings.vault_key_file.exists() and not settings.deletion_journal.exists()
    assert not (tmp_path / "fixture.db").exists()
    result = upgrade(
        settings, target, tmp_path / "before.sealed", new_installation=True, create_key=True
    )
    assert result["preflight"]["service_health"] == "READY"
    assert result["preflight"]["historical_deletion_assurance"] == "fresh_installation"
    assert result["preflight"]["approval_health"] == "INDEPENDENT_REVIEW_REQUIRED"
    assert "tables" not in (tmp_path / "before.sealed").read_text()


@pytest.mark.parametrize("revision", ["9b2a41e5021c", "62ab7d391c04"])
def test_missing_authentication_column_upgrade_preserves_unknown_history(
    settings, tmp_path, revision
):
    target = file_database(settings, tmp_path)
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, revision)
    before = preflight(settings)
    assert "connections.authentication_state" in before["missing_schema_fields"]
    assert before["service_health"] == "BLOCKED"
    result = upgrade(settings, target, tmp_path / "upgrade.sealed")
    assert result["preflight"]["service_health"] == "READY"
    assert result["preflight"]["historical_deletion_assurance"] == "unknown"


def test_wrong_database_and_backup_collision_never_migrate(settings, tmp_path):
    target = file_database(settings, tmp_path)
    with pytest.raises(ValueError, match="TARGET_MISMATCH"):
        upgrade(settings, "another-database", tmp_path / "bad.sealed", new_installation=True)
    path = tmp_path / "occupied.sealed"
    path.write_text("do-not-replace")
    with pytest.raises(FileExistsError):
        upgrade(settings, target, path, new_installation=True)
    assert preflight(settings)["revision"] is None
    assert path.read_text() == "do-not-replace"


@pytest.mark.parametrize(
    "failure", ["missing_key", "wrong_key", "missing_journal", "tampered_journal"]
)
def test_established_security_material_never_silently_recreated(settings, tmp_path, failure):
    target = file_database(settings, tmp_path)
    upgrade(settings, target, tmp_path / "before.sealed", new_installation=True)
    if failure == "missing_key":
        settings.vault_key_file.unlink()
    elif failure == "wrong_key":
        settings.vault_key_file.write_bytes(os.urandom(32))
    elif failure == "missing_journal":
        settings.deletion_journal.unlink()
    else:
        settings.deletion_journal.write_text('{"tampered": true}')
    state = preflight(settings)
    assert state["service_health"] == "BLOCKED"
    with pytest.raises((FileNotFoundError, InvalidTag, KeyError, ValueError)):
        upgrade(settings, target, tmp_path / "after.sealed")
    assert not (tmp_path / "after.sealed").exists()
    if failure == "missing_journal":
        with pytest.raises(FileNotFoundError):
            journal_delete(settings.deletion_journal, b"0" * 32, "fictional", 1)
        assert not settings.deletion_journal.exists()
        recover_journal(settings, target, acknowledge_history_loss=True)
        assert (
            preflight(settings)["historical_deletion_assurance"]
            == "unknown_after_explicit_recovery"
        )


def test_report_sanitizes_database_errors(settings, tmp_path):
    file_database(settings, tmp_path)
    store = Store(settings.database_url)
    with store.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (wrong_field TEXT)"))
    store.close()
    result = preflight(settings)
    assert "DATABASE_INSPECTION_FAILED" in result["findings"]
    assert str(tmp_path) not in str(result)
