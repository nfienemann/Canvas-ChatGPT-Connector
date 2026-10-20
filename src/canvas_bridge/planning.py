"""Deterministic prioritization and conservative allocation; no inference service."""

from datetime import datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import Effort, Model, WorkItem
from canvas_bridge.planning_dates import instant, resolve_timing


class Window(Model):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def valid(self):
        self.start, self.end = instant(self.start), instant(self.end)
        if self.end <= self.start or self.end - self.start > timedelta(days=1):
            raise ValueError("Availability windows must be positive and at most one day.")
        return self


class PinnedBlock(Window):
    work_id: str = Field(min_length=1, max_length=100)


class Importance(Model):
    grade_weight_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    basis: Literal["student_provided"] = "student_provided"
    explanation: str = Field(min_length=1, max_length=500)


class PlanRequest(Model):
    windows: list[Window] = Field(default_factory=list, max_length=100)
    busy_times: list[Window] = Field(default_factory=list, max_length=100)
    pinned_blocks: list[PinnedBlock] = Field(default_factory=list, max_length=100)
    effort_overrides: dict[str, Effort] = Field(default_factory=dict, max_length=100)
    priority_overrides: dict[str, Annotated[int, Field(ge=0, le=10)]] = Field(
        default_factory=dict, max_length=100
    )
    importance: dict[str, Importance] = Field(default_factory=dict, max_length=100)
    date_only_timezones: dict[str, Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=dict, max_length=100
    )
    opportunity_minutes: int = Field(default=45, ge=5, le=720)
    break_minutes: int = Field(default=10, ge=0, le=60)
    buffer_minutes: int = Field(default=10, ge=0, le=120)
    max_block_minutes: int = Field(default=50, ge=10, le=180)
    minimum_block_minutes: int = Field(default=15, ge=5, le=180)
    availability_origin: Literal["student_input", "provided_via_conversation"] = "student_input"

    @model_validator(mode="after")
    def consistent(self):
        for zone in self.date_only_timezones.values():
            try:
                ZoneInfo(zone)
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise ValueError("Date-only planning requires valid IANA timezones.") from exc
        if self.minimum_block_minutes > self.max_block_minutes:
            raise ValueError("Minimum block exceeds maximum block.")
        ordered = sorted(self.windows, key=lambda w: w.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Availability windows overlap.")
        if ordered and ordered[-1].end - ordered[0].start > timedelta(days=31):
            raise ValueError("Plan horizon exceeds 31 days.")
        pins = sorted(self.pinned_blocks, key=lambda w: w.start)
        if any(a.end > b.start for a, b in zip(pins, pins[1:], strict=False)):
            raise ValueError("Pinned blocks overlap.")
        if pins and not ordered:
            raise ValueError("Pinned blocks require explicit availability windows.")
        return self


def is_actionable(item: WorkItem) -> bool:
    if item.assessment_state == "excused" or (
        item.assessment_state == "graded" and item.revision_state in {"none_known", "unknown"}
    ):
        return False
    if item.availability_state in {"closed", "inaccessible", "future_locked"}:
        return False
    if (
        item.submission_state == "not_applicable"
        and item.personal_progress == "student_marked_done"
    ):
        return False
    return not (
        item.submission_state in {"submitted", "resubmitted"}
        and item.revision_state in {"none_known", "unknown"}
    )


def prioritize(
    items: list[WorkItem],
    now: datetime,
    opportunity: int,
    overrides=None,
    importance=None,
    timings=None,
) -> list[dict]:
    now = instant(now)
    overrides, importance = overrides or {}, importance or {}
    ranked = []
    for item in items:
        if not is_actionable(item):
            continue
        timing = timings[item.id] if timings else resolve_timing(item, now)
        due = item.effective_due.timestamp
        hard_limit = timing.deadline
        hours = (hard_limit - now).total_seconds() / 3600 if hard_limit else None
        undated = item.effective_due.kind not in {"timestamp", "local_date"}
        if timing.blocked:
            tier, reason = (
                3,
                "Source timing needs clarification before study blocks can be allocated.",
            )
        elif undated and not hard_limit:
            tier, reason = (
                3,
                "Timing is unknown; confirm whether this assessment is still relevant.",
            )
        elif item.prerequisites:
            tier, reason = 3, "Known prerequisite work needs to be completed first."
        elif timing.overdue or (hours is not None and hours <= 24):
            tier, reason = 0, "Due or closing within a day, or overdue; check recoverability."
        elif hours is not None and hours <= 72:
            tier, reason = 1, "Limited time remains before the source deadline."
        else:
            tier, reason = 2, "A reported date leaves more time; review the remaining work."
        effort = item.effort_remaining
        minutes = min(opportunity, effort.maximum_minutes) if effort else min(opportunity, 15)
        action = (
            f"Verify the Canvas submission receipt for {item.title}; you marked the work done, so do not redo it based only on this status."
            if item.personal_progress == "student_marked_done"
            else f"Confirm the source date, timezone or availability for {item.title} before scheduling it."
            if timing.blocked
            else f"Confirm when {item.title} takes place and whether any work remains before scheduling it."
            if undated and not hard_limit
            else f"Work on {item.title} for up to {minutes} minutes."
            if effort
            else f"Spend up to {minutes} minutes reviewing the requirements for {item.title} "
            "and estimating the remaining work."
        )
        ranked.append(
            {
                "work_id": item.id,
                "title": item.title,
                "priority_tier": tier,
                "urgency": {0: "immediate", 1: "soon", 2: "later", 3: "unresolved"}[tier],
                "importance": importance[item.id].model_dump(mode="json")
                if item.id in importance
                else None,
                "student_priority": overrides.get(item.id),
                "ranking_basis": "Student overrides first (0 highest), then urgency, then stated grade weight, then deadline. Unknown grade impact is not zero; points alone are not course weight.",
                "reason": reason,
                "first_action": action,
                "action_minutes": minutes,
                "effort_remaining": effort.model_dump(mode="json") if effort else None,
                "timing": timing.evidence(item),
                "uncertainties": [
                    *(
                        []
                        if effort
                        else ["Remaining effort is unknown; the first action is a bounded review."]
                    ),
                    *([] if due else ["A timed deadline is not available."]),
                    *(
                        []
                        if item.prerequisite_coverage == "known"
                        else ["Prerequisite coverage is unknown."]
                    ),
                    *(
                        []
                        if item.availability_state == "available"
                        else ["Current availability needs checking."]
                    ),
                ],
                "_sort": (
                    overrides.get(item.id, 11),
                    tier,
                    -importance[item.id].grade_weight_percent if item.id in importance else 1,
                    hard_limit or datetime.max.replace(tzinfo=now.tzinfo),
                    item.id,
                ),
            }
        )
    ranked.sort(key=lambda row: row.pop("_sort"))
    return ranked


def subtract(windows: list[list[datetime]], start: datetime, end: datetime):
    """Remove a commitment from capacity without inventing calendar free time."""
    result = []
    for left, right in windows:
        if end <= left or start >= right:
            result.append([left, right])
        else:
            if left < start:
                result.append([left, start])
            if end < right:
                result.append([end, right])
    return result


def propose(items: list[WorkItem], request: PlanRequest, now: datetime) -> dict:
    now = instant(now)
    by_id = {item.id: item.model_copy(deep=True) for item in items}
    if (
        set(request.effort_overrides)
        | set(request.priority_overrides)
        | set(request.importance)
        | set(request.date_only_timezones)
    ) - by_id.keys():
        raise ValueError("Planning input references a task outside this workload.")
    for key, effort in request.effort_overrides.items():
        by_id[key].effort_remaining = effort
    for item in by_id.values():
        if item.personal_progress == "student_marked_done" and item.revision_state in {
            "none_known",
            "unknown",
        }:
            # Keep an online-submission verification reminder, but do not
            # allocate work sessions for something the student says is done.
            item.effort_remaining = None
    timings = {
        ref: resolve_timing(item, now, request.date_only_timezones.get(ref))
        for ref, item in by_id.items()
    }
    timing_evidence = {ref: timing.evidence(by_id[ref]) for ref, timing in timings.items()}
    ranked = prioritize(
        list(by_id.values()),
        now,
        request.opportunity_minutes,
        request.priority_overrides,
        request.importance,
        timings,
    )
    if not request.windows:
        return {
            "feasibility": "availability_unknown",
            "recommendations": ranked[:5],
            "blocks": [],
            "unmet_work": [],
            "timing_constraints": timing_evidence,
            "assumptions": ["No calendar access or free time has been independently verified."],
        }
    windows = []
    for window in sorted(request.windows, key=lambda w: w.start):
        start = max(window.start, now)
        end = window.end - timedelta(minutes=request.buffer_minutes)
        if start < end:
            windows.append([start, end])
    for busy in request.busy_times:
        windows = subtract(windows, busy.start, busy.end)
    blocks, unmet, pinned_minutes, pinned_end = [], [], {}, {}
    for pin in sorted(request.pinned_blocks, key=lambda w: w.start):
        if pin.work_id not in by_id or not is_actionable(by_id[pin.work_id]):
            raise ValueError("Pinned block references work that is not currently actionable.")
        if pin.start < now or not any(a <= pin.start and pin.end <= b for a, b in windows):
            raise ValueError(
                "Pinned block conflicts with availability, busy time, buffer or another block."
            )
        minutes = int((pin.end - pin.start).total_seconds() // 60)
        if minutes < 1:
            raise ValueError("Pinned blocks must last at least one minute.")
        item = by_id[pin.work_id]
        timing = timings[pin.work_id]
        if timing.blocked:
            raise ValueError("Pinned block requires resolved source timing: " + timing.blocked)
        if (timing.opens and pin.start < timing.opens) or (
            timing.deadline and pin.end > timing.deadline
        ):
            raise ValueError(
                "Pinned block conflicts with source timing or a conservative date-only planning bound."
            )
        pinned_minutes[pin.work_id] = pinned_minutes.get(pin.work_id, 0) + minutes
        pinned_end[pin.work_id] = max(pin.end, pinned_end.get(pin.work_id, pin.end))
        blocks.append(
            {
                "work_id": pin.work_id,
                "start": pin.start.isoformat(),
                "end": pin.end.isoformat(),
                "minutes": minutes,
                "pinned": True,
                "overdue_recovery": timing.overdue,
            }
        )
        windows = subtract(
            windows,
            pin.start - timedelta(minutes=request.break_minutes),
            pin.end + timedelta(minutes=request.break_minutes),
        )
    completed_at = {
        item.id: now
        for item in items
        if item.assessment_state == "excused"
        or (
            item.submission_state in {"submitted", "resubmitted"}
            and item.revision_state == "none_known"
        )
        or (
            item.submission_state == "not_applicable"
            and item.personal_progress == "student_marked_done"
        )
    }
    # Visit prerequisites before their dependents, retaining rank among unrelated tasks.
    pending = [row["work_id"] for row in ranked]
    ordered, visiting, visited = [], set(), set()

    def visit(ref):
        if ref in visited or ref in visiting:
            return
        visiting.add(ref)
        for prerequisite in by_id[ref].prerequisites:
            if prerequisite in pending:
                visit(prerequisite)
        visiting.remove(ref)
        visited.add(ref)
        ordered.append(ref)

    for ref in pending:
        visit(ref)
    for ref in ordered:
        item = by_id[ref]
        timing = timings[ref]
        if timing.blocked:
            unmet.append({"work_id": item.id, "reason": timing.blocked, "minutes": None})
            continue
        if (
            item.effective_due.kind not in {"timestamp", "local_date"}
            and not timing.deadline
            and ref not in request.effort_overrides
            and ref not in pinned_minutes
            and item.personal_progress != "in_progress"
        ):
            unmet.append(
                {"work_id": item.id, "reason": "schedule_and_relevance_unknown", "minutes": None}
            )
            continue
        effort = item.effort_remaining
        if not effort:
            unmet.append({"work_id": item.id, "reason": "effort_unknown", "minutes": None})
            continue
        if set(item.prerequisites) - completed_at.keys():
            unmet.append(
                {
                    "work_id": item.id,
                    "reason": "prerequisite_unallocated",
                    "minutes": effort.maximum_minutes,
                }
            )
            continue
        earliest = max([now, timing.opens or now, *(completed_at[p] for p in item.prerequisites)])
        item_pins = [p for p in request.pinned_blocks if p.work_id == item.id]
        if any(p.start < earliest for p in item_pins):
            unmet.append(
                {
                    "work_id": item.id,
                    "reason": "pinned_prerequisite_conflict",
                    "minutes": max(0, effort.maximum_minutes - pinned_minutes.get(item.id, 0)),
                }
            )
            continue
        remaining = max(0, effort.maximum_minutes - pinned_minutes.get(item.id, 0))
        finish = pinned_end.get(item.id, now)
        # Overdue-but-open work uses the close time and labels lateness, not an invented extension.
        deadline, overdue = timing.deadline, timing.overdue
        for window in windows:
            while remaining > 0:
                cursor, window_end = max(window[0], earliest), window[1]
                end = min(window_end, deadline) if deadline else window_end
                usable = int((end - cursor).total_seconds() // 60)
                if usable < min(request.minimum_block_minutes, remaining):
                    break
                minutes = min(remaining, usable, request.max_block_minutes)
                block_end = cursor + timedelta(minutes=minutes)
                blocks.append(
                    {
                        "work_id": item.id,
                        "start": cursor.isoformat(),
                        "end": block_end.isoformat(),
                        "minutes": minutes,
                        "overdue_recovery": overdue,
                        "pinned": False,
                    }
                )
                remaining -= minutes
                finish = max(finish, block_end)
                window[0] = block_end + timedelta(minutes=request.break_minutes)
        if remaining:
            unmet.append(
                {"work_id": item.id, "reason": "insufficient_capacity", "minutes": remaining}
            )
        else:
            completed_at[item.id] = finish
    unknown_constraints = any(
        by_id[row["work_id"]].prerequisite_coverage == "unknown"
        or by_id[row["work_id"]].availability_state != "available"
        or by_id[row["work_id"]].effective_due.kind != "timestamp"
        or bool(timings[row["work_id"]].assumptions)
        or timings[row["work_id"]].overdue
        for row in ranked
    )
    return {
        "feasibility": "timing_unresolved"
        if unmet
        and all(x["reason"] in {t.blocked for t in timings.values() if t.blocked} for x in unmet)
        else "shortfall"
        if unmet
        else ("provisional" if unknown_constraints else "feasible"),
        "recommendations": ranked[:5],
        "blocks": sorted(blocks, key=lambda b: b["start"]),
        "unmet_work": unmet,
        "timing_constraints": timing_evidence,
        "known_shortfall_minutes": sum(x["minutes"] or 0 for x in unmet),
        "shortfall_basis": "Capacity within reported timing and labeled conservative date-only bounds. Unknown timing is not counted as a numerical shortage.",
        "availability_origin": request.availability_origin,
        "assumptions": [
            "Allocation uses the upper effort estimate.",
            f"Reserve {request.buffer_minutes} minutes per window and {request.break_minutes} minutes between blocks.",
            "Availability was supplied in conversation; no provider was contacted.",
            "Supplied busy times are excluded and pinned sessions are preserved.",
            "Unknown prerequisites or source constraints keep a fitting plan provisional.",
            "Block durations use elapsed UTC minutes, including across daylight-saving changes.",
        ],
    }
