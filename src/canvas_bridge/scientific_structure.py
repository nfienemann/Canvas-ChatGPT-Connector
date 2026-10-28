"""Inert, bounded scientific structure extraction inside the existing sandbox.

No layout inference, image interpretation, formula execution or external reads.
OOXML trees come from the existing bounded, defused package readers.
"""

import json
import re

SCHEMA = "scientific-structure-3"
MAX_ITEMS = 80
MAX_STRUCTURE_BYTES = 80_000
CAPTION = re.compile(r"^\s*(?:Figure|Fig\.?|Table|Panel)\s+(?:\d+[A-Za-z]?|[A-Za-z])\b", re.I)
NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://schemas.openxmlformats.org/presentationml/2006/main",
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "urn:schemas-microsoft-com:vml",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
    "http://purl.oclc.org/ooxml/drawingml/picture",
    "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing",
    "http://purl.oclc.org/ooxml/presentationml/main",
    "http://purl.oclc.org/ooxml/spreadsheetml/main",
    "http://purl.oclc.org/ooxml/officeDocument/math",
}


def tag(node):
    namespace, separator, local = node.tag.rpartition("}")
    return local if separator and namespace.removeprefix("{") in NAMESPACES else ""


def attr(node, name, default=None):
    return next((v for k, v in node.attrib.items() if k.rsplit("}", 1)[-1] == name), default)


def visible_nodes(root):
    if tag(root) in {"", "del", "moveFrom"}:
        return
    if tag(root) == "AlternateContent":
        fallback = next((e for e in root if tag(e) == "Fallback"), None)
        if fallback is not None:
            yield from visible_nodes(fallback)
        return
    yield root
    for child in root:
        yield from visible_nodes(child)


def text(root):
    return "".join(e.text or "" for e in visible_nodes(root) if tag(e) == "t")


def runs(root):
    values = []
    for e in visible_nodes(root):
        if tag(e) != "r":
            continue
        value = "".join(n.text or "" for n in e if tag(n) == "t")
        if not value:
            continue
        alignment, baseline = "baseline", None
        for n in e.iter():
            if tag(n) in {"vertAlign", "vertAlignPr"}:
                alignment = attr(n, "val", "unknown")
            if tag(n) == "rPr" and attr(n, "baseline") is not None:
                baseline = attr(n, "baseline")
                alignment = "source_baseline_offset"
        values.append(
            {"text": value[:4000], "vertical_alignment": alignment, "baseline_offset": baseline}
        )
        if len(values) >= MAX_ITEMS:
            break
    return values


def math_tree(node, budget, depth=0):
    budget[0] += 1
    if depth > 12 or budget[0] > 500:
        raise ValueError("equation_structure_limit")
    return {
        "operator": tag(node),
        "text": node.text if tag(node) == "t" else None,
        "attributes": {
            k.rsplit("}", 1)[-1]: v
            for k, v in node.attrib.items()
            if k.rsplit("}", 1)[-1] in {"val", "type", "begChr", "endChr"}
        },
        "children": [math_tree(n, budget, depth + 1) for n in node],
    }


def empty(scope):
    return {
        "schema_version": SCHEMA,
        "scope": scope,
        "text_blocks": [],
        "figures": [],
        "tables": [],
        "equations": [],
        "captions": [],
        "speaker_notes": [],
        "visual_inspection_status": "not_performed",
        "limitations": [],
    }


def bounded(structure):
    # Keep complete items only. Truncation must be visible and never split table cells.
    for field in ("text_blocks", "tables", "equations", "figures", "captions", "speaker_notes"):
        if len(structure[field]) > MAX_ITEMS:
            structure[field] = structure[field][:MAX_ITEMS]
            structure["limitations"].append(field + ": item budget exhausted.")
    for field in ("text_blocks", "tables", "equations", "figures", "captions", "speaker_notes"):
        while (
            len(json.dumps(structure, ensure_ascii=True).encode()) > MAX_STRUCTURE_BYTES
            and structure[field]
        ):
            structure[field].pop()
            message = (
                "Structure byte budget exhausted; omitted items require targeted source inspection."
            )
            if message not in structure["limitations"]:
                structure["limitations"].append(message)
    return structure


def ooxml_structure(root, kind):
    result = empty("original_slide" if kind == "pptx" else "original_document")
    nodes = list(visible_nodes(root))
    paragraphs = [n for n in nodes if tag(n) == "p"]
    for index, p in enumerate(paragraphs[:MAX_ITEMS], 1):
        value = text(p)
        block = {"locator": f"Paragraph {index}", "text": value[:4000], "runs": runs(p)}
        if len(value) > 4000 or sum(tag(n) == "r" for n in visible_nodes(p)) > MAX_ITEMS:
            result["limitations"].append(
                f"Paragraph {index}: text or formatting runs exceed the structure budget."
            )
        result["text_blocks"].append(block)
        if CAPTION.match(value):
            result["captions"].append(
                {
                    "locator": block["locator"],
                    "text": value[:1000],
                    "status": "textual_caption_candidate",
                }
            )
    if len(paragraphs) > MAX_ITEMS:
        result["limitations"].append(
            "Paragraph structure budget exhausted; use the text continuation."
        )
    for index, table in enumerate((n for n in nodes if tag(n) == "tbl"), 1):
        if index > MAX_ITEMS:
            result["limitations"].append("Table structure budget exhausted.")
            break
        cells, complete = [], True
        rows = [n for n in table if tag(n) == "tr"]
        for row_number, row in enumerate(rows, 1):
            column = 1
            before = next((n for n in row.iter() if tag(n) == "gridBefore"), None)
            if before is not None:
                try:
                    offset = int(attr(before, "val", "0"))
                    if not 0 <= offset <= 1000:
                        raise ValueError("Invalid table offset")
                    column += offset
                except ValueError:
                    complete, cells = False, []
                    break
            for cell in (n for n in row if tag(n) == "tc"):
                if len(cells) >= 400:
                    complete = False
                    break
                span = next((n for n in cell.iter() if tag(n) == "gridSpan"), None)
                try:
                    width = (
                        int(attr(span, "val", "1"))
                        if span is not None
                        else int(attr(cell, "gridSpan", "1"))
                    )
                    height = int(attr(cell, "rowSpan", "1"))
                    if not 1 <= width <= 1000 or not 1 <= height <= 1000:
                        raise ValueError("Invalid table span")
                except ValueError:
                    complete, cells = False, []
                    break
                merge = next((n for n in cell.iter() if tag(n) == "vMerge"), None)
                value = text(cell)
                if len(value) > 4000:
                    complete = False
                cells.append(
                    {
                        "row": row_number,
                        "column": column,
                        "column_span": width,
                        "row_span": height,
                        "vertical_merge": attr(merge, "val", "continue")
                        if merge is not None
                        else attr(cell, "vMerge"),
                        "horizontal_merge": attr(cell, "hMerge"),
                        "header_declared": any(tag(n) == "tblHeader" for n in row.iter()),
                        "text": value[:4000],
                        "runs": runs(cell),
                    }
                )
                column += 1 if kind == "pptx" else width
            if not complete and (len(cells) >= 400 or not cells):
                break
        result["tables"].append(
            {
                "locator": f"Table {index}",
                "cells": cells,
                "row_count": len(rows),
                "structure_complete": complete,
                "header_semantics": "source_declared_only_not_inferred",
            }
        )
    for index, equation in enumerate((n for n in nodes if tag(n) == "oMath"), 1):
        if index > MAX_ITEMS:
            result["limitations"].append("Equation structure budget exhausted.")
            break
        try:
            tree = math_tree(equation, [0])
        except ValueError:
            tree = None
        result["equations"].append(
            {
                "locator": f"Equation {index}",
                "notation": "OMML",
                "tree": tree,
                "structure_complete": tree is not None,
                "interpretation": "not_performed",
            }
        )
    for index, figure in enumerate((n for n in nodes if tag(n) in {"pic", "drawing"}), 1):
        if index > MAX_ITEMS:
            result["limitations"].append("Image-region budget exhausted.")
            break
        transform = next((n for n in figure.iter() if tag(n) == "xfrm"), None)
        geometry = None
        if transform is not None:
            geometry = {
                tag(n): {
                    k.rsplit("}", 1)[-1]: v
                    for k, v in n.attrib.items()
                    if k in {"x", "y", "cx", "cy"}
                }
                for n in transform
                if tag(n) in {"off", "ext"}
            }
        result["figures"].append(
            {
                "locator": f"Image object {index}",
                "geometry": geometry,
                "coordinate_system": "source_EMU" if geometry else "unknown",
                "status": "candidate_not_inspected",
            }
        )
    result["limitations"].append(
        "XML order and stored structure are not visual reading or scientific interpretation. Table headers/units are not inferred."
    )
    return bounded(result)


def enrich(extraction):
    """A document-wide cap supplements the existing text/CPU/ZIP budgets."""
    remaining = 120_000
    for page in extraction["pages"]:
        structure = from_page(page, extraction["format"])
        size = len(json.dumps(structure, ensure_ascii=True).encode())
        if size > remaining:
            page.pop("structure", None)
            message = "Document structure budget exhausted; omitted structures are unavailable, not empty. Text and selective visual reading remain available."
            if message not in extraction["warnings"]:
                extraction["warnings"].append(message)
            continue
        page["structure"] = structure
        remaining -= size
    return extraction


def from_page(page, kind):
    result = page.get("structure") or empty(
        "original_"
        + {"pdf": "page", "pptx": "slide", "xlsx": "sheet", "docx": "section"}.get(kind, "document")
    )
    if kind == "xlsx":
        records, complete = [], True
        for line in page["text"].splitlines():
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                complete = False
                result["limitations"].append(
                    "Workbook record was incomplete; no cells were reconstructed."
                )
                break
            if isinstance(record, dict):
                records.append(record)
        result["tables"] = [
            {
                "locator": "Sheet " + page.get("sheet_name", "unknown"),
                "stored_records": records[:400],
                "structure_complete": complete
                and len(records) <= 400
                and page["state"] == "extracted",
                "header_semantics": "source_cells_and_merged_ranges_not_inferred",
            }
        ]
        result["equations"] = [
            {
                "locator": r["cell"],
                "notation": "spreadsheet_formula",
                "expression": r.get("formula"),
                "structure_complete": bool(r.get("formula")),
                "interpretation": "not_evaluated",
            }
            for r in records
            if r.get("type") == "formula"
        ]
    if not result["text_blocks"]:
        lines = list(re.finditer(r"[^\n]+", page["text"]))
        result["text_blocks"] = [
            {"locator": f"Text offset {m.start()}", "text": m[0][:4000], "runs": []}
            for m in lines[:MAX_ITEMS]
        ]
        if len(lines) > MAX_ITEMS or any(len(m[0]) > 4000 for m in lines[:MAX_ITEMS]):
            result["limitations"].append(
                "Text-block structure budget exhausted; use the text continuation."
            )
    if not result["captions"]:
        result["captions"] = [
            {
                "locator": b["locator"],
                "text": b["text"][:1000],
                "status": "textual_caption_candidate",
            }
            for b in result["text_blocks"]
            if CAPTION.match(b["text"])
        ]
    result["speaker_notes"] = [
        {"locator": f"Notes offset {s['start']}", "text": page["text"][s["start"] : s["end"]]}
        for s in page.get("text_spans", [])
        if s["source_kind"] == "speaker_notes"
    ]
    if kind == "pdf":
        result["figures"] = [
            {
                "locator": f"PDF page {page['page']}",
                "geometry": None,
                "coordinate_system": "unknown",
                "status": "page_requires_visual_discovery",
            }
        ]
        result["limitations"].append(
            "PDF table/equation geometry and superscript roles are not established by embedded text; inspect pixels before interpretation."
        )
    return bounded(result)
