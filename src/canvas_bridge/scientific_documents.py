"""Bounded document projection for existing authorized read tools."""

import json


def document_model(row, pages):
    kind = row.file_state["format"]
    units, budget, omitted = [], 60_000, []
    for page in pages:
        locator_kind = page.get("locator_kind", "page" if kind == "pdf" else "document")
        unit = {
            "original_number": page["page"],
            "locator_kind": locator_kind,
            "locator": f"{locator_kind.capitalize()} {page['page']}",
            "source_file_id": row.id,
            "content_hash": row.version_hash,
            "structure": page.get("structure"),
            "extraction_state": page["state"],
            "hidden": page.get("hidden"),
            "visual_inspection_status": "not_performed",
            "structure_status": "available" if page.get("structure") else "unavailable_or_withheld",
        }
        size = len(json.dumps(unit, ensure_ascii=True).encode())
        if size > budget:
            omitted.append(page["page"])
            continue
        units.append(unit)
        budget -= size
    return {
        "schema_version": "scientific-document-3",
        "source_file_id": row.id,
        "content_hash": row.version_hash,
        "source_version": row.file_state.get("version"),
        "format": kind,
        "original_unit_count": row.file_state["page_count"],
        "units": units,
        "structure_units_omitted": omitted,
        "source_permissions": {
            "inherit_from_source": row.id,
            "course_id": row.course_id,
            "authority": "existing_source_authorization_and_final_recipient_egress",
            "untrusted_content": True,
            "grants_access": False,
        },
        "comprehension_status": "not_established",
        "limitations": [
            "This is a source structure index, not a claim of scientific comprehension.",
            "Word locators identify original paragraphs/tables/equations, not rendered page numbers.",
            "Table cells, merged ranges and mathematical operators remain structured; missing structure is not inferred.",
        ]
        + (
            [
                "Structure output budget reached. Request omitted original units explicitly; oversized individual structures require visual inspection."
            ]
            if omitted
            else []
        ),
    }
