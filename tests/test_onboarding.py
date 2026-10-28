"""Fictional, local-only onboarding, update and deletion acceptance scenarios."""

import base64
import contextlib
import hashlib
import json
import socket
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from canvas_bridge.desktop import (
    AlreadyRunning,
    DemoRuntime,
    friendly_error,
    remember_directory,
    remembered_directory,
)
from canvas_bridge.desktop_profiles import migrate_profile, prepare_profile, remove_profile
from canvas_bridge.desktop_updates import canonical, launch_update, prepare_update, verify_release
from canvas_bridge.domain import DomainError
from canvas_bridge.onboarding import (
    OfflineRuntime,
    SetupError,
    authorized_services,
    converter_status,
    diagnostics,
    stage_report,
    verify_bundle,
)
from canvas_bridge.storage import Connection


def test_offline_first_task_needs_no_network_account_database_or_token(tmp_path, monkeypatch):
    def denied(*a, **kw):
        raise AssertionError("Offline edition attempted a network socket")

    monkeypatch.setattr(socket, "create_connection", denied)
    runtime = OfflineRuntime(tmp_path / "offline")
    try:
        runtime.start()
        result = runtime.check()
        assert result["calculated_percentage"] == "85" and result["network_requests"] == 0
        source = tmp_path / "fictional.txt"
        source.write_text(
            "Fictional diffusion practice: particles move down a concentration gradient."
        )
        with pytest.raises(DomainError):
            runtime.inspect(source)
        read = runtime.inspect(source, own_material=True)
        with pytest.raises(SetupError, match="TXT and Markdown"):
            runtime.inspect(tmp_path / "fictional.pdf", own_material=True)
        assert read["characters_extracted"] > 0 and read["retained_document"] is False
        assert read["stages"]["pixels_rendered"] == "not_requested"
        assert read["analysis"] == "not_performed"
        assert diagnostics(runtime, result)["authentication"] == "not_required"
        assert {p.name for p in runtime.folder.iterdir()} == {"edition.json", "launcher.lock"}
    finally:
        runtime.stop()


def test_editions_cannot_mix_or_adopt_unrelated_files(tmp_path):
    folder = tmp_path / "dedicated"
    prepare_profile(folder, "offline")
    with pytest.raises(SetupError, match="separate"):
        prepare_profile(folder, "synthetic")
    other = tmp_path / "other"
    other.mkdir()
    (other / "personal-notes.txt").write_text("preserve this")
    with pytest.raises(SetupError):
        prepare_profile(other, "synthetic")
    assert (other / "personal-notes.txt").read_text() == "preserve this"
    with pytest.raises(SetupError):
        prepare_profile(tmp_path / "live", "institutional")


def test_bundle_integrity_detects_missing_tampered_and_traversal_files(tmp_path):
    payload = b"fictional executable bytes"
    (tmp_path / "app.bin").write_bytes(payload)
    manifest = {
        "schema": "desktop-bundle-1",
        "files": {"app.bin": hashlib.sha256(payload).hexdigest()},
    }
    (tmp_path / "bundle-manifest.json").write_text(json.dumps(manifest))
    assert verify_bundle(tmp_path)["state"] == "integrity_verified"
    (tmp_path / "app.bin").write_bytes(b"tampered")
    with pytest.raises(SetupError):
        verify_bundle(tmp_path)
    manifest["files"] = {"../outside": "a" * 64}
    (tmp_path / "bundle-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SetupError):
        verify_bundle(tmp_path)


def test_converter_detection_is_not_activation_or_success(tmp_path, monkeypatch):
    assert converter_status([])["ready"] is False
    program = tmp_path / "program"
    program.mkdir()
    (program / "version.ini").write_text("[Version]\nProductVersion=99.1.0.2\n")
    monkeypatch.setattr(
        "canvas_bridge.onboarding.trust_configuration", lambda: {"supported_converter_versions": []}
    )
    assert converter_status([tmp_path])["state"] == "detected_not_verified"
    monkeypatch.setattr(
        "canvas_bridge.onboarding.trust_configuration",
        lambda: {"supported_converter_versions": ["99.1.0.2"]},
    )
    assert converter_status([tmp_path])["state"] == "compatible_detected_not_activated"
    assert not converter_status([tmp_path])["ready"]


def test_missing_expired_disabled_or_unsafe_institution_routes_do_not_enable_access(monkeypatch):
    now = datetime.now(UTC)
    base = {
        "name": "Fictional University",
        "enabled": True,
        "settings_url": "https://approved.invalid/settings",
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }
    monkeypatch.setattr(
        "canvas_bridge.onboarding.trust_configuration", lambda: {"institution_services": [base]}
    )
    assert authorized_services()[0]["authorization"] == "must_be_verified_by_host_at_sign_in"
    for changes in (
        {"enabled": False},
        {"expires_at": (now - timedelta(seconds=1)).isoformat()},
        {"settings_url": "http://unsafe.invalid/settings"},
        {"settings_url": "https://user:secret@example.invalid/settings"},
    ):
        monkeypatch.setattr(
            "canvas_bridge.onboarding.trust_configuration",
            lambda c=changes: {"institution_services": [base | c]},
        )
        assert not authorized_services()


@pytest.fixture
def release_fixture(tmp_path):
    private = (
        Ed25519PrivateKey.generate()
    )  # Ephemeral test identity, never shipped/trusted by product.
    thumbprint = "A" * 40
    trust = {
        "release_keys": {
            "fictional-test": base64.b64encode(private.public_key().public_bytes_raw()).decode()
        },
        "publisher_thumbprints": [thumbprint],
    }
    installer = b"fictional installer; never executable"
    now = datetime.now(UTC)
    release = {
        "schema_version": "desktop-release-1",
        "product": "canvas-bridge-local",
        "version": "0.3.0",
        "platform": "windows-x64",
        "editions": ["offline", "synthetic"],
        "key_id": "fictional-test",
        "issued_at": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "installer_sha256": hashlib.sha256(installer).hexdigest(),
        "installer_bytes": len(installer),
        "publisher_thumbprint": thumbprint,
        "compatible_database_revisions": ["fixture-schema"],
        "release_notes": "Fictional release notes; preserve preferences and access state.",
    }

    def package(name="release.cbu", changes=None, content=None, extra=None):
        data = release | (changes or {})
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("release.json", json.dumps(data))
            archive.writestr("release.sig", base64.b64encode(private.sign(canonical(data))))
            archive.writestr("installer.exe", installer if content is None else content)
            if extra:
                archive.writestr(extra, b"not permitted")
        return path

    return trust, release, private, package


def test_signed_update_checks_all_integrity_layers_and_never_launches(tmp_path, release_fixture):
    trust, _, _, package = release_fixture
    observed = []
    result = prepare_update(
        package(),
        tmp_path / "staged",
        edition="synthetic",
        database_revision="fixture-schema",
        trust=trust,
        signature_check=lambda p, t: observed.append((p, t)),
    )
    assert observed and result["preserves_data"]
    with pytest.raises(SetupError):
        launch_update(result)


@pytest.mark.parametrize(
    "case", ["tampered", "extra", "wrong_schema", "downgrade", "expired", "wrong_edition"]
)
def test_update_negative_cases_fail_before_publisher_execution(tmp_path, release_fixture, case):
    trust, _, _, package = release_fixture
    changes = {
        "downgrade": {"version": "0.1.0"},
        "expired": {"expires_at": "2000-01-01T00:00:00+00:00"},
        "wrong_edition": {"editions": ["offline"]},
    }.get(case)
    path = package(
        changes=changes,
        content=b"tampered" if case == "tampered" else None,
        extra="../escape.exe" if case == "extra" else None,
    )
    called = []
    with pytest.raises(SetupError):
        prepare_update(
            path,
            tmp_path / "staged",
            edition="synthetic",
            database_revision="unknown" if case == "wrong_schema" else "fixture-schema",
            trust=trust,
            signature_check=lambda *args: called.append(args),
        )
    assert not called


def test_signature_unknown_key_and_tampering_cannot_be_bypassed(release_fixture):
    trust, release, private, _ = release_fixture
    signed = base64.b64encode(private.sign(canonical(release)))
    with pytest.raises(SetupError):
        verify_release(json.dumps(release | {"release_notes": "tampered"}), signed, trust=trust)
    with pytest.raises(SetupError):
        verify_release(json.dumps(release), signed, trust={})


def test_compatible_binary_rollback_never_rolls_back_database(tmp_path, release_fixture):
    trust, _, _, package = release_fixture
    result = prepare_update(
        package(changes={"version": "0.2.0"}),
        tmp_path / "staged",
        edition="synthetic",
        database_revision="fixture-schema",
        rollback=True,
        current_version="0.3.0",
        trust=trust,
        signature_check=lambda *_: None,
    )
    assert result["rollback"] and result["preserves_data"]
    with pytest.raises(SetupError, match="predates"):
        prepare_update(
            package(changes={"version": "0.1.0"}),
            tmp_path / "legacy-staging",
            edition="offline",
            rollback=True,
            trust=trust,
            signature_check=lambda *args: None,
        )
    assert not (tmp_path / "bridge.db").exists()


def test_delete_is_explicit_and_preserves_unrecognized_files(tmp_path):
    folder = tmp_path / "owned"
    prepare_profile(folder, "offline")
    (folder / "preferences.json").write_text('{"week_start":"monday"}')
    with pytest.raises(SetupError):
        remove_profile(folder)
    (folder / "not-ours.txt").write_text("keep")
    with pytest.raises(SetupError):
        remove_profile(folder, confirmed=True)
    assert (folder / "preferences.json").exists()
    (folder / "not-ours.txt").unlink()
    assert remove_profile(folder, confirmed=True)["local_data"] == "removed"
    assert not folder.exists()


def test_restart_cannot_reenable_disabled_demo_and_diagnostics_do_not_leak(tmp_path):
    runtime = DemoRuntime(tmp_path / "demo", preferred_port=0)
    runtime.start()
    with runtime.app.state.bridge.store.transaction() as session:
        session.scalar(select(Connection)).state = "disabled"
    runtime.stop()
    runtime.start()
    try:
        with runtime.app.state.bridge.store.transaction() as session:
            rows = list(session.scalars(select(Connection)))
            assert len(rows) == 1 and rows[0].state == "disabled"
        with pytest.raises(SetupError, match="no active"):
            runtime.check()
        result = json.dumps(diagnostics(runtime))
        assert "access_token" not in result and "issuer-private" not in result
        assert "secret" not in friendly_error(ValueError("secret token=do-not-expose"))
    finally:
        runtime.stop()


def test_migration_preserves_preferences_disabled_state_and_original_on_failure(
    tmp_path, monkeypatch
):
    runtime = DemoRuntime(tmp_path / "demo", preferred_port=0)
    runtime.start()
    with runtime.app.state.bridge.store.transaction() as session:
        conn = session.scalar(select(Connection))
        owner, ref = conn.owner, conn.id
    runtime.app.state.bridge.store.save_local(
        owner, ref, "preferences", "default", {"timezone": "UTC"}, 0
    )
    with runtime.app.state.bridge.store.transaction() as session:
        session.scalar(select(Connection)).state = "disabled"
    runtime.stop()
    assert migrate_profile(runtime.settings, acknowledged=True)["preferences"] == "preserved"
    before = (runtime.folder / "bridge.db").read_bytes()

    def fail(*a, **kw):
        raise RuntimeError("fictional migration fault")

    monkeypatch.setattr("canvas_bridge.resources.migrate", fail)
    with pytest.raises(RuntimeError, match="fictional migration fault"):
        migrate_profile(runtime.settings, acknowledged=True)
    assert (runtime.folder / "bridge.db").read_bytes() == before
    with sqlite3.connect(runtime.folder / "bridge.db") as db:
        assert db.execute("SELECT state FROM connections").fetchone()[0] == "disabled"
        assert db.execute("SELECT count(*) FROM local_records").fetchone()[0] == 1


def test_intermediate_stages_never_imply_visual_delivery_or_analysis():
    result = stage_report(source_retrieved="verified", content_extracted="verified")
    assert (
        result["pixels_rendered"]
        == result["visual_content_delivered"]
        == result["analysis_completed"]
        == "not_requested"
    )


def test_custom_edition_folders_are_remembered_independently(tmp_path, monkeypatch):
    monkeypatch.setattr("canvas_bridge.desktop.default_data_directory", lambda: tmp_path / "demo")
    remember_directory(tmp_path / "my-offline", "offline")
    remember_directory(tmp_path / "my-demo", "synthetic")
    assert remembered_directory("offline") == tmp_path / "my-offline"
    assert remembered_directory() == tmp_path / "my-demo"


def test_deletion_removes_only_owned_cache_and_refuses_running_profile(tmp_path):
    runtime = OfflineRuntime(tmp_path / "offline")
    runtime.start()
    try:
        with pytest.raises(AlreadyRunning):
            remove_profile(runtime.folder, confirmed=True)
    finally:
        runtime.stop()
    cache = runtime.folder / "original-delivery/fictional"
    cache.mkdir(parents=True)
    (cache / "opaque.enc").write_bytes(b"fictional encrypted cache")
    remove_profile(runtime.folder, confirmed=True)
    assert not runtime.folder.exists()


def test_desktop_migration_upgrades_previous_schema_and_refuses_active_or_other_database(tmp_path):
    runtime = DemoRuntime(tmp_path / "demo", preferred_port=0)
    runtime.start()
    try:
        with pytest.raises(AlreadyRunning):
            migrate_profile(runtime.settings, acknowledged=True)
    finally:
        runtime.stop()
    with contextlib.closing(sqlite3.connect(runtime.folder / "bridge.db")) as db:
        # Construct the previous synthetic schema, never downgrade user data.
        db.execute("DROP TABLE independent_resources")
        db.execute("DROP TABLE deployment_state")
        db.execute("UPDATE alembic_version SET version_num='c7d9130b42ae'")
        db.commit()
    result = migrate_profile(runtime.settings, acknowledged=True)
    assert result["migration"] == "verified" and result["retained_backup"] is False
    from canvas_bridge.deployment import preflight

    assert preflight(runtime.settings)["service_health"] == "READY"
    other = runtime.settings.model_copy(update={"database_url": "sqlite:///different.db"})
    with pytest.raises(SetupError, match="belong"):
        migrate_profile(other, acknowledged=True)


def test_deleted_demo_connection_is_not_recreated_on_restart(tmp_path):
    runtime = DemoRuntime(tmp_path / "demo", preferred_port=0)
    runtime.start()
    with runtime.app.state.bridge.store.transaction() as session:
        session.delete(session.scalar(select(Connection)))
    runtime.stop()
    runtime.start()
    try:
        with runtime.app.state.bridge.store.transaction() as session:
            assert session.scalar(select(Connection)) is None
        with pytest.raises(SetupError):
            runtime.check()
    finally:
        runtime.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Authenticode is OS-specific")
def test_windows_publisher_verification_refuses_unsigned_file(tmp_path):
    from canvas_bridge.desktop_updates import authenticode

    path = tmp_path / "not-an-executable.exe"
    path.write_bytes(b"fictional unsigned fixture")
    with pytest.raises(SetupError, match="publisher"):
        authenticode(path, "A" * 40)


@pytest.mark.skipif(sys.platform != "win32", reason="Native wizard requires a Windows desktop")
def test_native_failed_recheck_clears_previous_success_and_recovers(tmp_path):
    import time
    import tkinter as tk

    from canvas_bridge.desktop_wizard import SetupWizard

    root = tk.Tk()
    wizard = SetupWizard(root, tmp_path / "offline", remember=False)

    def finish():
        deadline = time.monotonic() + 10
        while wizard.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert not wizard.busy

    try:
        wizard.setup()
        wizard.consent.set(True)
        wizard.start()
        finish()
        assert wizard.stage == "ready"
        good_check = wizard.runtime.check

        def fail():
            raise SetupError("FICTIONAL_CHECK_FAILURE", "Fixture check failed.")

        wizard.runtime.check = fail
        wizard.check()
        finish()
        assert wizard.result["check"] == {"state": "failed"}
        assert wizard.result["diagnostics"]["client"] == "not_verified"
        assert "attention" in wizard.title.cget("text")
        wizard.runtime.check = good_check
        wizard.check()
        finish()
        assert wizard.result["diagnostics"]["client"] == "local_engine_verified"
    finally:
        if wizard.runtime:
            wizard.runtime.stop()
        root.destroy()
