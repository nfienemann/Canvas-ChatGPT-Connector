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

from canvas_bridge.canvas import Collection, inventory_parallelism
from canvas_bridge.domain import Coverage, DomainError, Model, Result, Source, utcnow
from canvas_bridge.file_download import file_access_issue, file_metadata, file_version, file_visible
from canvas_bridge.inventory_recovery import inventory_action, remember_assignments, track_method
from canvas_bridge.normalize import canonical_id, plain_text
from canvas_bridge.parser_worker import PARSER, SUPPORTED_FORMATS
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.retention_policy import RAW_PAGE_LIFETIME
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


def filename_key(name):
    # A filename is a search hint. Ignore separators and an optional known extension.
    if not isinstance(name, str):
        return ()
    stem, sep, extension = name.casefold().rpartition(".")
    return tuple(
        re.findall(r"[^\W_]+", stem if sep and extension in SUPPORTED_FORMATS else name.casefold())
    )


async def outline(
    bridge,
    owner: str,
    ref: str,
    course_ref: str,
    module_filter: str | None = None,
    *,
    include_assignment_files: bool = False,
    filename: str | None = None,
) -> Result:
    await bridge.refresh_course_access(owner, ref)
    _, courses = bridge.selected(owner, ref, [course_ref])
    course = courses[0]
    modules, resources, warnings = [], [], []
    collection, pages, files = (Collection(failure="not_refreshed") for _ in range(3))
    raw_modules = []
    denied_files = set()
    uncertain_files = set()
    observed_at = utcnow().isoformat()
    module_failures, metadata_failures = {}, {}
    metadata_verified = set()
    assignment_paths = {}
    assignments = Collection(failure="not_refreshed")
    folders = Collection(failure="not_refreshed")
    folder_ancestors = {}
    assignment_links_complete = not include_assignment_files
    metadata_candidates = set()
    known_hint_refs = set()
    resolved_metadata = {}
    origins = {}
    methods = []
    hold = None
    recovery_holds = {
        "UPSTREAM_THROTTLED",
        "UPSTREAM_CIRCUIT_OPEN",
        "UPSTREAM_BUDGET_EXHAUSTED",
        "OWNER_RATE_LIMITED",
        "TASK_BUDGET_EXCEEDED",
        "LOCAL_REQUEST_BUSY",
        "AUTHORIZATION_BUSY",
    }
    attempted_collections = set()
    budget_exhausted, metadata_limit_reached = False, False
    target_name = filename_key(filename)

    def matches_name(row):
        return bool(target_name) and target_name in {
            filename_key(row.get("filename")),
            filename_key(row.get("display_name")),
        }

    async with bridge.client(owner, ref) as client:
        loop = asyncio.get_running_loop()
        inventory_deadline = loop.time() + bridge.settings.refresh_budget_seconds

        width = inventory_parallelism(bridge)

        async def inventory_collection(endpoint, **ids):
            # A slow branch must leave time for the other inventory sources.
            nonlocal hold
            if hold or loop.time() >= inventory_deadline:
                return Collection(failure="not_refreshed", reason_code="INVENTORY_NOT_ATTEMPTED")
            track_method(endpoint.name.lower())
            attempted_collections.add(endpoint)
            if endpoint.name.lower() not in methods:
                methods.append(endpoint.name.lower())
            result = await client.collection(
                endpoint,
                budget_seconds=min(
                    bridge.settings.refresh_budget_seconds / 4,
                    max(0, inventory_deadline - loop.time()),
                ),
                **({"include_submission": False} if endpoint == Endpoint.ASSIGNMENTS else {}),
                **ids,
            )
            if (
                result.failure in {"source_changed", "reconnect_required"}
                or result.upstream_http_status == 401
            ):
                raise DomainError(
                    result.failure,
                    "Current Canvas authorization is unavailable.",
                    reason_code=result.reason_code,
                    upstream_http_status=result.upstream_http_status,
                )
            if result.reason_code in recovery_holds and result.failure == "retry_later":
                hold = result.reason_code
            if result.reason_code == "UPSTREAM_REQUEST_TIMEOUT":
                result.reason_code = "INVENTORY_BRANCH_TIMEOUT"
            return result

        async def resolve_metadata(file_id, file_ref, until):
            nonlocal hold
            if loop.time() >= until:
                return
            track_method("file")
            if "file" not in methods:
                methods.append("file")
            metadata_failures[file_ref]["reason_code"] = "INVENTORY_REQUEST_BUDGET"
            try:
                async with asyncio.timeout_at(
                    min(until, loop.time() + bridge.settings.refresh_budget_seconds / 4)
                ):
                    metadata = await file_metadata(client, course.source_id, file_id)
            except TimeoutError:
                metadata_failures[file_ref] = {
                    "status": "retry_later",
                    "reason_code": "INVENTORY_METADATA_TIMEOUT",
                }
                return
            except DomainError as exc:
                if (
                    exc.status in {"reconnect_required", "source_changed"}
                    or exc.upstream_http_status == 401
                ):
                    raise
                if exc.reason_code in recovery_holds:
                    hold = exc.reason_code
                if exc.status == "permission_denied":
                    denied_files.add(file_id)
                metadata_failures[file_ref] = {
                    "status": exc.status,
                    "reason_code": exc.reason_code,
                    "upstream_http_status": exc.upstream_http_status,
                    **(
                        {"retrieval_constraint": exc.details["retrieval_constraint"]}
                        if "retrieval_constraint" in exc.details
                        else {}
                    ),
                }
                return
            # Record each successful result before a sibling can time out.
            resolved_metadata[file_id] = metadata
            metadata_failures.pop(file_ref, None)
            metadata_verified.add(file_id)

        async def resolve_ids(ids, origin):
            nonlocal metadata_limit_reached
            if hold:
                return
            # Once a name has current object evidence, keep collecting associations
            # but avoid probing unrelated files just to answer the named lookup.
            if filename and (
                listed_match or any(matches_name(row) for row in resolved_metadata.values())
            ):
                return
            pending = []
            for file_id in ids:
                if file_id in known or file_id in metadata_candidates or file_id in denied_files:
                    continue
                if len(metadata_candidates) + (0 if filename else len(known)) >= 100:
                    metadata_limit_reached = True
                    break
                metadata_candidates.add(file_id)
                file_ref = canonical_id(owner, ref, "file", f"{course.source_id}:{file_id}")
                metadata_failures[file_ref] = {
                    "status": "retry_later",
                    "reason_code": "INVENTORY_NOT_ATTEMPTED",
                }
                if origin == "known_file_metadata":
                    known_hint_refs.add(file_ref)
                origins[file_id] = origin
                pending.append((file_id, file_ref))
            until = inventory_deadline
            if include_assignment_files and origin in {
                "known_file_metadata",
                "module_file_metadata",
                "folder_file_metadata",
            }:
                # Leave time for independent assignment and page collections.
                until -= bridge.settings.refresh_budget_seconds / 3
            elif origin == "assignment_file_metadata":
                until -= bridge.settings.refresh_budget_seconds / 6
            for offset in range(0, len(pending), width):
                if hold or loop.time() >= until:
                    break
                outcomes = await asyncio.gather(
                    *(resolve_metadata(*pair, until) for pair in pending[offset : offset + width]),
                    return_exceptions=True,
                )
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome

        # One budget covers the entire outline, not a fresh budget per module.
        files = (
            Collection(failure="module_filtered_inventory")
            if module_filter
            else await inventory_collection(Endpoint.FILES, course=course.source_id)
        )
        if any(file_access_issue(f) == "UNKNOWN_AUTHORIZATION_FAILURE" for f in files.items):
            files.complete = False
            files.failure = files.failure or "partial_data"
            files.reason_code = files.reason_code or "UNKNOWN_AUTHORIZATION_FAILURE"
        for row in files.items:
            issue = file_access_issue(row)
            if issue == "RESOURCE_PERMISSION_DENIED":
                denied_files.add(str(row["id"]))
            elif issue == "UNKNOWN_AUTHORIZATION_FAILURE":
                uncertain_files.add(str(row["id"]))
        if filename:
            files.items.sort(key=matches_name, reverse=True)
        listed_match = bool(
            filename and any(matches_name(row) and file_visible(row) for row in files.items)
        )
        needs_recovery = not files.complete or bool(filename and not listed_match)
        if include_assignment_files and needs_recovery:
            client.inventory_requests_remaining = 24
        known = {str(row["id"]) for row in files.items[:100] if file_visible(row)}
        if filename and not listed_match and not module_filter and not hold:
            # Read only scoped index identifiers and titles, never saved text.
            with bridge.store.transaction() as session:
                bridge.authorize(
                    owner, ref, course.id, "files", "inventory_metadata", session=session
                ).require()
                hints = session.execute(
                    select(Material.source_id, Material.title)
                    .where(
                        Material.owner == owner,
                        Material.connection_id == ref,
                        Material.course_id == course.id,
                        Material.kind == "file",
                    )
                    .order_by(Material.retrieved_at.desc(), Material.id)
                    .limit(201)
                ).all()
            await resolve_ids(
                [
                    source_id(row.source_id)
                    for row in hints[:200]
                    if filename_key(row.title) == filename_key(filename)
                ][:8],
                "known_file_metadata",
            )
        collection = await inventory_collection(Endpoint.MODULES, course=course.source_id)
        for module in collection.items[:30]:
            if (
                include_assignment_files
                and not module_filter
                and loop.time() > inventory_deadline - bridge.settings.refresh_budget_seconds / 3
            ):
                break
            if module.get("published") is False or module.get("state") == "locked":
                continue
            module_id = source_id(module["id"])
            if (
                module_filter
                and canonical_id(owner, ref, "module", f"{course.source_id}:{module_id}")
                != module_filter
            ):
                continue
            items = await inventory_collection(
                Endpoint.MODULE_ITEMS, course=course.source_id, module=module_id
            )
            raw_modules.append((module_id, module, items))
            if not items.complete or len(items.items) > 100:
                module_failures[
                    canonical_id(owner, ref, "module", f"{course.source_id}:{module_id}")
                ] = {
                    "failure": items.inventory_failure or "item_limit",
                    "upstream_http_status": items.upstream_http_status,
                    "reason_code": items.reason_code or "INVENTORY_ITEM_LIMIT",
                }
            await resolve_ids(
                (
                    source_id(item["content_id"])
                    for item in items.items[:100]
                    if item.get("type") == "File"
                    and item.get("published") is not False
                    and item.get("locked_for_user") is not True
                ),
                "module_file_metadata",
            )
        if include_assignment_files and not module_filter:
            from canvas_bridge.assignment_links import inventory_links
            from canvas_bridge.inventory_folders import folder_paths

            folders = await inventory_collection(Endpoint.FOLDERS, course=course.source_id)
            folder_ancestors, folder_error = folder_paths(folders.items, course.source_id)
            if folder_error:
                folders.complete = False
                folders.failure = "partial_data"
                folders.reason_code = folder_error

            if (
                needs_recovery
                and not folder_error
                and folders.items
                and not (
                    filename
                    and (
                        listed_match or any(matches_name(row) for row in resolved_metadata.values())
                    )
                )
            ):
                from canvas_bridge.inventory_folders import recover_folder_ids

                folder_candidates = await recover_folder_ids(
                    client,
                    course.source_id,
                    folders,
                    denied_files,
                    methods,
                    min(
                        bridge.settings.refresh_budget_seconds / 4,
                        max(0, inventory_deadline - loop.time()),
                    ),
                )
                if folders.failure == "retry_later" and folders.reason_code in recovery_holds:
                    hold = folders.reason_code
                await resolve_ids(sorted(folder_candidates), "folder_file_metadata")
            assignments = await inventory_collection(Endpoint.ASSIGNMENTS, course=course.source_id)
            assignment_links_complete = assignments.complete and len(assignments.items) <= 100
            if len(assignments.items) > 100:
                assignments.failure = "partial_data"
                assignments.reason_code = "INVENTORY_ASSIGNMENT_LIMIT"
            for assignment in assignments.items[:100]:
                if (
                    any(
                        assignment.get(key) is True for key in ("locked_for_user", "hidden_to_user")
                    )
                    or assignment.get("published") is False
                ):
                    continue
                assignment_id = source_id(assignment["id"])
                links, truncated = inventory_links(
                    assignment, client.institution.origin, course.source_id
                )
                assignment_links_complete &= not truncated
                if truncated and not assignments.reason_code:
                    assignments.failure = "partial_data"
                    assignments.reason_code = "INVENTORY_ASSIGNMENT_LINK_LIMIT"
                for file_id in links:
                    assignment_paths.setdefault(file_id, set()).add(
                        canonical_id(
                            owner,
                            ref,
                            "assignment",
                            f"{course.source_id}:{assignment_id}",
                        )
                    )
            await resolve_ids(assignment_paths, "assignment_file_metadata")
        pages = await inventory_collection(Endpoint.PAGES, course=course.source_id)
        if loop.time() >= inventory_deadline:
            budget_exhausted = True
            warnings.append("The course outline reached its overall request time limit.")

        # Network completion order must not change reference order or truncation.
        file_collection_nonempty = any(file_visible(row) for row in files.items)
        files.items = [
            row for row in files.items if file_visible(row) and str(row["id"]) not in denied_files
        ]
        files.items.extend(
            resolved_metadata[key]
            for key in sorted(resolved_metadata, key=int)
            if key not in denied_files
        )

        if filename:
            files.items.sort(key=matches_name, reverse=True)

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
                        material = Material(
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
                        session.add(material)
                    else:
                        material.title, material.url = title, url
                        if kind == "file" and (
                            material.file_state.get("version") != file_version(entry)
                            or (utcnow() - aware(material.retrieved_at)).total_seconds()
                            > bridge.settings.file_cache_hours * 3600
                        ):
                            from canvas_bridge.course_files import clear

                            clear(material)
                    if kind == "file":
                        material.file_state = {
                            **(material.file_state or {}),
                            "inventory": {
                                "filename": plain_text(str(entry.get("filename", "")), 1000),
                                "content_type": str(entry.get("content-type", ""))[:200],
                                "size": entry.get("size"),
                                "source_version": file_version(entry),
                            },
                            "inventory_checked_at": utcnow().isoformat(),
                        }
                    if kind == "file":
                        remember_assignments(material, assignment_paths.get(upstream))
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
                                    "assignments": sorted(assignment_paths.get(upstream, set())),
                                    "folders": [
                                        canonical_id(
                                            owner, ref, "folder", f"{course.source_id}:{folder}"
                                        )
                                        for folder in folder_ancestors.get(
                                            str(entry.get("folder_id")), []
                                        )
                                    ],
                                    "access_state": "available_at_inventory_check",
                                    "reference_origin": origins[upstream]
                                    if upstream in metadata_verified
                                    else "course_file_inventory",
                                    "inventory_freshness": "fresh",
                                    "inventory_checked_at": material.file_state[
                                        "inventory_checked_at"
                                    ],
                                    "access_verification": "course_file_metadata"
                                    if upstream in metadata_verified
                                    else "file_list_visibility",
                                }
                                if kind == "file"
                                else {}
                            ),
                        }
                    )
            # A partial inventory cannot revoke a previously returned reference.
            # Reuse only the owned, course-bound reference for a currently visible
            # module item. This is a lookup hint, not a fresh access grant; every
            # read/status/search still requires course-qualified file metadata.
            for _, _, items in raw_modules:
                for item in items.items[:100]:
                    if (
                        item.get("type") != "File"
                        or item.get("published") is False
                        or item.get("locked_for_user") is True
                    ):
                        continue
                    upstream = source_id(item.get("content_id", ""))
                    lookup = ("File", upstream)
                    if (
                        lookup in references
                        or upstream in denied_files
                        or upstream in uncertain_files
                    ):
                        continue
                    if sum(r["kind"] == "file" for r in resources) >= 100:
                        continue
                    identity = canonical_id(owner, ref, "file", f"{course.source_id}:{upstream}")
                    cached = session.get(Material, identity)
                    if (
                        cached is None
                        or cached.owner != owner
                        or cached.connection_id != ref
                        or cached.course_id != course_ref
                        or cached.kind != "file"
                        or cached.source_id != upstream
                        or cached.file_state.get("stage") == "inaccessible"
                    ):
                        continue
                    references[lookup] = identity
                    resources.append(
                        {
                            **cached.file_state.get("inventory", {}),
                            "id": identity,
                            "title": cached.title,
                            "url": cached.url,
                            "kind": "file",
                            "reading_status": "not_established",
                            "access_state": "not_rechecked",
                            "reference_origin": "previously_discovered_module_file",
                            "inventory_freshness": "retained",
                            "inventory_checked_at": cached.file_state.get("inventory_checked_at"),
                            "access_verification": "not_rechecked",
                        }
                    )
                    warnings.append(
                        "A previously discovered module file reference was retained; current file access must be checked by the reader."
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
                    if any(
                        r["id"] == material_ref and r.get("access_state") == "not_rechecked"
                        for r in resources
                    ):
                        visible["material_availability"] = (
                            "previously_discovered_access_not_rechecked"
                        )
                elif item.get("type") in {"File", "Page"}:
                    visible["material_availability"] = (
                        "inaccessible"
                        if lookup[0] == "File" and lookup[1] in denied_files
                        else "not_resolved_in_this_inventory"
                    )
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
            course_id=course_ref,
            source_type="canvas_inventory",
        )
    visible_module_count = sum(
        m.get("published") is not False
        and m.get("state") != "locked"
        and (
            not module_filter
            or canonical_id(owner, ref, "module", f"{course.source_id}:{source_id(m['id'])}")
            == module_filter
        )
        for m in collection.items[:30]
    )
    modules_complete = (
        collection.complete
        and len(collection.items) <= 30
        and len(raw_modules) == visible_module_count
        and all(m["items_complete"] for m in modules)
    )
    retained_count = sum(r.get("access_state") == "not_rechecked" for r in resources)
    fresh_count = sum(r.get("access_state") == "available_at_inventory_check" for r in resources)
    module_file_ids = {
        source_id(item["content_id"])
        for _, _, items in raw_modules
        for item in items.items[:100]
        if item.get("type") == "File"
        and item.get("published") is not False
        and item.get("locked_for_user") is not True
    }
    fresh_file_ids = {str(entry["id"]) for entry in files.items[:100] if file_visible(entry)}
    unresolved_module_files = module_file_ids - fresh_file_ids
    assignment_links_complete &= not (set(assignment_paths) - fresh_file_ids)
    if (
        include_assignment_files
        and assignments.complete
        and not assignment_links_complete
        and not assignments.reason_code
    ):
        assignments.failure = "partial_data"
        assignments.reason_code = "INVENTORY_ASSIGNMENT_FILE_UNRESOLVED"
    inventory_collections = [("pages", pages), ("files", files), ("modules", collection)]
    if include_assignment_files:
        inventory_collections.append(("assignments", assignments))
        inventory_collections.append(("folders", folders))
    for _, branch in inventory_collections:
        if branch.reason_code is None and branch.failure in {
            "request_budget",
            "not_refreshed",
            "module_filtered_inventory",
        }:
            branch.reason_code = (
                "INVENTORY_REQUEST_BUDGET"
                if branch.failure == "request_budget"
                else "INVENTORY_NOT_ATTEMPTED"
            )
        elif branch.failure and branch.reason_code is None:
            branch.reason_code = "UNCLASSIFIED_FAILURE"
    complete = (
        collection.complete
        and pages.complete
        and files.complete
        and len(collection.items) <= 30
        and len(pages.items) <= 100
        and len(files.items) <= 100
        and all(m["items_complete"] for m in modules)
        and modules_complete
        and not unresolved_module_files
        and not metadata_failures
        and not metadata_limit_reached
        and not warnings
        and assignment_links_complete
        and (not include_assignment_files or folders.complete)
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
                "formats": list(SUPPORTED_FORMATS),
                "parser": PARSER,
            },
            "inventory_coverage": {
                **(
                    {"folders": "complete" if folders.complete else "partial"}
                    if include_assignment_files
                    else {}
                ),
                **(
                    {
                        "assignments": "complete"
                        if assignment_links_complete
                        and not (set(assignment_paths) - fresh_file_ids)
                        else "partial"
                    }
                    if include_assignment_files
                    else {}
                ),
                **{
                    name: "complete"
                    if c.complete
                    and len(c.items) <= limit
                    and (name != "modules" or modules_complete)
                    else "partial"
                    for name, c, limit in (
                        ("pages", pages, 100),
                        ("files", files, 100),
                        ("modules", collection, 30),
                    )
                },
            },
            "inventory_failures": {
                name: c.inventory_failure for name, c in inventory_collections if c.failure
            },
            "inventory_reason_codes": {
                name: {
                    "reason_code": c.reason_code,
                    "recommended_action": inventory_action(c.reason_code, c.retrieval_constraint),
                    "pages_consumed": c.pages,
                    "upstream_http_status": c.upstream_http_status,
                    **(
                        {"retrieval_constraint": c.retrieval_constraint}
                        if c.retrieval_constraint
                        else {}
                    ),
                    **({"failed_method": c.failed_method} if c.failed_method else {}),
                    **({"capability_observation": "recent_denial"} if c.recent_denial else {}),
                    **(
                        {"retry_after_seconds": c.retry_after_seconds}
                        if c.retry_after_seconds is not None
                        else {}
                    ),
                }
                for name, c in inventory_collections
                if c.reason_code
            },
            "inventory_status": {
                "completeness": "complete" if complete else "partial",
                "retrieval_methods": methods,
                "observed_at": observed_at,
                "freshness": "mixed"
                if retained_count and fresh_count
                else "retained"
                if retained_count
                else "fresh"
                if fresh_count
                else "no_file_observations",
                "branches_attempted": len(
                    attempted_collections.intersection(
                        {
                            Endpoint.FILES,
                            Endpoint.PAGES,
                            Endpoint.FOLDERS,
                            Endpoint.MODULES,
                            Endpoint.ASSIGNMENTS,
                        }
                    )
                ),
                "collection_nonempty": {
                    "files": file_collection_nonempty,
                    "modules": bool(modules),
                    "pages": any(item["kind"] == "page" for item in resources),
                    "folders": any(
                        str(f.get("id")) in folder_ancestors
                        and not any(
                            f.get(flag) is True
                            for flag in ("locked_for_user", "hidden_for_user", "for_submissions")
                        )
                        for f in folders.items
                    ),
                    "assignments": any(
                        row.get("published") is not False
                        and row.get("locked_for_user") is not True
                        and row.get("hidden_to_user") is not True
                        for row in assignments.items
                    ),
                },
                "fresh_file_count": fresh_count,
                "retained_file_count": retained_count,
                "module_file_coverage": "complete"
                if modules_complete and not unresolved_module_files
                else "partial",
                "module_file_reference_count": len(module_file_ids),
                "unresolved_module_file_count": len(unresolved_module_files),
                "module_item_failures": module_failures,
                "file_metadata_failures": {
                    ref: detail
                    for ref, detail in metadata_failures.items()
                    if ref not in known_hint_refs
                },
                "known_lookup_failures": [
                    detail for ref, detail in metadata_failures.items() if ref in known_hint_refs
                ],
                "folder_lookup_failures": {
                    canonical_id(owner, ref, "folder", f"{course.source_id}:{folder}"): detail
                    for folder, detail in folders.folder_failures.items()
                },
                "request_budget_exhausted": budget_exhausted,
                "file_metadata_limit_reached": metadata_limit_reached,
                "content_reads_require_fresh_authorization": True,
            },
            "limitations": [
                "Use read_course_file or fetch_course_material to read file text when isolated extraction is enabled.",
                "External/LTI readings are not fetched. Module inclusion alone does not establish assigned versus optional status.",
            ],
        },
        sources=[source],
        meta=bridge.meta(
            coverage=[
                Coverage(
                    course_ref=course_ref,
                    resource="materials_inventory",
                    state="complete" if complete else "partial",
                    pagination_complete=complete,
                    warning=None
                    if complete
                    else "Some inventory branches, item lookups or request budgets are incomplete.",
                )
            ],
            warnings=warnings,
        ),
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
                Material.retrieved_at > bridge.retention.clock() - RAW_PAGE_LIFETIME,
                Material.course_id.in_([c.id for c in courses]),
            )
            .limit(1000)
        ).all()
        candidate_limit_reached = len(rows) == 1000
        # Search only the already-authorized, bounded plaintext working set.
        # Sensitive source text is ciphertext in persistent storage.
        rows = [
            r
            for r in rows
            if query.casefold() in r.text.casefold() or query.casefold() in r.title.casefold()
        ][: limit + 1]
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
            "candidate_limit_reached": candidate_limit_reached,
            "file_text_searched": False,
            "unfetched_content_searched": False,
            "next_step": "Use list_course_files to discover PDFs, read_course_file to extract likely documents, then search_course_files for indexed file passages.",
            "truncated": len(rows) > limit,
        },
        sources=sources,
        meta=bridge.meta(warnings=["This is not a complete course reading search."]),
    )
