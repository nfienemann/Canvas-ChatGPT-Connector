"""Bounded measurement data. These records never imply authorization."""

from datetime import UTC
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.analytics.observations import Minutes, Ref, Stamp
from canvas_bridge.domain import Model


class Span(Model):
    key: Ref
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def valid(self):
        if self.end < self.start:
            raise ValueError("Interval ends before it starts.")
        return self


class Schedule(Stamp):
    state: Literal["accepted", "proposed"]
    busy_version: Ref
    busy_coverage: Literal["complete", "partial", "unavailable"]
    blocks: list[Span] = Field(max_length=1000)
    busy: list[Span] = Field(max_length=200)
    capacity_shortfall_minutes: int | None = Field(default=None, ge=0)
    coverage_start: AwareDatetime | None = None
    coverage_end: AwareDatetime | None = None


class Forecast(Stamp):
    parent: Ref
    work_revision: Ref
    unit_id: Ref
    scope_id: Ref
    scope_kind: Literal["remaining_work", "whole_work_unit"]
    minimum: Minutes
    maximum: Minutes
    budget: Minutes | None = None
    point: Minutes | None = None
    estimated_at: AwareDatetime | None = None
    origin: str = Field(max_length=100)
    assumptions: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum > self.maximum:
            raise ValueError("Forecast range is reversed.")
        return self


class ActualInput(Model):
    forecast_id: Ref | None = None
    forecast_version: int | None = Field(default=None, ge=1)
    work_revision: Ref
    unit_id: Ref
    scope_id: Ref
    start: AwareDatetime
    completion: AwareDatetime | None = None
    completed: bool
    complete_duration: bool
    duration_basis: Literal["measured_scope", "cumulative"] = "measured_scope"
    minutes_before_scope: Minutes | None = None
    baseline_at: AwareDatetime | None = None
    minutes: Minutes | None = None

    @model_validator(mode="after")
    def valid(self):
        self.start = self.start.astimezone(UTC)
        if self.completion:
            self.completion = self.completion.astimezone(UTC)
        if self.duration_basis == "measured_scope" and (
            self.minutes_before_scope is not None or self.baseline_at
        ):
            raise ValueError("A direct phase measurement has no cumulative baseline.")
        if (
            self.minutes is not None
            and self.minutes_before_scope is not None
            and self.minutes_before_scope > self.minutes
        ):
            raise ValueError("Cumulative minutes must include the recorded baseline.")
        if self.completion and (not self.completed or self.completion < self.start):
            raise ValueError("Completion must follow the start of completed work.")
        return self


class Actual(Stamp, ActualInput):
    parent: Ref


class Action(Stamp):
    kind: Literal["logical_request", "attempt", "confirmed_effect", "manual_session"]
    effect_key: Ref | None = None
    manual_minutes: Minutes | None = None
    elapsed_ms: Annotated[int, Field(ge=0, strict=True)] | None = None


class ManualInput(Model):
    occurred_at: AwareDatetime
    minutes: Minutes | None = None


class Measurement(Model):
    """Students can declare their own durations. Provider receipts have separate trusted adapters."""

    course_id: Ref
    measurement_id: Ref
    work_id: Ref | None = None
    actual: ActualInput | None = None
    manual: ManualInput | None = None

    @model_validator(mode="after")
    def valid(self):
        if (self.actual is None) == (self.manual is None) or bool(self.actual) != bool(
            self.work_id
        ):
            raise ValueError(
                "Choose a work duration with a work ID, or a manual coordination session."
            )
        return self


class Instrumentation(Stamp):
    collection: Literal["logical_request", "attempt", "confirmed_effect"]
    start: AwareDatetime
    end: AwareDatetime


class FindingSample(Stamp):
    start: AwareDatetime
    end: AwareDatetime
    coverage_complete: bool
    deadline_clusters: int = Field(ge=0)
    capacity_shortfalls: int = Field(ge=0)
    study_plan_conflicts: int = Field(ge=0)
    acknowledged_unresolved: int = Field(ge=0)
    resolved_findings: int = Field(ge=0)
