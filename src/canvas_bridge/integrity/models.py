"""Bounded contracts. Only references and requested activities are accepted from clients."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator
from pydantic_core import PydanticCustomError

from canvas_bridge.domain import Model

VERSION = "academic-integrity-1"
Ref = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]


class Category(StrEnum):
    ADMINISTRATION = "A"
    LEARNING = "B"
    PLANNING = "C"
    ASSISTANCE = "D"
    GENERATION = "E"


class Activity(StrEnum):
    ADMINISTRATION = "administration"
    REQUIREMENTS = "requirements"
    LEARNING = "independent_learning"
    EXAM_PREPARATION = "exam_preparation"
    PLANNING = "assignment_planning"
    BRAINSTORM = "brainstorming"
    OUTLINE = "substantive_outline"
    FEEDBACK = "draft_feedback"
    GRAMMAR = "mechanical_editing"
    RESEARCH = "research_assistance"
    ANALYSIS = "assessed_data_analysis"
    DEBUG = "assessed_code_debugging"
    SOLVE = "partial_answer"
    DRAFT = "submission_drafting"
    REWRITE = "substantive_rewriting"
    CODE = "assessed_code_generation"
    ANSWER = "exam_or_quiz_answer"
    DISCUSSION = "assessed_discussion_response"
    DELIVERABLE = "assessed_slides_or_diagram"
    FALSE_DECLARATION = "false_no_ai_declaration"


CATEGORIES = {
    a: Category.ADMINISTRATION
    if a in {Activity.ADMINISTRATION, Activity.REQUIREMENTS}
    else Category.LEARNING
    if a in {Activity.LEARNING, Activity.EXAM_PREPARATION}
    else Category.PLANNING
    if a == Activity.PLANNING
    else Category.ASSISTANCE
    if a
    in {
        Activity.BRAINSTORM,
        Activity.OUTLINE,
        Activity.FEEDBACK,
        Activity.GRAMMAR,
        Activity.RESEARCH,
        Activity.ANALYSIS,
        Activity.DEBUG,
        Activity.SOLVE,
    }
    else Category.GENERATION
    for a in Activity
}
SUBSTANTIVE = frozenset(
    a for a in Activity if CATEGORIES[a] in {Category.ASSISTANCE, Category.GENERATION}
)
LEARNING = frozenset({Activity.LEARNING, Activity.EXAM_PREPARATION})


class State(StrEnum):
    PERMITTED_EXPLICIT = "PERMITTED_EXPLICIT"
    PERMITTED_CONDITIONAL = "PERMITTED_CONDITIONAL"
    PROHIBITED_CONFIRMED = "PROHIBITED_CONFIRMED"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTING = "CONFLICTING"
    NO_POLICY_FOUND = "NO_POLICY_FOUND"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Coverage(StrEnum):
    DISCOVERED = "DISCOVERED"
    READ_COMPLETE = "READ_COMPLETE"
    READ_PARTIAL = "READ_PARTIAL"
    UNREADABLE = "UNREADABLE"
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    STALE = "STALE"
    NOT_CHECKED = "NOT_CHECKED"


class Verification(StrEnum):
    INSTRUCTOR_VERIFIED = "INSTRUCTOR_VERIFIED"
    OFFICIAL_SOURCE_CONFIRMED = "OFFICIAL_SOURCE_CONFIRMED"
    STUDENT_SUPPLIED_UNVERIFIED = "STUDENT_SUPPLIED_UNVERIFIED"
    STUDENT_ATTESTED = "STUDENT_ATTESTED"
    NO_EVIDENCE = "NO_EVIDENCE"


class Scope(Model):
    connection_id: Ref | None = None
    course_id: Ref | None = None
    assessment_id: Ref | None = None
    document_ids: list[Ref] = Field(default_factory=list, max_length=6)
    # Local labels locate a saved context; they never assert institutional authority.
    local_course: Ref | None = None
    institution: Ref | None = None

    @model_validator(mode="after")
    def coherent(self):
        if bool(self.connection_id) != bool(self.course_id):
            raise PydanticCustomError("integrity_scope_invalid", "Provide a coherent scope.")
        if not self.connection_id and not self.document_ids and not self.local_course:
            raise PydanticCustomError("integrity_scope_missing", "Choose an authorized scope.")
        if self.connection_id and (self.local_course or self.institution):
            raise ValueError("Institution and course identity come from the connection.")
        self.document_ids = sorted(set(self.document_ids))
        return self


class AssistanceRequest(Model):
    scope: Scope
    activity: Activity
    # This can only raise the minimum classification, never lower it.
    expected_output: Literal[
        "source_evidence", "ideas", "substantive_outline", "submission_content"
    ] = "source_evidence"
    continuation_id: Ref | None = None
    acknowledgment_id: Ref | None = None

    def effective_activity(self):
        if (
            self.expected_output == "submission_content"
            and CATEGORIES[self.activity] != Category.GENERATION
        ):
            return Activity.DRAFT
        if self.expected_output == "substantive_outline" and CATEGORIES[self.activity] in {
            Category.ADMINISTRATION,
            Category.PLANNING,
            Category.LEARNING,
        }:
            return Activity.OUTLINE
        if self.expected_output == "ideas" and CATEGORIES[self.activity] in {
            Category.ADMINISTRATION,
            Category.PLANNING,
            Category.LEARNING,
        }:
            return Activity.BRAINSTORM
        return self.activity


class PolicySource(Model):
    id: str
    version: str
    kind: str
    authority: Literal[
        "institution", "department", "instructor", "student", "illustrative", "unknown"
    ]
    verification: Verification = Verification.NO_EVIDENCE
    course_id: str | None = None
    assessment_id: str | None = None
    uri: str = ""
    retrieved_at: AwareDatetime
    effective_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    academic_term: str | None = None
    coverage: Coverage
    parts: list[dict[str, str]] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    issuer: str = ""
    limitation: str | None = None

    @property
    def authoritative(self):
        return self.authority in {
            "institution",
            "department",
            "instructor",
        } and self.verification in {
            Verification.INSTRUCTOR_VERIFIED,
            Verification.OFFICIAL_SOURCE_CONFIRMED,
        }


class Rule(Model):
    effect: Literal[
        "deny", "allow", "permission_required", "approved_tool_required", "disclosure", "ambiguous"
    ]
    activities: frozenset[Activity]
    source_id: str
    source_version: str
    locator: str
    passage: str
    assessment_only: bool = False
    exam_only: bool = False
    condition: str | None = None


class Decision(Model):
    id: str
    version: str = VERSION
    policy_version: str
    activity: Activity
    category: Category
    state: State
    allowed: bool
    reason_code: str
    acknowledgment_eligible: bool = False
    acknowledgment_valid: bool = False
    permission_established: bool = False
    rules: list[Rule] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(
        default_factory=lambda: [
            "administration",
            "requirements",
            "assignment_planning",
            "seek_instructor_clarification",
        ]
    )
    created_at: datetime
    expires_at: datetime

    def require(self):
        from canvas_bridge.domain import DomainError

        if not self.allowed:
            raise DomainError(
                "permission_denied",
                "Academic permission for this assistance is not established. Review the integrity decision and permitted alternatives.",
                reason_code=self.reason_code,
                details={"integrity_decision_id": self.id, "integrity_state": str(self.state)},
            )
        return self
