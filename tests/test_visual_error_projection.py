"""Known renderer diagnostics survive; arbitrary source-bearing errors do not."""

import pytest

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_errors import safe_error_result
from canvas_bridge.visual_files import validate_rendering


@pytest.mark.parametrize(
    "reason",
    [
        "file_size_or_signature",
        "invalid_page_or_rotation",
        "page_limit_or_range",
        "page_dimensions",
        "image_output_limit",
        "memory_limit",
        "dependency_unavailable",
        "unreadable_or_rendering_limit",
        "active_or_external_content",
        "conversion_failed",
        "conversion_page_mismatch",
        "render_timeout",
        "pptx_expansion_limit",
        "image_resource_limit",
        "unsupported_slide_media",
        "unknown_reason",
    ],
)
def test_renderer_fixed_errors_survive_without_source_details(reason):
    with pytest.raises(DomainError) as error:
        validate_rendering({"ok": False, "reason": reason}, b"synthetic", {"kind": "pdf"})
    exc = error.value
    projected = safe_error_result(
        Result(
            status=exc.status,
            summary="SECRET SOURCE",
            data={
                **exc.data,
                "source_text": "SECRET SOURCE",
                "url": "https://fixture.invalid/?token=SECRET",
            },
        )
    )
    assert projected.data["reason_code"] == exc.reason_code
    assert projected.data["processing_stage"] == "page_rendering"
    assert "SECRET" not in projected.model_dump_json()


def test_native_image_validation_rejects_hidden_png_metadata():
    import base64
    import hashlib
    import io

    from PIL import Image, PngImagePlugin

    from canvas_bridge.visual_worker import RENDERER

    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("memo", "PRIVATE mark")
    Image.new("RGB", (2, 2)).save(out, format="PNG", pnginfo=info)
    png = out.getvalue()
    result = {
        "renderer": RENDERER,
        "page": 1,
        "page_count": 1,
        "rotation": 0,
        "pixels": [2, 2],
        "image_hash": hashlib.sha256(png).hexdigest(),
        "content_hash": hashlib.sha256(b"source").hexdigest(),
        "png": base64.b64encode(png).decode(),
    }
    with pytest.raises(DomainError) as caught:
        validate_rendering({"ok": True, "rendering": result}, b"source", {"page": 1, "rotation": 0})
    assert caught.value.reason_code == "RENDER_IMAGE_INVALID"
    assert "PRIVATE" not in str(caught.value.data)


def test_unreviewed_render_reason_remains_redacted():
    projected = safe_error_result(
        Result(
            status="partial_data",
            summary="SECRET",
            data={
                "reason_code": "RENDER_SECRET_SOURCE",
                "processing_stage": "SECRET",
            },
        )
    )
    assert projected.data == {"reason_code": "EGRESS_ERROR_REDACTED"}
    assert "SECRET" not in projected.model_dump_json()


@pytest.mark.parametrize("count", [None, False, 0])
def test_unknown_count_and_conversion_failure_do_not_disclose_ranges(count):
    from canvas_bridge.presentation_derivatives import validate_derivative

    for reason, code in (
        ("document_range_out_of_bounds", "DOCUMENT_LENGTH_UNAVAILABLE"),
        ("conversion_failed", "PPTX_CONVERSION_FAILED"),
    ):
        with pytest.raises(DomainError) as caught:
            validate_derivative(
                dict(ok=False, reason=reason, page_count=count, stderr="SECRET"), b"", b"", 3
            )
        assert caught.value.reason_code == code
        public = safe_error_result(
            Result(status=caught.value.status, summary="SECRET", data=caught.value.data)
        )
        assert not public.sources and "page_count" not in public.data
        assert "SECRET" not in public.model_dump_json()


@pytest.mark.parametrize(
    "code,status,first",
    [
        ("EGRESS_CLASSIFICATION_UNKNOWN", "permission_denied", 8),
        ("RESOURCE_PERMISSION_DENIED", "permission_denied", 8),
        ("UNREVIEWED_PRIVATE_REASON", "operation_failed", 8),
        ("DOCUMENT_RANGE_OUT_OF_BOUNDS", "needs_input", "SECRET"),
        ("DOCUMENT_RANGE_OUT_OF_BOUNDS", "needs_input", True),
    ],
)
def test_surface_only_emits_bounds_for_known_numeric_range_error(code, status, first):
    result = safe_error_result(
        Result(
            status=status,
            summary="SECRET",
            data={
                "reason_code": code,
                "page_start": first,
                "page_end": 8,
                "page_count": 7,
                "text": "SECRET",
                "slides": ["SECRET"],
                "debug_path": "SECRET",
            },
        )
    )
    assert not {"page_start", "page_end", "page_count", "text", "slides"} & result.data.keys()
    assert "SECRET" not in result.model_dump_json() and not result.sources
    assert result.data["reason_code"] == (
        "EGRESS_ERROR_REDACTED" if code.startswith("UNREVIEWED") else code
    )
