"""Bounded structured ranges from the existing owner-scoped document cache."""

import json
import re

from openpyxl.utils.cell import range_boundaries

from canvas_bridge.course_files import authorized, checked_row, read_file, source
from canvas_bridge.domain import DomainError, Result


async def read_workbook(
    bridge,
    owner,
    ref,
    file_id,
    sheet_name=None,
    cell_range=None,
    query=None,
    max_cells=100,
    offset=0,
    expected_hash=None,
):
    if not 1 <= max_cells <= 200 or not 0 <= offset <= 5000:
        raise DomainError("needs_input", "Use max_cells 1–200 and a valid continuation offset.")
    if offset and expected_hash is None:
        raise DomainError("needs_input", "Workbook continuation requires its content hash.")
    if cell_range and (
        not sheet_name
        or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?", cell_range)
    ):
        raise DomainError("needs_input", "Choose a sheet and an A1 range such as A1:F25.")
    bounds = range_boundaries(cell_range) if cell_range else None
    if bounds and (
        bounds[0] > bounds[2] or bounds[1] > bounds[3] or bounds[2] > 16384 or bounds[3] > 1048576
    ):
        raise DomainError("needs_input", "The cell range is reversed or outside Excel limits.")
    if query is not None and not 1 <= len(query.strip()) <= 200:
        raise DomainError("needs_input", "Use a nonempty search of at most 200 characters.")
    result = await read_file(bridge, owner, ref, file_id, length=1, expected_hash=expected_hash)
    if result.data.get("format") != "xlsx":
        if result.status != "ok" and result.status != "partial_data":
            return result
        raise DomainError("unsupported_feature", "This file is not an extracted XLSX workbook.")
    # Reuse the existing permission/version fence; do not duplicate its policy.
    _, _, _, epoch = await authorized(bridge, owner, ref, file_id)
    with bridge.store.transaction() as session:
        row = checked_row(bridge, session, owner, ref, file_id, epoch)
        if row.version_hash != result.data["content_hash"]:
            raise DomainError("source_changed", "Workbook changed during range retrieval.")
    metadata = row.file_state["metadata"]
    sheets = metadata["worksheets"]
    if sheet_name is not None and not any(s["name"] == sheet_name for s in sheets):
        raise DomainError(
            "needs_input", "Sheet not found. Read the workbook overview for exact worksheet names."
        )
    all_cells = [
        c
        for p in row.locators
        for c in p.get("cells", [])
        if sheet_name is None or p.get("sheet") == sheet_name
    ]
    matches = []
    for cell in all_cells:
        if bounds and not (
            bounds[0] <= cell["column"] <= bounds[2] and bounds[1] <= cell["row"] <= bounds[3]
        ):
            continue
        if (
            query
            and query.casefold()
            not in " ".join(
                str(cell.get(k, "")) for k in ("sheet", "value", "formula", "cached_value")
            ).casefold()
        ):
            continue
        matches.append(cell)
    # Overview first, unless a query explicitly requests search across sheets.
    if offset > len(matches) or (offset and not (sheet_name or query)):
        raise DomainError(
            "needs_input", "Continuation offset exceeds this selection's extracted cells."
        )
    selected = matches[offset : offset + max_cells] if sheet_name or query else []
    records, sources, response_size = [], [], 0
    for cell in selected:
        quoted_sheet = cell["sheet"].replace("'", "''")
        citation = source(row, f"'{quoted_sheet}'!{cell['address']}")
        sheet = next(s for s in sheets if s["name"] == cell["sheet"])
        merged = []
        for region in sheet["merged_regions"]:
            left, top, right, bottom = range_boundaries(region)
            if left <= cell["column"] <= right and top <= cell["row"] <= bottom:
                merged.append(region)
        record = {
            **cell,
            "merged_regions": merged,
            "source_reference": citation.model_dump(mode="json"),
        }
        size = len(json.dumps(record, ensure_ascii=True))
        if response_size + size > 60000:
            if not records:
                raise DomainError(
                    "unsupported_feature",
                    "This cell and its provenance exceed the response limit; no empty-cell conclusion is supported.",
                )
            break
        response_size += size
        records.append(record)
        sources.append(citation)
    next_offset = (
        offset + len(records) if records and offset + len(records) < len(matches) else None
    )
    return Result(
        status=result.status,
        summary="Stored workbook cells and formulas. Cached formula results are separate, may be stale, and have not been recomputed.",
        data={
            "file_id": file_id,
            "filename": row.title,
            "format": "xlsx",
            "workbook": metadata,
            "content_hash": row.version_hash,
            "source_version": row.file_state["version"],
            "sheet_name": sheet_name,
            "requested_range": cell_range,
            "cells": records,
            "matching_extracted_cells": len(matches) if sheet_name or query else None,
            "coverage": row.file_state["coverage"],
            "limitations": row.limitations,
            "blank_cells": "Not emitted. Only complete sheet coverage supports treating unreturned coordinates as blank.",
            "formula_evaluation": "not_performed",
            "content_boundary": "untrusted_source_data",
            "continuation": {
                "file_id": file_id,
                "sheet_name": sheet_name,
                "cell_range": cell_range,
                "query": query,
                "offset": next_offset,
                "max_cells": max_cells,
                "expected_hash": row.version_hash,
            }
            if next_offset is not None
            else None,
        },
        sources=sources or [source(row)],
        meta=bridge.meta(),
    )
