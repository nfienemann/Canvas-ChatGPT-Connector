"""Assignment progress is distinct from observed submission and grade evidence."""

from typing import Literal

from pydantic import Field

from canvas_bridge.domain import DomainError
from canvas_bridge.integrity.engine import evaluate_academic_assistance
from canvas_bridge.integrity.models import Activity
from canvas_bridge.processes.models import Model, Ref, SourceTag

Stage = Literal[
    "discovered",
    "requirements_reviewed",
    "planned",
    "in_progress",
    "draft_ready",
    "submission_pending",
    "submitted_confirmed",
    "graded",
    "feedback_reviewed",
]
ORDER = (
    "discovered",
    "requirements_reviewed",
    "planned",
    "in_progress",
    "draft_ready",
    "submission_pending",
    "submitted_confirmed",
    "graded",
    "feedback_reviewed",
)


class AssignmentState(Model):
    assignment_id: Ref
    stage: Stage = "discovered"
    archived: bool = False
    evidence: tuple[SourceTag, ...] = Field(default=(), max_length=100)
    basis: Literal["observed", "user_declared", "inferred"] = "user_declared"


class TransitionEvidence(Model):
    source: SourceTag
    kind: Literal["user_declaration", "draft_file", "submission_receipt", "grade_record"]
    assignment_id: Ref
    # Only a trusted provider adapter may populate observed provider facts.
    observed: bool = False
    value: Literal["submitted", "resubmitted", "graded", "unknown"] = "unknown"


def transition(state, target, evidence, *, policy_sources, activity=Activity.ADMINISTRATION, now):
    decision = evaluate_academic_assistance(
        activity, policy_sources, assessment_id=state.assignment_id, now=now
    )
    decision.require()
    if target not in ORDER or state.archived or evidence.assignment_id != state.assignment_id:
        raise DomainError(
            "needs_input",
            "Review the assignment and requested transition.",
            reason_code="PROCESS_TRANSITION_INVALID",
        )
    if evidence.source.expires_at <= now or evidence.source.observed_at > now:
        raise DomainError(
            "source_changed", "Refresh transition evidence.", reason_code="PROCESS_SOURCE_STALE"
        )
    official = evidence.observed and evidence.source.origin in {"institutional", "synthetic"}
    if target == "submitted_confirmed" and not (
        official
        and evidence.kind == "submission_receipt"
        and evidence.value in {"submitted", "resubmitted"}
    ):
        raise DomainError(
            "needs_input",
            "A draft or personal completion declaration does not confirm submission.",
            reason_code="PROCESS_SUBMISSION_UNCONFIRMED",
        )
    if target == "graded" and not (
        official and evidence.kind == "grade_record" and evidence.value == "graded"
    ):
        raise DomainError(
            "needs_input",
            "An observed grade record is required.",
            reason_code="PROCESS_GRADE_UNCONFIRMED",
        )
    if (
        target not in {"submitted_confirmed", "graded"}
        and ORDER.index(target) != ORDER.index(state.stage) + 1
    ):
        raise DomainError(
            "needs_input",
            "Review the next lifecycle step or use a correction preview.",
            reason_code="PROCESS_TRANSITION_INVALID",
        )
    return {
        "state": state.model_copy(
            update={
                "stage": target,
                "evidence": state.evidence + (evidence.source,),
                "basis": "observed" if official else "user_declared",
            }
        ),
        "integrity_decision": decision,
        "external_action": False,
        "next_step": ORDER[ORDER.index(target) + 1]
        if target != ORDER[-1]
        else "archive_when_appropriate",
    }
