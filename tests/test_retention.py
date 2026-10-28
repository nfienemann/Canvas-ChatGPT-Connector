"""Synthetic, deterministic storage lifecycle and deletion acceptance."""

import asyncio
import io
import os
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from cryptography.exceptions import InvalidTag
from sqlalchemy import MetaData, Table, create_engine, func, select
from sqlalchemy.exc import StatementError

from canvas_bridge.app import create_app
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.ephemeral_blob import Writer, chunks, storage_size
from canvas_bridge.lifecycle import backup, journal_delete, prune_journal, read_journal, restore
from canvas_bridge.retention import RULES
from canvas_bridge.retention_policy import BACKUP_LIFETIME, CONNECTION_LIFETIME, FENCE_LIFETIME
from canvas_bridge.storage import Connection, Course, LocalRecord, Material, Snapshot, Store, Work
from canvas_bridge.vault import DPAPI_PREFIX, Vault
from canvas_bridge.worker_storage import (
    invalidate,
    job_directory,
    pending,
    processing,
    require_running,
    sweep_orphans,
)
from tests.conftest import seed
from tests.test_file_delivery import original as original
from tests.test_settings_oauth import identity_exchange as identity_exchange
from tests.test_settings_oauth import start


def freeze(bridge, at=None):
    current = [at or utcnow()]
    bridge.retention.clock = lambda: current[0]
    return current


async def page(bridge, owner, seeded):
    from canvas_bridge.retrieval import fetch_material, outline

    course = bridge.selected(owner, seeded)[1][0]
    inventory = await outline(bridge, owner, seeded, course.id)
    ref = next(m["id"] for m in inventory.data["materials"] if m["kind"] == "page")
    await fetch_material(bridge, owner, seeded, ref)
    return ref


async def test_encrypted_database_roundtrip_and_engine_key_isolation(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    material = await page(bridge, owner, seeded)
    with bridge.store.engine.connect() as sql:
        values = sql.exec_driver_sql("SELECT text, title, url, locators FROM materials").first()
        assert all(v.startswith("bridge-sealed-v1:") for v in values)
        assert "Membrane" not in " ".join(values)
        assert (
            sql.exec_driver_sql("SELECT items FROM snapshots")
            .scalar()
            .startswith("bridge-sealed-v1:")
        )
    with bridge.store.transaction() as session:
        assert session.get(Snapshot, snapshot.id).items == snapshot.items
        assert session.get(Material, material).text
    other_key = bridge.settings.vault_key_file.parent / "wrong-key"
    other_key.write_bytes(os.urandom(32))
    bridge.store.protect(Vault(other_key))
    with pytest.raises(InvalidTag), bridge.store.transaction() as session:
        session.get(Material, material)
    bridge.store.protect(bridge.vault)


async def test_auth_secrets_cannot_enter_academic_cache(bridge, owner, seeded):
    payload = {"nested": [{"refresh_token": "synthetic-secret"}]}
    with pytest.raises(DomainError) as rejected:
        bridge.store.save_local(
            owner,
            seeded,
            "preferences",
            "default",
            payload,
            0,
        )
    assert rejected.value.status == "needs_input"
    assert "synthetic-secret" not in str(rejected.value)
    # The schema rejects this earlier, but the database guard must also remain
    # effective for other writers that do not pass through preference validation.
    with pytest.raises(StatementError, match="Authentication secrets"):
        with bridge.store.transaction() as session:
            session.add(
                LocalRecord(
                    owner=owner,
                    connection_id=seeded,
                    kind="preferences",
                    key="default",
                    payload=payload,
                )
            )
    assert bridge.retention.inventory(owner)["stored_categories"]["local_records"] == 0


async def test_expired_analysis_is_unreadable_before_sweep_then_physically_removed(
    bridge, owner, seeded
):
    snapshot = await bridge.refresh(owner, seeded)
    bridge.store.save_local(owner, seeded, "preferences", "default", {"timezone": "UTC"}, 0)
    clock = freeze(bridge)
    clock[0] += timedelta(days=31)
    with pytest.raises(DomainError):
        bridge.snapshot(owner, seeded, snapshot.id)
    with bridge.store.transaction() as session:
        assert not session.scalars(select(Work)).all()
        assert not session.scalars(select(LocalRecord)).all()
    assert bridge.retention.inventory(owner)["stored_categories"]["snapshots"] == 1
    await bridge.retention.sweep()
    with bridge.store.engine.connect() as sql:
        assert sql.exec_driver_sql("SELECT count(*) FROM snapshots").scalar() == 0
        assert sql.exec_driver_sql("SELECT count(*) FROM work_items").scalar() == 0
        assert sql.exec_driver_sql("SELECT count(*) FROM local_records").scalar() == 0


async def test_page_raw_expiry_and_export_never_extend_retention(bridge, owner, seeded):
    ref = await page(bridge, owner, seeded)
    clock = freeze(bridge)
    clock[0] += timedelta(hours=2)
    exported = bridge.store.export_connection(owner, seeded)
    assert exported["records"]["materials"][0]["text"] == ""
    await bridge.retention.sweep()
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        assert row.text == "" and row.locators == [] and row.file_state == {"stage": "available"}


async def test_connection_lifetime_fails_closed_then_purges_secret_and_fences(
    bridge, owner, seeded
):
    await bridge.refresh(owner, seeded)
    clock = freeze(bridge)
    clock[0] += CONNECTION_LIFETIME + timedelta(seconds=1)
    with pytest.raises(DomainError), bridge.store.transaction() as session:
        bridge.store.connection(session, owner, seeded)
    await bridge.retention.sweep()
    with bridge.store.transaction() as session:
        row = session.get(Connection, seeded)
        assert row.credential is None and row.state == "disconnected"
        assert session.scalar(select(func.count()).select_from(Course)) == 0
    clock[0] += FENCE_LIFETIME + timedelta(seconds=1)
    await bridge.retention.sweep()
    assert not bridge.retention.inventory(owner)["sources"]
    assert read_journal(bridge.settings.deletion_journal, bridge.vault.key) == {}


async def test_delete_caches_and_records_are_owned_confirmed_and_fenced(bridge, owner, seeded):
    foreign = await seed(bridge, "other-owner", "other-connection")
    for principal, ref in ((owner, seeded), ("other-owner", foreign)):
        await bridge.refresh(principal, ref)
        bridge.store.save_local(principal, ref, "preferences", "default", {"timezone": "UTC"}, 0)
    with pytest.raises(DomainError):
        bridge.retention.delete_local(owner, seeded)
    with pytest.raises(DomainError):
        bridge.retention.delete_local(owner, foreign, confirmed=True)
    with pytest.raises(DomainError):
        bridge.retention.delete_local(owner, seeded, confirmed=True, generation=77)
    receipt = bridge.retention.delete_local(owner, seeded, confirmed=True, generation=0)
    assert receipt["deleted_rows"]["snapshots"] == 1
    assert receipt["local_deletion"] == "completed"
    assert receipt["physical_erasure"] == "not_guaranteed"
    counts = bridge.retention.inventory(owner)["stored_categories"]
    assert counts["local_records"] == 1 and counts["courses"] > 0 and counts["work_items"] == 0
    receipt = bridge.retention.delete_local(owner, seeded, academic=True, confirmed=True)
    assert receipt["deleted_rows"]["local_records"] == 1
    assert all(c == 0 for c in bridge.retention.inventory(owner)["stored_categories"].values())
    assert bridge.retention.inventory("other-owner")["stored_categories"]["snapshots"] == 1
    with bridge.store.transaction() as session:
        assert bridge.store.connection(session, owner, seeded).epoch >= 2


async def test_receipts_expire_without_erasure_claims(bridge, owner):
    clock = freeze(bridge)
    receipt = bridge.retention.receipt(owner, "delete_caches", {}, 1)
    assert receipt["local_deletion"] == "access_blocked_cleanup_pending"
    clock[0] += timedelta(days=7)
    bridge.retention.expire_receipts()
    assert not bridge.retention.receipts
    assert len(RULES) == 7 and all(r.purpose and r.expiry and r.deletion for r in RULES.values())


async def test_backup_excludes_credentials_raw_documents_and_jobs_and_restores_inactive(
    bridge, owner, seeded, tmp_path
):
    await bridge.refresh(owner, seeded)
    await page(bridge, owner, seeded)
    source = tmp_path / "synthetic.backup"
    result = backup(bridge, source)
    assert result["encrypted"] and not result["credentials_included"]
    payload = bridge.vault.open(source.read_text(), "operator", "backup")
    assert not payload["tables"]["connections"][0]["credential"]
    assert not payload["tables"]["materials"][0]["text"]
    assert "jobs" not in payload["tables"] and "browser_sessions" not in payload["tables"]
    original_store = bridge.store
    target = Store("sqlite:///:memory:")
    target.create_fixture_schema()
    bridge.store = target
    try:
        restore(bridge, source, bridge.settings.deletion_journal)
        with target.transaction() as session:
            row = session.get(Connection, seeded)
            assert row.credential is None and row.authentication_state == "unverified"
            with pytest.raises(DomainError):
                target.connection(session, owner, seeded)
    finally:
        bridge.store = original_store
        target.close()


@pytest.mark.parametrize("invalid", ["expired", "future", "legacy"])
async def test_backup_restore_rejects_unbounded_or_invalid_lifetimes(
    bridge, owner, seeded, tmp_path, invalid
):
    clock = freeze(bridge)
    source = tmp_path / "synthetic.backup"
    backup(bridge, source)
    if invalid == "expired":
        clock[0] += BACKUP_LIFETIME
    elif invalid == "future":
        clock[0] -= timedelta(minutes=1)
    else:
        payload = bridge.vault.open(source.read_text(), "operator", "backup")
        payload["format"] = "bridge-backup-1"
        source.write_text(bridge.vault.seal(payload, "operator", "backup"))
    with pytest.raises(ValueError, match="expired|invalid|Unsupported"):
        restore(bridge, source, bridge.settings.deletion_journal)


async def test_cache_deletion_fences_prior_backup(bridge, owner, seeded, tmp_path):
    await bridge.refresh(owner, seeded)
    source = tmp_path / "synthetic.backup"
    backup(bridge, source)
    bridge.retention.delete_local(owner, seeded, confirmed=True)
    original_store = bridge.store
    bridge.store = Store("sqlite:///:memory:")
    bridge.store.create_fixture_schema()
    try:
        restore(bridge, source, bridge.settings.deletion_journal)
        with bridge.store.transaction() as session:
            assert not session.scalars(select(Connection)).all()
            assert not session.scalars(select(Snapshot)).all()
    finally:
        bridge.store.close()
        bridge.store = original_store


def test_journal_pruning_keeps_recent_fences_and_verifies_old_entries(bridge):
    now = utcnow()
    path = bridge.settings.deletion_journal
    journal_delete(path, bridge.vault.key, "old-fixture", 1, now=now - FENCE_LIFETIME)
    journal_delete(path, bridge.vault.key, "new-fixture", 2, now=now)
    prune_journal(path, bridge.vault.key, now)
    assert set(read_journal(path, bridge.vault.key)) == {"new-fixture"}
    path.write_text(path.read_text().replace("new-fixture", "tampered"))
    with pytest.raises(ValueError, match="integrity"):
        prune_journal(path, bridge.vault.key, now + FENCE_LIFETIME)


@pytest.mark.parametrize("size", [0, 1, 65536, 131075])
def test_staged_blobs_are_encrypted_authenticated_and_byte_exact(tmp_path, size):
    value, key, binding = b"x" * size, os.urandom(32), b"owner:connection:file:epoch"
    sink = io.BytesIO()
    writer = Writer(sink, key, binding)
    for i in range(0, size, 1151):
        writer.write(value[i : i + 1151])
    writer.finish()
    path = tmp_path / "encrypted.blob"
    path.write_bytes(sink.getvalue())
    assert len(sink.getvalue()) == storage_size(size)
    assert b"".join(chunks(path, key, binding)) == value
    with pytest.raises(OSError):
        list(chunks(path, key, b"other-owner"))
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(OSError):
        list(chunks(path, key, binding))


async def test_active_download_deletion_destroys_key_and_blocks_stale_link(
    bridge, owner, seeded, original
):
    _, file, original_bytes = original
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    item = bridge.original_files.records[prepared.data["delivery_id"]]
    assert item.path.read_bytes() != original_bytes
    item.active += 1
    receipt = bridge.retention.delete_local(owner, seeded, confirmed=True)
    assert receipt["pending_temporary_cleanup"] == 1 and item.key is None
    with pytest.raises(DomainError):
        bridge.original_files.lookup(item.id)
    item.active -= 1
    bridge.original_files.cleanup()
    assert not item.path.exists()


async def test_deletion_cancels_inflight_download_and_reports_pending_cleanup(
    bridge, owner, seeded, original, monkeypatch
):
    _, file, _ = original
    started = asyncio.Event()

    async def stalled(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("canvas_bridge.file_delivery.stream_original", stalled)
    task = asyncio.create_task(bridge.original_files.prepare(owner, seeded, file))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert len(bridge.original_files.preparing) == 1
        receipt = bridge.retention.delete_local(owner, seeded, confirmed=True)
        assert receipt["pending_temporary_cleanup"] == 1
        with pytest.raises(asyncio.CancelledError):
            await task
        assert bridge.original_files.pending_cleanup(owner, seeded) == 0
        assert not list(bridge.original_files.root.glob("obj_*"))
    finally:
        task.cancel()


def test_worker_error_cancellation_and_orphan_recovery(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    with pytest.raises(DomainError), processing("fixture-owner", "fixture-connection"):
        with job_directory(jobs) as name:
            work = Path(name)
            (work / "input.bin").write_bytes(b"synthetic course data")
            assert sweep_orphans(tmp_path, now=utcnow().timestamp() + 700)["removed"] == 0
            invalidate("fixture-owner", "fixture-connection")
            assert pending("fixture-owner", "fixture-connection") == 1
            require_running()
    assert not work.exists() and pending("fixture-owner", "fixture-connection") == 0
    with pytest.raises(RuntimeError), job_directory(jobs) as name:
        error_path = Path(name)
        (error_path / "result.json").write_text("synthetic")
        raise RuntimeError("Synthetic interrupted processing")
    assert not error_path.exists()
    orphan = jobs / "document-crashed"
    orphan.mkdir()
    (orphan / "input.bin").write_bytes(b"synthetic")
    created = orphan.stat().st_mtime
    assert sweep_orphans(tmp_path, now=created + 599)["removed"] == 0
    assert sweep_orphans(tmp_path, now=created + 600)["removed"] == 1


def test_failed_worker_cleanup_is_reported_and_retried(tmp_path, monkeypatch):
    import canvas_bridge.worker_storage as workers

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    remove = workers.remove_workspace
    monkeypatch.setattr(workers, "remove_workspace", lambda *args: False)
    with processing("fixture-cleanup", "connection"), job_directory(jobs) as name:
        path = Path(name)
    assert pending("fixture-cleanup", "connection") == 1
    monkeypatch.setattr(workers, "remove_workspace", remove)
    assert sweep_orphans(tmp_path, now=utcnow().timestamp() + 601)["removed"] == 1
    assert not path.exists() and pending("fixture-cleanup", "connection") == 0


def test_worker_cancellation_and_pending_receipts_isolate_service_instances(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    first, second = object(), object()
    with pytest.raises(DomainError), processing("same-owner", "same-ref", namespace=first):
        with job_directory(jobs):
            with processing("same-owner", "same-ref", namespace=second), job_directory(jobs):
                invalidate("same-owner", "same-ref", namespace=first)
                require_running()  # The second service's worker remains authorized.
                assert pending("same-owner", "same-ref", namespace=first) == 1
                assert pending("same-owner", "same-ref", namespace=second) == 1
                assert pending("same-owner", "same-ref") == 0
            require_running()
    assert not list(jobs.iterdir())


def test_new_vault_uses_windows_secret_protection_and_preserves_legacy_support(tmp_path):
    path = tmp_path / "new.key"
    Vault.create(path)
    vault = Vault(path)
    assert vault.open(vault.seal({"synthetic": True}, "owner", "ref"), "owner", "ref") == {
        "synthetic": True
    }
    if os.name == "nt":
        assert path.read_bytes().startswith(DPAPI_PREFIX)
    with pytest.raises(FileExistsError):
        Vault.create(path)


def test_existing_plaintext_migration_encrypts_in_place(bridge, tmp_path):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    config = Config("alembic.ini")
    config.attributes.update(database_url=url, vault_key_file=bridge.settings.vault_key_file)
    command.upgrade(config, "8d21f4c932ab")
    engine = create_engine(url)
    metadata = MetaData()
    connection_table = Table("connections", metadata, autoload_with=engine)
    course_table = Table("courses", metadata, autoload_with=engine)
    snapshot_table = Table("snapshots", metadata, autoload_with=engine)
    with engine.begin() as sql:
        sql.execute(
            connection_table.insert().values(
                id="fixture",
                owner="owner",
                institution="synthetic",
                canvas_user="101",
                state="active",
                epoch=0,
                timezone="UTC",
                created_at=utcnow(),
            )
        )
        sql.execute(
            course_table.insert().values(
                id="course",
                owner="owner",
                connection_id="fixture",
                source_id="11",
                name="Synthetic Sensitive Course",
                selected=True,
                accessible=True,
                enrollment_state="active",
                version=1,
            )
        )
        sql.execute(
            snapshot_table.insert().values(
                id="snapshot",
                owner="owner",
                connection_id="fixture",
                complete=True,
                course_ids=["course"],
                items=[{"synthetic": "Retained private fixture"}],
                coverage=[],
                workload_scope={"fixture": True},
                created_at=utcnow(),
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as sql:
        assert (
            sql.exec_driver_sql("SELECT name FROM courses").scalar().startswith("bridge-sealed-v1:")
        )
    store = Store(url)
    store.protect(bridge.vault)
    try:
        with store.transaction() as session:
            assert session.get(Course, "course").name == "Synthetic Sensitive Course"
            assert session.get(Snapshot, "snapshot").items == [
                {"synthetic": "Retained private fixture"}
            ]
        with pytest.raises(RuntimeError, match="plaintext"):
            command.downgrade(config, "8d21f4c932ab")
    finally:
        store.close()
        engine.dispose()


async def test_shortened_file_retention_applies_before_export_and_to_sweep(bridge, owner, seeded):
    bridge.settings.file_cache_hours = 1
    course = bridge.selected(owner, seeded)[1][0]
    clock = freeze(bridge)
    with bridge.store.transaction() as session:
        session.add(
            Material(
                id="old-file",
                owner=owner,
                connection_id=seeded,
                course_id=course.id,
                source_id="51",
                kind="file",
                title="Synthetic file",
                url="https://canvas.synthetic.invalid/file",
                version_hash="hash",
                text="Synthetic retained text",
                locators=[{"text": "Synthetic retained text"}],
                limitations=[],
                file_state={"stage": "parsed"},
                retrieved_at=clock[0] - timedelta(hours=2),
            )
        )
    assert bridge.store.export_connection(owner, seeded)["records"]["materials"][0]["text"] == ""
    await bridge.retention.sweep()
    with bridge.store.transaction() as session:
        row = session.get(Material, "old-file")
        assert not row.text and not row.locators and not row.version_hash


async def test_restore_preserves_original_record_expiry(bridge, owner, seeded, tmp_path):
    snapshot = await bridge.refresh(owner, seeded)
    clock = freeze(bridge)
    with bridge.store.transaction() as session:
        session.get(Snapshot, snapshot.id).created_at = clock[0] - timedelta(days=29)
    source = tmp_path / "synthetic.backup"
    backup(bridge, source)
    clock[0] += timedelta(days=2)
    original_store = bridge.store
    bridge.store = Store("sqlite:///:memory:")
    bridge.store.create_fixture_schema()
    try:
        restore(bridge, source, bridge.settings.deletion_journal)
        with bridge.store.engine.connect() as sql:
            assert sql.exec_driver_sql("SELECT count(*) FROM snapshots").scalar() == 0
    finally:
        bridge.store.close()
        bridge.store = original_store


async def test_settings_deletion_requires_session_csrf_confirmation_and_owner(
    bridge, owner, seeded, settings, identity_exchange
):
    foreign = await seed(bridge, "other-owner", "foreign")
    await bridge.refresh(owner, seeded)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
        headers={"Origin": settings.resource_url},
    ) as client:
        assert (
            await client.post(
                "/settings/delete-records", data={"connection": seeded, "confirm": "delete-records"}
            )
        ).status_code >= 400
        state, callback = await start(client)
        assert (
            await client.get(
                callback,
                params={"state": state["state"][0], "code": "fixture", "iss": settings.issuer_url},
            )
        ).status_code == 303
        inventory = await client.get("/settings/storage")
        assert (
            inventory.status_code == 200
            and "temporary_processing_artifacts".replace("_", " ") in inventory.text
        )
        csrf = re.search(r'name="csrf" value="([^"]+)"', inventory.text).group(1)
        for form in (
            {"connection": seeded, "confirm": "delete-records"},
            {"connection": seeded, "csrf": csrf},
            {"connection": foreign, "csrf": csrf, "confirm": "delete-records"},
        ):
            assert (await client.post("/settings/delete-records", data=form)).status_code >= 400
        response = await client.post(
            "/settings/delete-records",
            data={"connection": seeded, "csrf": csrf, "confirm": "delete-records"},
        )
        assert response.status_code == 200 and "Local deletion receipt" in response.text
        assert all(c == 0 for c in bridge.retention.inventory(owner)["stored_categories"].values())
        assert bridge.retention.inventory("other-owner")["stored_categories"]["courses"] > 0
