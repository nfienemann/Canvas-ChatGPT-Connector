"""Due-cohort and schedule calculations over retained evidence."""

from collections import Counter
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from canvas_bridge.analytics.observations import latest

TRACE_LIMIT = 60


def measure(name, numerator, denominator, *, unit="fraction", sample=None):
    return {
        "metric_id": name,
        "unit": unit,
        "numerator": numerator,
        "denominator": denominator,
        "sample_count": denominator if sample is None else sample,
        "value": numerator / denominator if denominator and numerator is not None else None,
    }


def counted(name, value, *, unit, sample):
    return measure(name, value, 1 if value is not None else 0, unit=unit, sample=sample)


def placement(fact, window, zone):
    if fact.exclusion:
        return fact.exclusion
    due = fact.due
    if due.timestamp:
        return "eligible" if window.contains(due.timestamp) else "out_of_window"
    if due.local_date:
        start = datetime.combine(due.local_date, time.min, zone).astimezone(UTC)
        end = datetime.combine(due.local_date + timedelta(days=1), time.min, zone).astimezone(UTC)
        if end <= window.start or start >= window.end:
            return "out_of_window"
        if window.start <= start and end <= window.end:
            return "eligible"
    return "timing_unresolved"


def observed_outcome(fact, due, zone):
    if fact is None:
        return "unknown"
    if fact.state == "missing":
        observed = fact.effective_at or fact.observed_at
        if (due.timestamp and observed <= due.timestamp) or (
            due.local_date and observed.astimezone(zone).date() <= due.local_date
        ):
            return "unknown"
        return "missed"
    if fact.state == "unknown" and fact.submitted_at and due.timestamp:
        return "on_time" if fact.submitted_at <= due.timestamp else "late"
    return fact.state


def due_family(name, cohort, versions, window, zone, coverage):
    deadline = name == "deadline_outcomes"
    categories = (
        ("on_time", "late", "missed", "unknown")
        if deadline
        else ("student_marked_done", "not_started", "in_progress", "unknown")
    )
    counts = Counter(dict.fromkeys(categories, 0))
    account = Counter()
    courses = {}
    revision_work = 0
    trace, membership = [], []
    for key, due in cohort.items():
        slot = placement(due, window, zone)
        state = versions.get(key)
        value = None
        if slot == "eligible":
            value = (
                observed_outcome(state, due.due, zone)
                if deadline
                else state.status
                if state
                else "unknown"
            )
            if value == "not_applicable":
                slot = "timeliness_not_applicable"
            else:
                counts[value] += 1
                if not deadline and state and state.revision_state == "requested":
                    revision_work += 1
                membership.append([key[0][0], key[1]])
                by_course = courses.setdefault(key[0][0], Counter())
                by_course[value] += 1
        account[slot] += 1
        trace.append(
            {
                "course_id": key[0][0],
                "work_id": key[1],
                "placement": slot,
                "category": value,
                "due": due.due.model_dump(mode="json", exclude={"raw"}),
                "deadline_source": due.citation(),
                "state_source": state.citation() if state else None,
                **(
                    {
                        "reported_timeliness": state.state,
                        "submitted_at": state.submitted_at.isoformat()
                        if state.submitted_at
                        else None,
                    }
                    if state and deadline
                    else {}
                ),
                **({"revision_state": state.revision_state} if state and not deadline else {}),
            }
        )
    eligible = account["eligible"]
    known = eligible - counts["unknown"]
    complete = bool(coverage) and all(c["state"] == "complete" for c in coverage)
    limitations = []
    if not complete:
        limitations.append("partial_or_unavailable_inventory")
    if not known:
        limitations.append(
            ("no_known_outcomes" if deadline else "no_known_progress")
            if eligible
            else "no_resolved_due_dates"
            if account["timing_unresolved"]
            else "no_applicable_items"
            if complete
            else "eligible_population_unknown"
        )
    if counts["unknown"]:
        limitations.append("unknown_outcomes" if deadline else "unknown_personal_progress")
    if account["timing_unresolved"]:
        limitations.append("unplaceable_due_dates")
    rates = (
        [(k + "_rate", k) for k in ("missed", "on_time", "late")]
        if deadline
        else [("completion_rate", "student_marked_done")]
    )
    by_course = []
    for c in coverage:
        cc = courses.get(c["course_id"], Counter())
        n = sum(cc.values()) - cc["unknown"]
        by_course.append(
            {
                "course_id": c["course_id"],
                "eligible": sum(cc.values()),
                "evaluated": n,
                "unknown": cc["unknown"],
                "measures": [measure(label, cc[cat], n) for label, cat in rates],
            }
        )
    return {
        "metric_id": name,
        "availability": "unavailable" if not known else "partial" if limitations else "available",
        "source_basis": "reported_timeliness_or_exact_submission"
        if deadline
        else "explicit_personal_status_at_as_of",
        "counts": dict(counts),
        "eligible": eligible,
        "evaluated": known,
        "unknown": counts["unknown"],
        "excluded": sum(account.values())
        - eligible
        - account["timing_unresolved"]
        - account["out_of_window"],
        "out_of_window": account["out_of_window"],
        "unplaceable": account["timing_unresolved"],
        **({"revision_work_count": revision_work} if not deadline else {}),
        "exclusions": [
            {"reason": k, "count": v}
            for k, v in sorted(account.items())
            if k not in {"eligible", "out_of_window", "timing_unresolved"}
        ],
        "measures": [measure(label, counts[cat], known) for label, cat in rates]
        + [measure("observation_coverage", known, eligible)],
        "by_course": by_course,
        "full_scope_rate": counts[rates[0][1]] / known
        if complete and known and not account["timing_unresolved"]
        else None,
        "limitations": limitations,
        "source_refs": trace[:TRACE_LIMIT],
        "trace_omitted": max(0, len(trace) - TRACE_LIMIT),
    }, membership


def due_metrics(history, request, window):
    parents = latest(history.dues, request)
    results, memberships = [], {}
    for name, rows in (
        ("deadline_outcomes", history.outcomes),
        ("personal_completion", history.progress),
    ):
        if name in request.families:
            result, members = due_family(
                name,
                parents,
                latest(rows, request),
                window,
                ZoneInfo(request.timezone),
                history.coverage,
            )
            results.append(result)
            memberships[name] = members
    return results, memberships


def merge(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(end, merged[-1][1])
        else:
            merged.append((start, end))
    return merged


def clipped(rows, window):
    spans = {}
    for row in rows:
        pair = (
            max(window.start, row.start.astimezone(UTC)),
            min(window.end, row.end.astimezone(UTC)),
        )
        if row.key in spans and spans[row.key] != pair:
            raise ValueError("Conflicting intervals share a block identity.")
        if pair[0] < pair[1]:
            spans[row.key] = pair
    return spans


def microseconds(spans):
    return sum((end - start) // timedelta(microseconds=1) for start, end in merge(spans))


def schedule_metric(history, request, window):
    available = list(latest(history.schedules, request).values())
    snapshots = []
    for state in ("accepted", "proposed"):
        requested = getattr(window, state + "_snapshot")
        candidates = [
            s
            for s in available
            if s.state == state
            and (
                (s.key == requested)
                if requested
                else any(b.start < window.end and b.end > window.start for b in s.blocks)
            )
        ]
        selected = max(candidates, key=lambda s: s.ordering(), default=None)
        if selected is None:
            snapshots.append(
                {
                    "state": state,
                    "availability": "unavailable",
                    "limitations": ["no_compatible_snapshot"],
                }
            )
            continue
        blocks, busy = (
            clipped(selected.blocks, window),
            merge(clipped(selected.busy, window).values()),
        )
        fragments, affected = [], set()
        for key, (left, right) in blocks.items():
            for start, end in busy:
                if start >= right:
                    break
                overlap = max(left, start), min(right, end)
                if overlap[0] < overlap[1]:
                    fragments.append(overlap)
                    affected.add(key)
        study = microseconds(blocks.values())
        overlap = microseconds(fragments)
        busy_coverage = selected.busy_coverage
        if busy_coverage == "complete" and selected.coverage_start and selected.coverage_end:
            if selected.coverage_start > window.start or selected.coverage_end < window.end:
                busy_coverage = (
                    "unavailable"
                    if selected.coverage_end <= window.start
                    or selected.coverage_start >= window.end
                    else "partial"
                )
        observed = busy_coverage != "unavailable"
        # Sorted blocks with a start inside the latest open block establish an internal clash.
        internal = set()
        active_key = active_end = None
        for block_id, (left, right) in sorted(blocks.items(), key=lambda kv: kv[1]):
            if active_end is not None and left < active_end:
                internal.update((active_key, block_id))
            if active_end is None or right > active_end:
                active_key, active_end = block_id, right
        duration = measure(
            "union_overlap_minutes",
            overlap if observed else None,
            60_000_000,
            unit="minutes",
            sample=len(blocks),
        )
        fraction = measure(
            "overlap_fraction", overlap if observed else None, study, sample=len(blocks)
        )
        snapshots.append(
            {
                "state": state,
                "snapshot_id": selected.key,
                "busy_version": selected.busy_version,
                "busy_coverage": busy_coverage,
                "source_refs": [selected.citation()],
                "availability": "available" if busy_coverage == "complete" else busy_coverage,
                "study_block_count": len(blocks),
                "affected_study_block_count": len(affected) if observed else None,
                "internal_clash": bool(internal),
                "internally_clashing_blocks": len(internal),
                "capacity_shortfall_scope": "entire_plan_snapshot",
                "capacity_shortfall_minutes": selected.capacity_shortfall_minutes,
                "measures": [
                    duration,
                    measure(
                        "study_union_minutes", study, 60_000_000, unit="minutes", sample=len(blocks)
                    ),
                    fraction,
                ],
                "limitations": []
                if busy_coverage == "complete"
                else ["busy_coverage_" + busy_coverage],
            }
        )
    samples = [
        f
        for f in latest(history.findings, request).values()
        if set(f.course_ids) == set(request.course_ids)
        and f.start == window.start
        and f.end == window.end
    ]
    sample = max(samples, key=lambda f: f.ordering(), default=None)
    findings = (
        {
            "deadline_clusters": sample.deadline_clusters,
            "capacity_shortfalls": sample.capacity_shortfalls,
            "study_plan_conflicts": sample.study_plan_conflicts,
            "acknowledged_unresolved": sample.acknowledged_unresolved,
            "resolved_findings": sample.resolved_findings,
            "source_refs": [sample.citation()],
            "availability": "available" if sample.coverage_complete else "partial",
        }
        if sample
        else {"availability": "unavailable", "reason": "no_retained_finding_scan_for_window"}
    )
    states = {s["availability"] for s in snapshots}
    return {
        "metric_id": "schedule_conflicts",
        "source_basis": "named_study_and_busy_snapshots",
        "availability": "unavailable"
        if states == {"unavailable"}
        else "partial"
        if states != {"available"}
        else "available",
        "snapshots": snapshots,
        "finding_counts": findings,
        "limitations": sorted({v for s in snapshots for v in s["limitations"]}),
    }
