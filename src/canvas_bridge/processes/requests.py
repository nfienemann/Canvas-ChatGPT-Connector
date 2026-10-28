"""Client requests contain proposals and references, never authority or permissions."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.integrity.models import Activity
from canvas_bridge.processes.feasibility import TimeWindow, WorkEstimate
from canvas_bridge.processes.models import Model, Ref


class ProcessScope(Model):
    document_ids: tuple[Ref, ...] = Field(default=(), max_length=6)
    connection_id: Ref | None = None
    course_id: Ref | None = None
    resource_ids: tuple[Ref, ...] = Field(default=(), max_length=30)
    local_course: str = Field(default="independent", min_length=1, max_length=100)
    term: str = Field(default="unspecified", min_length=1, max_length=100)

    @model_validator(mode="after")
    def coherent(self):
        if bool(self.connection_id) != bool(self.course_id):
            raise ValueError("A connected scope requires both connection and course.")
        if self.resource_ids and not self.connection_id:
            raise ValueError("Provider resources require a connection.")
        if not self.document_ids and not self.resource_ids:
            raise ValueError(
                "Choose independently imported documents or authorized provider resources."
            )
        return self


class ClaimInput(Model):
    source_id: Ref
    entity: Ref
    field: Literal["deadline", "requirements", "weight", "policy", "prerequisite", "concept"]
    value: str = Field(min_length=1, max_length=2000)
    unit: int = Field(default=1, ge=1, le=10000)


class EvidenceRequest(Model):
    operation: Literal["evidence"] = "evidence"
    decision_class: Literal["policy", "deadline", "summary", "graduation"] = "summary"
    claims: tuple[ClaimInput, ...] = Field(default=(), max_length=30)


class FeasibilityRequest(Model):
    operation: Literal["feasibility"] = "feasibility"
    work: tuple[WorkEstimate, ...] = Field(min_length=1, max_length=100)
    availability: tuple[TimeWindow, ...] = Field(min_length=1, max_length=100)
    commitments: tuple[TimeWindow, ...] = Field(default=(), max_length=200)
    buffer_minutes: int = Field(default=10, ge=0, le=120)
    break_minutes: int = Field(default=10, ge=0, le=60)


class LifecycleRequest(Model):
    operation: Literal["lifecycle"] = "lifecycle"
    assignment_id: Ref
    current: Literal[
        "discovered",
        "requirements_reviewed",
        "planned",
        "in_progress",
        "draft_ready",
        "submission_pending",
        "submitted_confirmed",
        "graded",
        "feedback_reviewed",
    ] = "discovered"
    target: (
        Literal[
            "requirements_reviewed",
            "planned",
            "in_progress",
            "draft_ready",
            "submission_pending",
            "submitted_confirmed",
            "graded",
            "feedback_reviewed",
        ]
        | None
    ) = None
    archive: bool = False
    activity: Activity = Activity.ADMINISTRATION

    @model_validator(mode="after")
    def one_action(self):
        if bool(self.target) == self.archive:
            raise ValueError("Choose one lifecycle transition or archival.")
        return self


class IdentityInput(Model):
    source_id: Ref
    provider: str = Field(min_length=1, max_length=100)
    external_id: Ref
    kind: Literal["course", "assignment", "document"] = "course"
    term: Ref
    institution: Ref
    course_code: str | None = Field(default=None, max_length=100)
    section: str | None = Field(default=None, max_length=100)
    instructor: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class IdentityRequest(Model):
    operation: Literal["identity"] = "identity"
    left: IdentityInput
    right: IdentityInput


class KnowledgeRequest(Model):
    operation: Literal["knowledge"] = "knowledge"
    concept_id: Ref
    label: str = Field(min_length=1, max_length=200)
    kind: Literal["exposure", "practice", "assessed_performance"] = "exposure"
    source_id: Ref
    score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    possible: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    review_at: AwareDatetime
    related_concept: str | None = Field(default=None, max_length=200)
    relationship_kind: Literal["equivalent", "prerequisite", "related"] = "related"


class DegreeCourseInput(Model):
    course: Ref
    credits: float = Field(ge=0, le=100, allow_inf_nan=False)
    completed: bool = False
    planned_term: int | None = Field(default=None, ge=1, le=50)
    prerequisites: tuple[Ref, ...] = Field(default=(), max_length=100)
    corequisites: tuple[Ref, ...] = Field(default=(), max_length=100)


class BasketInput(Model):
    id: Ref
    eligible: frozenset[Ref] = Field(min_length=1, max_length=200)
    minimum_credits: float = Field(gt=0, le=200, allow_inf_nan=False)


class SubstitutionInput(Model):
    required: Ref
    replacement: Ref
    source_id: Ref


class DegreeRequest(Model):
    operation: Literal["degree"] = "degree"
    program: Ref
    concentration: Ref | None = None
    catalog_year: int | None = Field(default=None, ge=1900, le=2200)
    minimum_credits: float = Field(gt=0, le=500, allow_inf_nan=False)
    required: frozenset[Ref] = Field(default=frozenset(), max_length=200)
    coursework: tuple[DegreeCourseInput, ...] = Field(default=(), max_length=200)
    baskets: tuple[BasketInput, ...] = Field(default=(), max_length=30)
    substitutions: tuple[SubstitutionInput, ...] = Field(default=(), max_length=30)


class ClarificationInput(Model):
    operation: Literal["clarification"] = "clarification"
    claims: tuple[ClaimInput, ...] = Field(min_length=2, max_length=10)


class ClarificationUpdate(Model):
    operation: Literal["clarification_update"] = "clarification_update"
    record_id: Ref
    event: Literal["sent", "awaiting_response", "resolved"]
    confirmed_event: bool = False
    response: ClaimInput | None = None


class AnnotationRequest(Model):
    operation: Literal["annotation"] = "annotation"
    source_id: Ref
    entity: Ref
    field: Literal["deadline", "requirements", "completion", "concept", "identity", "degree"]
    note: str = Field(min_length=1, max_length=2000)


class PortfolioInput(Model):
    source_id: Ref
    origin: Literal[
        "student_authored",
        "assigned_reading",
        "lms_material",
        "group_work",
        "lab_research",
        "third_party_asset",
        "patient_data",
    ]


class PortfolioRequest(Model):
    operation: Literal["portfolio"] = "portfolio"
    parts: tuple[PortfolioInput, ...] = Field(min_length=1, max_length=30)


Payload = Annotated[
    EvidenceRequest
    | FeasibilityRequest
    | LifecycleRequest
    | IdentityRequest
    | KnowledgeRequest
    | DegreeRequest
    | ClarificationInput
    | ClarificationUpdate
    | AnnotationRequest
    | PortfolioRequest,
    Field(discriminator="operation"),
]


class EvaluationRequest(Model):
    scope: ProcessScope
    payload: Payload


class SaveRequest(Model):
    evaluation: EvaluationRequest
    record_id: Ref
    expected_revision: int = Field(default=0, ge=0)
    depends_on: tuple[Ref, ...] = Field(default=(), max_length=100)
