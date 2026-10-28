"""Negative controls for the fictional corpus repairs; no live institution."""

import pytest

from canvas_bridge.academic.grade_engine import GradeAssessment, GradeGroup, GradePolicy, calculate
from canvas_bridge.academic_rules import instruction_findings
from canvas_bridge.independent import bounded_table_structure
from canvas_bridge.integrity.engine import evaluate_academic_assistance as evaluate
from canvas_bridge.integrity.models import Activity as A
from tests.test_integrity_engine import policy


@pytest.mark.parametrize("activity", [A.DRAFT, A.OUTLINE, A.REWRITE, A.DELIVERABLE])
def test_enumerated_prohibition_keeps_assessed_outputs_denied(activity):
    source = policy(
        "AI may be used to brainstorm possible topics. AI must not draft submission prose, produce a substantive outline, rewrite the memo, or generate assessed diagrams."
    )
    assert evaluate(A.BRAINSTORM, [source]).allowed
    assert not evaluate(activity, [source]).allowed


@pytest.mark.parametrize(
    "text",
    [
        "AI may not be used for brainstorming.",
        "AI can brainstorm, but all AI use is banned.",
        "AI is only prohibited for spelling and grammar.",
        "AI must not correct spelling and grammar only.",
        "AI may correct spelling and grammar only with instructor permission.",
        "AI may be used for brainstorming. AI must not draft submission prose or assist in any other way.",
    ],
)
def test_negation_unknown_remainder_and_conditional_permission_do_not_grant(text):
    assert not evaluate(A.BRAINSTORM, [policy(text)]).allowed
    assert not evaluate(A.GRAMMAR, [policy(text)]).allowed


def test_mechanical_permission_never_grants_rewriting():
    source = policy("AI may correct spelling and grammar only.")
    assert evaluate(A.GRAMMAR, [source]).allowed
    assert not evaluate(A.REWRITE, [source]).allowed


def test_requirement_modifiers_and_citations_are_clause_scoped():
    text = "Require 1,200-1,500 words. Rubric requires 1,800-2,000 words. A figure is recommended, not mandatory."
    document = dict(
        id="fictional",
        url="",
        version="v1",
        source_type="local_document",
        course_id=None,
        retrieved_at="2026-10-28",
        complete=True,
        parts=[{"locator": "Section 1", "text": text}],
    )
    result = instruction_findings([document])
    assert result["conflicts"]
    figure = next(r for r in result["rules"] if r["type"] == "figure_requirement")
    assert not figure["mandatory"]
    for rule in result["rules"]:
        evidence = rule["evidence"]
        assert text[evidence["offset"] :].startswith(evidence["passage"])
    document["parts"][0]["text"] = (
        "Do not require 1,200-1,500 words. About 1,800 words is recommended."
    )
    assert not any(r["mandatory"] for r in instruction_findings([document])["rules"])


def test_percentage_drop_is_explicit_and_does_not_optimize_retained_grade():
    rows = [
        GradeAssessment(
            id=key, title=key, group_id="g", score=score, possible=possible, score_state="posted"
        )
        for key, score, possible in [("a", 1, 10), ("b", 20, 100), ("c", 100, 100)]
    ]
    group = GradeGroup(id="g", name="g", drop_lowest=1)
    source = GradePolicy(method="points", groups=[group])
    assert calculate(source, rows)["calculated_percentage"] is None
    explicit = source.model_copy(
        update={"groups": [group.model_copy(update={"drop_basis": "percentage"})]}
    )
    result = calculate(explicit, rows)
    # Dropping b would maximize the final grade, but the declared rule drops a.
    assert result["calculated_percentage"] == "60.0000"
    assert result["excluded_assessments"] == [{"id": "a", "reason": "drop_lowest_percentage"}]
    protected = explicit.model_copy(
        update={"groups": [explicit.groups[0].model_copy(update={"never_drop": ["a"]})]}
    )
    assert calculate(protected, rows)["excluded_assessments"][0]["id"] == "b"
    rows[0] = GradeAssessment.model_validate({**rows[0].model_dump(), "possible": 0})
    assert calculate(explicit, rows)["calculated_percentage"] is None


def test_oversized_table_omits_whole_structure_and_reports_incompleteness():
    result = bounded_table_structure(
        {
            "tables": [
                {
                    "cells": [{"row": 1, "column": 1, "text": "x" * 12000}],
                    "structure_complete": True,
                }
            ]
        }
    )
    assert result["tables"] == []
    assert result["limitations"]
    assert result["visual_inspection_status"] == "not_performed"


@pytest.mark.parametrize("different", [{"section": "B"}, {"subject": "student-2"}])
def test_amendments_cannot_cross_sections_or_subjects(different):
    from canvas_bridge.processes.evidence import reconcile
    from tests.test_process_evidence import NOW, claim

    old = claim()
    scope = old.coverage.source.scope.model_copy(update={"section": "A", "subject": "student-1"})
    source = old.coverage.source.model_copy(update={"scope": scope})
    old = old.model_copy(update={"coverage": old.coverage.model_copy(update={"source": source})})
    amended_source = source.model_copy(update={"scope": scope.model_copy(update=different)})
    amendment = claim("amendment", "2030-10-12", supersedes=(old.id,))
    amendment = amendment.model_copy(
        update={"coverage": amendment.coverage.model_copy(update={"source": amended_source})}
    )
    with pytest.raises(ValueError, match="exact scope"):
        reconcile([old, amendment], now=NOW)
