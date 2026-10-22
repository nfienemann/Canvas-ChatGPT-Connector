"""Fixed credential-free PDF rasterizer. Run only inside the document sandbox."""

import base64
import hashlib
import json
import math
import struct
import sys
import zlib
from contextlib import closing
from pathlib import Path

RENDERER = "canvas-bridge-pdf-image-v1"
MAX_PNG = 1_300_000


def png_rgb(bitmap):
    """Encode bounded RGB scanlines; PDF parsing/rendering belongs to PDFium."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = bytes(bitmap.buffer)
    rows = b"".join(
        b"\0" + raw[y * bitmap.stride : y * bitmap.stride + bitmap.width * 3]
        for y in range(bitmap.height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", bitmap.width, bitmap.height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def render(data, page=1, rotation=0, ocr=False):
    import pypdfium2 as pdfium

    if len(data) > 10_000_000 or not data.startswith(b"%PDF-"):
        raise ValueError("file_size_or_signature")
    if type(page) is not int or not 1 <= page <= 200 or rotation not in {0, 90, 180, 270}:
        raise ValueError("invalid_page_or_rotation")
    # No forms, JavaScript, document actions, attachments or external content APIs.
    with pdfium.PdfDocument(data) as document:
        count = len(document)
        if not 1 <= count <= 200 or page > count:
            raise ValueError("page_limit_or_range")
        with closing(document[page - 1]) as pdf_page:
            width, height = pdf_page.get_size()
            if not all(math.isfinite(n) and 1 <= n <= 20_000 for n in (width, height)):
                raise ValueError("page_dimensions")
            with closing(pdf_page.get_textpage()) as textpage:
                chars = textpage.count_chars()
            # Keep the full color table geometry. No destructive thresholding/OCR.
            with closing(
                pdf_page.render(
                    scale=min(2400 / max(width, height), 4),
                    rotation=rotation,
                    may_draw_forms=False,
                    draw_annots=False,
                    rev_byteorder=True,
                    force_bitmap_format=pdfium.raw.FPDFBitmap_BGR,
                    limit_image_cache=True,
                )
            ) as bitmap:
                if ocr:
                    from ocr_worker import recognize

                    recognition = recognize(bitmap)
                    png = b""
                else:
                    png = png_rgb(bitmap)
                pixels = [bitmap.width, bitmap.height]
            if len(png) > MAX_PNG:
                raise ValueError("image_output_limit")
    return {
        "renderer": RENDERER,
        "content_hash": hashlib.sha256(data).hexdigest(),
        "page": page,
        "page_count": count,
        "rotation": rotation,
        "pixels": pixels,
        "image_hash": hashlib.sha256(png).hexdigest(),
        "png": base64.b64encode(png).decode(),
        "text_layer_characters": chars,
        "text_layer_status": "insufficient" if chars < 80 else "present_unverified_quality",
        "interpretation_required": True,
        **({"ocr": recognition} if ocr else {}),
    }


def main():
    work = Path(sys.argv[1])
    try:
        with (work / "input.bin").open("rb") as stream:
            data = stream.read(10_000_001)
        request = json.loads((work / "request.json").read_text(encoding="utf-8"))
        result = {
            "ok": True,
            "rendering": render(
                data, request["page"], request["rotation"], request.get("ocr", False)
            ),
        }
    except Exception as exc:
        allowed = {
            "file_size_or_signature",
            "invalid_page_or_rotation",
            "page_limit_or_range",
            "page_dimensions",
            "image_output_limit",
        }
        reason = (
            "memory_limit"
            if isinstance(exc, MemoryError)
            else "dependency_unavailable"
            if isinstance(exc, ImportError)
            else str(exc)
            if isinstance(exc, ValueError) and str(exc) in allowed
            else "unreadable_or_rendering_limit"
        )
        result = {"ok": False, "reason": reason}
    output = json.dumps(result).encode()
    if len(output) > 2_000_000:
        output = b'{"ok":false,"reason":"image_output_limit"}'
    (work / "result.json").write_bytes(output)


if __name__ == "__main__":
    main()
