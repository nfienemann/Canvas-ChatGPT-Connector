"""Fictional file inventory and adversarial download tests; no real coursework."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError
from canvas_bridge.file_download import download_file
from canvas_bridge.policy import Institution
from canvas_bridge.retrieval import fetch_material, outline, search_materials
from canvas_bridge.storage import Material
from canvas_bridge.synthetic import SyntheticProvider
from tests.conftest import seed

PDF = b"%PDF-1.7\nfictional transport fixture; not a parsed PDF"


def file_record(**changes):
    return {
        "id": 51,
        "display_name": "Synthetic reading.pdf",
        "filename": "reading.pdf",
        "content-type": "application/pdf",
        "size": len(PDF),
        "url": "https://canvas.fixture.invalid/files/51/download?verifier=private-synthetic-value",
        "locked_for_user": False,
        "hidden_for_user": False,
        "locked": False,
        "hidden": False,
        **changes,
    }


@pytest.fixture
async def file_client(settings):
    provider = SyntheticProvider()
    provider.data["files"] = {"11": [file_record()]}
    institution = Institution(
        id="file-fixture",
        name="Fictional",
        origin="https://canvas.fixture.invalid",
        status="personal_testing",
        download_origins=["https://storage.fixture.invalid"],
    )
    async with provider.client() as http:
        yield CanvasClient(institution, "fixture-only-secret", settings, http), provider


class Body(httpx.AsyncByteStream):
    def __init__(self, *chunks, delay=0):
        self.chunks, self.delay, self.closed = chunks, delay, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def response(data=PDF, **headers):
    return httpx.Response(
        200, stream=Body(data), headers={"Content-Type": "application/pdf", **headers}
    )


async def test_T12_T13_file_refs_are_course_scoped_and_join_module_items(bridge, owner, seeded):
    bridge.synthetic.data["files"] = {"11": [file_record(), file_record()], "12": [file_record()]}
    bridge.synthetic.data["module_items"] = {
        "11": [
            {"title": "Reading", "type": "File", "content_id": 51},
            {"title": "Syllabus", "type": "Page", "page_url": "syllabus"},
            {"title": "Unavailable", "type": "File", "content_id": 99},
            {"title": "Hidden item", "type": "File", "content_id": 51, "published": False},
        ]
    }
    _, courses = bridge.selected(owner, seeded)
    first = await outline(bridge, owner, seeded, courses[0].id)
    second = await outline(bridge, owner, seeded, courses[1].id)
    assert first.status == "partial_data"  # The unresolved module file is explicit coverage loss.
    assert first.data["inventory_status"]["file_metadata_failures"]
    assert first.data["inventory_coverage"] == dict.fromkeys(
        ["pages", "files", "modules"], "complete"
    )
    page, file = first.data["materials"]
    assert page["kind"] == "page" and file["kind"] == "file"
    assert file["id"] != second.data["materials"][1]["id"]
    items = first.data["modules"][0]["items"]
    assert len(items) == 3
    assert items[0]["material_ref"] == file["id"]
    assert items[1]["material_ref"] == page["id"]
    assert "material_ref" not in items[2]
    assert "verifier" not in first.model_dump_json()
    other = await seed(bridge, "other-owner", "other-connection")
    with pytest.raises(DomainError):
        await fetch_material(bridge, "other-owner", other, file["id"])
    bridge.select_courses(owner, seeded, [courses[1].id], "UTC")
    with pytest.raises(DomainError):
        await fetch_material(bridge, owner, seeded, file["id"])


async def test_T11_file_fetch_is_explicitly_gated_and_never_parsed(bridge, owner, seeded):
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    _, courses = bridge.selected(owner, seeded)
    listing = await outline(bridge, owner, seeded, courses[0].id)
    file = listing.data["materials"][1]
    result = await fetch_material(bridge, owner, seeded, file["id"])
    assert result.status == "unsupported_feature"
    assert result.data["coverage"] == "unsupported" and result.data["text"] == ""
    assert result.sources[0].url.endswith("/courses/11/files/51")
    assert "verifier" not in result.model_dump_json()
    assert not any("download" in r.url.path for r in bridge.synthetic.requests)
    assert not (await search_materials(bridge, owner, seeded, "reading")).data["results"]


@pytest.mark.parametrize(
    "flag,value",
    [
        ("locked_for_user", True),
        ("hidden_for_user", True),
        ("locked_for_user", None),
        ("hidden_for_user", None),
        ("locked", True),
        ("hidden", True),
    ],
)
async def test_T13_hidden_or_unknown_file_visibility_is_not_indexed(
    bridge, owner, seeded, flag, value
):
    bridge.synthetic.data["files"] = {"11": [file_record(**{flag: value})]}
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    assert not any(x["kind"] == "file" for x in result.data["materials"])
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Material).where(Material.kind == "file"))


async def test_T13_fresh_file_denial_clears_any_cached_text(bridge, owner, seeded):
    record = file_record()
    bridge.synthetic.data["files"] = {"11": [record]}
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    ref = result.data["materials"][1]["id"]
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.text, row.locators, row.version_hash = "former text", [{"text": "private"}], "old"
    record["hidden_for_user"] = True
    with pytest.raises(DomainError):
        await fetch_material(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        assert not row.text and not row.locators and not row.version_hash


async def test_T27_missing_file_collection_is_partial_not_empty_success(bridge, owner, seeded):
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    assert result.status == "partial_data"
    assert result.data["inventory_coverage"]["files"] == "partial"
    assert result.data["materials"][0]["kind"] == "page"


async def test_T27_outline_uses_one_budget_for_module_requests(bridge, owner, seeded, monkeypatch):
    original = CanvasClient._get
    bridge.settings.refresh_budget_seconds = 0.5

    async def slow(client, url):
        if "/modules/" in url and "/items?" in url:
            await asyncio.Event().wait()
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", slow)
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    assert result.status == "partial_data"
    assert not result.data["modules"][0]["items_complete"]
    assert result.data["inventory_coverage"]["modules"] == "partial"
    failure = next(iter(result.data["inventory_status"]["module_item_failures"].values()))
    assert failure["reason_code"] == "INVENTORY_BRANCH_TIMEOUT"


async def test_T23_download_strips_all_ambient_auth_and_never_restores_bearer(file_client):
    client, provider = file_client
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"Location": "https://storage.fixture.invalid/object?signature=fictional"},
            )
        if len(requests) == 2:
            return httpx.Response(
                302,
                headers={"Location": "https://canvas.fixture.invalid/files/51/download?second=1"},
            )
        return response(**{"Content-Length": str(len(PDF))})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        auth=("ambient-user", "ambient-secret"),
        headers={"Authorization": "ambient-token", "Referer": "https://private.invalid"},
        cookies={"session": "ambient-cookie"},
    ) as http:
        result = await download_file(client, "11", "51", http=http)
    assert result.data == PDF and result.kind == "pdf"
    assert "PDF" not in repr(result)
    assert requests[0].headers["Authorization"] == "Bearer fixture-only-secret"
    assert all("Authorization" not in r.headers for r in requests[1:])
    assert all("Cookie" not in r.headers and "Referer" not in r.headers for r in requests)
    assert provider.requests[0].url.path == "/api/v1/courses/11/files/51"


async def test_T23_direct_storage_url_never_receives_bearer(file_client):
    client, provider = file_client
    provider.data["files"]["11"][0]["url"] = "https://storage.fixture.invalid/object"

    def handle(request):
        assert "Authorization" not in request.headers
        return response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        assert (await download_file(client, "11", "51", http=http)).data == PDF


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.invalid/object",
        "http://storage.fixture.invalid/object",
        "https://storage.fixture.invalid:444/object",
        "https://user:pass@storage.fixture.invalid/object",
        "https://127.0.0.1/object",
        "https://storage.fixture.invalid.attacker.invalid/object",
        "https://canvas.fixture.invalid/api/v1/users/self/profile",
        "https://canvas.fixture.invalid/files/99/download",
        "https://canvas.fixture.invalid/courses/12/files/51/download",
        "https://canvas.fixture.invalid/files/51/download#fragment",
        "https://storage.fixture.invalid/\\evil",
        "https://storage%2efixture.invalid/object",
        "https://storage.fixture.invalid/\nobject",
    ],
)
async def test_T23_unapproved_redirect_is_not_requested(file_client, destination):
    client, _ = file_client
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": destination})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(DomainError):
            await download_file(client, "11", "51", http=http)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"locked_for_user": True},
        {"hidden_for_user": None},
        {"size": -1},
        {"size": True},
        {"size": 10_000_001},
        {"size": "52"},
        {"content-type": "application/x-msdownload"},
        {"filename": "disguised.exe"},
        {"url": None},
    ],
)
async def test_T23_download_requires_supported_current_metadata(file_client, changes):
    client, provider = file_client
    provider.data["files"]["11"][0].update(changes)

    def unexpected(request):
        pytest.fail("Rejected metadata must not start a download")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        with pytest.raises(DomainError):
            await download_file(client, "11", "51", http=http)


@pytest.mark.parametrize(
    "body,headers",
    [
        (PDF + b"overflow", {}),
        (PDF[:-1], {}),
        (b"x" * len(PDF), {}),
        (PDF, {"Content-Type": "text/html"}),
        (PDF, {"Content-Encoding": "gzip"}),
        (PDF, {"Content-Length": "999"}),
        (PDF, {"Content-Length": "-1"}),
    ],
)
async def test_T23_stream_size_type_and_signature_fail_closed(file_client, body, headers):
    client, _ = file_client
    result = response(body, **headers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: result)) as http:
        with pytest.raises(DomainError):
            await download_file(client, "11", "51", http=http)
    assert result.is_closed


async def test_T23_stream_timeout_closes_body_and_hides_signed_url(file_client):
    client, _ = file_client
    client.settings.refresh_budget_seconds = 0.02
    body = Body(PDF, delay=1)
    result = httpx.Response(200, stream=body, headers={"Content-Type": "application/pdf"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: result)) as http:
        with pytest.raises(DomainError) as error:
            await download_file(client, "11", "51", http=http)
    assert result.is_closed and body.closed
    assert "private-synthetic-value" not in str(error.value)


async def test_T23_download_cancellation_is_propagated_and_closed(file_client):
    client, _ = file_client
    entered = asyncio.Event()

    class WaitingBody(Body):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield PDF

    body = WaitingBody()
    result = httpx.Response(200, stream=body, headers={"Content-Type": "application/pdf"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: result)) as http:
        task = asyncio.create_task(download_file(client, "11", "51", http=http))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert body.closed


async def test_T23_mismatched_file_metadata_never_downloads(file_client, monkeypatch):
    client, _ = file_client

    async def wrong_file(*args, **kwargs):
        return file_record(id=99)

    monkeypatch.setattr(client, "one", wrong_file)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("Unexpected download"))
    ) as http:
        with pytest.raises(DomainError, match="unavailable"):
            await download_file(client, "11", "51", http=http)


async def test_T34_file_kind_survives_backup_without_signed_urls(bridge, owner, seeded, tmp_path):
    from canvas_bridge.lifecycle import backup, restore
    from canvas_bridge.storage import Store

    bridge.synthetic.data["files"] = {"11": [file_record()]}
    _, courses = bridge.selected(owner, seeded)
    await outline(bridge, owner, seeded, courses[0].id)
    path = tmp_path / "fictional.backup"
    backup(bridge, path)
    payload = bridge.vault.open(path.read_text(), "operator", "backup")
    assert "verifier" not in str(payload["tables"]["materials"])
    # Simulate a page record in a backup created before the kind column existed.
    for material in payload["tables"]["materials"]:
        if material["kind"] == "page":
            del material["kind"]
    path.write_text(bridge.vault.seal(payload, "operator", "backup"))
    original = bridge.store
    target = Store("sqlite:///:memory:")
    target.create_fixture_schema()
    bridge.store = target
    try:
        restore(bridge, path, bridge.settings.deletion_journal)
        with target.transaction() as session:
            assert sorted(m.kind for m in session.scalars(select(Material))) == ["file", "page"]
    finally:
        bridge.store = original
        target.close()


@pytest.mark.parametrize("loop", [True, False])
async def test_T23_redirect_count_and_cycle_are_bounded(file_client, loop):
    client, _ = file_client
    requests = []

    def handle(request):
        requests.append(request)
        path = "same" if loop else str(len(requests))
        return httpx.Response(302, headers={"Location": f"https://storage.fixture.invalid/{path}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(DomainError):
            await download_file(client, "11", "51", http=http)
    assert len(requests) == (2 if loop else 4)


@pytest.mark.parametrize(
    "origin",
    [
        "http://files.invalid",
        "https://*.files.invalid",
        "https://files.invalid/path",
        "https://files.invalid:444",
        "https://files.invalid?query",
        "https://user@files.invalid",
        "https://files.invalid/",
        "https://files%2einvalid",
        " https://files.invalid",
    ],
)
def test_T23_download_origins_require_exact_operator_configuration(origin):
    with pytest.raises(ValidationError):
        Institution(id="test", name="Test", status="candidate", download_origins=[origin])


def test_T23_origin_normalization_preserves_exact_host_policy():
    institution = Institution(
        id="test",
        name="Test",
        status="candidate",
        origin="https://CANVAS.fixture.invalid:443/",
        download_origins=["https://STORAGE.fixture.invalid:443", "https://storage.fixture.invalid"],
    )
    assert institution.origin == "https://canvas.fixture.invalid"
    assert institution.download_origins == ["https://storage.fixture.invalid"]
