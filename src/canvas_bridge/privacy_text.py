"""Bounded, local privacy inspection shared with isolated document workers.

This detector is deliberately not a claim of anonymity. Review of unstructured
content and opaque pixels remains a separate release requirement.
"""

import html
import re
from urllib.parse import unquote

VERSION = "third-party-privacy-1"
WITHHELD = "[CONTENT_WITHHELD_PRIVACY_UNCERTAINTY]"
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)")
IDENTIFIER = re.compile(
    r"(?i)\b(?:student\s*(?:id|number)|sis[_ -]?(?:user[_ -]?)?id|login[_ -]?id|"
    r"netid|ssn)\s*[:=#]\s*[\w@.+-]+"
)
PERSONAL_URL = re.compile(r"(?i)https?://[^\s<>\"]+/(?:users|people|profiles)/[^\s<>\"]+")
# Context, not title case: scientific names, gene symbols and citations survive.
PERSONAL_CONTEXT = re.compile(
    r"\b(?i:student|classmate|roommate|patient|participant|professor|instructor|"
    r"teaching assistant)\s+(?:(?i:name)\s*[:=]\s*)?[A-Z][a-z]+\s+[A-Z][a-z]+\b|"
    r"(?i:\b(?:my|her|his|their)\s+(?:diagnosis|disability|accommodation|home address)\b|"
    r"\b(?:group|team)\s+(?:members|roster)\s*[:=])"
)
SECRET = re.compile(
    r"(?i)\b(?:bearer\s+\S+|(?:access_token|refresh_token|client_secret|password)\s*[:=]\s*\S+)"
)


def inspect_text(value: str, aliases=()) -> tuple[str, bool]:
    if len(value) > 250_000:
        return WITHHELD, True
    decoded = value
    for _ in range(4):
        decoded = html.unescape(unquote(decoded)).replace("\\/", "/")
    if PERSONAL_CONTEXT.search(decoded) or SECRET.search(decoded):
        return WITHHELD, True
    cleaned = decoded
    for alias in sorted(aliases, key=lambda item: (-len(item), item)):
        if isinstance(alias, str) and 3 <= len(alias) <= 200:
            cleaned = re.sub(
                r"(?<!\w)" + re.escape(alias) + r"(?!\w)", "[private person]", cleaned, flags=re.I
            )
    for pattern, replacement in (
        (EMAIL, "[redacted email]"),
        (PHONE, "[private phone]"),
        (IDENTIFIER, "[private identifier]"),
        (PERSONAL_URL, "[private profile]"),
    ):
        cleaned = pattern.sub(replacement, cleaned)
    changed = cleaned != decoded
    # Never accidentally return a partly decoded version of an encoded secret.
    return (cleaned if decoded == value else WITHHELD, True) if changed else (value, False)


def document_privacy(extraction: dict, aliases=()) -> dict:
    """Remove personal properties and sanitize every string before cache storage.

    Page character offsets are recomputed by the service after extraction. Any
    detailed worker locators in a modified page are removed, not misattributed.
    Neither this function nor successful extraction clears original bytes/pixels.
    """
    changed = bool(extraction.get("privacy", {}).get("filtered"))
    aliases = tuple(aliases) + tuple(
        v
        for k, v in extraction.get("metadata", {}).items()
        if k.lower() in {"author", "creator", "last_modified_by"}
        and isinstance(v, str)
        and 3 <= len(v) <= 200
    )
    aliases += tuple(extraction.get("metadata", {}).get("privacy_aliases", ()))

    def walk(value, depth=0):
        nonlocal changed
        if depth > 32:
            changed = True
            return None
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key.lower() in {
                    "author",
                    "creator",
                    "lastmodifiedby",
                    "last_modified_by",
                    "comments",
                    "revision_author",
                }:
                    changed = True
                    continue
                out[key] = walk(item, depth + 1)
            return out
        if isinstance(value, list):
            return [walk(item, depth + 1) for item in value]
        if isinstance(value, str):
            text, filtered = inspect_text(value, aliases[:256])
            changed |= filtered
            return text
        return value

    clean = walk(extraction)
    # Property titles/subjects may be arbitrary names. They have no academic role
    # in extraction, so avoid collecting them even if a detector found nothing.
    clean["metadata"] = {}
    page_content_filtered = bool(extraction.get("privacy", {}).get("page_content_filtered"))
    for page in clean.get("pages", []):
        original = next(
            (p for p in extraction.get("pages", []) if p.get("page") == page.get("page")), {}
        )
        if page != original:
            page_content_filtered = True
            for key in (
                "spans",
                "runs",
                "blocks",
                "tables",
                "cells",
                "text_spans",
                "cell_spans",
                "structure",
            ):
                page.pop(key, None)
    clean["privacy"] = {
        "policy_version": VERSION,
        "enabled": True,
        "filtered": changed or bool(extraction.get("metadata")),
        "page_content_filtered": page_content_filtered,
        "content_status": "content_withheld_privacy_uncertainty"
        if any(WITHHELD in p.get("text", "") for p in clean.get("pages", []))
        else "text_inspected_visuals_unreviewed",
        "original_bytes_sanitized": False,
        "auxiliary_content_status": extraction.get("privacy", {}).get(
            "auxiliary_content_status", "not_assessed"
        ),
    }
    return clean


def inspect_office_parts(data: bytes) -> tuple[str, tuple[str, ...]]:
    """Inspect bounded accessible XML, including properties, revisions, hidden
    worksheets/slides, notes, comments and relationships. Return no source text.
    Images/embedded objects remain unreviewed regardless of this result.
    """
    import io
    import zipfile

    from defusedxml import ElementTree

    filtered = False
    aliases = set()
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 5000:
            return "incomplete", tuple(aliases)
        for entry in archive.infolist():
            if not entry.filename.endswith((".xml", ".rels")):
                continue
            total += entry.file_size
            if entry.file_size > 4_000_000 or total > 20_000_000:
                return "incomplete", tuple(aliases)
            try:
                root = ElementTree.fromstring(archive.read(entry))
                for node in root.iter():
                    for key, value in ((node.tag, node.text), *node.attrib.items()):
                        if (
                            key.rsplit("}", 1)[-1].lower()
                            in {"author", "creator", "lastmodifiedby"}
                            and isinstance(value, str)
                            and 3 <= len(value) <= 200
                        ):
                            aliases.add(value)
                            filtered = True
                            if len(aliases) > 256:
                                return "incomplete", ()
                    for text in (node.text or "", *node.attrib.values()):
                        filtered |= inspect_text(text)[1]
            except Exception:
                return "incomplete", tuple(aliases)
    return ("identifiers_detected" if filtered else "bounded_xml_inspection_only"), tuple(aliases)
