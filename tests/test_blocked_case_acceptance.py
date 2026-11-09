"""Negative controls for the disposable UI and independent slide delivery.

No automated request records a successful human acknowledgment.
"""

import asyncio
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.presentation_render_worker import convert, validate_excluded_workbook
from canvas_bridge.presentation_worker import Package
from canvas_bridge.storage import IndependentResource
from scripts.run_integrity_acknowledgment_demo import Demo
from tests.test_presentation_rendering import (
    synthetic_render_transport as synthetic_render_transport,
)
from tests.test_presentation_subset import changed
from tests.test_recovery_independence import parsed_locally as parsed_locally

DECK = Path("tests/fixtures/stress-repair/sources/formats/lecture_continuation.pptx")
BOOK = "ppt/embeddings/Microsoft_Excel_Sheet1.xlsx"


def workbook():
    with zipfile.ZipFile(io.BytesIO(DECK.read_bytes())) as archive:
        return archive.read(BOOK)


def test_valid_unselected_workbook_never_reaches_native_converter(tmp_path, monkeypatch):
    class Inspected(Exception):
        pass

    original = DECK.read_bytes()

    def inspect(office, profile, source, output, options):
        with Package(source.read_bytes()) as package:
            assert package.slide_paths() == ["ppt/slides/slide10.xml"]
            assert not any("/embeddings/" in name.lower() for name in package.names)
        assert original == DECK.read_bytes()
        raise Inspected()

    monkeypatch.setattr("canvas_bridge.presentation_render_worker.convert_native", inspect)
    with pytest.raises(Inspected):
        convert(tmp_path, original, 10, 0, tmp_path / "unused")


def test_selected_chart_workbook_remains_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canvas_bridge.presentation_render_worker.convert_native",
        lambda *a, **k: pytest.fail("Embedded workbook reached native converter"),
    )
    with pytest.raises(ValueError, match="active_or_external_content"):
        convert(tmp_path, DECK.read_bytes(), 4, 0, tmp_path / "unused")


@pytest.mark.parametrize("threat", ["external", "macro", "malformed", "nested"])
def test_excluded_workbook_is_still_validated(threat):
    raw = workbook()
    if threat == "malformed":
        raw = b"not a workbook"
    elif threat == "external":
        raw = changed(
            raw,
            "xl/_rels/workbook.xml.rels",
            lambda b: b.replace(b"<Relationship ", b'<Relationship TargetMode="External" ', 1),
        )
    else:
        stream = io.BytesIO(raw)
        with zipfile.ZipFile(stream, "a") as archive:
            archive.writestr(
                "xl/vbaProject.bin" if threat == "macro" else "xl/embeddings/nested.xlsx", b"x"
            )
        raw = stream.getvalue()
    with pytest.raises(ValueError, match="active_or_external_content"):
        validate_excluded_workbook(raw)


async def test_ui_get_and_rejected_posts_never_acknowledge(
    bridge, owner, tmp_path, parsed_locally, monkeypatch
):
    demo = Demo(bridge, owner, tmp_path, "http://127.0.0.1:8766")
    await demo.initialize()

    async def forbidden(*a, **k):
        pytest.fail("Invalid form acknowledged a decision")

    monkeypatch.setattr(bridge.integrity, "acknowledge", forbidden)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=demo.app()), base_url=demo.origin
    ) as client:
        page = await client.get(demo.path)
        assert page.status_code == 200
        assert page.headers["referrer-policy"] == "same-origin"
        assert 'name="acknowledge" value="yes" required' in page.text
        assert " checked" not in page.text
        assert "HttpOnly" in page.headers["set-cookie"]
        assert "SameSite=strict" in page.headers["set-cookie"]
        for origin, fields in [
            ("null", {"csrf": demo.token, "acknowledge": "yes"}),
            ("https://untrusted.invalid", {"csrf": demo.token, "acknowledge": "yes"}),
            (demo.origin, {"csrf": "wrong", "acknowledge": "yes"}),
            (demo.origin, {"csrf": demo.token}),
            (demo.origin, {"csrf": demo.token, "acknowledge": "no"}),
        ]:
            assert (
                await client.post(demo.path, data=fields, headers={"Origin": origin})
            ).status_code == 403
        client.cookies.clear()
        assert (
            await client.post(
                demo.path,
                data={"csrf": demo.token, "acknowledge": "yes"},
                headers={"Origin": demo.origin},
            )
        ).status_code == 403
        assert (
            await client.get(demo.path, headers={"Host": "untrusted.invalid"})
        ).status_code == 403
    assert demo.receipt is None and not (tmp_path / "receipt.json").exists()


async def imported(bridge, owner, **kwargs):
    return await bridge.independent.ingest(
        owner,
        await asyncio.to_thread(DECK.read_bytes),
        DECK.name,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        own_material=True,
        share_text=True,
        **kwargs,
    )


async def test_independent_slides_require_explicit_visual_sharing(
    bridge, owner, parsed_locally, monkeypatch
):
    ident = await imported(bridge, owner)
    monkeypatch.setattr(
        "canvas_bridge.presentation_pipeline.backend_identity",
        lambda s: pytest.fail("Unpermitted source reached converter"),
    )
    with pytest.raises(DomainError) as caught:
        await bridge.independent.render(owner, ident, 10)
    assert caught.value.reason_code == "EGRESS_REVIEW_REQUIRED"


async def test_independent_slides_have_no_unconfigured_renderer_fallback(
    bridge, owner, parsed_locally
):
    ident = await imported(bridge, owner, share_visual=True)
    with pytest.raises(DomainError) as caught:
        await bridge.independent.render(owner, ident, 10)
    assert caught.value.reason_code == "PPTX_RENDERER_UNAVAILABLE"


@pytest.mark.parametrize("change", ["delete", "revoke_visual", "replace"])
async def test_independent_slide_rechecks_before_releasing_pixels(
    bridge, owner, parsed_locally, synthetic_render_transport, monkeypatch, change
):
    from canvas_bridge.visual_files import render_document

    ident = await imported(bridge, owner, share_visual=True)

    async def race(*args, **kwargs):
        pixels = await render_document(*args, **kwargs)
        if change == "delete":
            bridge.independent.delete(owner, ident)
        else:
            with bridge.store.transaction() as database:
                row = database.get(IndependentResource, ident)
                if change == "revoke_visual":
                    row.provenance = {**row.provenance, "share_visual": False}
                else:
                    row.version_hash = "f" * 64
        return pixels

    monkeypatch.setattr("canvas_bridge.visual_files.render_document", race)
    with pytest.raises(DomainError):
        await bridge.independent.render(owner, ident, 10)


def test_acknowledgment_receipt_hashes_resolve_source_path_aliases(monkeypatch):
    import scripts.run_integrity_acknowledgment_demo as demo

    alias = demo.ROOT / "scripts" / ".." / "scripts" / "run_integrity_acknowledgment_demo.py"
    monkeypatch.setattr(demo, "__file__", str(alias))
    hashes = demo.implementation_hashes()
    assert "scripts/run_integrity_acknowledgment_demo.py" in hashes
    assert all(".." not in name for name in hashes)
