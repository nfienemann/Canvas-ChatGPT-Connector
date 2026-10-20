"""Standalone worker: no service imports, database, credentials or network use.

Only the OS-sandbox launcher may use this worker for live documents.
"""

import hashlib
import io
import json
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

MAX_BYTES = 10_000_000
MAX_TEXT = 250_000
MAX_PAGES = 200
PARSER = "canvas-bridge-pypdf-6.21.1-v2"


def extract(data: bytes, kind: str) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("file_too_large")
    warnings = [
        "Figures, charts, equations and table structure have not been visually interpreted."
    ]
    metadata, pages = {}, []
    coverage, total, page_count = "text_only", 0, 1
    if kind == "pdf":
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted_pdf")
        page_count = len(reader.pages)
        if page_count > MAX_PAGES:
            raise ValueError("too_many_pages")
        if b"/JavaScript" in data or b"/Launch" in data:
            warnings.append(
                "PDF interactive actions are ignored. Scripts, links and attachments are never executed or opened."
            )
        metadata = {
            key: str((reader.metadata or {}).get(source, ""))[:1000]
            for key, source in (("title", "/Title"), ("author", "/Author"), ("subject", "/Subject"))
        }
        for number, page in enumerate(reader.pages, 1):
            content = page.get_contents()
            if content and len(content.get_data()) > 10_000_000:
                coverage = "partial"
                warnings.append(f"Page {number}: content stream exceeds extraction limits.")
                pages.append({"page": number, "text": "", "state": "resource_limit"})
                continue
            text = page.extract_text() or ""
            state = "extracted" if text.strip() else "no_text"
            if not text.strip():
                coverage = "partial"
                warnings.append(f"Page {number}: no text layer; OCR or visual reading is required.")
            separator = 2 if pages else 0
            remaining = max(0, MAX_TEXT - total - separator)
            if len(text) > remaining:
                text, coverage, state = text[:remaining], "partial", "truncated"
                warnings.append(
                    f"Page {number}: text limit reached; remaining content was not extracted."
                )
            pages.append({"page": number, "text": text, "state": state})
            total += len(text) + separator
            if total >= MAX_TEXT:
                break
        warnings.append(
            "Page numbers are PDF page positions, not printed journal pagination. Reading order may be imperfect in multi-column papers."
        )
    elif kind in {"txt", "md"}:
        raw = data.decode("utf-8-sig")
        if len(raw) > MAX_TEXT:
            coverage = "partial"
            warnings.append("Document exceeded the text extraction limit.")
        pages = [{"page": 1, "text": raw[:MAX_TEXT], "state": "extracted"}]
        warnings.append("Plain text/Markdown has no intrinsic pages; page 1 denotes the document.")
    else:
        raise ValueError("unsupported_format")
    if not any(p["text"].strip() for p in pages):
        coverage = "partial"
        warnings.append(
            "No readable text was extracted. Do not infer this document's subject from its filename."
        )
    return {
        "format": kind,
        "content_hash": hashlib.sha256(data).hexdigest(),
        "parser": PARSER,
        "metadata": metadata,
        "pages": pages,
        "page_count": page_count,
        "coverage": coverage,
        "warnings": warnings,
    }


def main():
    logging.disable(logging.CRITICAL)
    root = Path(sys.argv[1])
    try:
        request = json.loads((root / "request.json").read_text(encoding="utf-8"))
        with (root / "input.bin").open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        result = {"ok": True, "extraction": extract(data, request["kind"])}
    except Exception as exc:
        # Never return parser exception text: it may contain private document data.
        known = {
            "file_too_large",
            "encrypted_pdf",
            "too_many_pages",
            "active_pdf_content",
            "unsupported_format",
        }
        reason = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc) in known
            else "corrupt_or_unreadable"
        )
        result = {"ok": False, "reason": reason}
    encoded = json.dumps(result, ensure_ascii=True)
    if len(encoded) > 2_000_000:
        encoded = json.dumps({"ok": False, "reason": "output_limit"})
    (root / "result.json").write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
