"""Document outcomes are distinct from generic extraction cautions."""

import re

OCR_DIAGNOSTICS_VERSION = 2
ZERO_TEXT_WARNING = "No readable text was extracted."


def safe_ocr_failure(failure):
    """Historical cached locators and fresh worker errors use the same projection."""
    from canvas_bridge.domain import Result
    from canvas_bridge.egress_errors import safe_error_result

    data = failure if isinstance(failure, dict) else {}
    status = data.get("status", "operation_failed")
    if status not in (
        "operation_failed",
        "unsupported_feature",
        "retry_later",
        "permission_denied",
    ):
        status = "operation_failed"
    clean = safe_error_result(Result(status=status, summary="", data=data))
    fields = (
        "reason_code",
        "processing_stage",
        "worker_exit_code",
        "retry_after_seconds",
        "timeout_stage",
        "deadline_seconds",
        "page_start",
        "page_end",
    )
    return {"status": status, **{key: clean.data[key] for key in fields if key in clean.data}}


def diagnostics(pages, warnings, page_count, kind=None):
    usable = any(p.get("text", "").strip() for p in pages)
    warnings = [w for w in warnings if not (usable and w.startswith(ZERO_TEXT_WARNING))]
    specific, generic = [], []
    for warning in warnings:
        page_match = re.match(r"Page (\d+):", warning)
        if page_match or warning.startswith((ZERO_TEXT_WARNING, "Document exceeded")):
            specific.append(
                {
                    "scope": "page" if page_match else "document",
                    "page": int(page_match[1]) if page_match else None,
                    "message": warning,
                }
            )
        else:
            generic.append(warning)
    attempted = [
        p
        for p in pages
        if p.get("ocr_status") in {"extracted", "failed", "unusable"}
        or p.get("ocr_confidence") is not None
        or p.get("ocr_failure")
    ]
    accepted = [
        p for p in pages if p.get("state") == "ocr_extracted" or p.get("ocr_status") == "extracted"
    ]
    failed = [p for p in attempted if p.get("ocr_failure")]
    specific.extend(
        {
            "scope": "page",
            "page": p["page"],
            "message": "OCR processing failed for this page.",
            **safe_ocr_failure(p["ocr_failure"]),
        }
        for p in failed
    )
    unit = {
        "pdf": "page",
        "pptx": "slide",
        "xlsx": "sheet",
        "docx": "section",
        "txt": "document",
        "md": "document",
    }.get(kind, "unit")
    text_cap = any(w.startswith("Document exceeded") for w in warnings)
    usable_units = sum(
        bool(p.get("text", "").strip())
        and (not p.get("sparse_image_text") or p.get("state") == "ocr_extracted")
        for p in pages
    )
    outcomes = []
    for page in pages:
        state = page.get("state")
        if state == "ocr_extracted":
            outcome = "ocr_extracted"
        elif page.get("ocr_failure"):
            outcome = "failed"
        elif state in {"truncated", "resource_limit"}:
            outcome = "extraction_limit"
        elif page.get("sparse_image_text"):
            outcome = "sparse"
        elif page.get("ocr_status") == "skipped_budget":
            outcome = "skipped_budget"
        elif kind in {"txt", "md"} and text_cap:
            outcome = "extraction_limit"
        elif page.get("text", "").strip():
            outcome = "extracted"
        elif kind in {"txt", "md"} and not text_cap:
            outcome = "empty_verified"
        else:
            outcome = "no_usable_text"
        outcomes.append({"position": page["page"], "state": outcome})
    extraction = {
        "unit_kind": unit,
        "total_units": page_count,
        "attempted_units": len(pages),
        "remaining_unattempted": max(0, page_count - len(pages)),
        "units_with_usable_text": usable_units,
        "unit_outcomes": outcomes,
        "continuation_scope": "pdf_page_batches"
        if kind == "pdf" and len(pages) < page_count and not text_cap
        else "extracted_text_only",
        "extraction_limited": len(pages) < page_count
        or any(item["state"] == "extraction_limit" for item in outcomes)
        or text_cap,
    }
    return {
        "unit_coverage": extraction,
        "limitations": warnings,
        "document_diagnostics": specific,
        "parser_warnings": generic,
        "ocr_coverage": {
            "document_pages": page_count,
            "attempted_pages": len(attempted),
            "accepted_pages": len(accepted),
            "failed_pages": len(failed),
            "skipped_budget_pages": sum(p.get("ocr_status") == "skipped_budget" for p in pages),
            "pages_with_usable_text": usable_units,
            "text_positions_complete": bool(pages)
            and not extraction["extraction_limited"]
            and len(pages) == page_count
            and all(
                p.get("text", "").strip()
                and p.get("state") not in {"truncated", "resource_limit"}
                and (not p.get("sparse_image_text") or p.get("state") == "ocr_extracted")
                for p in pages
            ),
        },
        "ocr_confidence": {
            "scale": "0_to_100",
            "pages": [
                {
                    "page": p["page"],
                    "mean_confidence": p.get("ocr_confidence"),
                    "accepted": p in accepted,
                }
                for p in attempted
            ],
            "meaning": "Recognition confidence is separate from page coverage and does not verify dates or table structure.",
        },
    }
