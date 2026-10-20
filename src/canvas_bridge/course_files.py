"""Authorized file discovery, versioned extraction and page-aware text windows."""

import asyncio
import hashlib
import re
from contextlib import nullcontext
from datetime import datetime, timedelta

from canvas_bridge.domain import DomainError, Result, Source, utcnow
from canvas_bridge.file_download import download_file, file_metadata, file_version
from canvas_bridge.normalize import plain_text
from canvas_bridge.parser_sandbox import extract_document
from canvas_bridge.parser_worker import PARSER
from canvas_bridge.storage import Course, Material, aware


def clear(row, stage="available", reason=None):
    row.text, row.locators, row.version_hash = "", [], ""
    row.file_state = {"stage": stage, "reason": reason} if reason else {"stage": stage}


def fresh_cache(row, metadata, settings):
    state = row.file_state
    return bool(
        state.get("stage") in {"parsed", "partially_parsed"}
        and row.version_hash
        and state.get("parser") == PARSER
        and file_version(metadata) is not None
        and state.get("version") == file_version(metadata)
        and state.get("expires_at")
        and datetime.fromisoformat(state["expires_at"]) > utcnow()
        and aware(row.retrieved_at) > utcnow() - timedelta(hours=settings.file_cache_hours)
    )


async def authorized(bridge, owner, ref, material_id):
    await bridge.list_courses(owner, ref)
    _, courses = bridge.selected(owner, ref)
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, ref)
        try:
            row = bridge.store.owned(session, Material, owner, ref, material_id)
        except DomainError as exc:
            raise DomainError(
                "permission_denied",
                "File reference unavailable. Use a file_id from list_course_files or a File item's material_ref from get_course_outline; a parent module ID cannot identify one document.",
            ) from exc
        course = next((c for c in courses if c.id == row.course_id), None)
        if not course or row.kind != "file":
            raise DomainError("permission_denied", "File is outside the selected course scope.")
        epoch = conn.epoch
    try:
        async with bridge.client(owner, ref) as client:
            metadata = await file_metadata(client, course.source_id, row.source_id)
    except DomainError:
        with bridge.store.transaction() as session:
            row = bridge.store.owned(session, Material, owner, ref, material_id)
            clear(row, "inaccessible")
        raise
    with bridge.store.transaction() as session:
        row = checked_row(bridge, session, owner, ref, material_id, epoch)
        if (
            row.file_state.get("stage") in {"parsed", "partially_parsed"}
            and not fresh_cache(row, metadata, bridge.settings)
        ) or (
            row.file_state.get("version") and row.file_state["version"] != file_version(metadata)
        ):
            clear(row)
        row.title = plain_text(str(metadata.get("display_name", "Untitled file")), 1000)
    return row, course, metadata, epoch


def checked_row(bridge, session, owner, ref, material_id, epoch):
    conn = bridge.store.connection(session, owner, ref, lock=True)
    row = bridge.store.owned(session, Material, owner, ref, material_id)
    course = bridge.store.owned(session, Course, owner, ref, row.course_id)
    if conn.epoch != epoch or not course.selected or not course.accessible:
        raise DomainError("permission_denied", "File scope changed during this request.")
    return row


def source(row, locator=None):
    return Source(id=row.id, title=row.title, url=row.url, retrieved_at=utcnow(), locator=locator)


def page_label(row, number):
    return (
        f"PDF page {number}"
        if row.file_state.get("format") == "pdf"
        else "Text page 1 (artificial)"
    )


async def list_files(bridge, owner, ref, course_id, module_id=None):
    from canvas_bridge.retrieval import outline

    result = await outline(bridge, owner, ref, course_id, module_id)
    modules = result.data["modules"]
    if module_id is not None and not any(m["id"] == module_id for m in modules):
        raise DomainError(
            "needs_input",
            "Module is not in the currently accessible outline. Refresh the outline first.",
        )
    associations = {}
    for module in modules:
        for item in module["items"]:
            if item.get("type") == "File" and item.get("material_ref"):
                associations.setdefault(item["material_ref"], []).append(
                    {"id": module["id"], "title": module["title"]}
                )
    files = []
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref, lock=True)
        course = bridge.store.owned(session, Course, owner, ref, course_id)
        if not course.selected or not course.accessible:
            raise DomainError("permission_denied", "Course is no longer selected.")
        for item in result.data["materials"]:
            if item["kind"] != "file":
                continue
            related = associations.get(item["id"], [])
            if module_id and not any(m["id"] == module_id for m in related):
                continue
            row = bridge.store.owned(session, Material, owner, ref, item["id"])
            files.append(
                {
                    "file_id": row.id,
                    "canvas_file_id": row.source_id,
                    "course_id": course_id,
                    "title": row.title,
                    "filename": item.get("filename"),
                    "type": item.get("content_type"),
                    "size": item.get("size"),
                    "modules": related,
                    "url": row.url,
                    "extraction_state": row.file_state.get("stage", "available"),
                    "indexed": row.file_state.get("stage") in {"parsed", "partially_parsed"},
                }
            )
    return Result(
        status=result.status,
        summary="Accessible course files. Use the returned file_id to read a document; listings do not prove its contents were read.",
        data={
            "files": files,
            "modules": [{"id": m["id"], "title": m["title"]} for m in modules],
            "coverage": result.data["inventory_coverage"],
            "inventory_failures": result.data["inventory_failures"],
            "document_content_included": False,
        },
        sources=result.sources,
        meta=result.meta,
    )


async def status(bridge, owner, ref, file_id):
    try:
        row, _, metadata, _ = await authorized(bridge, owner, ref, file_id)
    except DomainError as exc:
        if exc.status == "permission_denied":
            return Result(
                status="permission_denied",
                summary="This file is inaccessible in the current selected scope.",
                data={"file_id": file_id, "state": "inaccessible", "indexed": False},
            )
        raise
    state = row.file_state.get("stage", "available")
    return Result(
        summary="Current file access and extraction status; no document was downloaded by this check.",
        data={
            "file_id": row.id,
            "state": state,
            "indexed": fresh_cache(row, metadata, bridge.settings),
            "content_hash": row.version_hash or None,
            "page_count": row.file_state.get("page_count"),
            "limitations": row.limitations,
            "reason": row.file_state.get("reason"),
            "extraction_enabled": bridge.settings.file_reading_enabled,
        },
        sources=[source(row)],
        meta=bridge.meta(),
    )


async def read_file(
    bridge,
    owner,
    ref,
    file_id,
    offset=0,
    length=8000,
    expected_hash=None,
    page_start=None,
    page_end=None,
    *,
    index_only=False,
):
    if offset < 0 or offset > 250_000 or not 1 <= length <= 16_000:
        raise DomainError("needs_input", "Invalid document text window.")
    if (page_start is not None and not 1 <= page_start <= 200) or (
        page_end is not None and (page_start is None or not page_start <= page_end <= 200)
    ):
        raise DomainError("needs_input", "Use an ordered PDF page range starting at page 1.")
    async with bridge.lock("file:" + ref + ":" + file_id):
        row, course, metadata, epoch = await authorized(bridge, owner, ref, file_id)
        if not fresh_cache(row, metadata, bridge.settings):
            if index_only:
                return None
            if not bridge.settings.file_reading_enabled:
                return Result(
                    status="unsupported_feature",
                    summary="Isolated file extraction is not enabled on this server.",
                    data={
                        "id": row.id,
                        "file_id": row.id,
                        "kind": "file",
                        "coverage": "unsupported",
                        "text": "",
                    },
                    sources=[source(row)],
                    meta=bridge.meta(),
                )
            try:
                async with bridge.client(owner, ref) as client:
                    async with (
                        bridge.synthetic.client() if bridge.synthetic else nullcontext(None) as http
                    ):
                        download = await download_file(
                            client, course.source_id, row.source_id, http=http
                        )
                with bridge.store.transaction() as session:
                    current = checked_row(bridge, session, owner, ref, file_id, epoch)
                    clear(current, "downloaded")
                extracted = await extract_document(download.data, download.kind, bridge.settings)
                async with bridge.client(owner, ref) as client:
                    after = await file_metadata(client, course.source_id, row.source_id)
                if download.revision is not None and file_version(after) != download.revision:
                    raise DomainError(
                        "source_changed", "The file changed during extraction. Read it again."
                    )
                with bridge.store.transaction() as session:
                    current = checked_row(bridge, session, owner, ref, file_id, epoch)
                    current.text = "\n\n".join(p["text"] for p in extracted["pages"])
                    current.locators = extracted["pages"]
                    current.version_hash = extracted["content_hash"]
                    current.limitations = extracted["warnings"]
                    current.retrieved_at = utcnow()
                    current.file_state = {
                        "stage": "parsed"
                        if extracted["coverage"] == "text_only"
                        else "partially_parsed",
                        "coverage": extracted["coverage"],
                        "version": download.revision,
                        "parser": extracted["parser"],
                        "metadata": extracted["metadata"],
                        "page_count": extracted["page_count"],
                        "format": extracted["format"],
                        "expires_at": (
                            utcnow() + timedelta(hours=bridge.settings.file_cache_hours)
                        ).isoformat(),
                    }
                    row = current
            except DomainError as exc:
                with bridge.store.transaction() as session:
                    current = checked_row(bridge, session, owner, ref, file_id, epoch)
                    clear(
                        current,
                        "inaccessible"
                        if exc.status == "permission_denied"
                        else "unsupported"
                        if exc.status == "unsupported_feature"
                        else "failed",
                        exc.message,
                    )
                    current.file_state = {**current.file_state, "version": file_version(metadata)}
                    current.limitations = [exc.message]
                raise
            except asyncio.CancelledError:
                with bridge.store.transaction() as session:
                    current = checked_row(bridge, session, owner, ref, file_id, epoch)
                    clear(current, "failed", "The extraction request was cancelled.")
                raise
        if (offset or expected_hash) and expected_hash != row.version_hash:
            raise DomainError(
                "source_changed",
                "Continuation requires the current content_hash; the file may have changed.",
            )
        with bridge.store.transaction() as session:
            row = checked_row(bridge, session, owner, ref, file_id, epoch)
            return chunk_result(bridge, row, offset, length, page_start, page_end)


def chunk_result(bridge, row, offset, length, page_start, page_end):
    first, last = (
        page_start or 1,
        page_end or (page_start if page_start else row.file_state["page_count"]),
    )
    if first > row.file_state["page_count"]:
        raise DomainError("needs_input", "Requested page exceeds this document's page count.")
    pages = [p for p in row.locators if first <= p["page"] <= last]
    text = "\n\n".join(p["text"] for p in pages)
    passages, cursor = [], 0
    for page in pages:
        start, end = max(offset, cursor), min(offset + length, cursor + len(page["text"]))
        if start < end:
            passages.append(
                {
                    "page": page["page"],
                    "page_offset": start - cursor,
                    "offset": start,
                    "text": page["text"][start - cursor : end - cursor],
                }
            )
        cursor += len(page["text"]) + 2
    next_offset = offset + length if offset + length < len(text) else None
    chunk_id = hashlib.sha256(
        f"{row.id}:{row.version_hash}:{first}:{last}:{offset}:{length}".encode()
    ).hexdigest()
    return Result(
        status="ok" if row.file_state["coverage"] == "text_only" else "partial_data",
        summary="Extracted document text with page references. Visual content has not been interpreted.",
        data={
            "id": row.id,
            "file_id": row.id,
            "title": row.title,
            "metadata": row.file_state["metadata"],
            "text": text[offset : offset + length],
            "passages": passages,
            "chunk_id": chunk_id,
            "content_hash": row.version_hash,
            "offset": offset,
            "next_offset": next_offset,
            "page_start": first,
            "page_end": last,
            "page_count": row.file_state["page_count"],
            "total_extracted_characters": len(text),
            "coverage": row.file_state["coverage"],
            "parser": row.file_state["parser"],
            "format": row.file_state["format"],
            "limitations": row.limitations,
            "content_boundary": "untrusted_source_data",
            "continuation": {
                "file_id": row.id,
                "offset": next_offset,
                "expected_hash": row.version_hash,
                "page_start": first,
                "page_end": last,
            }
            if next_offset is not None
            else None,
        },
        sources=[
            source(
                row,
                f"{page_label(row, p['page'])}, characters {p['page_offset']}–{p['page_offset'] + len(p['text'])}",
            )
            for p in passages
        ]
        or [source(row)],
        meta=bridge.meta(),
    )


async def search_files(bridge, owner, ref, course_id, query, limit=10):
    if not 1 <= len(query.strip()) <= 200 or not 1 <= limit <= 20:
        raise DomainError("needs_input", "Use a short search query and limit from 1 to 20.")
    inventory = await list_files(bridge, owner, ref, course_id)
    results, sources, indexed, unindexed = [], [], 0, []
    started = asyncio.get_running_loop().time()
    unavailable, budget_exhausted = 0, False
    # The inventory is bounded. Only previously extracted files are searched;
    # each candidate gets a fresh course-file permission/version check first.
    for file in inventory.data["files"]:
        remaining = bridge.settings.refresh_budget_seconds - (
            asyncio.get_running_loop().time() - started
        )
        if remaining <= 0:
            budget_exhausted = True
            break
        if not file["indexed"]:
            unindexed.append({"file_id": file["file_id"], "title": file["title"]})
            continue
        try:
            async with asyncio.timeout(remaining):
                fresh = await read_file(bridge, owner, ref, file["file_id"], index_only=True)
            if fresh is None:
                unindexed.append({"file_id": file["file_id"], "title": file["title"]})
                continue
            with bridge.store.transaction() as session:
                bridge.store.connection(session, owner, ref, lock=True)
                course = bridge.store.owned(session, Course, owner, ref, course_id)
                if not course.selected or not course.accessible:
                    raise DomainError("permission_denied", "Course selection changed.")
                row = bridge.store.owned(session, Material, owner, ref, file["file_id"])
                for page in row.locators:
                    match = re.search(re.escape(query.strip()), page["text"], re.IGNORECASE)
                    if match is None or len(results) >= limit:
                        continue
                    at = match.start()
                    start = max(0, at - 160)
                    results.append(
                        {
                            "file_id": row.id,
                            "title": row.title,
                            "page": page["page"],
                            "page_offset": start,
                            "passage": page["text"][start : start + 600],
                            "content_hash": row.version_hash,
                            "url": row.url,
                        }
                    )
                    sources.append(source(row, page_label(row, page["page"])))
            indexed += 1
        except DomainError:
            unavailable += 1
            continue
        except TimeoutError:
            budget_exhausted = True
            break
    return Result(
        status="partial_data"
        if unindexed
        or unavailable
        or budget_exhausted
        or len(results) == limit
        or inventory.status != "ok"
        else "ok",
        summary=f"{len(results)} matching passages in {indexed} freshly authorized indexed documents.",
        data={
            "results": results,
            "indexed_documents": indexed,
            "unindexed_documents": unindexed,
            "search_scope": "previously_extracted_selected_course_files",
            "limit": limit,
            "limit_reached": len(results) == limit,
            "unavailable_documents": unavailable,
            "request_budget_exhausted": budget_exhausted,
            "inventory_coverage": inventory.data["coverage"],
            "inventory_failures": inventory.data["inventory_failures"],
            "unread_documents_searched": False,
            "next_step": "Read likely unindexed files with read_course_file, then search again. No match is not evidence that unread documents lack the topic.",
        },
        sources=sources,
        meta=bridge.meta(
            warnings=[
                "Unindexed documents were not searched; read them first. Figures are not searched."
            ]
        ),
    )
