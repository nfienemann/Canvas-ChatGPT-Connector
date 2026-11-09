"""Regression cases for completion, pin conflicts, scope and effort accounting."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from canvas_bridge.academic.independent_engine import analyze, work_items
from canvas_bridge.academic.independent_models import IndependentAcademicInput, IndependentRequest
from canvas_bridge.academic.study_steps import calendar_items, review_step_evidence, step_parents
from canvas_bridge.planning import PlanRequest, propose
from tests.test_domain_planning import NOW, task


def dataset(rows):
    return IndependentAcademicInput(schema_version="independent-academic-1", work=rows)


def window(minutes):
    return {"start": NOW, "end": NOW + timedelta(minutes=minutes)}


def effort(minutes):
    return {
        "minimum_minutes": minutes,
        "maximum_minutes": minutes,
        "origin": "student_estimate",
        "as_of": NOW,
    }


@pytest.mark.parametrize(
    ("progress", "revision", "minutes"),
    [
        ("student_marked_done", False, 0),
        ("in_progress", False, 12),
        ("student_marked_done", True, 12),
        ("unknown", False, 12),
    ],
)
def test_local_edges_follow_current_reported_remaining_effort(progress, revision, minutes):
    due = {"kind": "timestamp", "timestamp": NOW + timedelta(days=1)}
    data = dataset(
        [
            {"key": "memo", "title": "Memo", "due": due},
            {
                "key": "analysis",
                "title": "Analysis",
                "parent_key": "memo",
                "activity_kind": "study_step",
                "effort": effort(12),
                "progress": progress,
                "revision_requested": revision,
            },
            {
                "key": "write",
                "title": "Write",
                "effort": effort(30),
                "prerequisites": ["analysis"],
                "parent_key": "memo",
                "activity_kind": "study_step",
            },
        ]
    )
    source = task("source").source
    request = IndependentRequest(
        capability="planning",
        dataset={"document_id": source.id, "expected_hash": "0" * 64},
        plan={"windows": [window(90)], "break_minutes": 0, "buffer_minutes": 0},
    )
    plan, _ = analyze(request, data, source, [], owner="fixture", now=NOW)
    assert plan["effort_summary"]["known_remaining_minutes"] == 30 + minutes
    assert plan["effort_summary"]["completed_work_ids"] == ([] if minutes else ["analysis"])
    assert [b["work_id"] for b in plan["blocks"]] == (
        ["analysis", "write"] if minutes else ["write"]
    )
    assert plan["work_accounting"]["memo"]["reason"] == "planned_in_study_steps"
    assert all(w.submission_state == "unknown" for w in work_items(data, source))


def test_only_individually_conflicting_pins_are_withheld_and_restored():
    analysis, write = task("analysis", 30), task("write", 35)
    write.prerequisites = ["analysis"]
    pins = [
        {
            "work_id": "write",
            "start": NOW + timedelta(minutes=start),
            "end": NOW + timedelta(minutes=end),
        }
        for start, end in [(15, 30), (75, 95)]
    ]
    plan = PlanRequest(windows=[window(120)], pinned_blocks=pins, break_minutes=0, buffer_minutes=0)
    blocked = propose([analysis, write], plan, NOW)
    assert [p["reason"] for p in blocked["pin_conflicts"]] == [
        "prerequisite_finishes_after_pin_starts"
    ]
    assert [p["minutes"] for p in blocked["blocks"] if p["pinned"]] == [20]
    assert blocked["effort_summary"]["dependency_blocked_minutes"] == 15
    analysis.personal_progress = "student_marked_done"
    analysis.independent_personal_work = True
    repaired = propose([analysis, write], plan, NOW)
    assert repaired["pin_conflicts"] == [] and sum(p["minutes"] for p in repaired["blocks"]) == 35
    assert all(p["pinned"] for p in repaired["blocks"])


def test_unavailable_and_elapsed_work_never_resolve_edges():
    a, b = task("a", 20), task("b", 15)
    b.prerequisites = ["a"]
    a.availability_state = "inaccessible"
    plan = propose([a, b], PlanRequest(windows=[window(60)]), NOW)
    assert not plan["blocks"] and not plan["effort_summary"]["completed_work_ids"]
    assert plan["effort_summary"]["dependency_blocked_minutes"] == 15
    assert plan["effort_summary"]["other_unallocated_minutes"] == 20
    b.prerequisites = []
    b.personal_progress = "student_marked_done"
    result = propose([b, task("unknown")], PlanRequest(), NOW)
    assert result["effort_summary"]["receipt_verification_work_ids"] == ["b"]
    assert result["effort_summary"]["unknown_effort_work_ids"] == ["unknown"]


def test_unestimated_and_oversized_pins_do_not_inflate_work_balance():
    a, b = task("a", 10), task("b")
    pins = [
        {
            "work_id": key,
            "start": NOW + timedelta(minutes=start),
            "end": NOW + timedelta(minutes=start + 30),
        }
        for key, start in [("a", 0), ("b", 30)]
    ]
    plan = propose(
        [a, b],
        PlanRequest(windows=[window(60)], pinned_blocks=pins, buffer_minutes=0, break_minutes=0),
        NOW,
    )
    stats = plan["effort_summary"]
    assert stats["known_remaining_minutes"] == stats["allocated_work_minutes"] == 10
    assert stats["uncredited_block_minutes"] == 50 and stats["unknown_effort_work_ids"] == ["b"]


def test_distinct_dated_children_and_ambiguous_legacy_cutoffs():
    due = {"kind": "timestamp", "timestamp": NOW + timedelta(days=1)}
    data = dataset(
        [
            {"key": "post", "title": "Post", "due": due},
            {
                "key": "reply",
                "title": "Reply",
                "due": due,
                "parent_key": "post",
                "activity_kind": "reply",
            },
            {"key": "ABC123-A01-S1", "title": "ABC123-A01 / Review", "due": due},
            {"key": "ABC123-A01-S2", "title": "ABC123-A01 / Draft"},
            {"key": "ABC123-A02-S1", "title": "A separate assignment", "due": due},
        ]
    )
    items, provisional = calendar_items(work_items(data, task("s").source), step_parents(data))
    assert {x.id for x in items} == {"post", "reply", "ABC123-A01", "ABC123-A02-S1"}
    assert provisional == ["ABC123-A01"]
    assert next(x.effective_due.kind for x in items if x.id == "ABC123-A01") == "not_returned"
    with pytest.raises(ValidationError, match="inherit"):
        dataset(
            [
                {"key": "post", "title": "Post"},
                {
                    "key": "x",
                    "title": "X",
                    "activity_kind": "study_step",
                    "parent_key": "post",
                    "due": due,
                },
            ]
        )


def test_cited_step_checks_parent_hash_passage_and_offset():
    doc = {
        "id": "brief",
        "version": "1" * 64,
        "parts": [{"locator": "Part 1", "text": "ABC123-A01 | ABC123 | memo\nStudy skills."}],
    }
    anchor = {
        "document_id": "brief",
        "locator": "Part 1",
        "content_hash": doc["version"],
        "quote": "Study skills.",
    }
    data = dataset(
        [
            {"key": "ABC123-A01", "title": "Memo"},
            {"key": "ABC123-A02", "title": "Quiz"},
            {
                "key": "review",
                "title": "Review",
                "activity_kind": "study_step",
                "parent_key": "ABC123-A01",
                "evidence": [anchor],
            },
        ]
    )
    assert review_step_evidence(data, [doc])[0]["status"] == "cited_passages_located"
    for bad in (
        {"quote": "Different text"},
        {"content_hash": "2" * 64},
        {"start": 0},
        {"document_id": "other"},
    ):
        data.work[-1].evidence = [{**anchor, **bad}]
        assert review_step_evidence(data, [doc])[0]["evidence"] == []
    data.work[-1].evidence = [anchor]
    data.work[-1].parent_key = "ABC123-A02"
    assert review_step_evidence(data, [doc])[0]["status"] == "source_review_required"
