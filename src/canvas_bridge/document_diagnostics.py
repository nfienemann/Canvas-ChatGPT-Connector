"""Document outcomes are distinct from generic extraction cautions."""

import re

OCR_DIAGNOSTICS_VERSION = 1
ZERO_TEXT_WARNING = "No readable text was extracted."


def diagnostics(pages, warnings, page_count):
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
    accepted = [p for p in pages if p.get("state") == "ocr_extracted"]
    failed = [p for p in attempted if p.get("ocr_failure")]
    specific.extend(
        {
            "scope": "page",
            "page": p["page"],
            "message": "OCR processing failed for this page.",
            **p["ocr_failure"],
        }
        for p in failed
    )
    return {
        "limitations": warnings,
        "document_diagnostics": specific,
        "parser_warnings": generic,
        "ocr_coverage": {
            "document_pages": page_count,
            "attempted_pages": len(attempted),
            "accepted_pages": len(accepted),
            "failed_pages": len(failed),
            "skipped_budget_pages": sum(p.get("ocr_status") == "skipped_budget" for p in pages),
            "pages_with_usable_text": sum(bool(p.get("text", "").strip()) for p in pages),
            "text_positions_complete": bool(pages)
            and len(pages) == page_count
            and all(
                p.get("text", "").strip() and p.get("state") not in {"truncated", "resource_limit"}
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
