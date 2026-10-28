"""Source-neutral academic input, loaded only through a permitted source adapter."""

from typing import Annotated, Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from canvas_bridge.academic.grade_engine import (
    GradeAssessment,
    GradeGroup,
    GradeScenario,
    Mode,
    PolicyReview,
)
from canvas_bridge.calendar_sync import CalendarContext
from canvas_bridge.domain import Effort, FactDate, Model
from canvas_bridge.planning import PlanRequest

Key = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")]
Ref = Annotated[str, Field(min_length=1, max_length=100)]


class IndependentWork(Model):
    key: Key
    title: str = Field(min_length=1, max_length=500)
    due: FactDate = Field(default_factory=FactDate)
    effort: Effort | None = None
    progress: Literal["not_started", "in_progress", "student_marked_done", "unknown"] = "unknown"
    prerequisites: list[Key] = Field(default_factory=list, max_length=30)


class IndependentAssessment(GradeAssessment):
    # An entered score does not establish that it counts under the supplied policy.
    eligibility_verified: bool = False


class IndependentGrades(Model):
    method: Literal["points", "weighted", "unknown"] = "unknown"
    groups: list[GradeGroup] = Field(default_factory=list, max_length=30)
    assessments: list[IndependentAssessment] = Field(default_factory=list, max_length=100)
    policy_origin: Literal["manual", "syllabus_interpretation"] = "manual"
    rules: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=30
    )
    unsupported_rules: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=30
    )
    complete: bool = False

    @model_validator(mode="after")
    def sources(self):
        # URLs/versions are assigned by the adapter; these old engine fields are
        # not an alternative route to institutional source identifiers.
        if any(a.source_url or a.source_version for a in self.assessments):
            raise ValueError("Grade sources are assigned from the permitted input document.")
        values = [g.weight for g in self.groups] + [
            v for a in self.assessments for v in (a.possible, a.score)
        ]
        if any(v is not None and (not v.is_finite() or abs(v) > 1_000_000_000) for v in values):
            raise ValueError(
                "Grade numbers must be finite and within the supported arithmetic bounds."
            )
        return self


class IndependentAcademicInput(Model):
    schema_version: Literal["independent-academic-1"]
    work: list[IndependentWork] = Field(default_factory=list, max_length=50)
    grades: IndependentGrades | None = None
    timezone: str | None = Field(default=None, max_length=100)
    complete: bool = False

    @model_validator(mode="after")
    def valid(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise ValueError("Use a valid IANA timezone or leave it unknown.") from exc
        keys = {w.key for w in self.work}
        if len(keys) != len(self.work):
            raise ValueError("Work keys must be unique within the input document.")
        if any(set(w.prerequisites) - keys or w.key in w.prerequisites for w in self.work):
            raise ValueError("Prerequisites must identify other work in the same input.")
        if len(self.model_dump_json().encode()) > 80_000:
            raise ValueError("Academic input exceeds 80 KB.")
        return self


class DocumentSelection(Model):
    document_id: Ref
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_part: int = Field(default=1, ge=1, le=200)
    limit: int = Field(default=3, ge=1, le=5)
    role: Literal["material", "instructions", "rubric", "schedule", "draft"] = "material"


class IndependentRequest(Model):
    capability: Literal[
        "planning", "assessment", "requirements", "grades", "deadlines", "consistency", "calendar"
    ]
    # Structured records are ordinary owned TXT/Markdown imports. No caller
    # permission/classification/source-label fields and no LMS connection ID.
    dataset: DocumentSelection | None = None
    documents: list[DocumentSelection] = Field(default_factory=list, max_length=5)
    plan: PlanRequest | None = None
    calendar: CalendarContext | None = None
    assessment_description: str | None = Field(default=None, max_length=2000)
    grade_mode: Mode = "current_graded"
    scenario: GradeScenario | None = None
    policy_review: PolicyReview | None = None

    @model_validator(mode="after")
    def bounded(self):
        ids = [d.document_id for d in self.documents]
        if len(set(ids)) != len(ids) or (self.dataset and self.dataset.document_id in ids):
            raise ValueError("Select each source once.")
        if self.capability in {"planning", "grades", "calendar"} and self.dataset is None:
            raise PydanticCustomError("independent_input_missing", "Select academic records.")
        if self.capability in {"assessment", "requirements"} and not self.documents:
            raise PydanticCustomError("independent_input_missing", "Select evidence documents.")
        if not self.dataset and not self.documents:
            raise PydanticCustomError("independent_input_missing", "Select independent sources.")
        if len(self.model_dump_json().encode()) > 60_000:
            raise ValueError("Request exceeds the bounded input size.")
        return self
