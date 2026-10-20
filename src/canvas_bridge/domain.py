"""Typed facts. Absence, uncertainty and denied access are different states."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def opaque_id() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactDate(Model):
    kind: Literal[
        "timestamp",
        "local_date",
        "known_none",
        "not_returned",
        "permission_denied",
        "not_refreshed",
        "unsupported",
    ] = "not_returned"
    timestamp: AwareDatetime | None = None
    local_date: date | None = None
    raw: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.kind == "timestamp") != (self.timestamp is not None):
            raise ValueError("Timestamp state requires exactly a timestamp.")
        if (self.kind == "local_date") != (self.local_date is not None):
            raise ValueError("Date-only state requires exactly a date.")
        return self

    def display(self, zone: str) -> str:
        if self.timestamp:
            return self.timestamp.astimezone(ZoneInfo(zone)).isoformat()
        if self.local_date:
            return self.local_date.isoformat()
        return self.kind


class Effort(Model):
    minimum_minutes: int = Field(ge=1, le=100_000)
    maximum_minutes: int = Field(ge=1, le=100_000)
    origin: Literal[
        "student_estimate", "instructor_estimate", "rule_of_thumb", "assistant_estimate"
    ]
    as_of: AwareDatetime = Field(default_factory=utcnow)
    assumptions: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def ordered(self):
        if self.maximum_minutes < self.minimum_minutes:
            raise ValueError("Effort maximum must be at least the minimum.")
        return self


class Source(Model):
    id: str
    url: str
    title: str
    retrieved_at: AwareDatetime
    source_updated_at: AwareDatetime | None = None
    locator: str | None = None
    classification: Literal[
        "source_fact",
        "deterministic_calculation",
        "student_input",
        "assistant_inference",
        "unknown",
    ] = "source_fact"
    untrusted_content: bool = True


class WorkItem(Model):
    id: str
    connection_id: str
    institution_id: str
    course_id: str
    source_id: str
    title: str = Field(max_length=1000)
    kind: str = "assignment"
    effective_due: FactDate = Field(default_factory=FactDate)
    available_from: FactDate = Field(default_factory=FactDate)
    closes_at: FactDate = Field(default_factory=FactDate)
    submission_state: Literal[
        "not_submitted", "submitted", "resubmitted", "not_applicable", "unknown"
    ] = "unknown"
    assessment_state: Literal["graded", "pending", "excused", "unknown"] = "unknown"
    timeliness_state: Literal["on_time", "late", "missing", "not_applicable", "unknown"] = "unknown"
    availability_state: Literal[
        "available", "future_locked", "closed", "inaccessible", "unknown"
    ] = "unknown"
    revision_state: Literal["none_known", "requested", "resubmission_available", "unknown"] = (
        "unknown"
    )
    personal_progress: Literal["not_started", "in_progress", "student_marked_done", "unknown"] = (
        "unknown"
    )
    submission_requirement: str = "unknown"
    points_possible: Decimal | None = None
    effort_remaining: Effort | None = None
    source: Source
    prerequisites: list[str] = Field(default_factory=list, max_length=100)
    prerequisite_coverage: Literal["unknown", "known"] = "unknown"


class Coverage(Model):
    course_ref: str
    resource: str
    state: Literal[
        "complete", "partial", "unavailable", "permission_denied", "unsupported", "not_refreshed"
    ]
    pagination_complete: bool = False
    pages_consumed: int = 0
    warning: str | None = None


class Meta(Model):
    request_id: str = Field(default_factory=opaque_id)
    snapshot_id: str | None = None
    retrieved_at: AwareDatetime = Field(default_factory=utcnow)
    display_timezone: str = "UTC"
    freshness: Literal["live", "cached", "stale", "synthetic", "not_refreshed"] = "not_refreshed"
    coverage: list[Coverage] = Field(default_factory=list)
    next_cursor: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Result(Model):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "ok",
        "partial_data",
        "stale_data",
        "reconnect_required",
        "permission_denied",
        "unsupported_feature",
        "source_changed",
        "needs_input",
        "retry_later",
        "operation_uncertain",
    ] = "ok"
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)


class DomainError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
