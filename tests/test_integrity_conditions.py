"""Synthetic regressions for conditions on activity-specific AI permissions."""

import pytest

from canvas_bridge.integrity.engine import evaluate_academic_assistance as evaluate
from canvas_bridge.integrity.models import Activity as A
from canvas_bridge.integrity.models import State
from canvas_bridge.integrity.parser import parse
from tests.test_integrity_engine import policy


@pytest.mark.parametrize("assessment_id", [None, "fictional-assessment"])
@pytest.mark.parametrize(
    ("text", "activity"),
    [
        ("AI may be used for data analysis only if the work is unassessed.", A.ANALYSIS),
        ("AI may be used for research when the work is unassessed.", A.RESEARCH),
        ("AI may be used for feedback provided the draft is unassessed.", A.FEEDBACK),
        ("AI may be used for debugging if the work is not assessed.", A.DEBUG),
        ("AI may be used for an outline only if the work is ungraded.", A.OUTLINE),
        ("AI may be used to generate code when the exercise is unassessed.", A.CODE),
        ("AI may be used only for grammar if the work is unassessed.", A.GRAMMAR),
        ("AI may be used for brainstorming only if the work is unassessed.", A.BRAINSTORM),
        (
            "You may use AI to prepare for the exam, but not during the exam, if the work is unassessed.",
            A.EXAM_PREPARATION,
        ),
        ("AI is permitted if the work is unassessed.", A.DRAFT),
        (
            "AI may be used for data analysis only if the work is unassessed and properly cited.",
            A.ANALYSIS,
        ),
        ("AI may be used for data analysis if properly cited and unassessed.", A.ANALYSIS),
        ("AI may be used for data analysis only for unassessed work.", A.ANALYSIS),
        ("AI may be used for non-assessed data analysis.", A.ANALYSIS),
        ("AI may be used for data analysis subject to a tutor's review.", A.ANALYSIS),
        ("AI may be used for data analysis with supervisor review.", A.ANALYSIS),
        ("AI may be used for data analysis after completing the workshop.", A.ANALYSIS),
        (
            "AI may be used for data analysis if the instructor considers it appropriate.",
            A.ANALYSIS,
        ),
        ("AI may be used for data analysis if eligible, with citation.", A.ANALYSIS),
        ("AI may be used for data analysis, but not if properly cited.", A.ANALYSIS),
        ("AI may be used for data analysis conditional upon a tutor's review.", A.ANALYSIS),
    ],
)
def test_unresolved_allowance_conditions_require_review(text, activity, assessment_id):
    source = policy(text)
    rules = parse(source)
    assert not any(rule.effect == "allow" for rule in rules)
    review = [rule for rule in rules if rule.effect == "ambiguous"]
    assert review and all(rule.condition for rule in review)
    assert all(
        rule.passage == text
        and rule.source_id == source.id
        and rule.source_version == source.version
        and rule.locator == "Section 4"
        for rule in review
    )

    decision = evaluate(activity, [source], assessment_id=assessment_id)
    assert decision.state == State.REVIEW_REQUIRED
    assert not decision.allowed and not decision.permission_established
    assert not decision.acknowledgment_eligible
    acknowledgment = {
        "valid": True,
        "policy_version": decision.policy_version,
        "decision_version": decision.version,
        "activity": activity,
    }
    acknowledged = evaluate(
        activity, [source], assessment_id=assessment_id, acknowledgment=acknowledgment
    )
    assert not acknowledged.allowed and not acknowledged.permission_established


@pytest.mark.parametrize("assessment_id", [None, "fictional-assessment"])
@pytest.mark.parametrize(
    ("text", "activity"),
    [
        ("AI is permitted.", A.DRAFT),
        ("AI may be used for assessed data analysis.", A.ANALYSIS),
        ("AI may be used only for data analysis.", A.ANALYSIS),
        ("AI may be used for research assistance.", A.RESEARCH),
        ("AI may be used for feedback.", A.FEEDBACK),
        ("AI may be used for debugging.", A.DEBUG),
        ("AI may be used for brainstorming but not writing.", A.BRAINSTORM),
        ("AI may be used only for spelling and grammar.", A.GRAMMAR),
    ],
)
def test_unconditional_allowances_retain_activity_scope(text, activity, assessment_id):
    source = policy(text)
    decision = evaluate(activity, [source], assessment_id=assessment_id)
    assert decision.allowed and decision.permission_established
    if activity != A.DRAFT:
        outside_scope = evaluate(A.DRAFT, [source], assessment_id=assessment_id)
        assert not outside_scope.allowed and not outside_scope.permission_established
        assert not outside_scope.acknowledgment_eligible


@pytest.mark.parametrize(
    ("text", "activity"),
    [
        ("AI tools may be used if properly cited.", A.DRAFT),
        ("AI may be used for data analysis if properly cited.", A.ANALYSIS),
        ("AI may be used for brainstorming if properly cited.", A.BRAINSTORM),
        ("AI may be used only for grammar if properly cited.", A.GRAMMAR),
        ("AI may be used for data analysis with proper attribution.", A.ANALYSIS),
        ("AI may be used for data analysis provided that properly cited.", A.ANALYSIS),
    ],
)
def test_supported_disclosure_condition_is_retained(text, activity):
    decision = evaluate(activity, [policy(text)])
    assert decision.state == State.PERMITTED_CONDITIONAL
    assert decision.allowed and decision.permission_established
    assert any("Disclose" in condition for condition in decision.conditions)


@pytest.mark.parametrize("exam", [False, True])
def test_unresolved_exam_condition_cannot_be_filtered_out(exam):
    source = policy("AI may be used for data analysis only when not during the exam.")
    decision = evaluate(A.ANALYSIS, [source], exam=exam)
    assert decision.state == State.REVIEW_REQUIRED
    assert not decision.allowed and not decision.acknowledgment_eligible


def test_conditional_activity_scope_does_not_offer_an_acknowledgment_for_other_work():
    source = policy("AI may be used for data analysis if the work is unassessed.")
    decision = evaluate(A.DRAFT, [source])
    assert decision.state == State.REVIEW_REQUIRED
    assert not decision.allowed and not decision.acknowledgment_eligible
    for activity in (A.LEARNING, A.ADMINISTRATION, A.PLANNING):
        assert evaluate(activity, [source]).allowed


def test_conditional_allowance_respects_source_assessment_scope():
    source = policy(
        "AI may be used for data analysis only if the work is unassessed.",
        assessment_id="fictional-assessment",
    )
    for assessment_id, state in (
        ("fictional-assessment", State.REVIEW_REQUIRED),
        (None, State.POLICY_UNAVAILABLE),
        ("another-assessment", State.POLICY_UNAVAILABLE),
    ):
        decision = evaluate(A.ANALYSIS, [source], assessment_id=assessment_id)
        assert decision.state == state
        assert not decision.allowed and not decision.permission_established
        assert not decision.acknowledgment_eligible


@pytest.mark.parametrize(
    "text",
    [
        "AI is prohibited for data analysis.",
        "AI may not be used for data analysis.",
        "AI is prohibited. AI may be used for data analysis only if the work is unassessed.",
        "AI may be used for data analysis only if the work is unassessed. AI is prohibited.",
    ],
)
def test_conditional_allowances_never_weaken_explicit_prohibitions(text):
    decision = evaluate(A.ANALYSIS, [policy(text)])
    assert decision.state == State.PROHIBITED_CONFIRMED
    assert not decision.allowed and not decision.permission_established
    assert not decision.acknowledgment_eligible
