"""Deterministic prioritization and conservative allocation; no inference service."""

from datetime import datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import Effort, Model, WorkItem
from canvas_bridge.planning_dates import instant, resolve_timing
from canvas_bridge.work_eligibility import completion_reason


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


class PinTimingConflict(ValueError):
    """A retained user pin falls outside a resolved source bound."""


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


def omission_reason(item: WorkItem, *, allow_future=False):
    return completion_reason(item) or (
        "source_" + item.availability_state
        if item.availability_state in {"closed", "inaccessible"}
        else "not_open_now"
        if item.availability_state == "future_locked" and not allow_future
        else None
    )


def is_actionable(item: WorkItem) -> bool:
    return omission_reason(item) is None


def prioritize(
    items: list[WorkItem],
    now: datetime,
    opportunity: int,
    overrides=None,
    importance=None,
    timings=None,
    *,
    allow_future=False,
) -> list[dict]:
    now = instant(now)
    overrides, importance = overrides or {}, importance or {}
    ranked = []
    for item in items:
        if omission_reason(item, allow_future=allow_future):
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
            tier, reason = (
                0,
                (
                    "Selected event preparation should finish within a day, before the event or an earlier source closing bound."
                    if timing.preparation_target
                    else "Due or closing within a day, or overdue; check recoverability."
                ),
            )
        elif hours is not None and hours <= 72:
            tier, reason = (
                1,
                (
                    "Limited time remains for selected event preparation before the event or an earlier source closing bound."
                    if timing.preparation_target
                    else "Limited time remains before the source deadline."
                ),
            )
        else:
            tier, reason = 2, "A reported date leaves more time; review the remaining work."
        effort = item.effort_remaining
        minutes = min(opportunity, effort.maximum_minutes) if effort else min(opportunity, 15)
        receipt_label = (
            "completion evidence"
            if item.source.source_type == "local_document"
            else "Canvas submission receipt"
        )
        action = (
            f"Verify the {receipt_label} for {item.title}; you marked the work done, so do not redo it based only on this status."
            if item.personal_progress == "student_marked_done"
            and item.revision_state in {"none_known", "unknown"}
            else f"Confirm the source date, timezone or availability for {item.title} before scheduling it."
            if timing.blocked
            else f"Confirm when {item.title} takes place and whether any work remains before scheduling it."
            if undated and not hard_limit
            else f"After the reported opening, recheck access and work on {item.title} for up to {minutes} minutes."
            if item.availability_state == "future_locked" and effort
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


def planning_windows(availability, busy_times, now, buffer_minutes):
    windows = []
    for window in sorted(availability, key=lambda w: w.start):
        start = max(window.start, now)
        end = window.end - timedelta(minutes=buffer_minutes)
        if start < end:
            windows.append([start, end])
    for busy in busy_times:
        windows = subtract(windows, busy.start, busy.end)
    return windows


def effort_summary(items, accounting, blocks):
    """Balance upper estimates in work minutes. Keep unestimated work and extra
    reserved time outside that balance (a pin may exceed its work estimate).
    """
    allocated = {}
    for block in blocks:
        ref = block["work_id"]
        allocated[ref] = allocated.get(ref, 0) + block["minutes"]
    known = credited = capacity = dependency = 0
    completed, unknown, receipts = [], [], []
    for ref, item in items.items():
        if completion_reason(item):
            completed.append(ref)
            continue
        if item.personal_progress == "student_marked_done" and item.revision_state in {
            "none_known",
            "unknown",
        }:
            receipts.append(ref)
            continue
        if not item.effort_remaining:
            unknown.append(ref)
            continue
        estimate = item.effort_remaining.maximum_minutes
        planned = min(estimate, allocated.get(ref, 0))
        known += estimate
        credited += planned
        reason = accounting[ref]["reason"]
        if reason == "insufficient_capacity":
            capacity += estimate - planned
        elif reason in {"pinned_prerequisite_conflict", "prerequisite_unallocated"}:
            dependency += estimate - planned
    return {
        "known_remaining_minutes": known,
        "allocated_work_minutes": credited,
        "total_known_unallocated_minutes": known - credited,
        "capacity_blocked_minutes": capacity,
        "dependency_blocked_minutes": dependency,
        "other_unallocated_minutes": known - credited - capacity - dependency,
        "uncredited_block_minutes": sum(allocated.values()) - credited,
        "unknown_effort_work_ids": sorted(unknown),
        "completed_work_ids": sorted(completed),
        "receipt_verification_work_ids": sorted(receipts),
        "receipt_checks": [{"work_id": ref, "title": items[ref].title} for ref in sorted(receipts)],
        "unresolved_requirement_ids": [],
    }


def propose(
    items: list[WorkItem],
    request: PlanRequest,
    now: datetime,
    *,
    preparation_targets=None,
    completed_prerequisites=(),
) -> dict:
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
    preparation_targets = preparation_targets or {}
    if set(preparation_targets) - by_id.keys():
        raise ValueError("Preparation target references work outside this workload.")
    timings = {
        ref: resolve_timing(
            item,
            now,
            request.date_only_timezones.get(ref),
            preparation_target=preparation_targets.get(ref),
        )
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
        allow_future=bool(request.windows),
    )
    omitted = [
        {"work_id": item.id, "reason": reason}
        for item in by_id.values()
        if (reason := omission_reason(item, allow_future=bool(request.windows)))
    ]
    accounting = {
        item.id: {"state": "pending_review", "reason": "availability_unknown"}
        for item in by_id.values()
    }
    for row in omitted:
        accounting[row["work_id"]] = {"state": "omitted", "reason": row["reason"]}
    if not request.windows:
        return {
            "feasibility": "availability_unknown",
            "known_capacity_status": "unknown",
            "information_status": "uncertain",
            "known_shortfall_minutes": 0,
            "omitted_work": omitted,
            "work_accounting": accounting,
            "effort_summary": effort_summary(by_id, accounting, []),
            "recommendations": ranked[:5],
            "blocks": [],
            "pin_conflicts": [],
            "unmet_work": [],
            "timing_constraints": timing_evidence,
            "assumptions": ["No calendar access or free time has been independently verified."],
        }
    windows = planning_windows(request.windows, request.busy_times, now, request.buffer_minutes)
    blocks, unmet, pins_by_work, pin_conflicts = [], [], {}, []
    for pin in sorted(request.pinned_blocks, key=lambda w: w.start):
        if pin.work_id not in by_id or omission_reason(by_id[pin.work_id], allow_future=True):
            raise ValueError("Pinned block references work that is not eligible for planning.")
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
            raise PinTimingConflict(
                "Pinned block conflicts with source timing or a conservative date-only planning bound."
            )
        pins_by_work.setdefault(pin.work_id, []).append(pin)
        # A student pin reserves capacity even when its prerequisites later conflict.
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
            completion_reason(item) == "student_marked_done"
            and item.revision_state in {"none_known", "unknown"}
        )
    }
    completed_at.update(dict.fromkeys(completed_prerequisites, now))
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
        effort = item.effort_remaining
        missing = sorted(set(item.prerequisites) - completed_at.keys())
        earliest = max(
            [
                now,
                timing.opens or now,
                *(completed_at[p] for p in item.prerequisites if p in completed_at),
            ]
        )
        pinned_minutes, finish = 0, now
        conflict = False
        for pin in pins_by_work.get(ref, ()):
            blockers = missing or sorted(
                p for p in item.prerequisites if completed_at[p] > pin.start
            )
            if blockers:
                conflict = True
                pin_conflicts.append(
                    {
                        **pin.model_dump(mode="json"),
                        "reason": "prerequisite_unallocated"
                        if missing
                        else "prerequisite_finishes_after_pin_starts",
                        "prerequisites": blockers,
                        "next_action": "Review the prerequisite work. Move the pin after it can finish, revise its remaining effort, or make more time before the pin.",
                    }
                )
                continue
            minutes = int((pin.end - pin.start).total_seconds() // 60)
            blocks.append(
                {
                    "work_id": ref,
                    "start": pin.start.isoformat(),
                    "end": pin.end.isoformat(),
                    "minutes": minutes,
                    "pinned": True,
                    "overdue_recovery": timing.overdue,
                    "conditional_on_future_access": item.availability_state == "future_locked",
                }
            )
            pinned_minutes += minutes
            finish = max(finish, pin.end)
        remaining = max(0, effort.maximum_minutes - pinned_minutes) if effort else None
        if missing or conflict:
            unmet.append(
                {
                    "work_id": ref,
                    "reason": "pinned_prerequisite_conflict"
                    if conflict
                    else "prerequisite_unallocated",
                    "minutes": remaining,
                }
            )
            continue
        if (
            item.effective_due.kind not in {"timestamp", "local_date"}
            and not timing.deadline
            and ref not in request.effort_overrides
            and not pinned_minutes
            and item.personal_progress != "in_progress"
        ):
            unmet.append(
                {"work_id": item.id, "reason": "schedule_and_relevance_unknown", "minutes": None}
            )
            continue
        if not effort:
            unmet.append({"work_id": item.id, "reason": "effort_unknown", "minutes": None})
            continue
        # Overdue-but-open work uses the close time and labels lateness, not an invented extension.
        deadline, overdue = timing.deadline, timing.overdue
        for left, window_end in list(windows):
            cursor = max(left, earliest)
            while remaining > 0:
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
                        "conditional_on_future_access": item.availability_state == "future_locked",
                    }
                )
                remaining -= minutes
                finish = max(finish, block_end)
                windows = subtract(
                    windows,
                    cursor - timedelta(minutes=request.break_minutes),
                    block_end + timedelta(minutes=request.break_minutes),
                )
                cursor = block_end + timedelta(minutes=request.break_minutes)
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
    known_shortfall = sum(
        x["minutes"] or 0 for x in unmet if x["reason"] == "insufficient_capacity"
    )
    uncertain = (
        unknown_constraints
        or any(x["reason"] != "insufficient_capacity" for x in unmet)
        or any(x["reason"] in {"source_closed", "source_inaccessible"} for x in omitted)
    )
    for row in ranked:
        ref = row["work_id"]
        pending = next((x for x in unmet if x["work_id"] == ref), None)
        accounting[ref] = {
            "state": "unmet" if pending else "allocated",
            "reason": pending["reason"] if pending else None,
            "allocated_minutes": sum(b["minutes"] for b in blocks if b["work_id"] == ref),
        }
    return {
        "feasibility": "timing_unresolved"
        if unmet
        and all(x["reason"] in {t.blocked for t in timings.values() if t.blocked} for x in unmet)
        else "shortfall"
        if known_shortfall
        else ("provisional" if uncertain else "feasible"),
        "known_capacity_status": "shortfall" if known_shortfall else "fits",
        "information_status": "uncertain" if uncertain else "sufficient",
        "omitted_work": omitted,
        "work_accounting": accounting,
        "effort_summary": effort_summary(by_id, accounting, blocks),
        "recommendations": ranked[:5],
        "blocks": sorted(blocks, key=lambda b: b["start"]),
        "pin_conflicts": sorted(pin_conflicts, key=lambda p: p["start"]),
        "unmet_work": unmet,
        "timing_constraints": timing_evidence,
        "known_shortfall_minutes": known_shortfall,
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
