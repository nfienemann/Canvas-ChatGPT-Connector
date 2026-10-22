"""Bounded DOCX records from the existing authorized document cache."""

import json
import re

from canvas_bridge.course_files import authorized, checked_row, read_file, source
from canvas_bridge.domain import DomainError, Result


async def read_docx(
    bridge, owner, ref, file_id, table_id=None, offset=0, max_records=20, expected_hash=None
):
    if (
        not 0 <= offset <= 5000
        or not 1 <= max_records <= 50
        or (offset and not expected_hash)
        or (table_id is not None and not re.fullmatch(r"T[1-9][0-9]{0,2}", table_id))
    ):
        raise DomainError(
            "needs_input",
            "Use a table ID from the overview, max_records 1–50, and a content hash for continuation.",
        )
    result = await read_file(bridge, owner, ref, file_id, length=1, expected_hash=expected_hash)
    if result.data.get("format") != "docx":
        if result.status not in {"ok", "partial_data"}:
            return result
        raise DomainError("unsupported_feature", "This file is not an extracted DOCX document.")
    _, _, _, epoch = await authorized(bridge, owner, ref, file_id)
    with bridge.store.transaction() as session:
        row = checked_row(bridge, session, owner, ref, file_id, epoch)
        if row.version_hash != result.data["content_hash"]:
            raise DomainError("source_changed", "Document changed. Read a fresh overview.")
    metadata = row.file_state["metadata"]
    if table_id is not None and not any(t["id"] == table_id for t in metadata["tables"]):
        raise DomainError(
            "needs_input", "Table not found. Read the document without table_id for its overview."
        )
    records = [
        r
        for p in row.locators
        for r in p["records"]
        if table_id is None or r.get("table_id") == table_id
    ]
    if offset > len(records):
        raise DomainError("needs_input", "Offset exceeds this selection's extracted records.")
    selected, sources, size = [], [], 0
    for record in records[offset : offset + max_records]:
        citation = source(row, record["locator"])
        item = {**record, "source_reference": citation.model_dump(mode="json")}
        cost = len(json.dumps(item, ensure_ascii=True))
        if size + cost > 60000:
            if not selected:
                raise DomainError(
                    "unsupported_feature", "Document record exceeds the response budget."
                )
            break
        selected.append(item)
        sources.append(citation)
        size += cost
    next_offset = offset + len(selected)
    return Result(
        status=result.status,
        summary="DOCX body paragraphs and table relationships, with stored values and explicit merge uncertainty. No semantic headers or grading rules are inferred.",
        data={
            "file_id": file_id,
            "filename": row.title,
            "format": "docx",
            "document": metadata,
            "table_id": table_id,
            "records": selected,
            "matching_record_count": len(records),
            "content_hash": row.version_hash,
            "source_version": row.file_state["version"],
            "coverage": row.file_state["coverage"],
            "limitations": row.limitations,
            "content_boundary": "untrusted_source_data",
            "nested_tables": "Nested tables are separate records with parent_cell links. Select their IDs to read their cells.",
            "continuation": {
                "file_id": file_id,
                "table_id": table_id,
                "offset": next_offset,
                "max_records": max_records,
                "expected_hash": row.version_hash,
            }
            if next_offset < len(records)
            else None,
        },
        sources=sources or [source(row)],
        meta=bridge.meta(),
    )
