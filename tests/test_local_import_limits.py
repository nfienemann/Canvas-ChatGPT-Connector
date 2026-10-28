"""Synthetic import-size boundaries; no private documents or deployed-service claims."""

import hashlib
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from canvas_bridge.academic.cli import run
from canvas_bridge.app import create_app
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.linking import digest
from canvas_bridge.storage import BrowserSession
from tests.test_presentation_reading import MIME, deck
from tests.test_provider_architecture import local
from tests.test_recovery_independence import parsed_locally as parsed_locally


@pytest.fixture
async def import_client(bridge, settings, owner, token_factory):
    with bridge.store.transaction() as session:
        session.add(
            BrowserSession(
                digest=digest("fixture-import-browser"),
                owner=owner,
                credential=bridge.vault.seal({"token": token_factory()}, owner, "browser-session"),
                csrf="fixture-import-csrf",
                expires_at=utcnow() + timedelta(minutes=20),
                generation=0,
            )
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
        cookies={"bridge_session": "fixture-import-browser"},
        headers={
            "Origin": settings.resource_url,
            "X-Bridge-CSRF": "fixture-import-csrf",
            "X-Bridge-Filename": "fictional.PPTX",
            "Content-Type": MIME,
            "X-Bridge-Own": "true",
        },
    ) as client:
        yield client


@pytest.mark.parametrize("size", [10_000_001, 25_000_000, 25_000_001])
async def test_browser_streamed_pptx_size_boundary(
    import_client, bridge, owner, parsed_locally, size
):
    data = deck(target_size=size)

    async def chunks():
        for offset in range(0, size, 1_000_000):
            yield data[offset : offset + 1_000_000]

    response = await import_client.post("/settings/documents/import", content=chunks())
    assert "content-length" not in response.request.headers
    documents = bridge.independent.list(owner).data["documents"]
    if size > 25_000_000:
        assert response.status_code == 403
        assert "exceeds 25 MB" in response.text
        assert documents == []
    else:
        assert response.status_code == 200
        assert len(documents) == 1
        assert documents[0]["content_hash"] == hashlib.sha256(data).hexdigest()
        result = bridge.independent.read(owner, documents[0]["document_id"])
        assert "Methods" in result.data["parts"][0]["text"]
        assert result.sources[0].content_hash == hashlib.sha256(data).hexdigest()


async def test_import_page_advertises_format_limits(import_client):
    response = await import_client.get("/settings/documents")
    assert response.status_code == 200
    assert "PPTX: 25 MB maximum; other formats: 10 MB" in response.text
    assert "25000000:10000000" in response.text


async def test_browser_still_rejects_oversized_non_pptx(import_client, bridge, owner):
    response = await import_client.post(
        "/settings/documents/import",
        content=b"x" * 10_000_001,
        headers={"X-Bridge-Filename": "fictional.txt", "Content-Type": "text/plain"},
    )
    assert response.status_code == 403
    assert "exceeds 10 MB" in response.text
    assert bridge.independent.list(owner).data["documents"] == []


@pytest.mark.parametrize(
    ("kind", "mime", "size"),
    [("pptx", MIME, 25_000_001), ("pdf", "application/pdf", 10_000_001)],
)
async def test_direct_import_cannot_bypass_size_limit(bridge, owner, monkeypatch, kind, mime, size):
    async def forbidden(*args):
        pytest.fail("Oversized import reached the parser")

    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_document", forbidden)
    with pytest.raises(DomainError):
        await bridge.independent.ingest(
            owner, b"x" * size, f"fictional.{kind}", mime, own_material=True
        )
    assert bridge.independent.list(owner).data["documents"] == []


async def test_local_provider_rejects_pptx_above_import_cap():
    provider, request = local(b"x" * 25_000_001)
    provider.kind = "pptx"
    with pytest.raises(DomainError, match="size limits"):
        await provider.get_authorized_document(request)


@pytest.mark.parametrize("size", [25_000_000, 25_000_001])
async def test_offline_cli_and_provider_pptx_boundary(tmp_path, parsed_locally, size):
    path = tmp_path / "fictional.PPTX"
    path.write_bytes(deck(target_size=size))
    args = SimpleNamespace(command="inspect-document", path=path, acknowledge_own_material=True)
    if size > 25_000_000:
        with pytest.raises(DomainError, match="25 MB"):
            await run(args)
    else:
        result = await run(args)
        assert result["documents"][0]["format"] == "pptx"
        assert "Methods" in result["documents"][0]["parts"][0]["text"]


async def test_offline_cli_keeps_non_pptx_limit(tmp_path):
    path = tmp_path / "fictional.txt"
    path.write_bytes(b"x" * 10_000_001)
    with pytest.raises(DomainError, match="10 MB"):
        await run(
            SimpleNamespace(command="inspect-document", path=path, acknowledge_own_material=True)
        )
