from datetime import timedelta

from canvas_bridge.analytics.academic_metrics import due_metrics, schedule_metric
from canvas_bridge.analytics.measurements import Schedule, Span
from canvas_bridge.analytics.observations import Declaration, Due, History, Outcome
from canvas_bridge.domain import FactDate
from tests.test_analytics_observations import NOW, review


def test_offline_unknown_excused_and_cutoff():
    req = review()
    h = History(coverage=[{"course_id": "one", "state": "complete"}])
    stamp = dict(
        key="offline",
        observed_at=NOW,
        course_ids=["one"],
        source_ref="s",
        basis="provider_observation",
    )
    due = FactDate(kind="timestamp", timestamp=NOW - timedelta(days=1))
    h.dues = [Due(**stamp, due=due), Due(**(stamp | {"key": "exc"}), due=due, exclusion="excused")]
    h.progress = [
        Declaration(**(stamp | {"basis": "student_declaration"}), status="student_marked_done")
    ]
    metrics, _ = due_metrics(h, req, req.windows[0])
    assert metrics[0]["unknown"] == 1 and metrics[0]["measures"][0]["value"] is None
    assert metrics[1]["measures"][0]["value"] == 1 and metrics[0]["excluded"] == 1
    h.outcomes = [Outcome(**stamp, state="unknown", submitted_at=due.timestamp)]
    assert due_metrics(h, req, req.windows[0])[0][0]["counts"]["on_time"] == 1


def test_union_and_touching_endpoints():
    req = review()
    t = NOW - timedelta(days=1)

    def span(key, a, b):
        return Span(key=key, start=t + timedelta(minutes=a), end=t + timedelta(minutes=b))

    s = Schedule(
        key="s",
        observed_at=t,
        course_ids=["one"],
        source_ref="a",
        basis="accepted_plan",
        state="accepted",
        busy_version="v",
        busy_coverage="complete",
        blocks=[span("a", 0, 90), span("b", 60, 120)],
        busy=[span("c", 30, 75), span("d", 60, 105), span("e", 120, 135)],
    )
    result = schedule_metric(History(schedules=[s, s]), req, req.windows[0])["snapshots"][0]
    assert [m["value"] for m in result["measures"]] == [75, 120, 75 / 120]
    assert result["affected_study_block_count"] == 2 and result["internal_clash"]


def test_scope_errors_and_zero_actual():
    from canvas_bridge.analytics.activity_metrics import effort_metric
    from canvas_bridge.analytics.measurements import Actual, Forecast

    req = review()
    old = NOW - timedelta(days=4)
    common = dict(
        course_ids=["one"], source_ref="v1", observed_at=old, key="f", basis="accepted_plan"
    )
    unit = dict(parent="p", work_revision="v1", unit_id="unit", scope_id="phase")
    f = Forecast(
        **common,
        **unit,
        origin="student_estimate",
        minimum=20,
        maximum=40,
        budget=40,
        point=30,
        scope_kind="remaining_work",
    )
    a = Actual(
        **(common | {"key": "a", "basis": "student_declaration", "observed_at": NOW}),
        **unit,
        start=old,
        completion=old + timedelta(hours=1),
        minutes=0,
        completed=True,
        complete_duration=True,
        forecast_id="f",
    )
    h = History(
        forecasts=[f], actuals=[a, a, a.model_copy(update={"key": "b", "work_revision": "v2"})]
    )
    result = effort_metric(h, req, req.windows[0])
    assert result["zero_actual_pair_count"] == 1 and result["eligible"] == 2
    assert [m["value"] for m in result["measures"]] == [0.5, 0, -40, 40, 30, -30]


def test_manual_correction_and_effect_identity():
    from canvas_bridge.analytics.activity_metrics import coordination_metric
    from canvas_bridge.analytics.measurements import Action

    t = NOW - timedelta(days=1)
    stamp = dict(
        course_ids=["one"],
        source_ref="manual",
        observed_at=t,
        effective_at=t,
        key="m",
        basis="student_declaration",
    )
    first = Action(**stamp, kind="manual_session", manual_minutes=10)
    second = first.model_copy(update={"version": 2, "manual_minutes": 8})
    receipt = Action(
        **(stamp | {"key": "r", "basis": "confirmed_action_receipt"}),
        kind="confirmed_effect",
        effect_key="op",
    )
    h = History(actions=[first, second, second, receipt, receipt.model_copy(update={"key": "r2"})])
    r = coordination_metric(h, review(), review().windows[0])
    assert [m["value"] for m in r["measures"]] == [None, None, 1, 8, 1, None]
