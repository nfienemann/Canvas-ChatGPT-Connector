"""Deterministic prioritization and conservative allocation; no inference service."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import Effort, Model, WorkItem


class Window(Model):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def valid(self):
        if self.end <= self.start or self.end - self.start > timedelta(days=1):
            raise ValueError("Availability windows must be positive and at most one day.")
        return self


class PinnedBlock(Window):
    work_id: str = Field(min_length=1, max_length=100)


class PlanRequest(Model):
    windows: list[Window] = Field(default_factory=list, max_length=100)
    busy_times: list[Window] = Field(default_factory=list, max_length=100)
    pinned_blocks: list[PinnedBlock] = Field(default_factory=list, max_length=100)
    effort_overrides: dict[str, Effort] = Field(default_factory=dict, max_length=100)
    opportunity_minutes: int = Field(default=45, ge=5, le=720)
    break_minutes: int = Field(default=10, ge=0, le=60)
    buffer_minutes: int = Field(default=10, ge=0, le=120)
    max_block_minutes: int = Field(default=50, ge=10, le=180)
    minimum_block_minutes: int = Field(default=15, ge=5, le=180)
    availability_origin: Literal["student_input", "provided_via_conversation"] = "student_input"

    @model_validator(mode="after")
    def consistent(self):
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
    if item.assessment_state == "excused":
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


def prioritize(items: list[WorkItem], now: datetime, opportunity: int) -> list[dict]:
    ranked = []
    for item in items:
        if not is_actionable(item):
            continue
        due = item.effective_due.timestamp
        closes = item.closes_at.timestamp
        hard_limit = min(t for t in (due, closes) if t) if due or closes else None
        hours = (hard_limit - now).total_seconds() / 3600 if hard_limit else None
        undated = item.effective_due.kind not in {"timestamp", "local_date"}
        if undated and not closes:
            tier, reason = (
                3,
                "Timing is unknown; confirm whether this assessment is still relevant.",
            )
        elif item.prerequisites:
            tier, reason = 3, "Known prerequisite work needs to be completed first."
        elif hours is not None and hours <= 24:
            tier, reason = 0, "Due or closing within a day, or overdue; check recoverability."
        elif hours is not None and hours <= 72:
            tier, reason = 1, "Limited time remains before the source deadline."
        else:
            tier, reason = 2, "A reported date leaves more time; review the remaining work."
        effort = item.effort_remaining
        minutes = min(opportunity, effort.maximum_minutes) if effort else min(opportunity, 15)
        action = (
            f"Confirm when {item.title} takes place and whether any work remains before scheduling it."
            if undated and not closes
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
                "reason": reason,
                "first_action": action,
                "action_minutes": minutes,
                "effort_remaining": effort.model_dump(mode="json") if effort else None,
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
                "_sort": (tier, hard_limit or datetime.max.replace(tzinfo=now.tzinfo), item.id),
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
    by_id = {item.id: item.model_copy(deep=True) for item in items}
    if set(request.effort_overrides) - by_id.keys():
        raise ValueError("Effort references a task outside this workload.")
    for key, effort in request.effort_overrides.items():
        by_id[key].effort_remaining = effort
    ranked = prioritize(list(by_id.values()), now, request.opportunity_minutes)
    if not request.windows:
        return {
            "feasibility": "availability_unknown",
            "recommendations": ranked[:5],
            "blocks": [],
            "unmet_work": [],
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
        for limit in (item.effective_due.timestamp, item.closes_at.timestamp):
            if limit and limit >= now and pin.end > limit:
                raise ValueError("Pinned block conflicts with a current source deadline.")
        pinned_minutes[pin.work_id] = pinned_minutes.get(pin.work_id, 0) + minutes
        pinned_end[pin.work_id] = max(pin.end, pinned_end.get(pin.work_id, pin.end))
        blocks.append(
            {
                "work_id": pin.work_id,
                "start": pin.start.isoformat(),
                "end": pin.end.isoformat(),
                "minutes": minutes,
                "pinned": True,
                "overdue_recovery": bool(
                    item.effective_due.timestamp and item.effective_due.timestamp < now
                ),
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
        if (
            item.effective_due.kind not in {"timestamp", "local_date"}
            and not item.closes_at.timestamp
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
        earliest = max([now, *(completed_at[p] for p in item.prerequisites)])
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
        deadline = item.effective_due.timestamp
        overdue = deadline is not None and deadline < now
        if overdue:
            deadline = item.closes_at.timestamp
        if item.closes_at.timestamp:
            deadline = (
                min(deadline, item.closes_at.timestamp) if deadline else item.closes_at.timestamp
            )
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
        for row in ranked
    )
    return {
        "feasibility": "shortfall"
        if unmet
        else ("provisional" if unknown_constraints else "feasible"),
        "recommendations": ranked[:5],
        "blocks": sorted(blocks, key=lambda b: b["start"]),
        "unmet_work": unmet,
        "known_shortfall_minutes": sum(x["minutes"] or 0 for x in unmet),
        "availability_origin": request.availability_origin,
        "assumptions": [
            "Allocation uses the upper effort estimate.",
            f"Reserve {request.buffer_minutes} minutes per window and {request.break_minutes} minutes between blocks.",
            "Availability was supplied in conversation; no provider was contacted.",
            "Supplied busy times are excluded and pinned sessions are preserved.",
            "Unknown prerequisites or source constraints keep a fitting plan provisional.",
        ],
    }
