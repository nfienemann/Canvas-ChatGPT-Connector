"""Pure reasoning. No Bridge, credentials, storage, provider or network calls."""

from canvas_bridge.academic.grade_engine import GradePolicy, calculate, digest
from canvas_bridge.academic.study_steps import (
    calendar_items,
    reported_plan_conflicts,
    review_step_evidence,
    source_steps,
    step_parents,
)
from canvas_bridge.academic_rules import (
    citation,
    deadline_findings,
    instruction_findings,
    repeated_concepts,
)
from canvas_bridge.calendar_sync import calendar_proposal
from canvas_bridge.domain import DomainError, WorkItem
from canvas_bridge.registrar import calendar_handoff, final_gaps, lookup_handoff


def work_items(dataset, source):
    parents = step_parents(dataset)
    records = {row.key: row for row in dataset.work}
    return [
        WorkItem(
            id=w.key,
            connection_id="",
            institution_id="",
            course_id=source.id,
            source_id=w.key,
            title=w.title,
            kind=w.activity_kind,
            effective_due=records[parents[w.key]].due if parents.get(w.key) in records else w.due,
            available_from=w.opens,
            closes_at=w.closes,
            revision_state="requested" if w.revision_requested else "unknown",
            independent_personal_work=True,
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
    if capability == "analytics":
        from canvas_bridge.analytics.independent import independent_review

        return independent_review(dataset, source, request.analytics, owner, now)
    if capability == "planning":
        if not items:
            raise DomainError(
                "needs_input",
                "Supply independent work items before planning.",
                reason_code="INDEPENDENT_WORK_MISSING",
            )
        from canvas_bridge.usefulness.engine import obligations

        inventory = obligations(dataset, source, now=now, plan=request.plan)
        data = inventory.pop("plan")
        conflicts = reported_plan_conflicts(dataset, documents)
        if conflicts:
            data["requirement_review"] = {"conflicts": conflicts}
        step_review = review_step_evidence(dataset, documents)
        if step_review:
            data["study_step_review"] = step_review
        if conflicts or any(step["status"] == "source_review_required" for step in step_review):
            data["information_status"] = "uncertain"
            if data["feasibility"] == "feasible":
                data["feasibility"] = "provisional"
        data["work_accounting"] = {
            r["work_id"]: {k: v for k, v in r.items() if k != "work_id"}
            for r in inventory["accounting"]
        }
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
        items, inherited = calendar_items(items, step_parents(dataset))
        data = calendar_proposal(
            items, request.calendar, owner, "", now, source_label="Independent"
        )
        if inherited:
            data["inferred_deadline_parents"] = inherited
            data["limitations"].append(
                "These parents have only step-level planning cutoffs. Confirm each date "
                "against its assignment before using a reminder. Inconsistent cutoffs are omitted."
            )
        calendar_handoff(
            data,
            items,
            request.calendar,
            owner,
            "",
            request.registrar_lookup,
            allowed_courses=[source.id],
        )
        return data, bool(inherited) or not dataset.complete or data[
            "status"
        ] != "proposal_only" or bool(data["ambiguous_matches"])
    if capability == "assessment":
        return assessment_evidence(documents, request.assessment_description), True
    data = {}
    if capability in {"requirements", "consistency"}:
        drafts = [d for d in documents if d["role"] == "draft"]
        data["requirement_review"] = instruction_findings(
            [d for d in documents if d["role"] != "draft"],
            "\n".join(p["text"] for d in drafts for p in d["parts"]) if drafts else None,
            draft_complete=len(drafts) == 1 and drafts[0]["complete"],
        )
        candidates = source_steps(documents)
        if candidates["steps"]:
            data["source_work_steps"] = candidates
    if capability in {"deadlines", "consistency"}:
        data["deadline_review"] = deadline_findings(
            documents,
            [i.model_dump(mode="json") for i in items],
            dataset.timezone if dataset else None,
            bool(dataset and dataset.complete),
            source_label="Independent",
        )
        handoff = lookup_handoff(
            final_gaps(
                [i.model_dump(mode="json") for i in items],
                documents,
                data["deadline_review"]["findings"],
            ),
            request.registrar_lookup,
            allowed_courses={d.get("course_id") or d["id"] for d in documents}
            | ({source.id} if source else set()),
        )
        if handoff:
            data["registrar_lookup"] = handoff
    # Narrow extraction cannot certify absence of all natural-language conflicts.
    return data, True
