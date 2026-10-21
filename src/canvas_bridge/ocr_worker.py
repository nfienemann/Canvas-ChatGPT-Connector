"""Tesseract C API in the existing restricted worker; no child process or URL input."""

import ctypes as C
import os
from pathlib import Path


def recognize(bitmap):
    root = Path(__file__).parent / "ocr"
    if not (root / "tessdata/eng.traineddata").is_file():
        raise RuntimeError("OCR model unavailable")
    handle = os.add_dll_directory(str(root)) if os.name == "nt" else None
    try:
        lib = C.CDLL(str(root / "libtesseract-5.dll") if os.name == "nt" else "libtesseract.so.5")
        signatures = {
            "TessBaseAPICreate": (C.c_void_p, []),
            "TessBaseAPIInit3": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            "TessBaseAPISetPageSegMode": (None, [C.c_void_p, C.c_int]),
            "TessBaseAPISetVariable": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            "TessBaseAPISetImage": (
                None,
                [C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int],
            ),
            "TessBaseAPIGetTsvText": (C.c_void_p, [C.c_void_p, C.c_int]),
            "TessBaseAPIMeanTextConf": (C.c_int, [C.c_void_p]),
            "TessDeleteText": (None, [C.c_void_p]),
            "TessBaseAPIDelete": (None, [C.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
        api = lib.TessBaseAPICreate()
        if not api:
            raise RuntimeError("OCR initialization failed")
        try:
            if lib.TessBaseAPIInit3(api, str(root / "tessdata").encode(), b"eng"):
                raise RuntimeError("OCR model initialization failed")
            lib.TessBaseAPISetVariable(
                api, b"debug_file", b"NUL" if os.name == "nt" else b"/dev/null"
            )
            lib.TessBaseAPISetVariable(api, b"user_defined_dpi", b"220")
            lib.TessBaseAPISetVariable(api, b"thresholding_method", b"0")
            # Sparse text preserves words/coordinates rather than guessing table cell membership.
            lib.TessBaseAPISetPageSegMode(api, 11)
            from PIL import Image, ImageChops, ImageFilter

            image = Image.frombytes(
                "RGB",
                (bitmap.width, bitmap.height),
                bytes(bitmap.buffer),
                "raw",
                "RGB",
                bitmap.stride,
            )
            gray = image.convert("L")
            background = gray.filter(ImageFilter.MedianFilter(15))
            normalized = ImageChops.difference(gray, background).point(
                lambda x: 0 if x > 30 else 255
            )
            raw = normalized.tobytes()
            buffer = C.create_string_buffer(raw)
            lib.TessBaseAPISetImage(
                api,
                C.cast(buffer, C.c_void_p),
                bitmap.width,
                bitmap.height,
                1,
                bitmap.width,
            )
            # Detect long horizontal rules, then OCR each band independently.
            # This avoids losing text inside colored/merged table cells. It does
            # not assign semantic columns or infer a date from another row.
            dark = gray.point(lambda x: 255 if x < 45 else 0).tobytes()
            rules = []
            for y in range(bitmap.height):
                if dark[y * bitmap.width : (y + 1) * bitmap.width].count(255) > bitmap.width * 0.5:
                    if not rules or y > rules[-1][1] + 1:
                        rules.append([y, y])
                    else:
                        rules[-1][1] = y
            bands = [(0, bitmap.height)]
            if 3 <= len(rules) <= 80:
                bands = [
                    (0, rules[0][0]),
                    *[(a[1] + 2, b[0] - 1) for a, b in zip(rules, rules[1:], strict=False)],
                    (rules[-1][1] + 2, bitmap.height),
                ]
            fragments = []
            confidence = []
            for top, bottom in bands:
                if bottom - top < 8:
                    continue
                band_bytes = normalized.crop((0, top, bitmap.width, bottom)).tobytes()
                band_buffer = C.create_string_buffer(band_bytes)
                lib.TessBaseAPISetImage(
                    api,
                    C.cast(band_buffer, C.c_void_p),
                    bitmap.width,
                    bottom - top,
                    1,
                    bitmap.width,
                )
                lib.TessBaseAPISetPageSegMode(api, 11)
                pointer = lib.TessBaseAPIGetTsvText(api, 0)
                if not pointer:
                    raise RuntimeError("OCR recognition failed")
                try:
                    tsv_band = C.string_at(pointer).decode("utf-8")
                    lines = []
                    for line in tsv_band.splitlines():
                        fields = line.split("\t", 11)
                        if len(fields) == 12 and fields[0] == "5":
                            fields[7] = str(int(fields[7]) + top)
                            lines.append("\t".join(fields))
                    fragments.append("\n".join(lines))
                    confidence.append(lib.TessBaseAPIMeanTextConf(api))
                finally:
                    lib.TessDeleteText(pointer)
            tsv = "\n".join(fragments)
            if len(tsv) > 1_000_000:
                raise ValueError("OCR output limit")
            words = []
            for line in tsv.splitlines():
                fields = line.split("\t", 11)
                if len(fields) != 12 or fields[0] != "5" or not fields[11].strip():
                    continue
                words.append(
                    {
                        "text": fields[11],
                        "bbox": [int(v) for v in fields[6:10]],
                        "confidence": float(fields[10]),
                    }
                )
                if len(words) > 4000:
                    raise ValueError("OCR word limit")
            # Cluster word centers into reading lines, preserving x order and geometry.
            lines = []
            for word in sorted(
                words, key=lambda w: (w["bbox"][1] + w["bbox"][3] / 2, w["bbox"][0])
            ):
                center = word["bbox"][1] + word["bbox"][3] / 2
                if not lines or abs(center - lines[-1][0]) > max(5, word["bbox"][3] * 0.55):
                    lines.append((center, [word]))
                else:
                    lines[-1][1].append(word)
            text = "\n".join(
                "  ".join(w["text"] for w in sorted(row, key=lambda w: w["bbox"][0]))
                for _, row in lines
            )
            return {
                "text": text,
                "words": words,
                "mean_confidence": round(sum(confidence) / max(1, len(confidence))),
                "method": "tesseract_english_ocr",
                "table_structure_verified": False,
            }
        finally:
            lib.TessBaseAPIDelete(api)
    finally:
        if handle:
            handle.close()
