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
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


@pytest.mark.contract
@pytest.mark.parametrize(
    "pages_error,http,reason,label,action",
    [
        (404, 404, "RESOURCE_UNAVAILABLE", "unavailable", "check_resource_availability_in_canvas"),
        ("timeout", None, "INVENTORY_BRANCH_TIMEOUT", "request_budget", "resume_bounded_inventory"),
        ("unknown", None, "UNCLASSIFIED_FAILURE", "operation_failed", "review_request_diagnostics"),
    ],
)
async def test_outline_serializes_observed_collection_failures(
    running,
    token_factory,
    bridge,
    owner,
    seeded,
    monkeypatch,
    pages_error,
    http,
    reason,
    label,
    action,
):
    _, courses = bridge.selected(owner, seeded)
    course = courses[0]
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    if pages_error == 404:
        bridge.synthetic.failures["/api/v1/courses/11/pages"] = 404
    original = CanvasClient._get
    calls = []

    async def get(client, url):
        path = url.split("?", 1)[0]
        calls.append(path)
        if path.endswith("/pages"):
            if pages_error == "timeout":
                raise TimeoutError
            if pages_error == "unknown":
                raise DomainError("operation_failed", "private fixture detail")
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", get)
    async with client_session(running, token_factory(), read_timeout=30) as session:
        response = await session.call_tool(
            "get_course_outline", {"connection_id": seeded, "course_id": course.id}
        )
    result = response.structuredContent
    assert result["status"] == "partial_data"
    data = result["data"]
    assert data["inventory_status"]["completeness"] == "partial"
    for branch, status, code, failure, guidance in (
        ("pages", http, reason, label, action),
        (
            "files",
            403,
            "RESOURCE_PERMISSION_DENIED",
            "permission_denied",
            "check_student_access_and_endpoint_permissions",
        ),
    ):
        assert sum(path.endswith("/" + branch) for path in calls) == 1
        assert data["inventory_coverage"][branch] == "partial"
        assert data["inventory_failures"][branch] == failure
        detail = data["inventory_reason_codes"][branch]
        assert detail.get("upstream_http_status") == status
        assert detail["reason_code"] == code
        assert detail["recommended_action"] == guidance
    assert "private fixture detail" not in str(response)


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
    # Allow the other fixture branches to finish their real accounting transactions.
    # Page two stays blocked until the collection's own deadline.
    bridge.settings.refresh_budget_seconds = 3
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
    # Both bounded deadlines are valid: under load, the whole-outline deadline
    # can win before the per-file deadline. The non-starvation contract above
    # still requires fresh metadata for file 52 and retained data for file 51.
    assert result.data["inventory_status"]["file_metadata_failures"][file_id]["reason_code"] in {
        "INVENTORY_METADATA_TIMEOUT",
        "INVENTORY_REQUEST_BUDGET",
    }
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


@pytest.mark.parametrize(
    "http,reason,label",
    [
        (403, "RESOURCE_PERMISSION_DENIED", "permission_denied"),
        (404, "RESOURCE_UNAVAILABLE", "unavailable"),
    ],
)
async def test_later_denial_discards_received_page_in_same_collection(
    bridge, owner, seeded, readable, monkeypatch, http, reason, label
):
    course, _ = readable
    original = CanvasClient._get

    async def get(client, url):
        if "/files?" in url:
            if "page=2" in url:
                raise DomainError(
                    "permission_denied",
                    "Synthetic denial",
                    reason_code=reason,
                    upstream_http_status=http,
                )
            return [file_record(id=77)], url + "&page=2"
        return await original(client, url)

    monkeypatch.setattr(CanvasClient, "_get", get)
    result = await list_files(bridge, owner, seeded, course.id)
    assert "77" not in {f["canvas_file_id"] for f in result.data["files"]}
    assert result.data["inventory_reason_codes"]["files"]["upstream_http_status"] == http
    assert result.data["inventory_failures"]["files"] == label


async def test_overall_budget_cancels_all_metadata_tasks_and_reports_unattempted(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable
    bridge.synthetic.data["module_items"]["11"] = [
        {"type": "File", "content_id": n, "title": f"Synthetic {n}"} for n in range(51, 66)
    ]
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    # Real fixture admission and membership reads precede the stalled metadata.
    bridge.settings.refresh_budget_seconds = 3
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
    assert active == 0 and peak == 2
    assert status["unresolved_module_file_count"] == 15
    assert any(
        f["reason_code"] == "INVENTORY_NOT_ATTEMPTED"
        for f in status["file_metadata_failures"].values()
    )
    assert result.status == "partial_data"


def test_recovery_counts_only_explicitly_verified_references():
    from canvas_bridge.inventory_recovery import recovery_report

    rows = [{"access_state": "not_rechecked"} for _ in range(5)] + [{}, {"access_state": "unknown"}]

    def verified():
        return recovery_report({"files": rows}, "fixture", "0" * 32, [], [])[
            "verified_file_references"
        ]

    assert verified() == 0
    rows.append({"access_state": "available_at_inventory_check"})
    assert verified() == 1


@pytest.mark.parametrize("cap", [1, 2])
async def test_three_linked_metadata_reads_obey_policy_and_keep_collection_denial(
    bridge, owner, monkeypatch, cap
):
    from tests.conftest import seed

    policy = bridge.usage.fixture_policy
    limits = policy.limits.model_copy(update={"max_concurrency_per_token": cap})
    bridge.usage.fixture_policy = policy.model_copy(update={"limits": limits})
    seeded = await seed(bridge, owner)
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["files"] = {"11": [file_record(id=i) for i in (51, 52, 53)]}
    bridge.synthetic.data["module_items"] = {
        "11": [{"type": "File", "content_id": i, "title": f"Synthetic {i}"} for i in (51, 52, 53)]
    }
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    original = CanvasClient.one
    peak = active = 0

    async def one(client, endpoint, **ids):
        nonlocal peak, active
        if endpoint != Endpoint.FILE:
            return await original(client, endpoint, **ids)
        active += 1
        peak = max(active, peak)
        try:
            await asyncio.sleep(0.005)
            return await original(client, endpoint, **ids)
        finally:
            active -= 1

    monkeypatch.setattr(CanvasClient, "one", one)
    result = await list_files(bridge, owner, seeded, course.id)
    assert active == 0 and peak == cap
    assert result.status == "partial_data"
    assert result.data["inventory_reason_codes"]["files"]["upstream_http_status"] == 403
    assert result.data["inventory_status"]["fresh_file_count"] == 3
