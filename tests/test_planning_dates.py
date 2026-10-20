from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from canvas_bridge.calendar_sync import propose_sync
from canvas_bridge.domain import DomainError, FactDate, utcnow
from canvas_bridge.planning import PinnedBlock, PlanRequest, Window, propose
from canvas_bridge.planning_dates import resolve_timing
from canvas_bridge.storage import Snapshot
from tests.test_academic_intelligence import context
from tests.test_domain_planning import NOW, task
from tests.test_mcp_contract import running as running


def dated(day=date(2026, 10, 21), minutes=60):
    item = task("date-only", minutes)
    item.effective_due = FactDate(kind="local_date", local_date=day, raw=day.isoformat())
    return item


def request_for(start=NOW, end=NOW + timedelta(hours=2), **kwargs):
    return PlanRequest(
        windows=[Window(start=start, end=end)],
        break_minutes=0,
        buffer_minutes=0,
        max_block_minutes=180,
        **kwargs,
    )


def test_T04_T20_date_only_without_timezone_never_allocates_or_guesses():
    item = dated()
    result = propose([item], request_for(), NOW)
    assert not result["blocks"]
    assert result["unmet_work"][0]["reason"] == "date_only_timezone_required"
    assert result["known_shortfall_minutes"] == 0  # Unknown timing is not a capacity shortfall.
    assert result["feasibility"] == "timing_unresolved"
    assert result["recommendations"][0]["urgency"] == "unresolved"
    assert item.effective_due.timestamp is None
    assert result["timing_constraints"][item.id]["source_due"]["raw"] == "2026-10-21"


@pytest.mark.parametrize(
    "zone,cutoff",
    [
        ("America/New_York", "2026-10-21T04:00:00+00:00"),
        ("Pacific/Auckland", "2026-10-20T11:00:00+00:00"),
    ],
)
def test_T04_T20_date_only_bounds_keep_source_and_timezone_provenance(zone, cutoff):
    item = dated()
    now = datetime(2026, 10, 20, 0, tzinfo=UTC)
    request = request_for(now, now + timedelta(hours=3), date_only_timezones={item.id: zone})
    before = item.model_dump(mode="json")
    result = propose([item], request, now)
    timing = result["timing_constraints"][item.id]
    assert timing["planning_finish_by"] == cutoff
    assert timing["source_due"]["timestamp"] is None
    assert timing["timezone_basis"] == "student_or_conversation_input"
    assert "not a reported deadline time" in timing["assumptions"][0]
    assert result["blocks"] and result["feasibility"] == "provisional"
    assert item.model_dump(mode="json") == before
    assert propose([item], request, now) == result


def test_T04_T20_no_block_on_or_after_date_only_due_day():
    item = dated()
    start = datetime(2026, 10, 21, 4, tzinfo=UTC)
    result = propose(
        [item],
        request_for(
            start, start + timedelta(hours=2), date_only_timezones={item.id: "America/New_York"}
        ),
        NOW,
    )
    assert not result["blocks"]
    assert result["known_shortfall_minutes"] == 60
    # When already on the source day, unknown due time requires clarification,
    # not a claim that the actual Canvas deadline has passed.
    current = propose(
        [item],
        request_for(
            start, start + timedelta(hours=2), date_only_timezones={item.id: "America/New_York"}
        ),
        start,
    )
    assert current["unmet_work"][0]["reason"] == "date_only_deadline_needs_clarification"
    assert not current["timing_constraints"][item.id]["overdue_recovery"]


@pytest.mark.parametrize("field", ["available_from", "closes_at"])
def test_T04_T20_date_only_availability_requires_timezone(field):
    item = task("availability", 30, NOW + timedelta(days=3))
    setattr(item, field, FactDate(kind="local_date", local_date=NOW.date()))
    assert not propose([item], request_for(), NOW)["blocks"]
    timing = resolve_timing(item, NOW, "UTC")
    if field == "available_from":
        assert timing.opens == datetime(2026, 10, 21, tzinfo=UTC)
    else:
        assert timing.blocked == "source_closing_bound_passed"


def test_T04_T20_opening_constraint_and_conflicting_bounds():
    item = task("opens-later", 60, NOW + timedelta(hours=4))
    item.available_from = FactDate(kind="timestamp", timestamp=NOW + timedelta(hours=1))
    result = propose([item], request_for(), NOW)
    assert result["blocks"][0]["start"] == (NOW + timedelta(hours=1)).isoformat()
    item.closes_at = FactDate(kind="timestamp", timestamp=NOW + timedelta(minutes=30))
    conflict = propose([item], request_for(), NOW)
    assert not conflict["blocks"]
    assert conflict["unmet_work"][0]["reason"] == "source_timing_bounds_conflict"


@pytest.mark.parametrize("mode", ["date_only", "closed", "before_open"])
def test_T04_T42_pins_cannot_override_source_or_unknown_date_bounds(mode):
    item = dated() if mode == "date_only" else task("pinned", 30)
    if mode == "closed":
        item.closes_at = FactDate(kind="timestamp", timestamp=NOW - timedelta(minutes=1))
    if mode == "before_open":
        item.available_from = FactDate(kind="timestamp", timestamp=NOW + timedelta(hours=1))
    pin = PinnedBlock(work_id=item.id, start=NOW, end=NOW + timedelta(minutes=30))
    with pytest.raises(ValueError, match="source timing"):
        propose([item], request_for(pinned_blocks=[pin]), NOW)


def test_T04_T42_pinned_date_only_after_cutoff_rejected_without_move():
    item = dated()
    start = NOW + timedelta(days=2)
    pin = PinnedBlock(work_id=item.id, start=start, end=start + timedelta(minutes=30))
    before = pin.model_dump()
    with pytest.raises(ValueError, match="date-only planning bound"):
        propose(
            [item],
            request_for(
                start,
                start + timedelta(hours=1),
                pinned_blocks=[pin],
                date_only_timezones={item.id: "UTC"},
            ),
            NOW,
        )
    assert pin.model_dump() == before


@pytest.mark.parametrize("zone", ["Not/A_Timezone", "../private", ""])
def test_T04_date_timezone_validation(zone):
    with pytest.raises(ValidationError):
        PlanRequest(date_only_timezones={"date-only": zone})


def test_T13_foreign_work_timezone_input_rejected():
    with pytest.raises(ValueError, match="outside this workload"):
        propose([dated()], PlanRequest(date_only_timezones={"other-user-work": "UTC"}), NOW)


@pytest.mark.parametrize(
    "day,zone", [(date(2011, 12, 30), "Pacific/Apia"), (date(2026, 3, 8), "America/Havana")]
)
def test_T04_skipped_date_or_nonexistent_midnight_stays_unresolved(day, zone):
    now = datetime.combine(day - timedelta(days=1), datetime.min.time(), UTC)
    timing = resolve_timing(dated(day), now, zone)
    assert timing.blocked == "source_date_boundary_unresolved"


def test_T04_repeated_midnight_uses_earliest_safe_boundary():
    timing = resolve_timing(dated(date(2026, 11, 1)), NOW, "America/Havana")
    assert timing.deadline == datetime(2026, 11, 1, 4, tzinfo=UTC)


@pytest.mark.parametrize("month,day,capacity", [(3, 8, 60), (11, 1, 180)])
def test_T04_T20_dst_capacity_uses_elapsed_minutes(month, day, capacity):
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, month, day, 1 if month == 3 else 0, 30, tzinfo=zone)
    end = datetime(2026, month, day, 3 if month == 3 else 2, 30, tzinfo=zone)
    item = task("dst", 180, end + timedelta(hours=1))
    result = propose([item], request_for(start, end), start)
    assert sum(b["minutes"] for b in result["blocks"]) == capacity
    assert result["known_shortfall_minutes"] == 180 - capacity
    for block in result["blocks"]:
        elapsed = datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])
        assert elapsed.total_seconds() == block["minutes"] * 60
    assert all(b["end"] <= end.astimezone(UTC).isoformat() for b in result["blocks"])


def test_T04_T20_fold_order_overlap_and_nonexistent_windows():
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 40, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 10, tzinfo=zone, fold=1)
    window = Window(start=first, end=second)
    assert (window.end - window.start).total_seconds() == 1800
    with pytest.raises(ValidationError):
        Window(start=second, end=first)
    with pytest.raises(ValidationError):
        Window(
            start=datetime(2026, 3, 8, 2, 30, tzinfo=zone),
            end=datetime(2026, 3, 8, 3, 30, tzinfo=zone),
        )


def test_T04_T20_dst_busy_time_and_breaks_conserve_capacity():
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
    end = datetime(2026, 11, 1, 2, 30, tzinfo=zone)
    busy = Window(
        start=datetime(2026, 11, 1, 1, 0, tzinfo=zone, fold=0),
        end=datetime(2026, 11, 1, 1, 0, tzinfo=zone, fold=1),
    )
    request = PlanRequest(
        windows=[Window(start=start, end=end)],
        busy_times=[busy],
        break_minutes=10,
        buffer_minutes=10,
    )
    result = propose([task("dst", 180, end + timedelta(hours=1))], request, start)
    assert sum(b["minutes"] for b in result["blocks"]) <= 110
    for block in result["blocks"]:
        assert block["end"] <= busy.start.isoformat() or block["start"] >= busy.end.isoformat()


def test_T20_overdue_recovery_retains_urgency_but_is_not_verified_feasible():
    item = task("late", 30, NOW - timedelta(hours=1))
    item.closes_at = FactDate(kind="timestamp", timestamp=NOW + timedelta(days=5))
    result = propose([item], request_for(), NOW)
    assert result["recommendations"][0]["urgency"] == "immediate"
    assert result["blocks"][0]["overdue_recovery"]
    assert result["feasibility"] == "provisional"


async def date_snapshot(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    course = next(c for c in courses if c.source_id == "11")
    bridge.select_courses(owner, seeded, [course.id], "UTC")
    row = deepcopy(bridge.synthetic.data["assignments"]["11"][0])
    row.update(due_at=(utcnow().date() + timedelta(days=2)).isoformat(), lock_at=None)
    bridge.synthetic.data["assignments"]["11"] = [row]
    snap = await bridge.refresh(owner, seeded)
    return snap, snap.items[0]["id"]


async def test_T04_T13_T20_snapshot_service_authorization_staleness_and_partial(
    bridge, owner, seeded
):
    snap, ref = await date_snapshot(bridge, owner, seeded)
    now = utcnow()
    request = request_for(
        now,
        now + timedelta(hours=2),
        effort_overrides={
            ref: {"minimum_minutes": 30, "maximum_minutes": 30, "origin": "student_estimate"}
        },
    )
    result = bridge.study_plan(owner, seeded, snap.id, request)
    assert not result.data["blocks"]
    request.date_only_timezones[ref] = "UTC"
    assert bridge.study_plan(owner, seeded, snap.id, request).data["blocks"]
    with pytest.raises(DomainError):
        bridge.study_plan("another-student", seeded, snap.id, request)
    with bridge.store.transaction() as session:
        session.get(Snapshot, snap.id).complete = False
    assert (
        bridge.study_plan(owner, seeded, snap.id, request).data["feasibility"] == "partial_workload"
    )
    with bridge.store.transaction() as session:
        session.get(Snapshot, snap.id).created_at = now - timedelta(minutes=6)
    with pytest.raises(DomainError, match="Refresh"):
        bridge.study_plan(owner, seeded, snap.id, request)
    bridge.select_courses(owner, seeded, [], "UTC")
    with pytest.raises(DomainError):
        bridge.study_plan(owner, seeded, snap.id, request)


async def test_T04_T20_calendar_composition_uses_same_date_boundaries(bridge, owner, seeded):
    snap, ref = await date_snapshot(bridge, owner, seeded)
    now = utcnow()
    calendar = context(availability_complete=True).model_copy(
        update={"retrieved_at": now, "window_start": now, "window_end": now + timedelta(days=7)}
    )
    request = request_for(
        now,
        now + timedelta(hours=2),
        effort_overrides={
            ref: {"minimum_minutes": 30, "maximum_minutes": 30, "origin": "student_estimate"}
        },
    )
    unknown = await propose_sync(bridge, owner, seeded, snap.id, calendar, request)
    assert unknown.data["study_plan"]["feasibility"] == "timing_unresolved"
    assert unknown.data["provider_writes_executed"] is False
    request.date_only_timezones[ref] = "America/New_York"
    result = await propose_sync(bridge, owner, seeded, snap.id, calendar, request)
    assert result.data["study_plan"]["blocks"]
    assert result.data["study_plan"]["timing_constraints"][ref]["source_due"]["timestamp"] is None
    request.date_only_timezones["foreign-work"] = "UTC"
    with pytest.raises(DomainError, match="outside this workload") as error:
        await propose_sync(bridge, owner, seeded, snap.id, calendar, request)
    assert error.value.status == "needs_input"


@pytest.mark.contract
async def test_T04_T20_T36_http_mcp_date_only_plan_keeps_source_and_unknowns(
    running, bridge, owner, seeded, token_factory
):
    snap, ref = await date_snapshot(bridge, owner, seeded)
    now = utcnow()
    request = request_for(
        now,
        now + timedelta(hours=2),
        effort_overrides={
            ref: {"minimum_minutes": 30, "maximum_minutes": 30, "origin": "student_estimate"}
        },
    )
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                args = {
                    "connection_id": seeded,
                    "snapshot_id": snap.id,
                    "request": request.model_dump(mode="json"),
                }
                missing = await session.call_tool("propose_study_plan", args)
                assert not missing.isError
                assert not missing.structuredContent["data"]["blocks"]
                args["request"]["date_only_timezones"] = {ref: "America/New_York"}
                result = await session.call_tool("propose_study_plan", args)
                data = result.structuredContent["data"]
                assert data["blocks"] and data["feasibility"] == "provisional"
                assert data["timing_constraints"][ref]["source_due"]["timestamp"] is None
                assert result.structuredContent["sources"][0]["url"].endswith("/assignments/1")
                args["request"]["date_only_timezones"] = {"outside-snapshot": "UTC"}
                denied = await session.call_tool("propose_study_plan", args)
                assert denied.structuredContent["status"] == "needs_input"
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
