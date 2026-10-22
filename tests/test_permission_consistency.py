"""Synthetic permission diagnostics, isolation and exact-ID incident regression."""

import json
from datetime import timedelta

import httpx
import pytest

from canvas_bridge.authorization import (
    SCOPES,
    RequestAuthorization,
    request_authorization,
    validate_request_authorization,
)
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.course_files import list_files, read_file, search_files
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.permission_audit import audit_permissions
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Base, Connection, Course
from tests.conftest import seed
from tests.test_course_files import file_record


def course(bridge, owner, ref):
    return bridge.selected(owner, ref)[1][0]


def stored_state(bridge):
    with bridge.store.engine.connect() as connection:
        return {
            t.name: [tuple(row) for row in connection.execute(t.select())]
            for t in Base.metadata.sorted_tables
        }


async def test_selected_authorized_default_is_read_only_and_never_calls_upstream(
    bridge, owner, seeded
):
    before, requests = stored_state(bridge), len(bridge.synthetic.requests)
    result = await audit_permissions(bridge, owner, seeded)
    assert result.status == "ok"
    assert result.data["scope_consistency"] == "consistent"
    assert len(result.data["checks"]) == 14
    assert all(c["scope_authorized"] and c["connection_owned"] for c in result.data["checks"])
    assert all(c["upstream_permission"] == "not_checked" for c in result.data["checks"])
    assert all(c["reason_code"] == "AUTHORIZED_LOCAL_SCOPE" for c in result.data["checks"])
    assert stored_state(bridge) == before
    assert len(bridge.synthetic.requests) == requests
    assert not result.sources


async def test_oct21_truncated_id_denied_exact_advertised_id_succeeds(bridge, owner, seeded):
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    advertised = bridge.connection_status(owner).data["connections"][0]
    target = advertised["selected_courses"][0]["id"]
    truncated = target[:-1]  # 39-character synthetic reproduction; never real coursework/IDs.
    assert len(target) == 40
    with pytest.raises(DomainError) as error:
        await list_files(bridge, owner, seeded, truncated)
    assert error.value.status == "permission_denied"
    assert error.value.reason_code == "IDENTIFIER_MAPPING_FAILURE"
    report = await audit_permissions(bridge, owner, seeded, truncated, ["files"])
    assert report.status == "permission_denied"
    assert report.data["checks"][0]["identifier_state"] == "invalid_format"
    assert report.data["checks"][0]["course_id"] is None
    assert target not in report.model_dump_json()  # No guessed correction disclosed.
    after = await list_files(bridge, owner, seeded, target)
    assert after.status == "ok" and len(after.data["files"]) == 1
    exact = await audit_permissions(bridge, owner, seeded, target, ["files"], True)
    assert exact.status == "ok"
    assert exact.data["checks"][0]["upstream_permission"] == "allowed"
    assert exact.data["correlation_id"] == advertised["correlation_id"]


@pytest.mark.parametrize(
    "status,reason,permission,classification",
    [
        (403, "RESOURCE_PERMISSION_DENIED", "denied", "consistent"),
        (404, "RESOURCE_UNAVAILABLE", "unknown", "indeterminate"),
        (401, "UNKNOWN_AUTHORIZATION_FAILURE", "unknown", "indeterminate"),
        (429, "UPSTREAM_UNAVAILABLE", "unknown", "indeterminate"),
        (503, "UPSTREAM_UNAVAILABLE", "unknown", "indeterminate"),
        (302, "UPSTREAM_UNAVAILABLE", "unknown", "indeterminate"),
    ],
)
async def test_restricted_or_unavailable_resource_is_not_a_course_scope_denial(
    bridge, owner, seeded, status, reason, permission, classification
):
    target = course(bridge, owner, seeded)
    bridge.synthetic.failures[f"/api/v1/courses/{target.source_id}/files"] = status
    before = stored_state(bridge)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    check = result.data["checks"][0]
    assert result.status == "partial_data"
    assert check["scope_authorized"] and check["advertised_selected"]
    assert check["upstream_permission"] == permission
    assert check["reason_code"] == reason and check["result"] == classification
    assert check["upstream_http_status"] == status
    assert stored_state(bridge) == before
    assert not result.sources and "files" not in result.data


async def test_transport_failure_stays_unknown(bridge, owner, seeded, monkeypatch):
    target = course(bridge, owner, seeded)

    def fail(request):
        raise httpx.ConnectError("synthetic secret must not escape", request=request)

    monkeypatch.setattr(bridge.synthetic, "handle", fail)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    check = result.data["checks"][0]
    assert check["reason_code"] == "UPSTREAM_UNAVAILABLE"
    assert check["upstream_permission"] == "unknown"
    assert check["upstream_http_status"] is None
    assert "synthetic secret" not in result.model_dump_json()


async def test_unselected_course_uses_shared_deny_without_upstream_calls(bridge, owner, seeded):
    target = course(bridge, owner, seeded)
    bridge.select_courses(owner, seeded, [], "UTC")
    count = len(bridge.synthetic.requests)
    report = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    assert report.status == "permission_denied"
    check = report.data["checks"][0]
    assert not check["advertised_selected"] and not check["scope_authorized"]
    assert check["reason_code"] == "COURSE_NOT_SELECTED"
    with pytest.raises(DomainError) as error:
        bridge.selected(owner, seeded, [target.id])
    assert error.value.reason_code == check["reason_code"]
    assert len(bridge.synthetic.requests) == count


async def test_cross_owner_and_cross_connection_are_non_disclosing(bridge, owner, seeded):
    target = course(bridge, owner, seeded)
    other = await seed(bridge, "other-owner", "other-connection")
    other_target = course(bridge, "other-owner", other)
    sibling = await seed(bridge, owner, "same-owner-other-connection")
    for ref in (other, "nonexistent-connection"):
        with pytest.raises(DomainError) as error:
            await audit_permissions(bridge, owner, ref, other_target.id, ["files"], True)
        assert error.value.reason_code == "CONNECTION_OWNERSHIP_MISMATCH"
        assert error.value.status == "permission_denied"
    outputs = []
    for bad_ref in (other_target.id, "0" * 40):
        result = await audit_permissions(bridge, owner, seeded, bad_ref, ["files"], True)
        assert result.status == "permission_denied"
        outputs.append(result.data["checks"])
    assert outputs[0] == outputs[1]
    result = await audit_permissions(bridge, owner, sibling, target.id, ["files"])
    assert result.data["checks"][0]["reason_code"] == "IDENTIFIER_CONNECTION_MISMATCH"
    assert target.id not in result.model_dump_json() and target.name not in result.model_dump_json()


@pytest.mark.parametrize(
    "mutation,reason,classification,status",
    [
        ("access", "SELECTED_SCOPE_MISMATCH", "inconsistent", "partial_data"),
        ("lease", "STALE_SCOPE_SNAPSHOT", "indeterminate", "partial_data"),
        ("mapping", "IDENTIFIER_MAPPING_FAILURE", "inconsistent", "permission_denied"),
        ("expired", "UPSTREAM_AUTH_EXPIRED", "indeterminate", "reconnect_required"),
        ("inactive", "CONNECTION_INACTIVE", "consistent", "reconnect_required"),
    ],
)
async def test_local_snapshot_anomalies_never_repair_or_probe(
    bridge, owner, seeded, mutation, reason, classification, status
):
    target = course(bridge, owner, seeded)
    with bridge.store.transaction() as session:
        conn, row = session.get(Connection, seeded), session.get(Course, target.id)
        if mutation == "access":
            row.accessible = False
        elif mutation == "lease":
            conn.entitlement_at = utcnow() - timedelta(hours=1)
        elif mutation == "mapping":
            row.source_id = "999"
        elif mutation == "expired":
            conn.token_expires_at = utcnow() - timedelta(seconds=1)
        else:
            conn.state = "disabled"
    before, count = stored_state(bridge), len(bridge.synthetic.requests)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    check = result.data["checks"][0]
    assert result.status == status
    assert check["reason_code"] == reason and check["result"] == classification
    assert check["upstream_permission"] == "not_checked"
    assert bridge.authorize(owner, seeded, target.id, "files").reason_code == reason
    assert stored_state(bridge) == before and len(bridge.synthetic.requests) == count


async def test_expired_upstream_challenge_does_not_refresh_or_write(
    bridge, owner, seeded, monkeypatch
):
    target = course(bridge, owner, seeded)
    monkeypatch.setattr(
        bridge.synthetic,
        "handle",
        lambda request: httpx.Response(
            401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ),
    )
    before = stored_state(bridge)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files", "modules"], True)
    assert result.status == "reconnect_required"
    assert result.data["upstream_requests"] == 1
    assert result.data["checks"][1]["result"] == "not_checked"
    assert result.data["checks"][0]["reason_code"] == "UPSTREAM_AUTH_EXPIRED"
    assert result.data["credential_state"] == "expired_or_rejected"
    assert stored_state(bridge) == before


async def test_near_expiry_diagnostic_does_not_refresh(bridge, owner, seeded, monkeypatch):
    target = course(bridge, owner, seeded)
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).token_expires_at = utcnow() + timedelta(seconds=40)

    async def forbidden(*args):
        pytest.fail("Audit must not refresh credentials")

    monkeypatch.setattr("canvas_bridge.linking.refresh_credential", forbidden)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    assert result.status == "ok"


async def test_course_access_does_not_grant_grades_or_quiz_attempts(bridge, owner, seeded):
    target = course(bridge, owner, seeded)
    bridge.registry.entries["synthetic"].scopes = [SCOPES[Endpoint.COURSE], SCOPES[Endpoint.FILES]]
    result = await audit_permissions(
        bridge, owner, seeded, target.id, ["course", "files", "grades"]
    )
    checks = {c["resource"]: c for c in result.data["checks"]}
    assert (
        checks["course"]["scope_authorized"]
        and checks["files"]["resource_capability"] == "configured"
    )
    assert checks["grades"]["reason_code"] == "MISSING_RESOURCE_CAPABILITY"
    assert checks["grades"]["scope_authorized"]
    with pytest.raises(DomainError) as error:
        await bridge.gradebook(owner, seeded, target.id)
    assert error.value.reason_code == "MISSING_RESOURCE_CAPABILITY"
    assert not any(r.url.path.endswith("enrollments") for r in bridge.synthetic.requests)
    assert not bridge.authorize(owner, seeded, target.id, "quizzes", "attempt").allowed


async def test_files_collection_permission_does_not_grant_file_read(bridge, owner, seeded):
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    target = course(bridge, owner, seeded)
    files = await list_files(bridge, owner, seeded, target.id)
    file_id = files.data["files"][0]["file_id"]
    bridge.registry.entries["synthetic"].scopes = [SCOPES[Endpoint.COURSE], SCOPES[Endpoint.FILES]]
    before = len(bridge.synthetic.requests)
    with pytest.raises(DomainError) as error:
        await read_file(bridge, owner, seeded, file_id)
    assert error.value.reason_code == "MISSING_RESOURCE_CAPABILITY"
    assert not any("/files/51" in r.url.path for r in bridge.synthetic.requests[before:])


async def test_denied_file_cache_does_not_leak_in_search(bridge, owner, seeded):
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    target = course(bridge, owner, seeded)
    await list_files(bridge, owner, seeded, target.id)
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    bridge.synthetic.data["module_items"] = {"11": []}
    result = await search_files(bridge, owner, seeded, target.id, "secret")
    assert result.status == "partial_data" and result.data["results"] == []
    listed = await list_files(bridge, owner, seeded, target.id)
    assert listed.data["files"] == []
    assert (
        listed.data["inventory_reason_codes"]["files"]["reason_code"]
        == "RESOURCE_PERMISSION_DENIED"
    )


class NeverRead(httpx.AsyncByteStream):
    async def __aiter__(self):
        pytest.fail("Permission probes must not consume response bodies")
        yield b""  # pragma: no cover


async def test_probes_use_minimal_gets_never_bodies_or_sensitive_resources(
    bridge, owner, seeded, monkeypatch
):
    target = course(bridge, owner, seeded)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=NeverRead())

    monkeypatch.setattr(bridge.synthetic, "handle", handler)
    before = stored_state(bridge)
    result = await audit_permissions(bridge, owner, seeded, target.id, None, True)
    assert result.status == "partial_data" and len(requests) == 5
    assert result.data["credential_state"] == "accepted_for_metadata_request"
    for request in requests:
        assert request.method == "GET" and "include" not in str(request.url)
        assert dict(request.url.params) in ({}, {"per_page": "1"})
        assert all(
            x not in request.url.path
            for x in ("enrollments", "submissions", "questions", "download", "profile")
        )
    checks = {c["resource"]: c for c in result.data["checks"]}
    for resource in ("grades", "syllabus"):
        assert checks[resource]["upstream_permission"] == "not_checked"
        assert checks[resource]["reason_code"] == "NO_SAFE_METADATA_PROBE"
    assert stored_state(bridge) == before


async def test_concurrent_selection_change_discards_probe_conclusions(
    bridge, owner, seeded, monkeypatch
):
    target = course(bridge, owner, seeded)
    original = CanvasClient.probe_metadata

    async def racing(client, resource, upstream):
        result = await original(client, resource, upstream)
        bridge.select_courses(owner, seeded, [], "UTC")
        bridge.select_courses(owner, seeded, [target.id], "UTC")  # ABA change must be detected.
        return result

    monkeypatch.setattr(CanvasClient, "probe_metadata", racing)
    result = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    assert result.status == "partial_data" and result.data["scope_consistency"] == "mismatch"
    assert result.data["checks"][0]["reason_code"] == "STALE_SCOPE_SNAPSHOT"
    assert result.data["checks"][0]["upstream_permission"] == "unknown"


async def test_request_fence_rejects_selection_change_after_read(bridge, owner, seeded):
    target = course(bridge, owner, seeded)
    token = request_authorization.set(RequestAuthorization("test_tool"))
    try:
        bridge.authorize(owner, seeded, target.id, "files").require()
        bridge.select_courses(owner, seeded, [], "UTC")
        bridge.select_courses(owner, seeded, [target.id], "UTC")
        with pytest.raises(DomainError) as error:
            validate_request_authorization(bridge)
        assert error.value.reason_code == "STALE_SCOPE_SNAPSHOT"
    finally:
        request_authorization.reset(token)


async def test_structured_logs_have_correlation_without_identifiers_or_content(
    bridge, owner, seeded, caplog
):
    target = course(bridge, owner, seeded)
    caplog.set_level("INFO", logger="canvas_bridge.authorization")
    context = RequestAuthorization("audit_permission_consistency")
    token = request_authorization.set(context)
    try:
        await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    finally:
        request_authorization.reset(token)
    records = [json.loads(r.message.split("permission_decision ")[1]) for r in caplog.records]
    assert records and all(r["request_id"] == context.request_id for r in records)
    assert {r["correlation_id"] for r in records} == {records[0]["correlation_id"]}
    assert any(r["upstream_http_status"] == 200 for r in records)
    for value in (owner, seeded, target.id, target.name, "fixture-provider-token"):
        assert value not in caplog.text
    assert all(
        set(r)
        == {
            "request_id",
            "tool_name",
            "correlation_id",
            "connection_reference",
            "course_reference",
            "resource_type",
            "authorization_decision",
            "reason_code",
            "scope_snapshot_version",
            "upstream_http_status",
            "timestamp",
        }
        for r in records
    )


async def test_syllabus_read_does_not_request_grade_includes(bridge, owner, seeded):
    target = course(bridge, owner, seeded)
    bridge.synthetic.data["course_details"] = {
        target.source_id: {"id": int(target.source_id), "syllabus_body": "Fictional"}
    }
    bridge.registry.entries["synthetic"].scopes = [SCOPES[Endpoint.COURSE]]
    async with bridge.client(owner, seeded) as client:
        result = await client.one(
            Endpoint.COURSE, course=target.source_id, course_content="syllabus"
        )
        assert result["syllabus_body"] == "Fictional"
        with pytest.raises(DomainError) as error:
            await client.one(Endpoint.COURSE, course=target.source_id)
        assert error.value.reason_code == "MISSING_RESOURCE_CAPABILITY"
    assert bridge.synthetic.requests[-1].url.params.get_list("include[]") == ["syllabus_body"]


async def test_authorization_lease_expiring_during_probe_discards_success(
    bridge, owner, seeded, monkeypatch
):
    target = course(bridge, owner, seeded)
    original = CanvasClient.probe_metadata

    async def racing(client, resource, upstream):
        result = await original(client, resource, upstream)
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).entitlement_at = utcnow() - timedelta(hours=1)
        return result

    monkeypatch.setattr(CanvasClient, "probe_metadata", racing)
    report = await audit_permissions(bridge, owner, seeded, target.id, ["files"], True)
    check = report.data["checks"][0]
    assert report.status == "partial_data"
    assert check["reason_code"] == "STALE_SCOPE_SNAPSHOT"
    assert check["upstream_permission"] == "unknown" and not check["scope_authorized"]


async def test_no_selected_courses_does_not_hide_disabled_connection(bridge, owner, seeded):
    bridge.select_courses(owner, seeded, [], "UTC")
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).state = "disabled"
    report = await audit_permissions(bridge, owner, seeded)
    assert report.status == "reconnect_required" and report.data["checks"] == []
    assert report.data["recommended_action"] == "reconnect_canvas_account"


async def test_cached_work_cannot_bypass_missing_assignment_capability(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    bridge.registry.entries["synthetic"].scopes = [SCOPES[Endpoint.COURSE]]
    with pytest.raises(DomainError) as error:
        bridge.snapshot(owner, seeded, snapshot.id)
    assert error.value.reason_code == "MISSING_RESOURCE_CAPABILITY"
    with pytest.raises(DomainError) as error:
        bridge.changes(owner, seeded, utcnow() - timedelta(days=1))
    assert error.value.reason_code == "MISSING_RESOURCE_CAPABILITY"


async def test_course_refresh_auth_failure_retains_upstream_reason(
    bridge, owner, seeded, monkeypatch
):
    target = course(bridge, owner, seeded)
    monkeypatch.setattr(
        bridge.synthetic,
        "handle",
        lambda request: httpx.Response(
            401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ),
    )
    with pytest.raises(DomainError) as error:
        await list_files(bridge, owner, seeded, target.id)
    assert error.value.status == "reconnect_required"
    assert error.value.reason_code == "UPSTREAM_AUTH_EXPIRED"
    assert error.value.upstream_http_status == 401


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"locked_for_user": True}, "RESOURCE_PERMISSION_DENIED"),
        ({"hidden_for_user": None}, "UNKNOWN_AUTHORIZATION_FAILURE"),
    ],
)
async def test_file_object_permission_remains_separate_from_course(
    bridge, owner, seeded, change, reason
):
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    target = course(bridge, owner, seeded)
    listing = await list_files(bridge, owner, seeded, target.id)
    file_id = listing.data["files"][0]["file_id"]
    bridge.synthetic.data["files"]["11"][0].update(change)
    assert bridge.authorize(owner, seeded, target.id).allowed
    with pytest.raises(DomainError) as error:
        await read_file(bridge, owner, seeded, file_id)
    assert error.value.status == "permission_denied"
    assert error.value.reason_code == reason
