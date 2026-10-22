"""Read-only WordprocessingML body/table structure in the isolated worker."""

import json

if globals().get("__package__"):
    from .office_package import OfficePackage
else:
    from office_package import OfficePackage

DOCUMENT_ERRORS = frozenset({"document_resource_limit", "invalid_document_structure"})
REVISIONS = frozenset(
    {
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "cellIns",
        "cellDel",
        "cellMerge",
        "pPrChange",
        "rPrChange",
        "tblPrChange",
        "trPrChange",
        "tcPrChange",
        "tblGridChange",
    }
)


def tag(e):
    return e.tag.rsplit("}", 1)[-1]


def child(e, name):
    return next((c for c in e if tag(c) == name), None) if e is not None else None


def attribute(e, name, default=None):
    if e is None:
        return default
    return next((v for k, v in e.attrib.items() if k.rsplit("}", 1)[-1] == name), default)


def value(e, name, default=None):
    return attribute(child(e, name), "val", default)


def number(value, default=0, minimum=0):
    try:
        result = default if value is None else int(value)
        if not minimum <= result <= 100:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ValueError("invalid_document_structure") from None


class DocumentReader:
    def __init__(self):
        self.records, self.tables, self.omitted = [], [], set()
        self.paragraph_count, self.cell_count = 0, 0

    def paragraph(self, element):
        self.paragraph_count += 1
        if self.paragraph_count > 5000:
            raise ValueError("document_resource_limit")

        def text(e, depth=0):
            if depth > 32:
                raise ValueError("document_resource_limit")
            name = tag(e)
            if name in {
                "ins",
                "del",
                "moveFrom",
                "moveTo",
                "drawing",
                "pict",
                "object",
                "oMath",
                "oMathPara",
                "footnoteReference",
                "endnoteReference",
                "txbxContent",
            }:
                self.omitted.add(name)
                return ""
            if name in {"pPr", "rPr", "sdtPr"}:
                return ""
            if name == "t":
                return e.text or ""
            if name == "tab":
                return "\t"
            if name in {"br", "cr"}:
                return "\n"
            if name in {"instrText", "fldChar"}:
                self.omitted.add("field_evaluation")
                return ""
            return "".join(text(c, depth + 1) for c in e)

        contents = text(element)
        if len(contents) > 16000:
            raise ValueError("document_resource_limit")
        props = child(element, "pPr")
        return {
            "id": f"P{self.paragraph_count}",
            "kind": "paragraph",
            "text": contents,
            "style_id": value(props, "pStyle"),
            "outline_level": value(props, "outlineLvl"),
            "locator": f"Paragraph {self.paragraph_count}",
        }

    def blocks(self, container, parent_cell=None, depth=0):
        if depth > 8:
            raise ValueError("document_resource_limit")
        blocks = []
        for e in container:
            name = tag(e)
            if name == "p":
                record = self.paragraph(e)
                if parent_cell:
                    record["locator"] = f"{parent_cell}, {record['locator']}"
                else:
                    self.records.append(record)
                blocks.append(record)
            elif name == "tbl":
                table = self.table(e, parent_cell, depth + 1)
                blocks.append({"id": table["id"], "kind": "table_reference"})
            elif name == "sdt":
                content = child(e, "sdtContent")
                if content is not None:
                    blocks.extend(self.blocks(content, parent_cell, depth + 1))
            elif name not in {"sectPr", "tcPr", "bookmarkStart", "bookmarkEnd", "proofErr"}:
                self.omitted.add(name)
        for i, block in enumerate(blocks):
            if block["kind"] == "table_reference":
                table = next(t for t in self.tables if t["id"] == block["id"])
                table["preceding_block"] = blocks[i - 1]["id"] if i else None
                table["following_block"] = blocks[i + 1]["id"] if i + 1 < len(blocks) else None
        return blocks

    def table(self, element, parent_cell, depth):
        if depth > 8 or len(self.tables) >= 100:
            raise ValueError("document_resource_limit")
        table_id = f"T{len(self.tables) + 1}"
        props, grid = child(element, "tblPr"), child(element, "tblGrid")
        columns = (
            [attribute(c, "w") for c in grid if tag(c) == "gridCol"] if grid is not None else []
        )
        if len(columns) > 100:
            raise ValueError("document_resource_limit")
        rows = [c for c in element if tag(c) == "tr"]
        if len(rows) > 200:
            raise ValueError("document_resource_limit")
        record = {
            "id": table_id,
            "table_id": table_id,
            "kind": "table",
            "locator": f"Table {table_id}",
            "parent_cell": parent_cell,
            "caption": value(props, "tblCaption"),
            "description": value(props, "tblDescription"),
            "style_id": value(props, "tblStyle"),
            "grid_widths_twips": columns,
            "declared_column_count": len(columns) or None,
            "row_count": len(rows),
            "rows": [],
            "uncertainties": [],
            "header_policy": "Only explicit repeating-header flags are reported; semantic headers are not inferred.",
        }
        self.tables.append(record)
        self.records.append(record)
        if any(tag(e) in REVISIONS for e in element.iter()):
            record["uncertainties"].append(
                "Table contains revision markers; stored properties/row/cell records are not a verified accepted-revision view."
            )
        if not columns:
            record["uncertainties"].append(
                "No declared table grid; coordinates use stored spans only."
            )
        if child(props, "tblpPr") is not None:
            record["uncertainties"].append(
                "Floating table: XML neighbors do not establish visual position."
            )
        if any(tag(c) not in {"tblPr", "tblGrid", "tr"} for c in element):
            record["uncertainties"].append(
                "Unsupported table-level content or revisions were omitted."
            )
        previous = {}
        for row_index, row in enumerate(rows, 1):
            row_props = child(row, "trPr")
            before, after = (
                number(value(row_props, "gridBefore")),
                number(value(row_props, "gridAfter")),
            )
            header = child(row_props, "tblHeader")
            row_meta = {
                "row": row_index,
                "grid_before": before,
                "grid_after": after,
                "repeating_header": header is not None
                and attribute(header, "val", "1") not in {"0", "false", "off"},
                "cell_ids": [],
            }
            record["rows"].append(row_meta)
            if any(tag(c) not in {"trPr", "tc"} for c in row):
                record["uncertainties"].append(
                    f"Row {row_index}: unsupported row content omitted; cell positions may be incomplete."
                )
            column, current = before + 1, {}
            for cell in (c for c in row if tag(c) == "tc"):
                self.cell_count += 1
                if self.cell_count > 4000:
                    raise ValueError("document_resource_limit")
                cell_props = child(cell, "tcPr")
                span = number(value(cell_props, "gridSpan"), 1, 1)
                if column + span - 1 > 100:
                    raise ValueError("document_resource_limit")
                merge = child(cell_props, "vMerge")
                mode = attribute(merge, "val", "continue") if merge is not None else None
                identity = f"{table_id}:R{row_index}C{column}"
                locator = f"Table {table_id}, R{row_index}C{column}"
                item = {
                    "id": identity,
                    "kind": "cell",
                    "table_id": table_id,
                    "locator": locator,
                    "row": row_index,
                    "column": column,
                    "column_span": span,
                    "row_span": 1,
                    "vertical_merge": mode,
                    "merge_origin": None,
                    "merge_status": "unmerged",
                    "parent_cell": parent_cell,
                    "blocks": [],
                }
                if span > 1:
                    item["merge_origin"], item["merge_status"] = identity, "horizontal_span"
                key = (column, span)
                if child(cell_props, "hMerge") is not None:
                    item["legacy_horizontal_merge"] = value(cell_props, "hMerge", "continue")
                    item["merge_status"] = "unresolved"
                    item["merge_origin"], item["row_span"] = None, None
                    record["uncertainties"].append(
                        f"{identity}: legacy horizontal merge is not resolved."
                    )
                elif mode == "restart":
                    item["merge_origin"], item["merge_status"] = identity, "origin"
                    current[key] = item
                elif mode == "continue" and key in previous:
                    origin = previous[key]
                    item["merge_origin"], item["merge_status"] = origin["id"], "continuation"
                    item["row_span"] = None
                    origin["row_span"] += 1
                    current[key] = origin
                elif mode is not None:
                    item["merge_status"] = "unresolved"
                    item["merge_origin"], item["row_span"] = None, None
                    record["uncertainties"].append(
                        f"{identity}: vertical merge has no matching prior origin/span or an invalid value."
                    )
                row_meta["cell_ids"].append(identity)
                self.records.append(item)
                item["blocks"] = self.blocks(cell, locator, depth)
                item["text"] = "\n".join(
                    b["text"] if b["kind"] == "paragraph" else f"[Nested table {b['id']}]"
                    for b in item["blocks"]
                )
                if item["merge_status"] == "continuation" and any(
                    b.get("text", "").strip() or b["kind"] == "table_reference"
                    for b in item["blocks"]
                ):
                    record["uncertainties"].append(
                        f"{identity}: merge continuation contains content; preserved without copying the origin value."
                    )
                column += span
            previous = current
            row_meta["occupied_grid_width"] = column - 1 + after
            if columns and row_meta["occupied_grid_width"] != len(columns):
                record["uncertainties"].append(
                    f"Row {row_index}: stored spans/omissions disagree with the declared grid."
                )
        record["structure_status"] = "partial" if record["uncertainties"] else "parsed"
        return record


def extract_document_body(data):
    with OfficePackage(data, "docx") as package:
        body = child(package.xml("word/document.xml"), "body")
        if body is None:
            raise ValueError("invalid_document_structure")
        reader = DocumentReader()
        blocks = reader.blocks(body)
        revisions = sorted({tag(e) for e in body.iter() if tag(e) in REVISIONS})
        metadata = {
            "body_order": [b["id"] for b in blocks],
            "paragraph_count": reader.paragraph_count,
            "table_count": len(reader.tables),
            "cell_count": reader.cell_count,
            "tables": [{k: v for k, v in t.items() if k != "rows"} for t in reader.tables],
            "omitted_elements": sorted(reader.omitted),
            "detected_revision_markers": revisions,
        }
        if "docProps/core.xml" in package.names:
            for e in package.xml("docProps/core.xml"):
                if tag(e) in {"title", "creator", "subject"}:
                    metadata[{"creator": "author"}.get(tag(e), tag(e))] = (e.text or "")[:1000]
        warnings = [
            "Word references identify text sections, not rendered pages. Use paragraph/table/cell locators for precise attribution.",
            "Body and cell block order is retained. Table neighbors are structural context, not proof of a caption or policy relationship.",
            "Merged continuation cells retain their own stored text; origin values are never copied into blank cells. Omitted grid positions are not empty cells.",
            "Headers, footers, comments, footnotes/endnotes, images, equations, fields, styles and page layout are not rendered or evaluated. Tracked insertions/deletions are omitted and reported.",
        ]
        partial = bool(reader.omitted or revisions) or any(
            t["uncertainties"] for t in reader.tables
        )
        if partial:
            warnings.append(
                "Unsupported elements or unresolved table relationships remain; inspect omitted_elements and each table's uncertainties before drawing conclusions."
            )
        if len(json.dumps(metadata, ensure_ascii=True)) > 40000:
            raise ValueError("document_resource_limit")
        pages, total, encoded = [], 0, 0
        for record in reader.records:
            size = len(json.dumps(record, ensure_ascii=True))
            encoded += size
            if size > 32000 or encoded > 900000 or len(reader.records) > 5000:
                raise ValueError("document_resource_limit")
            text = record.get("text", "")
            if record["kind"] == "table":
                text = record.get("caption") or ""
            # Keep author text compatible with deterministic deadline/policy
            # readers. Locators belong in structured records and citations, not
            # in source titles (e.g. "[Paragraph 1] Exam 1").
            line = text if text.strip() else ""
            total += len(line) + 1
            if total > 240000:
                raise ValueError("document_resource_limit")
            if (
                not pages
                or len(pages[-1]["text"]) + len(line) > 8000
                or len(pages[-1]["records"]) >= 50
            ):
                pages.append(
                    {
                        "page": len(pages) + 1,
                        "text": "",
                        "state": "extracted",
                        "locator_kind": "section",
                        "extraction_method": "ooxml_document_structure",
                        "records": [],
                    }
                )
            pages[-1]["records"].append(record)
            pages[-1]["text"] += ("\n" if pages[-1]["text"] and line else "") + line
            if len(pages) > 200:
                raise ValueError("document_resource_limit")
        for page in pages:
            page["state"] = "extracted" if page["text"].strip() else "no_text"
        return metadata, pages, partial, warnings
