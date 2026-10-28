"""Pure reasoning. No Bridge, credentials, storage, provider or network calls."""

from canvas_bridge.academic.grade_engine import GradePolicy, calculate, digest
from canvas_bridge.academic_rules import (
    citation,
    deadline_findings,
    instruction_findings,
    repeated_concepts,
)
from canvas_bridge.calendar_sync import calendar_proposal
from canvas_bridge.domain import DomainError, WorkItem
from canvas_bridge.planning import PlanRequest, propose


def work_items(dataset, source):
    return [
        WorkItem(
            id=w.key,
            connection_id="",
            institution_id="",
            course_id=source.id,
            source_id=w.key,
            title=w.title,
            effective_due=w.due,
            personal_progress=w.progress,
            effort_remaining=w.effort,
            prerequisites=w.prerequisites,
            prerequisite_coverage="known",
            source=source.model_copy(update={"locator": "Work " + w.key}),
            submission_state_basis="Independent input; no LMS submission evidence.",
        )
        for w in dataset.work
    ]


def bounded_excerpts(documents):
    """Shared assessment excerpt accounting for every source adapter."""
    remaining, excerpts = 16_000, []
    for doc in documents:
        for part in doc["parts"]:
            text = part["text"][: min(4000, remaining)]
            if text:
                excerpts.append(
                    {
                        **citation(doc, part, text),
                        "text": text,
                        "truncated": len(text) < len(part["text"]),
                    }
                )
                remaining -= len(text)
    return excerpts


def assessment_evidence(documents, description=None):
    """Explicit user-selected coverage, bounded excerpts; no inferred exam scope."""
    return {
        "assessment_description": description,
        "assessment_basis": "user_selected_scope_not_instructor_verified",
        "material_excerpts": bounded_excerpts(documents),
        "repeated_concepts": repeated_concepts(documents),
        "coverage_status": "selected_excerpts_only",
        "figure_interpretation": "not_performed",
        "limitations": [
            "Selected passages are not comprehensive assessment coverage. Relevance needs review."
        ],
    }


def grade_result(grades, source, request):
    if grades is None:
        raise DomainError(
            "needs_input",
            "The selected input has no grading records.",
            reason_code="INDEPENDENT_GRADES_MISSING",
        )
    policy = GradePolicy(
        basis="syllabus" if grades.policy_origin == "syllabus_interpretation" else "student_input",
        method=grades.method,
        groups=grades.groups,
        blockers=list(grades.unsupported_rules),
        rule_ids=[digest(rule) for rule in grades.rules],
        version=digest([source.content_hash, grades.model_dump(mode="json")]),
    )
    if policy.basis == "syllabus":
        review = request.policy_review
        if not (
            review
            and review.policy_version == policy.version
            and review.complete_policy_confirmed
            and review.applicability_confirmed
            and set(review.confirmed_rule_ids) == set(policy.rule_ids)
        ):
            policy.blockers.append(
                "Review the exact syllabus interpretation, rules and applicability before calculation."
            )
        elif review:
            policy.empty_categories = review.empty_categories
    assessments = [
        a.model_copy(update={"source_version": source.content_hash}) for a in grades.assessments
    ]
    result = calculate(
        policy, assessments, request.grade_mode, request.scenario, evidence_complete=grades.complete
    )
    return {
        "calculation": result,
        "policy": policy.model_dump(mode="json"),
        "grade_source": "independently_supplied_not_lms_reported",
        "policy_verification": "student_review_not_instructor_verification",
    }


def analyze(request, dataset, source, documents, *, owner, now):
    items = work_items(dataset, source) if dataset and source else []
    capability = request.capability
    if capability == "planning":
        if not items:
            raise DomainError(
                "needs_input",
                "Supply independent work items before planning.",
                reason_code="INDEPENDENT_WORK_MISSING",
            )
        data = propose(items, request.plan or PlanRequest(), now)
        return data, not dataset.complete or data["information_status"] != "sufficient"
    if capability == "grades":
        data = grade_result(dataset.grades, source, request)
        return data, bool(data["calculation"]["missing_information"])
    if capability == "calendar":
        if not request.calendar:
            raise DomainError(
                "needs_input",
                "Read the existing authorized calendar and supply current event coverage; missing calendar information is unknown.",
                reason_code="INDEPENDENT_CALENDAR_MISSING",
            )
        data = calendar_proposal(
            items, request.calendar, owner, "", now, source_label="Independent"
        )
        return data, not dataset.complete or data["status"] != "proposal_only" or bool(
            data["ambiguous_matches"]
        )
    if capability == "assessment":
        return assessment_evidence(documents, request.assessment_description), True
    data = {}
    if capability in {"requirements", "consistency"}:
        drafts = [p["text"] for d in documents if d["role"] == "draft" for p in d["parts"]]
        data["requirement_review"] = instruction_findings(
            [d for d in documents if d["role"] != "draft"], "\n".join(drafts) if drafts else None
        )
    if capability in {"deadlines", "consistency"}:
        data["deadline_review"] = deadline_findings(
            documents,
            [i.model_dump(mode="json") for i in items],
            dataset.timezone if dataset else None,
            bool(dataset and dataset.complete),
            source_label="Independent",
        )
    # Narrow extraction cannot certify absence of all natural-language conflicts.
    return data, True
