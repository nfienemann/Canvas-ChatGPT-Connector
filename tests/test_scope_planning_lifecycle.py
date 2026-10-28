import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from canvas_bridge.domain import DomainError
from canvas_bridge.lifecycle import backup, restore
from canvas_bridge.planning import PinnedBlock, PlanRequest, Window, propose
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Connection, Job, LocalRecord, Material, Snapshot, Work
from tests.test_domain_planning import NOW, task


def test_T20_T42_replan_preserves_pins_excludes_busy_and_keeps_breaks():
    pin = PinnedBlock(
        work_id="a", start=NOW + timedelta(minutes=90), end=NOW + timedelta(minutes=120)
    )
    busy = Window(start=NOW + timedelta(minutes=30), end=NOW + timedelta(minutes=60))
    result = propose(
        [task("a", 60), task("b", 30)],
        PlanRequest(
            windows=[Window(start=NOW, end=NOW + timedelta(hours=3))],
            pinned_blocks=[pin],
            busy_times=[busy],
            break_minutes=10,
            buffer_minutes=10,
        ),
        NOW,
    )
    fixed = next(b for b in result["blocks"] if b["pinned"])
    assert (fixed["start"], fixed["end"]) == (pin.start.isoformat(), pin.end.isoformat())
    for block in result["blocks"]:
        assert block["end"] <= busy.start.isoformat() or block["start"] >= busy.end.isoformat()
        assert block["end"] <= (NOW + timedelta(minutes=170)).isoformat()
    assert sum(b["minutes"] for b in result["blocks"]) == 90


def test_T20_dependencies_respect_finish_time_and_reverse_input_order():
    dependent, prerequisite = task("a", 30), task("z", 30)
    dependent.prerequisites = ["z"]
    result = propose(
        [dependent, prerequisite],
        PlanRequest(windows=[Window(start=NOW, end=NOW + timedelta(hours=2))]),
        NOW,
    )
    assert result["feasibility"] == "feasible"
    assert [b["work_id"] for b in result["blocks"]] == ["z", "a"]
    assert result["blocks"][0]["end"] <= result["blocks"][1]["start"]


def test_T20_dependency_cycles_and_unknown_references_do_not_claim_feasibility():
    a, b = task("a", 30), task("b", 30)
    a.prerequisites, b.prerequisites = ["b"], ["a"]
    result = propose(
        [a, b], PlanRequest(windows=[Window(start=NOW, end=NOW + timedelta(hours=2))]), NOW
    )
    assert result["feasibility"] == "provisional" and not result["blocks"]
    assert result["known_shortfall_minutes"] == 0
    assert result["information_status"] == "uncertain"


def test_T20_pinned_conflict_requires_correction_not_silent_move():
    with pytest.raises(ValueError, match="conflicts"):
        propose(
            [task("a", 30)],
            PlanRequest(
                windows=[Window(start=NOW, end=NOW + timedelta(hours=2))],
                busy_times=[Window(start=NOW, end=NOW + timedelta(hours=1))],
                pinned_blocks=[
                    PinnedBlock(work_id="a", start=NOW, end=NOW + timedelta(minutes=30))
                ],
            ),
            NOW,
        )


def test_T07_offline_personal_done_not_recommended_online_status_preserved():
    offline, online = task("offline", 30), task("online", 30)
    for item in [offline, online]:
        item.personal_progress = "student_marked_done"
    offline.submission_state = "not_applicable"
    online.submission_state = "not_submitted"
    result = propose([offline, online], PlanRequest(), NOW)
    assert [r["work_id"] for r in result["recommendations"]] == ["online"]
    assert online.submission_state == "not_submitted"


async def test_T18_T34_complete_export_has_material_history_and_no_credentials(
    bridge, owner, seeded
):
    snapshot = await bridge.refresh(owner, seeded)
    _, courses = bridge.selected(owner, seeded)
    index = await outline(bridge, owner, seeded, courses[0].id)
    await fetch_material(bridge, owner, seeded, index.data["materials"][0]["id"])
    output = bridge.store.export_connection(owner, seeded)
    assert output["records"]["snapshots"][0]["id"] == snapshot.id
    assert output["records"]["materials"][0]["text"]
    assert len(output["records"]["courses"]) == 2
    raw = json.dumps(output)
    assert "fixture-provider-token" not in raw and '"credential"' not in raw
    with pytest.raises(DomainError):
        bridge.store.export_connection("another-owner", seeded)


async def test_T18_T34_course_deselection_purges_derived_data_and_fences_old_backup(
    bridge, owner, seeded, tmp_path
):
    snapshot = await bridge.refresh(owner, seeded)
    work_id = snapshot.items[0]["id"]
    bridge.store.save_local(owner, seeded, "progress", work_id, {"status": "in_progress"}, 0)
    bridge.store.save_local(owner, seeded, "plan", "current", {"snapshot_id": snapshot.id}, 0)
    _, courses = bridge.selected(owner, seeded)
    index = await outline(bridge, owner, seeded, courses[0].id)
    await fetch_material(bridge, owner, seeded, index.data["materials"][0]["id"])
    path = tmp_path / "before-removal.enc"
    backup(bridge, path)
    bridge.select_courses(owner, seeded, [courses[1].id], "UTC")
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Work).where(Work.course_id == courses[0].id)))
        assert not list(
            session.scalars(select(Material).where(Material.course_id == courses[0].id))
        )
        assert not list(session.scalars(select(Snapshot)))
        assert not list(session.scalars(select(LocalRecord)))
        assert not list(session.scalars(select(Job)))
    with pytest.raises(DomainError):
        bridge.store.save_local(owner, seeded, "progress", work_id, {"status": "in_progress"}, 0)
    # Destructive restore testing uses a separate, empty in-memory fixture store.
    from canvas_bridge.storage import Store

    original = bridge.store
    bridge.store = Store("sqlite:///:memory:")
    bridge.store.create_fixture_schema()
    try:
        restore(bridge, path, bridge.settings.deletion_journal)
        with bridge.store.transaction() as session:
            assert not list(session.scalars(select(Connection)))
    finally:
        bridge.store.close()
        bridge.store = original


async def test_T14_T18_denial_during_refresh_removes_cached_course(bridge, owner, seeded):
    await bridge.refresh(owner, seeded)
    _, courses = bridge.selected(owner, seeded)
    revoked = next(c for c in courses if c.source_id == "11")
    bridge.synthetic.failures["/api/v1/courses/11/assignments"] = 403
    with pytest.raises(DomainError, match="Source access changed"):
        await bridge.refresh(owner, seeded)
    with bridge.store.transaction() as session:
        rows = list(session.scalars(select(Work)))
        assert rows and all(w.course_id != revoked.id for w in rows)
        assert not list(session.scalars(select(Snapshot)))
