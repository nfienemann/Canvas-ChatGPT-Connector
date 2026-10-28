"""Render contract and resource-denial checks. Native success remains a live gate."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.domain import DomainError
from canvas_bridge.presentation_render_worker import convert
from canvas_bridge.visual_files import render_file, validate_rendering
from canvas_bridge.visual_worker import render
from canvas_bridge.windows_sandbox import presentation_disk_usage
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running
from tests.test_presentation_reading import deck
from tests.test_presentation_reading import presentation as presentation


@pytest.mark.skipif(os.name != "nt", reason="Windows public runtime packaging")
def test_office_install_parent_is_public_without_granting_private_cache(tmp_path, monkeypatch):
    from canvas_bridge.presentation_runtime import prepare

    source = tmp_path / "trusted-source"
    (source / "program").mkdir(parents=True)
    for name in ("soffice.bin", "mergedlo.dll", "version.ini"):
        (source / "program" / name).write_bytes(b"synthetic public runtime")
    private = tmp_path / "private-cache"
    runtime = private / "python-runtime"
    runtime.mkdir(parents=True)
    (private / "secret.txt").write_text("synthetic private canary")
    grants = []
    monkeypatch.setattr(
        "canvas_bridge.windows_sandbox.acl", lambda path, *args: grants.append(path)
    )

    installed = prepare(runtime, source)
    assert installed.name == "install"
    assert installed.parent.parent == private
    assert (installed / "program/soffice.bin").is_file()
    assert len(grants) == 1
    assert Path(str(grants[0]).removeprefix("\\\\?\\")) == installed.parent
    assert not (installed.parent / "secret.txt").exists()
    assert prepare(runtime, source) == installed
    assert len(grants) == 1


@pytest.mark.skipif(
    os.name != "nt" or not os.getenv("BRIDGE_TEST_OFFICE_ROOT"),
    reason="Explicit trusted native converter runtime required",
)
@pytest.mark.parametrize("slide", [2, 3])
def test_native_single_slide_hidden_mapping_and_pdf_pixels(tmp_path, slide):
    from canvas_bridge.parser_sandbox import extract_isolated

    root = (
        Path(os.environ["BRIDGE_TEST_PARSER_ROOT"])
        if os.getenv("BRIDGE_TEST_PARSER_ROOT")
        else tmp_path
    )
    data = Path("tests/fixtures/synthetic_visual_slides.pptx").read_bytes()
    if slide == 3:
        from tests.test_presentation_subset import numbered_hidden_slide

        data = numbered_hidden_slide(data)
    manifest, pdf = extract_isolated(
        data,
        "pptx",
        root,
        presentation_root=Path(os.environ["BRIDGE_TEST_OFFICE_ROOT"]),
        visual={"page": slide, "rotation": 0, "conversion_only": True},
    )
    assert manifest["pdf_page_count"] == 1
    assert manifest["source_slide_count"] == 3
    assert manifest["slide_to_page"] == [
        {"source_slide": slide, "pdf_page": 1, "hidden": slide == 3}
    ]
    pixels = extract_isolated(pdf, "pdf", root, visual={"page": 1, "rotation": 0})
    assert pixels["png"] and pixels["image_hash"]
    assert pixels["content_hash"] == manifest["derivative_content_hash"]
    if slide == 3:
        from contextlib import closing

        import pypdfium2 as pdfium

        with (
            pdfium.PdfDocument(pdf) as document,
            closing(document[0]) as page,
            closing(page.get_textpage()) as text,
        ):
            assert text.get_text_range().strip() == "3"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"ppt/embeddings/data.xlsx": b"do not open"}, "active_or_external_content"),
        ({"ppt/media/image.wmf": b"unsupported vector"}, "unsupported_slide_media"),
        (
            {
                "ppt/slides/_rels/slide1.xml.rels": '<Relationships><Relationship Id="x" Type="a/image" TargetMode="External" Target="https://untrusted.invalid/image"/></Relationships>'
            },
            "active_or_external_content",
        ),
        (
            {
                "ppt/theme/_rels/theme1.xml.rels": '<Relationships><Relationship Id="x" Type="a/image" Target="file:///private"/></Relationships>'
            },
            "invalid_slide_reference",
        ),
    ],
)
def test_native_converter_is_never_started_for_active_external_or_unsupported_content(
    tmp_path, monkeypatch, changes, reason
):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe source reached native converter")

    monkeypatch.setattr("canvas_bridge.presentation_render_worker.convert_native", forbidden)
    with pytest.raises(ValueError, match=reason):
        convert(tmp_path, deck(changes=changes), 1, 0, tmp_path / "unused-public-runtime")


def test_corrupt_raster_is_not_silently_rendered_as_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canvas_bridge.presentation_render_worker.convert_native",
        lambda *a, **k: pytest.fail("Corrupt media reached converter"),
    )
    with pytest.raises(OSError):
        convert(
            tmp_path,
            deck(changes={"ppt/media/corrupt.png": b"invalid raster"}),
            1,
            0,
            tmp_path / "unused-public-runtime",
        )


def test_render_budget_failure_never_claims_pixels():
    for reason in ("render_timeout", "image_output_limit", "memory_limit"):
        with pytest.raises(DomainError) as caught:
            validate_rendering({"ok": False, "reason": reason}, b"", {"kind": "pptx"})
        assert caught.value.reason_code == "SLIDE_RENDER_RESOURCE_LIMIT"
        assert caught.value.data["visual_render_status"] == "failed"
        assert not caught.value.data["assistant_pixels_delivered"]


def test_staging_monitor_limits_files_and_bytes(tmp_path):
    large = tmp_path / "synthetic-sparse-output"
    with large.open("wb") as stream:
        stream.truncate(128 * 1024 * 1024 + 1)
    with pytest.raises(DomainError) as caught:
        presentation_disk_usage(tmp_path)
    assert caught.value.data["budget"] == "staging_bytes"
    large.unlink()
    for i in range(2049):
        (tmp_path / str(i)).touch()
    with pytest.raises(DomainError) as caught:
        presentation_disk_usage(tmp_path)
    assert caught.value.data["budget"] == "workspace_entries"


@pytest.fixture
def synthetic_render_transport(bridge, monkeypatch):
    # This proves transport/auth fencing only. It is deliberately NOT evidence
    # that LibreOffice rendered a slide, nor used for scientific-fidelity claims.
    bridge.settings.pptx_rendering_enabled = True
    bridge.settings.pptx_renderer_root = Path("synthetic-unused-public-runtime")
    bridge.settings.parser_root = Path("synthetic-unused-parser")

    from canvas_bridge.presentation_derivatives import validate_derivative
    from canvas_bridge.presentation_render_worker import CONVERTER

    async def fixture(data, settings, slide):
        if slide > 17:
            validate_derivative({"ok": False, "reason": "page_limit_or_range"}, data, b"", slide)
        pdf = scientific_pdf([f"Synthetic transport slide {slide}"])
        result = {
            "converter": CONVERTER,
            "engine_build": "synthetic",
            "source_content_hash": hashlib.sha256(data).hexdigest(),
            "derivative_content_hash": hashlib.sha256(pdf).hexdigest(),
            "pdf_bytes": len(pdf),
            "pdf_page_count": 1,
            "source_slide_count": 17,
            "selected_slide": slide,
            "subset_bytes": 123,
            "subset_members": 4,
            "source_slide_image_references": 1,
            "slide_to_page": [{"source_slide": slide, "pdf_page": 1, "hidden": slide == 3}],
            "mapping_validation": "single_source_slide_hidden_included_one_pdf_page_and_geometry",
            "conversion_ms": 1,
            "warnings": ["Synthetic converter substitute; not native fidelity evidence."],
        }
        return validate_derivative({"ok": True, "derivative": result}, data, pdf, slide), pdf

    async def raster(pdf, settings, page=1, rotation=0, **kwargs):
        return render(pdf, page, rotation, max_edge=kwargs.get("max_edge", 2400))

    monkeypatch.setattr(
        "canvas_bridge.presentation_pipeline.backend_identity", lambda s: "synthetic"
    )
    monkeypatch.setattr("canvas_bridge.presentation_pipeline.convert_document", fixture)
    monkeypatch.setattr("canvas_bridge.visual_files.render_document", raster)


@pytest.mark.skipif(__import__("os").name != "nt", reason="PPTX rendering is Windows-only")
@pytest.mark.contract
async def test_real_mcp_image_transport_has_slide_evidence_and_revokes_access(
    running, token_factory, bridge, seeded, presentation, synthetic_render_transport
):
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "render_course_slide",
                    {"connection_id": seeded, "file_id": presentation, "slide": 2},
                )
                assert result.structuredContent["status"] == "ok"
                data = result.structuredContent["data"]
                assert (
                    data["slide_number"] == 2 and data["visual_observation"] == "not_yet_inspected"
                )
                assert data["assistant_pixel_visibility"] == "not_confirmed_by_server"
                assert result.structuredContent["sources"][0]["locator"] == "Slide 2"
                assert any(block.type == "image" for block in result.content)
                assert "office_root" not in json.dumps(result.structuredContent)
                bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
                denied = await session.call_tool(
                    "render_course_file_page", {"connection_id": seeded, "file_id": presentation}
                )
                assert denied.structuredContent["status"] == "permission_denied"
                assert not any(block.type == "image" for block in denied.content)


@pytest.mark.skipif(__import__("os").name != "nt", reason="PPTX rendering is Windows-only")
async def test_render_rechecks_version_after_worker_and_rejects_old_hash(
    bridge, owner, seeded, presentation, synthetic_render_transport, monkeypatch
):
    with pytest.raises(DomainError) as old:
        await render_file(bridge, owner, seeded, presentation, expected_hash="0" * 64)
    assert old.value.status == "source_changed"
    import canvas_bridge.presentation_pipeline as visual

    original = visual.convert_document

    async def changed(*args, **kwargs):
        value = await original(*args, **kwargs)
        bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-23T00:00:00Z"
        return value

    monkeypatch.setattr(visual, "convert_document", changed)
    with pytest.raises(DomainError) as stale:
        await render_file(bridge, owner, seeded, presentation)
    assert stale.value.status == "source_changed"
