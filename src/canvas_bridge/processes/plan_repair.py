"""Bounded repair of accepted study blocks with the planning.propose end-buffer policy."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from canvas_bridge.analytics.effort_history import Instant, Interval, Minutes, elapsed, union
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning import planning_windows, subtract
from canvas_bridge.processes.models import Model, Ref


class Task(Model):
    task_id: Ref
    episode_id: Ref
    required_minutes: Minutes | None = None
    priority: int = Field(default=5, ge=0, le=100)
    deadline: Instant | None = None
    release: Instant | None = None
    prerequisites: tuple[Ref, ...] = Field(default=(), max_length=24)
    demand_basis: Ref = "selected_forecast"


class Block(Interval):
    block_id: Ref
    task_id: Ref
    episode_id: Ref
    owner: Literal["canvasbridge"] = "canvasbridge"
    provider_event_id: Ref | None = None
    provider_revision: Ref | None = None
    locked: bool = False
    started: bool = False
    user_edited: bool = False
    manual_title: str | None = Field(default=None, max_length=240)
    manual_note: str | None = Field(default=None, max_length=800)

    def protected(self, now):
        return self.locked or self.started or self.user_edited or self.start < now


class Constraints(Model):
    as_of: Instant
    timezone: Ref = "UTC"
    availability_coverage: Literal["complete", "partial", "unknown"] = "unknown"
    availability: tuple[Interval, ...] = Field(max_length=100)
    busy: tuple[Interval, ...] = Field(default=(), max_length=100)
    buffer_minutes: int = Field(default=0, ge=0, le=120)
    compact_reservations: bool = False
    break_minutes: int = Field(default=0, ge=0, le=60)
    min_block_minutes: int = Field(default=1, ge=1, le=120)
    max_block_minutes: int = Field(default=180, ge=1, le=720)

    @model_validator(mode="before")
    @classmethod
    def wall_times(cls, raw):
        if not isinstance(raw, dict):
            return raw
        try:
            zone = ZoneInfo(raw.get("timezone", "UTC"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone.") from exc
        stamps = [raw.get("as_of")]
        for field in ("availability", "busy"):
            for window in raw.get(field, ()) or ():
                if isinstance(window, dict):
                    stamps.extend((window.get("start"), window.get("end")))
        for value in stamps:
            if not isinstance(value, (str, datetime)):
                continue
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
            # Explicit UTC is an absolute instant. Local-offset wall times must
            # round-trip through the named zone, including both sides of a fold.
            if parsed.utcoffset() is None or (
                parsed.utcoffset() != timedelta(0)
                and parsed.astimezone(zone).utcoffset() != parsed.utcoffset()
            ):
                raise ValueError(
                    "The local wall time and offset must agree with the declared timezone."
                )
        return raw

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA timezone.") from exc
        windows = sorted(self.availability, key=lambda w: w.start)
        if (
            any(a.end > b.start for a, b in zip(windows, windows[1:], strict=False))
            or self.min_block_minutes > self.max_block_minutes
        ):
            raise ValueError("Invalid planning windows or block bounds.")
        return self


def ordered(tasks):
    return sorted(
        tasks, key=lambda t: (t.priority, t.deadline or datetime.max.replace(tzinfo=UTC), t.task_id)
    )


def assess(tasks, base, blocks, policy, free):
    now = policy.as_of
    old = {b.block_id: b for b in base}
    new = {b.block_id: b for b in blocks}
    by_task = {t.task_id: t for t in tasks}
    errors = []
    supplied = Counter()
    allocations = {}
    if len(new) != len(blocks):
        errors.append("duplicate_block_identity")
    gap = timedelta(minutes=policy.break_minutes)
    future = []
    for prior in base:
        if prior.protected(now) and new.get(prior.block_id) != prior:
            errors.append("protected:" + prior.block_id)
    for block in blocks:
        prior = old.get(block.block_id)
        if prior and (prior.episode_id, prior.task_id, prior.provider_event_id) != (
            block.episode_id,
            block.task_id,
            block.provider_event_id,
        ):
            errors.append("identity:" + block.block_id)
        if block.end <= now:
            if prior != block:
                errors.append("elapsed:" + block.block_id)
            continue
        t = by_task.get(block.task_id)
        if not t or t.episode_id != block.episode_id:
            errors.append("episode:" + block.block_id)
            continue
        if t.required_minutes == 0 and not block.protected(now):
            errors.append("completed:" + t.task_id)
        start = max(block.start, now)
        if block.start < now and prior != block:
            errors.append("rewrites_started:" + block.block_id)
        if (t.deadline and block.end > t.deadline) or (t.release and block.start < t.release):
            errors.append("timing:" + t.task_id)
        if not any(a <= start and block.end <= b for a, b in free):
            errors.append("outside_availability:" + block.block_id)
        duration = elapsed(block.start, block.end)
        if not policy.min_block_minutes <= duration <= policy.max_block_minutes:
            errors.append("block_length:" + block.block_id)
        supplied[t.task_id] += elapsed(start, block.end)
        future.append((start, block.end))
        allocations.setdefault(t.task_id, []).append((start, block.end))
    future.sort()
    if any(b + gap > c for (_, b), (c, _) in zip(future, future[1:], strict=False)):
        errors.append("overlap_or_break")
    for t in tasks:
        if t.task_id not in allocations:
            continue
        for parent in t.prerequisites:
            if (
                parent not in by_task
                or by_task[parent].required_minutes is None
                or supplied[parent] < by_task[parent].required_minutes
                or any(
                    end > min(allocations[t.task_id])[0] for _, end in allocations.get(parent, [])
                )
            ):
                errors.append("prerequisite:" + t.task_id)
    unmet = {
        t.task_id: max(0, t.required_minutes - supplied[t.task_id])
        for t in tasks
        if t.required_minutes is not None
    }
    moved = [k for k in old.keys() & new.keys() if old[k].start != new[k].start]
    resized = [
        k for k in old.keys() & new.keys() if old[k].end - old[k].start != new[k].end - new[k].start
    ]
    removed = sorted(old.keys() - new.keys())
    changed = sorted(set(moved) | set(resized) | set(removed))
    displacement = sum(abs(elapsed(old[k].start, new[k].start)) for k in moved)
    size_delta = sum(
        abs(elapsed(old[k].start, old[k].end) - elapsed(new[k].start, new[k].end)) for k in resized
    )
    score = (
        tuple(unmet[t.task_id] for t in ordered(tasks) if t.task_id in unmet),
        len(changed),
        displacement,
        size_delta,
    )
    return score, dict(
        valid=not errors,
        reasons=sorted(set(errors)),
        unmet_minutes={k: float(v) for k, v in unmet.items()},
        supplied_minutes={t.task_id: float(supplied[t.task_id]) for t in tasks},
        changed_existing_block_ids=changed,
        changed_existing_block_count=len(changed),
        retained_block_ids=sorted((old.keys() & new.keys()) - set(changed)),
        added_block_ids=sorted(new.keys() - old.keys()),
        moved_block_ids=sorted(moved),
        removed_block_ids=removed,
        start_displacement_minutes=float(displacement),
        duration_change_minutes=float(size_delta),
    )


def generate(plan_id, tasks, base, policy, free, keep):
    now = policy.as_of
    result = [b for b in base if b.protected(now)]
    gap = timedelta(minutes=policy.break_minutes)
    remaining = list(free)

    def reserve(b):
        nonlocal remaining
        if b.end > now:
            remaining = subtract(remaining, b.start - gap, b.end + gap)

    for b in result:
        reserve(b)
    by_id = {t.task_id: t for t in tasks}
    for b in sorted(
        base,
        key=lambda b: (
            by_id[b.task_id].priority if b.task_id in by_id else 101,
            b.start,
            b.block_id,
        ),
    ):
        if b in result or b.block_id not in keep:
            continue
        t = by_id.get(b.task_id)
        if not t or t.episode_id != b.episode_id or t.required_minutes == 0:
            continue
        if (
            (not t.deadline or b.end <= t.deadline)
            and (not t.release or b.start >= t.release)
            and any(a <= b.start and b.end <= e for a, e in remaining)
        ):
            result.append(b)
            reserve(b)
    pending = list(ordered(tasks))
    served = {
        t.task_id: sum(
            elapsed(max(b.start, now), b.end)
            for b in result
            if b.task_id == t.task_id and b.end > now
        )
        for t in tasks
    }
    processed = set()
    while pending:
        t = next((t for t in pending if set(t.prerequisites) <= processed), None)
        if t is None:
            break
        pending.remove(t)
        if t.required_minutes is None or any(
            by_id[k].required_minutes is None or served[k] < by_id[k].required_minutes
            for k in t.prerequisites
        ):
            processed.add(t.task_id)
            continue
        lower = max(
            [now, t.release or now] + [b.end for b in result if b.task_id in t.prerequisites]
        )
        while served[t.task_id] < t.required_minutes and len(result) < 256:
            need = min(policy.max_block_minutes, t.required_minutes - served[t.task_id])
            slots = [(max(a, lower), min(b, t.deadline or b)) for a, b in remaining]
            slots = [(a, b) for a, b in slots if elapsed(a, b) >= policy.min_block_minutes]
            if not slots:
                break
            start, end = next(((a, b) for a, b in slots if elapsed(a, b) >= need), slots[0])
            length = max(policy.min_block_minutes, min(ceil(need), int(elapsed(start, end))))
            until = start + timedelta(minutes=int(length))
            used = {b.block_id for b in result}
            prior = next(
                (
                    b
                    for b in base
                    if b.task_id == t.task_id
                    and b.episode_id == t.episode_id
                    and b.block_id not in used
                ),
                None,
            )
            if prior:
                block = prior.model_copy(update={"start": start, "end": until})
            else:
                key = fingerprint(
                    ["study-block-v1", plan_id, t.episode_id, t.task_id, start.isoformat()]
                )[:40]
                block = Block(
                    block_id=key, task_id=t.task_id, episode_id=t.episode_id, start=start, end=until
                )
            result.append(block)
            reserve(block)
            served[t.task_id] += length
        processed.add(t.task_id)
    return result


def repair(plan_id, tasks, base, policy, *, alternatives=(), generate_candidates=True):
    if len({t.task_id for t in tasks}) != len(tasks) or len({b.block_id for b in base}) != len(
        base
    ):
        raise ValueError("Duplicate task or accepted block identity.")
    free = planning_windows(policy.availability, policy.busy, policy.as_of, policy.buffer_minutes)
    candidates = list(alternatives)
    if generate_candidates:
        flexible = {b.block_id for b in base if not b.protected(policy.as_of)}
        candidates.append(("accepted", base))
        populations = [flexible, set()] + [flexible - {key} for key in sorted(flexible)[:24]]
        for n, keep in enumerate(populations):
            candidates.append(
                (f"repair-{n:02}", generate(plan_id, tasks, base, policy, free, keep))
            )
    best = None
    rejected = []
    for name, blocks in candidates:
        score, details = assess(tasks, base, blocks, policy, free)
        if not details["valid"]:
            rejected.append(dict(candidate=name, reasons=details["reasons"]))
            continue
        if policy.compact_reservations:
            slack = sum(
                max(0, details["supplied_minutes"][t.task_id] - t.required_minutes)
                for t in tasks
                if t.required_minutes is not None
            )
            score = (score[0], slack, *score[1:])
        if best is None or (*score, name) < best[0]:
            best = ((*score, name), name, blocks, details)
    known = sum(t.required_minutes or 0 for t in tasks)
    capacity = sum(float(elapsed(a, b)) for a, b in union(free))
    unknown = [t.task_id for t in tasks if t.required_minutes is None]
    selected = best[3] if best else None
    residual = sum(selected["unmet_minutes"].values()) if selected else known
    certified = policy.availability_coverage == "complete" and known > capacity
    status = (
        "availability_unverified"
        if policy.availability_coverage != "complete"
        else "infeasible_capacity"
        if certified
        else "no_feasible_schedule_found"
        if not best or residual
        else "provisional"
        if unknown
        else "feasible"
    )
    return dict(
        status=status,
        policy="stable_prioritized_repair_v1",
        buffer_policy="end_only_per_supplied_availability_window",
        timezone=policy.timezone,
        selected_candidate_id=best[1] if best else None,
        selected_blocks=[b.model_dump(mode="json") for b in best[2]] if best else [],
        required_minutes=known,
        free_minutes=capacity,
        unscheduled_minutes=residual,
        unknown_demand=unknown,
        selection=selected,
        work_allocations=[
            dict(
                work_id=t.task_id,
                episode_id=t.episode_id,
                required_minutes=t.required_minutes,
                supplied_minutes=selected["supplied_minutes"][t.task_id],
                unmet_minutes=selected["unmet_minutes"].get(t.task_id),
                deadline=t.deadline.isoformat() if t.deadline else None,
            )
            for t in tasks
        ]
        if selected
        else [],
        capacity_certificate=dict(
            minimum_unscheduled_minutes=max(0, known - capacity),
            coverage=policy.availability_coverage,
        )
        if certified
        else None,
        candidate_count=len(candidates),
        rejected=rejected,
        retained_reserve_minutes=sum(
            max(0, selected["supplied_minutes"][t.task_id] - (t.required_minutes or 0))
            for t in tasks
            if t.required_minutes is not None
        )
        if selected
        else 0,
    )
