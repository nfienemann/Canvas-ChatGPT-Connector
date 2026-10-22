"""Bounded authenticated search that can extract unread documents on demand."""

import asyncio
import re

from canvas_bridge.course_files import (
    cell_references,
    checked_row,
    failure_state,
    list_files,
    passage_label,
    read_file,
    source,
)
from canvas_bridge.domain import Coverage, DomainError, Result, utcnow
from canvas_bridge.evidence import attach, fingerprint
from canvas_bridge.parser_worker import PARSER

SEARCH_SECONDS = 45
CURSOR_SECONDS = 1800


def inventory_version(inventory):
    return fingerprint(
        {
            "files": [
                {
                    k: f.get(k)
                    for k in ("file_id", "source_version", "title", "filename", "type", "size")
                }
                for f in sorted(inventory.data["files"], key=lambda f: f["file_id"])
            ],
            "coverage": inventory.data["coverage"],
            "failures": inventory.data["inventory_failures"],
            "status": inventory.status,
        }
    )


def continuation(bridge, owner, ref, cursor, binding):
    initial = {
        "file": 0,
        "page": 0,
        "hash": None,
        "completed": 0,
        "failed": 0,
        "partial": 0,
        "unversioned": False,
        "expires": utcnow().timestamp() + CURSOR_SECONDS,
    }
    if not cursor:
        return initial
    try:
        if len(cursor) > 4096:
            raise ValueError
        value = bridge.vault.open(cursor, owner, ref + ":document-search")
        if value["binding"] != binding:
            raise DomainError(
                "source_changed",
                "Search scope, query or file inventory changed. Restart the search without a cursor.",
            )
        if value["expires"] < utcnow().timestamp():
            raise ValueError
        for field in ("file", "page", "completed", "failed", "partial"):
            if type(value[field]) is not int or value[field] < 0:
                raise ValueError
        return value
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "permission_denied", "This document search continuation is invalid or expired."
        ) from exc


async def search_documents(bridge, owner, ref, course_id, query, limit, cursor, max_documents):
    if type(max_documents) is not int or not 1 <= max_documents <= 3:
        raise DomainError("needs_input", "Search one to three documents per request.")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SEARCH_SECONDS
    try:
        async with asyncio.timeout(SEARCH_SECONDS):
            inventory = await list_files(bridge, owner, ref, course_id)
    except TimeoutError as exc:
        raise DomainError(
            "retry_later",
            "File discovery exceeded the search budget. No search result was produced.",
        ) from exc
    connection, _ = bridge.selected(owner, ref, [course_id])
    files = sorted(inventory.data["files"], key=lambda f: f["file_id"])
    version = inventory_version(inventory)
    binding = fingerprint([course_id, connection.epoch, query.strip(), limit, version, PARSER])
    state = continuation(bridge, owner, ref, cursor, binding)
    if state["file"] > len(files):
        raise DomainError("permission_denied", "Document continuation is outside this inventory.")
    results, sources, statuses = [], {}, []
    attempted, indexed, unread_searched, budget_exhausted = 0, 0, False, False
    matcher = re.compile(re.escape(query.strip()), re.IGNORECASE)
    while state["file"] < len(files) and attempted < max_documents and len(results) < limit:
        remaining = deadline - loop.time()
        if remaining <= 0:
            budget_exhausted = True
            break
        file = files[state["file"]]
        attempted += 1
        info = {
            "file_id": file["file_id"],
            "title": file["title"],
            "source_version": file["source_version"],
        }
        try:
            async with asyncio.timeout(remaining):
                fresh = await read_file(
                    bridge,
                    owner,
                    ref,
                    file["file_id"],
                    length=1,
                    expected_hash=state["hash"] if state["page"] else None,
                )
            if fresh.status == "unsupported_feature":
                raise DomainError(
                    "unsupported_feature", "Isolated document extraction is not enabled."
                )
            with bridge.store.transaction() as session:
                row = checked_row(bridge, session, owner, ref, file["file_id"], connection.epoch)
                if row.version_hash != fresh.data["content_hash"]:
                    raise DomainError(
                        "source_changed", "Document text changed during search. Restart the search."
                    )
                if row.file_state.get("version") != file["source_version"]:
                    raise DomainError(
                        "source_changed",
                        "File metadata changed after discovery. Restart the search.",
                    )
            # The authenticated row is detached; no untrusted content executes.
            if state["page"] > len(row.locators):
                raise DomainError(
                    "source_changed", "Extracted document positions changed. Restart the search."
                )
            indexed += bool(fresh.data.get("usable_text", fresh.data.get("text", "").strip()))
            unread_searched |= not file["indexed"]
            file["indexed"] = bool(
                fresh.data.get("usable_text", fresh.data.get("text", "").strip())
            )
            state["unversioned"] |= file["source_version"] is None
            first_page = state["page"]
            state["hash"] = row.version_hash
            while state["page"] < len(row.locators) and len(results) < limit:
                page = row.locators[state["page"]]
                state["page"] += 1
                match = matcher.search(page["text"])
                if match is None:
                    continue
                at = max(0, match.start() - 160)
                results.append(
                    {
                        "file_id": row.id,
                        "title": row.title,
                        "page": page["page"],
                        "locator": passage_label(row, page, match.start(), match.end()),
                        **(
                            {
                                "sheet_name": page["sheet_name"],
                                "cell_references": cell_references(
                                    page, match.start(), match.end()
                                ),
                            }
                            if "sheet_name" in page
                            else {}
                        ),
                        "page_offset": at,
                        "passage": page["text"][at : at + 600],
                        "extraction_method": page.get("extraction_method", "text_extraction"),
                        "ocr_confidence": page.get("ocr_confidence"),
                        "content_hash": row.version_hash,
                        "url": row.url,
                    }
                )
            complete = state["page"] == len(row.locators)
            statuses.append(
                {
                    **info,
                    "state": row.file_state["stage"],
                    "content_hash": row.version_hash,
                    "extraction_coverage": row.file_state["coverage"],
                    "page_count": row.file_state["page_count"],
                    "positions_searched_this_response": state["page"] - first_page,
                    "document_search_finished": complete,
                    "limitations": row.limitations[:8],
                    "additional_limitation_count": max(0, len(row.limitations) - 8),
                }
            )
            document_source = source(
                row, "Document text; matching page/slide/section references are in results."
            )
            document_source.uncertainty = row.limitations[:8]
            if len(row.limitations) > 8:
                document_source.uncertainty.append(
                    "Additional extraction warnings are available from read_course_file."
                )
            sources[row.id] = document_source
            if not complete:
                break
            state["completed"] += 1
            state["partial"] += row.file_state["coverage"] != "text_only"
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            current, _ = bridge.selected(owner, ref, [course_id])
            if current.epoch != connection.epoch:
                raise DomainError(
                    "source_changed", "Course selection changed during document search."
                ) from exc
            statuses.append(
                {
                    **info,
                    "state": failure_state(exc),
                    "reason": exc.message,
                    "status": exc.status,
                    **exc.data,
                    "document_search_finished": False,
                }
            )
            state["failed"] += 1
        except TimeoutError:
            statuses.append(
                {
                    **info,
                    "state": "failed",
                    "reason": "Document search reached its time budget; no text from this file was returned.",
                    "document_search_finished": False,
                }
            )
            state["failed"] += 1
            budget_exhausted = True
        state["file"] += 1
        state["page"], state["hash"] = 0, None
        if budget_exhausted:
            break
    current, _ = bridge.selected(owner, ref, [course_id])
    if current.epoch != connection.epoch:
        raise DomainError("source_changed", "Course selection changed during document search.")
    more = state["file"] < len(files)
    next_cursor = (
        bridge.vault.seal({**state, "binding": binding}, owner, ref + ":document-search")
        if more
        else None
    )
    full_text = not (
        more
        or state["failed"]
        or state["partial"]
        or state["unversioned"]
        or inventory.status != "ok"
    )
    pending = [
        {"file_id": f["file_id"], "title": f["title"]}
        for f in files[state["file"] :]
        if not f["indexed"]
    ]
    warnings = [
        "Results cover a bounded, freshly authorized inventory observed over this search pass, not a simultaneous snapshot of all course content.",
        "Search is literal text, with the first match per extracted page/slide/section. Images, diagrams, unreadable pages and external readings are not searched. No match does not establish topic absence.",
        "Follow next_cursor with the same course/query/limit to combine results; completed documents are not downloaded again. A changed inventory requires restarting.",
        "Failed or unsupported documents are not empty documents. Retry them individually with read_course_file; this pass records the failure and advances.",
        *inventory.meta.warnings,
    ]
    response = Result(
        status="ok" if full_text else "partial_data",
        summary=f"{len(results)} matching passages in this response; {indexed} documents searched using authenticated extraction or current cache.",
        data={
            "results": results,
            "indexed_documents": indexed,
            "unindexed_documents": pending[:20],
            "unindexed_documents_truncated": len(pending) > 20,
            "document_statuses": statuses,
            "search_scope": "authorized_course_file_text_including_unread",
            "unread_documents_searched": unread_searched,
            "limit": limit,
            "limit_reached": len(results) == limit,
            "request_budget_exhausted": budget_exhausted,
            "unavailable_documents": sum(
                s["state"] in {"failed", "unsupported", "inaccessible"} for s in statuses
            ),
            "inventory_coverage": inventory.data["coverage"],
            "inventory_failures": inventory.data["inventory_failures"],
            "inventory_version": version,
            "next_cursor": next_cursor,
            "search_pass_finished": not more,
            "text_coverage_complete_in_bounded_inventory": full_text,
            "pass_progress": {
                "completed_documents": state["completed"],
                "failed_documents": state["failed"],
                "partially_extracted_documents": state["partial"],
                "unversioned_document_seen": state["unversioned"],
                "remaining_documents": len(files) - state["file"],
                "bounded_inventory_documents": len(files),
            },
            "next_step": "Continue with next_cursor; combine passages and coverage from each response."
            if more
            else "Search pass finished. Review failures and extraction/inventory limitations before drawing conclusions.",
            "content_boundary": "untrusted_source_data",
            "limitations": warnings,
        },
        sources=list(sources.values()),
        meta=bridge.meta(
            coverage=[
                Coverage(
                    course_ref=course_id,
                    resource="course_file_text",
                    state="complete" if full_text else "partial",
                    pagination_complete=not more,
                    warning="Text-only observed search pass; source inventory and extraction limitations still apply.",
                )
            ],
            next_cursor=next_cursor,
            warnings=warnings,
        ),
    )
    attach(response)
    if len(response.model_dump_json().encode()) > 200_000:
        raise DomainError(
            "needs_input",
            "Document search exceeded its response budget. Reduce the document or result limit.",
        )
    return response
