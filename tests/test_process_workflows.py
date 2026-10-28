"""Acceptance cases for CB-02/05/07/08/09/10/11/16/17."""

from datetime import timedelta

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.integrity.models import Activity
from canvas_bridge.processes.clarification import (
    confirm_status,
    draft_clarification,
    response_candidate,
)
from canvas_bridge.processes.degree import CourseCredit, CourseRule, DegreeRules, project_degree
from canvas_bridge.processes.diagnostics import preview_report, support_report
from canvas_bridge.processes.evidence import reconcile
from canvas_bridge.processes.feasibility import TimeWindow, WorkEstimate, simulate
from canvas_bridge.processes.identity import (
    ExternalEntityKey,
    canonical_link,
    match_entities,
    unlink,
)
from canvas_bridge.processes.impact import impact_proposals
from canvas_bridge.processes.knowledge import (
    Concept,
    ConceptRelationship,
    LearningEvidence,
    competency,
    related_concepts,
)
from canvas_bridge.processes.lifecycle import AssignmentState, TransitionEvidence, transition
from canvas_bridge.processes.portfolio import (
    PortfolioPart,
    PublicationReview,
    export_manifest,
    publication_clearance,
)
from canvas_bridge.processes.state import indexed
from tests.test_process_evidence import NOW, SCOPE, claim, source
from tests.test_process_state import record


def test_cb02_earlier_exam_impacts_sessions_but_cosmetic_title_does_not_reschedule():
    exam = record()
    plan = record("plan", kind="plan", depends_on=(exam.id,))
    state = indexed({exam.id: exam, plan.id: plan})
    new = exam.model_copy(update={"revision": 2, "data": {"deadline": "2030-10-08"}})
    proposals = impact_proposals(state, exam, new, now=NOW)
    assert (
        proposals[0]["reschedule_proposed"] and proposals[0]["classification"] == "action_required"
    )
    assert impact_proposals(state, exam, new, now=NOW + timedelta(seconds=3)) == proposals
    assert len({p["id"] for p in proposals * 3}) == 1
    title = exam.model_copy(update={"data": exam.data | {"title": "New title"}})
    assert not impact_proposals(state, exam, title, now=NOW)[0]["reschedule_proposed"]


def entity(provider="import", **updates):
    fields = dict(
        provider=provider,
        external_id=provider + "-1",
        scope=SCOPE,
        kind="course",
        course_code="BIO101",
        section="A",
        instructor="fictional-instructor",
        sources=(source(),),
    )
    return ExternalEntityKey(**(fields | updates))


def test_cb05_link_preserves_permission_boundaries_and_unmerge_restores_originals():
    from canvas_bridge.processes.identity import canonical_inventory

    left, right = entity(), entity("canvas")
    assert match_entities(left, right)["status"] == "strong_candidate"
    with pytest.raises(DomainError):
        canonical_link(left, right, confirmed=False)
    merged = canonical_link(left, right, confirmed=True)
    assert merged["permission_mode"] == "authorize_each_origin"
    assert unlink(merged) == (left, right)
    assert len(canonical_inventory([left, right], [merged])) == 1
    assert len(canonical_inventory([left, right], [])) == 2


@pytest.mark.parametrize(
    "scope",
    [
        SCOPE.model_copy(update={"term": "2031-spring"}),
        SCOPE.model_copy(update={"principal": "other-student"}),
    ],
)
def test_cb05_same_title_never_merges_different_terms_or_students(scope):
    assert not match_entities(entity(), entity("canvas", scope=scope))["merge_allowed"]


def test_cb07_draft_never_proves_submission_but_observed_receipt_does():
    state = AssignmentState(assignment_id="exam")
    draft = TransitionEvidence(source=source(), kind="draft_file", assignment_id="exam")
    with pytest.raises(DomainError) as error:
        transition(state, "submitted_confirmed", draft, policy_sources=[], now=NOW)
    assert error.value.reason_code == "PROCESS_SUBMISSION_UNCONFIRMED"
    observed = draft.model_copy(
        update={"kind": "submission_receipt", "observed": True, "value": "submitted"}
    )
    outcome = transition(state, "submitted_confirmed", observed, policy_sources=[], now=NOW)
    assert outcome["state"].stage == "submitted_confirmed" and not outcome["external_action"]
    imported = observed.model_copy(
        update={"source": source().model_copy(update={"origin": "local_document"})}
    )
    with pytest.raises(DomainError):
        transition(state, "submitted_confirmed", imported, policy_sources=[], now=NOW)


def test_cb07_existing_integrity_engine_blocks_disallowed_assistance():
    with pytest.raises(DomainError) as error:
        transition(
            AssignmentState(assignment_id="exam"),
            "requirements_reviewed",
            TransitionEvidence(source=source(), kind="user_declaration", assignment_id="exam"),
            policy_sources=[],
            activity=Activity.FALSE_DECLARATION,
            now=NOW,
        )
    assert error.value.reason_code == "INTEGRITY_FALSE_AUTHORSHIP_CLAIM"


def test_cb08_reading_is_exposure_scored_practice_is_separate_and_relations_are_cited():
    western = Concept(id="western-blot", label="Western blot", sources=(source(),))
    evidence = LearningEvidence(
        concept_id=western.id,
        kind="exposure",
        source=source(),
        observed_at=NOW,
        review_at=NOW + timedelta(hours=12),
    )
    assert competency(western, [evidence], now=NOW)["category"] == "exposed"
    practice = evidence.model_copy(update={"kind": "practice", "score": 8, "possible": 10})
    result = competency(western, [practice], now=NOW)
    assert result["category"] == "practiced" and not result["mastery_certified"]
    assert (
        competency(western, [practice], now=NOW + timedelta(hours=13))["category"] == "review_due"
    )
    protein = Concept(id="protein", label="Protein detection", sources=(source("biochemistry"),))
    relation = ConceptRelationship(
        left=western.id,
        right=protein.id,
        kind="related",
        basis="inferred",
        sources=(source(), source("biochemistry")),
    )
    assert related_concepts([western, protein], [relation], western.id)[0]["basis"] == "inferred"


def test_cb09_overcommitment_and_three_hour_uncertainty_are_visible():
    slot = TimeWindow(start=NOW, end=NOW + timedelta(hours=4))
    task = WorkEstimate(id="report", minimum_minutes=120, maximum_minutes=300, deadline=slot.end)
    result = simulate([task], [slot], [], now=NOW, buffer_minutes=0, break_minutes=0)
    assert result["status"] == "at_risk"
    assert (
        result["cases"][0]["status"] == "feasible" and result["cases"][-1]["status"] == "infeasible"
    )
    assert not result["calendar_changed"]
    impossible = task.model_copy(update={"minimum_minutes": 360, "maximum_minutes": 400})
    assert simulate([impossible], [slot], [], now=NOW)["status"] == "infeasible"


def test_cb09_deduplicates_availability_respects_commitments_breaks_and_prerequisites():
    slot = TimeWindow(start=NOW, end=NOW + timedelta(hours=5))
    busy = TimeWindow(start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2))
    tasks = [
        WorkEstimate(id="draft", minimum_minutes=60, maximum_minutes=60, deadline=slot.end),
        WorkEstimate(
            id="edit",
            minimum_minutes=30,
            maximum_minutes=30,
            deadline=slot.end,
            prerequisites=("draft",),
        ),
    ]
    result = simulate(tasks, [slot, slot], [busy], now=NOW, buffer_minutes=0, break_minutes=10)
    blocks = result["cases"][0]["blocks"]
    assert result["cases"][0]["capacity_minutes_before_breaks"] == 240
    assert result["status"] == "feasible"
    assert max(b["end"] for b in blocks if b["work_id"] == "draft") <= min(
        b["start"] for b in blocks if b["work_id"] == "edit"
    )
    assert all(
        b["end"] <= busy.start.isoformat() or b["start"] >= busy.end.isoformat() for b in blocks
    )


def test_cb10_missing_catalog_provisional_and_prerequisite_blocks_impossible_plan():
    rules = DegreeRules(
        institution=SCOPE.institution,
        program="biology",
        version="v1",
        minimum_credits=120,
        required=frozenset({"BIO201"}),
        courses=(CourseRule(course="BIO201", prerequisites=("BIO101",)),),
        source=source(),
    )
    courses = [
        CourseCredit(course="BIO201", credits=3, planned_term=1, source=source()),
        CourseCredit(course="BIO101", credits=3, planned_term=2, source=source()),
    ]
    projection = project_degree(rules, courses, now=NOW)
    assert projection["unofficial"] and not projection["certifies_graduation"]
    assert (
        projection["status"] == "provisional"
        and "CATALOG_YEAR_MISSING" in projection["limitations"]
    )
    assert projection["blocked_plan"] == [
        {"course": "BIO201", "requires": "BIO101", "kind": "prerequisite"}
    ]


def test_cb11_clarification_is_unsent_and_response_is_narrow_unverified_evidence():
    conflict = reconcile([claim(), claim("update", "2030-10-09")], now=NOW)
    draft = draft_clarification(conflict)
    assert not draft["message_sent"] and draft["self_service_first"]
    with pytest.raises(DomainError):
        confirm_status(draft["request"], "sent", confirmed=False)
    sent = confirm_status(draft["request"], "sent", confirmed=True)
    assert sent.status == "sent" and sent.status_basis == "user_confirmed"
    response = response_candidate(sent, claim("reply"))
    assert response.authority == "unverified" and not response.supersedes
    with pytest.raises(DomainError):
        response_candidate(sent, claim("reply", field="weight"))


def test_cb16_diagnostics_excludes_freeform_secrets_and_previews_exact_unsent_report():
    first, second = support_report("authorization"), support_report("authorization")
    assert (
        first["reason_code"] == second["reason_code"] and first["next_step"] == second["next_step"]
    )
    preview = preview_report(first)
    assert not preview["sent"] and first["event_id"] in preview["exact_payload"]
    with pytest.raises(ValueError):
        preview_report(first | {"exception": "SECRET_TOKEN_AND_PRIVATE_COURSEWORK"})
    with pytest.raises(ValueError):
        preview_report(first | {"event_id": "private-student-name"})


def test_cb17_unpublished_research_and_group_work_are_held_until_separate_rights_review():
    parts = [
        PortfolioPart(id="figure", source=source(), origin="lab_research", content_hash="a" * 64),
        PortfolioPart(id="group", source=source(), origin="group_work", content_hash="b" * 64),
    ]
    clearance = publication_clearance(parts, [], now=NOW)
    assert clearance["status"] == "held_for_review" and not clearance["publish_executed"]
    assert "UNPUBLISHED_RESEARCH_REVIEW_REQUIRED" in clearance["checklist"][0]["reasons"]
    assert "COLLABORATOR_CREDIT_AND_CONSENT_REQUIRED" in clearance["checklist"][1]["reasons"]
    reviews = [
        PublicationReview(
            part_id=p.id,
            content_hash=p.content_hash,
            source_version="v1",
            permission="allowed",
            reviewed_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            review_reference="human-review",
            attribution_checked=True,
            privacy_checked=True,
            collaborators_checked=True,
            research_release_checked=True,
        )
        for p in parts
    ]
    with pytest.raises(DomainError):
        export_manifest(parts, reviews, now=NOW, confirmed=False, authorize=lambda *a: None)
    checks = []
    result = export_manifest(
        parts, reviews, now=NOW, confirmed=True, authorize=lambda *a: checks.append(a)
    )
    assert len(checks) == 2 and not result["published"]
    changed = [parts[0].model_copy(update={"content_hash": "c" * 64}), parts[1]]
    assert publication_clearance(changed, reviews, now=NOW)["status"] == "held_for_review"
