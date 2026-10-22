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

if __package__:
    from canvas_bridge.spreadsheet_worker import extract_workbook
else:
    from spreadsheet_worker import extract_workbook

MAX_BYTES = 10_000_000
MAX_TEXT = 250_000
MAX_PAGES = 200
PARSER = "canvas-bridge-documents-v6-docx"
SUPPORTED_FORMATS = ("pdf", "docx", "pptx", "txt", "md", "xlsx")


def word_paragraphs(root):
    """Read each Word text node once, in XML order, without resolving links.

    Nested text boxes have their own paragraphs. Walking every paragraph's
    descendants independently duplicates their contents in the enclosing run.
    Use boundary events instead; surrounding runs remain separate text blocks.
    """
    namespace = root.tag.removesuffix("document")
    if namespace not in {
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
        "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
    }:
        raise ValueError("invalid_docx_structure")
    bodies = root.findall(namespace + "body")
    if len(bodies) != 1:
        raise ValueError("invalid_docx_structure")
    compatibility = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    text, paragraphs = [], []
    stack = [bodies[0]]
    while stack:
        element = stack.pop()
        if element is None:
            if text:
                paragraphs.append("".join(text))
                text = []
            continue
        if element.tag in {namespace + "del", namespace + "moveFrom"}:
            continue
        if element.tag == compatibility + "AlternateContent":
            # Do not concatenate mutually exclusive representations. We do not
            # implement extension namespaces, so use only the portable fallback.
            fallback = element.find(compatibility + "Fallback")
            if fallback is not None:
                stack.append(fallback)
            continue
        if element.tag == namespace + "p":
            if text:
                paragraphs.append("".join(text))
                text = []
            stack.append(None)
        if element.tag == namespace + "t":
            text.append(element.text or "")
        elif element.tag in {namespace + "br", namespace + "cr"}:
            text.append("\n")
        elif element.tag == namespace + "tab":
            text.append("\t")
        elif element.tag == namespace + "noBreakHyphen":
            text.append("\u2011")
        elif element.tag == namespace + "softHyphen":
            text.append("\u00ad")
        stack.extend(reversed(element))
    if text:
        paragraphs.append("".join(text))
    # Even an empty document needs a valid section for a partial/no-text read.
    return paragraphs or [""]


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
            if "word/document.xml" not in names:
                raise ValueError("invalid_docx_structure")
            root = xml("word/document.xml")
            # Paragraph sections are stable within this document version. Word
            # pagination depends on the renderer, fonts and printer settings.
            texts = word_paragraphs(root)
            # Bound section count while preserving complete paragraph order.
            grouped = []
            for text in texts:
                if not grouped or len(grouped[-1]) + 1 + len(text) > 8000:
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
            text = (page.extract_text() or "").strip()
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
            pages.append(
                {"page": number, "text": text, "state": state, "extraction_method": "embedded_text"}
            )
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
                if state == "truncated" or index < page_count:
                    coverage = "partial"
                    warnings.append(
                        f"{locator_kind.capitalize()} {index}: text limit reached; remaining content was not extracted."
                    )
                break
        warnings.append(
            "Word references identify text sections, not rendered pages."
            if kind == "docx"
            else "Slide numbers follow presentation order. Speaker notes, animations and image text are not extracted."
        )
        warnings.append(
            "Headers, footers, footnotes/endnotes, comments, equations, embedded objects and layout are not interpreted; table text may lose structure."
        )
        if kind == "docx":
            warnings.extend(
                [
                    "DOCX text uses XML order, including text boxes once; visual placement, heading hierarchy and automatic list numbering are not reconstructed. Empty paragraphs are omitted.",
                    "Inserted and moved-to text is included; deleted and moved-from text is omitted. Revision history and formatting changes are not interpreted.",
                    "Compatibility content uses its fallback only; extension-only content is omitted. Hyperlink labels and stored field results are text only; links are not followed and fields are not evaluated.",
                ]
            )
    elif kind == "xlsx":
        workbook = extract_workbook(data, MAX_TEXT)
        return {
            "format": kind,
            "content_hash": hashlib.sha256(data).hexdigest(),
            "parser": PARSER,
            **workbook,
        }
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
            "invalid_docx_structure",
            "invalid_workbook_structure",
            "invalid_workbook_reference",
            "unsupported_workbook_cell_type",
            "workbook_resource_limit",
        }
        reason = (
            "memory_limit"
            if isinstance(exc, MemoryError)
            else "dependency_unavailable"
            if isinstance(exc, ImportError)
            else str(exc)
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
