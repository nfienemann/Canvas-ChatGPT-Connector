"""Additional constructions from the 24-case acceptance contract."""

from datetime import timedelta
from fractions import Fraction

import pytest

from canvas_bridge.academic.independent_models import IndependentAcademicInput
from canvas_bridge.analytics.independent import independent_review
from canvas_bridge.analytics.measurements import Action, Actual, Forecast, Schedule, Span
from canvas_bridge.analytics.observations import Due, History, Outcome
from canvas_bridge.analytics.report import build, restatement
from canvas_bridge.domain import FactDate, Source
from canvas_bridge.normalize import normalize_assignment
from tests.test_analytics_archive import corpus as corpus
from tests.test_analytics_archive import metric_map, staged, write_evidence
from tests.test_analytics_observations import NOW, review


def stamp(key, *, course="one", at=NOW, basis="provider_observation"):
    return dict(key=key, course_ids=[course], source_ref=key, observed_at=at, basis=basis)


def cohort(states, *, course="one"):
    h = History(coverage=[{"course_id": course, "state": "complete", "retrieved": len(states)}])
    for i, state in enumerate(states):
        st = stamp("parent-" + str(i), course=course)
        h.dues.append(Due(**st, due=FactDate(kind="timestamp", timestamp=NOW - timedelta(days=1))))
        h.outcomes.append(Outcome(**st, state=state))
    return h


def run(h, req=None):
    return build(h, req or review(), scope_binding="case", synthetic=True, now=NOW)


def family(report, name, p=0):
    return next(f for f in report["periods"][p]["families"] if f["metric_id"] == name)


def exact(family, metric, n, d):
    row = metric_map(family)[metric]
    assert (row["numerator"], row["denominator"]) == (n, d)
    assert row["sample_count"] == d


def archive(corpus, name):
    req, h, _ = staged(corpus[name][0])
    return req, h


def baseline(corpus):
    request, history = archive(corpus, "baseline")
    return run(history, request)[0]


def receipt(number, report, controls=None):
    write_evidence(
        f"ANL-T{number:02}", {"structured_report": report, "additional_controls": controls or {}}
    )


def test_deadline_counts(corpus):
    data = baseline(corpus)
    for i, n in enumerate([1, 0]):
        d = family(data, "deadline_outcomes", i)
        exact(d, "missed_rate", n, 3)
        assert d["counts"] == (
            {"on_time": 1, "late": 1, "missed": 1, "unknown": 1}
            if i == 0
            else {"on_time": 2, "late": 1, "missed": 0, "unknown": 1}
        )
    receipt(1, data)


def test_population_accounting():
    extra = {}
    h = cohort(["unknown"] * 4)
    h.dues += [
        Due(**stamp("excused"), due=h.dues[0].due, exclusion="excused"),
        Due(**stamp("optional"), due=h.dues[0].due, exclusion="optional"),
        Due(**stamp("undated"), due=FactDate()),
    ]
    data, _ = run(h)
    f = family(data, "deadline_outcomes")
    assert (f["eligible"], f["excluded"], f["unplaceable"], f["unknown"]) == (4, 2, 1, 4)
    assert "no_known_outcomes" in f["limitations"]
    extra["empty"] = run(cohort([]))[0]
    assert "no_applicable_items" in family(extra["empty"], "deadline_outcomes")["limitations"]
    receipt(2, data, extra)


def test_grade_and_offline_controls():
    extra = {}
    from canvas_bridge.analytics.observations import work_facts

    h = History(coverage=[{"course_id": "one", "state": "complete"}])
    for i, score in enumerate([None, 0, 7, None, 9]):
        due = NOW - timedelta(days=1)
        submission = {"user_id": 101, "score": score}
        if i == 3:
            submission["missing"] = True
        if i == 4:
            submission.update(submitted_at=due.isoformat(), workflow_state="submitted", late=False)
        item = normalize_assignment(
            {
                "id": i + 1,
                "submission": submission,
                "due_at": due.isoformat(),
                "submission_types": ["online_upload"],
                "description": "Draft feedback only.",
            },
            owner="o",
            connection="c",
            institution="synthetic",
            course="one",
            canvas_course="11",
            canvas_user="101",
            origin="https://fixture.invalid",
            now=NOW,
        )
        work_facts(h, item, "s", NOW)
    data, _ = run(h)
    d = family(data, "deadline_outcomes")
    exact(d, "missed_rate", 1, 2)
    assert d["unknown"] == 3
    item = item.model_copy(
        update={
            "submission_state": "not_applicable",
            "timeliness_state": "unknown",
            "submitted_at": None,
            "personal_progress": "student_marked_done",
        }
    )
    h = History(coverage=h.coverage)
    work_facts(h, item, "offline-snapshot", NOW)
    extra["offline"] = run(h)[0]
    assert family(extra["offline"], "deadline_outcomes")["unknown"] == 1
    exact(family(extra["offline"], "personal_completion"), "completion_rate", 1, 1)
    receipt(3, data, extra)


def test_dst_date_precision(corpus):
    extra = {}
    req, h = archive(corpus, "boundary_dst")
    data, members = run(h, req)
    assert [p["elapsed_hours"] * 60 for p in data["periods"]] == [10080, 10140]
    for field in ("previous", "current"):
        from tests.test_analytics_archive import expectation_view

        assert (
            expectation_view(data)["windows"][field]["deadline_outcomes"]
            == corpus["boundary_dst"][1]["windows"][field]["deadline_outcomes"]
        )
    h = cohort(["unknown"])
    h.dues[0].due = FactDate(kind="local_date", local_date=req.windows[0].start.date())
    w = req.windows[0].model_copy(update={"start": req.windows[0].start + timedelta(hours=12)})
    extra["partial_day"] = run(h, review(windows=[w]))[0]
    assert family(extra["partial_day"], "deadline_outcomes")["unplaceable"] == 1
    receipt(4, data, extra)


@pytest.mark.parametrize("number", (5, 6), ids=lambda n: f"ANL-T{n:02}")
def test_restatement_cutoffs(number):
    extra = {}
    req = review()
    cutoff = NOW + timedelta(days=1)
    h = cohort(["missing" if number == 5 else "unknown"])
    old, old_members = run(h)
    if number == 5:
        h.dues.append(
            h.dues[0].model_copy(
                update={
                    "version": 2,
                    "observed_at": cutoff,
                    "effective_at": NOW,
                    "due": FactDate(kind="timestamp", timestamp=NOW),
                }
            )
        )
    else:
        h.outcomes.append(
            h.outcomes[0].model_copy(
                update={"version": 2, "observed_at": cutoff, "effective_at": NOW, "state": "late"}
            )
        )
        h.outcomes.append(
            h.outcomes[0].model_copy(
                update={"version": 3, "observed_at": cutoff, "state": "missing"}
            )
        )
    data, new_members = run(h, req.model_copy(update={"evidence_cutoff": cutoff}))
    extra["prior"] = old
    extra["restatement"] = restatement(
        {"report": old, "populations": old_members}, data, new_members
    )
    assert run(h)[0]["report_id"] == old["report_id"] and data["report_id"] != old["report_id"]
    if number == 5:
        exact(family(old, "deadline_outcomes"), "missed_rate", 1, 1)
        exact(family(data, "deadline_outcomes"), "missed_rate", 0, 0)
        assert len(extra["restatement"]["cohort_changes"][0]["removed_from_window"]) == 1
    else:
        exact(family(old, "deadline_outcomes"), "missed_rate", 0, 0)
        exact(family(data, "deadline_outcomes"), "late_rate", 1, 1)
    receipt(number, data, extra)


def test_parent_aliases():
    extra = {}
    parents = [
        {
            "key": f"p{i}",
            "title": "Parent",
            "aliases": [f"alias{i}"],
            "due": {"kind": "timestamp", "timestamp": (NOW - timedelta(days=1)).isoformat()},
        }
        for i in range(3)
    ]
    children = [
        {
            "key": f"p{i}s{j}",
            "title": "Work step",
            "activity_kind": "study_step",
            "parent_key": f"p{i}",
        }
        for i in range(3)
        for j in range(6)
    ]
    row = {
        "work_key": "alias0",
        "version": 1,
        "recorded_at": NOW.isoformat(),
        "progress": "student_marked_done",
    }
    dataset = IndependentAcademicInput(
        schema_version="independent-academic-1",
        work=parents + children,
        complete=True,
        declarations=[row, row],
    )
    source = Source(
        id="one",
        url="",
        title="synthetic student declarations",
        retrieved_at=NOW,
        content_hash="a" * 64,
    )
    data, _ = independent_review(dataset, source, review(), "fixture", NOW)
    d = family(data, "personal_completion")
    assert (d["eligible"], d["excluded"], d["counts"]["student_marked_done"]) == (3, 18, 1)
    h = cohort(["missing"])
    other = cohort(["on_time"], course="two")
    h.dues += other.dues
    h.outcomes += other.outcomes
    h.coverage += other.coverage
    extra["same_id"] = run(h, review(course_ids=["one", "two"]))[0]
    assert family(extra["same_id"], "deadline_outcomes")["eligible"] == 2
    receipt(7, data, extra)


def test_personal_progress(corpus):
    data = baseline(corpus)
    for i, n in enumerate([2, 3]):
        f = family(data, "personal_completion", i)
        exact(f, "completion_rate", n, 3)
        assert f["unknown"] == 1
    receipt(8, data)


def test_progress_correction(corpus):
    data = baseline(corpus)
    extra = {}
    extra["prior"] = data
    req, h = archive(corpus, "progress_correction")
    data, _ = run(h, req)
    exact(family(extra["prior"], "personal_completion", 1), "completion_rate", 3, 3)
    exact(family(data, "personal_completion", 1), "completion_rate", 2, 3)
    assert (
        family(data, "deadline_outcomes", 1)["counts"]
        == family(extra["prior"], "deadline_outcomes", 1)["counts"]
    )
    receipt(9, data, extra)


@pytest.mark.parametrize("number", (10, 11, 12, 13), ids=lambda n: f"ANL-T{n:02}")
def test_schedule_snapshots(number):
    extra = {}
    origin = NOW - timedelta(days=1)

    def schedule(key, blocks, busy, state="accepted", busy_version="v1"):
        def spans(pairs):
            return [
                Span(
                    key=f"s{i}",
                    start=origin + timedelta(minutes=a),
                    end=origin + timedelta(minutes=b),
                )
                for i, (a, b) in enumerate(pairs)
            ]

        return Schedule(
            **stamp(key, basis=state + "_plan"),
            state=state,
            busy_version=busy_version,
            busy_coverage="complete",
            blocks=spans(blocks),
            busy=spans(busy),
        )

    def selected(s):
        h = History(schedules=s)
        return run(h)[0]

    def overlap(d, state=0):
        s = family(d, "schedule_conflicts")["snapshots"][state]
        return metric_map(s)["union_overlap_minutes"]["value"], s["affected_study_block_count"]

    if number == 10:
        data = selected([schedule("s", [(0, 90), (60, 120)], [(30, 75), (60, 105)])])
        assert overlap(data) == (75, 2)
    elif number == 11:
        extra["touching"] = selected([schedule("s", [(0, 60)], [(60, 120)])])
        assert overlap(extra["touching"]) == (0, 0)
        origin = datetime_from("2026-11-01T01:15:00-04:00")
        data = selected([schedule("dst", [(0, 60)], [(15, 75)])])
        assert overlap(data) == (45, 1)
    elif number == 12:
        before = schedule("before", [(0, 90)], [(0, 90)])
        after = schedule("after", [(60, 90)], [(0, 90)])
        extra["before"] = selected([before])
        data = selected([after])
        extra["changed_busy"] = selected([after.model_copy(update={"busy_version": "v2"})])
        assert overlap(extra["before"])[0] - overlap(data)[0] == 60
        assert (
            family(extra["changed_busy"], "schedule_conflicts")["snapshots"][0]["busy_version"]
            == "v2"
        )
    else:
        accepted = schedule("saved", [(0, 30), (60, 90)], [(15, 30), (60, 75)])
        proposed = schedule("draft", [(30, 60)], [(15, 30), (60, 75)], "proposed")
        data = selected([accepted, proposed, proposed])
        assert overlap(data) == (30, 2) and overlap(data, 1) == (0, 0)
    receipt(number, data, extra)


def test_calibration(corpus):
    data = baseline(corpus)
    for i, (inside, numerator) in enumerate([(1, 15), (3, -25)]):
        f = family(data, "effort_calibration", i)
        exact(f, "interval_coverage", inside, 3)
        exact(f, "budget_signed_error_minutes", numerator, 3)
        assert metric_map(f)["point_mae_minutes"]["value"] == [20, 10][i]
    receipt(14, data)


@pytest.mark.parametrize("number", (15, 16, 17), ids=lambda n: f"ANL-T{n:02}")
def test_recorded_work_phases(number):
    t = NOW - timedelta(days=2)
    common = stamp("f", at=t, basis="accepted_plan")
    unit = dict(parent="p", work_revision="v1", unit_id="u", scope_id="phase")
    f = Forecast(
        **common,
        **unit,
        scope_kind="remaining_work",
        minimum=20,
        maximum=40,
        budget=40,
        point=30,
        origin="student_estimate",
    )
    a = Actual(
        **(common | {"key": "a", "observed_at": NOW, "basis": "student_declaration"}),
        **unit,
        start=t,
        completion=t + timedelta(hours=2),
        minutes=0,
        completed=True,
        complete_duration=True,
        forecast_id="f",
    )
    if number == 15:
        h = History(forecasts=[f], actuals=[a, a.model_copy(update={"key": "b", "minutes": None})])
    else:
        f = f.model_copy(update={"minimum": 60, "maximum": 60, "budget": 60, "point": 60})
        a = a.model_copy(
            update={
                "minutes": 120,
                "baseline_at": t,
                "minutes_before_scope": 30,
                "duration_basis": "cumulative",
            }
        )
        h = History(forecasts=[f], actuals=[a])
        if number == 16:
            h.actuals.append(a.model_copy(update={"key": "b", "work_revision": "v2"}))
        else:
            h.forecasts.append(f.model_copy(update={"observed_at": NOW, "version": 2, "point": 90}))
    data, _ = run(h)
    ef = family(data, "effort_calibration")
    exact(ef, "point_mae_minutes", 30, 1)
    exact(ef, "budget_signed_error_minutes", -40 if number == 15 else 30, 1)
    if number == 16:
        assert ef["exclusions"] == [{"reason": "work_revision_mismatch", "count": 1}]
    receipt(number, data)


def test_coordination(corpus):
    data = baseline(corpus)
    for i, counts in enumerate([(4, 5, 2, 25), (3, 3, 3, 10)]):
        assert tuple(m["value"] for m in family(data, "coordination", i)["measures"][:4]) == counts
    receipt(18, data)


def test_action_replay():
    t = NOW - timedelta(hours=2)
    actions = []
    for kind, n, basis in [
        ("logical_request", 1, "system_diagnostic"),
        ("attempt", 3, "system_diagnostic"),
        ("confirmed_effect", 2, "confirmed_action_receipt"),
    ]:
        for i in range(n):
            actions.append(
                Action(
                    **stamp(kind + str(i), at=t, basis=basis),
                    effective_at=t,
                    kind=kind,
                    effect_key="op1" if kind == "confirmed_effect" else None,
                )
            )
    m = Action(
        **stamp("session", at=t, basis="student_declaration"),
        effective_at=t,
        kind="manual_session",
        manual_minutes=10,
    )
    m2 = m.model_copy(update={"version": 2, "manual_minutes": 8})
    data, _ = run(History(actions=[*actions, m, m2, m2]))
    assert [m["value"] for m in family(data, "coordination")["measures"][:4]] == [1, 3, 1, 8]
    receipt(19, data)


def test_descriptive_comparison(corpus):
    data = baseline(corpus)
    extra = {}
    changes = {(c["family"], c["metric_id"]): c for c in data["comparison"]}
    for k, expected in [
        (("deadline_outcomes", "missed_rate"), Fraction(-100, 3)),
        (("personal_completion", "completion_rate"), Fraction(100, 3)),
        (("accepted", "union_overlap_minutes"), -60),
        (("effort_calibration", "point_mae_minutes"), -10),
        (("coordination", "recorded_manual_minutes"), -15),
    ]:
        m = changes[k]
        assert Fraction(m["numerator"], m["denominator"]) == expected
    from canvas_bridge.analytics.report import compare

    zero = cohort(["on_time"])
    period = run(zero)[0]["periods"][0]
    extra["zero"] = next(c for c in compare(period, period) if c["metric_id"] == "missed_rate")
    assert extra["zero"]["value"] == 0 and extra["zero"]["relative_change_fraction"] is None
    receipt(20, data, extra)


def test_pooling():
    extra = {}
    h = cohort(["missing"])
    other = cohort(["on_time"] * 9, course="two")
    h.dues += other.dues
    h.outcomes += other.outcomes
    h.coverage += other.coverage
    data, _ = run(h, review(course_ids=["one", "two"]))
    d = family(data, "deadline_outcomes")
    exact(d, "missed_rate", 1, 10)
    assert [c["evaluated"] for c in d["by_course"]] == [1, 9]
    extra["one_course"] = run(cohort(["missing"]))[0]
    exact(family(extra["one_course"], "deadline_outcomes"), "missed_rate", 1, 1)
    receipt(21, data, extra)


def test_partial_results(corpus):
    req, h = archive(corpus, "baseline")
    h.actuals.clear()
    h.schedules = [s.model_copy(update={"busy_coverage": "partial"}) for s in h.schedules]
    data, _ = run(h, req)
    exact(family(data, "personal_completion", 1), "completion_rate", 3, 3)
    e = family(data, "effort_calibration", 1)
    assert (
        e["availability"] == "unavailable" and metric_map(e)["point_mae_minutes"]["value"] is None
    )
    s = family(data, "schedule_conflicts", 1)["snapshots"][0]
    assert s["availability"] == "partial" and metric_map(s)["union_overlap_minutes"]["value"] == 30
    receipt(22, data)


def test_bounded_collection():
    h = cohort(["missing", "on_time", "on_time", "unknown", "unknown"])
    h.coverage = [
        {
            "course_id": "one",
            "state": "partial",
            "retrieved": 5,
            "omitted_count": 3,
            "pagination_complete": False,
        }
    ]
    data, _ = run(h)
    f = family(data, "deadline_outcomes")
    exact(f, "missed_rate", 1, 3)
    assert (
        f["unknown"] == 2
        and f["full_scope_rate"] is None
        and data["inventory_coverage"][0]["omitted_count"] == 3
    )
    receipt(23, data)


def test_replay_traceability(corpus):
    data = baseline(corpus)
    r2, h2 = archive(corpus, "replay_reorder")
    assert data["report_id"] == run(h2, r2)[0]["report_id"]
    assert all(
        f["definition_version"] and f["source_basis"]
        for p in data["periods"]
        for f in p["families"]
    )
    receipt(24, data)


def datetime_from(value):
    from datetime import datetime

    return datetime.fromisoformat(value)
