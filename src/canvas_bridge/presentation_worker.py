"""Bounded PresentationML structure and embedded pictures, inside the OS worker.

This is not a slide compositor. Pictures remain original, uncropped assets.
"""

import base64
import hashlib
import io
import json
import warnings

from PIL import Image

if globals().get("__package__"):
    from .office_package import OfficePackage
else:
    from office_package import OfficePackage

PRESENTATION_ERRORS = frozenset({"presentation_resource_limit", "invalid_slide_reference"})
PICTURE_RENDERER = "canvas-bridge-pptx-picture-v1"
MAX_OBJECTS = 200
MAX_CELLS = 400


def tag(e):
    return e.tag.rsplit("}", 1)[-1]


def first(root, name):
    return next((e for e in root.iter() if tag(e) == name), None)


def attr(e, name):
    return next((v for k, v in e.attrib.items() if k.rsplit("}", 1)[-1] == name), None)


def bounded(value, limit=16000):
    if len(value) > limit:
        raise ValueError("presentation_resource_limit")
    return value


def paragraphs(root):
    records = []
    for p in root.iter():
        if tag(p) != "p":
            continue
        text = "".join(
            (e.text or "") if tag(e) == "t" else "\n" if tag(e) == "br" else "" for e in p.iter()
        )
        properties = first(p, "pPr")
        records.append(
            {
                "text": bounded(text),
                "level": properties.attrib.get("lvl", "0") if properties is not None else "0",
                "bullet": next((tag(e) for e in properties if tag(e).startswith("bu")), None)
                if properties is not None
                else None,
            }
        )
    return records


def slide_parts(package):
    parts = []
    for e in package.xml(package.format.main_part).iter():
        if tag(e) != "sldId":
            continue
        try:
            relation = next((v for k, v in e.attrib.items() if k.endswith("}id")), None)
            path = package.related_part(package.format.main_part, relation, "slide")
        except ValueError:
            raise ValueError("invalid_slide_reference") from None
        if not path.startswith("ppt/slides/"):
            raise ValueError("invalid_slide_reference")
        parts.append(path)
        if len(parts) > 200:
            raise ValueError("presentation_resource_limit")
    return parts


def shapes(root):
    """Document/z order; group membership retained, not geometrically composed."""
    result = []

    def visit(parent, group=None, depth=0):
        if depth > 16:
            raise ValueError("presentation_resource_limit")
        for e in parent:
            if tag(e) in {"sp", "pic", "graphicFrame", "cxnSp", "grpSp", "contentPart"}:
                index = len(result) + 1
                result.append((e, group))
                if len(result) > MAX_OBJECTS:
                    raise ValueError("presentation_resource_limit")
                if tag(e) == "grpSp":
                    visit(e, index, depth + 1)

    tree = first(root, "spTree")
    if tree is not None:
        visit(tree)
    return result


def table(root):
    rows = [e for e in root if tag(e) == "tr"]
    grid = first(root, "tblGrid")
    widths = [e.attrib.get("w") for e in grid] if grid is not None else []
    cells = []
    for r, row in enumerate(rows, 1):
        for c, cell in enumerate((e for e in row if tag(e) == "tc"), 1):
            cells.append(
                {
                    "row": r,
                    "column": c,
                    "text": "\n".join(p["text"] for p in paragraphs(cell)),
                    "row_span": cell.attrib.get("rowSpan", "1"),
                    "column_span": cell.attrib.get("gridSpan", "1"),
                    "horizontal_merge": cell.attrib.get("hMerge", "0") in {"true", "1"},
                    "vertical_merge": cell.attrib.get("vMerge", "0") in {"true", "1"},
                }
            )
            if len(cells) > MAX_CELLS:
                raise ValueError("presentation_resource_limit")
    return {
        "row_count": len(rows),
        "column_widths_emu": widths,
        "cells": cells,
        "row_heights_emu": [row.attrib.get("h") for row in rows],
        "merge_semantics": "Stored spans and continuation flags; no inferred headers or values.",
    }


def object_record(e, index, group):
    props = first(e, "cNvPr")
    placeholder = first(e, "ph")
    transform = first(e, "xfrm")
    if tag(e) == "grpSp":
        placeholder = None
        properties = next((c for c in e if tag(c) == "grpSpPr"), None)
        transform = first(properties, "xfrm") if properties is not None else None
    record = {
        "object_index": index,
        "kind": tag(e),
        "group_index": group,
        "shape_id": props.attrib.get("id") if props is not None else None,
        "name": bounded(props.attrib.get("name", ""), 1000) if props is not None else "",
        "alt_text": bounded(props.attrib.get("descr", ""), 4000) if props is not None else "",
        "alt_text_status": "author_supplied_unverified",
        "placeholder": dict(placeholder.attrib) if placeholder is not None else None,
        "transform": {
            "attributes": dict(transform.attrib),
            "components": {tag(c): dict(c.attrib) for c in transform},
        }
        if transform is not None
        else None,
        "coordinate_system": "Stored EMU in parent group; inherited layout geometry is not resolved.",
    }
    if tag(e) == "grpSp":
        record["paragraphs"] = []  # Children are emitted once with group_index.
    elif first(e, "tbl") is not None:
        record["kind"] = "table"
        record["table"] = table(first(e, "tbl"))
    elif tag(e) == "pic":
        record["kind"] = "picture"
        blip = first(e, "blip")
        crop = first(e, "srcRect")
        record["image_status"] = (
            "embedded_uninterpreted"
            if blip is not None and attr(blip, "embed")
            else "external_or_unavailable_not_fetched"
        )
        record["crop"] = dict(crop.attrib) if crop is not None else None
    else:
        record["paragraphs"] = paragraphs(e)
        if tag(e) in {"graphicFrame", "contentPart"}:
            record["interpretation_status"] = "unsupported_graphic_or_chart"
    if len(json.dumps(record, ensure_ascii=True)) > 32000:
        raise ValueError("presentation_resource_limit")
    return record


def extract_presentation(data):
    warnings = [
        "Slide numbers follow presentation order, including hidden slides. Objects follow stored z-order, not guaranteed reading order.",
        "Notes are separate author text, not visible slide content. Alt text is unverified; no picture, chart or scientific meaning has been inferred.",
        "Masters, layouts, backgrounds, animations, equations, SmartArt, media and comments are not rendered/interpreted. Embedded picture reading is not full-slide rendering.",
    ]
    with OfficePackage(data, "pptx") as package:
        parts = slide_parts(package)
        presentation = package.xml(package.format.main_part)
        size = first(presentation, "sldSz")
        metadata = {
            "slide_count": len(parts),
            "slide_size_emu": dict(size.attrib) if size is not None else None,
            "slides": [],
        }
        if "docProps/core.xml" in package.names:
            for e in package.xml("docProps/core.xml"):
                if tag(e) in {"title", "creator", "subject"}:
                    metadata[{"creator": "author"}.get(tag(e), tag(e))] = (e.text or "")[:1000]
        pages, partial, text_size, structured_size = [], False, 0, 0
        for number, path in enumerate(parts, 1):
            root = package.xml(path)
            objects = [object_record(e, i, group) for i, (e, group) in enumerate(shapes(root), 1)]
            # Retain text from older/minimal packages with no shape tree.
            if not objects and first(root, "spTree") is None:
                objects = [
                    {"object_index": 1, "kind": "unplaced_text", "paragraphs": paragraphs(root)}
                ]
            notes, notes_state = [], "absent"
            relations = package.relationships(path, "notesSlide")
            if len(relations) > 1:
                raise ValueError("invalid_slide_reference")
            if relations:
                note_path = package.related_part(path, relations[0].attrib.get("Id"), "notesSlide")
                if not note_path.startswith("ppt/notesSlides/"):
                    raise ValueError("invalid_slide_reference")
                for e, _ in shapes(package.xml(note_path)):
                    placeholder = first(e, "ph")
                    if tag(e) != "sp" or (
                        placeholder is not None
                        and placeholder.attrib.get("type")
                        in {"sldImg", "sldNum", "dt", "ftr", "hdr"}
                    ):
                        continue
                    notes.extend(paragraphs(e))
                notes_state = (
                    "extracted" if any(p["text"].strip() for p in notes) else "present_empty"
                )
            if len(notes) > 200 or any(
                len(json.dumps(p, ensure_ascii=True)) > 32000 for p in notes
            ):
                raise ValueError("presentation_resource_limit")
            lines = []
            for obj in objects:
                label = f"Slide {number}, object {obj['object_index']}"
                for paragraph in obj.get("paragraphs", []):
                    if paragraph["text"].strip():
                        lines.append(f"[{label}] {paragraph['text']}")
                for cell in obj.get("table", {}).get("cells", []):
                    if cell["text"].strip():
                        lines.append(
                            f"[{label}, table R{cell['row']}C{cell['column']}] {cell['text']}"
                        )
            for i, p in enumerate(notes, 1):
                if p["text"].strip():
                    lines.append(f"[Slide {number}, speaker notes paragraph {i}] {p['text']}")
            visual = first(root, "blip") is not None or any(
                o["kind"] in {"picture", "graphicFrame", "contentPart"} for o in objects
            )
            text = "\n".join(lines)
            page = {
                "page": number,
                "locator_kind": "slide",
                "text": text,
                "state": "extracted" if text.strip() else "no_text",
                "extraction_method": "ooxml_slide_structure",
                "hidden": root.attrib.get("show", "1") in {"0", "false"},
                "objects": objects,
                "notes": notes,
                "notes_state": notes_state,
                "visual_review_required": visual or not text.strip(),
                "coverage": "partial" if visual or not text.strip() else "text_and_structure",
            }
            text_size += len(text) + 2
            structured_size += len(json.dumps(page, ensure_ascii=True))
            if text_size > 240000 or structured_size > 900000:
                raise ValueError("presentation_resource_limit")
            pages.append(page)
            partial |= page["coverage"] == "partial"
            metadata["slides"].append(
                {
                    "slide": number,
                    "hidden": page["hidden"],
                    "object_count": len(objects),
                    "picture_count": sum(o["kind"] == "picture" for o in objects),
                    "table_count": sum(o["kind"] == "table" for o in objects),
                    "notes_state": notes_state,
                    "visual_review_required": page["visual_review_required"],
                    "title": next(
                        (
                            "\n".join(p["text"] for p in o.get("paragraphs", []))[:1000]
                            for o in objects
                            if (o.get("placeholder") or {}).get("type") in {"title", "ctrTitle"}
                        ),
                        None,
                    ),
                }
            )
            if len(json.dumps(metadata, ensure_ascii=True)) > 50000:
                raise ValueError("presentation_resource_limit")
        if partial:
            warnings.append(
                "Some slides require visual review. Text search excludes unread picture pixels; text or notes alone cannot establish complete slide coverage."
            )
        return metadata, pages, partial, warnings


def render_picture(data, slide, object_index):
    """Decode only a requested embedded raster image; never links or vectors."""
    with OfficePackage(data, "pptx") as package:
        parts = slide_parts(package)
        if type(slide) is not int or not 1 <= slide <= len(parts):
            raise ValueError("invalid_slide_reference")
        path = parts[slide - 1]
        objects = shapes(package.xml(path))
        if type(object_index) is not int or not 1 <= object_index <= len(objects):
            raise ValueError("invalid_slide_reference")
        e, _ = objects[object_index - 1]
        blip = first(e, "blip")
        if tag(e) != "pic" or blip is None or not attr(blip, "embed"):
            raise ValueError("invalid_slide_reference")
        member = package.related_part(path, attr(blip, "embed"), "image")
        if not member.startswith("ppt/media/"):
            raise ValueError("invalid_slide_reference")
        raw = package.read(member)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG", "WEBP"]) as image:
                if image.width * image.height > 12000000 or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("presentation_resource_limit")
                original_pixels = list(image.size)
                image.load()
                image.thumbnail((2400, 2400))
                rgba = image.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                for _ in range(8):
                    output = io.BytesIO()
                    clean.save(output, format="PNG")
                    png = output.getvalue()
                    if len(png) <= 1300000:
                        break
                    clean = clean.resize(
                        (max(1, clean.width * 3 // 4), max(1, clean.height * 3 // 4))
                    )
                else:
                    raise ValueError("presentation_resource_limit")
        return {
            "renderer": PICTURE_RENDERER,
            "visual_kind": "pptx_picture",
            "content_hash": hashlib.sha256(data).hexdigest(),
            "page": slide,
            "page_count": len(parts),
            "rotation": 0,
            "object_index": object_index,
            "pixels": list(clean.size),
            "original_pixels": original_pixels,
            "image_hash": hashlib.sha256(png).hexdigest(),
            "png": base64.b64encode(png).decode(),
            "interpretation_required": True,
            "image_locator": f"Slide {slide}, object {object_index}",
            "coverage": "one_uncropped_embedded_picture; not a rendered slide",
        }
