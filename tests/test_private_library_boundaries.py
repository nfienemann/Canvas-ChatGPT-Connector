"""Additional fault, boundary and compatibility probes for the private library."""

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.exc import IntegrityError

from canvas_bridge.academic.independent_models import IndependentRequest
from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.independent_intelligence import run
from canvas_bridge.library.contracts import PermissionChange, VersionExpectation
from canvas_bridge.library.models import Account, Grant, Intake, Selection, Version
from canvas_bridge.library_safety_worker import inspect
from canvas_bridge.lifecycle import journal_delete
from canvas_bridge.storage import IndependentResource, utcnow
from tests.test_private_library import browser as browser
from tests.test_private_library import library as library
from tests.test_private_library import recipient as recipient
from tests.test_private_library import selection, upload


async def test_duplicate_hash_reuses_only_identical_permissions(library, browser, owner):
    first, _ = await upload(library, browser, b"same fictional bytes", channels=())
    same, _ = await upload(library, browser, b"same fictional bytes", channels=())
    assert same["version_id"] == first["version_id"]
    assert library.status(owner).data["quota"]["committed_bytes"] == len(b"same fictional bytes")
    different, _ = await upload(
        library, browser, b"same fictional bytes", channels=("metadata", "text")
    )
    assert different["version_id"] != first["version_id"]
    assert library.require(owner, version=first["version_id"])[2].payload["recipients"] == []


async def test_search_revocation_cannot_return_hits_without_source_fences(
    library, browser, owner, recipient, monkeypatch
):
    item, _ = await upload(library, browser)
    await library.process_once(owner)
    original = library.representation

    def revoke_after_read(who, version):
        rep = original(who, version)
        library.update_grants(
            browser,
            item["item_id"],
            PermissionChange(
                expected_version_id=item["version_id"],
                expected_permission_revision=1,
                allow_processing=False,
                purpose="study",
                recipient_grants=[],
            ),
        )
        return rep

    monkeypatch.setattr(library, "representation", revoke_after_read)
    with pytest.raises(DomainError):
        library.search(owner, "ATP")


async def test_receipt_reconciles_processing_deletion_and_scrubs_manifest(library, browser, owner):
    item, receipt = await upload(library, browser, name="private-fictional-title.txt")
    await library.process_once(owner)
    assert (
        library.receipt(owner, receipt["intake_id"])["files"][0]["items"][0]["processing_state"]
        == "ready"
    )
    current = library.get(owner, item["item_id"], browser=True).data
    library.delete_item(
        browser,
        item["item_id"],
        VersionExpectation(
            expected_version_id=item["version_id"],
            expected_revision=current["metadata_revision"],
            expected_permission_revision=current["permission_revision"],
        ),
    )
    reconciled = library.receipt(owner, receipt["intake_id"])
    assert reconciled["files"][0]["items"][0]["storage_state"] == "deleted"
    assert reconciled["files"][0]["items"][0]["processing_state"] == "unavailable"
    with library.bridge.store.transaction() as session:
        intake = session.get(Intake, (owner, receipt["intake_id"]))
        row = session.get(Selection, (owner, receipt["files"][0]["selection_id"]))
        assert "private-fictional-title" not in json.dumps([intake.payload, row.payload])
        assert "grants" not in intake.payload


async def test_above_parser_limit_preserves_exact_original(library, browser, owner):
    raw = b"Fictional storage-only large document.\n" * 280_000
    assert 10_000_000 < len(raw) < 100 * 1024 * 1024
    item, _ = await upload(library, browser, raw)
    await library.process_once(owner)
    assert (
        library.get(owner, item["item_id"], browser=True).data["processing_state"] == "unsupported"
    )
    _, stream = library.original(owner, item["item_id"], item["version_id"])
    assert hashlib.sha256(b"".join(stream)).hexdigest() == hashlib.sha256(raw).hexdigest()


def test_pptx_embedded_chart_workbook_cannot_hide_active_content():
    raw = (
        Path(__file__).parent / "fixtures/stress-repair/sources/formats/lecture_continuation.pptx"
    ).read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(out, "w") as target:
        for entry in source.infolist():
            body = source.read(entry)
            if entry.filename.endswith("Microsoft_Excel_Sheet1.xlsx"):
                altered = io.BytesIO()
                with (
                    zipfile.ZipFile(io.BytesIO(body)) as workbook,
                    zipfile.ZipFile(altered, "w") as hidden,
                ):
                    for member in workbook.infolist():
                        hidden.writestr(member, workbook.read(member))
                    hidden.writestr("xl/vbaProject.bin", b"fictional forbidden macro payload")
                body = altered.getvalue()
            target.writestr(entry, body)
    with pytest.raises(ValueError, match="UNSAFE_CONTENT"):
        inspect(out.getvalue(), "pptx")


async def test_explicit_search_finds_an_item_beyond_first_listing(
    library, browser, owner, recipient
):
    items = []
    for index in range(51):
        item, _ = await upload(
            library, browser, f"Fictional distant marker {index}.".encode(), processing=False
        )
        items.append(item)
    target = max(items, key=lambda item: item["item_id"])
    library.update_grants(
        browser,
        target["item_id"],
        PermissionChange(
            expected_version_id=target["version_id"],
            expected_permission_revision=1,
            allow_processing=True,
            purpose="study",
            recipient_grants=[
                {"recipient_profile_id": "fictional-independent", "channels": ["metadata", "text"]}
            ],
        ),
    )
    await library.process_once(owner)
    assert target["item_id"] not in {
        i["item_id"] for i in library.list(owner, limit=50).data["items"]
    }
    result = library.search(owner, "distant", item_ids=[target["item_id"]])
    assert len(result.data["hits"]) == 1
    assert result.data["hits"][0]["item_id"] == target["item_id"]


async def test_reordered_profile_sets_do_not_lose_grants(library, browser, owner, recipient):
    item, _ = await upload(library, browser)
    with library.bridge.store.transaction() as session:
        grant = session.get(Grant, (owner, item["version_id"]))
        payload = json.loads(json.dumps(grant.payload))
        for key in ("purposes", "channels", "classifications", "downstream_processing"):
            payload["recipients"][0]["profile"][key].reverse()
        grant.payload = payload
    assert library.permitted(owner, item["version_id"], "metadata")


def test_concurrent_admission_is_atomic(library, browser, owner):
    library.bridge.settings.library_quota_bytes = 16

    def create(_):
        return library.create_intake(browser, selection(browser, b"1234567890"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(8)))
    assert sum(r["files"][0]["state"] == "created" for r in results) == 1
    assert library.status(owner).data["quota"]["reserved_bytes"] == 10


async def test_foreign_owner_child_rejected_by_database(library, browser, owner):
    item, _ = await upload(library, browser)
    with library.bridge.store.transaction() as session:
        session.add(Account(owner="another-owner"))
    with pytest.raises(IntegrityError):
        with library.bridge.store.transaction() as session:
            session.add(
                Version(
                    owner="another-owner",
                    id=opaque_id(),
                    item=item["item_id"],
                    digest="a" * 64,
                    size=1,
                    object_key=opaque_id(),
                    kind="txt",
                    provenance={},
                )
            )


async def test_missing_or_new_journal_fence_blocks_existing_bytes(library, browser, owner):
    item, _ = await upload(library, browser)
    journal_delete(
        library.bridge.settings.deletion_journal,
        library.bridge.vault.key,
        "library-item:" + owner + ":" + item["item_id"],
        1,
    )
    with pytest.raises(DomainError):
        library.bytes(owner, item["version_id"])


async def test_queued_and_running_processing_revocation(library, browser, owner, monkeypatch):
    item, _ = await upload(library, browser)

    async def parser(*args, **kwargs):
        library.update_grants(
            browser,
            item["item_id"],
            PermissionChange(
                expected_version_id=item["version_id"],
                expected_permission_revision=1,
                allow_processing=False,
                purpose="study",
                recipient_grants=[],
            ),
        )
        return {"pages": [{"text": "must not be published", "page": 1}], "coverage": "complete"}

    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_document", parser)
    assert await library.process_once(owner)
    assert library.require(owner, version=item["version_id"])[1].processing == "not_requested"
    with pytest.raises(DomainError):
        library.representation(owner, item["version_id"])


async def test_grant_is_separate_from_heavy_processing_admission(library, browser, owner):
    item, _ = await upload(library, browser)
    async with library.heavy(owner):
        assert not await library.process_once(owner)
        with pytest.raises(DomainError) as error:
            async with library.heavy(owner):
                pytest.fail("A second heavy operation was admitted")
        assert error.value.reason_code == "PROCESSING_BUSY"
    assert await library.process_once(owner)


async def test_known_institutional_digest_cannot_be_renamed(library, browser, owner):
    data = b"Fictional restricted institution source"
    with library.bridge.store.transaction() as session:
        session.add(
            IndependentResource(
                owner=owner,
                id=opaque_id(),
                kind="institutional_lineage",
                version_hash=hashlib.sha256(data).hexdigest(),
                provenance={"source_type": "institutional"},
                content={},
                expires_at=utcnow() + timedelta(days=91),
            )
        )
    request = selection(browser, data, name="renamed.txt")
    receipt = library.create_intake(browser, request)
    sel = receipt["files"][0]["selection_id"]
    digest = hashlib.sha256(data).hexdigest()
    library.put_chunk(browser, receipt["intake_id"], sel, 0, digest, data)
    result = await library.complete(browser, receipt["intake_id"], {sel: digest})
    assert result["files"][0]["state"] == "rejected"
    assert not result["files"][0]["items"]


async def test_study_adapter_and_exact_image_preview(library, browser, owner, recipient):
    item, _ = await upload(
        library, browser, b"Fictional methods: compare ATP before and after exercise."
    )
    await library.process_once(owner)
    result = await run(
        library.bridge,
        owner,
        IndependentRequest(
            capability="assessment",
            documents=[
                {"document_id": item["document_id"], "expected_hash": item["original_sha256"]}
            ],
        ),
    )
    assert result.status in {"ok", "partial_data"} and result.sources
    assert result.sources[0].content_hash == item["original_sha256"]
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "green").save(image, "PNG")
    picture, _ = await upload(library, browser, image.getvalue(), name="fictional.png")
    result, png = await library.render(owner, picture["item_id"], picture["version_id"])
    assert png and result.data["original_sha256"] == hashlib.sha256(image.getvalue()).hexdigest()


async def test_delivery_expiry_owner_binding_and_readonly_gate(library, browser, owner, recipient):
    from canvas_bridge.app import create_app

    item, _ = await upload(library, browser)
    result = library.prepare_download(owner, item["item_id"], item["version_id"])
    ident = result.data["delivery_id"]
    assert library.delivery(owner, ident)[1] == item["version_id"]
    with pytest.raises(DomainError):
        library.delivery("another-owner", ident)
    library.bridge.settings.mcp_read_only = True
    app = create_app(library.bridge.settings, library.bridge)
    names = {t.name for t in app.state.mcp._tool_manager.list_tools()}
    assert "prepare_library_download" not in names and "submit_library_files" not in names
    assert "get_library_status" in names
    library.bridge.retention.clock = lambda: utcnow() + timedelta(minutes=6)
    with pytest.raises(DomainError):
        library.delivery(owner, ident)
