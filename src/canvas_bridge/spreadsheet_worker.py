"""Bounded, inert SpreadsheetML extraction; also copied into the OS sandbox.

No formula evaluation, external references, ZIP extraction or grid expansion.
Each text line is JSON, so newlines and formula-like strings remain source data.
Numeric lexical values and number formats are preserved instead of coerced.
"""

import io
import json
import posixpath
import re
import zipfile

from defusedxml import ElementTree as ET

MAX_CELLS = 50_000
MAX_SHEETS = 200
CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")
BUILTIN_FORMATS = {
    0: "General",
    1: "0",
    2: "0.00",
    9: "0%",
    10: "0.00%",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
    49: "@",
}


def tag(element):
    return element.tag.rsplit("}", 1)[-1]


def child(element, name):
    return next((e for e in element if tag(e) == name), None)


def children(element, name):
    return [e for e in element if tag(e) == name]


def true(value):
    return value in {"1", "true"}


def position(ref):
    match = CELL.fullmatch(ref)
    if not match:
        raise ValueError("invalid_workbook_structure")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - 64
    row = int(match[2])
    if column > 16384 or row > 1048576:
        raise ValueError("invalid_workbook_structure")
    return row, column


def reference(row, column):
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def rich_text(element):
    if element is None:
        return ""
    # Phonetic annotations are not an extra copy of the cell's value.
    return unescape(
        "".join(
            e.text or ""
            for item in element
            if tag(item) in {"t", "r"}
            for e in item.iter()
            if tag(e) == "t"
        )
    )


def unescape(value):
    # ST_Xstring escapes are decoded once: _x005F_x0041_ is literal _x0041_.
    text = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m[1], 16)), value)
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le")


def typed_value(cell, strings):
    kind = cell.get("t", "n")
    if kind not in {"n", "b", "s", "str", "inlineStr", "e", "d"}:
        raise ValueError("unsupported_workbook_cell_type")
    if any(len(children(cell, name)) > 1 for name in ("v", "f", "is")):
        raise ValueError("invalid_workbook_structure")
    value = child(cell, "v")
    raw = value.text if value is not None else None
    if kind == "inlineStr":
        return {"type": "string", "value": rich_text(child(cell, "is"))}
    if kind == "str" and value is not None:
        return {"type": "string", "value": unescape(raw or "")}
    if raw is None:
        return {"type": "blank", "value": None}
    if kind == "s":
        index = int(raw)
        if not 0 <= index < len(strings):
            raise ValueError("invalid_workbook_structure")
        return {"type": "string", "value": strings[index]}
    if kind == "b":
        if raw not in {"0", "1"}:
            raise ValueError("invalid_workbook_structure")
        return {"type": "boolean", "value": raw == "1"}
    if kind == "n":
        if not NUMBER.fullmatch(raw):
            raise ValueError("invalid_workbook_structure")
        return {"type": "number", "value": raw}
    if kind in {"str", "e", "d"}:
        return {"type": {"str": "string", "e": "error", "d": "iso_date"}[kind], "value": raw}
    raise ValueError("unsupported_workbook_cell_type")


def extract_workbook(data, max_text):
    warnings = [
        "Workbook text is JSON lines: one sheet header, then one record per stored cell. Missing cells are not zero; absent grid cells are not expanded.",
        "Formulas are source text, never evaluated. Cached results may be absent or stale; shared/array formula attributes are preserved without expanding or recalculating them.",
        "Numbers retain their stored lexical value. Dates stored as numbers retain the number format and workbook date system; no localized display or date conversion is inferred.",
        "Hidden sheets, rows and columns are included and labeled. Merged ranges are listed without duplicating the anchor value.",
        "Charts, images, comments, pivot tables, conditional formatting and layout are not interpreted. Links and external data are never fetched.",
    ]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = {e.filename for e in entries}
        if (
            len(entries) > 1000
            or len(names) != len(entries)
            or sum(e.file_size for e in entries) > 20_000_000
            or any(
                e.file_size > 10_000_000
                or e.flag_bits & 1
                or e.file_size > max(1, e.compress_size) * 200
                for e in entries
            )
        ):
            raise ValueError("office_resource_limit")
        if any(
            "vbaproject" in n.lower()
            or "/embeddings/" in n.lower()
            or "/macrosheets/" in n.lower()
            or "/activex/" in n.lower()
            for n in names
        ):
            raise ValueError("active_office_content")

        def xml(name):
            return ET.fromstring(archive.read(name), forbid_dtd=True, forbid_entities=True)

        if "[Content_Types].xml" in names and any(
            "macroenabled" in e.get("ContentType", "").lower() for e in xml("[Content_Types].xml")
        ):
            raise ValueError("active_office_content")
        workbook = xml("xl/workbook.xml")
        if tag(workbook) != "workbook":
            raise ValueError("invalid_workbook_structure")
        relationships = {}
        for e in xml("xl/_rels/workbook.xml.rels"):
            identity = e.get("Id")
            if not identity or identity in relationships:
                raise ValueError("invalid_workbook_structure")
            relationships[identity] = e

        def target(relation, expected):
            if relation is None or not relation.get("Type", "").endswith("/" + expected):
                raise ValueError("invalid_workbook_reference")
            name = relation.get("Target", "")
            if (
                relation.get("TargetMode", "Internal") != "Internal"
                or not name
                or "\\" in name
                or ":" in name
                or ".." in name.split("/")
            ):
                raise ValueError("invalid_workbook_reference")
            path = posixpath.normpath(name.lstrip("/") if name.startswith("/") else "xl/" + name)
            if not path.startswith("xl/") or path not in names:
                raise ValueError("invalid_workbook_reference")
            return path

        def optional_part(kind):
            relations = [
                r for r in relationships.values() if r.get("Type", "").endswith("/" + kind)
            ]
            if len(relations) > 1:
                raise ValueError("invalid_workbook_structure")
            return xml(target(relations[0], kind)) if relations else None

        shared = optional_part("sharedStrings")
        strings = [rich_text(e) for e in shared] if shared is not None else []
        if len(strings) > MAX_CELLS:
            raise ValueError("workbook_resource_limit")
        styles_root = optional_part("styles")
        styles, formats = [], {}
        if styles_root is not None:
            for e in styles_root:
                if tag(e) == "numFmts":
                    formats = {int(n.attrib["numFmtId"]): n.attrib["formatCode"] for n in e}
                elif tag(e) == "cellXfs":
                    styles = [int(s.get("numFmtId", "0")) for s in e]
        props = child(workbook, "workbookPr")
        date_system = "1904" if props is not None and true(props.get("date1904")) else "1900"
        sheet_list = child(workbook, "sheets")
        sheets = children(sheet_list, "sheet") if sheet_list is not None else []
        if not sheets or len(sheets) > MAX_SHEETS:
            raise ValueError("workbook_resource_limit")
        if len({s.get("name") for s in sheets}) != len(sheets):
            raise ValueError("invalid_workbook_structure")
        pages, total, count, truncated = [], 0, 0, False
        sheet_metadata = []
        for index, sheet in enumerate(sheets, 1):
            name = sheet.get("name", "")
            state = sheet.get("state", "visible")
            if not name or len(name) > 128 or state not in {"visible", "hidden", "veryHidden"}:
                raise ValueError("invalid_workbook_structure")
            sheet_metadata.append({"index": index, "name": name, "state": state})
        for index, sheet in enumerate(sheets, 1):
            relation = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), None)
            root = xml(target(relationships.get(relation), "worksheet"))
            if tag(root) != "worksheet":
                raise ValueError("invalid_workbook_structure")
            merges, columns = [], []
            for e in root:
                if tag(e) == "mergeCells":
                    for merge in e:
                        ref = merge.attrib["ref"]
                        ends = ref.split(":")
                        if len(ends) != 2 or any(
                            a > b for a, b in zip(position(ends[0]), position(ends[1]), strict=True)
                        ):
                            raise ValueError("invalid_workbook_structure")
                        merges.append(ref)
                elif tag(e) == "cols":
                    for col in e:
                        low, high = int(col.attrib["min"]), int(col.attrib["max"])
                        if not 1 <= low <= high <= 16384:
                            raise ValueError("invalid_workbook_structure")
                        columns.append(
                            {
                                "min": low,
                                "max": high,
                                "hidden": true(col.get("hidden")),
                                "style": col.get("style"),
                            }
                        )
            if len(merges) + len(columns) > MAX_CELLS:
                raise ValueError("workbook_resource_limit")
            info = sheet_metadata[index - 1]
            header = {
                "sheet": info["name"],
                "sheet_index": index,
                "state": info["state"],
                "date_system": date_system,
                "merged_ranges": merges,
                "hidden_columns": [
                    {"min": c["min"], "max": c["max"]} for c in columns if c["hidden"]
                ],
            }
            text = json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n"
            remaining = max_text - total - (2 if pages else 0)
            if len(text) > remaining:
                truncated = True
                break
            spans, seen, last_row = [], set(), 0
            grid = child(root, "sheetData")
            for row in [] if grid is None else grid:
                if tag(row) != "row":
                    continue
                cells = children(row, "c")
                first_reference = next((cell.get("r") for cell in cells if cell.get("r")), None)
                inferred_row = position(first_reference)[0] if first_reference else last_row + 1
                row_number = int(row.get("r", str(inferred_row)))
                if not last_row < row_number <= 1048576:
                    raise ValueError("invalid_workbook_structure")
                last_row, last_col = row_number, 0
                for cell in cells:
                    count += 1
                    if count > MAX_CELLS:
                        truncated = True
                        break
                    ref = cell.get("r", reference(row_number, last_col + 1))
                    number, column = position(ref)
                    if number != row_number or column <= last_col or ref in seen:
                        raise ValueError("invalid_workbook_structure")
                    seen.add(ref)
                    last_col = column
                    matching = [c for c in columns if c["min"] <= column <= c["max"]]
                    style = cell.get("s", row.get("s") if true(row.get("customFormat")) else None)
                    if style is None and matching:
                        style = matching[-1]["style"]
                    if style is None and styles:
                        style = "0"
                    record = {"cell": ref, **typed_value(cell, strings)}
                    if style is not None:
                        style_index = int(style)
                        if not 0 <= style_index < len(styles):
                            raise ValueError("invalid_workbook_structure")
                        fmt = styles[style_index]
                        record.update(
                            number_format_id=fmt,
                            number_format=formats.get(fmt, BUILTIN_FORMATS.get(fmt)),
                        )
                    formula = child(cell, "f")
                    if formula is not None:
                        value = child(cell, "v")
                        record = {
                            "cell": ref,
                            "type": "formula",
                            "formula": formula.text,
                            "formula_attributes": dict(formula.attrib),
                            "cached_value_present": value is not None
                            and (value.text is not None or cell.get("t") == "str"),
                            "cached_value": {k: v for k, v in record.items() if k != "cell"},
                        }
                    if true(row.get("hidden")):
                        record["hidden_row"] = True
                    if any(c["hidden"] for c in matching):
                        record["hidden_column"] = True
                    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    if len(text) + len(line) > remaining:
                        truncated = True
                        break
                    spans.append({"cell": ref, "start": len(text), "end": len(text) + len(line)})
                    text += line
                if truncated:
                    break
            pages.append(
                {
                    "page": index,
                    "text": text,
                    "state": "truncated" if truncated else "extracted",
                    "locator_kind": "sheet",
                    "sheet_name": info["name"],
                    "sheet_state": info["state"],
                    "cell_spans": spans,
                    "extraction_method": "stored_workbook_cells",
                }
            )
            total += len(text) + (2 if index > 1 else 0)
            if truncated:
                break
        if truncated:
            warnings.append(
                "Workbook cell/text budget reached; remaining cells or sheets were not extracted. No oversized cell is partially emitted."
            )
        return {
            "metadata": {"date_system": date_system, "sheets": sheet_metadata},
            "pages": pages,
            "page_count": len(sheets),
            "coverage": "partial" if truncated else "text_only",
            "warnings": warnings,
        }
