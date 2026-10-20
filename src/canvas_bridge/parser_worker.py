"""Standalone worker: no service imports, database, credentials or network use.

Only the OS-sandbox launcher may use this worker for live documents.
"""

import hashlib
import io
import json
import logging
import posixpath
import sys
import zipfile
from pathlib import Path

from defusedxml import ElementTree as ET
from pypdf import PdfReader

MAX_BYTES = 10_000_000
MAX_TEXT = 250_000
MAX_PAGES = 200
PARSER = "canvas-bridge-documents-v3"


def office(data: bytes, kind: str):
    """Bounded OOXML text only. Never extract files or resolve external relations."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 1000
            or sum(e.file_size for e in entries) > 20_000_000
            or len({e.filename for e in entries}) != len(entries)
            or any(
                e.file_size > 10_000_000
                or e.file_size > max(1, e.compress_size) * 200
                or e.flag_bits & 1
                for e in entries
            )
        ):
            raise ValueError("office_resource_limit")
        names = {e.filename for e in entries}
        if any("vbaproject" in n.lower() or "/embeddings/" in n.lower() for n in names):
            raise ValueError("active_office_content")

        def xml(name):
            return ET.fromstring(archive.read(name), forbid_dtd=True, forbid_entities=True)

        def tag(element):
            return element.tag.rsplit("}", 1)[-1]

        metadata = {}
        if "docProps/core.xml" in names:
            for e in xml("docProps/core.xml"):
                if tag(e) in {"title", "creator", "subject"}:
                    metadata[{"creator": "author"}.get(tag(e), tag(e))] = (e.text or "")[:1000]
        if kind == "docx":
            root = xml("word/document.xml")
            # Paragraph sections are stable within this document version. Word
            # pagination depends on the renderer, fonts and printer settings.
            texts = [
                "".join(
                    (e.text or "")
                    if tag(e) == "t"
                    else "\t"
                    if tag(e) == "tab"
                    else "\n"
                    if tag(e) == "br"
                    else ""
                    for e in p.iter()
                )
                for p in root.iter()
                if tag(p) == "p"
            ]
            # Bound section count while preserving complete paragraph order.
            grouped = []
            for text in texts:
                if not grouped or len(grouped[-1]) + len(text) > 8000:
                    grouped.append(text)
                else:
                    grouped[-1] += "\n" + text
            return metadata, grouped, "section"
        relationships = {
            e.attrib["Id"]: e.attrib.get("Target", "")
            for e in xml("ppt/_rels/presentation.xml.rels")
            if e.attrib.get("TargetMode", "Internal") != "External"
            and e.attrib.get("Type", "").endswith("/slide")
        }
        texts = []
        for e in xml("ppt/presentation.xml").iter():
            if tag(e) != "sldId":
                continue
            relation = next((v for k, v in e.attrib.items() if k.endswith("}id")), None)
            target = relationships.get(relation, "")
            path = posixpath.normpath("ppt/" + target)
            if not target or not path.startswith("ppt/slides/") or path not in names:
                raise ValueError("invalid_slide_reference")
            texts.append(
                "\n".join(
                    "".join(t.text or "" for t in p.iter() if tag(t) == "t")
                    for p in xml(path).iter()
                    if tag(p) == "p"
                )
            )
        return metadata, texts, "slide"


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
    elif kind in {"docx", "pptx"}:
        metadata, sections, locator_kind = office(data, kind)
        page_count = len(sections)
        if page_count > MAX_PAGES:
            raise ValueError("too_many_pages")
        for index, text in enumerate(sections, 1):
            remaining = max(0, MAX_TEXT - total - (2 if pages else 0))
            state = "extracted" if text.strip() else "no_text"
            if len(text) > remaining:
                text, state, coverage = text[:remaining], "truncated", "partial"
            if not text.strip():
                coverage = "partial"
            pages.append(
                {"page": index, "text": text, "state": state, "locator_kind": locator_kind}
            )
            total += len(text) + (2 if index > 1 else 0)
            if total >= MAX_TEXT:
                break
        warnings.append(
            "Word references identify text sections, not rendered pages."
            if kind == "docx"
            else "Slide numbers follow presentation order. Speaker notes, animations and image text are not extracted."
        )
        warnings.append(
            "Headers, footers, comments, tracked changes, embedded objects and layout are not interpreted; table text may lose structure."
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
            "office_resource_limit",
            "active_office_content",
            "invalid_slide_reference",
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
