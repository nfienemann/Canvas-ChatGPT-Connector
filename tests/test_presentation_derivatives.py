"""Derivative lifecycle and source binding. Converter substitutes are explicit."""

import asyncio
import copy
import hashlib

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.presentation_derivatives import Derivatives, validate_derivative
from canvas_bridge.presentation_pipeline import render_slide
from canvas_bridge.presentation_render_worker import validate_svg
from tests.test_presentation_reading import presentation as presentation
from tests.test_presentation_rendering import (
    synthetic_render_transport as synthetic_render_transport,
)


@pytest.mark.parametrize(
    "svg",
    [
        "<svg><script>bad</script></svg>",
        '<svg><use href="https://untrusted.invalid/figure"/></svg>',
        '<svg><style>@import "remote";</style></svg>',
        '<svg><path style="fill:url(file:///private)"/></svg>',
        '<svg onload="bad"/>',
        "<svg><foreignObject/></svg>",
    ],
)
def test_svg_rejects_active_or_external_content(svg):
    from defusedxml import ElementTree as ET

    with pytest.raises(ValueError, match="active_or_external_content"):
        validate_svg(ET.fromstring(svg))


def test_static_svg_embedded_diagram_is_supported():
    from defusedxml import ElementTree as ET

    validate_svg(
        ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs><path d="M0,0L10,10" fill="url(#g)"/><text>synthetic</text></svg>'
        )
    )


async def test_cache_reuses_conversion_but_not_authorization(
    bridge, owner, seeded, presentation, synthetic_render_transport, monkeypatch
):
    import canvas_bridge.presentation_pipeline as pipeline

    original, calls = pipeline.convert_document, []

    async def tracked(*args):
        calls.append(1)
        return await original(*args)

    monkeypatch.setattr(pipeline, "convert_document", tracked)
    a, b = await asyncio.gather(
        render_slide(bridge, owner, seeded, presentation, 2),
        render_slide(bridge, owner, seeded, presentation, 3),
    )
    assert len(calls) == 2
    assert not a[0].data["cache_hit"] and not b[0].data["cache_hit"]
    again, _ = await render_slide(bridge, owner, seeded, presentation, 2)
    assert len(calls) == 2 and again.data["cache_hit"]
    assert again.data["rendered_page"] == 1 and again.data["page_count"] == 17
    assert len(bridge.presentation_derivatives.records) == 2
    with pytest.raises(DomainError) as other_owner:
        await render_slide(bridge, "unrelated-owner", seeded, presentation, 2)
    assert other_owner.value.status in {"permission_denied", "reconnect_required"}
    assert len(calls) == 2
    assert b[0].data["hidden_slide"]
    assert b[0].data["source_content_hash"] != b[0].data["derivative_content_hash"]
    assert b[0].sources[0].locator == "Slide 3"
    events = {e["stage"]: e for e in a[0].data["pipeline_events"]}
    for stage in ("model_visibility", "visual_interpretation", "image_delivery"):
        assert events[stage]["result"] == "not_attempted"
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError) as revoked:
        await render_slide(bridge, owner, seeded, presentation, 2)
    assert revoked.value.status == "permission_denied"
    assert not bridge.presentation_derivatives.records


async def test_changed_version_invalidates_derivative_and_wrong_slide_is_typed(
    bridge, owner, seeded, presentation, synthetic_render_transport
):
    await render_slide(bridge, owner, seeded, presentation, 2)
    bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-24T00:00:00Z"
    result, _ = await render_slide(bridge, owner, seeded, presentation, 2)
    assert not result.data["cache_hit"]
    assert len(bridge.presentation_derivatives.records) == 1
    with pytest.raises(DomainError) as absent:
        await render_slide(bridge, owner, seeded, presentation, 18)
    assert absent.value.reason_code == "INVALID_SLIDE"


async def test_post_render_permission_denial_and_version_change_never_return_cached_pixels(
    bridge, owner, seeded, presentation, synthetic_render_transport, monkeypatch
):
    import canvas_bridge.visual_files as visual

    await render_slide(bridge, owner, seeded, presentation, 1)
    original = visual.render_document

    async def revoked(*args, **kwargs):
        result = await original(*args, **kwargs)
        bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
        return result

    monkeypatch.setattr(visual, "render_document", revoked)
    with pytest.raises(DomainError) as denied:
        await render_slide(bridge, owner, seeded, presentation, 1)
    assert denied.value.status == "permission_denied"
    assert not bridge.presentation_derivatives.records


async def test_conversion_manifest_hash_mapping_and_pdf_checks(bridge, synthetic_render_transport):
    from canvas_bridge.presentation_pipeline import convert_document

    data = b"synthetic source"
    d, pdf = await convert_document(data, bridge.settings, 2)
    for key, value in (
        ("source_content_hash", "0" * 64),
        ("derivative_content_hash", "0" * 64),
        ("pdf_page_count", 16),
        ("pdf_bytes", 0),
        ("selected_slide", 3),
        ("source_slide_count", 1),
    ):
        bad = copy.deepcopy(d)
        bad[key] = value
        with pytest.raises(ValueError):
            validate_derivative({"ok": True, "derivative": bad}, data, pdf, 2)
    bad = copy.deepcopy(d)
    bad["slide_to_page"][0]["pdf_page"] = 3
    with pytest.raises(ValueError):
        validate_derivative({"ok": True, "derivative": bad}, data, pdf, 2)
    corrupt = b"invalid pdf"
    bad = copy.deepcopy(d)
    bad.update(pdf_bytes=len(corrupt), derivative_content_hash=hashlib.sha256(corrupt).hexdigest())
    with pytest.raises(ValueError):
        validate_derivative({"ok": True, "derivative": bad}, data, corrupt, 2)


@pytest.mark.parametrize(
    "reason,code",
    [
        ("render_timeout", "PPTX_CONVERSION_TIMEOUT"),
        ("conversion_page_mismatch", "PPTX_SLIDE_MAPPING_UNCERTAIN"),
        ("memory_limit", "SLIDE_RENDER_RESOURCE_LIMIT"),
        ("conversion_invalid_pdf", "PPTX_DERIVATIVE_INVALID"),
    ],
)
def test_conversion_failures_keep_distinct_stages(reason, code):
    with pytest.raises(DomainError) as caught:
        validate_derivative({"ok": False, "reason": reason}, b"", b"")
    assert caught.value.reason_code == code
    assert caught.value.processing_stage == "pptx_conversion"


def test_cache_isolation_ttl_epoch_capacity_and_shutdown(monkeypatch):
    cache = Derivatives()
    key = ("owner", "connection", "file", 0, "version", "engine", 2)
    cache.put(key, {"source_content_hash": "x"}, b"pdf")
    for index in range(7):
        other = list(key)
        other[index] = "different"
        assert cache.get(tuple(other)) is None
    cache.put(key, {}, b"pdf")
    item = cache.records[key]
    monkeypatch.setattr(
        "canvas_bridge.presentation_derivatives.time.monotonic", lambda: item.created + 601
    )
    assert cache.get(key) is None
    for i in range(5):
        cache.put(("o", "c", str(i), 0, "v", "e", 1), {}, b"pdf")
    assert len(cache.records) == 4
    cache.close()
    assert not cache.records
