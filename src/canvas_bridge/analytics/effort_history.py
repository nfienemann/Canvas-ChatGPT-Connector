"""Scoped effort evidence for independent work episodes; no implicit activity tracking."""

from datetime import UTC, datetime
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from canvas_bridge.analytics.activity_metrics import mismatch
from canvas_bridge.analytics.measurements import Actual, Forecast
from canvas_bridge.processes.models import Model, Ref

Instant = Annotated[AwareDatetime, AfterValidator(lambda t: t.astimezone(UTC))]
Minutes = Annotated[int, Field(ge=0, le=100_000, strict=True)]


class Interval(Model):
    start: Instant
    end: Instant

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Use a positive elapsed interval.")
        return self


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def elapsed(start, end):
    return Fraction((end - start) // datetime.resolution, 60_000_000)


class Estimate(Model):
    low: Minutes | None = None
    high: Minutes | None = None
    point: Minutes | None = None

    @model_validator(mode="after")
    def ordered(self):
        if (self.low is None) != (self.high is None) or (
            self.low is None and self.point is not None
        ):
            raise ValueError("Supply both range endpoints or leave demand unknown.")
        if self.low is not None and (
            self.low > self.high
            or self.point is not None
            and not self.low <= self.point <= self.high
        ):
            raise ValueError("The point must fall inside an ordered range.")
        return self


class Reading(Model):
    observation_id: Ref
    revision: int = Field(ge=1)
    known_at: Instant
    scope_id: Ref
    kind: Literal["duration_total", "active_interval"]
    basis: Ref
    minutes: Minutes | None = None
    start: Instant | None = None
    end: Instant | None = None
    pauses: tuple[Interval, ...] = Field(default=(), max_length=32)
    representation_group: Ref | None = None
    logical_observation_id: Ref | None = None
    retracted: bool = False

    @model_validator(mode="after")
    def valid(self):
        if self.retracted:
            return self
        if self.kind == "active_interval":
            if (
                self.start is None
                or self.end is None
                or self.end <= self.start
                or self.minutes is not None
                or self.end > self.known_at
            ):
                raise ValueError("Supply a past active interval.")
            if any(p.start < self.start or p.end > self.end for p in self.pauses):
                raise ValueError("A pause must be within its session.")
        elif self.minutes is None or self.start or self.end or self.pauses:
            raise ValueError("Supply an explicit active-minute total.")
        return self


class Issued(Model):
    forecast_id: Ref
    scope_id: Ref
    frozen_at: Instant
    known_at: Instant
    baseline: Estimate
    published: Estimate
    baseline_policy: Ref
    baseline_origin: Ref
    previous_calibration_policy: Ref | None = None
    canonical_forecast_id: Ref | None = None
    budget: Minutes | None = None


class Completion(Model):
    complete: bool
    completed_at: Instant | None = None
    known_at: Instant
    basis: Ref


class Coverage(Model):
    reason: Ref | None = None
    state: Literal["complete", "partial", "unknown", "unavailable"]
    known_at: Instant
    basis: Ref


class Scope(Model):
    episode_id: Ref
    scope_id: Ref
    task_family: Ref
    scope_kind: Literal["whole_episode", "remaining_episode"]
    baseline_policy: Ref


class HistoryScope(Scope):
    history_id: Ref
    user_id: Ref
    scope_start_at: Instant
    scope_end_at: Instant
    completion: Completion
    coverage: Coverage
    forecasts: tuple[Issued, ...] = Field(max_length=80)
    observations: tuple[Reading, ...] = Field(max_length=256)
    disjoint_subscope_coverage: bool = False

    @model_validator(mode="after")
    def chronology(self):
        if (
            self.scope_end_at < self.scope_start_at
            or self.completion.complete
            and (
                self.completion.completed_at is None
                or self.completion.completed_at < self.scope_end_at
                or self.completion.known_at < self.completion.completed_at
            )
        ):
            raise ValueError("Inconsistent measured scope and completion chronology.")
        return self


def selected_actual(scope, cutoff):
    """Select a revision before reducing a measured scope. Preserve genuine zero."""
    groups = {}
    for row in scope.observations:
        if row.known_at <= cutoff and row.scope_id == scope.scope_id:
            groups.setdefault(row.logical_observation_id or row.observation_id, []).append(row)
    rows = []
    for revisions in groups.values():
        highest = max(r.revision for r in revisions)
        current = [r for r in revisions if r.revision == highest]
        if any(
            r.model_dump(exclude={"observation_id"})
            != current[0].model_dump(exclude={"observation_id"})
            for r in current[1:]
        ):
            return None, [], [], "conflicting_observation_revision"
        if not current[0].retracted:
            rows.append(current[0])
    refs = sorted(f"{r.observation_id}@{r.revision}" for r in rows)
    if not rows:
        return None, refs, [], "missing_actual_observations"
    totals = [r for r in rows if r.kind == "duration_total"]
    intervals = [r for r in rows if r.kind == "active_interval"]
    if len(totals) > 1:
        return None, refs, [], "ambiguous_multiple_totals"
    if totals and not intervals:
        return Fraction(totals[0].minutes), refs, [], None
    if totals and (
        not totals[0].representation_group
        or any(r.representation_group != totals[0].representation_group for r in intervals)
    ):
        return None, refs, [], "mixed_actual_representations"
    from canvas_bridge.planning import subtract

    covered = []
    for row in intervals:
        if row.start < scope.scope_start_at or row.end > scope.scope_end_at:
            return None, refs, [], "interval_outside_actual_scope"
        chunks = [(row.start, row.end)]
        for pause in row.pauses:
            chunks = subtract(chunks, pause.start, pause.end)
        covered.extend(chunks)
    spans = union(covered)
    minutes = sum((elapsed(s, e) for s, e in spans), Fraction())
    if totals and minutes != totals[0].minutes:
        return None, refs, spans, "conflicting_linked_measurements"
    return minutes, refs, spans, None


def stage6_scope(actual: Actual, forecast: Forecast, *, owner, family, policy):
    """Adapt already authorized Stage 6 records; historical frozen values stay immutable."""
    if (actual.forecast_id, actual.forecast_version, set(actual.course_ids)) != (
        forecast.key,
        forecast.version,
        set(forecast.course_ids),
    ):
        raise ValueError("Forecast reference or course does not match the actual.")
    if forecast.origin not in {
        "student_estimate",
        "instructor_estimate",
        "rule_of_thumb",
        "assistant_estimate",
    }:
        raise ValueError("Unrecognized original Stage 6 estimate basis.")
    reason = mismatch(actual, forecast)
    if reason:
        raise ValueError(reason)
    start = forecast.effective_at or forecast.observed_at
    duration = (
        actual.minutes - (actual.minutes_before_scope or 0)
        if actual.duration_basis == "cumulative"
        else actual.minutes
    )
    scope_start = start if actual.duration_basis == "cumulative" else actual.start
    return HistoryScope(
        history_id=actual.key,
        user_id=owner,
        episode_id=actual.unit_id,
        scope_id=actual.scope_id,
        scope_kind="remaining_episode"
        if forecast.scope_kind == "remaining_work"
        else "whole_episode",
        task_family=family,
        baseline_policy=policy,
        scope_start_at=scope_start,
        scope_end_at=actual.completion or actual.start,
        completion=Completion(
            complete=actual.completed,
            completed_at=actual.completion,
            known_at=actual.observed_at,
            basis=actual.basis,
        ),
        coverage=Coverage(
            state="complete" if actual.complete_duration else "partial",
            known_at=actual.observed_at,
            basis=actual.basis,
        ),
        forecasts=[
            Issued(
                forecast_id=forecast.key,
                scope_id=forecast.scope_id,
                frozen_at=start,
                known_at=forecast.observed_at,
                baseline_policy=policy,
                baseline_origin=forecast.origin,
                baseline=Estimate(
                    low=forecast.minimum, high=forecast.maximum, point=forecast.point
                ),
                published=Estimate(
                    low=forecast.minimum, high=forecast.maximum, point=forecast.point
                ),
                budget=forecast.budget,
            )
        ],
        observations=[
            Reading(
                observation_id=actual.key,
                scope_id=actual.scope_id,
                revision=actual.version,
                known_at=actual.observed_at,
                kind="duration_total",
                basis=actual.basis,
                minutes=duration,
            )
        ],
    )
