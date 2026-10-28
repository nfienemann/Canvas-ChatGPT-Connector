"""Credential-free reasoning over normalized input with an active authorization receipt."""

from canvas_bridge.academic.evidence_adapters import dataset_builder, grade_inputs
from canvas_bridge.academic.grade_engine import calculate
from canvas_bridge.domain import DomainError


def calculate_grade(gateway, authorized, *, mode="current_graded", scenario=None):
    dataset = gateway.consume(authorized)
    if dataset.grading_rules is None or len(dataset.courses) != 1:
        raise DomainError("unsupported_feature", "A single-course grading policy is required.")
    builder, course, parents = dataset_builder(dataset)
    inputs = builder.build()
    policy, assessments = grade_inputs(inputs)
    result = calculate(policy, assessments, mode, scenario, evidence_complete=inputs.complete)
    builder.assert_fact(
        course,
        "grade_calculation",
        result,
        parents=parents,
        basis="calculated",
        uncertainty=("Arithmetic result is not instructor policy verification.",),
    )
    graph = builder.build()
    gateway.release(authorized)
    return {
        "schema_version": "academic-result-1",
        "calculation": result,
        "evidence_graph": graph.view(),
        "sources": [r.provenance.model_dump(mode="json") for r in dataset.records()],
        "restrictions": [r.restrictions.model_dump(mode="json") for r in dataset.records()],
        "complete": dataset.complete,
        "limitations": list(dataset.limitations),
        "verification": "arithmetic_only_not_instructor_policy_verification",
    }


def document_text(gateway, authorized):
    dataset = gateway.consume(authorized)
    if not dataset.documents:
        raise DomainError("unsupported_feature", "Authorized document evidence is required.")
    gateway.release(authorized)
    return {
        "schema_version": "academic-result-1",
        "documents": [d.model_dump(mode="json") for d in dataset.documents],
        "complete": dataset.complete,
        "limitations": list(dataset.limitations),
        "verification": "extracted_text_not_visual_interpretation",
    }
