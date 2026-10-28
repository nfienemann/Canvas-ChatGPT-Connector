import socket
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.desktop import (
    AlreadyRunning,
    DemoRuntime,
    DemoSettings,
    default_data_directory,
    remember_directory,
    remembered_directory,
)
from canvas_bridge.storage import Connection, Course, Store


def test_T01_T35_desktop_ignores_operator_environment_and_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRIDGE_PROFILE", "hosted")
    monkeypatch.setenv("BRIDGE_LIVE_ACCESS_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_HOST", "0.0.0.0")  # noqa: S104 - prove unsafe inherited config is ignored
    monkeypatch.setenv("BRIDGE_DATABASE_URL", "postgresql+psycopg://invalid.example/live")
    Path(".env").write_text("BRIDGE_PROFILE=personal\n", encoding="utf-8")
    runtime = DemoRuntime(tmp_path / "A student's dÃ©monstration", preferred_port=0)
    try:
        runtime.start()
        assert runtime.settings.profile == "synthetic"
        assert runtime.settings.host == "127.0.0.1"
        assert not runtime.settings.live_access_enabled
        result = runtime.check()
        assert result["observed_obligations"] == 5
        assert result["planning"] == "verified"
        assert result["actual_chatgpt"] == "not_tested"
        with httpx.Client(trust_env=False) as client:
            response = client.get(runtime.url)
            assert response.status_code == 200
            assert "synthetic" in response.text
        assert Path(".env").read_text() == "BRIDGE_PROFILE=personal\n"
    finally:
        runtime.stop()
    # Windows refuses this rename if the application's pooled DB handles leak.
    database = runtime.folder / "bridge.db"
    database.rename(runtime.folder / "closed.db")


def test_T35_desktop_port_collision_lock_and_restart_preserve_data(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        busy_port = occupied.getsockname()[1]
        first = DemoRuntime(tmp_path, preferred_port=busy_port)
        first.start()
        try:
            assert first.settings.port != busy_port
            vault_before = (tmp_path / "vault.key").read_bytes()
            store = Store(first.settings.database_url)
            from canvas_bridge.vault import Vault

            store.protect(Vault(first.settings.vault_key_file))
            with store.transaction() as session:
                connection_id = session.scalar(select(Connection.id))
                course = session.scalar(select(Course).order_by(Course.id))
                course.selected = False
                course_id = course.id
            store.close()
            with pytest.raises(AlreadyRunning):
                DemoRuntime(tmp_path).start()
        finally:
            first.stop()
    second = DemoRuntime(tmp_path, preferred_port=0)
    try:
        second.start()
        assert (tmp_path / "vault.key").read_bytes() == vault_before
        store = Store(second.settings.database_url)
        store.protect(Vault(second.settings.vault_key_file))
        with store.transaction() as session:
            assert session.scalar(select(Connection.id)) == connection_id
            assert not session.get(Course, course_id).selected
        store.close()
    finally:
        second.stop()


def test_desktop_failed_initialization_releases_lock(tmp_path):
    (tmp_path / "vault.key").write_bytes(b"damaged")
    for diagnostic in ("VAULT_KEY_UNREADABLE_OR_MISMATCH", "explicit deployment recovery"):
        with pytest.raises(RuntimeError, match=diagnostic):
            DemoRuntime(tmp_path, preferred_port=0).start()
    assert (tmp_path / "vault.key").read_bytes() == b"damaged"


def test_desktop_data_location_is_remembered_without_operator_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canvas_bridge.desktop.default_data_directory", lambda: tmp_path / "default"
    )
    assert remembered_directory() == tmp_path / "default"
    picked = tmp_path / "custom folder"
    remember_directory(picked)
    assert remembered_directory() == picked
    preferences = tmp_path / "Canvas Bridge Launcher/preferences.json"
    preferences.write_text('{"data_directory":"relative"}', encoding="utf-8")
    assert remembered_directory() == tmp_path / "default"
    preferences.write_text("not json", encoding="utf-8")
    assert remembered_directory() == tmp_path / "default"


def test_desktop_defaults_are_per_user_and_loopback():
    assert default_data_directory().is_absolute()
    assert DemoSettings().profile == "synthetic"
