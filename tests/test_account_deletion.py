from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from canvas_bridge.domain import DomainError
from canvas_bridge.jobs import enqueue_refresh
from canvas_bridge.lifecycle import backup, restore
from canvas_bridge.linking import begin_link, delete_account, disconnect, finish_link
from canvas_bridge.storage import (
    BrowserSession,
    Connection,
    Course,
    Job,
    LocalRecord,
    Material,
    OAuthState,
    PrincipalState,
    Snapshot,
    Store,
    Work,
)
from tests.conftest import seed
from tests.test_oauth import configure


async def test_T18_T43_delete_all_institutions_before_remote_revocation_and_preserve_foreign(
    bridge, owner, seeded, monkeypatch
):
    second = await seed(bridge, owner, "second-institution")
    foreign = await seed(bridge, "foreign-owner", "foreign-connection")
    for ref in (seeded, second, foreign):
        await bridge.refresh(owner if ref != foreign else "foreign-owner", ref)
        enqueue_refresh(bridge, owner if ref != foreign else "foreign-owner", ref)
    configure(bridge, monkeypatch)
    begin_link(bridge, owner, "synthetic", "browser", 0)
    attempts = []

    async def revoked(*args):
        # Even an unavailable provider cannot delay local deletion.
        with bridge.store.transaction() as session:
            for cls in (
                Connection,
                Course,
                Work,
                Snapshot,
                Job,
                Material,
                LocalRecord,
                OAuthState,
                BrowserSession,
            ):
                assert not session.scalar(select(cls).where(cls.owner == owner))
        attempts.append(1)
        return "not_confirmed"

    monkeypatch.setattr("canvas_bridge.linking.revoke_token", revoked)
    result = await delete_account(bridge, owner, 0)
    assert result.data["active_store"] == "purged"
    assert result.data["connection_count"] == 2 and len(attempts) == 2
    assert all(r["remote_revocation"] == "not_confirmed" for r in result.data["remote_revocations"])
    with bridge.store.transaction() as session:
        assert session.get(Connection, foreign).state == "active"
        assert session.get(PrincipalState, owner).generation == 1
    with pytest.raises(DomainError):
        bridge.store.export_connection(owner, seeded)


async def test_T18_inflight_oauth_exchange_cannot_create_connection_after_delete(
    bridge, owner, monkeypatch
):
    configure(bridge, monkeypatch)
    state = parse_qs(urlsplit(begin_link(bridge, owner, "synthetic", "browser", 0)).query)["state"][
        0
    ]
    calls = []

    async def exchange(*args, **kwargs):
        await delete_account(bridge, owner, 0)
        return {"access_token": "returned-after-deletion"}

    async def revoked(*args):
        calls.append("revoke")
        return "not_confirmed"

    async def forbidden_profile(*args, **kwargs):
        pytest.fail("No new academic/profile read should start after known deletion.")

    monkeypatch.setattr("canvas_bridge.linking.exchange", exchange)
    monkeypatch.setattr("canvas_bridge.linking.revoke_token", revoked)
    monkeypatch.setattr("canvas_bridge.linking.CanvasClient.one", forbidden_profile)
    result = await finish_link(bridge, state, "browser", "fixture-code")
    assert result.status == "permission_denied" and not result.data["connection_created"]
    assert calls == ["revoke"]
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Connection))


async def test_T18_delete_during_profile_read_fences_final_insert(bridge, owner, monkeypatch):
    configure(bridge, monkeypatch)
    state = parse_qs(urlsplit(begin_link(bridge, owner, "synthetic", "browser", 0)).query)["state"][
        0
    ]

    async def exchange(*args, **kwargs):
        return {"access_token": "profile-flight-fixture"}

    async def profile(*args, **kwargs):
        await delete_account(bridge, owner, 0)
        return {"id": "101"}

    monkeypatch.setattr("canvas_bridge.linking.exchange", exchange)
    monkeypatch.setattr("canvas_bridge.linking.CanvasClient.one", profile)
    result = await finish_link(bridge, state, "browser", "fixture-code")
    assert result.status == "permission_denied"
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Connection))


async def test_T18_stale_browser_cannot_restart_linking_but_new_signin_can(
    bridge, owner, monkeypatch
):
    configure(bridge, monkeypatch)
    await delete_account(bridge, owner, 0)
    with pytest.raises(DomainError, match="Sign in again"):
        begin_link(bridge, owner, "synthetic", "old-browser", 0)
    url = begin_link(bridge, owner, "synthetic", "new-browser", 1)
    assert parse_qs(urlsplit(url).query)["state"]


async def test_T34_account_fence_blocks_old_backup_but_allows_new_explicit_connection(
    bridge, owner, seeded, tmp_path
):
    await bridge.refresh(owner, seeded)
    before = tmp_path / "before.backup"
    backup(bridge, before)
    await delete_account(bridge, owner, 0)
    new_ref = await seed(bridge, owner, "new-explicit-connection")
    after = tmp_path / "after.backup"
    backup(bridge, after)
    original = bridge.store
    for path, expected in ((before, set()), (after, {new_ref})):
        bridge.store = Store("sqlite:///:memory:")
        bridge.store.create_fixture_schema()
        try:
            restore(bridge, path, bridge.settings.deletion_journal)
            with bridge.store.transaction() as session:
                assert {c.id for c in session.scalars(select(Connection))} == expected
                assert session.get(PrincipalState, owner).generation == 1
        finally:
            bridge.store.close()
            bridge.store = original


async def test_T34_unavailable_deletion_journal_does_not_claim_or_partially_delete(
    bridge, owner, seeded, monkeypatch
):
    def unavailable(*args):
        raise OSError("Fixture journal unavailable")

    monkeypatch.setattr("canvas_bridge.lifecycle.journal_delete", unavailable)
    with pytest.raises(OSError):
        await delete_account(bridge, owner, 0)
    with bridge.store.transaction() as session:
        assert session.get(Connection, seeded).credential
        assert session.get(Connection, seeded).state == "active"


async def test_T43_account_revocation_timeout_does_not_delay_local_deletion(
    bridge, owner, seeded, monkeypatch
):
    import asyncio

    bridge.settings.refresh_budget_seconds = 0.01

    async def unavailable(*args):
        with bridge.store.transaction() as session:
            assert not session.scalar(select(Connection).where(Connection.owner == owner))
        await asyncio.sleep(1)
        return "confirmed"

    monkeypatch.setattr("canvas_bridge.linking.revoke_token", unavailable)
    result = await delete_account(bridge, owner, 0)
    assert result.data["remote_revocations"][0]["remote_revocation"] == "not_confirmed"


async def test_T07_T18_term_retirement_purges_course_history(bridge, owner, seeded):
    await bridge.refresh(owner, seeded)
    _, courses = bridge.selected(owner, seeded)
    retired = next(c for c in courses if c.source_id == "11")
    bridge.synthetic.data["courses"][0]["workflow_state"] = "completed"
    result = await bridge.list_courses(owner, seeded)
    assert retired.id not in {c["id"] for c in result.data["courses"]}
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Work).where(Work.course_id == retired.id))
        assert not session.scalar(select(Snapshot))


async def test_T43_corrupt_local_credential_does_not_hide_completed_disconnect(
    bridge, owner, seeded
):
    import base64

    bridge.synthetic = None
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).credential = base64.urlsafe_b64encode(b"x" * 64).decode()
    result = await disconnect(bridge, owner, seeded)
    assert result.data["active_store"] == "purged"
    assert result.data["remote_revocation"] == "not_confirmed"
