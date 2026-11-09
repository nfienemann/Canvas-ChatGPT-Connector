"""Fictional resumable inventories, including the actual public MCP path."""

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.course_files import list_files
from canvas_bridge.domain import DomainError
from canvas_bridge.inventory_cursor import KIND, binding, load
from canvas_bridge.normalize import canonical_id
from canvas_bridge.storage import LocalRecord
from tests.test_course_files import file_record
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


async def crawl(bridge, owner, seeded, course):
    cursor, pages = None, []
    for _ in range(500):
        result = await list_files(
            bridge, owner, seeded, course, inventory_mode="resumable", cursor=cursor
        )
        pages.append(result)
        cursor = result.meta.next_cursor
        if not cursor:
            return pages
    pytest.fail("Inventory did not terminate")


@pytest.mark.parametrize(
    "visibility,expected_coverage",
    [
        ({"hidden_for_user": None}, "partial"),
        ({"locked_for_user": "false"}, "partial"),
        ({"hidden_for_user": True}, "complete"),
    ],
)
async def test_unknown_file_visibility_cannot_be_a_complete_empty_inventory(
    bridge, owner, seeded, visibility, expected_coverage
):
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["files"] = {"11": [file_record(id=51, **visibility)]}
    result = await list_files(bridge, owner, seeded, course.id, inventory_mode="resumable")
    assert result.data["files"] == []
    assert result.data["coverage"]["files"] == expected_coverage
    if expected_coverage == "partial":
        assert (
            result.data["inventory_reason_codes"]["files"]["reason_code"]
            == "UNKNOWN_AUTHORIZATION_FAILURE"
        )
    else:
        assert "files" not in result.data["inventory_reason_codes"]


@pytest.mark.contract
async def test_bounded_complete_empty_collections_through_mcp(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient, Collection
    from canvas_bridge.policy import Endpoint

    course = bridge.selected(owner, seeded)[1][0]
    original = CanvasClient.collection

    async def empty(client, endpoint, **kwargs):
        if endpoint in {
            Endpoint.PAGES,
            Endpoint.FILES,
            Endpoint.MODULES,
            Endpoint.ASSIGNMENTS,
            Endpoint.FOLDERS,
        }:
            return Collection(complete=True, pages=1)
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", empty)
    async with client_session(running, token_factory(scope="academic:read")) as client:
        response = await client.call_tool(
            "list_course_files", {"connection_id": seeded, "course_id": course.id}
        )
    result = response.structuredContent
    assert result["status"] == "ok" and result["data"]["files"] == []
    progress = result["data"]["inventory_progress"]
    assert progress["collections"] == dict.fromkeys(
        ("pages", "files", "modules", "assignments", "folders"), "complete_empty"
    )
    assert progress["branches_completed"] == progress["branches_attempted"] == 5
    assert not progress["count_is_lower_bound"]


def paginated_provider(bridge, monkeypatch):
    original = bridge.synthetic.handle

    def handle(request):
        response = original(request)
        if request.url.path.endswith("/assignments"):
            return response  # The provider already paginates assignments.
        if response.status_code != 200:
            return response
        rows = response.json()
        if not isinstance(rows, list):
            return response
        page = int(request.url.params.get("page", 1))
        # Two records per page deliberately exercises every branch continuation.
        start = (page - 1) * 2
        headers = (
            {"Link": f'<{request.url.copy_set_param("page", page + 1)}>; rel="next"'}
            if start + 2 < len(rows)
            else {}
        )
        return httpx.Response(200, json=rows[start : start + 2], headers=headers)

    monkeypatch.setattr(bridge.synthetic, "handle", handle)


@pytest.mark.contract
async def test_public_inventory_preserves_unknown_visibility_gap_without_file_metadata(
    running, bridge, owner, seeded, token_factory
):
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["files"] = {
        "11": [file_record(id=51, hidden_for_user=None, display_name="UNKNOWN PRIVATE FIXTURE")]
    }
    async with client_session(running, token_factory(scope="academic:read")) as client:
        response = await client.call_tool(
            "list_course_files",
            {"connection_id": seeded, "course_id": course.id, "inventory_mode": "resumable"},
        )
    result = response.structuredContent
    assert result["status"] == "partial_data"
    assert result["data"]["files"] == []
    progress = result["data"]["inventory_progress"]
    assert progress["collections"]["files"] == "partial"
    assert progress["collections"]["pages"] == "unsupported"
    branch_id = result["data"]["inventory_reason_codes"]["files"]["request_id"]
    assert branch_id == result["meta"]["request_id"]
    from canvas_bridge.failure_events import journal, lookup

    assert any(
        event["code"] == "UNKNOWN_AUTHORIZATION_FAILURE"
        for event in lookup(journal(bridge.settings), branch_id)
    )
    assert progress["branches_attempted"] == 1
    assert progress["distinct_verified_files"] == 0
    assert progress["count_is_lower_bound"]
    assert result["data"]["coverage"]["files"] == "partial"
    assert (
        result["data"]["inventory_reason_codes"]["files"]["reason_code"]
        == "UNKNOWN_AUTHORIZATION_FAILURE"
    )
    assert "UNKNOWN PRIVATE FIXTURE" not in response.model_dump_json()


async def test_resumable_inventory_follows_all_branches_without_filename_dedup(
    bridge, owner, seeded, monkeypatch
):
    _, courses = bridge.selected(owner, seeded)
    course = courses[0]
    bridge.synthetic.data["files"] = {"11": [file_record(id=i, folder_id=3) for i in range(51, 56)]}
    bridge.synthetic.data["folders"] = {
        "11": [
            {
                "id": i,
                "parent_folder_id": i - 1 if i > 1 else None,
                "context_type": "Course",
                "context_id": 11,
            }
            for i in (1, 2, 3)
        ]
    }
    bridge.synthetic.data["module_items"] = {
        "11": [
            {"type": "File", "content_id": 51},
            {"type": "File", "content_id": 52},
            {"type": "File", "content_id": 53},
        ]
    }
    bridge.synthetic.data["assignments"]["11"] = [
        {"id": i, "description": '<a href="/courses/11/files/55">Fictional</a>'}
        for i in range(71, 74)
    ]
    paginated_provider(bridge, monkeypatch)
    pages = await crawl(bridge, owner, seeded, course.id)
    assert pages[-1].status == "ok"
    progress = pages[-1].data["inventory_progress"]
    assert progress["distinct_verified_files"] == 5
    assert progress["branches_completed"] == 4
    assert not progress["count_is_lower_bound"]
    assert set(pages[-1].data["coverage"].values()) == {"complete"}
    files = [item for page in pages for item in page.data["files"]]
    assert {item["canvas_file_id"] for item in files} == {str(i) for i in range(51, 56)}
    assert len({item["filename"] for item in files}) == 1
    assert {a for f in files for a in f["assignments"]} == {
        canonical_id(owner, seeded, "assignment", f"11:{i}") for i in range(71, 74)
    }
    assert sum(page.data["inventory_operation"] == "folders" for page in pages) == 2
    assert sum(page.data["inventory_operation"] == "assignments" for page in pages) == 2
    assert not any("download" in request.url.path for request in bridge.synthetic.requests)
    with bridge.store.transaction() as session:
        states = session.scalars(select(LocalRecord).where(LocalRecord.kind == KIND)).all()
        assert states and all("description" not in str(row.payload) for row in states)


async def test_cursor_replay_is_immutable_and_cannot_cross_course_or_owner(bridge, owner, seeded):
    conn, courses = bridge.selected(owner, seeded)
    first = await list_files(bridge, owner, seeded, courses[0].id, inventory_mode="resumable")
    cursor = first.meta.next_cursor
    before = load(bridge, owner, seeded, binding(conn, courses[0]), cursor)
    await list_files(bridge, owner, seeded, courses[0].id, cursor=cursor)
    assert load(bridge, owner, seeded, binding(conn, courses[0]), cursor) == before
    with pytest.raises(DomainError) as changed:
        await list_files(bridge, owner, seeded, courses[1].id, cursor=cursor)
    assert changed.value.reason_code == "INVENTORY_SCOPE_CHANGED"
    with pytest.raises(DomainError):
        load(bridge, "other-owner", seeded, binding(conn, courses[0]), cursor)
    bridge.select_courses(owner, seeded, [courses[1].id], "UTC")
    with pytest.raises(DomainError):
        await list_files(bridge, owner, seeded, courses[0].id, cursor=cursor)


async def test_cursor_lease_renewal_and_expiry_are_distinct(bridge, owner, seeded, monkeypatch):
    from datetime import timedelta

    import canvas_bridge.inventory_cursor as cursors
    from canvas_bridge.domain import utcnow

    conn, courses = bridge.selected(owner, seeded)
    first = await list_files(bridge, owner, seeded, courses[0].id, inventory_mode="resumable")
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, seeded).entitlement_at = None
    resumed = await list_files(bridge, owner, seeded, courses[0].id, cursor=first.meta.next_cursor)
    assert resumed.data["inventory_operation"] == "folders"
    future = utcnow() + timedelta(days=2)
    monkeypatch.setattr(cursors, "utcnow", lambda: future)
    with pytest.raises(DomainError) as expired:
        load(bridge, owner, seeded, binding(conn, courses[0]), resumed.meta.next_cursor)
    assert expired.value.reason_code == "INVENTORY_CURSOR_INVALID"
    assert expired.value.status == "needs_input"


async def test_transient_page_failure_keeps_the_same_unfinished_operation(
    bridge, owner, seeded, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient

    conn, courses = bridge.selected(owner, seeded)
    original = CanvasClient.inventory_page

    async def throttle(*args, **kwargs):
        raise DomainError(
            "retry_later",
            "Synthetic throttle",
            reason_code="UPSTREAM_THROTTLED",
            details={"retry_after_seconds": 120},
        )

    monkeypatch.setattr(CanvasClient, "inventory_page", throttle)
    result = await list_files(bridge, owner, seeded, courses[0].id, inventory_mode="resumable")
    assert result.status == "retry_later" and result.data["retry_after_seconds"] == 120
    pending = load(bridge, owner, seeded, binding(conn, courses[0]), result.meta.next_cursor)
    assert pending["queue"][0]["kind"] == "files"
    monkeypatch.setattr(CanvasClient, "inventory_page", original)
    resumed = await list_files(bridge, owner, seeded, courses[0].id, cursor=result.meta.next_cursor)
    assert resumed.data["inventory_operation"] == "files"


@pytest.mark.contract
async def test_mcp_failed_page_preserves_only_reviewed_cause_and_resume_cursor(
    running, bridge, owner, seeded, token_factory, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient

    course = bridge.selected(owner, seeded)[1][0]

    async def busy(*args, **kwargs):
        raise DomainError(
            "retry_later",
            "PRIVATE fixture message",
            reason_code="UPSTREAM_THROTTLED",
            details={
                "blocking_scope": "cooldown",
                "retry_after_seconds": 17,
                "title": "PRIVATE fixture detail",
            },
        )

    monkeypatch.setattr(CanvasClient, "inventory_page", busy)
    async with client_session(running, token_factory(scope="academic:read")) as client:
        response = await client.call_tool(
            "list_course_files",
            {
                "connection_id": seeded,
                "course_id": course.id,
                "inventory_mode": "resumable",
            },
        )
    data = response.structuredContent
    assert data["meta"]["next_cursor"] and data["data"]["files"] == []
    diag = data["data"]["diagnostic"]
    assert diag["code"] == "UPSTREAM_THROTTLED" and diag["retry_after_seconds"] == 17
    assert (
        diag["blocking_scope"] == "cooldown" and diag["requested_content_policy"] == "not_evaluated"
    )
    assert "PRIVATE" not in response.model_dump_json()


async def test_missing_branch_stays_partial_and_other_sources_continue(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    bridge.synthetic.data["assignments"]["11"] = [
        {"id": 71, "description": '<a href="/courses/11/files/51">Fictional</a>' * 21}
    ]
    pages = await crawl(bridge, owner, seeded, courses[0].id)
    assert pages[-1].status == "partial_data"
    assert pages[-1].data["coverage"]["files"] == "partial"
    assert pages[-1].data["coverage"]["assignments"] == "complete"
    assert any(f["canvas_file_id"] == "51" for p in pages for f in p.data["files"])


async def test_denied_link_is_a_reference_not_permission_and_can_be_audited(bridge, owner, seeded):
    from canvas_bridge.course_files import read_file

    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["assignments"]["11"] = [
        {"id": 71, "description": '<a href="/courses/11/files/999">Fictional</a>'}
    ]
    bridge.synthetic.failures["/api/v1/courses/11/files/999"] = 403
    pages = await crawl(bridge, owner, seeded, courses[0].id)
    references = [f for p in pages for f in p.data["files"] if f["canvas_file_id"] == "999"]
    assert (
        len(references) == 1 and references[0]["access_state"] == "reference_only_access_unverified"
    )
    assert pages[-1].data["coverage"]["assignments"] == "partial"
    with pytest.raises(DomainError) as error:
        await read_file(bridge, owner, seeded, references[0]["file_id"])
    assert error.value.reason_code == "RESOURCE_PERMISSION_DENIED"


async def test_assignment_source_restriction_survives_inventory_provenance(bridge, owner, seeded):
    from canvas_bridge.egress_models import ContentClassification as CC
    from canvas_bridge.egress_sources import resolve_sources

    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    bridge.synthetic.data["assignments"]["11"] = [
        {"id": 71, "description": '<a href="/courses/11/files/51">Fictional</a>'}
    ]
    assignment = canonical_id(owner, seeded, "assignment", "11:71")
    bridge.synthetic.egress_contexts = {assignment: {"classification": CC.RESTRICTED_ASSESSMENT}}
    pages = await crawl(bridge, owner, seeded, courses[0].id)
    linked = next(p for p in pages if any(f["assignments"] for f in p.data["files"]))
    sources, _ = resolve_sources(
        bridge.egress,
        owner,
        {"connection_id": seeded, "course_id": courses[0].id},
        linked,
        "list_course_files",
    )
    assert any(
        s.source_id == assignment and s.classification == CC.RESTRICTED_ASSESSMENT for s in sources
    )


@pytest.mark.contract
async def test_public_mcp_exposes_and_follows_owner_bound_inventory_cursor(
    running, bridge, owner, seeded, token_factory
):
    _, courses = bridge.selected(owner, seeded)
    async with client_session(
        running, token_factory(scope="academic:read"), read_timeout=30
    ) as client:
        catalog = await client.list_tools()
        schema = next(t.inputSchema for t in catalog.tools if t.name == "list_course_files")
        assert {"cursor", "inventory_mode"} <= schema["properties"].keys()
        cursor, operations = None, []
        for _ in range(30):
            result = (
                await client.call_tool(
                    "list_course_files",
                    {
                        "connection_id": seeded,
                        "course_id": courses[0].id,
                        "inventory_mode": "resumable",
                        "cursor": cursor,
                    },
                )
            ).structuredContent
            assert result["status"] in {"ok", "partial_data"}, result
            operations.append(result["data"]["inventory_operation"])
            cursor = result["meta"]["next_cursor"]
            if not cursor:
                break
        else:
            pytest.fail("Public inventory did not terminate")
        assert set(operations) >= {"files", "folders", "modules", "assignments", "module_items"}


@pytest.mark.contract
async def test_public_inventory_cannot_release_restricted_assignment_provenance(
    running, bridge, owner, seeded, token_factory
):
    from canvas_bridge.egress_models import ContentClassification as CC

    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    bridge.synthetic.data["assignments"]["11"] = [
        {
            "id": 71,
            "description": 'RESTRICTED ASSIGNMENT BODY <a href="/courses/11/files/51">Handout</a>',
        }
    ]
    assignment = canonical_id(owner, seeded, "assignment", "11:71")
    bridge.synthetic.egress_contexts = {assignment: {"classification": CC.RESTRICTED_ASSESSMENT}}
    async with client_session(
        running, token_factory(scope="academic:read"), read_timeout=30
    ) as client:
        cursor = None
        for _ in range(20):
            response = await client.call_tool(
                "list_course_files",
                {
                    "connection_id": seeded,
                    "course_id": courses[0].id,
                    "inventory_mode": "resumable",
                    "cursor": cursor,
                },
            )
            result = response.structuredContent
            assert "RESTRICTED ASSIGNMENT BODY" not in response.model_dump_json()
            if result["status"] == "permission_denied":
                assert result["data"]["reason_code"] == "EGRESS_RESTRICTED_CONTENT"
                assert not result["data"].get("files")
                break
            cursor = result["meta"]["next_cursor"]
            assert cursor, "Restricted assignment provenance escaped the public gate"
        else:
            pytest.fail("Restricted source was not denied")


async def test_wide_inventory_suffix_is_distinct_and_rechecks_visibility(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0]
    rows = [file_record(id=i, display_name="多" * 900) for i in range(1, 101)]
    bridge.synthetic.data["files"] = {"11": rows}
    args = (bridge, owner, seeded, course.id)
    first = await list_files(*args, inventory_mode="resumable")
    prefix = [item["canvas_file_id"] for item in first.data["files"]]
    assert 0 < len(prefix) < 99
    rows[-1]["hidden_for_user"] = True
    second = await list_files(*args, inventory_mode="resumable", cursor=first.meta.next_cursor)
    suffix = [item["canvas_file_id"] for item in second.data["files"]]
    assert prefix + suffix == [str(i) for i in range(1, 100)]
    assert first.data["page_identity"] != second.data["page_identity"]
    assert first.data["coverage"]["files"] == "not_refreshed"
    assert second.data["coverage"]["files"] == "complete"
