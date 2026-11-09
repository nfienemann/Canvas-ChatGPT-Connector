"""Bounded resource-process inputs. Physical resources have no authority over source access."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.analytics.effort_history import Instant
from canvas_bridge.processes.models import Model, Ref

Minute = Annotated[int, Field(strict=True, ge=0, le=525600)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=5)]
Clock = Literal["elapsed_minutes", "operating_minutes"]


class Span(Model):
    start_at: Instant
    end_at: Instant

    @model_validator(mode="after")
    def ordered(self):
        if self.end_at <= self.start_at:
            raise ValueError("Resource interval must be positive.")
        return self


class OperatingCalendar(Model):
    known_at: Instant | None = None
    source_ref: Ref | None = None
    id: Ref
    revision: Ref
    timezone: Ref
    windows: tuple[Span, ...] = Field(max_length=160)
    coverage: Literal["complete", "partial", "unknown"] = "complete"

    @model_validator(mode="before")
    @classmethod
    def validate_wall_times(cls, raw):
        if isinstance(raw, dict):
            from canvas_bridge.processes.plan_repair import Constraints

            Constraints.wall_times(
                dict(
                    timezone=raw.get("timezone", "UTC"),
                    availability=[
                        dict(start=w.get("start_at"), end=w.get("end_at"))
                        for w in raw.get("windows", ())
                        if isinstance(w, dict)
                    ],
                )
            )
        return raw


class Capacity(Model):
    quantity: Quantity
    unit: Ref


class Booking(Span):
    id: Ref
    revision: Ref
    owner_step_id: Ref
    status: Literal["confirmed", "requested", "tentative", "cancelled", "unknown"]
    quantity: Quantity
    unit: Ref
    source_ref: Ref | None = None


class ResourceCapacity(Model):
    quantity: Quantity | None = None
    unit: Ref | None = None


class CapacityInterval(Span):
    quantity: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=5)]
    revision: Ref
    source_ref: Ref


class Resource(Model):
    capacity_intervals: tuple[CapacityInterval, ...] = Field(default=(), max_length=48)
    aliases: tuple[Ref, ...] = Field(default=(), max_length=16)
    source_ref: Ref | None = None
    known_at: Instant | None = None
    id: Ref
    revision: Ref
    capability: Ref
    capacity: ResourceCapacity
    access_calendar_ref: Ref | None = None
    run_calendar_ref: Ref | None = None
    occupancy_calendar_ref: Ref | None = None
    reservations: tuple[Booking, ...] = Field(default=(), max_length=80)
    unavailable: tuple[Span, ...] = Field(default=(), max_length=80)

    @model_validator(mode="after")
    def unique_bookings(self):
        ordered = sorted(self.capacity_intervals, key=lambda row: row.start_at)
        if any(a.end_at > b.start_at for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Capacity intervals for one resource must be disjoint.")
        unique(self.reservations)
        return self


def unique(rows):
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("Duplicate logical identity.")


class Inventory(Model):
    resources: tuple[Resource, ...] = Field(max_length=32)
    calendars: tuple[OperatingCalendar, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def identities(self):
        unique(self.resources)
        names = [name for r in self.resources for name in (r.id, *r.aliases)]
        if len(names) != len(set(names)):
            raise ValueError("A physical resource alias must resolve uniquely.")
        unique(self.calendars)
        return self


class Duration(Model):
    minimum_minutes: Minute | None = None
    maximum_minutes: Minute | None = None
    clock: Clock = "elapsed_minutes"
    source_ref: Ref


class Requirement(Capacity):
    resource_ids: tuple[Ref, ...] = Field(min_length=1, max_length=16)
    capability: Ref
    booking_required: bool = False


class Phase(Model):
    id: Ref
    work_lineage_id: Ref
    episode_id: Ref
    scope_state: Literal["current", "retired", "completed"] = "current"
    mode: Literal["active", "unattended"]
    run_duration: Duration
    setup_minutes: Minute = 0
    cleanup_minutes: Minute = 0
    turnaround_minutes: Minute = 0
    divisible: bool = False
    occupancy_policy: Literal["none", "continuous", "unknown"]
    resource_requirement: Requirement | None = None
    priority: int = Field(default=5, ge=0, le=100)


class Edge(Model):
    from_step: Ref
    to_step: Ref
    from_anchor: Literal["start", "run_start", "run_end", "finish"] = "finish"
    to_anchor: Literal["start", "run_start", "run_end", "finish"] = "start"
    minimum_lag_minutes: Minute | None = 0
    maximum_lag_minutes: Minute | None = None
    clock: Clock = "elapsed_minutes"
    calendar_ref: Ref | None = None
    maximum_inclusive: bool = True


class Lead(Duration):
    anchor: Instant
    deadline: Instant
    source_available: bool = True
    calendar_ref: Ref | None = None


class Supply(Model):
    required_quantity: Quantity | None = None
    available_quantity: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=5)] | None = (
        None
    )
    unit: Ref | None = None
    id: Ref
    revision: Ref
    step_id: Ref
    ready_at: Instant | None = None
    source_available: bool = True
    lead: Lead | None = None


class History(Model):
    episode_id: Ref
    completion: Ref
    active_minutes: Minute | None = None
    source_revision: Ref


class Mapping(Model):
    active_demand_scope_id: Ref
    basis: Literal["phase_partition", "explicit_phase_override"]
    parent_remaining_minutes: Minute | None = None
    parent_forecast_ref: Ref
    phase_scope_refs: tuple[Ref, ...] = Field(max_length=32)
    override_ref: Ref | None = None
    override_minutes: Minute | None = None


class Process(Model):
    id: Ref
    revision: Ref
    steps: tuple[Phase, ...] = Field(min_length=1, max_length=32)
    dependencies: tuple[Edge, ...] = Field(default=(), max_length=80)
    supplies: tuple[Supply, ...] = Field(default=(), max_length=32)
    historical_episodes: tuple[History, ...] = Field(default=(), max_length=32)
    active_demand_mapping: Mapping | None = None


class Placement(Model):
    placement_id: Ref
    step_id: Ref
    episode_id: Ref
    start_at: Instant
    resource_id: Ref | None = None
    booking_id: Ref | None = None
    run_minutes: Minute | None = None


class Candidate(Model):
    id: Ref
    placements: tuple[Placement, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def distinct(self):
        if len({p.placement_id for p in self.placements}) != len(self.placements):
            raise ValueError("Duplicate placement identity.")
        return self


class Block(Span):
    id: Ref
    step_id: Ref
    episode_id: Ref
    protected: bool = False


class Schedule(Model):
    planning_boundary: Instant
    deadline_at: Instant
    student_windows: tuple[Span, ...] = Field(max_length=100)
    busy: tuple[Span, ...] = Field(default=(), max_length=100)
    base_blocks: tuple[Block, ...] = Field(default=(), max_length=128)
    candidates: tuple[Candidate, ...] = Field(default=(), max_length=32)
    buffer_minutes: Minute = 0
    break_minutes: Minute = 0

    @model_validator(mode="after")
    def valid(self):
        unique(self.candidates)
        unique(self.base_blocks)
        if self.deadline_at <= self.planning_boundary:
            raise ValueError("Deadline must follow the planning boundary.")
        return self
