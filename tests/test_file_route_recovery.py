"""Synthetic endpoint permissions, independent file rechecks and the public MCP envelope."""

import httpx
import pytest

from canvas_bridge.authorization import SCOPES
from canvas_bridge.canvas import InventoryCapabilities, upstream_error
from canvas_bridge.course_files import list_files, read_file
from canvas_bridge.domain import DomainError
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.policy import Endpoint
from tests.test_course_files import file_record
from tests.test_file_reading import readable as readable
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


def locations(bridge):
    return [req.url.path for req in bridge.synthetic.requests]


def test_only_explicit_bearer_scope_failure_is_classified():
    for challenge, expected in [
        ('Bearer error="insufficient_scope"', "UPSTREAM_SCOPE_INSUFFICIENT"),
        ('Bearer error_description="insufficient_scope"', "RESOURCE_PERMISSION_DENIED"),
        ('Basic error="insufficient_scope"', "RESOURCE_PERMISSION_DENIED"),
        (
            'Bearer realm="fixture", Basic realm="fixture", error="insufficient_scope"',
            "RESOURCE_PERMISSION_DENIED",
        ),
        ("", "RESOURCE_PERMISSION_DENIED"),
    ]:
        err = upstream_error(403, httpx.Headers({"WWW-Authenticate": challenge}))
        assert (err.reason_code, err.upstream_http_status) == (expected, 403)
        assert err.status == "permission_denied"
    assert (
        upstream_error(
            401, httpx.Headers({"WWW-Authenticate": 'Bearer error="invalid_token"'})
        ).reason_code
        == "UPSTREAM_CREDENTIAL_REJECTED"
    )
    assert upstream_error(429, {}).reason_code == "UPSTREAM_THROTTLED"
    assert upstream_error(503, {}).reason_code == "UPSTREAM_UNAVAILABLE"


async def test_recent_route_denial_is_bounded_and_does_not_grant_file_access(
    bridge, owner, seeded, readable
):
    course, file = readable
    clock = [0.0]
    bridge.inventory_capabilities = InventoryCapabilities(lambda: clock[0])
    path = "/api/v1/courses/11/files"
    bridge.synthetic.failures[path] = 403
    before = locations(bridge).count(path)
    first = await list_files(bridge, owner, seeded, course.id)
    second = await list_files(bridge, owner, seeded, course.id)
    assert locations(bridge).count(path) == before + 1
    assert first.data["files"][0]["file_id"] == file
    denial = next(
        x
        for x in second.data["inventory_recovery"]["failed_methods"]
        if x["inventory_operation"] == "files"
    )
    assert (
        denial["capability_observation"] == "recent_denial"
        and denial["upstream_http_status"] == 403
    )
    assert denial["origin"] == "canvas_api"
    bridge.synthetic.failures[path + "/51"] = 403
    with pytest.raises(DomainError) as err:
        await read_file(bridge, owner, seeded, file)
    assert err.value.upstream_http_status == 403
    assert not any("/download" in x for x in locations(bridge))
    del bridge.synthetic.failures[path]
    clock[0] = 21
    assert (await list_files(bridge, owner, seeded, course.id)).data["coverage"][
        "files"
    ] == "complete"


async def test_folder_only_file_uses_scoped_metadata_and_unpublished_file_stays_hidden(
    bridge, owner, seeded
):
    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["files"] = {
        "11": [file_record(id=51, folder_id=3), file_record(id=52, folder_id=3, published=False)]
    }
    bridge.synthetic.data["folders"] = {
        "11": [{"id": 3, "context_type": "Course", "context_id": 11}]
    }
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    result = await list_files(bridge, owner, seeded, courses[0].id)
    assert [row["canvas_file_id"] for row in result.data["files"]] == ["51"]
    assert result.data["files"][0]["reference_origin"] == "folder_file_metadata"
    assert result.status == "partial_data"
    assert "/api/v1/courses/11/folders/3" in locations(bridge)
    assert "/api/v1/folders/3/files" in locations(bridge)
    assert "/api/v1/courses/11/files/51" in locations(bridge)
    assert "/api/v1/courses/11/files/52" not in locations(bridge)


@pytest.mark.contract
async def test_known_name_recovers_after_collection_denials_and_obeys_egress(
    running, bridge, owner, seeded, readable, token_factory
):
    course, file = readable
    # Establish the ordinary owned reference. Remove other discovery paths.
    row = bridge.synthetic.data["files"]["11"][0]
    row.update(filename="Bundle 3, Paper 3.pdf", display_name="Bundle 3, Paper 3.pdf")
    await list_files(bridge, owner, seeded, course.id)
    root = "/api/v1/courses/11/"
    bridge.synthetic.failures.update(
        {root + op: 403 for op in ("files", "folders", "modules", "assignments")}
    )
    args = {"connection_id": seeded, "course_id": course.id, "filename": "Bundle 3 Paper 3"}
    async with client_session(running, token_factory()) as client:
        answer = (await client.call_tool("list_course_files", args)).structuredContent
        assert answer["status"] == "partial_data" and answer["data"]["files"][0]["file_id"] == file
        report = answer["data"]["inventory_recovery"]
        assert report["request_id"] == answer["meta"]["request_id"]
        assert report["course_id"] == course.id and report["document_content_included"] is False
        assert {x["inventory_operation"] for x in report["failed_methods"]} >= {"files", "folders"}
        assert report["verified_file_references"] == 1 and "file" in report["attempted_methods"]
        bridge.synthetic.egress_contexts = {file: {"classification": CC.RESTRICTED_ASSESSMENT}}
        denied = (await client.call_tool("list_course_files", args)).structuredContent
        assert denied["status"] == "permission_denied" and "files" not in denied["data"]


@pytest.mark.contract
async def test_configured_list_scope_is_not_required_for_independent_file_lookup(
    running, bridge, seeded, readable, token_factory
):
    course, file = readable
    institution = bridge.registry.entries["synthetic"]
    institution.scopes = sorted(set(SCOPES.values()) - {SCOPES[Endpoint.FILES]})
    before = locations(bridge).count("/api/v1/courses/11/files")
    async with client_session(running, token_factory()) as client:
        answer = (
            await client.call_tool(
                "list_course_files", {"connection_id": seeded, "course_id": course.id}
            )
        ).structuredContent
    assert answer["status"] == "partial_data"
    assert locations(bridge).count("/api/v1/courses/11/files") == before
    assert file in {row["file_id"] for row in answer["data"]["files"]}
    async with client_session(running, token_factory()) as client:
        opened = (
            await client.call_tool(
                "read_course_file", {"connection_id": seeded, "file_id": file, "length": 40}
            )
        ).structuredContent
    assert opened["status"] == "ok" and opened["data"]["text"]
    denied = next(
        x
        for x in answer["data"]["inventory_recovery"]["failed_methods"]
        if x["inventory_operation"] == "files"
    )
    assert denied["origin"] == "bridge" and "upstream_http_status" not in denied
    assert denied["reason_code"] == "MISSING_RESOURCE_CAPABILITY"
    assert denied["retrieval_constraint"] == "configured_endpoint_scope"


async def test_attachment_ids_verified_independently_without_submission_expansion(
    bridge, owner, seeded
):
    _, courses = bridge.selected(owner, seeded)
    root = "/api/v1/courses/11/"
    bridge.synthetic.failures.update(
        {root + "files": 403, root + "folders": 403, root + "modules": 403, root + "files/52": 403}
    )
    bridge.synthetic.data["files"] = {"11": [file_record(id=51), file_record(id=52)]}
    bridge.synthetic.data["assignments"]["11"] = [
        {"id": 71, "attachments": [{"id": 51}, {"id": 52}]}
    ]
    result = await list_files(bridge, owner, seeded, courses[0].id)
    assert [row["canvas_file_id"] for row in result.data["files"]] == ["51"]
    assert result.data["files"][0]["assignments"]
    assert not any(
        "submission" in str(req.url.query)
        for req in bridge.synthetic.requests
        if req.url.path == root + "assignments"
    )
    failure = next(
        x
        for x in result.data["inventory_recovery"]["failed_methods"]
        if x["inventory_operation"] == "file"
    )
    assert failure["upstream_http_status"] == 403


@pytest.mark.parametrize("blocked", ["all", "rate"])
async def test_empty_inventory_remains_partial_after_denials_or_throttling(
    bridge, owner, seeded, blocked
):
    course = bridge.selected(owner, seeded)[1][0]
    root = "/api/v1/courses/11/"
    if blocked == "all":
        for method in ("files", "folders", "modules", "assignments", "pages"):
            bridge.synthetic.failures[root + method] = 403
    else:
        original = bridge.synthetic.handle

        def throttled(request):
            if request.url.path == root + "files":
                return httpx.Response(429, headers={"Retry-After": "120"})
            return original(request)

        bridge.synthetic.handle = throttled
    result = await list_files(bridge, owner, seeded, course.id)
    report = result.data["inventory_recovery"]
    assert result.status == "partial_data" and result.data["files"] == []
    assert report["verified_file_references"] == 0 and report["completeness"] == "partial"
    if blocked == "all":
        assert {x["inventory_operation"] for x in report["failed_methods"]} == {
            "files",
            "folders",
            "modules",
            "assignments",
            "pages",
        }
        assert all(x["upstream_http_status"] == 403 for x in report["failed_methods"])
    else:
        assert report["attempted_methods"] == ["files"]
        assert report["failed_methods"][0]["reason_code"] == "UPSTREAM_THROTTLED"


async def test_known_attachment_restriction_survives_loss_of_assignment_route(
    bridge, owner, seeded
):
    course = bridge.selected(owner, seeded)[1][0]
    root = "/api/v1/courses/11/"
    bridge.synthetic.failures[root + "files"] = 403
    bridge.synthetic.data["files"] = {
        "11": [file_record(id=51, filename="Named.pdf", display_name="Named.pdf")]
    }
    bridge.synthetic.data["assignments"]["11"] = [{"id": 71, "attachments": [{"id": 51}]}]
    first = await list_files(bridge, owner, seeded, course.id)
    parent = first.data["files"][0]["assignments"][0]
    bridge.synthetic.egress_contexts = {parent: {"classification": CC.RESTRICTED_ASSESSMENT}}
    bridge.synthetic.failures[root + "assignments"] = 403
    result = await list_files(bridge, owner, seeded, course.id, filename="Named")
    assert result.data["files"][0]["reference_origin"] == "known_file_metadata"
    with pytest.raises(DomainError) as denied:
        bridge.egress.release(
            result,
            owner,
            {"connection_id": seeded, "course_id": course.id},
            tool_name="list_course_files",
        )
    assert denied.value.reason_code == "EGRESS_RESTRICTED_CONTENT"


async def test_recovery_budget_bounds_module_fanout(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0]
    root = "/api/v1/courses/11/"
    bridge.synthetic.failures[root + "files"] = 403
    bridge.synthetic.data["files"] = {"11": [file_record(id=i) for i in range(101, 181)]}
    bridge.synthetic.data["module_items"] = {
        "11": [{"type": "File", "content_id": i, "title": "Fixture"} for i in range(101, 181)]
    }
    result = await list_files(bridge, owner, seeded, course.id)
    reqs = locations(bridge)
    index = reqs.index(root + "files")
    assert len(reqs[index + 1 :]) <= 24
    assert result.status == "partial_data"


@pytest.mark.contract
async def test_file_403_never_uses_another_download_route(
    running, bridge, seeded, readable, token_factory
):
    _, file = readable
    bridge.synthetic.failures["/api/v1/courses/11/files/51"] = 403
    async with client_session(running, token_factory()) as client:
        response = await client.call_tool(
            "read_course_file", {"connection_id": seeded, "file_id": file}
        )
    payload = response.structuredContent
    diagnostic = payload["data"]["diagnostic"]
    assert diagnostic["origin"] == "canvas_api" and diagnostic["upstream_http_status"] == 403
    assert diagnostic["retrieval_method"] == "file" and "file" in diagnostic["attempted_methods"]
    assert diagnostic["source_bytes_obtained"] is False and diagnostic["content_delivery"] == "none"
    assert diagnostic["request_id"] == payload["meta"]["request_id"]
    assert not any("/download" in path for path in locations(bridge))


async def test_repeated_folder_metadata_denial_uses_short_lived_observation(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0]
    folder = {"id": 3, "context_type": "Course", "context_id": 11}
    bridge.synthetic.data["folders"] = {"11": [folder, dict(folder)]}
    bridge.synthetic.failures.update(
        {"/api/v1/courses/11/files": 403, "/api/v1/courses/11/folders/3": 403}
    )
    for _ in range(2):
        result = await list_files(bridge, owner, seeded, course.id)
    assert locations(bridge).count("/api/v1/courses/11/folders/3") == 1
    assert "/api/v1/folders/3/files" not in locations(bridge)
    report = result.data["inventory_recovery"]
    denial = next(
        x for x in report["failed_methods"] if x["inventory_operation"] == "folder_metadata"
    )
    assert (
        denial["capability_observation"] == "recent_denial"
        and "folder_files" not in report["attempted_methods"]
    )


@pytest.mark.contract
async def test_unpublished_metadata_has_distinct_remedy(
    running, bridge, seeded, readable, token_factory
):
    _, file = readable
    bridge.synthetic.data["files"]["11"][0]["published"] = False
    async with client_session(running, token_factory()) as client:
        response = await client.call_tool(
            "read_course_file", {"connection_id": seeded, "file_id": file}
        )
    diag = response.structuredContent["data"]["diagnostic"]
    assert (
        diag["retrieval_constraint"] == "file_unpublished" and diag["origin"] == "canvas_metadata"
    )
    assert diag["next_action"] == "check_file_publication" and "upstream_http_status" not in diag
    assert diag["content_delivery"] == "none"


async def test_name_match_after_first_hundred_rows_precedes_display_limit(bridge, owner, seeded):
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(id=i, filename=f"Doc-{i}.pdf", display_name=f"Doc-{i}.pdf")
            for i in range(1, 121)
        ]
    }
    result = await list_files(bridge, owner, seeded, course.id, filename="Doc 120")
    assert [r["canvas_file_id"] for r in result.data["files"]] == ["120"]
    assert result.status == "partial_data" and result.data["coverage"]["files"] == "partial"


async def test_incomplete_list_visibility_requires_independent_object_evidence(
    bridge, owner, seeded, readable, monkeypatch
):
    course, ref = readable
    path = "/api/v1/courses/11/files"
    orig = bridge.synthetic.handle

    def handle(req):
        if req.url.path == path:
            return httpx.Response(
                200, json=[file_record(id=51, hidden_for_user=None, display_name="UNVERIFIED-ROW")]
            )
        return orig(req)

    monkeypatch.setattr(bridge.synthetic, "handle", handle)
    result = await list_files(bridge, owner, seeded, course.id)
    assert result.status == "partial_data"
    assert result.data["files"][0]["file_id"] == ref
    assert result.data["files"][0]["access_verification"] == "course_file_metadata"
    assert "UNVERIFIED-ROW" not in result.model_dump_json()
    assert path + "/51" in locations(bridge)
