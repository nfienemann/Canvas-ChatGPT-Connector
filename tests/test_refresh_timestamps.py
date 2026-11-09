from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import text

from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.database_upgrade import migration_config
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.membership import membership_state
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Connection, Store, aware
from tests.test_database_upgrade_postgres import disposable_postgres as disposable_postgres


def check_backfill(settings):
    cfg = migration_config(settings)
    command.upgrade(cfg, "b39f81ca26de")
    store = Store(settings.database_url)
    try:
        with store.engine.begin() as db:
            for identifier, stamp in (
                ("old", "2025-11-02 06:10:00"),
                ("missing", None),
                ("future", "2099-11-02 06:10:00"),
            ):
                db.execute(
                    text(
                        "INSERT INTO connections (id,owner,institution,canvas_user,state,authentication_state,epoch,timezone,created_at,entitlement_at) "
                        "VALUES (:id,'fixture','synthetic','fixture','active','verified',0,'UTC',CURRENT_TIMESTAMP,:stamp)"
                    ),
                    {"id": identifier, "stamp": stamp},
                )
        command.upgrade(cfg, "head")
        with store.engine.connect() as db:
            rows = db.execute(
                text(
                    "SELECT id,last_complete_course_list_at,last_course_list_attempt_at,last_course_list_outcome FROM connections"
                )
            ).all()
            for identifier, success, attempt, outcome in rows:
                assert bool(success) == (identifier == "old")
                assert attempt is outcome is None
    finally:
        store.close()


def test_sqlite_membership_backfill(settings, tmp_path):
    settings.database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    check_backfill(settings)


def test_pg_membership_backfill(disposable_postgres):
    check_backfill(disposable_postgres[0])


def test_evidence_boundaries_and_eastern_fold():
    now = datetime(2026, 11, 1, 6, 10, tzinfo=UTC)
    assert membership_state(now - timedelta(seconds=300), now, 300) == "within_lease"
    assert membership_state(now - timedelta(seconds=300, microseconds=1), now, 300) == "expired"
    assert membership_state(now + timedelta(microseconds=1), now, 300) == "invalid_clock"
    assert membership_state(None, now, 300) == "missing"
    eastern = ZoneInfo("America/New_York")
    assert now.astimezone(eastern).strftime("%H:%M %z") == "01:10 -0500"
    assert (now - timedelta(hours=1)).astimezone(eastern).strftime("%H:%M %z") == "01:10 -0400"


async def test_membership_failure_and_future_evidence(bridge, owner, seeded, monkeypatch):
    def state():
        return bridge.connection_status(owner).data["connections"][0]

    complete = state()["last_complete_course_list_at"]
    with bridge.store.transaction() as db:
        db.get(Connection, seeded).entitlement_at = utcnow() + timedelta(hours=1)
    assert state()["membership_lease_state"] == "invalid_clock"
    with pytest.raises(DomainError, match="refresh"):
        bridge.selected(owner, seeded)

    async def broken(*args, **kwargs):
        raise RuntimeError("fixture interrupted")

    monkeypatch.setattr(CanvasClient, "collection", broken)
    with pytest.raises(RuntimeError, match="fixture interrupted"):
        await bridge.list_courses(owner, seeded)
    after = state()
    assert after["last_complete_course_list_at"] == complete
    assert after["membership_lease_state"] == "missing"
    assert after["last_course_list_outcome"] == "failed"
    assert after["membership_evidence_at"] is after["membership_lease_expires_at"] is None


async def test_assignment_snapshot_continuation_and_incomplete_refresh(
    bridge, owner, seeded, monkeypatch
):
    course = bridge.selected(owner, seeded)[1][0]
    now = utcnow()
    args = (owner, seeded, now - timedelta(days=2), now + timedelta(days=15), "America/New_York")
    first = await bridge.workload(*args, course_refs=[course.id], limit=1)
    status = bridge.connection_status(owner).data["connections"][0]
    success = status["last_complete_assignment_refresh_at"]
    assert success and success == status["last_successful_refresh"]
    if first.meta.next_cursor is None:
        first = await bridge.workload(*args, limit=1)
        course_ids = None
        success = bridge.connection_status(owner).data["connections"][0][
            "last_complete_assignment_refresh_at"
        ]
    else:
        course_ids = [course.id]
    assert first.meta.next_cursor
    second = await bridge.workload(
        *args, course_refs=course_ids, limit=1, cursor=first.meta.next_cursor
    )
    assert second.meta.freshness == "cached"
    assert second.meta.workload_snapshot_created_at == first.meta.workload_snapshot_created_at
    assert second.meta.response_generated_at >= first.meta.response_generated_at
    original = CanvasClient.collection

    async def partial(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS:
            return Collection(pages=1, failure="retry_later")
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", partial)
    snapshot = await bridge.refresh(owner, seeded)
    assert (
        not snapshot.complete
        and aware(snapshot.created_at) >= first.meta.workload_snapshot_created_at
    )
    assert (
        bridge.connection_status(owner).data["connections"][0]["last_successful_refresh"] == success
    )


async def test_superseded_listing_cannot_restore_evidence(bridge, owner, seeded, monkeypatch):
    import asyncio

    entered, resume = asyncio.Event(), asyncio.Event()
    original = CanvasClient.collection

    async def delayed(client, endpoint, **kwargs):
        collection = await original(client, endpoint, **kwargs)
        entered.set()
        await resume.wait()
        return collection

    monkeypatch.setattr(CanvasClient, "collection", delayed)
    task = asyncio.create_task(bridge.list_courses(owner, seeded))
    await entered.wait()
    # Simulate a newer committed attempt from a second SQLite service.
    with bridge.store.transaction() as db:
        row = db.get(Connection, seeded)
        row.last_course_list_attempt_at = utcnow()
        row.last_course_list_outcome = "failed"
        row.entitlement_at = None
    resume.set()
    with pytest.raises(DomainError, match="changed"):
        await task
    state = bridge.connection_status(owner).data["connections"][0]
    assert state["last_course_list_outcome"] == "failed" and state["membership_evidence_at"] is None


async def test_history_survives_minimization_only_when_authorized(bridge, owner, seeded):
    from canvas_bridge.egress_sources import minimize
    from canvas_bridge.membership import MEMBERSHIP_FIELDS
    from canvas_bridge.privacy.output import filter_output

    def status():
        projected, _ = minimize(bridge.connection_status(owner), "get_connection_status", live=True)
        public, *_ = filter_output(projected.model_dump(mode="json"))
        return public["data"]["connections"][0]

    assert set(MEMBERSHIP_FIELDS) <= status().keys()
    bridge.settings.live_access_enabled = False
    bridge.settings.capability_profile = "offline_research"
    restricted = status()
    assert not set(MEMBERSHIP_FIELDS).intersection(restricted)
    assert "last_successful_refresh" not in restricted
    bridge.store.disconnect(owner, seeded)
    with bridge.store.transaction() as db:
        row = db.get(Connection, seeded)
        assert row.last_complete_course_list_at is row.last_course_list_attempt_at is None
        assert row.entitlement_at is row.last_course_list_outcome is None


async def test_unusable_listing_rolls_back_before_recording_failure(bridge, owner, seeded):
    before = bridge.connection_status(owner).data["connections"][0]
    bridge.synthetic.data["courses"][0]["id"] = "invalid"
    with pytest.raises(DomainError):
        await bridge.list_courses(owner, seeded)
    after = bridge.connection_status(owner).data["connections"][0]
    assert after["last_course_list_outcome"] == "failed"
    assert after["last_complete_course_list_at"] == before["last_complete_course_list_at"]
    assert after["membership_lease_state"] == "missing"
