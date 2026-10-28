"""Lossless output and unchanged byte budget, using synthetic pixels only."""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from canvas_bridge.visual_worker import MAX_PNG, png_rgb, render
from tests.test_file_reading import scientific_pdf


def test_png_filters_preserve_exact_rgb_pixels_and_ignore_row_padding():
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 17, 81, 203])
    bitmap = SimpleNamespace(
        width=2, height=2, stride=8, buffer=pixels[:6] + b"\x77\x88" + pixels[6:] + b"\x99\xaa"
    )
    with Image.open(io.BytesIO(png_rgb(bitmap))) as result:
        assert result.mode == "RGB" and result.size == (2, 2)
        assert result.tobytes() == pixels


def test_smooth_color_field_compresses_without_changing_any_pixels():
    raw = bytes(c for y in range(256) for x in range(256) for c in (x, y, (x + y) % 256))
    png = png_rgb(SimpleNamespace(width=256, height=256, stride=768, buffer=raw))
    assert len(png) < 10_000
    with Image.open(io.BytesIO(png)) as result:
        assert result.tobytes() == raw


def test_uncompressible_output_still_fails_at_original_cap(monkeypatch):
    assert MAX_PNG == 1_300_000
    monkeypatch.setattr("canvas_bridge.visual_worker.png_rgb", lambda _: bytes(MAX_PNG + 1))
    with pytest.raises(ValueError, match="image_output_limit"):
        render(scientific_pdf(), max_edge=1600)
