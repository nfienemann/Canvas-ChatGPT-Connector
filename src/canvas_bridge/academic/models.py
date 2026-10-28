"""Versioned facts; permission metadata describes a decision, never grants one."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from canvas_bridge.egress_models import ContentClassification

Ref = Annotated[str, Field(min_length=1, max_length=100)]
SCHEMA = "academic-1"


class AcademicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["academic-1"] = SCHEMA


class SourceReference(AcademicModel):
    provider: Ref
    id: Ref
    version: str = Field(min_length=1, max_length=128)
    locator: str | None = Field(default=None, max_length=200)
    # Optional supplied URI, never synthesized by the reasoning engine.
    uri: str | None = Field(default=None, max_length=2000)


class Provenance(AcademicModel):
    source: SourceReference
    source_type: str | None = Field(default=None, max_length=100)
    observed_at: AwareDatetime
    verified_at: AwareDatetime | None = None
    fresh_until: AwareDatetime | None = None
    basis: Literal["source_fact", "user_supplied", "synthetic", "derived"]
    complete: bool = False
    uncertainty: tuple[str, ...] = Field(default=(), max_length=30)
    derived_from: tuple[SourceReference, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def dates(self):
        if self.verified_at and self.verified_at > self.observed_at:
            raise ValueError("Verification cannot postdate observation.")
        if self.fresh_until and self.fresh_until <= self.observed_at:
            raise ValueError("Freshness requires a future bound.")
        return self


class PermissionContext(AcademicModel):
    principal: Ref
    tenant: Ref
    connection: Ref
    scope: frozenset[str]
    decision_reference: Ref
    expires_at: AwareDatetime


class Restrictions(AcademicModel):
    classifications: frozenset[ContentClassification] = Field(min_length=1)
    purposes: frozenset[str] = Field(min_length=1)
    recipients: frozenset[str] = Field(min_length=1)
    copyright: Literal["unknown", "owner_attested", "reviewed_permission", "fictional"] = "unknown"
    permission_reference: str | None = Field(default=None, max_length=300)
    untrusted_content: Literal[True] = True


class Record(AcademicModel):
    id: Ref
    provenance: Provenance
    permission: PermissionContext
    restrictions: Restrictions


class Course(Record):
    title: str = Field(max_length=1000)
    timezone: str | None = None


class Deadline(AcademicModel):
    kind: Literal[
        "timestamp", "local_date", "known_none", "not_returned", "unsupported", "permission_denied"
    ] = "not_returned"
    timestamp: AwareDatetime | None = None
    local_date: date | None = None
    timezone: str | None = None
    uncertainty: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent(self):
        if (self.kind == "timestamp") != (self.timestamp is not None):
            raise ValueError("Timestamp kind and value must agree.")
        if (self.kind == "local_date") != (self.local_date is not None):
            raise ValueError("Local-date kind and value must agree.")
        return self


class Assignment(Record):
    course_id: Ref
    title: str = Field(max_length=1000)
    deadline: Deadline = Field(default_factory=Deadline)
    submission_state: Literal["submitted", "not_submitted", "unknown", "not_applicable"] = "unknown"
    effort_minutes: int | None = Field(default=None, ge=0, le=10000)


class GradeCategory(Record):
    course_id: Ref
    title: str = Field(max_length=1000)
    weight: Decimal | None = Field(default=None, allow_inf_nan=False)
    drop_lowest: int = Field(default=0, ge=0, le=100)
    drop_highest: int = Field(default=0, ge=0, le=100)
    never_drop: tuple[Ref, ...] = ()


class GradeResult(AcademicModel):
    score: Decimal | None = Field(default=None, allow_inf_nan=False)
    state: Literal["posted", "ungraded", "unavailable", "excused", "conflicting"] = "unavailable"

    @model_validator(mode="after")
    def visible(self):
        if self.state != "posted" and self.score is not None:
            raise ValueError("Only posted scores may carry a visible grade.")
        return self


class Assessment(Record):
    course_id: Ref
    title: str = Field(max_length=1000)
    category_id: Ref | None = None
    possible: Decimal | None = Field(default=None, allow_inf_nan=False)
    result: GradeResult = Field(default_factory=GradeResult)
    excluded_reason: str | None = None
    eligibility_verified: bool = False
    submission_state: str = "unknown"
    missing: bool | None = None
    late: bool | None = None


class CourseCalendarEvent(Record):
    course_id: Ref
    title: str = Field(max_length=1000)
    starts: Deadline = Field(default_factory=Deadline)
    ends: Deadline = Field(default_factory=Deadline)
    attendance_required: bool | None = None


class DocumentPart(Record):
    document_id: Ref
    kind: Literal["page", "slide", "section", "sheet"]
    number: int = Field(ge=1, le=1000)
    text: str = Field(max_length=250000)
    structure: dict[str, JsonValue] | None = None
    extraction_status: Literal["complete_text", "partial_text", "unavailable"]
    # Text is never a claim that pixels or a slide's visual content were inspected.
    visual_interpretation: Literal["not_performed"] = "not_performed"


class AcademicDocument(Record):
    course_id: Ref | None = None
    title: str = Field(max_length=1000)
    format: Literal["txt", "md", "pdf", "docx", "pptx", "xlsx"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parts: tuple[DocumentPart, ...] = Field(default=(), max_length=200)


class GradingRules(AcademicModel):
    method: Literal["points", "weighted", "unknown"] = "unknown"
    basis: Literal["provider", "syllabus", "student_input", "canvas"] = "provider"
    empty_categories: Literal["refuse", "renormalize"] = "refuse"
    blockers: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    version: str = ""


class AcademicDataset(AcademicModel):
    provider: Ref
    courses: tuple[Course, ...] = Field(default=(), max_length=100)
    assignments: tuple[Assignment, ...] = Field(default=(), max_length=100)
    categories: tuple[GradeCategory, ...] = Field(default=(), max_length=100)
    assessments: tuple[Assessment, ...] = Field(default=(), max_length=100)
    events: tuple[CourseCalendarEvent, ...] = Field(default=(), max_length=100)
    documents: tuple[AcademicDocument, ...] = Field(default=(), max_length=10)
    grading_rules: GradingRules | None = None
    complete: bool = False
    limitations: tuple[str, ...] = Field(default=(), max_length=50)

    def records(self):
        return (
            *self.courses,
            *self.assignments,
            *self.categories,
            *self.assessments,
            *self.events,
            *self.documents,
            *(p for d in self.documents for p in d.parts),
        )

    @model_validator(mode="after")
    def scoped_references(self):
        records = self.records()
        ids = [r.id for r in records]
        if len(ids) != len(set(ids)):
            raise ValueError("Normalized record identifiers must be unique.")
        if any(r.provenance.source.provider != self.provider for r in records):
            raise ValueError("Source provider differs from dataset provider.")
        courses = {r.id for r in self.courses}
        categories = {r.id: r for r in self.categories}
        for r in (
            *self.assignments,
            *self.categories,
            *self.assessments,
            *self.events,
            *self.documents,
        ):
            if r.course_id is not None and r.course_id not in courses:
                raise ValueError("Unknown normalized course reference.")
        for r in self.assessments:
            if r.category_id is not None and (
                r.category_id not in categories
                or categories[r.category_id].course_id != r.course_id
            ):
                raise ValueError("Unknown or cross-course grade category.")
        for d in self.documents:
            if any(
                p.document_id != d.id
                or p.restrictions != d.restrictions
                or p.permission != d.permission
                for p in d.parts
            ):
                raise ValueError("Document transformation changed its scope or restrictions.")
        return self
