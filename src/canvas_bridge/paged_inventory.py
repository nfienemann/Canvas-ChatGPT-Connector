"""Resumable course file discovery through the public file-list operation.

One bounded upstream page or course-qualified file lookup per call. All remaining
branches and continuation URLs stay in encrypted, owner-bound local checkpoints.
"""

import hashlib
import json

from canvas_bridge.assignment_links import inventory_links
from canvas_bridge.domain import Coverage, DomainError, Result, Source, utcnow
from canvas_bridge.failure_diagnostics import current as diagnostic_attempt
from canvas_bridge.file_download import file_access_issue, file_metadata, file_version, file_visible
from canvas_bridge.inventory_cursor import binding, load, save
from canvas_bridge.inventory_folders import folder_paths
from canvas_bridge.inventory_recovery import remember_assignments, track_method
from canvas_bridge.normalize import canonical_id, plain_text
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.storage import Course, Material

ENDPOINTS = {
    "files": Endpoint.FILES,
    "folders": Endpoint.FOLDERS,
    "modules": Endpoint.MODULES,
    "module_items": Endpoint.MODULE_ITEMS,
    "assignments": Endpoint.ASSIGNMENTS,
}
BRANCHES = ("files", "folders", "modules", "assignments")


def initial():
    return {
        "version": 1,
        "queue": [{"kind": kind, "branch": kind, "cursor": None} for kind in BRANCHES],
        "seen_pages": [],
        "verified_files": [],
        "nonempty_branches": [],
        "seen_tasks": [],
        "folders": {},
        "failures": {},
        "pages": dict.fromkeys(BRANCHES, 0),
    }


def enqueue(state, task):
    # Collection continuations are checked by page identity. Object tasks are
    # deduplicated by source identity AND discovery path, not filename.
    key = (task["kind"], task.get("id"), task.get("module"), task.get("assignment"))
    if list(key) not in state["seen_tasks"]:
        state["seen_tasks"].append(list(key))
        state["queue"].append(task)


def fail(state, branch, code, http=None, method=None):
    detail = {"reason_code": code or "INVENTORY_PAGE_INVALID", "upstream_http_status": http}
    if method:
        detail["failed_method"] = method
    if attempt := diagnostic_attempt.get():
        detail["request_id"] = attempt.request_id
    state["failures"].setdefault(branch, detail)


def reference_only(bridge, owner, ref, course, task, origin):
    """An authorized module/assignment link is a lookup hint, never access proof."""
    upstream = source_id(task["id"])
    identity = canonical_id(owner, ref, "file", f"{course.source_id}:{upstream}")
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref, lock=True)
        bridge.authorize(
            owner, ref, course.id, "files", "inventory_metadata", session=session
        ).require()
        row = session.get(Material, identity)
        if row is None:
            session.add(
                Material(
                    id=identity,
                    owner=owner,
                    connection_id=ref,
                    course_id=course.id,
                    source_id=upstream,
                    kind="file",
                    title="Unverified referenced file",
                    url=f"{origin}/courses/{course.source_id}/files/{upstream}",
                    version_hash="",
                    text="",
                    locators=[],
                    limitations=["Reference only; access has not been established."],
                    file_state={"stage": "reference_only"},
                )
            )
        elif (
            row.owner != owner
            or row.connection_id != ref
            or row.course_id != course.id
            or row.kind != "file"
            or row.source_id != upstream
        ):
            raise DomainError("permission_denied", "File mapping changed.")
    return {
        "file_id": identity,
        "canvas_file_id": upstream,
        "course_id": course.id,
        "source_version": None,
        "access_state": "reference_only_access_unverified",
        "modules": [{"id": task["module"]}] if task.get("module") else [],
        "assignments": [task["assignment"]] if task.get("assignment") else [],
        "folders": [],
    }


def record(bridge, owner, ref, course, metadata, task, origin):
    if not file_visible(metadata):
        return None
    upstream = source_id(metadata["id"])
    identity = canonical_id(owner, ref, "file", f"{course.source_id}:{upstream}")
    title = plain_text(str(metadata.get("display_name", "Untitled file")), 1000)
    version = file_version(metadata)
    inventory = {
        "filename": plain_text(str(metadata.get("filename", "")), 1000),
        "content_type": str(metadata.get("content-type", ""))[:200],
        "size": metadata.get("size"),
        "source_version": version,
    }
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref, lock=True)
        bridge.authorize(
            owner, ref, course.id, "files", "inventory_metadata", session=session
        ).require()
        current = bridge.store.owned(session, Course, owner, ref, course.id)
        if not current.selected or not current.accessible:
            raise DomainError("permission_denied", "Course is no longer selected.")
        row = session.get(Material, identity)
        if row is None:
            row = Material(
                id=identity,
                owner=owner,
                connection_id=ref,
                course_id=course.id,
                source_id=upstream,
                kind="file",
                title=title,
                url=f"{origin}/courses/{course.source_id}/files/{upstream}",
                version_hash="",
                text="",
                locators=[],
                limitations=["Not fetched."],
                file_state={},
            )
            session.add(row)
        else:
            row = bridge.store.owned(session, Material, owner, ref, identity)
            if row.course_id != course.id or row.kind != "file" or row.source_id != upstream:
                raise DomainError("permission_denied", "File mapping changed.")
            if row.file_state.get("version") != version:
                from canvas_bridge.course_files import clear

                clear(row)
            row.title = title
        if task.get("assignment"):
            remember_assignments(row, [task["assignment"]])
        row.file_state = {
            **row.file_state,
            "inventory": inventory,
            "inventory_checked_at": utcnow().isoformat(),
        }
    folder = metadata.get("folder_id")
    return {
        "file_id": identity,
        "canvas_file_id": upstream,
        "course_id": course.id,
        "source_version": version,
        "access_state": "available_at_inventory_check",
        "title": title,
        "filename": inventory["filename"],
        "type": inventory["content_type"],
        "size": inventory["size"],
        "modules": [{"id": task["module"]}] if task.get("module") else [],
        "assignments": [task["assignment"]] if task.get("assignment") else [],
        "folders": [canonical_id(owner, ref, "folder", f"{course.source_id}:{source_id(folder)}")]
        if folder is not None
        else [],
    }


async def page(bridge, owner, ref, course_id, cursor=None):
    await bridge.refresh_course_access(owner, ref)
    conn, courses = bridge.selected(owner, ref, [course_id])
    course = courses[0]
    bound = binding(conn, course)
    state = load(bridge, owner, ref, bound, cursor) if cursor else initial()
    if state.get("version") != 1 or not state.get("queue"):
        raise DomainError(
            "needs_input",
            "Inventory continuation has no remaining operation.",
            reason_code="INVENTORY_CURSOR_INVALID",
        )
    # Save the initial request BEFORE doing network work. A transient failure
    # returns this same continuation and never loses its unfinished branch.
    input_cursor = cursor or save(bridge, owner, ref, bound, state)
    task = state["queue"].pop(0)
    branch, kind = task["branch"], task["kind"]
    track_method(kind)
    methods = state.setdefault("retrieval_methods", [])
    if kind not in methods:
        methods.append(kind)
    denied = state.setdefault("denied_files", {})

    files, folder_graph, page_id, transient = [], [], None, None
    page_members = None
    observed_member = False
    async with bridge.client(owner, ref) as client:
        try:
            if kind == "file":
                if not task.get("folder"):
                    files.append(
                        reference_only(bridge, owner, ref, course, task, client.institution.origin)
                    )
                if task["id"] in denied:
                    detail = denied[task["id"]]
                    raise DomainError(
                        "permission_denied",
                        "File access was withheld in this inventory.",
                        reason_code=detail["reason_code"],
                        upstream_http_status=detail.get("upstream_http_status"),
                    )
                metadata = await file_metadata(client, course.source_id, task["id"])
                if item := record(
                    bridge, owner, ref, course, metadata, task, client.institution.origin
                ):
                    files[:] = [item]
            else:
                ids = {"course": course.source_id}
                if kind == "module_items":
                    ids["module"] = task["id"]
                if kind == "folder_files":
                    rows, next_link, page_id = await client.folder_files_page(
                        course.source_id, task["id"], cursor=task.get("cursor")
                    )
                else:
                    rows, next_link, page_id = await client.inventory_page(
                        ENDPOINTS[kind], cursor=task.get("cursor"), **ids
                    )
                if kind in {"files", "folder_files"}:
                    page_members = hashlib.sha256(
                        json.dumps([[source_id(row["id"]) for row in rows], next_link]).encode()
                    ).hexdigest()
                if "remaining_ids" in task:
                    # Re-read through the original authorized route before releasing
                    # buffered identities. A checkpoint cannot confer file visibility.
                    by_id = {source_id(row["id"]): row for row in rows}
                    if page_members != task["page_members"]:
                        raise DomainError(
                            "partial_data",
                            "The inventory page changed during continuation.",
                            reason_code="INVENTORY_PAGE_INVALID",
                        )
                    rows = [by_id[identity] for identity in task["remaining_ids"]]
                    page_id = hashlib.sha256(f"{page_id}:{len(rows)}".encode()).hexdigest()
                else:
                    if page_id in state["seen_pages"]:
                        raise DomainError(
                            "partial_data",
                            "Inventory pagination cycle detected.",
                            reason_code="INVENTORY_PAGINATION_CYCLE",
                        )
                    state["seen_pages"].append(page_id)
                    state["pages"][branch] += 1
                    if next_link:
                        state["queue"].append({**task, "cursor": next_link})
                for row in rows:
                    if kind in {"files", "folder_files"}:
                        identity = source_id(row["id"])
                        if identity in denied:
                            continue
                        issue = file_access_issue(row)
                        if issue == "RESOURCE_PERMISSION_DENIED":
                            denied[identity] = {"reason_code": issue}
                        elif issue:
                            fail(state, branch, issue, method=kind)
                        if (
                            kind == "folder_files"
                            and "files" in state["failures"]
                            and identity not in denied
                        ):
                            enqueue(
                                state,
                                {
                                    "kind": "file",
                                    "branch": "folders",
                                    "id": identity,
                                    "folder": task["id"],
                                },
                            )
                            continue
                        if item := record(
                            bridge, owner, ref, course, row, task, client.institution.origin
                        ):
                            files.append(item)
                    elif kind == "folders":
                        if any(
                            row.get(flag) is True
                            for flag in ("locked_for_user", "hidden_for_user", "for_submissions")
                        ):
                            continue
                        identity = source_id(row["id"])
                        observed_member = True
                        minimal = {
                            k: row.get(k)
                            for k in ("id", "parent_folder_id", "context_type", "context_id")
                        }
                        if identity in state["folders"] and state["folders"][identity] != minimal:
                            fail(state, branch, "INVENTORY_FOLDER_CONFLICT")
                        state["folders"][identity] = minimal
                        enqueue(
                            state,
                            {
                                "kind": "folder_files",
                                "branch": branch,
                                "id": identity,
                                "cursor": None,
                            },
                        )
                        folder_graph.append(
                            {
                                "id": canonical_id(
                                    owner, ref, "folder", f"{course.source_id}:{identity}"
                                ),
                                "parent_id": canonical_id(
                                    owner,
                                    ref,
                                    "folder",
                                    f"{course.source_id}:{source_id(row['parent_folder_id'])}",
                                )
                                if row.get("parent_folder_id")
                                else None,
                            }
                        )
                    elif kind == "modules":
                        if row.get("published") is not False and row.get("state") != "locked":
                            observed_member = True
                            module = source_id(row["id"])
                            enqueue(
                                state,
                                {
                                    "kind": "module_items",
                                    "branch": branch,
                                    "id": module,
                                    "module": canonical_id(
                                        owner, ref, "module", f"{course.source_id}:{module}"
                                    ),
                                    "cursor": None,
                                },
                            )
                    elif kind == "module_items":
                        if (
                            row.get("type") == "File"
                            and row.get("published") is not False
                            and row.get("locked_for_user") is not True
                        ):
                            enqueue(
                                state,
                                {
                                    "kind": "file",
                                    "branch": branch,
                                    "id": source_id(row["content_id"]),
                                    "module": task["module"],
                                },
                            )
                    elif kind == "assignments":
                        if (
                            row.get("published") is False
                            or row.get("hidden_to_user") is True
                            or row.get("locked_for_user") is True
                        ):
                            continue
                        observed_member = True
                        assignment = source_id(row["id"])
                        links, truncated = inventory_links(
                            row, client.institution.origin, course.source_id, resumable=True
                        )
                        if truncated:
                            fail(state, branch, "INVENTORY_ASSIGNMENT_LINK_LIMIT")
                        for linked in links:
                            enqueue(
                                state,
                                {
                                    "kind": "file",
                                    "branch": branch,
                                    "id": source_id(linked),
                                    "assignment": canonical_id(
                                        owner,
                                        ref,
                                        "assignment",
                                        f"{course.source_id}:{assignment}",
                                    ),
                                },
                            )
        except DomainError as exc:
            if (
                exc.status in {"reconnect_required", "source_changed"}
                or exc.upstream_http_status == 401
                or exc.reason_code
                in {
                    "STALE_SCOPE_SNAPSHOT",
                    "COURSE_NOT_SELECTED",
                    "SELECTED_SCOPE_MISMATCH",
                    "CONNECTION_OWNERSHIP_MISMATCH",
                    "CONNECTION_INACTIVE",
                }
            ):
                raise
            if kind == "file" and exc.status == "permission_denied":
                denied[task["id"]] = {
                    "reason_code": exc.reason_code or "UNKNOWN_AUTHORIZATION_FAILURE",
                    "upstream_http_status": exc.upstream_http_status,
                }
            if exc.status == "retry_later":
                transient = exc
            else:
                fail(
                    state,
                    branch,
                    exc.reason_code,
                    exc.upstream_http_status,
                    exc.details.get("failed_method", kind),
                )
        except (KeyError, TypeError, ValueError):
            fail(state, branch, "INVENTORY_PAGE_INVALID")

        if transient:
            return Result(
                status="retry_later",
                summary="Inventory page remains unfinished; resume the same cursor after the indicated delay.",
                data={
                    **transient.data,
                    "files": [],
                    "inventory_operation": kind,
                    "inventory_status": {"retrieval_methods": methods},
                },
                meta=bridge.meta(next_cursor=input_cursor),
            )
        with bridge.store.transaction() as session:
            current = bridge.store.connection(session, owner, ref)
            bridge.authorize(owner, ref, course.id, "course", session=session).require()
            if current.epoch != bound["epoch"]:
                raise DomainError(
                    "source_changed",
                    "Scope changed during inventory.",
                    reason_code="INVENTORY_SCOPE_CHANGED",
                )
        # Leave room for the coverage envelope, sealed cursor and release metadata
        # under the public 250,000-byte response limit. Measure serialized UTF-8.
        file_bytes = 0
        for index, item in enumerate(files):
            file_bytes += len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 1
            if file_bytes > 220_000:
                remaining = [entry["canvas_file_id"] for entry in files[index:]]
                state["queue"].insert(
                    0, {**task, "remaining_ids": remaining, "page_members": page_members}
                )
                files = files[:index]
                break
        if not any(t["branch"] == "folders" for t in state["queue"]):
            _, error = folder_paths(list(state["folders"].values()), course.source_id)
            if error:
                fail(state, "folders", error)
        coverage = {
            name: "partial"
            if name in state["failures"]
            else "not_refreshed"
            if any(t["branch"] == name for t in state["queue"])
            else "complete"
            for name in BRANCHES
        }
        complete = all(value == "complete" for value in coverage.values())
        # Legacy checkpoints lack prior distinct identities. Never infer an exact
        # total or complete-empty state from pages processed since the upgrade.
        verified = set(state.get("verified_files", []))
        current_verified = {
            item["file_id"]
            for item in files
            if item.get("access_state") == "available_at_inventory_check"
        }
        verified.update(current_verified)
        if (
            (observed_member or current_verified)
            and "nonempty_branches" in state
            and branch not in state["nonempty_branches"]
        ):
            state["nonempty_branches"].append(branch)
        counts_known = "verified_files" in state
        state["verified_files"] = sorted(verified)
        if not counts_known:
            state["legacy_counts_incomplete"] = True
        progress = {
            "distinct_verified_files": len(verified),
            "count_is_lower_bound": not complete or bool(state.get("legacy_counts_incomplete")),
            "branches_attempted": sum(
                bool(state["pages"][b]) or b in state["failures"] for b in BRANCHES
            ),
            "branches_completed": sum(v == "complete" for v in coverage.values()),
            "collections": {},
        }
        for name, value in coverage.items():
            failure = state["failures"].get(name, {})
            if value == "complete" and "nonempty_branches" in state:
                value = (
                    "complete_nonempty" if name in state["nonempty_branches"] else "complete_empty"
                )
            elif name in state["failures"] and not state["pages"][name]:
                value = (
                    "permission_denied"
                    if failure.get("reason_code") == "RESOURCE_PERMISSION_DENIED"
                    else "unavailable"
                )
            elif value == "not_refreshed" and state["pages"][name]:
                value = "partial"
            progress["collections"][name] = value
        progress["collections"]["pages"] = "unsupported"
        next_cursor = save(bridge, owner, ref, bound, state) if state["queue"] else None
        return Result(
            status="ok" if complete else "partial_data",
            summary="One authorized inventory step. Follow next_cursor until absent; only complete branch coverage establishes enumeration, and file reads require fresh authorization.",
            data={
                "files": files,
                "folder_graph": folder_graph,
                "inventory_status": {"retrieval_methods": methods},
                "coverage": coverage,
                "inventory_progress": progress,
                "inventory_reason_codes": state["failures"],
                "inventory_operation": kind,
                "page_identity": page_id,
                "document_content_included": False,
            },
            sources=[
                Source(
                    id=course.id,
                    title=course.name,
                    url=f"{client.institution.origin}/courses/{course.source_id}",
                    course_id=course.id,
                    source_type="canvas_inventory",
                    retrieved_at=utcnow(),
                )
            ],
            meta=bridge.meta(
                next_cursor=next_cursor,
                coverage=[
                    Coverage(
                        course_ref=course.id,
                        resource="materials_inventory",
                        state="complete" if complete else "partial",
                        pagination_complete=complete,
                        pages_consumed=sum(state["pages"].values()),
                    )
                ],
            ),
        )
