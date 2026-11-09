"""Synthetic proof of bounded resolution fallback, never permission recovery."""

import pytest

from canvas_bridge import visual_files
from canvas_bridge.domain import DomainError


async def test_pdf_output_limit_uses_only_existing_standard_resolution(monkeypatch):
    calls = []

    async def render(data, settings, page, rotation, *, max_edge=2400):
        calls.append((data, page, rotation, max_edge))
        if max_edge == 2400:
            raise DomainError(
                "unsupported_feature", "Fixed", reason_code="RENDER_IMAGE_OUTPUT_LIMIT"
            )
        return {"pixels": [1600, 1200]}

    monkeypatch.setattr(visual_files, "render_document", render)
    result, fallback = await visual_files.render_pdf_with_fallback(b"synthetic", None, 3, 90)
    assert fallback and result["pixels"] == [1600, 1200]
    assert calls == [(b"synthetic", 3, 90, 2400), (b"synthetic", 3, 90, 1600)]


@pytest.mark.parametrize(
    "code,expected",
    [
        ("RENDER_IMAGE_OUTPUT_LIMIT", [2400, 1600]),
        ("RENDER_MEMORY_LIMIT", [2400]),
        ("RESOURCE_PERMISSION_DENIED", [2400]),
    ],
)
async def test_pdf_fallback_is_bounded_and_other_failures_remain_denied(
    monkeypatch, code, expected
):
    calls = []

    async def render(data, settings, page, rotation, *, max_edge=2400):
        calls.append(max_edge)
        raise DomainError(
            "permission_denied" if code == "RESOURCE_PERMISSION_DENIED" else "unsupported_feature",
            "Fixed",
            reason_code=code,
        )

    monkeypatch.setattr(visual_files, "render_document", render)
    with pytest.raises(DomainError) as error:
        await visual_files.render_pdf_with_fallback(b"synthetic", None, 1, 0)
    assert error.value.reason_code == code
    assert calls == expected
