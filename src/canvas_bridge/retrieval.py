"""Bounded source extraction and authorized Canvas page retrieval.

The in-process extraction helpers below remain synthetic-development primitives.
Live PDF/text reads delegate to the isolated worker through course_files.
"""

import asyncio
import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Literal

from defusedxml import ElementTree
from pypdf import PdfReader
from sqlalchemy import select

from canvas_bridge.canvas import Collection
from canvas_bridge.domain import DomainError, Model, Result, Source, utcnow
from canvas_bridge.file_download import file_metadata, file_version, file_visible
from canvas_bridge.normalize import canonical_id, plain_text
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.storage import Material, aware

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


async def outline(
    bridge, owner: str, ref: str, course_ref: str, module_filter: str | None = None
) -> Result:
    await bridge.refresh_course_access(owner, ref)
    _, courses = bridge.selected(owner, ref, [course_ref])
    course = courses[0]
    modules, resources, warnings = [], [], []
    collection, pages, files = (Collection(failure="request_budget") for _ in range(3))
    raw_modules = []
    async with bridge.client(owner, ref) as client:
        # One budget covers the entire outline, not a fresh budget per module.
        try:
            async with asyncio.timeout(bridge.settings.refresh_budget_seconds):
                pages = await client.collection(Endpoint.PAGES, course=course.source_id)
                files = (
                    Collection(failure="module_filtered_inventory")
                    if module_filter
                    else await client.collection(Endpoint.FILES, course=course.source_id)
                )
                collection = await client.collection(Endpoint.MODULES, course=course.source_id)
                for module in collection.items[:30]:
                    if module.get("published") is False or module.get("state") == "locked":
                        continue
                    module_id = source_id(module["id"])
                    if (
                        module_filter
                        and canonical_id(owner, ref, "module", f"{course.source_id}:{module_id}")
                        != module_filter
                    ):
                        continue
                    items = await client.collection(
                        Endpoint.MODULE_ITEMS, course=course.source_id, module=module_id
                    )
                    raw_modules.append((module_id, module, items))
                # Some courses disable the Files tab/list endpoint while granting
                # access to files through modules. Resolve those IDs with the
                # course-qualified metadata endpoint; never trust a bare global ID.
                known = {str(file.get("id")) for file in files.items[:100]}
                for _, _, items in raw_modules:
                    for item in items.items[:100]:
                        if (
                            item.get("type") != "File"
                            or item.get("published") is False
                            or item.get("locked_for_user") is True
                            or len(known) >= 100
                        ):
                            continue
                        file_id = source_id(item.get("content_id", ""))
                        if file_id in known:
                            continue
                        try:
                            metadata = await file_metadata(client, course.source_id, file_id)
                        except DomainError as exc:
                            if exc.status == "reconnect_required":
                                raise
                            continue
                        files.items.insert(0, metadata)
                        known.add(file_id)
        except TimeoutError:
            warnings.append("The course outline reached its overall request time limit.")

        references = {}
        with bridge.store.transaction() as session:
            bridge.store.connection(session, owner, ref, lock=True)
            selected = bridge.store.owned(session, type(course), owner, ref, course_ref)
            if not selected.selected or not selected.accessible:
                raise DomainError("permission_denied", "Course is no longer selected.")
            for kind, entries in (("page", pages.items), ("file", files.items)):
                for entry in entries[:100]:
                    if kind == "file":
                        if not file_visible(entry):
                            continue
                        upstream = source_id(entry["id"])
                        title = plain_text(str(entry.get("display_name", "Untitled file")), 1000)
                        path = f"files/{upstream}"
                        lookup = ("File", upstream)
                    else:
                        if entry.get("published") is False or entry.get("locked_for_user") is True:
                            continue
                        upstream = source_id(entry["page_id"])
                        title = plain_text(str(entry.get("title", "Untitled page")), 1000)
                        path = f"pages/page_id:{upstream}"
                        lookup = ("Page", str(entry.get("url", "")))
                    material_id = canonical_id(owner, ref, kind, f"{course.source_id}:{upstream}")
                    if material_id in {r["id"] for r in resources}:
                        continue
                    url = f"{client.institution.origin}/courses/{course.source_id}/{path}"
                    material = session.get(Material, material_id)
                    if material is None:
                        session.add(
                            Material(
                                id=material_id,
                                owner=owner,
                                connection_id=ref,
                                course_id=course_ref,
                                source_id=upstream,
                                kind=kind,
                                title=title,
                                url=url,
                                version_hash="",
                                text="",
                                locators=[],
                                limitations=["Not fetched."],
                            )
                        )
                    else:
                        material.title, material.url = title, url
                        if kind == "file" and (
                            material.file_state.get("version") != file_version(entry)
                            or (utcnow() - aware(material.retrieved_at)).total_seconds()
                            > bridge.settings.file_cache_hours * 3600
                        ):
                            from canvas_bridge.course_files import clear

                            clear(material)
                    references[lookup] = material_id
                    resources.append(
                        {
                            "id": material_id,
                            "title": title,
                            "url": url,
                            "kind": kind,
                            "reading_status": "not_established",
                            **(
                                {
                                    "filename": plain_text(str(entry.get("filename", "")), 1000),
                                    "content_type": str(entry.get("content-type", ""))[:200],
                                    "size": entry.get("size"),
                                    "source_version": file_version(entry),
                                }
                                if kind == "file"
                                else {}
                            ),
                        }
                    )
        for module_id, module, items in raw_modules:
            visible_items = []
            for item in items.items[:100]:
                if item.get("published") is False or item.get("locked_for_user") is True:
                    continue
                visible = {
                    k: item[k] for k in ("type", "position", "completion_requirement") if k in item
                }
                visible["title"] = plain_text(str(item.get("title", "")), 1000)
                lookup = (item.get("type"), str(item.get("content_id") or item.get("page_url", "")))
                if material_ref := references.get(lookup):
                    visible["material_ref"] = material_ref
                elif item.get("type") in {"File", "Page"}:
                    visible["material_availability"] = "not_in_accessible_inventory"
                visible_items.append(visible)
            modules.append(
                {
                    "id": canonical_id(owner, ref, "module", f"{course.source_id}:{module_id}"),
                    "title": plain_text(str(module.get("name", "")), 1000),
                    "position": module.get("position"),
                    "state": module.get("state", "unknown"),
                    "items": visible_items,
                    "items_complete": items.complete and len(items.items) <= 100,
                }
            )
        source = Source(
            id=course.id,
            title=f"{course.name}: modules",
            url=f"{client.institution.origin}/courses/{course.source_id}/modules",
            retrieved_at=utcnow(),
        )
    complete = (
        collection.complete
        and pages.complete
        and files.complete
        and len(collection.items) <= 30
        and len(pages.items) <= 100
        and len(files.items) <= 100
        and all(m["items_complete"] for m in modules)
        and not warnings
    )
    if not complete:
        warnings.append(
            "Outline exceeds the current request budget or some collections are unavailable."
        )
    return Result(
        status="ok" if complete else "partial_data",
        summary="Authorized course outline with page and file references; listing is not evidence of reading.",
        data={
            "modules": modules,
            "materials": resources,
            "document_content_included": False,
            "file_reading": {
                "enabled": bridge.settings.file_reading_enabled,
                "read_tool": "read_course_file",
                "search_tool": "search_course_files",
                "reference": "Use the File item's material_ref as file_id, never the parent module ID.",
                "formats": ["pdf", "docx", "pptx", "txt", "md"],
            },
            "inventory_coverage": {
                name: "complete" if c.complete and len(c.items) <= limit else "partial"
                for name, c, limit in (
                    ("pages", pages, 100),
                    ("files", files, 100),
                    ("modules", collection, 30),
                )
            },
            "inventory_failures": {
                name: c.failure
                for name, c in (("pages", pages), ("files", files), ("modules", collection))
                if c.failure
            },
            "inventory_reason_codes": {
                name: {"reason_code": c.reason_code, "upstream_http_status": c.upstream_http_status}
                for name, c in (("pages", pages), ("files", files), ("modules", collection))
                if c.reason_code
            },
            "limitations": [
                "Use read_course_file or fetch_course_material to read file text when isolated extraction is enabled.",
                "External/LTI readings are not fetched. Module inclusion alone does not establish assigned versus optional status.",
            ],
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
    with bridge.store.transaction() as session:
        try:
            entry = bridge.store.owned(session, Material, owner, ref, material_ref)
        except DomainError as exc:
            raise DomainError(
                "permission_denied",
                "Material reference unavailable. Resolve a File or Page item's material_ref with get_course_outline; parent module IDs are not document IDs.",
            ) from exc
        is_file = entry.kind == "file"
    if is_file:
        from canvas_bridge.course_files import read_file

        return await read_file(bridge, owner, ref, material_ref, offset, length, expected_hash)
    await bridge.refresh_course_access(owner, ref)
    _, courses = bridge.selected(owner, ref, resource_type="pages", operation=Endpoint.PAGE)
    with bridge.store.transaction() as session:
        material = bridge.store.owned(session, Material, owner, ref, material_ref)
        course = next((c for c in courses if c.id == material.course_id), None)
        if not course:
            raise DomainError("permission_denied", "Material unavailable.")
    async with bridge.client(owner, ref) as client:
        try:
            if material.kind != "page":
                raise DomainError("unsupported_feature", "Unknown material format.")
            page = await client.one(Endpoint.PAGE, course=course.source_id, page=material.source_id)
            if page.get("published") is False or page.get("locked_for_user") is True:
                raise DomainError("permission_denied", "Material is currently restricted.")
        except DomainError:
            with bridge.store.transaction() as session:
                row = bridge.store.owned(session, Material, owner, ref, material_ref)
                row.text, row.locators, row.version_hash = "", [], ""
            raise
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
    await bridge.refresh_course_access(owner, ref)
    _, courses = bridge.selected(owner, ref, resource_type="pages", operation=Endpoint.PAGE)
    with bridge.store.transaction() as session:
        # ACLs precede matching, counts, snippets and ranking.
        rows = session.scalars(
            select(Material)
            .where(
                Material.owner == owner,
                Material.connection_id == ref,
                Material.kind == "page",
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
            "file_text_searched": False,
            "unfetched_content_searched": False,
            "next_step": "Use list_course_files to discover PDFs, read_course_file to extract likely documents, then search_course_files for indexed file passages.",
            "truncated": len(rows) > limit,
        },
        sources=sources,
        meta=bridge.meta(warnings=["This is not a complete course reading search."]),
    )
