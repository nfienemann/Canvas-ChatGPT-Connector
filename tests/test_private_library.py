"""Fictional library acceptance. Mocked processing is distinct from OS/host acceptance."""

import hashlib
import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.app import create_app
from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.domain import DomainError, opaque_id, utcnow
from canvas_bridge.egress_models import RecipientIdentity
from canvas_bridge.library.contracts import (
    CHUNK,
    ExportRequest,
    IntakeRequest,
    PermissionChange,
    VersionExpectation,
)
from canvas_bridge.library.models import Account, Representation, Version
from canvas_bridge.library_safety_worker import inspect
from canvas_bridge.linking import delete_account, digest, disconnect
from canvas_bridge.parser_worker import extract
from canvas_bridge.storage import BrowserSession
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


@pytest.fixture
def library(bridge, settings, tmp_path, monkeypatch):
    settings.library_enabled = True
    settings.library_root = tmp_path / "private-objects"
    settings.file_reading_enabled = True

    async def scanner(data, kind, settings, preview=False):
        try:
            return inspect(data, kind, preview)
        except ValueError as exc:
            from canvas_bridge.library.contracts import fail

            fail(str(exc), "unsupported_feature")

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.library.safety.scan", scanner)
    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_document", parser)
    return bridge.library


@pytest.fixture
def browser(bridge, owner, token_factory):
    row = BrowserSession(
        digest=digest("library-browser"),
        owner=owner,
        credential=bridge.vault.seal({"token": token_factory()}, owner, "browser-session"),
        csrf="fictional-library-csrf",
        expires_at=utcnow() + timedelta(hours=1),
        generation=0,
    )
    with bridge.store.transaction() as session:
        bridge.store.principal(session, owner)
        session.add(row)
    return row


@pytest.fixture
def recipient():
    token = request_authorization.set(
        RequestAuthorization(
            "library-test", recipient="chatgpt", egress_identity=RecipientIdentity("chatgpt")
        )
    )
    try:
        yield
    finally:
        request_authorization.reset(token)


def selection(
    browser,
    data=b"Fictional cells use ATP.\n",
    *,
    name="fictional.txt",
    processing=True,
    channels=("metadata", "text", "visual"),
    key=None,
):
    return IntakeRequest.model_validate(
        {
            "authorization_action_id": hashlib.sha256(browser.csrf.encode()).hexdigest(),
            "idempotency_key": key or opaque_id(),
            "files": [
                {
                    "selection_id": "0",
                    "file_name": name,
                    "declared_bytes": len(data),
                    "maximum_bytes": len(data),
                }
            ],
            "allow_processing": processing,
            "purpose": "study",
            "recipient_grants": [
                {"recipient_profile_id": "fictional-independent", "channels": list(channels)}
            ]
            if channels
            else [],
        }
    )


async def upload(library, browser, data=b"Fictional cells use ATP.\n", **kwargs):
    value = selection(browser, data, **kwargs)
    receipt = library.create_intake(browser, value)
    ident, file = receipt["intake_id"], receipt["files"][0]["selection_id"]
    for offset in range(0, len(data), CHUNK):
        chunk = data[offset : offset + CHUNK]
        library.put_chunk(browser, ident, file, offset, hashlib.sha256(chunk).hexdigest(), chunk)
    receipt = await library.complete(browser, ident, {file: hashlib.sha256(data).hexdigest()})
    assert receipt["status"] == "complete", receipt
    return receipt["files"][0]["items"][0], receipt


async def test_zero_lms_storage_restart_channels_processing(
    library, browser, owner, bridge, recipient
):
    assert library.status(owner).data["state"] == "not_provisioned"
    with bridge.store.transaction() as session:
        assert session.get(Account, owner) is None
    raw = b"Fictional ATP synthesis.\n"
    item, receipt = await upload(library, browser, raw, processing=False, channels=())
    assert library.list(owner).data["items"] == []
    assert (
        library.get(owner, item["item_id"], browser=True).data["processing_state"]
        == "not_requested"
    )
    assert not await library.process_once(owner)
    from canvas_bridge.library.service import Library

    restarted = Library(bridge)
    _, stream = restarted.original(owner, item["item_id"], item["version_id"])
    assert b"".join(stream) == raw
    assert all(
        raw not in path.read_bytes()
        for path in bridge.settings.library_root.rglob("*")
        if path.is_file()
    )
    library.update_grants(
        browser,
        item["item_id"],
        PermissionChange(
            expected_version_id=item["version_id"],
            expected_permission_revision=1,
            allow_processing=True,
            purpose="study",
            recipient_grants=[
                {"recipient_profile_id": "fictional-independent", "channels": ["metadata", "text"]}
            ],
        ),
    )
    assert await library.process_once(owner)
    read = library.read(owner, item["item_id"], item["version_id"])
    assert read.data["parts"][0]["text"] == raw.decode()
    assert read.data["original_sha256"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(DomainError):
        await library.render(owner, item["item_id"], item["version_id"])


async def test_owner_isolation_and_quota_replay(library, browser, owner, bridge, recipient):
    request = selection(browser)
    first = library.create_intake(browser, request)
    assert library.create_intake(browser, request) == first
    altered = request.model_copy(update={"allow_processing": False})
    with pytest.raises(DomainError, match="current version"):
        library.create_intake(browser, altered)
    bridge.settings.library_quota_bytes = 1
    rejected = library.create_intake(browser, selection(browser))
    assert rejected["files"][0]["reason_code"] == "QUOTA_EXCEEDED"
    assert library.status(owner).data["quota"]["reserved_bytes"] == request.files[0].declared_bytes
    with pytest.raises(DomainError):
        library.receipt("other-owner", first["intake_id"])
    library.cancel(browser, first["intake_id"], first["revision"])
    assert library.status(owner).data["quota"]["reserved_bytes"] == 0


async def test_chunks_idempotency_partial_batch_and_mismatch(library, browser, owner):
    data = b"synthetic content"
    request = selection(browser, data)
    request.files.append(request.files[0].model_copy(update={"selection_id": "1"}))
    receipt = library.create_intake(browser, request)
    ident, selected = receipt["intake_id"], receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(data).hexdigest()
    assert library.put_chunk(browser, ident, selected, 0, checksum, data)["offset"] == len(data)
    assert library.put_chunk(browser, ident, selected, 0, checksum, data)["replayed"]
    with pytest.raises(DomainError):
        library.put_chunk(
            browser, ident, selected, 0, hashlib.sha256(b"different").hexdigest(), b"different"
        )
    complete = await library.complete(browser, ident, {selected: checksum})
    assert complete["status"] == "partial"
    assert {f["state"] for f in complete["files"]} == {"published", "created"}
    complete = library.cancel(browser, ident, complete["revision"])
    assert {f["state"] for f in complete["files"]} == {"published", "cancelled"}
    assert library.status(owner).data["quota"]["committed_bytes"] == len(data)
    assert library.status(owner).data["quota"]["reserved_bytes"] == 0


async def test_revocation_output_and_delete_stream_fences(
    library, browser, owner, bridge, recipient
):
    raw = b"fictional-" * 10000
    item, _ = await upload(library, browser, raw)
    await library.process_once(owner)
    read = library.read(owner, item["item_id"], item["version_id"])
    _, stream = library.original(owner, item["item_id"], item["version_id"])
    assert next(stream)
    result = library.delete_item(
        browser,
        item["item_id"],
        VersionExpectation(
            expected_version_id=item["version_id"],
            expected_revision=1,
            expected_permission_revision=1,
        ),
    )
    assert result["access"] == "disabled" and result["active_store"] == "purged"
    with pytest.raises(DomainError):
        next(stream)
    with pytest.raises(DomainError):
        library.sources(owner, read)
    with pytest.raises(DomainError):
        bridge.independent.require(owner, item["document_id"])
    assert library.status(owner).data["quota"]["committed_bytes"] == 0


async def test_account_delete_and_disconnect_independence(library, browser, owner, bridge, seeded):
    item, _ = await upload(library, browser)
    await disconnect(bridge, owner, seeded)
    assert library.bytes(owner, item["version_id"])
    await delete_account(bridge, owner, 0)
    with pytest.raises(DomainError):
        library.bytes(owner, item["version_id"])
    library.sweep()
    assert library.status(owner).data["quota"]["committed_bytes"] == 0


async def test_version_citations_replacement_race_and_history(library, browser, owner, recipient):
    item, _ = await upload(library, browser, b"old fictional evidence")
    await library.process_once(owner)
    replacement = {
        "item_id": item["item_id"],
        "expected_version_id": item["version_id"],
        "expected_revision": 1,
        "expected_permission_revision": 1,
    }
    newer = b"new fictional evidence"
    request = selection(browser, newer)
    receipt = library.create_intake(browser, request, replacement=replacement)
    sel = receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(newer).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, checksum, newer)
    final = await library.complete(browser, receipt["intake_id"], {sel: checksum})
    assert final["status"] == "complete"
    current = final["files"][0]["items"][0]
    assert current["item_id"] == item["item_id"] and current["version_id"] != item["version_id"]
    assert library.bytes(owner, item["version_id"]) == b"old fictional evidence"
    assert (
        library.read(owner, item["item_id"], item["version_id"]).data["parts"][0]["text"]
        == "old fictional evidence"
    )
    with pytest.raises(DomainError):
        library.create_intake(browser, selection(browser, newer), replacement=replacement)


async def test_export_revocation_and_owner_range(library, browser, owner):
    item, _ = await upload(library, browser, processing=False, channels=())
    _, stream = library.original(owner, item["item_id"], item["version_id"], start=2, end=8)
    assert b"".join(stream) == b"ctional"
    receipt = library.create_export(
        browser, ExportRequest(idempotency_key=opaque_id(), versions=[item["version_id"]])
    )
    exported = b"".join(library.export_stream(owner, receipt["export_id"]))
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert (
            hashlib.sha256(archive.read(manifest["items"][0]["filename"])).hexdigest()
            == item["original_sha256"]
        )
    stream = library.export_stream(owner, receipt["export_id"])
    library.update_grants(
        browser,
        item["item_id"],
        PermissionChange(
            expected_version_id=item["version_id"],
            expected_permission_revision=1,
            allow_processing=False,
            purpose="document_reading",
            recipient_grants=[],
        ),
    )
    with pytest.raises(DomainError):
        next(stream)


@pytest.mark.parametrize(
    "name,raw",
    [
        ("fake.pdf", b"not pdf"),
        ("x.txt", b"<html><script>bad</script>"),
        ("x.txt", b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"),
        ("x.txt", b"PKfake"),
    ],
)
async def test_unsafe_bytes_never_publish(library, browser, owner, name, raw):
    request = selection(browser, raw, name=name)
    receipt = library.create_intake(browser, request)
    sel = receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(raw).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, checksum, raw)
    final = await library.complete(browser, receipt["intake_id"], {sel: checksum})
    assert final["files"][0]["state"] == "rejected"
    assert library.list(owner, browser=True).data["items"] == []
    assert library.status(owner).data["quota"]["reserved_bytes"] == 0


async def test_zip_preflight_and_per_member_receipts(library, browser, owner):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("first.txt", b"fictional one")
        z.writestr("sub/second.md", b"fictional two")
        z.writestr("unsupported.csv", b"a,b")
    request = selection(browser, out.getvalue(), name="bundle.zip")
    receipt = library.create_intake(browser, request)
    sel = receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(out.getvalue()).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, checksum, out.getvalue())
    final = await library.complete(browser, receipt["intake_id"], {sel: checksum})
    assert len(final["files"][0]["items"]) == 2
    assert library.status(owner).data["quota"]["committed_bytes"] == len(
        b"fictional onefictional two"
    )
    for member in ("../escape.txt", "name:ads.txt", "sub/./name.txt"):
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr(member, b"bad")
        with pytest.raises(ValueError):
            inspect(bad.getvalue(), "zip")


@pytest.mark.parametrize(
    "filename",
    [
        "fictional.txt",
        "scientific_figure.pdf",
        "requirements_conflict.docx",
        "lecture_continuation.pptx",
        "gradebook_fixture.xlsx",
        "fictional.png",
        "fictional.jpg",
    ],
)
async def test_http_browser_upload_csrf_and_original(
    library, browser, owner, bridge, settings, filename
):
    if filename.endswith((".png", ".jpg")):
        from PIL import Image

        output = io.BytesIO()
        Image.new("RGB", (12, 8), "navy").save(
            output, "PNG" if filename.endswith(".png") else "JPEG"
        )
        raw = output.getvalue()
    elif filename == "fictional.txt":
        raw = b"Fictional cells use ATP.\n"
    else:
        raw = (
            Path(__file__).parent / "fixtures/stress-repair/sources/formats" / filename
        ).read_bytes()
    app = create_app(settings, bridge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=settings.resource_url,
        cookies={"bridge_session": "library-browser"},
    ) as client:
        page = await client.get("/settings/library")
        assert page.status_code == 200 and "Save to private library" in page.text
        request = selection(browser, raw, name=filename)
        denied = await client.post("/api/library/intakes", json=request.model_dump(mode="json"))
        assert denied.status_code == 403
        headers = {"Origin": settings.resource_url, "X-Bridge-CSRF": browser.csrf}
        receipt = (
            await client.post(
                "/api/library/intakes", json=request.model_dump(mode="json"), headers=headers
            )
        ).json()
        ident, sel = receipt["intake_id"], receipt["files"][0]["selection_id"]
        checksum = hashlib.sha256(raw).hexdigest()
        response = await client.put(
            f"/api/library/intakes/{ident}/files/{sel}/chunks",
            content=raw,
            headers={**headers, "Upload-Offset": "0", "X-Chunk-SHA256": checksum},
        )
        assert response.status_code == 200, response.text
        completed = await client.post(
            f"/api/library/intakes/{ident}/complete",
            json={"hashes": {sel: checksum}},
            headers=headers,
        )
        item = completed.json()["files"][0]["items"][0]
        original = await client.get(
            f"/api/library/items/{item['item_id']}/versions/{item['version_id']}/original",
            headers={"Range": "bytes=0-8"},
        )
        assert original.status_code == 206 and original.content == raw[:9]
        assert original.headers["cache-control"] == "no-store"
        complete_original = await client.get(
            f"/api/library/items/{item['item_id']}/versions/{item['version_id']}/original"
        )
        assert complete_original.content == raw
        assert item["original_sha256"] == checksum


@pytest.fixture
async def library_running(library, bridge, settings):
    async for url in running.__wrapped__(bridge, settings, None):
        yield url


async def test_real_mcp_serialized_metadata_text_and_legacy_adapter(
    library_running, library, browser, owner, token_factory
):
    item, _ = await upload(library, browser)
    await library.process_once(owner)
    async with client_session(library_running, token_factory()) as session:
        tools = {t.name for t in (await session.list_tools()).tools}
        assert "submit_library_files" not in tools
        assert "get_library_status" in tools
        for name, args in [
            ("get_library_status", {}),
            ("list_library_items", {}),
            ("get_library_item", {"item_id": item["item_id"]}),
            ("read_library_item", {"item_id": item["item_id"], "version_id": item["version_id"]}),
            ("read_local_document", {"document_id": item["document_id"]}),
            ("search_library", {"query": "ATP"}),
        ]:
            result = (await session.call_tool(name, args)).structuredContent
            assert result["status"] == "ok", (name, result)
            assert result["meta"]["privacy"]
            if name == "read_library_item":
                assert "ATP" in result["data"]["parts"][0]["text"]
                assert result["data"]["version_id"] == item["version_id"]


async def test_expiry_and_sweeper(library, browser, owner, bridge):
    item, _ = await upload(library, browser)
    await library.process_once(owner)
    with bridge.store.transaction() as session:
        session.get(Version, (owner, item["version_id"])).expires_at = utcnow() - timedelta(
            seconds=1
        )
    with pytest.raises(DomainError):
        library.bytes(owner, item["version_id"])
    library.sweep()
    assert library.status(owner).data["quota"]["committed_bytes"] == 0
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Representation)))


def recovery_target(bridge, tmp_path, name):
    from canvas_bridge.policy import Registry
    from canvas_bridge.service import Bridge
    from canvas_bridge.storage import Store
    from canvas_bridge.synthetic import SyntheticProvider

    settings = bridge.settings.model_copy(update={"library_root": tmp_path / name})
    store = Store("sqlite:///:memory:")
    store.create_fixture_schema()
    return Bridge(
        settings, store, bridge.vault, Registry(settings.institutions_file), SyntheticProvider()
    )


async def test_encrypted_backup_restore_deletion_and_missing_journal(
    library, browser, owner, bridge, tmp_path
):
    from canvas_bridge.library.recovery import backup, restore

    first, _ = await upload(library, browser, b"surviving fictional bytes")
    deleted, _ = await upload(library, browser, b"deleted fictional bytes")
    path = tmp_path / "fictional-backup.zip"
    report = backup(library, owner, path)
    assert report["originals"] == 2
    assert b"surviving fictional bytes" not in path.read_bytes()
    library.delete_item(
        browser,
        deleted["item_id"],
        VersionExpectation(
            expected_version_id=deleted["version_id"],
            expected_revision=1,
            expected_permission_revision=1,
        ),
    )
    target = recovery_target(bridge, tmp_path, "restored")
    try:
        outcome = restore(target.library, owner, path, bridge.settings.deletion_journal)
        assert outcome["restored_originals"] == 1 and not outcome["grants_restored"]
        assert target.library.bytes(owner, first["version_id"]) == b"surviving fictional bytes"
        with pytest.raises(DomainError):
            target.library.bytes(owner, deleted["version_id"])
    finally:
        target.store.close()
    held = recovery_target(bridge, tmp_path, "held")
    try:
        with pytest.raises(DomainError) as exc:
            restore(held.library, owner, path, tmp_path / "missing-journal")
        assert exc.value.reason_code == "RESTORE_ON_HOLD"
        assert held.library.status(owner).data["state"] == "restore_hold"
    finally:
        held.store.close()


async def test_migration_is_additive_and_downgrade_preserves_data(tmp_path, settings):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy import inspect as inspect_db

    from canvas_bridge.resources import resource_root

    database = "sqlite:///" + (tmp_path / "migration.sqlite").as_posix()
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    config.attributes["database_url"] = database
    config.attributes["vault_key_file"] = settings.vault_key_file
    command.upgrade(config, "f17a6b204c31")
    command.upgrade(config, "head")
    engine = create_engine(database)
    try:
        assert "library_versions" in inspect_db(engine).get_table_names()
        assert "independent_resources" in inspect_db(engine).get_table_names()
        with pytest.raises(RuntimeError, match="durable originals"):
            command.downgrade(config, "f17a6b204c31")
        assert "library_versions" in inspect_db(engine).get_table_names()
    finally:
        engine.dispose()


async def test_legacy_explicit_copy_does_not_extend_old_expiry(library, browser, owner, bridge):
    data = b"Fictional temporary source"
    old_id = await bridge.independent.ingest(
        owner, data, "fictional.txt", "text/plain", own_material=True, share_text=True
    )
    old = bridge.independent.require(owner, old_id)
    request = selection(browser, data, channels=("metadata", "text"))
    result = await library.save_legacy(browser, old_id, request)
    assert result["status"] == "complete"
    assert bridge.independent.require(owner, old_id).expires_at == old.expires_at
    version = result["files"][0]["items"][0]["version_id"]
    assert library.require(owner, version=version)[1].expires_at is None


async def test_publication_rechecks_account_after_safety_work(
    library, browser, owner, bridge, monkeypatch
):
    raw = b"Fictional pending file"
    request = selection(browser, raw)
    receipt = library.create_intake(browser, request)
    sel = receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(raw).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, checksum, raw)

    async def scanner(data, kind, settings, preview=False):
        await delete_account(bridge, owner, 0)
        return inspect(data, kind)

    monkeypatch.setattr("canvas_bridge.library.safety.scan", scanner)
    result = await library.complete(browser, receipt["intake_id"], {sel: checksum})
    assert not any(f["items"] for f in result["files"])
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Version)))


async def test_scan_outage_is_retryable_quarantine_not_publication(
    library, browser, owner, monkeypatch
):
    from canvas_bridge.library.contracts import fail

    raw = b"Fictional quarantine"
    receipt = library.create_intake(browser, selection(browser, raw))
    sel = receipt["files"][0]["selection_id"]
    checksum = hashlib.sha256(raw).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, checksum, raw)

    async def scanner(*args, **kwargs):
        fail("SCAN_UNAVAILABLE", "retry_later", retryable=True)

    monkeypatch.setattr("canvas_bridge.library.safety.scan", scanner)
    result = await library.complete(browser, receipt["intake_id"], {sel: checksum})
    assert result["files"][0]["reason_code"] == "SCAN_UNAVAILABLE"
    assert library.status(owner).data["quota"]["reserved_bytes"] == len(raw)
    assert library.list(owner, browser=True).data["items"] == []


async def test_cursor_owner_permission_and_representation_binding(
    library, browser, owner, recipient
):
    one, _ = await upload(library, browser, b"First fictional ATP")
    await upload(library, browser, b"Second fictional ATP")
    page = library.list(owner, limit=1)
    assert page.data["next_cursor"]
    with pytest.raises(DomainError):
        library.read_cursor("other", page.data["next_cursor"], "list", {}, 0)
    library.update_grants(
        browser,
        one["item_id"],
        PermissionChange(
            expected_version_id=one["version_id"],
            expected_permission_revision=1,
            allow_processing=False,
            purpose="study",
            recipient_grants=[],
        ),
    )
    with pytest.raises(DomainError):
        library.list(owner, limit=1, cursor=page.data["next_cursor"])


async def test_actual_safety_worker_text_and_image(settings, tmp_path):
    """Actual isolated local decoder run; does not prove host pixel delivery."""
    from PIL import Image

    from canvas_bridge.library.safety import scan

    settings.parser_root = tmp_path / "bounded-parser"
    text = await scan(b"Fictional safety worker input", "txt", settings)
    assert text["kind"] == "txt"
    source = io.BytesIO()
    Image.new("RGB", (64, 32), "navy").save(source, "PNG")
    preview = await scan(source.getvalue(), "png", settings, preview=True)
    assert preview["dimensions"] == [64, 32] and preview["png"]
