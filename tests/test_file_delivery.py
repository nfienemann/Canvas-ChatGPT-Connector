"""Synthetic original-byte, authorization, transport and lifecycle acceptance."""

import asyncio
import base64
import hashlib
import io
import zipfile

import httpx
import pytest
from starlette.requests import ClientDisconnect

from canvas_bridge.app import create_app
from canvas_bridge.course_files import list_files
from canvas_bridge.domain import DomainError
from canvas_bridge.file_delivery import OriginalFiles, safe_filename
from canvas_bridge.file_download import file_version, stream_original
from canvas_bridge.storage import Connection, Course
from tests.conftest import seed
from tests.test_course_files import Body, file_record
from tests.test_course_files import file_client as file_client
from tests.test_docx_reading import docx
from tests.test_file_reading import scientific_pdf
from tests.test_spreadsheet_reading import MIME, workbook


def deterministic_workbook():
    """Freeze ZIP timestamps; preserve formulas, cached cells, styles and hidden data."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as target:
        for name in source.namelist():
            target.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), source.read(name))
    return output.getvalue()


@pytest.fixture
async def original(bridge, owner, seeded):
    data = deterministic_workbook()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                size=len(data),
                filename="Synthetic PCR Δ.xlsx",
                **{"content-type": MIME},
                updated_at="2026-10-22T12:00:00Z",
                url="https://canvas.synthetic.invalid/files/51/download",
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": data}
    bridge.synthetic.data["file_types"] = {"51": MIME}
    _, courses = bridge.selected(owner, seeded)
    listed = await list_files(bridge, owner, seeded, courses[0].id)
    yield courses[0], listed.data["files"][0]["file_id"], data
    bridge.original_files.close()


@pytest.fixture
async def http_delivery(bridge, settings):
    app = create_app(settings, bridge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=settings.resource_url
    ) as http:
        yield http


async def test_workbook_complete_routes_are_original_bytes(
    bridge, owner, seeded, original, http_delivery, token_factory
):
    course, file, data = original
    first = await bridge.original_files.prepare(owner, seeded, file)
    assert first.status == "ok" and first.data["original"]
    assert first.data["host_handoff"] == "not_attempted"
    assert first.data["bytes_sha256"] == hashlib.sha256(data).hexdigest()
    assert first.data["byte_size"] == len(data)
    result, private = await bridge.original_files.payload(owner, seeded, first.data["delivery_id"])
    decoded = base64.b64decode(private["resource"]["resource"]["blob"])
    # Independent hash implementation (OpenSSL-backed standard hashlib vs WebCrypto
    # in test_file_delivery_ui); byte equality also proves all ZIP parts survived.
    assert decoded == data
    assert "blob" not in result.model_dump_json()
    url = private["external_url"]
    head = await http_delivery.head(url)
    assert head.status_code == 200 and not head.content
    assert int(head.headers["content-length"]) == len(data)
    for headers in ({}, {"Range": "bytes=1-20"}, {"Range": "invalid"}):
        delivered = await http_delivery.get(url, headers=headers)
        assert delivered.status_code == 200 and delivered.content == data
        assert delivered.headers["accept-ranges"] == "none"
        assert delivered.headers["cache-control"] == "private, no-store"
        assert delivered.headers["x-content-type-options"] == "nosniff"
        assert "filename*=UTF-8''" in delivered.headers["content-disposition"]
    machine = "/course-file-original/" + first.data["delivery_id"]
    assert (await http_delivery.get(machine)).status_code == 401
    assert (
        await http_delivery.get(machine, headers={"Authorization": "Bearer " + token_factory()})
    ).content == data
    assert (
        await http_delivery.get(
            machine, headers={"Authorization": "Bearer " + token_factory(sub="student-two")}
        )
    ).status_code == 403
    assert not bridge.original_files.active


@pytest.mark.parametrize(
    "kind,data,mime",
    [
        ("pdf", scientific_pdf(), "application/pdf"),
        ("docx", docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("bin", bytes(range(256)) * 800, "application/octet-stream"),
        ("txt", b"\xff\x00\xfe\r\n", "text/plain"),
        ("html", b"<html><script>untrusted()</script></html>", "text/html"),
        ("json", b'{"source":"legitimate"}', "application/json"),
        ("pdf", b"malformed-authorized-document", "application/pdf"),
        ("bin", b"", "application/octet-stream"),
    ],
    ids=["pdf", "docx", "large-binary", "non-utf8", "html", "json", "malformed", "empty"],
)
async def test_formats_do_not_require_extraction(
    bridge, owner, seeded, original, http_delivery, kind, data, mime
):
    _, file, _ = original
    bridge.synthetic.data["files"]["11"][0].update(
        filename="original." + kind, size=len(data), **{"content-type": mime}
    )
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["file_types"]["51"] = mime
    assert not bridge.settings.file_reading_enabled
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    _, private = await bridge.original_files.payload(owner, seeded, prepared.data["delivery_id"])
    delivered = await http_delivery.get(private["external_url"])
    assert delivered.content == data and delivered.status_code == 200
    assert delivered.headers["content-type"] == mime
    if len(data) > bridge.settings.file_delivery_inline_bytes:
        assert private["resource"]["type"] == "resource_link"


@pytest.mark.parametrize(
    "change",
    ["other_owner", "other_connection", "altered_file", "scope", "locked", "revoked", "changed"],
)
async def test_prepare_and_redemption_authorization(
    bridge, owner, seeded, original, http_delivery, change
):
    course, file, data = original
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    ident = prepared.data["delivery_id"]
    _, private = await bridge.original_files.payload(owner, seeded, ident)
    if change in {"other_owner", "other_connection"}:
        other = await seed(bridge, "other", "other-connection")
        with pytest.raises(DomainError):
            await bridge.original_files.prepare(
                "other" if change == "other_owner" else owner, other, file
            )
        with pytest.raises(DomainError):
            await bridge.original_files.payload(
                "other" if change == "other_owner" else owner, other, ident
            )
        # Document possession-based semantics: an intentionally shared capability
        # itself grants redemption, without claiming redeemer identity.
        assert (await http_delivery.get(private["external_url"])).content == data
        return
    if change == "altered_file":
        with pytest.raises(DomainError):
            await bridge.original_files.prepare(owner, seeded, file + "x")
        with pytest.raises(DomainError):
            await bridge.original_files.payload(owner, seeded, ident + "x")
        return
    if change == "scope":
        with bridge.store.transaction() as session:
            session.get(Course, course.id).selected = False
    elif change == "locked":
        bridge.synthetic.data["files"]["11"][0]["locked_for_user"] = True
    elif change == "revoked":
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).state = "revoked"
    else:
        bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-22T13:00:00Z"
    response = await http_delivery.get(private["external_url"])
    assert response.status_code in {403, 409}
    if change == "changed":
        assert response.json()["reason_code"] == "SOURCE_CHANGED"
    assert response.content != data
    assert not bridge.original_files.records
    with pytest.raises(DomainError):
        await bridge.original_files.prepare(
            owner, seeded, file, expected_source_version=prepared.data["source_version"]
        )


async def test_partial_inventory_allows_individually_authorized_file(
    bridge, owner, seeded, original
):
    _, file, data = original
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    result = await bridge.original_files.prepare(owner, seeded, file)
    assert result.data["byte_size"] == len(data)


@pytest.mark.parametrize("guard", ["version", "digest", "during"])
async def test_source_and_digest_guards_delete_partial_staging(
    bridge, owner, seeded, original, monkeypatch, guard
):
    _, file, _ = original
    kwargs = (
        {"expected_source_version": "a" * 64}
        if guard == "version"
        else {"expected_bytes_sha256": "b" * 64}
        if guard == "digest"
        else {}
    )
    if guard == "during":
        import canvas_bridge.file_delivery as module

        original_stream = module.stream_original

        async def change(*args, **kwargs):
            result = await original_stream(*args, **kwargs)
            bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-23T00:00:00Z"
            return result

        monkeypatch.setattr(module, "stream_original", change)
    with pytest.raises(DomainError) as error:
        await bridge.original_files.prepare(owner, seeded, file, **kwargs)
    assert error.value.reason_code in {"SOURCE_CHANGED", "INTEGRITY_MISMATCH"}
    assert not list(bridge.original_files.root.glob("obj_*"))


@pytest.mark.parametrize(
    "change", ["expired", "backward", "forward", "resume", "origin", "corrupt", "altered_cap"]
)
async def test_expiry_clocks_origin_and_integrity(
    bridge, owner, seeded, original, http_delivery, monkeypatch, change
):
    import canvas_bridge.file_delivery as module

    _, file, _ = original
    first = await bridge.original_files.prepare(owner, seeded, file)
    _, private = await bridge.original_files.payload(owner, seeded, first.data["delivery_id"])
    item = bridge.original_files.records[first.data["delivery_id"]]
    if change == "expired":
        item.wall_start -= 301
        item.mono_start -= 301
    elif change in {"backward", "forward", "resume"}:
        wall = module.time.time()
        mono = module.time.monotonic()
        monkeypatch.setattr(
            module.time, "time", lambda: wall + (-60 if change == "backward" else 1000)
        )
        if change == "resume":
            monkeypatch.setattr(module.time, "monotonic", lambda: mono + 1000)
    elif change == "origin":
        bridge.settings.resource_url = "https://new-tunnel.invalid"
    elif change == "corrupt":
        item.path.write_bytes(b"damaged")
    else:
        private["external_url"] += "x"
    response = await http_delivery.get(private["external_url"])
    assert response.status_code in {403, 409}
    assert not bridge.original_files.active


async def test_restart_crash_cleanup_and_fresh_grant(
    bridge, owner, seeded, original, http_delivery
):
    _, file, _ = original
    first = await bridge.original_files.prepare(owner, seeded, file)
    manager = bridge.original_files
    old = manager.records[first.data["delivery_id"]]
    root = manager.root
    old.wall_start -= 301
    old.mono_start -= 301
    second = await manager.prepare(owner, seeded, file)
    assert second.data["delivery_id"] != first.data["delivery_id"] and not old.path.exists()
    # Simulate process loss of the directory lock without graceful cleanup.
    manager.lockfile.close()
    manager.lockfile = None
    stray = root / ("obj_" + "a" * 32 + ".part")
    stray.write_bytes(b"abandoned")
    unrelated = root / "keep.txt"
    unrelated.write_text("unrelated")
    recovered = OriginalFiles(bridge)
    recovered.start()
    assert not list(root.glob("obj_*")) and unrelated.exists()
    with pytest.raises(DomainError):
        recovered.lookup(second.data["delivery_id"], owner, seeded)
    recovered.close()


async def test_limits_and_cancellation_release_staging(
    bridge, owner, seeded, original, monkeypatch
):
    _, file, data = original
    bridge.settings.file_delivery_max_bytes = 1
    with pytest.raises(DomainError) as error:
        await bridge.original_files.prepare(owner, seeded, file)
    assert error.value.reason_code == "FILE_TOO_LARGE"
    bridge.settings.file_delivery_max_bytes = len(data)
    bridge.settings.file_delivery_staging_bytes = 1
    with pytest.raises(DomainError) as error:
        await bridge.original_files.prepare(owner, seeded, file)
    assert error.value.reason_code == "STAGING_UNAVAILABLE"
    bridge.settings.file_delivery_staging_bytes = len(data) * 4
    entered = asyncio.Event()

    async def stall(*args, **kwargs):
        args[4].write(b"partial")
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("canvas_bridge.file_delivery.stream_original", stall)
    pending = asyncio.create_task(bridge.original_files.prepare(owner, seeded, file))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert bridge.original_files.reserved == 0 and not bridge.original_files.active
    assert not list(bridge.original_files.root.glob("obj_*"))


@pytest.mark.parametrize(
    "name",
    [
        "../../evil.xlsx",
        "CON.xlsx",
        "a\r\nX-Injected: yes.xlsx",
        "雪" * 200 + ".xlsx",
        "..",
        "LPT9",
        "<script>.xlsx",
    ],
)
def test_filenames_are_safe(name):
    safe = safe_filename(name)
    assert safe and len(safe.encode()) <= 180
    assert not any(c in safe for c in '/\\<>:"|?*\r\n')
    assert safe not in {"CON.xlsx", "LPT9", ".."}
    if name.endswith(".xlsx"):
        assert safe.endswith(".xlsx")


@pytest.mark.parametrize(
    "failure",
    ["html", "json", "short", "excess", "dishonest", "encoded", "disconnect", "429", "500"],
)
async def test_original_response_validation(file_client, failure):
    client, provider = file_client
    data = b"%PDF-1.7\nsynthetic body"
    metadata = file_record(size=len(data), updated_at="2026-01-01T00:00:00Z")
    headers = {"content-type": "application/pdf"}
    if failure == "html":
        data = b"<html>login</html>"
    if failure == "json":
        data = b'{"error":"denied"}'
    if failure in {"html", "json"}:
        metadata["size"] = len(data)
    if failure == "short":
        data = data[:-1]
    if failure == "excess":
        data += b"excess"
    if failure == "dishonest":
        headers["content-length"] = "99999"
    if failure == "encoded":
        headers["content-encoding"] = "gzip"

    class Broken(Body):
        async def __aiter__(self):
            yield b"%PDF"
            raise httpx.ReadError("synthetic disconnect")

    response = httpx.Response(
        int(failure) if failure.isdecimal() else 200,
        headers=headers,
        stream=Broken() if failure == "disconnect" else Body(data),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        with pytest.raises(DomainError):
            await stream_original(
                client, "11", "51", metadata, io.BytesIO(), max_bytes=500, budget=2, http=http
            )


def test_source_version_excludes_rotating_url():
    metadata = file_record(updated_at="2026-01-01T00:00:00Z")
    version = file_version(metadata)
    metadata["url"] = "https://storage.fixture.invalid/rotated?signature=changed"
    assert file_version(metadata) == version


async def test_concurrent_acquisition_budget_is_enforced(
    bridge, owner, seeded, original, monkeypatch
):
    _, file, data = original
    entered = asyncio.Event()
    count = 0

    async def stall(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("canvas_bridge.file_delivery.stream_original", stall)
    tasks = [
        asyncio.create_task(bridge.original_files.prepare(owner, seeded, file)) for _ in range(2)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        from canvas_bridge.ephemeral_blob import storage_size

        assert bridge.original_files.reserved == 2 * storage_size(len(data))
        with pytest.raises(DomainError) as error:
            await bridge.original_files.prepare(owner, seeded, file)
        assert error.value.reason_code == "RATE_LIMITED"
        async with (
            bridge.original_files.slot("synthetic-b"),
            bridge.original_files.slot("synthetic-c"),
        ):
            with pytest.raises(DomainError) as error:
                async with bridge.original_files.slot("synthetic-d"):
                    pass
            assert error.value.reason_code == "RATE_LIMITED"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert not bridge.original_files.active and bridge.original_files.reserved == 0
    assert not list(bridge.original_files.root.glob("obj_*"))


async def test_stream_failure_before_body_releases_handle_and_lease(
    bridge, owner, seeded, original
):
    from canvas_bridge.file_delivery import OriginalResponse

    _, file, _ = original
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    manager = bridge.original_files
    item = manager.records[prepared.data["delivery_id"]]
    slot = manager.slot(owner)
    await slot.__aenter__()
    item.active += 1

    async def chunks():
        with item.path.open("rb") as stream:
            yield stream.read(4)

    response = OriginalResponse(chunks(), {}, manager, item, slot)

    async def disconnected(message):
        raise OSError("synthetic disconnected consumer")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, disconnected)
    assert not manager.active and item.active == 0
    manager.revoke(item)
    assert not item.path.exists()


async def test_retention_deadline_cannot_be_extended(bridge, owner, seeded, original):
    _, file, _ = original
    bridge.settings.file_delivery_ttl_seconds = 1
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    item = bridge.original_files.records[prepared.data["delivery_id"]]
    bridge.settings.file_delivery_ttl_seconds = 900
    item.wall_start -= 2
    item.mono_start -= 2
    with pytest.raises(DomainError):
        bridge.original_files.lookup(item.id, owner, seeded)
