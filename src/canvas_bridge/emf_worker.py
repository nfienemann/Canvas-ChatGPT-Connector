"""Narrow EMF preflight, used ONLY inside the credential-free render worker.

Classic EMF supports a bounded static drawing allowlist. A full-frame EMF+
bitmap wrapper is decoded to PNG; its optional PDF alternative is never parsed
or given to LibreOffice. Unknown records, transforms and media fail closed.
This is deliberately not a general EMF/EMF+ interpreter.
"""

import io
import math
import struct

from PIL import Image

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_RECORDS = 20_000


def require(condition):
    if not condition:
        raise ValueError("unsupported_slide_media")


def u32(data, offset):
    require(0 <= offset <= len(data) - 4)
    return struct.unpack_from("<I", data, offset)[0]


def integers(data, offset, count):
    require(0 <= offset <= len(data) - count * 4)
    return struct.unpack_from("<" + "i" * count, data, offset)


def coordinates(data, offset, count):
    require(all(abs(n) <= 1_000_000 for n in integers(data, offset, count)))


def floats(data, offset, count):
    require(0 <= offset <= len(data) - count * 4)
    values = struct.unpack_from("<" + "f" * count, data, offset)
    require(all(math.isfinite(n) and abs(n) <= 1_000_000 for n in values))
    return values


def records(data):
    result, offset = [], 0
    while offset < len(data):
        require(len(result) < MAX_RECORDS and offset + 8 <= len(data))
        kind, size = struct.unpack_from("<II", data, offset)
        require(size >= 8 and size % 4 == 0 and size <= len(data) - offset)
        result.append((kind, memoryview(data)[offset : offset + size]))
        offset += size
    return result


def comment(record, signature):
    size = u32(record, 8)
    require(size >= 4 and 12 + size <= len(record) < 16 + size)
    require(record[12:16] == signature)
    return record[16 : 12 + size]


def pdf_alternative(record):
    # EMR_COMMENT_MULTIFORMATS: exactly one bounded PDF alternative. No native
    # parser ever sees this payload, even if the PDF contains active content.
    data = comment(record, b"GDIC")
    require(len(data) >= 40 and u32(data, 0) == 0x40000004)
    coordinates(data, 4, 4)
    require(u32(data, 20) == 1 and u32(data, 24) == 0x50444620)
    require(u32(data, 28) == 0 and u32(data, 36) == 44)
    length = u32(data, 32)
    require(length >= 8 and length == len(data) - 40)
    require(data[40:45] == b"%PDF-")


def bitmap(record):
    data = comment(record, b"EMF+")
    nested, offset = [], 0
    while offset < len(data):
        require(offset + 12 <= len(data) and len(nested) < 9)
        kind, flags, size, length = struct.unpack_from("<HHII", data, offset)
        require(size >= 12 and size % 4 == 0 and size == length + 12)
        require(size <= len(data) - offset)
        nested.append((kind, flags, data[offset + 12 : offset + size]))
        offset += size
    require(
        [r[0] for r in nested] == [0x4001, 0x4030, 0x4009, 0x4023, 0x4008, 0x4008, 0x401A, 0x4002]
    )
    header, page, clear, reset, attributes, picture, draw, eof = nested
    require(header[1] == 1 and len(header[2]) == 16)
    require(tuple(u32(header[2], n) for n in (0, 4, 8, 12)) == (0xDBC01002, 1, 96, 96))
    require(page[1] == 2 and len(page[2]) == 4 and floats(page[2], 0, 1) == (1.0,))
    require(clear[1] == 0 and len(clear[2]) == 4 and u32(clear[2], 0) == 0x00FFFFFF)
    require(reset[1:] == (0, b"") and eof[1:] == (0, b""))
    attr_id, image_id = attributes[1] & 255, picture[1] & 255
    require(attr_id < 64 and image_id < 64 and attr_id != image_id)
    require(attributes[1] == 0x800 | attr_id and len(attributes[2]) == 24)
    require(
        tuple(u32(attributes[2], n) for n in range(0, 24, 4))
        == (0xDBC01002, 0, 0, 0xFFFFFFFF, 0, 0)
    )
    require(picture[1] == 0x500 | image_id and len(picture[2]) >= 28)
    raw = picture[2]
    require(u32(raw, 0) == 0xDBC01002 and u32(raw, 4) == 1)
    width, height, stride = integers(raw, 8, 3)
    require(1 <= width <= 16384 and 1 <= height <= 16384 and width * height <= MAX_PIXELS)
    require(stride == width * 4 and u32(raw, 20) == 0x000E200B and u32(raw, 24) == 0)
    require(len(raw) == 28 + stride * height)
    require(draw[1] == image_id and len(draw[2]) == 40)
    require(u32(draw[2], 0) == attr_id and u32(draw[2], 4) == 2)
    require(floats(draw[2], 8, 8) == (0, 0, width, height, 0, 0, width, height))
    # Pillow explicitly converts premultiplied BGRA to ordinary RGBA. No
    # metafile renderer, embedded PDF decoder, or general image probe is used.
    with Image.frombytes(
        "RGBa", (width, height), raw[28:].tobytes(), "raw", "BGRa"
    ) as premultiplied:
        with premultiplied.convert("RGBA") as rgba:
            output = io.BytesIO()
            rgba.save(output, format="PNG")
    require(output.tell() <= MAX_BYTES)
    return output.getvalue(), width, height


def classic(items, handles):
    objects, stack, path = set(), 0, "none"
    exact = {
        22: 12,
        24: 12,
        27: 16,
        33: 8,
        34: 12,
        37: 12,
        38: 28,
        39: 24,
        40: 12,
        42: 24,
        43: 24,
        54: 16,
        59: 8,
        60: 8,
        61: 8,
        62: 24,
        63: 24,
        64: 24,
        76: 100,
        82: 368,
    }
    for kind, record in items:
        require(kind in exact or kind in {75, 84})
        if kind in exact:
            require(len(record) == exact[kind])
        if kind == 33:
            stack += 1
            require(stack <= 32)
        elif kind == 34:
            restore = integers(record, 8, 1)[0]
            require(-stack <= restore < 0)
            stack += restore
        elif kind in {38, 39, 82}:
            handle = u32(record, 8)
            require(0 < handle < handles and handle not in objects)
            objects.add(handle)
            if kind == 38:
                require(
                    u32(record, 12) <= 6
                    and 0 <= integers(record, 16, 1)[0] <= 16384
                    and u32(record, 20) == 0
                )
            elif kind == 39:
                require(u32(record, 12) in {0, 1, 2} and u32(record, 20) <= 5)
            else:
                coordinates(record, 12, 5)
                require(b"\0\0" in record[40:104].tobytes())
        elif kind in {37, 40}:
            handle = u32(record, 8)
            require(handle in objects or (kind == 37 and 0x80000000 <= handle <= 0x80000013))
            if kind == 40:
                objects.remove(handle)
        elif kind == 22:
            require(u32(record, 8) & ~0x11F == 0)
        elif kind in {27, 54}:
            coordinates(record, 8, 2)
        elif kind in {42, 43, 62, 63, 64}:
            coordinates(record, 8, 4)
            if kind in {62, 63, 64}:
                require(path == "closed")
                path = "none"
        elif kind == 59:
            require(path == "none")
            path = "open"
        elif kind == 60:
            require(path == "open")
            path = "closed"
        elif kind == 61:
            require(path == "open")
        elif kind == 75:
            size, mode = u32(record, 8), u32(record, 12)
            require(mode in {1, 2, 3, 4, 5} and len(record) == 16 + size)
            if size == 0:
                require(mode == 5)
            else:
                require(size >= 32 and u32(record, 16) == 32 and u32(record, 20) == 1)
                count = u32(record, 24)
                require(count <= 4096 and size == 32 + count * 16 and u32(record, 28) == count * 16)
                coordinates(record, 32, 4 + count * 4)
        elif kind == 76:
            coordinates(record, 8, 8)
            coordinates(record, 44, 2)
            # PATCOPY uses only the selected static brush. No source bitmap.
            require(u32(record, 40) == 0x00F00021)
            require(floats(record, 52, 6) == (1, 0, 0, 1, 0, 0))
            require(all(u32(record, n) == 0 for n in (80, 84, 88, 92, 96)))
        elif kind == 84:
            require(len(record) >= 76 and u32(record, 24) in {1, 2})
            coordinates(record, 8, 4)
            floats(record, 28, 2)
            coordinates(record, 36, 2)
            count, start, options, spacing = (u32(record, n) for n in (44, 48, 52, 72))
            require(count <= 16384 and options & ~6 == 0)
            coordinates(record, 56, 4)
            require(start >= 76 and start % 2 == 0 and start + count * 2 <= len(record))
            if spacing:
                require(spacing >= 76 and spacing % 4 == 0 and spacing + count * 4 <= len(record))
                require(spacing >= start + count * 2 or start >= spacing + count * 4)
                coordinates(record, spacing, count)
    require(stack == 0 and path == "none")


def prepare_emf(data):
    """Return safe representation (extension, bytes), or reject the whole file."""
    require(108 <= len(data) <= MAX_BYTES)
    items = records(data)
    require(len(items) >= 2 and items[0][0] == 1 and items[-1][0] == 14)
    header = items[0][1]
    require(len(header) >= 108 and u32(header, 40) == 0x464D4520 and u32(header, 44) == 0x10000)
    require(u32(header, 48) == len(data) and header[58:60] == b"\0\0")
    handles = struct.unpack_from("<H", header, 56)[0]
    require(1 <= handles <= 4096)
    left, top, right, bottom = integers(header, 8, 4)
    width, height = right - left + 1, bottom - top + 1
    coordinates(header, 8, 8)
    require(1 <= width <= 16384 and 1 <= height <= 16384 and width * height <= MAX_PIXELS)
    require(all(1 <= n <= 1_000_000 for n in integers(header, 72, 4)))
    require(all(u32(header, n) == 0 for n in (68, 88, 92, 96)))
    desc, offset = u32(header, 60), u32(header, 64)
    require(
        (desc == 0 and offset == 0)
        or (
            desc <= 16384 and offset >= 108 and offset % 2 == 0 and offset + desc * 2 <= len(header)
        )
    )
    if items[1][0] == 70:
        require(len(items) in {3, 4} and all(k == 70 for k, _ in items[1:-1]))
        png, bitmap_width, bitmap_height = bitmap(items[1][1])
        require((left, top, width, height) == (0, 0, bitmap_width, bitmap_height))
        if len(items) == 4:
            pdf_alternative(items[2][1])
        # Some producers omit the alternate-format comment from nRecords and
        # write a palette-free 16-byte EOF. Accept only for this normalized form.
        require(u32(header, 52) in {len(items), 3})
        eof = items[-1][1]
        require(len(eof) in {16, 20} and u32(eof, 8) == 0)
        require(u32(eof, 12) in {0, 16})
        require(len(eof) == 16 or u32(eof, 16) == 20)
        return "png", png
    require(u32(header, 52) == len(items))
    eof = items[-1][1]
    require(len(eof) == 20 and u32(eof, 8) == 0 and u32(eof, 12) in {0, 16} and u32(eof, 16) == 20)
    classic(items[1:-1], handles)
    return "emf", data
