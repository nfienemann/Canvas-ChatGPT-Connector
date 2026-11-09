"""Typed report windows and source observations. Only adapters assign source basis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import FactDate, Model, WorkItem
from canvas_bridge.evidence import fingerprint

if TYPE_CHECKING:
    from canvas_bridge.analytics.measurements import (
        Action,
        Actual,
        FindingSample,
        Forecast,
        Instrumentation,
        Schedule,
    )

Ref = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]
Minutes = Annotated[int, Field(ge=0, le=100_000, strict=True)]
Family = Literal[
    "deadline_outcomes",
    "personal_completion",
    "schedule_conflicts",
    "effort_calibration",
    "coordination",
]
FAMILIES = (
    "deadline_outcomes",
    "personal_completion",
    "schedule_conflicts",
    "effort_calibration",
    "coordination",
)


class Period(Model):
    start: AwareDatetime
    end: AwareDatetime
    accepted_snapshot: Ref | None = None
    proposed_snapshot: Ref | None = None

    @model_validator(mode="after")
    def bounds(self):
        self.start, self.end = self.start.astimezone(UTC), self.end.astimezone(UTC)
        if not timedelta(0) < self.end - self.start <= timedelta(days=31):
            raise ValueError("Use a positive reporting window of at most 31 elapsed days.")
        return self

    def contains(self, instant):
        return instant is not None and self.start <= instant.astimezone(UTC) < self.end


class Review(Model):
    course_ids: list[Ref] = Field(min_length=1, max_length=24)
    windows: list[Period] = Field(min_length=1, max_length=2)
    timezone: str = Field(max_length=100)
    as_of: AwareDatetime
    evidence_cutoff: AwareDatetime
    families: list[Family] = Field(
        default_factory=lambda: list(FAMILIES), min_length=1, max_length=5
    )
    restates: Ref | None = None

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError("Choose an IANA timezone.") from exc
        if len(set(self.course_ids)) != len(self.course_ids) or len(set(self.families)) != len(
            self.families
        ):
            raise ValueError("Select each course and family once.")
        self.as_of = self.as_of.astimezone(UTC)
        self.evidence_cutoff = self.evidence_cutoff.astimezone(UTC)
        self.course_ids = sorted(self.course_ids)
        self.families = [f for f in FAMILIES if f in self.families]
        if self.as_of > self.evidence_cutoff or any(w.end > self.as_of for w in self.windows):
            raise ValueError(
                "Close report windows by as_of and use an evidence cutoff at or after as_of."
            )
        if len(self.windows) == 2 and self.windows[0].end > self.windows[1].start:
            raise ValueError("Choose two ordered, disjoint reporting periods.")
        return self


class Binding(Model):
    course_id: Ref
    work_id: Ref
    source_version: str = Field(max_length=100)


class Stamp(Model):
    key: Ref
    version: int = Field(default=1, ge=1)
    observed_at: AwareDatetime
    effective_at: AwareDatetime | None = None
    source_recorded_at: AwareDatetime | None = None
    event_time_known: bool = True
    # Multi-course facts (e.g. a calendar snapshot) require the whole scope.
    course_ids: list[Ref] = Field(min_length=1, max_length=24)
    parent_sources: list[Binding] = Field(default_factory=list, max_length=5000)
    source_ref: str = Field(min_length=1, max_length=220)
    basis: Literal[
        "provider_observation",
        "student_declaration",
        "accepted_plan",
        "proposed_plan",
        "confirmed_action_receipt",
        "system_diagnostic",
    ]

    def eligible(self, request):
        return (
            set(self.course_ids) <= set(request.course_ids)
            and self.observed_at <= request.evidence_cutoff
            and (self.effective_at or self.observed_at) <= request.as_of
        )

    def ordering(self):
        return self.observed_at, self.version, self.source_ref

    def citation(self):
        return {
            "key": self.key,
            "course_ids": self.course_ids,
            "source_ref": self.source_ref,
            "version": self.version,
            "basis": self.basis,
            "observed_at": self.observed_at.isoformat(),
            "effective_at": self.effective_at.isoformat()
            if self.effective_at and self.event_time_known
            else None,
            "source_recorded_at": self.source_recorded_at.isoformat()
            if self.source_recorded_at
            else None,
            "temporal_basis": "event_time"
            if self.effective_at and self.event_time_known
            else "observation_time",
        }


class Due(Stamp):
    due: FactDate
    exclusion: (
        Literal["excused", "cancelled", "optional", "child_step", "requirement_unresolved"] | None
    ) = None


class Outcome(Stamp):
    state: Literal["on_time", "late", "missing", "unknown", "not_applicable"]
    submitted_at: AwareDatetime | None = None


class Declaration(Stamp):
    status: Literal["student_marked_done", "not_started", "in_progress", "unknown"]
    revision_state: str = "unknown"


@dataclass
class History:
    dues: list[Due] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    progress: list[Declaration] = field(default_factory=list)
    instrumentation: list[Instrumentation] = field(default_factory=list)
    findings: list[FindingSample] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)
    forecasts: list[Forecast] = field(default_factory=list)
    actuals: list[Actual] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    bindings: set[tuple[str, str, str]] = field(default_factory=set)
    scanned: dict[str, int] = field(default_factory=dict)


def latest(rows, request):
    """Select one version per course-qualified logical identity, independent of input order."""
    selected = {}
    revisions = {}
    for row in rows:
        if not row.eligible(request):
            continue
        key = tuple(sorted(row.course_ids)), row.key
        version = key, row.ordering()
        if version in revisions and revisions[version] != row:
            raise ValueError("Conflicting observations share an identity and version.")
        revisions[version] = row
        if key not in selected or selected[key].ordering() < row.ordering():
            selected[key] = row
    return dict(sorted(selected.items()))


def work_facts(history: History, item: WorkItem, snapshot_id: str, captured: datetime):
    """WorkItem.id is the owner/connection/course-qualified canonical Canvas identity."""
    history.bindings.add((item.course_id, item.id, item.source.content_hash or ""))
    stamp = dict(
        key=item.id,
        course_ids=[item.course_id],
        observed_at=captured,
        source_ref=snapshot_id + "/" + item.id,
        basis="provider_observation",
    )
    history.dues.append(
        Due(
            **stamp,
            due=item.effective_due,
            exclusion="excused" if item.assessment_state == "excused" else None,
        )
    )
    history.outcomes.append(
        Outcome(**stamp, state=item.timeliness_state, submitted_at=item.submitted_at)
    )
    history.progress.append(
        Declaration(
            **(stamp | {"basis": "student_declaration"}),
            status=item.personal_progress,
            revision_state=item.revision_state,
        )
    )


def version_id(*parts):
    return fingerprint(list(parts))[:40]
