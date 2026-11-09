"""Exact supplied synthetic histories through Stage 6 projection, storage and HTTP MCP.

Set BRIDGE_TEST_ANALYTICS_ZIP to the original specification ZIP to run the archive
checks. BRIDGE_TEST_ANALYTICS_OUTPUT optionally retains synthetic requests and results.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.analytics.measurements import (
    Action,
    Actual,
    Forecast,
    Instrumentation,
    Schedule,
    Span,
)
from canvas_bridge.analytics.observations import Declaration, Due, History, Outcome, Period, Review
from canvas_bridge.analytics.report import build
from canvas_bridge.analytics.storage import store_observation
from canvas_bridge.domain import FactDate
from canvas_bridge.normalize import normalize_assignment
from canvas_bridge.storage import Snapshot
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session

ARCHIVE = "91c493d36496f5145025c1207058f7ae91e18833fad6690e10d4a8243db1b33f"


@pytest.fixture
def corpus():
    name = os.getenv("BRIDGE_TEST_ANALYTICS_ZIP")
    if not name:
        pytest.skip("Set BRIDGE_TEST_ANALYTICS_ZIP to the Stage 6 specification ZIP.")
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == ARCHIVE
    with ZipFile(name) as z:
        root = "stage6_analytics/fixtures/"
        expected = json.loads(z.read(root + "expected.json"))["cases"]
        return {
            k: (json.loads(z.read(root + "cases/" + k + ".json")), v) for k, v in expected.items()
        }


def write_evidence(name, data):
    if output := os.getenv("BRIDGE_TEST_ANALYTICS_OUTPUT"):
        target = Path(output)
        target.mkdir(exist_ok=True, parents=True)
        (target / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")


def staged(f, *, owner="fixture", ref="fixture", course_map=None):
    course_map = course_map or {c: c for c in f["scope"]["course_ids"]}
    courses = sorted(course_map.values())
    rr = f["request"]
    req = Review(
        course_ids=courses,
        windows=[Period(**{k: v for k, v in w.items() if k != "id"}) for w in rr["windows"]],
        as_of=rr["as_of"],
        evidence_cutoff=rr["evidence_cutoff"],
        timezone=f["scope"]["timezone"],
    )
    h = History(coverage=[{"course_id": c, "state": "complete"} for c in courses])
    parents, native = {}, {}

    def stamp(row, ids, basis, temporal, key=None):
        return dict(
            key=key or row["record_id"],
            version=row["revision"],
            course_ids=ids,
            observed_at=row["observed_at"],
            effective_at=row.get(temporal),
            source_ref=row["record_id"],
            basis=basis,
        )

    for assignment in f["assignments"]:
        name = assignment["assignment_id"]
        course = course_map[assignment["course_id"]]
        # The real normalizer generates a course-qualified canonical ID even for the same raw ID.
        source_id = int(name.split("FX")[-1])
        item = normalize_assignment(
            {
                "id": source_id,
                "name": name,
                "submission_types": ["online_upload"],
                "published": True,
                "locked_for_user": False,
            },
            owner=owner,
            connection=ref,
            institution="synthetic",
            course=course,
            canvas_course=str(11 + f["scope"]["course_ids"].index(assignment["course_id"])),
            canvas_user="101",
            origin="https://canvas.fixture.invalid",
            now=datetime.fromisoformat("2026-10-18T08:00:00-04:00"),
        )
        parents[name] = (course, item.id)
        native[item.id] = item
        h.bindings.add((course, item.id, item.source.content_hash))
        for r in assignment["due_records"]:
            due = (
                FactDate(kind="timestamp", timestamp=r["due_at"])
                if r["due_at"] and r["resolution"] == "resolved"
                else FactDate()
            )
            h.dues.append(
                Due(**stamp(r, [course], "provider_observation", "effective_at", item.id), due=due)
            )
        for r in assignment["outcome_records"]:
            h.outcomes.append(
                Outcome(
                    **stamp(r, [course], "provider_observation", "effective_at", item.id),
                    state={"timestamp_observation": "unknown", "missed": "missing"}.get(
                        r["timeliness"], r["timeliness"]
                    ),
                    submitted_at=r.get("submitted_at"),
                )
            )
        for r in assignment["progress_records"]:
            h.progress.append(
                Declaration(
                    **stamp(r, [course], "student_declaration", "occurred_at", item.id),
                    status="student_marked_done" if r["state"] == "complete" else r["state"],
                )
            )
    for r in f["forecasts"]:
        course, parent = parents[r["assignment_id"]]
        h.forecasts.append(
            Forecast(
                **stamp(r, [course], "accepted_plan", "frozen_at"),
                parent=parent,
                work_revision=r["work_revision"],
                unit_id=r["work_unit_id"],
                scope_id=r["scope_id"],
                scope_kind=r["scope_kind"],
                minimum=r["minimum_minutes"],
                maximum=r["maximum_minutes"],
                budget=r["planning_budget_minutes"],
                point=r.get("point_estimate_minutes"),
                origin="synthetic_frozen_forecast",
            )
        )
    for r in f["effort_observations"]:
        course, parent = parents[r["assignment_id"]]
        h.actuals.append(
            Actual(
                **stamp(r, [course], "student_declaration", "completed_at"),
                parent=parent,
                work_revision=r["work_revision"],
                unit_id=r["work_unit_id"],
                scope_id=r["scope_id"],
                forecast_id=r["forecast_id"],
                start=r["started_at"],
                completion=r["completed_at"],
                completed=r["completed"],
                complete_duration=r["completed"],
                minutes=r["actual_minutes"],
            )
        )
    for r in f["schedule_snapshots"]:
        state = r["snapshot_kind"]

        def spans(rows):
            return [Span(key=s["id"], start=s["start"], end=s["end"]) for s in rows]

        h.schedules.append(
            Schedule(
                **stamp(r, courses, state + "_plan", "captured_at"),
                state=state,
                busy_version="busy-" + r["record_id"],
                busy_coverage="complete"
                if r["busy_coverage"] == "complete_for_fixture_snapshot"
                else r["busy_coverage"],
                blocks=spans(r["study_blocks"]),
                busy=spans(r["busy_events"]),
            )
        )
    for field, kind in [
        ("coordination_requests", "logical_request"),
        ("coordination_attempts", "attempt"),
        ("effect_receipts", "confirmed_effect"),
        ("manual_sessions", "manual_session"),
    ]:
        for r in f[field]:
            if kind == "confirmed_effect" and r["result"] != "confirmed":
                continue
            basis = {
                "manual_session": "student_declaration",
                "confirmed_effect": "confirmed_action_receipt",
            }.get(kind, "system_diagnostic")
            h.actions.append(
                Action(
                    **stamp(r, courses, basis, "occurred_at"),
                    kind=kind,
                    effect_key=r.get("effect_key"),
                    manual_minutes=r.get("minutes"),
                )
            )
        if kind != "manual_session":
            h.instrumentation.append(
                Instrumentation(
                    key=kind,
                    observed_at=req.as_of,
                    source_ref="synthetic-collection",
                    course_ids=courses,
                    basis="system_diagnostic",
                    collection=kind,
                    start=req.windows[0].start,
                    end=req.windows[-1].end,
                )
            )
    return req, h, native


def metric_map(family):
    return {m["metric_id"]: m for m in family.get("measures", [])}


def expectation_view(report):
    """Translate names/units only; observations and arithmetic come from the product."""
    out = {}
    for tag, p in zip(("previous", "current"), report["periods"], strict=True):
        d, c, s, e, a = p["families"]
        dm, cm, em, am = map(metric_map, (d, c, e, a))
        snapshots = {}
        for snap in s["snapshots"]:
            measures = metric_map(snap)
            snapshots[snap["state"]] = {
                "union_overlap_minutes": measures.get("union_overlap_minutes", {}).get("value"),
                "study_union_minutes": measures.get("study_union_minutes", {}).get("value"),
                "affected_study_block_count": snap.get("affected_study_block_count"),
                "study_block_count": snap.get("study_block_count"),
                "busy_coverage": "complete_for_fixture_snapshot"
                if snap.get("busy_coverage") == "complete"
                else snap.get("busy_coverage", "unavailable"),
            }
        out[tag] = {
            "window_elapsed_hours": p["elapsed_hours"],
            "deadline_outcomes": {
                "eligible_parent_count": d["eligible"],
                **d["counts"],
                "known_outcome_count": d["evaluated"],
                "missed_rate": dm["missed_rate"]["value"],
                "coverage": dm["observation_coverage"]["value"],
            },
            "personal_completion": {
                "eligible_parent_count": c["eligible"],
                "complete": c["counts"]["student_marked_done"],
                "incomplete": c["counts"]["in_progress"] + c["counts"]["not_started"],
                "unknown": c["unknown"],
                "known_state_count": c["evaluated"],
                "completion_rate": cm["completion_rate"]["value"],
                "coverage": cm["observation_coverage"]["value"],
            },
            "schedule_conflicts": snapshots,
            "effort_calibration": {
                "completed_scope_count": e["eligible"],
                "paired_scope_count": e["evaluated"],
                **{k: m["value"] for k, m in em.items()},
                "interval_covered_count": em["interval_coverage"]["numerator"],
                "point_pair_count": em["point_mae_minutes"]["sample_count"],
                "budget_pair_count": em["budget_signed_error_minutes"]["sample_count"],
                "zero_actual_pair_count": e["zero_actual_pair_count"],
                "unfinished_scope_count": e["unfinished_scope_count"],
                "exclusions": {x["reason"]: x["count"] for x in e["exclusions"]},
            },
            "coordination": {
                "logical_request_count": am["logical_requests"]["value"],
                "attempt_count": am["attempts"]["value"],
                "distinct_confirmed_effect_count": am["confirmed_effects"]["value"],
                "manual_session_count": a["manual_session_count"],
                "manual_duration_known_count": am["manual_duration_coverage"]["numerator"],
                "recorded_manual_minutes": am["recorded_manual_minutes"]["value"],
                "manual_duration_coverage": am["manual_duration_coverage"]["value"],
            },
        }
    pooled = report["pooled_deadline_outcomes"]
    return {
        "windows": out,
        "pooled_deadline_outcomes": {
            "eligible_parent_count": pooled["eligible"],
            "known_outcome_count": pooled["denominator"],
            "missed": pooled["numerator"],
            "missed_rate": pooled["value"],
            "coverage": pooled["observation_coverage"]["value"],
        },
        "unplaced_deadline_parent_count": d["unplaceable"],
        "unplaced_completed_effort_count": e["unplaceable"],
    }


def check(expected, actual):
    if isinstance(expected, dict):
        for k, v in expected.items():
            assert k in actual, k
            check(v, actual[k])
    else:
        assert expected == actual


def test_supplied_scenarios(corpus):
    reports = {}
    for name, (fixture, expected) in corpus.items():
        req, h, _ = staged(fixture)
        report, _ = build(h, req, scope_binding="synthetic", synthetic=True, now=req.as_of)
        view = expectation_view(report)
        write_evidence(
            "scenario-" + name, {"request": req.model_dump(mode="json"), "report": report}
        )
        check(expected, view)
        reports[name] = report
    assert reports["replay_reorder"]["report_id"] == reports["baseline"]["report_id"]


@pytest.mark.parametrize(
    "scenario", ["baseline", "partial_observations", "correction_after_cutoff"]
)
async def test_supplied_http_baseline(
    corpus, running, bridge, owner, seeded, token_factory, scenario
):
    fixture, expected = corpus[scenario]
    from copy import deepcopy

    third = deepcopy(bridge.synthetic.data["courses"][0])
    third.update(id=13, name="Synthetic third course")
    bridge.synthetic.data["courses"].append(third)
    courses = await bridge.list_courses(owner, seeded)
    ids = [r["id"] for r in courses.data["courses"]]
    bridge.select_courses(owner, seeded, ids, "UTC")
    req, h, items = staged(
        fixture,
        owner=owner,
        ref=seeded,
        course_map=dict(zip(fixture["scope"]["course_ids"], ids, strict=True)),
    )
    with bridge.store.transaction() as session:
        session.add(
            Snapshot(
                id="synthetic-inventory",
                owner=owner,
                connection_id=seeded,
                complete=True,
                course_ids=ids,
                workload_scope={"kind": "source_inventory"},
                coverage=[],
                items=[i.model_dump(mode="json") for i in items.values()],
                created_at=datetime.fromisoformat("2026-10-18T08:00:00-04:00"),
            )
        )
        for kind, values in (
            ("due", h.dues),
            ("outcome", h.outcomes),
            ("progress", h.progress),
            ("forecast", h.forecasts),
            ("schedule", h.schedules),
            ("actual", h.actuals),
            ("action", h.actions),
            ("instrumentation", h.instrumentation),
        ):
            for fact in values:
                store_observation(session, owner, seeded, kind, fact)
    args = {"connection_id": seeded, "request": req.model_dump(mode="json")}
    async with client_session(running, token_factory(), read_timeout=90) as session:
        baseline = None
        for label in ("baseline", "repeat", "single"):
            if label == "single":
                args["request"]["windows"] = args["request"]["windows"][-1:]
            body = (await session.call_tool("get_academic_analytics", args)).structuredContent
            write_evidence(
                ("http-" if scenario == "baseline" else "http-" + scenario + "-") + label,
                {"tool": "get_academic_analytics", "arguments": args, "result": body},
            )
            assert body and body["status"] in {"ok", "partial_data"}, str(body)[:600]
            if label == "single":
                assert body["data"]["periods"][0] == baseline["periods"][1]
            else:
                check(expected, expectation_view(body["data"]))
                if label == "repeat":
                    assert body["data"]["report_id"] == baseline["report_id"]
                baseline = body["data"]
