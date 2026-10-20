"""Bounded source extraction and authorized Canvas page retrieval.

Binary parsing is a local synthetic-development capability only until a
network-isolated parser container has been deployed and verified.
"""

import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Literal

from defusedxml import ElementTree
from pypdf import PdfReader
from sqlalchemy import select

from canvas_bridge.domain import DomainError, Model, Result, Source, utcnow
from canvas_bridge.normalize import canonical_id, plain_text
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.storage import Material

MAX_BYTES = 10_000_000
MAX_EXPANDED = 20_000_000
MAX_TEXT = 250_000


class Extraction(Model):
    format: str
    content_hash: str
    parser: str
    text: str
    locators: list[dict]
    coverage: Literal["text_only", "partial", "unsupported"]
    warnings: list[str]


def extract_synthetic(
    data: bytes, kind: Literal["txt", "html", "pdf", "docx", "pptx"]
) -> Extraction:
    """No URLs, subprocesses, credentials, macros or embedded-file execution."""
    if len(data) > MAX_BYTES:
        raise ValueError("Document size limit exceeded.")
    parts, warnings = (
        [],
        ["Text extraction does not establish figure, equation or table interpretation."],
    )
    coverage = "text_only"
    if kind in {"txt", "html"}:
        raw = data.decode("utf-8")
        text = plain_text(raw, MAX_TEXT) if kind == "html" else raw[:MAX_TEXT]
        parts.append({"locator": "document text", "text": text})
        if len(raw) > MAX_TEXT:
            coverage = "partial"
            warnings.append("Text exceeded extraction limit.")
    elif kind == "pdf":
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("Encrypted or oversized PDF is unsupported.")
        if "/JavaScript" in reader.trailer.get("/Root", {}) or b"/JavaScript" in data:
            raise ValueError("Active PDF content is unsupported.")
        total = 0
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                coverage = "partial"
                warnings.append(
                    f"Page {index}: no text extracted; image-only content may be present."
                )
            if total + len(text) > MAX_TEXT:
                coverage = "partial"
                warnings.append("Text limit reached; remaining pages were not extracted.")
                break
            total += len(text)
            parts.append({"locator": f"page {index}", "text": text})
        warnings.append("PDF reading order and multi-column layout are not independently verified.")
    elif kind in {"docx", "pptx"}:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 500 or sum(x.file_size for x in members) > MAX_EXPANDED:
                raise ValueError("Expanded archive exceeds limits.")
            for member in members:
                path = PurePosixPath(member.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.filename
                    or ":" in member.filename
                    or member.file_size > MAX_BYTES
                    or member.file_size / max(member.compress_size, 1) > 100
                    or any(
                        x in member.filename.lower()
                        for x in ("vbaproject", "embeddings/", "activex/")
                    )
                ):
                    raise ValueError("Unsafe office archive member.")
            names = (
                ["word/document.xml"]
                if kind == "docx"
                else sorted(
                    [
                        x.filename
                        for x in members
                        if re.fullmatch(r"ppt/slides/slide[0-9]+\.xml", x.filename)
                    ],
                    key=lambda name: int(re.search(r"slide([0-9]+)", name)[1]),
                )
            )
            if len(names) > 200:
                raise ValueError("Slide limit exceeded.")
            for number, name in enumerate(names, 1):
                tree = ElementTree.fromstring(archive.read(name))
                texts = [n.text for n in tree.iter() if n.tag.endswith("}t") and n.text]
                text = "\n".join(texts)
                if sum(len(x["text"]) for x in parts) + len(text) > MAX_TEXT:
                    coverage = "partial"
                    warnings.append("Text limit reached.")
                    break
                parts.append(
                    {
                        "locator": f"slide {number}"
                        if kind == "pptx"
                        else "document body (pagination unavailable)",
                        "text": text,
                    }
                )
            warnings.append(
                "Speaker notes, headers, footnotes, embedded objects and visual layout are not extracted."
            )
    else:
        raise ValueError("Unsupported document format.")
    text = "\n\n".join(p["text"] for p in parts)
    return Extraction(
        format=kind,
        content_hash=hashlib.sha256(data).hexdigest(),
        parser="canvas-bridge-text-v1",
        text=text,
        locators=parts,
        coverage=coverage,
        warnings=warnings,
    )


async def outline(bridge, owner: str, ref: str, course_ref: str) -> Result:
    await bridge.list_courses(owner, ref)
    _, courses = bridge.selected(owner, ref, [course_ref])
    course = courses[0]
    modules, resources, warnings = [], [], []
    async with bridge.client(owner, ref) as client:
        collection = await client.collection(Endpoint.MODULES, course=course.source_id)
        for module in collection.items[:30]:
            module_id = source_id(module["id"])
            items = await client.collection(
                Endpoint.MODULE_ITEMS,
                course=course.source_id,
                module=module_id,
            )
            modules.append(
                {
                    "id": canonical_id(owner, ref, "module", f"{course.source_id}:{module_id}"),
                    "title": plain_text(str(module.get("name", "")), 1000),
                    "position": module.get("position"),
                    "state": module.get("state", "unknown"),
                    "items": [
                        {
                            k: item[k]
                            for k in ("title", "type", "position", "completion_requirement")
                            if k in item
                        }
                        for item in items.items[:100]
                    ],
                    "items_complete": items.complete and len(items.items) <= 100,
                }
            )
        pages = await client.collection(Endpoint.PAGES, course=course.source_id)
        with bridge.store.transaction() as session:
            bridge.store.connection(session, owner, ref, lock=True)
            selected = bridge.store.owned(session, type(course), owner, ref, course_ref)
            if not selected.selected or not selected.accessible:
                raise DomainError("permission_denied", "Course is no longer selected.")
            for page in pages.items[:100]:
                if page.get("published") is False or page.get("locked_for_user") is True:
                    continue
                upstream = source_id(page["page_id"])
                material_id = canonical_id(owner, ref, "page", f"{course.source_id}:{upstream}")
                title = plain_text(str(page.get("title", "Untitled page")), 1000)
                url = f"{client.institution.origin}/courses/{course.source_id}/pages/page_id:{upstream}"
                material = session.get(Material, material_id)
                if material is None:
                    session.add(
                        Material(
                            id=material_id,
                            owner=owner,
                            connection_id=ref,
                            course_id=course_ref,
                            source_id=upstream,
                            title=title,
                            url=url,
                            version_hash="",
                            text="",
                            locators=[],
                            limitations=["Not fetched."],
                        )
                    )
                resources.append({"id": material_id, "title": title, "url": url, "kind": "page"})
        source = Source(
            id=course.id,
            title=f"{course.name}: modules",
            url=f"{client.institution.origin}/courses/{course.source_id}/modules",
            retrieved_at=utcnow(),
        )
    complete = (
        collection.complete
        and pages.complete
        and len(collection.items) <= 30
        and len(pages.items) <= 100
        and all(m["items_complete"] for m in modules)
    )
    if not complete:
        warnings.append(
            "Outline exceeds the current request budget or some collections are unavailable."
        )
    return Result(
        status="ok" if complete else "partial_data",
        summary="Authorized course outline and available page references.",
        data={
            "modules": modules,
            "materials": resources,
            "limitations": ["Binary files and external/LTI readings are not fetched by this tool."],
        },
        sources=[source],
        meta=bridge.meta(warnings=warnings),
    )


async def fetch_material(
    bridge,
    owner: str,
    ref: str,
    material_ref: str,
    offset: int = 0,
    length: int = 8000,
    expected_hash: str | None = None,
) -> Result:
    if offset < 0 or not 1 <= length <= 16_000 or offset > MAX_TEXT:
        raise DomainError("needs_input", "Invalid text window.")
    await bridge.list_courses(owner, ref)
    _, courses = bridge.selected(owner, ref)
    with bridge.store.transaction() as session:
        material = bridge.store.owned(session, Material, owner, ref, material_ref)
        course = next((c for c in courses if c.id == material.course_id), None)
        if not course:
            raise DomainError("permission_denied", "Material unavailable.")
    async with bridge.client(owner, ref) as client:
        try:
            page = await client.one(Endpoint.PAGE, course=course.source_id, page=material.source_id)
        except DomainError:
            with bridge.store.transaction() as session:
                row = bridge.store.owned(session, Material, owner, ref, material_ref)
                row.text, row.locators, row.version_hash = "", [], ""
            raise
    if page.get("published") is False or page.get("locked_for_user") is True:
        raise DomainError("permission_denied", "Material is currently restricted.")
    raw = str(page.get("body") or "")
    parsed = extract_synthetic(raw.encode(), "html")
    if offset and (not expected_hash or expected_hash != parsed.content_hash):
        raise DomainError(
            "source_changed", "Material version changed or continuation has no version binding."
        )
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref, lock=True)
        selected = bridge.store.owned(session, type(course), owner, ref, course.id)
        if not selected.selected or not selected.accessible:
            raise DomainError("permission_denied", "Material is no longer in selected scope.")
        row = bridge.store.owned(session, Material, owner, ref, material_ref)
        row.text, row.locators, row.version_hash = parsed.text, parsed.locators, parsed.content_hash
        row.retrieved_at, row.limitations = utcnow(), parsed.warnings
    return Result(
        summary="Source text only; figures and layout have not been interpreted.",
        data={
            "id": material_ref,
            "text": parsed.text[offset : offset + length],
            "content_hash": parsed.content_hash,
            "offset": offset,
            "next_offset": offset + length if offset + length < len(parsed.text) else None,
            "total_extracted_characters": len(parsed.text),
            "coverage": parsed.coverage,
            "limitations": parsed.warnings,
            "content_boundary": "untrusted_source_data",
        },
        sources=[
            Source(
                id=material_ref,
                title=material.title,
                url=material.url,
                retrieved_at=utcnow(),
                locator=f"extracted characters {offset}–{min(offset + length, len(parsed.text))}",
            )
        ],
        meta=bridge.meta(),
    )


async def search_materials(bridge, owner: str, ref: str, query: str, limit: int = 10) -> Result:
    if not 1 <= len(query.strip()) <= 200 or not 1 <= limit <= 20:
        raise DomainError("needs_input", "Search requires a short query and a limit from 1 to 20.")
    await bridge.list_courses(owner, ref)
    _, courses = bridge.selected(owner, ref)
    with bridge.store.transaction() as session:
        # ACLs precede matching, counts, snippets and ranking.
        rows = session.scalars(
            select(Material)
            .where(
                Material.owner == owner,
                Material.connection_id == ref,
                Material.course_id.in_([c.id for c in courses]),
                (
                    Material.text.icontains(query, autoescape=True)
                    | Material.title.icontains(query, autoescape=True)
                ),
            )
            .limit(limit + 1)
        ).all()
    results, sources = [], []
    for row in rows[:limit]:
        try:
            fresh = await fetch_material(bridge, owner, ref, row.id, length=16_000)
        except DomainError:
            continue
        # A prior index hit is never proof the current document still contains the phrase.
        with bridge.store.transaction() as session:
            current = bridge.store.owned(session, Material, owner, ref, row.id)
            position = current.text.casefold().find(query.casefold())
            if position < 0 and query.casefold() not in current.title.casefold():
                continue
            start = max(0, position - 120)
            results.append(
                {
                    "id": row.id,
                    "title": current.title,
                    "url": current.url,
                    "snippet": current.text[start : start + 400],
                    "locator": f"extracted characters {start}–{start + 400}",
                    "content_hash": current.version_hash,
                }
            )
            sources.extend(fresh.sources)
    return Result(
        status="partial_data",
        summary=f"{len(results)} authorized matches in previously fetched pages. Unfetched readings are not searched.",
        data={
            "results": results,
            "search_scope": "previously_fetched_pages",
            "truncated": len(rows) > limit,
        },
        sources=sources,
        meta=bridge.meta(warnings=["This is not a complete course reading search."]),
    )
