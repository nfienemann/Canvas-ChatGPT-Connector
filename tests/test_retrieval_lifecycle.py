import io
import zipfile
from datetime import timedelta

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.jobs import enqueue_refresh, work_once
from canvas_bridge.lifecycle import backup, read_journal, restore
from canvas_bridge.linking import disconnect
from canvas_bridge.retrieval import extract_synthetic, fetch_material, outline
from canvas_bridge.storage import Connection, Job, Store, Tombstone


def archive(name, data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "word/vbaProject.bin", "word/embeddings/object.bin"]
)
def test_T23_office_archives_reject_unsafe_members(name):
    with pytest.raises(ValueError, match="Unsafe"):
        extract_synthetic(archive(name, b"fixture"), "docx")


def test_T23_archive_expansion_bomb_rejected():
    with pytest.raises(ValueError, match="Unsafe"):
        extract_synthetic(archive("word/document.xml", b"0" * 1_000_000), "docx")


def test_T11_T25_docx_scientific_text_and_content_hash():
    first = archive(
        "word/document.xml", '<w:document xmlns:w="urn:w"><w:t>α β ATP ΔG</w:t></w:document>'
    )
    result = extract_synthetic(first, "docx")
    assert "α β ATP ΔG" in result.text
    assert "pagination unavailable" in result.locators[0]["locator"]
    second = archive(
        "word/document.xml", '<w:document xmlns:w="urn:w"><w:t>Changed</w:t></w:document>'
    )
    assert extract_synthetic(second, "docx").content_hash != result.content_hash


def test_T11_scan_never_claimed_fully_read():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    result = extract_synthetic(buf.getvalue(), "pdf")
    assert result.coverage == "partial"
    assert result.text == ""
    assert any("image-only" in warning for warning in result.warnings)


def test_T23_xml_entities_not_expanded():
    xml = '<!DOCTYPE d [<!ENTITY secret SYSTEM "file:///etc/passwd">]><d>&secret;</d>'
    from defusedxml.common import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        extract_synthetic(archive("word/document.xml", xml), "docx")


async def test_T25_material_continuation_requires_version(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    ref = result.data["materials"][0]["id"]
    first = await fetch_material(bridge, owner, seeded, ref, length=10)
    assert first.data["next_offset"] == 10
    with pytest.raises(DomainError):
        await fetch_material(bridge, owner, seeded, ref, offset=10)
    second = await fetch_material(
        bridge,
        owner,
        seeded,
        ref,
        offset=10,
        expected_hash=first.data["content_hash"],
    )
    assert first.data["text"] + second.data["text"]


async def test_T15_job_is_durable_and_deduplicated(bridge, owner, seeded):
    first = enqueue_refresh(bridge, owner, seeded)
    second = enqueue_refresh(bridge, owner, seeded)
    assert first == second
    assert await work_once(bridge)
    with bridge.store.transaction() as session:
        job = session.get(Job, first)
        assert job.state == "succeeded"
        assert job.attempts == 1
    assert not await work_once(bridge)


async def test_T34_encrypted_restore_applies_newer_deletion_fences(bridge, owner, seeded, tmp_path):
    await bridge.refresh(owner, seeded)
    destination = tmp_path / "fixture.backup"
    backup(bridge, destination)
    assert "Membrane" not in destination.read_text()
    await disconnect(bridge, owner, seeded)
    original = bridge.store
    target = Store("sqlite:///:memory:")
    target.create_fixture_schema()
    bridge.store = target
    try:
        result = restore(bridge, destination, bridge.settings.deletion_journal)
        assert result["deletion_fences_applied"] == 1
        with target.transaction() as session:
            assert not list(session.scalars(select(Connection)))
            assert session.get(Tombstone, seeded)
    finally:
        bridge.store = original
        target.close()


async def test_T34_missing_or_tampered_journal_prevents_restore(bridge, owner, seeded, tmp_path):
    await disconnect(bridge, owner, seeded)
    journal = bridge.settings.deletion_journal
    assert read_journal(journal, bridge.settings.vault_key_file.read_bytes())
    journal.write_text(journal.read_text().replace("connection-one", "connection-two"))
    with pytest.raises(ValueError):
        read_journal(journal, bridge.settings.vault_key_file.read_bytes())
    with pytest.raises(FileNotFoundError):
        read_journal(tmp_path / "missing", bridge.settings.vault_key_file.read_bytes())


async def test_T34_retention_removes_only_expired_snapshots(bridge, owner, seeded):
    old = await bridge.refresh(owner, seeded)
    latest = await bridge.refresh(owner, seeded)
    from canvas_bridge.storage import Snapshot

    with bridge.store.transaction() as session:
        session.get(Snapshot, old.id).created_at = utcnow() - timedelta(days=31)
    assert bridge.store.purge_history() == 1
    with bridge.store.transaction() as session:
        assert session.get(Snapshot, latest.id)
