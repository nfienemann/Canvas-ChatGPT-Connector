"""Deterministic bounded scheduling with effort ranges and explicit shortfalls."""

from datetime import UTC, timedelta

from pydantic import AwareDatetime, Field, field_validator, model_validator

from canvas_bridge.processes.models import Model, Ref


class TimeWindow(Model):
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def positive(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=31):
            raise ValueError("Window must be positive and at most 31 days.")
        return self


class WorkEstimate(Model):
    id: Ref
    minimum_minutes: int = Field(ge=1, le=10080)
    maximum_minutes: int = Field(ge=1, le=10080)
    deadline: AwareDatetime
    prerequisites: tuple[Ref, ...] = Field(default=(), max_length=100)

    @field_validator("deadline")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum_minutes > self.maximum_minutes or self.id in self.prerequisites:
            raise ValueError("Invalid effort range or dependency.")
        return self


def free_windows(availability, commitments, *, now, buffer_minutes):
    merged = []
    for slot in sorted(availability, key=lambda w: w.start):
        start, end = max(now, slot.start), slot.end
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for busy in commitments:
        parts = []
        for start, end in merged:
            if busy.start >= end or busy.end <= start:
                parts.append((start, end))
            else:
                if start < busy.start:
                    parts.append((start, busy.start))
                if busy.end < end:
                    parts.append((busy.end, end))
        merged = parts
    buffer = timedelta(minutes=buffer_minutes)
    return [
        (start + buffer, end - buffer) for start, end in merged if start + buffer < end - buffer
    ]


def simulate(
    work, availability, commitments, *, now, buffer_minutes=10, break_minutes=10, focus_minutes=50
):
    now = now.astimezone(UTC)
    if (
        not 0 <= buffer_minutes <= 120
        or not 0 <= break_minutes <= 60
        or not 1 <= focus_minutes <= 120
    ):
        raise ValueError("Invalid rest/buffer configuration.")
    if len(work) > 100 or len(availability) > 100 or len(commitments) > 200:
        raise ValueError("Planning budget exceeded.")
    tasks = {w.id: w for w in work}
    if len(tasks) != len(work) or any(p not in tasks for w in work for p in w.prerequisites):
        raise ValueError("Duplicate task or missing prerequisite.")
    # Validate the DAG, and move predecessor scheduling priority to its earliest dependent deadline.
    unresolved, order = set(tasks), []
    while unresolved:
        ready = sorted(k for k in unresolved if not (set(tasks[k].prerequisites) & unresolved))
        if not ready:
            raise ValueError("Prerequisite cycle.")
        order.extend(ready)
        unresolved -= set(ready)
    priority = {k: w.deadline for k, w in tasks.items()}
    for key in reversed(order):
        for parent in tasks[key].prerequisites:
            priority[parent] = min(priority[parent], priority[key])
    windows = free_windows(availability, commitments, now=now, buffer_minutes=buffer_minutes)
    capacity = sum(int((end - start).total_seconds() // 60) for start, end in windows)
    cases = []
    for mode in ("optimistic", "midpoint", "pessimistic"):
        effort = {
            w.id: w.minimum_minutes
            if mode == "optimistic"
            else w.maximum_minutes
            if mode == "pessimistic"
            else (w.minimum_minutes + w.maximum_minutes + 1) // 2
            for w in work
        }
        remaining, complete, blocks, shortfall = set(tasks), {}, [], {}
        free = list(windows)
        while remaining:
            ready = [k for k in remaining if set(tasks[k].prerequisites) <= complete.keys()]
            if not ready:
                shortfall.update({k: effort[k] for k in remaining})
                break
            key = min(ready, key=lambda k: (priority[k], k))
            task, minutes = tasks[key], effort[key]
            earliest = max([now, *(complete[p] for p in task.prerequisites)])
            last_end = earliest
            for i, (start, end) in enumerate(free):
                start, limit = max(start, earliest), min(end, task.deadline)
                while minutes and start < limit:
                    duration = min(
                        minutes, focus_minutes, int((limit - start).total_seconds() // 60)
                    )
                    if duration <= 0:
                        break
                    finish = start + timedelta(minutes=duration)
                    blocks.append(
                        {
                            "work_id": key,
                            "start": start.isoformat(),
                            "end": finish.isoformat(),
                            "minutes": duration,
                        }
                    )
                    minutes -= duration
                    last_end = finish
                    start = finish + timedelta(minutes=break_minutes)
                    free[i] = (min(start, end), end)
                if not minutes:
                    break
            remaining.remove(key)
            if minutes:
                shortfall[key] = minutes
            else:
                complete[key] = last_end
        proven_capacity_failure = sum(effort.values()) > capacity or any(
            effort[key]
            > sum(
                max(0, int((min(end, tasks[key].deadline) - start).total_seconds() // 60))
                for start, end in windows
            )
            for key in tasks
        )
        cases.append(
            {
                "case": mode,
                "status": "feasible"
                if not shortfall
                else "infeasible"
                if proven_capacity_failure
                else "no_feasible_schedule_found",
                "blocks": sorted(blocks, key=lambda b: b["start"]),
                "shortfall_minutes": shortfall,
                "effort_minutes": effort,
                "capacity_minutes_before_breaks": capacity,
            }
        )
    return {
        "status": "feasible"
        if all(c["status"] == "feasible" for c in cases)
        else "infeasible"
        if all(c["status"] == "infeasible" for c in cases)
        else "at_risk",
        "cases": cases,
        "assumptions": [
            "User-adjustable effort ranges",
            "User-supplied availability and commitments",
            "Greedy schedules are not proof that no alternative exists",
        ],
        "calendar_changed": False,
        "external_write_requires_separate_preview_and_consent": True,
    }
