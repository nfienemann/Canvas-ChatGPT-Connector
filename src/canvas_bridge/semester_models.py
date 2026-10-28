"""User-owned semester preferences and bounded on-demand analysis requests."""

from datetime import time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import Model
from canvas_bridge.planning import Window

Ref = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]


class CoursePriority(Model):
    course_id: Ref
    priority: int = Field(ge=0, le=10, strict=True)


class StudyPeriod(Model):
    weekdays: list[Annotated[int, Field(ge=0, le=6, strict=True)]] = Field(
        min_length=1, max_length=7
    )
    start: time
    end: time

    @model_validator(mode="after")
    def valid(self):
        if self.start.tzinfo or self.end.tzinfo or self.start >= self.end:
            raise ValueError("Study periods use increasing local wall times without a UTC offset.")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Do not repeat a weekday.")
        return self


class NotificationPreferences(Model):
    opted_in: bool = False
    frequency: Literal["daily", "weekly"] = "weekly"
    quiet_start: time = time(21)
    quiet_end: time = time(8)
    course_ids: list[Ref] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def valid(self):
        if self.quiet_start.tzinfo or self.quiet_end.tzinfo or self.quiet_start == self.quiet_end:
            raise ValueError("Quiet hours need distinct local wall times without a UTC offset.")
        if len(set(self.course_ids)) != len(self.course_ids):
            raise ValueError("Notification courses must be distinct.")
        if self.opted_in and not self.course_ids:
            raise ValueError("Notification opt-in requires explicit course scope.")
        return self


class SemesterPreferences(Model):
    course_priorities: list[CoursePriority] = Field(default_factory=list, max_length=24)
    preferred_study_periods: list[StudyPeriod] = Field(default_factory=list, max_length=21)
    available_windows: list[Window] = Field(default_factory=list, max_length=100)
    workload_tolerance_minutes_per_day: int | None = Field(
        default=None, ge=15, le=1440, strict=True
    )
    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)

    @model_validator(mode="after")
    def distinct(self):
        if len({p.course_id for p in self.course_priorities}) != len(self.course_priorities):
            raise ValueError("Course priorities must be distinct.")
        ordered = sorted(self.available_windows, key=lambda w: w.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Available windows must not overlap.")
        return self


class SemesterRequest(Model):
    course_ids: list[Ref] | None = Field(default=None, min_length=1, max_length=24)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    timezone: str | None = Field(default=None, max_length=100)
    busy_times: list[Window] = Field(default_factory=list, max_length=100)
    include_course_evidence: bool = True

    @model_validator(mode="after")
    def valid(self):
        if bool(self.start) != bool(self.end):
            raise ValueError("Provide both semester bounds or neither.")
        if self.start and (self.end <= self.start or self.end - self.start > timedelta(days=366)):
            raise ValueError("Semester window must be positive and at most 366 days.")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ValueError, KeyError) as exc:
                raise ValueError("Choose an IANA timezone.") from exc
        if self.course_ids and len(set(self.course_ids)) != len(self.course_ids):
            raise ValueError("Course scope must be distinct.")
        return self
