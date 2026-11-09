from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from canvas_bridge.analytics.observations import Declaration, Period, Review, latest
from canvas_bridge.analytics.storage import load_history
from canvas_bridge.domain import utcnow

NOW = datetime(2026, 11, 2, 5, tzinfo=UTC)


def review(**changes):
    params = dict(
        course_ids=["one"],
        windows=[Period(start=NOW - timedelta(days=7), end=NOW)],
        timezone="America/New_York",
        as_of=NOW,
        evidence_cutoff=NOW,
    )
    return Review(**(params | changes))


def test_cutoffs_scope_and_replay():
    earlier = Declaration(
        key="a",
        course_ids=["one"],
        observed_at=NOW,
        source_ref="a",
        basis="student_declaration",
        status="not_started",
    )
    after = earlier.model_copy(
        update={
            "observed_at": NOW + timedelta(days=1),
            "version": 2,
            "status": "student_marked_done",
        }
    )
    other = earlier.model_copy(update={"course_ids": ["two"]})
    request = review(evidence_cutoff=after.observed_at)
    assert list(latest([after, other, earlier, earlier], request).values()) == [earlier]
    corrected = after.model_copy(update={"effective_at": NOW})
    assert list(latest([corrected, earlier], request).values()) == [corrected]
    assert list(latest([corrected, earlier], review()).values()) == [earlier]
    with pytest.raises(ValueError):
        latest([earlier, earlier.model_copy(update={"status": "unknown"})], request)
    with pytest.raises(ValidationError):
        review(as_of=NOW - timedelta(hours=1))


async def test_scoped_snapshot_population_and_optional_capture(bridge, owner, seeded, monkeypatch):
    _, courses = bridge.selected(owner, seeded)
    snap = await bridge.refresh(owner, seeded)
    now = utcnow()
    req = review(
        course_ids=[courses[0].id],
        as_of=now,
        evidence_cutoff=now,
        windows=[Period(start=now - timedelta(days=1), end=now)],
    )
    h, _ = load_history(bridge, owner, seeded, req)
    assert {r.key for r in h.dues} == {
        r["id"]
        for r in snap.items
        if r["course_id"] == courses[0].id and r["availability_state"] != "inaccessible"
    }
    work = h.dues[0].key

    def fail(*args):
        raise RuntimeError("fixture capture failure")

    monkeypatch.setattr("canvas_bridge.analytics.storage.capture_save", fail)
    saved = bridge.store.save_local(owner, seeded, "progress", work, {"status": "in_progress"}, 0)
    assert (
        saved["version"] == 1 and saved["measurement_coverage"] == "observation_capture_unavailable"
    )


async def test_later_verified_submission_can_restate_but_capture_only_fields_cannot(
    bridge, owner, seeded
):
    from canvas_bridge.analytics.report import report
    from canvas_bridge.storage import Snapshot

    snap = await bridge.refresh(owner, seeded)
    cid = snap.course_ids[0]
    raw = next(i for i in snap.items if i["course_id"] == cid)
    now = utcnow()
    prior = now - timedelta(days=2)
    due = prior - timedelta(hours=2)
    submitted = prior - timedelta(hours=3)
    historic = raw | {
        "effective_due": {"kind": "timestamp", "timestamp": due.isoformat()},
        "timeliness_state": "unknown",
        "personal_progress": "unknown",
        "submitted_at": None,
    }
    later = historic | {
        "personal_progress": "student_marked_done",
        "submission_state": "submitted",
        "submission_evidence": "returned",
        "submitted_at": submitted.isoformat(),
        "effective_due": {"kind": "timestamp", "timestamp": now.isoformat()},
    }
    with bridge.store.transaction() as session:
        for key, when, data in [("past", prior, [historic]), ("later-evidence", now, [later])]:
            session.add(
                Snapshot(
                    id=key,
                    owner=owner,
                    connection_id=seeded,
                    course_ids=[cid],
                    created_at=when,
                    items=data,
                    coverage=[],
                    complete=True,
                    workload_scope={"kind": "source_inventory"},
                )
            )
    req = review(
        course_ids=[cid],
        windows=[Period(start=prior - timedelta(days=1), end=prior)],
        as_of=prior,
        evidence_cutoff=prior,
    )
    old = report(bridge, owner, seeded, req, save=True).data
    req.evidence_cutoff = now
    req.restates = old["report_id"]
    new = report(bridge, owner, seeded, req).data
    deadline, progress = new["periods"][0]["families"][:2]
    assert deadline["counts"]["on_time"] == 1 and deadline["eligible"] == 1
    assert progress["unknown"] == 1
    assert old["periods"][0]["families"][0]["unknown"] == 1


async def test_bounded_native_inventory_keeps_actual_omissions(bridge, owner, seeded, monkeypatch):
    from canvas_bridge.analytics.report import report
    from canvas_bridge.storage import Snapshot

    snap = await bridge.refresh(owner, seeded)
    cid = snap.course_ids[0]
    at = utcnow()
    raw = next(i for i in snap.items if i["course_id"] == cid)
    rows = [
        raw
        | {
            "id": "p" + str(i),
            "availability_state": "available",
            "assessment_state": "unknown",
            "timeliness_state": v,
            "submitted_at": None,
            "effective_due": {
                "kind": "timestamp",
                "timestamp": (at - timedelta(hours=1)).isoformat(),
            },
        }
        for i, v in enumerate(
            ["missing", "late", "on_time", "unknown", "unknown", "late", "on_time", "on_time"]
        )
    ]
    with bridge.store.transaction() as session:
        session.add(
            Snapshot(
                owner=owner,
                connection_id=seeded,
                created_at=at,
                course_ids=[cid],
                items=rows,
                complete=True,
                coverage=[],
                workload_scope={"kind": "filtered_workload", "work_ids": ["p1"]},
            )
        )
    monkeypatch.setattr("canvas_bridge.analytics.storage.ITEM_LIMIT", 5)
    req = review(
        course_ids=[cid],
        windows=[Period(start=at - timedelta(days=1), end=at)],
        as_of=at,
        evidence_cutoff=at,
    )
    data = report(bridge, owner, seeded, req).data
    f = data["periods"][0]["families"][0]
    assert (
        f["eligible"],
        f["evaluated"],
        f["counts"]["missed"],
        f["unknown"],
        f["full_scope_rate"],
    ) == (5, 3, 1, 2, None)
    assert data["inventory_coverage"][0]["omitted_count"] == 3
    from tests.test_analytics_archive import write_evidence

    write_evidence(
        "bounded-native-inventory", {"request": req.model_dump(mode="json"), "report": data}
    )
