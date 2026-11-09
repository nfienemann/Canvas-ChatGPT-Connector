"""Validate the course-qualified flat folder listing, including every ancestor.

Canvas's course folders endpoint includes all subfolders. Never follow its URL
fields or infer access from a folder: file metadata/read authorization is separate.
"""

from canvas_bridge.domain import DomainError
from canvas_bridge.policy import source_id


def folder_paths(rows, course):
    parents, paths = {}, {}
    try:
        for row in rows:
            if row.get("context_type") != "Course" or str(row.get("context_id")) != course:
                return {}, "INVENTORY_FOLDER_CONTEXT_MISMATCH"
            key = source_id(row["id"])
            parent = source_id(row["parent_folder_id"]) if row.get("parent_folder_id") else None
            if key in parents and parents[key] != parent:
                return {}, "INVENTORY_FOLDER_CONFLICT"
            parents[key] = parent
        for key in parents:
            path, seen, current = [], set(), key
            while current is not None:
                if current in seen:
                    return paths, "INVENTORY_FOLDER_CYCLE"
                if current not in parents:
                    return paths, "INVENTORY_FOLDER_PARENT_MISSING"
                seen.add(current)
                path.append(current)
                current = parents[current]
            paths[key] = list(reversed(path))
    except (DomainError, KeyError, TypeError):
        return {}, "INVENTORY_FOLDER_IDENTITY_INVALID"
    return paths, None


async def recover_folder_ids(client, course, folders, denied, methods, budget):
    """At most four verified folder pages. File rows are only object lookup hints."""
    import asyncio

    from canvas_bridge.file_download import file_access_issue
    from canvas_bridge.inventory_recovery import track_method

    candidates = set()
    pages = 0
    visited_folders = set()
    try:
        async with asyncio.timeout(budget):
            for row in folders.items:
                if any(
                    row.get(k) is True
                    for k in ("locked_for_user", "hidden_for_user", "for_submissions")
                ):
                    continue
                folder = source_id(row["id"])
                if folder in visited_folders:
                    continue
                visited_folders.add(folder)
                cursor = None
                seen = set()
                while True:
                    if pages >= 4:
                        folders.complete = False
                        folders.failure = folders.failure or "request_budget"
                        folders.reason_code = folders.reason_code or "INVENTORY_REQUEST_BUDGET"
                        return candidates
                    pages += 1
                    track_method("folder_metadata")
                    if "folder_metadata" not in methods:
                        methods.append("folder_metadata")
                    try:
                        rows, cursor, page_id = await client.folder_files_page(
                            course, folder, cursor=cursor
                        )
                    except DomainError as exc:
                        if (
                            exc.status in {"source_changed", "reconnect_required"}
                            or exc.upstream_http_status == 401
                        ):
                            raise
                        folders.complete = False
                        folders.failed_method = exc.details.get("failed_method", "folder_files")
                        if (
                            folders.failed_method == "folder_files"
                            and "folder_files" not in methods
                        ):
                            methods.append("folder_files")
                        folders.folder_failures[folder] = {
                            "failed_method": folders.failed_method,
                            "reason_code": exc.reason_code,
                            "upstream_http_status": exc.upstream_http_status,
                            "capability_observation": exc.details.get("capability_observation"),
                        }
                        folders.recent_denial = (
                            exc.details.get("capability_observation") == "recent_denial"
                        )
                        folders.failure = exc.status
                        folders.reason_code = exc.reason_code
                        folders.upstream_http_status = exc.upstream_http_status
                        folders.retry_after_seconds = exc.details.get("retry_after_seconds")
                        if exc.status == "retry_later":
                            return candidates
                        break
                    if "folder_files" not in methods:
                        methods.append("folder_files")
                    if page_id in seen:
                        folders.complete = False
                        folders.failure, folders.reason_code = (
                            "partial_data",
                            "INVENTORY_PAGINATION_CYCLE",
                        )
                        return candidates
                    seen.add(page_id)
                    for item in rows:
                        try:
                            ident = source_id(item.get("id", ""))
                        except DomainError:
                            folders.complete = False
                            folders.reason_code = folders.reason_code or "INVENTORY_PAGE_INVALID"
                            continue
                        issue = file_access_issue(item)
                        if issue is None:
                            candidates.add(ident)
                        else:
                            if issue == "RESOURCE_PERMISSION_DENIED":
                                denied.add(ident)
                            else:
                                candidates.add(ident)
                                folders.complete = False
                                folders.reason_code = folders.reason_code or issue
                    if not cursor:
                        break
    except TimeoutError:
        folders.complete = False
        folders.failure, folders.reason_code = "retry_later", "INVENTORY_BRANCH_TIMEOUT"
    return candidates
