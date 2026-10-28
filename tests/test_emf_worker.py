"""Generated synthetic metafiles only. No course data or embedded real PDFs."""

import io
import os
import struct
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from canvas_bridge.emf_worker import prepare_emf
from canvas_bridge.presentation_render_worker import UnsupportedMedia, convert
from canvas_bridge.presentation_subset import single_slide
from canvas_bridge.presentation_worker import Package
from tests.test_presentation_subset import changed, fixture_bytes


def words(*values):
    return struct.pack("<" + "I" * len(values), *values)


def record(kind, data=b""):
    return words(kind, 8 + len(data)) + data


def plus(kind, flags=0, data=b""):
    return struct.pack("<HHII", kind, flags, 12 + len(data), len(data)) + data


def envelope(body, width=2, height=1, *, count=None, short_eof=False):
    header = bytearray(108)
    struct.pack_into(
        "<II4i4iIIIIHH",
        header,
        0,
        1,
        108,
        0,
        0,
        width - 1,
        height - 1,
        0,
        0,
        width * 25,
        height * 25,
        0x464D4520,
        0x10000,
        0,
        0,
        8,
        0,
    )
    struct.pack_into("<4i", header, 72, 1920, 1080, 500, 300)
    eof = record(14, words(0, 0) if short_eof else words(0, 16, 20))
    struct.pack_into(
        "<II", header, 48, len(header) + sum(map(len, body)) + len(eof), count or len(body) + 2
    )
    return bytes(header) + b"".join(body) + eof


def bitmap_emf(*, alternate=False, short_eof=False):
    stream = b"".join(
        [
            plus(0x4001, 1, words(0xDBC01002, 1, 96, 96)),
            plus(0x4030, 2, struct.pack("<f", 1)),
            plus(0x4009, 0, words(0x00FFFFFF)),
            plus(0x4023),
            plus(0x4008, 0x800, words(0xDBC01002, 0, 0, 0xFFFFFFFF, 0, 0)),
            plus(
                0x4008,
                0x501,
                words(0xDBC01002, 1, 2, 1, 8, 0x000E200B, 0)
                + bytes([0, 0, 128, 128, 255, 0, 0, 255]),
            ),
            plus(0x401A, 1, words(0, 2) + struct.pack("<8f", 0, 0, 2, 1, 0, 0, 2, 1)),
            plus(0x4002),
        ]
    )
    body = [record(70, words(4 + len(stream)) + b"EMF+" + stream)]
    if alternate:
        payload = b"%PDF-1.3\nSynthetic alternative /JavaScript never parsed.\n"
        comment = (
            b"GDIC" + words(0x40000004, 0, 0, 0, 0, 1, 0x50444620, 0, len(payload), 44) + payload
        )
        body.append(record(70, words(len(comment)) + comment + bytes((-len(comment)) % 4)))
    return envelope(body, count=3, short_eof=short_eof)


def vector_emf():
    return envelope(
        [
            record(33),
            record(39, words(1, 0, 0x000000FF, 0)),
            record(37, words(1)),
            record(43, words(0, 0, 99, 49)),
            record(37, words(0x80000000)),
            record(40, words(1)),
            record(34, words(0xFFFFFFFF)),
        ],
        100,
        50,
    )


@pytest.mark.parametrize("alternate,short", [(False, False), (True, False), (True, True)])
def test_bitmap_preserves_channels_alpha_and_discards_alternative(alternate, short):
    source = bitmap_emf(alternate=alternate, short_eof=short)
    extension, result = prepare_emf(source)
    assert extension == "png" and b"%PDF" not in result
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (2, 1)
        assert list(image.get_flattened_data()) == [(255, 0, 0, 128), (0, 0, 255, 255)]


def test_vector_is_preserved_after_validation():
    raw = vector_emf()
    assert prepare_emf(raw) == ("emf", raw)


def test_every_truncation_is_rejected():
    for source in (vector_emf(), bitmap_emf(alternate=True, short_eof=True)):
        for length in range(len(source)):
            with pytest.raises(ValueError, match="unsupported_slide_media"):
                prepare_emf(source[:length])


def test_metafile_disguised_as_png_is_not_passed_to_native(tmp_path, monkeypatch):
    with zipfile.ZipFile(io.BytesIO(fixture_bytes())) as archive:
        media = next(
            n for n in archive.namelist() if n.startswith("ppt/media/") and n.endswith(".png")
        )
    data = changed(fixture_bytes(), media, lambda _: vector_emf())

    def forbidden(*args, **kwargs):
        pytest.fail("Native conversion must never run")

    monkeypatch.setattr("canvas_bridge.presentation_render_worker.convert_native", forbidden)
    with pytest.raises(UnsupportedMedia):
        convert(tmp_path, data, 1, 0, tmp_path)


@pytest.mark.parametrize(
    "offset,value",
    [
        (0, 2),
        (4, 104),
        (16, 50000),
        (40, 0),
        (48, 0),
        (52, 500),
        (56, 0),
        (60, 50000),
        (88, 1),
        (92, 108),
        (96, 1),
        (112, 0),
        (112, 0xFFFFFFFC),
    ],
)
def test_bad_headers_counts_dimensions_and_record_bounds_fail(offset, value):
    raw = bytearray(vector_emf())
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(ValueError, match="unsupported_slide_media"):
        prepare_emf(bytes(raw))


@pytest.mark.parametrize("kind", [70, 77, 80, 98, 102, 105, 110, 112, 122, 0xFFFFFFFF])
def test_opaque_comments_escapes_opengl_bitmaps_profiles_and_unknown_records_fail(kind):
    with pytest.raises(ValueError, match="unsupported_slide_media"):
        prepare_emf(envelope([record(kind, words(0, 0))]))


@pytest.mark.parametrize(
    "mutation",
    [
        "stride",
        "pixel_format",
        "image_id",
        "transform",
        "continued_object",
        "pdf_offset",
        "pdf_size",
        "source_crop",
    ],
)
def test_unsupported_bitmap_variants_fail(mutation):
    raw = bytearray(bitmap_emf(alternate=True, short_eof=True))
    marker = raw.index(struct.pack("<HH", 0x4008, 0x501))
    if mutation == "stride":
        struct.pack_into("<I", raw, marker + 28, 0xFFFFFFF8)
    elif mutation == "pixel_format":
        struct.pack_into("<I", raw, marker + 32, 0)
    elif mutation == "image_id":
        struct.pack_into("<H", raw, marker + 2, 0x540)
    elif mutation == "continued_object":
        struct.pack_into("<H", raw, marker + 2, 0x8501)
    elif mutation == "transform":
        at = raw.index(struct.pack("<HH", 0x4030, 2))
        struct.pack_into("<f", raw, at + 12, float("nan"))
    elif mutation == "source_crop":
        at = raw.index(struct.pack("<HH", 0x401A, 1))
        struct.pack_into("<f", raw, at + 28, 1)
    else:
        at = raw.index(b"GDIC")
        struct.pack_into("<I", raw, at + (40 if mutation == "pdf_offset" else 36), 0xFFFFFFF0)
    with pytest.raises(ValueError, match="unsupported_slide_media"):
        prepare_emf(bytes(raw))


def emf_deck(raw):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(fixture_bytes())) as original,
        zipfile.ZipFile(output, "w") as target,
    ):
        media = next(
            n for n in original.namelist() if n.startswith("ppt/media/") and n.endswith(".png")
        )
        replacement = media + ".emf"
        for name in original.namelist():
            data = original.read(name)
            if name == media:
                name, data = replacement, raw
            elif name.endswith(".rels"):
                data = data.replace(
                    media.rsplit("/", 1)[-1].encode(), replacement.rsplit("/", 1)[-1].encode()
                )
            elif name == "[Content_Types].xml":
                data = data.replace(
                    b"</Types>", b'<Default Extension="emf" ContentType="image/x-emf"/></Types>'
                )
            target.writestr(name, data)
    return output.getvalue(), replacement


def test_normalized_subset_has_no_original_metafile_or_pdf_and_resolves_targets(tmp_path):
    raw = bitmap_emf(alternate=True)
    data, member = emf_deck(raw)
    _, png = prepare_emf(raw)
    path = tmp_path / "subset.pptx"
    result = single_slide(data, 2, path, media_replacements={member: (member + ".png", png)})
    assert result["normalized_emf_bitmaps"] == 1
    with Package(path.read_bytes()) as package:
        assert member not in package.names and package.read(member + ".png") == png
        assert ("image", member + ".png") in package.relations("ppt/slides/slide2.xml")[0].values()
        assert b"image/png" in package.read("[Content_Types].xml")
    assert b"%PDF" not in path.read_bytes()


def test_unsafe_media_on_unrequested_slide_prevents_native_launch(tmp_path, monkeypatch):
    data, _ = emf_deck(envelope([record(105, words(0, 0))]))

    def forbidden(*args, **kwargs):
        pytest.fail("Native conversion must never run")

    monkeypatch.setattr("canvas_bridge.presentation_render_worker.convert_native", forbidden)
    with pytest.raises(UnsupportedMedia):
        convert(tmp_path, data, 1, 0, tmp_path)
    assert not (tmp_path / "input.pptx").exists()


@pytest.mark.skipif(
    os.name != "nt" or not os.getenv("BRIDGE_TEST_OFFICE_ROOT"),
    reason="Explicit trusted native converter runtime required",
)
@pytest.mark.parametrize("source", [bitmap_emf(alternate=True, short_eof=True), vector_emf()])
def test_synthetic_emf_in_native_sandbox(tmp_path, source):
    from canvas_bridge.parser_sandbox import extract_isolated

    data, _ = emf_deck(source)
    root = Path(os.environ.get("BRIDGE_TEST_PARSER_ROOT", str(tmp_path)))
    manifest, pdf = extract_isolated(
        data,
        "pptx",
        root,
        presentation_root=Path(os.environ["BRIDGE_TEST_OFFICE_ROOT"]),
        visual={"page": 2, "rotation": 0, "conversion_only": True},
    )
    assert manifest["pdf_page_count"] == 1
    result = extract_isolated(pdf, "pdf", root, visual={"page": 1, "rotation": 0})
    assert result["png"] and result["image_hash"]
