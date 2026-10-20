import asyncio
from datetime import timedelta

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from canvas_bridge.auth import JWTVerifier
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.jobs import enqueue_refresh, work_once
from canvas_bridge.linking import disconnect
from canvas_bridge.network import PublicBackend
from canvas_bridge.policy import Endpoint, public_ip, route, validate_continuation
from canvas_bridge.retrieval import fetch_material, outline, search_materials
from canvas_bridge.storage import Connection, Job, Snapshot, Work
from tests.conftest import seed


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "https://another-resource.invalid"},
        {"iss": "https://another-issuer.invalid"},
        {"exp": 1},
        {"sub": ""},
        {"scope": "preferences:write"},
    ],
)
async def test_T21_invalid_token_rejected(settings, token_factory, overrides):
    assert await JWTVerifier(settings).verify_token(token_factory(**overrides)) is None


async def test_T21_valid_identity_uses_subject_not_email(settings, token_factory):
    token = await JWTVerifier(settings).verify_token(token_factory(email="same@example.invalid"))
    assert token.subject == "student-one"
    assert token.claims == {"iss": settings.issuer_url}


async def test_T21_expired_key_cache_fails_closed(settings, token_factory):
    verifier = JWTVerifier(settings)
    raw = token_factory()
    assert await verifier.verify_token(raw)
    # Monotonic zero can be recent on a freshly booted Linux runner.
    verifier.loaded_at -= 301
    settings.local_jwks_file.unlink()
    assert await verifier.verify_token(raw) is None


def test_T23_credentials_are_bound_to_owner_and_connection(bridge, owner):
    sealed = bridge.vault.seal({"access_token": "private-fixture"}, owner, "one")
    assert "private-fixture" not in sealed
    assert bridge.vault.open(sealed, owner, "one")["access_token"] == "private-fixture"
    with pytest.raises(InvalidTag):
        bridge.vault.open(sealed, "other", "one")
    with pytest.raises(InvalidTag):
        bridge.vault.open(sealed, owner, "two")


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104 - blocked-address fixture, not a bind.
    ],
)
def test_T23_private_addresses_blocked(value):
    assert not public_ip(value)


async def test_T23_dns_connect_is_pinned_to_validated_address(monkeypatch):
    backend = PublicBackend()
    loop = asyncio.get_running_loop()

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    observed = []

    async def connect(host, port, **kwargs):
        observed.append((host, port))
        return object()

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    await backend.connect_tcp("school.invalid", 443)
    assert observed == [("8.8.8.8", 443)]


async def test_T23_dns_rebinding_to_private_is_rejected(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("169.254.169.254", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(DomainError):
        await PublicBackend().connect_tcp("school.invalid", 443)


@pytest.mark.parametrize(
    "next_url",
    [
        "http://school.invalid/api/v1/courses?per_page=100&page=2",
        "https://evil.invalid/api/v1/courses?per_page=100&page=2",
        "https://school.invalid/api/v1/users?per_page=100&page=2",
        "https://school.invalid/api/v1/courses?per_page=100&page=2&as_user_id=other",
        "https://school.invalid/api/v1/courses?per_page=999999&page=2",
    ],
)
def test_T22_T23_continuations_cannot_widen_route_or_authority(next_url):
    with pytest.raises(DomainError):
        validate_continuation(next_url, "https://school.invalid/api/v1/courses?per_page=100")


def test_T22_no_generic_academic_route():
    with pytest.raises(DomainError):
        route("/api/v1/courses/1/users")
    with pytest.raises(DomainError):
        route(Endpoint.ASSIGNMENTS, course="1/../../users")


async def test_T01_middle_page_failure_preserves_partial_coverage(bridge, owner, seeded):
    calls = []

    def handle(request):
        calls.append(request.url)
        if "page=2" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={
                "Link": f'<{request.url.copy_set_param("page", "2")}>; rel="next"',
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(
            bridge.registry.require("synthetic", True),
            "private",
            bridge.settings,
            http,
        )
        result = await client.collection(Endpoint.ASSIGNMENTS, course="11")
    assert not result.complete and result.pages == 1 and result.items == [{"id": 1}]
    assert result.failure == "retry_later"
    assert len(calls) == 4  # First page + bounded three attempts, not an infinite retry.


async def test_T03_T06_T46_workload_has_undated_and_submitted_items(bridge, owner, seeded):
    now = utcnow()
    result = await bridge.workload(owner, seeded, now, now + timedelta(days=7), "UTC")
    assert result.status == "ok"
    assert len(result.data["items"]) == 5
    assert any(
        x["section"] == "undated" and x["submission_state"] == "not_applicable"
        for x in result.data["items"]
    )
    assert len(result.sources) == 5
    assert all(c.pagination_complete for c in result.meta.coverage)
    assert all("visible_score" not in x for x in result.data["items"])


async def test_T13_T21_foreign_connection_and_cursor_denied(bridge, owner, seeded):
    other_ref = await seed(bridge, "another-owner", "connection-two")
    now = utcnow()
    with pytest.raises(DomainError):
        await bridge.workload("another-owner", seeded, now, now + timedelta(days=7), "UTC")
    first = await bridge.workload(owner, seeded, now, now + timedelta(days=7), "UTC", limit=2)
    cursor = first.meta.next_cursor
    assert cursor
    second = await bridge.workload(
        owner, seeded, now, now + timedelta(days=7), "UTC", limit=2, cursor=cursor
    )
    assert not {x["id"] for x in first.data["items"]} & {x["id"] for x in second.data["items"]}
    with pytest.raises(DomainError):
        await bridge.workload(
            "another-owner", other_ref, now, now + timedelta(days=7), "UTC", limit=2, cursor=cursor
        )
    with pytest.raises(DomainError):
        await bridge.workload(
            owner, seeded, now, now + timedelta(days=7), "America/New_York", limit=2, cursor=cursor
        )


async def test_T14_T15_partial_refresh_never_advances_success(bridge, owner, seeded):
    first = await bridge.refresh(owner, seeded)
    with bridge.store.transaction() as session:
        success = session.get(Connection, seeded).last_success
    bridge.synthetic.failures["/api/v1/courses/12/assignments"] = 503
    second = await bridge.refresh(owner, seeded)
    assert first.complete and not second.complete
    assert any(c["state"] == "partial" for c in second.coverage)
    with bridge.store.transaction() as session:
        assert session.get(Connection, seeded).last_success == success


async def test_T39_staff_power_does_not_expand_student_access(bridge, owner, seeded):
    bridge.synthetic.data["courses"][0]["enrollments"].append({"type": "teacher", "user_id": 101})
    courses = await bridge.list_courses(owner, seeded)
    assert len(courses.data["courses"]) == 1
    with bridge.store.transaction() as session:
        from canvas_bridge.storage import Course

        assert session.scalar(select(Course).where(Course.source_id == "11")).accessible is False


async def test_T07_personal_effort_is_applied_without_canvas_completion(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    work_id = snapshot.items[0]["id"]
    bridge.store.save_local(
        owner,
        seeded,
        "progress",
        work_id,
        {
            "status": "student_marked_done",
            "remaining_effort": {
                "minimum_minutes": 30,
                "maximum_minutes": 45,
                "origin": "student_estimate",
            },
        },
        0,
    )
    updated = await bridge.refresh(owner, seeded)
    item = next(x for x in updated.items if x["id"] == work_id)
    assert item["personal_progress"] == "student_marked_done"
    assert item["submission_state"] == "not_submitted"
    assert item["effort_remaining"]["maximum_minutes"] == 45


async def test_T18_T43_disconnect_fences_cache_and_queued_jobs(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    job = enqueue_refresh(bridge, owner, seeded)
    assert job
    result = await disconnect(bridge, owner, seeded)
    assert result.data["remote_revocation"] == "not_applicable"
    with pytest.raises(DomainError):
        bridge.snapshot(owner, seeded, snapshot.id)
    assert not await work_once(bridge)
    with bridge.store.transaction() as session:
        assert session.get(Connection, seeded).credential is None
        assert not list(session.scalars(select(Work)))
        assert not list(session.scalars(select(Job)))
        assert not list(session.scalars(select(Snapshot)))
    assert bridge.settings.deletion_journal.read_text()


async def test_T27_first_observed_is_not_invented_history(bridge, owner, seeded):
    result = bridge.changes(owner, seeded, utcnow() - timedelta(days=1))
    assert result.status == "needs_input"
    first = await bridge.refresh(owner, seeded)
    bridge.synthetic.data["assignments"]["11"][0]["name"] = "Updated requirements"
    await bridge.refresh(owner, seeded)
    from canvas_bridge.storage import aware

    changes = bridge.changes(owner, seeded, aware(first.created_at))
    assert len(changes.data["changes"]) == 1
    assert changes.data["changes"][0]["field"] == "title"


async def test_T09_T26_material_access_loss_blocks_cached_search(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    result = await outline(bridge, owner, seeded, courses[0].id)
    material_id = result.data["materials"][0]["id"]
    fetched = await fetch_material(bridge, owner, seeded, material_id)
    assert "Synthetic syllabus" in fetched.data["text"]
    found = await search_materials(bridge, owner, seeded, "notebook")
    assert found.data["results"]
    bridge.synthetic.failures[f"/api/v1/courses/{courses[0].source_id}/pages/page_id:41"] = 403
    denied = await search_materials(bridge, owner, seeded, "notebook")
    assert not denied.data["results"]
    with pytest.raises(DomainError):
        await fetch_material(bridge, "another-owner", seeded, material_id)


async def test_T09_closed_and_locked_assignment_never_exposes_content(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    work = next(x for x in snapshot.items if x["title"] == "Membrane transport analysis")
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["lock_at"] = (utcnow() - timedelta(days=1)).isoformat()
    raw["locked_for_user"] = True
    raw["description"] = "Restricted fixture content."
    with pytest.raises(DomainError):
        await bridge.assignment_details(owner, seeded, work["id"])
