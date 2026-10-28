"""Sectioned synthetic decks and file/version-bound diagnostic evidence."""

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_bridge.course_files import ocr_configuration
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.file_download import file_version
from canvas_bridge.parser_worker import PARSER, extract
from canvas_bridge.presentation_derivatives import validate_derivative
from canvas_bridge.presentation_pipeline import render_slide, text_fallback
from canvas_bridge.presentation_subset import single_slide
from canvas_bridge.presentation_worker import Package
from canvas_bridge.visual_delivery import image_response
from tests.test_presentation_reading import presentation as presentation
from tests.test_presentation_rendering import (
    synthetic_render_transport as synthetic_render_transport,
)
from tests.test_presentation_subset import changed, fixture_bytes


def sectioned_deck():
    # Section IDs have no r:id, and can have a different order from the deck.
    extension = b'<p:extLst><p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"><p14:sectionLst xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"><p14:section name="Synthetic section" id="{00000000-0000-0000-0000-000000000001}"><p14:sldIdLst><p14:sldId id="258"/><p14:sldId id="256"/><p14:sldId id="257"/></p14:sldIdLst></p14:section></p14:sectionLst></p:ext></p:extLst>'
    return changed(
        fixture_bytes(),
        "ppt/presentation.xml",
        lambda raw: raw.replace(b"</p:presentation>", extension + b"</p:presentation>"),
    )


def test_sections_do_not_change_order_count_or_hidden_slides(tmp_path):
    data = sectioned_deck()
    data = changed(data, "ppt/slides/slide3.xml", lambda r: r.replace(b'show="0"', b'show="false"'))
    original = extract(fixture_bytes(), "pptx")
    parsed = extract(data, "pptx")
    assert parsed["page_count"] == 3
    assert [p["text"] for p in parsed["pages"]] == [p["text"] for p in original["pages"]]
    assert parsed["pages"][2]["hidden"] is True
    output = tmp_path / "one.pptx"
    result = single_slide(data, 3, output)
    assert result["source_slide_count"] == 3 and result["hidden"]
    with Package(output.read_bytes()) as package:
        assert package.slide_paths() == ["ppt/slides/slide3.xml"]
        assert b"sectionLst" not in package.read("ppt/presentation.xml")


@pytest.mark.skipif(
    os.name != "nt" or not os.getenv("BRIDGE_TEST_OFFICE_ROOT"),
    reason="Explicit trusted native converter runtime required",
)
def test_sectioned_deck_in_native_sandbox(tmp_path):
    from canvas_bridge.parser_sandbox import extract_isolated

    root = Path(os.environ.get("BRIDGE_TEST_PARSER_ROOT", str(tmp_path)))
    data = sectioned_deck()
    parsed = extract_isolated(data, "pptx", root)
    assert parsed["page_count"] == 3 and len(parsed["pages"]) == 3
    manifest, pdf = extract_isolated(
        data,
        "pptx",
        root,
        presentation_root=Path(os.environ["BRIDGE_TEST_OFFICE_ROOT"]),
        visual={"page": 2, "rotation": 0, "conversion_only": True},
    )
    assert manifest["source_slide_count"] == 3 and manifest["pdf_page_count"] == 1
    assert manifest["slide_to_page"] == [{"source_slide": 2, "pdf_page": 1, "hidden": False}]
    image = extract_isolated(pdf, "pdf", root, visual={"page": 1, "rotation": 0})
    assert image["png"] and image["image_hash"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_id",
        "wrong_id_namespace",
        "duplicate",
        "missing_list",
        "second_list",
        "foreign_child",
    ],
)
def test_malformed_real_slide_lists_still_fail_closed(mutation):
    from defusedxml.minidom import parseString

    def change(raw):
        with parseString(raw) as dom:
            listing = dom.getElementsByTagName("p:sldIdLst")[0]
            entry = listing.getElementsByTagName("p:sldId")[0]
            if mutation == "missing_id":
                entry.removeAttribute("r:id")
            elif mutation == "wrong_id_namespace":
                value = entry.getAttribute("r:id")
                entry.removeAttribute("r:id")
                entry.setAttribute("xmlns:x", "urn:untrusted")
                entry.setAttribute("x:id", value)
            elif mutation == "duplicate":
                listing.appendChild(entry.cloneNode(deep=True))
            elif mutation == "missing_list":
                listing.parentNode.removeChild(listing)
            elif mutation == "second_list":
                listing.parentNode.appendChild(listing.cloneNode(deep=True))
            else:
                listing.appendChild(dom.createElementNS("urn:untrusted", "sldId"))
            return dom.toxml(encoding="utf-8")

    data = changed(sectioned_deck(), "ppt/presentation.xml", change)
    with pytest.raises(ValueError, match="invalid_slide_reference"):
        extract(data, "pptx")


@pytest.mark.parametrize(
    "target",
    [
        "../../../escape.xml",
        "file:///secret",
        "https://untrusted.invalid/a",
        "slides/missing.xml",
        "%2e%2e/%2e%2e/secret",
        "slides/slide1.xml#fragment",
    ],
)
def test_unsafe_or_absent_slide_targets_still_fail_closed(target):
    data = changed(
        sectioned_deck(),
        "ppt/_rels/presentation.xml.rels",
        lambda r: r.replace(b'Target="slides/slide1.xml"', f'Target="{target}"'.encode()),
    )
    with pytest.raises(ValueError, match="invalid_slide_reference"):
        extract(data, "pptx")


def test_conversion_worker_preserves_sanitized_package_reason(tmp_path, monkeypatch):
    from canvas_bridge.presentation_render_worker import main

    data = changed(
        sectioned_deck(),
        "ppt/_rels/presentation.xml.rels",
        lambda r: r.replace(b"slides/slide1.xml", b"slides/absent.xml"),
    )
    (tmp_path / "input.bin").write_bytes(data)
    (tmp_path / "request.json").write_text(
        json.dumps({"page": 1, "rotation": 0, "office_root": "unused", "conversion_only": True})
    )
    monkeypatch.setattr("sys.argv", ["worker", str(tmp_path)])
    main()
    result = json.loads((tmp_path / "result.json").read_text())
    assert result == {"ok": False, "reason": "invalid_slide_reference"}
    with pytest.raises(DomainError) as caught:
        validate_derivative(result, data, b"")
    assert caught.value.reason_code == "PPTX_INVALID_SLIDE_REFERENCE"
    assert "remains available" not in caught.value.message


@pytest.mark.parametrize(
    "state,expected",
    [
        ("failed", "failed"),
        ("parsed", "available"),
        ("old_version", "not_checked"),
        ("old_parser", "not_checked"),
        ("expired", "not_checked"),
        ("empty", "failed"),
        ("unreadable", "failed"),
        ("absent", "failed"),
    ],
)
def test_text_fallback_requires_current_usable_slide_evidence(settings, state, expected):
    metadata = {"id": 51, "size": 100, "updated_at": "2026-10-23T00:00:00Z"}
    row = SimpleNamespace(
        id="synthetic",
        version_hash="a" * 64,
        retrieved_at=utcnow(),
        locators=[{"page": 1, "state": "extracted", "text": "Synthetic text"}],
        file_state={
            "version": file_version(metadata),
            "parser": PARSER,
            "stage": "parsed",
            "format": "pptx",
            "source_byte_limit": settings.pptx_source_max_bytes,
            "ocr_enabled": bool(settings.ocr_root),
            "ocr_configuration": ocr_configuration(settings),
            "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    if state == "failed":
        row.file_state.update(
            stage="failed",
            reason_code="EXTRACTION_INVALID_SLIDE_REFERENCE",
            processing_stage="text_extraction",
        )
    elif state == "old_version":
        row.file_state["version"] = "old"
    elif state == "old_parser":
        row.file_state["parser"] = "old"
    elif state == "expired":
        row.file_state["expires_at"] = (utcnow() - timedelta(hours=1)).isoformat()
    elif state == "empty":
        row.locators[0].update(text="", state="no_text")
    elif state == "unreadable":
        row.locators[0]["state"] = "unreadable"
    elif state == "absent":
        row.locators = []
    result = text_fallback(row, metadata, settings, 1)
    assert result["status"] == expected
    if state == "failed":
        assert result["reason_code"] == "EXTRACTION_INVALID_SLIDE_REFERENCE"


async def test_success_cache_and_failure_keep_server_stage_evidence(
    bridge, owner, seeded, presentation, synthetic_render_transport, monkeypatch
):
    import canvas_bridge.presentation_pipeline as pipeline

    for _ in range(2):
        result, png = await render_slide(bridge, owner, seeded, presentation, 1)
        response = image_response(result, png, bridge.settings)
        stages = response.structuredContent["data"]["visual_pipeline"]
        assert all(
            stages[k]["status"] == "established"
            for k in ("source_authorized", "source_retrieved", "page_rendered")
        )
        assert all(
            stages[k]["status"] == "unknown"
            for k in (
                "image_delivered_to_host",
                "image_visible_to_model",
                "visual_interpretation_completed",
                "interpretation_verified",
            )
        )
    assert stages["source_retrieved"]["evidence"] == "version_checked_cached_derivative"

    async def fail(*args):
        validate_derivative({"ok": False, "reason": "invalid_slide_reference"}, b"", b"")

    monkeypatch.setattr(pipeline, "convert_document", fail)
    with pytest.raises(DomainError) as caught:
        await render_slide(bridge, owner, seeded, presentation, 2)
    stages = caught.value.data["visual_pipeline"]
    assert (
        stages["source_authorized"]["status"]
        == stages["source_retrieved"]["status"]
        == "established"
    )
    assert stages["page_rendered"]["status"] == "unknown"
    assert caught.value.data["text_fallback"]["status"] == "not_checked"
    assert "has not been checked" in caught.value.message


async def test_render_error_reports_cached_extraction_failure(
    bridge, owner, seeded, presentation, synthetic_render_transport, monkeypatch
):
    from canvas_bridge.course_files import authorized
    from canvas_bridge.storage import Material

    _, _, metadata, _ = await authorized(bridge, owner, seeded, presentation)
    with bridge.store.transaction() as session:
        row = session.get(Material, presentation)
        row.file_state = {
            "stage": "failed",
            "parser": PARSER,
            "version": file_version(metadata),
            "reason_code": "EXTRACTION_INVALID_SLIDE_REFERENCE",
            "processing_stage": "text_extraction",
        }

    async def fail(*args):
        validate_derivative({"ok": False, "reason": "invalid_slide_reference"}, b"", b"")

    monkeypatch.setattr("canvas_bridge.presentation_pipeline.convert_document", fail)
    with pytest.raises(DomainError) as caught:
        await render_slide(bridge, owner, seeded, presentation, 1)
    assert caught.value.data["text_fallback"]["status"] == "failed"
    assert "EXTRACTION_INVALID_SLIDE_REFERENCE" in caught.value.message
    assert "available" not in caught.value.message
