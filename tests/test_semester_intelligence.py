"""Entirely fictional semester scenarios and negative authorization cases."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge.domain import DomainError, Effort, FactDate, Source, WorkItem
from canvas_bridge.semester import acknowledge, overview, verified_weights
from canvas_bridge.semester_engine import analyze
from canvas_bridge.semester_models import (
    NotificationPreferences,
    SemesterPreferences,
    SemesterRequest,
)
from canvas_bridge.semester_notifications import delivery_receipt_state, notification_decision
from canvas_bridge.source_authorization import LocalPreferences
from canvas_bridge.storage import Job, LocalRecord
from tests.test_academic_intelligence import academic as academic
from tests.test_grade_audit import grade_data as grade_data
from tests.test_grade_audit import graded, policy
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def work(ident="a", course="course-a", hours=24, **changes):
    data = dict(
        id=ident,
        connection_id="connection",
        institution_id="synthetic",
        course_id=course,
        source_id=ident,
        title="Fictional assessment " + ident,
        effective_due=FactDate(kind="timestamp", timestamp=NOW + timedelta(hours=hours))
        if hours is not None
        else FactDate(),
        submission_state="not_submitted",
        submission_evidence="returned",
        availability_state="available",
        instruction_hash="a" * 64,
        instruction_state="present",
        source=Source(
            id=ident,
            url="https://canvas.synthetic.invalid/assignments/" + ident,
            title="Fictional source",
            retrieved_at=NOW,
            content_hash="a" * 64,
            course_id=course,
        ),
    )
    return WorkItem(**(data | changes))


def snap(items, ident="current", complete=True, when=NOW):
    return SimpleNamespace(
        id=ident,
        owner="fictional-owner",
        connection_id="connection",
        course_ids=sorted({i.course_id for i in items}),
        complete=complete,
        items=[i.model_dump(mode="json") for i in items],
        created_at=when,
    )


def run(items, baseline=None, **kw):
    return analyze(
        snap(items),
        baseline,
        now=NOW,
        start=NOW - timedelta(days=30),
        end=NOW + timedelta(days=120),
        timezone="America/New_York",
        **kw,
    )


def test_twelve_courses_multiple_deadlines_consistent_priorities_and_traceability():
    items = [work(str(i), "course-" + str(i), hours=12 + i) for i in range(12)]
    report = run(items)
    assert len(report["current_obligations"]) == 12
    assert len([f for f in report["findings"] if f["kind"] == "deadline_cluster"]) == 1
    assert all(f["evidence"] and f["next_action"] for f in report["findings"])
    assert all(f["priority"]["verified_weight_percent"] is None for f in report["findings"])
    assert [f["issue_key"] for f in report["findings"]] == [
        f["issue_key"] for f in run(list(reversed(items)))["findings"]
    ]
    assert report["history_status"] == "incomplete_historical_comparison"
    assert not any(f["lifecycle"] == "confirmed_newly_observed_change" for f in report["findings"])


def test_unknown_time_and_unknown_submission_do_not_become_overdue_or_grade_loss():
    report = run(
        [
            work("unknown", hours=None),
            work("old", hours=-12, submission_state="unknown", submission_evidence="not_returned"),
        ]
    )
    assert all(f["priority"]["tier"] == 4 for f in report["findings"])
    assert not any(f["kind"] == "overdue_work" for f in report["findings"])
    assert all(f["academic_consequence"] is None for f in report["findings"])


def test_repeated_snapshots_are_deduplicated_and_not_new():
    item = work()
    baseline = snap([item], "baseline", when=NOW - timedelta(hours=1))
    one = run([item], baseline)
    two = run([item], snap([item], "another", when=NOW - timedelta(minutes=1)))
    assert [(f["issue_key"], f["finding_revision"]) for f in one["findings"]] == [
        (f["issue_key"], f["finding_revision"]) for f in two["findings"]
    ]
    assert not any(
        f["evidence_status"] == "confirmed_newly_observed_change" for f in two["findings"]
    )


def test_late_date_and_instruction_revision_have_both_observations():
    old = work(hours=96)
    current = work(hours=12, instruction_hash="b" * 64)
    report = run([current], snap([old], "before", when=NOW - timedelta(days=1)))
    changes = [
        f for f in report["findings"] if f["evidence_status"] == "confirmed_newly_observed_change"
    ]
    assert {f["kind"] for f in changes} == {"assessment_date_changed", "requirements_changed"}
    assert all(len(f["evidence"]) == 2 for f in changes)
    renamed = work(title="Corrected spelling")
    assert not any(
        f["evidence_status"] == "confirmed_newly_observed_change"
        for f in run([renamed], snap([work()], "before", when=NOW - timedelta(days=1)))["findings"]
    )


def test_acknowledgment_survives_repeat_but_changed_due_requires_review():
    report = run([work()])
    first = report["findings"][0]
    ack = {first["issue_key"]: first["finding_revision"]}
    same = run([work()], acknowledgements=ack)
    assert same["findings"][0]["acknowledged"] and not same["recommended_priorities"]
    assert not run([work(hours=4)], acknowledgements=ack)["findings"][0]["acknowledged"]


def test_resolved_cluster_requires_completeness_and_current_access():
    before = snap([work("a"), work("b", hours=30)], "before", when=NOW - timedelta(hours=1))
    after = [work("a"), work("b", hours=200)]
    result = run(after, before)
    assert any(
        f["kind"] == "deadline_cluster" and f["lifecycle"] == "resolved_finding"
        for f in result["findings"]
    )
    before.complete = False
    assert not any(f["lifecycle"] == "resolved_finding" for f in run(after, before)["findings"])
    before.complete = True
    assert not any(
        f["lifecycle"] == "resolved_finding" for f in run([work("a")], before)["findings"]
    )


def test_missing_dependency_is_uncertain_not_a_fabricated_missing_file():
    report = run([work(prerequisites=["unavailable-material"], prerequisite_coverage="known")])
    f = next(f for f in report["findings"] if f["kind"] == "prerequisite_needs_review")
    assert f["evidence_status"] == "uncertain" and f["priority"]["tier"] == 4


def test_known_estimates_and_user_windows_support_conditional_shortfall():
    estimate = Effort(
        minimum_minutes=120, maximum_minutes=180, origin="student_estimate", as_of=NOW
    )
    prefs = SemesterPreferences(available_windows=[{"start": NOW, "end": NOW + timedelta(hours=1)}])
    result = run([work(effort_remaining=estimate)], preferences=prefs)
    f = next(f for f in result["findings"] if f["kind"] == "availability_shortfall")
    assert (
        f["details"]["available_minutes"] == 60
        and f["evidence_status"] == "conditional_on_user_inputs"
    )
    estimate.origin = "assistant_estimate"
    assert not any(
        f["kind"] == "availability_shortfall"
        for f in run([work(effort_remaining=estimate)], preferences=prefs)["findings"]
    )


def test_timezone_transition_uses_elapsed_instants_and_unknown_date_has_no_hour():
    due = datetime.fromisoformat("2026-11-01T01:30:00-05:00")
    report = run(
        [
            work(effective_due=FactDate(kind="timestamp", timestamp=due)),
            work("date", effective_due=FactDate(kind="local_date", local_date=due.date())),
        ]
    )
    by_kind = {f["kind"]: f for f in report["findings"]}
    assert by_kind["upcoming_deadline"]["priority"]["hours_until_reported_date"] == 18.5
    assert by_kind["uncertain_timing"]["priority"]["hours_until_reported_date"] is None


def test_unknown_or_dropped_grade_weights_are_not_reconstructed():
    p = policy(True)
    raw = {"policy": p, "assessments": [graded(), graded("b", "lab")], "complete": True}
    result = verified_weights(raw)
    assert result["a"]["percent"] == 70
    p.groups[0].weight = None
    assert verified_weights(raw) == {}
    p.groups[0].weight = Decimal(70)
    p.groups[0].drop_lowest = 1
    assert verified_weights(raw) == {}


def test_notifications_require_opt_in_host_scope_quiet_hours_and_frequency():
    report = run([work()])
    preferences = NotificationPreferences()
    assert (
        notification_decision(report, preferences, NOW, "UTC", approved_host=True)["delivery_state"]
        == "not_requested"
    )
    preferences = NotificationPreferences(opted_in=True, course_ids=["course-a"], frequency="daily")
    assert (
        notification_decision(report, preferences, NOW, "UTC")["delivery_state"]
        == "approved_host_schedule_required"
    )
    decision = notification_decision(report, preferences, NOW, "UTC", approved_host=True)
    assert decision["eligible_findings"] and not decision["active"]
    saved = delivery_receipt_state(
        {}, decision, provider_receipt="fictional-provider-receipt", delivered_at=NOW
    )
    duplicate = notification_decision(
        report | {"analysis_as_of": (NOW + timedelta(days=2)).isoformat()},
        preferences,
        NOW + timedelta(days=2),
        "UTC",
        delivered=saved["delivered"],
        approved_host=True,
    )
    assert (
        duplicate["delivery_state"] == "no_new_actionable_findings"
        and duplicate["deduplicated_count"]
    )
    assert (
        notification_decision(
            report,
            preferences,
            NOW + timedelta(hours=1),
            "UTC",
            last_delivery=saved["last_delivery"],
            approved_host=True,
        )["delivery_state"]
        == "frequency_limit"
    )
    assert (
        notification_decision(report, preferences, NOW.replace(hour=23), "UTC", approved_host=True)[
            "delivery_state"
        ]
        == "quiet_hours"
    )
    preferences.course_ids = ["other-course"]
    assert not notification_decision(report, preferences, NOW, "UTC", approved_host=True)[
        "eligible_findings"
    ]
    with pytest.raises(ValueError):
        delivery_receipt_state({}, decision, provider_receipt=None, delivered_at=NOW)


def test_preferences_reject_protected_traits_and_require_explicit_notification_scope():
    with pytest.raises(ValidationError):
        SemesterPreferences(health_condition="inferred")
    with pytest.raises(ValidationError):
        NotificationPreferences(opted_in=True)
    assert "semester" not in LocalPreferences().validated()
    pref = LocalPreferences(semester={"workload_tolerance_minutes_per_day": 90})
    assert pref.validated()["semester"]["workload_tolerance_minutes_per_day"] == 90


async def test_overview_all_selected_no_jobs_and_acknowledgment_is_explicit(bridge, owner, seeded):
    first = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    assert first.data["background_monitoring"] is False
    assert len(first.data["courses"]) == len(bridge.selected(owner, seeded)[1])
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Job)))
        assert not list(
            session.scalars(select(LocalRecord).where(LocalRecord.kind == "semester_state"))
        )
    f = first.data["findings"][0]
    await acknowledge(bridge, owner, seeded, first.data["acknowledgment_receipt"], [f["issue_key"]])
    second = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    assert next(x for x in second.data["findings"] if x["issue_key"] == f["issue_key"])[
        "acknowledged"
    ]
    with pytest.raises(DomainError, match="Acknowledgments changed"):
        await acknowledge(
            bridge, owner, seeded, first.data["acknowledgment_receipt"], [f["issue_key"]]
        )


async def test_revocation_during_analysis_and_foreign_ack_are_denied(
    bridge, owner, seeded, monkeypatch
):
    first = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    with pytest.raises(DomainError):
        await acknowledge(
            bridge,
            "other-owner",
            seeded,
            first.data["acknowledgment_receipt"],
            [first.data["findings"][0]["issue_key"]],
        )
    original = bridge.refresh_course_access
    calls = 0

    async def revoked(*args, **kw):
        nonlocal calls
        calls += 1
        if calls > 1:
            bridge.select_courses(owner, seeded, [], "UTC")
        return await original(*args, **kw)

    monkeypatch.setattr(bridge, "refresh_course_access", revoked)
    with pytest.raises(DomainError):
        await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))


async def test_syllabus_deadline_conflict_and_grade_uncertainty(bridge, owner, seeded, academic):
    bridge.synthetic.data["assignments"]["11"][0]["due_at"] = "2026-11-15T18:00:00Z"
    result = await overview(bridge, owner, seeded, SemesterRequest(course_ids=[academic.id]))
    assert any(f["kind"] == "conflicting_deadlines" for f in result.data["findings"])
    assert result.data["grade_positions"]
    assert any(f["kind"] == "grade_projection_uncertainty" for f in result.data["findings"])


def test_partial_history_suspects_changes_without_claiming_new_events_or_resolution():
    before = snap([work(hours=96)], "before", complete=False, when=NOW - timedelta(hours=1))
    result = run([work(hours=6), work("new")], before)
    changes = [f for f in result["findings"] if f["kind"] == "assessment_date_changed"]
    assert changes and changes[0]["lifecycle"] == "unverified_suspected_change"
    assert changes[0]["priority"]["tier"] == 4
    assert not any(f["kind"] == "newly_observed_assessment" for f in result["findings"])
    assert not any(f["lifecycle"] == "resolved_finding" for f in result["findings"])


@pytest.mark.parametrize("new_hours", [None, 24 * 200])
def test_unknown_or_out_of_window_dates_do_not_resolve_conflicts(new_hours):
    before = snap([work("a"), work("b", hours=26)], "before", when=NOW - timedelta(hours=1))
    result = run([work("a"), work("b", hours=new_hours)], before)
    assert not any(
        f["kind"] == "deadline_cluster" and f["lifecycle"] == "resolved_finding"
        for f in result["findings"]
    )


def test_saved_plan_conflict_and_verified_deadline_resolution():
    block = {
        "work_id": "a",
        "start": (NOW + timedelta(hours=20)).isoformat(),
        "end": (NOW + timedelta(hours=21)).isoformat(),
    }
    plans = [{"proposal": {"blocks": [block]}}]
    assert any(
        f["kind"] == "study_plan_conflict" for f in run([work(hours=12)], plans=plans)["findings"]
    )
    before = snap([work(hours=12)], "before", when=NOW - timedelta(hours=1))
    result = run([work(hours=48)], before, plans=plans)
    assert any(
        f["kind"] == "study_plan_conflict" and f["lifecycle"] == "resolved_finding"
        for f in result["findings"]
    )
    assert any(f["kind"] == "study_plan_needs_revision" for f in result["findings"])


def test_daily_workload_tolerance_and_preferred_periods_do_not_invent_availability():
    from canvas_bridge.planning import Window
    from canvas_bridge.semester_engine import availability

    start = datetime.fromisoformat("2026-11-01T00:00:00-04:00")
    end = datetime.fromisoformat("2026-11-01T04:00:00-05:00")
    prefs = SemesterPreferences(
        available_windows=[Window(start=start, end=end)],
        workload_tolerance_minutes_per_day=180,
        preferred_study_periods=[{"weekdays": [6], "start": "09:00", "end": "12:00"}],
    )
    assert availability(prefs, [], start, end, "America/New_York") == 180
    prefs.workload_tolerance_minutes_per_day = None
    assert availability(prefs, [], start, end, "America/New_York") == 300
    prefs.available_windows = []
    assert availability(prefs, [], start, end, "America/New_York") == 0
    f = run([work()], preferences=prefs)["findings"][0]
    assert "preferred periods alone are not free time" in f["next_action"]


def test_old_report_cannot_trigger_delivery_and_acknowledged_findings_are_suppressed():
    prefs = NotificationPreferences(opted_in=True, course_ids=["course-a"], frequency="daily")
    report = run([work()])
    assert (
        notification_decision(report, prefs, NOW + timedelta(minutes=6), "UTC", approved_host=True)[
            "delivery_state"
        ]
        == "fresh_authorized_analysis_required"
    )
    first = report["findings"][0]
    acknowledged = run([work()], acknowledgements={first["issue_key"]: first["finding_revision"]})
    assert not notification_decision(acknowledged, prefs, NOW, "UTC", approved_host=True)[
        "eligible_findings"
    ]


async def test_scope_epoch_checked_inside_acknowledgment_write(bridge, owner, seeded, monkeypatch):
    result = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    original = bridge.store.save_local

    def concurrent_change(*args, **kw):
        bridge.select_courses(owner, seeded, [], "UTC")
        return original(*args, **kw)

    monkeypatch.setattr(bridge.store, "save_local", concurrent_change)
    with pytest.raises(DomainError):
        await acknowledge(
            bridge,
            owner,
            seeded,
            result.data["acknowledgment_receipt"],
            [result.data["findings"][0]["issue_key"]],
        )
    with bridge.store.transaction() as session:
        assert not list(
            session.scalars(select(LocalRecord).where(LocalRecord.kind == "semester_state"))
        )


async def test_expired_receipt_and_unacknowledgment(bridge, owner, seeded):
    result = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    key = result.data["findings"][0]["issue_key"]
    proof = bridge.vault.open(result.data["acknowledgment_receipt"], owner, seeded)
    expired = bridge.vault.seal(proof | {"expires": "2000-01-01T00:00:00+00:00"}, owner, seeded)
    with pytest.raises(DomainError):
        await acknowledge(bridge, owner, seeded, expired, [key])
    await acknowledge(bridge, owner, seeded, result.data["acknowledgment_receipt"], [key])
    result = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    await acknowledge(bridge, owner, seeded, result.data["acknowledgment_receipt"], [key], False)
    result = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    assert not next(f for f in result.data["findings"] if f["issue_key"] == key)["acknowledged"]


async def test_visible_module_requirement_missing_prerequisite_preserves_unknown(
    bridge, owner, seeded, academic
):
    bridge.synthetic.data["modules"] = {
        "11": [
            {
                "id": 21,
                "name": "Fictional advanced laboratory",
                "published": True,
                "state": "unlocked",
                "prerequisite_module_ids": [22, 23],
            },
            {
                "id": 22,
                "name": "RESTRICTED TITLE DO NOT DISCLOSE",
                "published": True,
                "state": "locked",
            },
        ]
    }
    result = await overview(bridge, owner, seeded, SemesterRequest(course_ids=[academic.id]))
    item = next(
        f for f in result.data["findings"] if f["kind"] == "prerequisite_material_unavailable"
    )
    assert item["details"]["unavailable_prerequisite_count"] == 2
    assert item["priority"]["tier"] == 4 and item["evidence"]
    assert "RESTRICTED TITLE" not in result.model_dump_json()


async def test_semester_mcp_wire_preserves_evidence_preferences_and_ack_receipt(
    running,
    bridge,
    owner,
    seeded,
    token_factory,
):
    async with client_session(running, token_factory()) as session:
        catalog = {t.name: t for t in (await session.list_tools()).tools}
        assert catalog["get_semester_overview"].annotations.readOnlyHint
        assert not catalog["acknowledge_semester_findings"].annotations.readOnlyHint
        pref = await session.call_tool(
            "update_local_study_preferences",
            {
                "preferences": {
                    "timezone": "America/New_York",
                    "semester": {
                        "workload_tolerance_minutes_per_day": 120,
                        "preferred_study_periods": [
                            {"weekdays": [0, 1], "start": "18:00", "end": "20:00"}
                        ],
                    },
                },
                "expected_version": 0,
            },
        )
        assert pref.structuredContent["status"] == "ok", pref.structuredContent
        result = await session.call_tool(
            "get_semester_overview",
            {"connection_id": seeded, "request": {"include_course_evidence": False}},
        )
        assert result.structuredContent["status"] == "partial_data", result.structuredContent
        data = result.structuredContent["data"]
        assert data["planning_preferences"]["workload_tolerance_minutes_per_day"] == 120
        assert data["analysis_window"]["timezone"] == "America/New_York"
        assert data["notifications"]["delivery_state"] == "not_requested"
        f = data["findings"][0]
        assert f["evidence"] and f["priority"]["basis"] and f["finding_revision"]
        ack = await session.call_tool(
            "acknowledge_semester_findings",
            {
                "connection_id": seeded,
                "acknowledgment_receipt": data["acknowledgment_receipt"],
                "issue_keys": [f["issue_key"]],
            },
        )
        assert ack.structuredContent["status"] == "ok", ack.structuredContent
        assert ack.structuredContent["data"]["version"] == 1
    async with client_session(running, token_factory(scope="academic:read")) as session:
        denied = await session.call_tool(
            "acknowledge_semester_findings",
            {
                "connection_id": seeded,
                "acknowledgment_receipt": data["acknowledgment_receipt"],
                "issue_keys": [f["issue_key"]],
            },
        )
        assert denied.structuredContent["status"] == "permission_denied"


async def test_restricted_source_cannot_leave_in_aggregate(
    running, bridge, owner, seeded, token_factory
):
    from canvas_bridge.egress_models import ContentClassification

    snapshot = await bridge.refresh(owner, seeded)
    ident = snapshot.items[0]["id"]
    bridge.synthetic.egress_contexts = {
        ident: {"classification": ContentClassification.RESTRICTED_ASSESSMENT}
    }
    async with client_session(running, token_factory()) as session:
        result = await session.call_tool(
            "get_semester_overview",
            {"connection_id": seeded, "request": {"include_course_evidence": False}},
        )
        assert result.structuredContent["status"] == "permission_denied", result.structuredContent
        assert "findings" not in result.structuredContent["data"]
        assert "acknowledgment_receipt" not in result.structuredContent["data"]


async def test_legacy_preferences_and_scope_withdrawal_state_cleanup(bridge, owner, seeded):
    bridge.store.save_local(
        owner,
        seeded,
        "preferences",
        "default",
        {"timezone": "America/Chicago", "semester": {"workload_tolerance_minutes_per_day": 45}},
        0,
    )
    result = await overview(bridge, owner, seeded, SemesterRequest(include_course_evidence=False))
    assert result.data["analysis_window"]["timezone"] == "America/Chicago"
    assert result.data["planning_preferences"]["workload_tolerance_minutes_per_day"] == 45
    await acknowledge(
        bridge,
        owner,
        seeded,
        result.data["acknowledgment_receipt"],
        [result.data["findings"][0]["issue_key"]],
    )
    bridge.select_courses(owner, seeded, [], "UTC")
    with bridge.store.transaction() as session:
        assert not list(
            session.scalars(select(LocalRecord).where(LocalRecord.kind == "semester_state"))
        )
        assert session.scalar(select(LocalRecord).where(LocalRecord.kind == "preferences"))


def test_lost_submission_evidence_never_resolves_overdue_warning():
    before = snap([work(hours=-12)], "before", when=NOW - timedelta(hours=1))
    result = run(
        [work(hours=-12, submission_state="unknown", submission_evidence="not_returned")], before
    )
    assert not any(
        f["kind"] == "overdue_work" and f["lifecycle"] == "resolved_finding"
        for f in result["findings"]
    )
    assert any(f["kind"] == "uncertain_completion" for f in result["findings"])


def test_distinct_conflicting_dates_can_be_acknowledged_independently():
    from canvas_bridge.semester_engine import finding

    def conflict(day):
        return finding(
            "conflicting_deadlines",
            ["course-a"],
            ["a"],
            "Fictional conflict",
            {"source_date": f"2026-11-{day}"},
            [work().source.model_dump(mode="json")],
            "Verify applicability.",
            status="source_difference_applicability_unverified",
        )

    first, second = conflict(12), conflict(14)
    assert first["issue_key"] != second["issue_key"]
    result = run(
        [work()],
        supplemental=[first, second],
        acknowledgements={first["issue_key"]: first["finding_revision"]},
    )
    assert next(f for f in result["findings"] if f["issue_key"] == first["issue_key"])[
        "acknowledged"
    ]
    assert not next(f for f in result["findings"] if f["issue_key"] == second["issue_key"])[
        "acknowledged"
    ]


async def test_bounded_report_keeps_all_returned_ephemeral_sources(
    bridge, owner, seeded, monkeypatch
):
    from canvas_bridge.evidence import attach
    from canvas_bridge.semester_engine import finding

    async def many_sources(bridge, owner, ref, course, snapshot_items, timezone):
        sources = [
            Source(
                id=f"module-{n}-{course.id}",
                url=f"https://canvas.synthetic.invalid/courses/{course.source_id}/modules",
                title="Fictional module",
                course_id=course.id,
                source_type="module_requirement",
                content_hash="a" * 64,
                retrieved_at=NOW,
            )
            for n in range(120)
        ]
        found = [
            finding(
                "prerequisite_material_unavailable",
                [course.id],
                [],
                "Fictional prerequisite",
                {"module_id": source.id},
                [source.model_dump(mode="json")],
                "Verify access.",
                status="uncertain",
            )
            for source in sources
        ]
        return found, {}, {"coverage": "fictional bounded module requirements"}, sources

    monkeypatch.setattr("canvas_bridge.semester.course_evidence", many_sources)
    result = await overview(bridge, owner, seeded)
    ephemeral = {
        e["id"]
        for f in result.data["findings"]
        for e in f["evidence"]
        if e.get("source_type") == "module_requirement"
    }
    assert ephemeral <= {s.id for s in result.sources}
    assert result.data["coverage_counts"]["returned_findings"] == 60
    assert result.data["coverage_counts"]["total_findings"] > 200
    assert len(attach(result).model_dump_json().encode()) < 250_000


async def test_native_grade_position_and_weight_discrepancies_are_source_bounded(
    bridge,
    owner,
    seeded,
    grade_data,
):
    result = await overview(bridge, owner, seeded, SemesterRequest(course_ids=[grade_data]))
    position = result.data["grade_positions"][0]
    assert Decimal(str(position["calculation"]["calculated_percentage"])) == Decimal(86)
    differences = [f for f in result.data["findings"] if f["kind"] == "grade_weighting_discrepancy"]
    assert len(differences) == 2
    assert all(
        f["evidence_status"] == "source_difference_applicability_unverified" for f in differences
    )
    assert all(len(f["evidence"]) == 2 and f["academic_consequence"] is None for f in differences)


def test_verified_major_cluster_and_completed_plan_suppression():
    result = run(
        [work("a"), work("b", "course-b", hours=36)],
        weights={"a": {"percent": 25}, "b": {"percent": 15}},
    )
    cluster = next(f for f in result["findings"] if f["kind"] == "major_assessment_cluster")
    assert len(cluster["work_ids"]) == 2
    completed = work(submission_state="submitted", submission_evidence="returned")
    plans = [
        {
            "proposal": {
                "blocks": [
                    {
                        "work_id": "a",
                        "start": (NOW + timedelta(hours=48)).isoformat(),
                        "end": (NOW + timedelta(hours=49)).isoformat(),
                    }
                ]
            }
        }
    ]
    assert not any(
        f["kind"] == "study_plan_conflict" for f in run([completed], plans=plans)["findings"]
    )
