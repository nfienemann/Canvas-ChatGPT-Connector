"""Synthetic regressions for restricted inventory and resumable partial search."""

import asyncio

import pytest

from canvas_bridge import document_search
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.course_files import list_files, read_file
from canvas_bridge.domain import DomainError
from canvas_bridge.policy import Endpoint
from tests.test_course_files import file_record
from tests.test_document_search import add_pdf, downloads, search
from tests.test_file_reading import readable as readable


@pytest.mark.parametrize("first_partial", [True, False])
async def test_cursor_survives_observation_changes_but_remembers_partial_coverage(
    bridge, owner, seeded, readable, monkeypatch, first_partial
):
    course, _ = readable
    add_pdf(bridge, 52)
    original = document_search.list_files
    calls = 0

    async def inventory(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        partial = first_partial if calls == 0 else not first_partial
        calls += 1
        if partial:
            result.status = "partial_data"
            result.data["coverage"]["files"] = "partial"
            result.data["inventory_failures"]["files"] = "retry_later"
            for file in result.data["files"]:
                file.update(inventory_freshness="retained", access_verification="not_rechecked")
        return result

    monkeypatch.setattr(document_search, "list_files", inventory)
    first = await search(bridge, owner, seeded, course, max_documents=1)
    second = await search(
        bridge, owner, seeded, course, max_documents=1, cursor=first.data["next_cursor"]
    )
    assert second.data["search_pass_finished"]
    assert second.data["pass_progress"]["completed_documents"] == 2
    assert second.data["pass_progress"]["inventory_incomplete_seen"]
    assert second.status == "partial_data"
    assert "INVENTORY_INCOMPLETE" in second.data["coverage_reasons"]
    assert not second.data["text_coverage_complete_in_bounded_inventory"]
    assert len(downloads(bridge)) == 2
    assert {r["file_id"] for r in first.data["results"]}.isdisjoint(
        {r["file_id"] for r in second.data["results"]}
    )


@pytest.mark.parametrize("change", ["add", "remove", "version"])
async def test_real_inventory_changes_still_reject_continuation(
    bridge, owner, seeded, readable, change
):
    course, _ = readable
    add_pdf(bridge, 52)
    first = await search(bridge, owner, seeded, course, max_documents=1)
    if change == "add":
        add_pdf(bridge, 53)
    elif change == "remove":
        bridge.synthetic.data["files"]["11"].pop()
    else:
        bridge.synthetic.data["files"]["11"][-1]["updated_at"] = "2026-10-23T12:00:00Z"
    with pytest.raises(DomainError) as error:
        await search(bridge, owner, seeded, course, cursor=first.data["next_cursor"])
    assert error.value.status == "source_changed"


async def test_branch_timeout_retains_already_received_inventory_page(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable
    bridge.settings.refresh_budget_seconds = 0.4
    original = CanvasClient._get

    async def get(client, url):
        if "/files?" in url:
            if "page=2" in url:
                await asyncio.Event().wait()
            return [file_record(id=77)], url + "&page=2"
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", get)
    result = await list_files(bridge, owner, seeded, course.id)
    assert "77" in {f["canvas_file_id"] for f in result.data["files"]}
    assert (
        result.data["inventory_reason_codes"]["files"]["reason_code"] == "INVENTORY_BRANCH_TIMEOUT"
    )
    assert result.status == "partial_data"
    assert result.data["coverage"]["modules"] == "complete"


async def test_slow_module_file_does_not_starve_other_metadata(
    bridge, owner, seeded, readable, monkeypatch
):
    course, file_id = readable
    bridge.synthetic.data["files"]["11"].append(file_record(id=52))
    bridge.synthetic.data["module_items"]["11"].append(
        {"title": "Second synthetic file", "type": "File", "content_id": 52}
    )
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    bridge.settings.refresh_budget_seconds = 0.8
    original = CanvasClient.one
    active, peak = 0, 0

    async def one(client, endpoint, **ids):
        nonlocal active, peak
        if endpoint != Endpoint.FILE:
            return await original(client, endpoint, **ids)
        active += 1
        peak = max(peak, active)
        try:
            if ids["file"] == "51":
                await asyncio.Event().wait()
            return await original(client, endpoint, **ids)
        finally:
            active -= 1

    monkeypatch.setattr(CanvasClient, "one", one)
    result = await list_files(bridge, owner, seeded, course.id)
    files = {f["canvas_file_id"]: f for f in result.data["files"]}
    assert files["52"]["inventory_freshness"] == "fresh"
    assert files["51"]["inventory_freshness"] == "retained"
    assert active == 0 and 1 < peak <= 3
    assert (
        result.data["inventory_status"]["file_metadata_failures"][file_id]["reason_code"]
        == "INVENTORY_METADATA_TIMEOUT"
    )
    assert result.data["inventory_status"]["module_file_coverage"] == "partial"


async def test_restricted_course_list_does_not_hide_complete_module_resolution(
    bridge, owner, seeded, readable
):
    course, _ = readable
    bridge.synthetic.failures.update(
        {
            "/api/v1/courses/11/files": 403,
            "/api/v1/courses/11/pages": 404,
        }
    )
    result = await list_files(bridge, owner, seeded, course.id)
    status = result.data["inventory_status"]
    assert result.status == "partial_data" and status["completeness"] == "partial"
    assert status["module_file_coverage"] == "complete"
    assert status["module_file_reference_count"] == 1
    assert status["unresolved_module_file_count"] == 0
    assert result.data["inventory_reason_codes"]["files"]["upstream_http_status"] == 403
    assert result.data["inventory_reason_codes"]["pages"]["upstream_http_status"] == 404
    assert all(request.method == "GET" for request in bridge.synthetic.requests)


async def test_retained_search_reference_still_requires_fresh_permission(
    bridge, owner, seeded, readable, monkeypatch
):
    course, file_id = readable
    await read_file(bridge, owner, seeded, file_id)
    inventory = await list_files(bridge, owner, seeded, course.id)
    inventory.data["files"][0].update(
        inventory_freshness="retained", access_verification="not_rechecked"
    )

    async def retained(*args, **kwargs):
        return inventory

    monkeypatch.setattr(document_search, "list_files", retained)
    bridge.synthetic.data["files"]["11"][0]["locked_for_user"] = True
    result = await search(bridge, owner, seeded, course)
    assert not result.data["results"]
    assert result.data["document_statuses"][0]["state"] == "inaccessible"
    assert result.status == "partial_data"


async def test_later_denial_discards_received_page_in_same_collection(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable
    original = CanvasClient._get

    async def get(client, url):
        if "/files?" in url:
            if "page=2" in url:
                raise DomainError(
                    "permission_denied",
                    "Synthetic denial",
                    reason_code="RESOURCE_PERMISSION_DENIED",
                    upstream_http_status=403,
                )
            return [file_record(id=77)], url + "&page=2"
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", get)
    result = await list_files(bridge, owner, seeded, course.id)
    assert "77" not in {f["canvas_file_id"] for f in result.data["files"]}
    assert result.data["inventory_reason_codes"]["files"]["upstream_http_status"] == 403


async def test_overall_budget_cancels_all_metadata_tasks_and_reports_unattempted(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable
    bridge.synthetic.data["module_items"]["11"] = [
        {"type": "File", "content_id": n, "title": f"Synthetic {n}"} for n in range(51, 66)
    ]
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    bridge.settings.refresh_budget_seconds = 0.4
    original = CanvasClient.one
    active, peak = 0, 0

    async def one(client, endpoint, **ids):
        nonlocal active, peak
        if endpoint != Endpoint.FILE:
            return await original(client, endpoint, **ids)
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    monkeypatch.setattr(CanvasClient, "one", one)
    result = await list_files(bridge, owner, seeded, course.id)
    status = result.data["inventory_status"]
    assert status["request_budget_exhausted"] and active == 0 and peak == 3
    assert status["unresolved_module_file_count"] == 15
    assert any(
        f["reason_code"] == "INVENTORY_REQUEST_BUDGET"
        for f in status["file_metadata_failures"].values()
    )
    assert result.status == "partial_data"
