"""Deterministic, evidence-bounded semester findings. No scheduling or I/O."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_bridge.change_tracking import compare_snapshots
from canvas_bridge.domain import WorkItem
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning import subtract
from canvas_bridge.planning_dates import day_boundary, instant
from canvas_bridge.semester_models import SemesterPreferences
from canvas_bridge.storage import aware
from canvas_bridge.work_eligibility import completion_reason

ENGINE = "semester-intelligence-1"


def evidence(item):
    return item.source.model_dump(mode="json") | {"work_id": item.id, "course_id": item.course_id}


def semantic(finding):
    return fingerprint([finding["issue_key"], finding["details"]])


def finding(
    kind,
    course_ids,
    work_ids,
    title,
    details,
    sources,
    action,
    *,
    due=None,
    consequence=None,
    status="supported_observation",
):
    key = fingerprint(
        [
            ENGINE,
            kind,
            sorted(course_ids),
            sorted(work_ids),
            details.get("field"),
            details.get("category"),
            details.get("block_start"),
            details.get("module_id"),
            details.get("source_date"),
        ]
    )
    result = {
        "issue_key": key,
        "kind": kind,
        "course_ids": sorted(course_ids),
        "work_ids": sorted(work_ids),
        "title": title,
        "details": details,
        "evidence": sources,
        "applicable_at": due.isoformat() if due else None,
        "academic_consequence": consequence,
        "evidence_status": status,
        "next_action": action,
        "acknowledged": False,
        "lifecycle": "current_observation",
    }
    result["finding_revision"] = semantic(result)
    return result


def availability(preferences, busy, now, deadline, timezone):
    windows = [
        [max(now, w.start), min(deadline, w.end)]
        for w in preferences.available_windows
        if w.end > now and w.start < deadline
    ]
    for occupied in busy:
        windows = subtract(windows, occupied.start, occupied.end)
    daily = {}
    for left, right in windows:
        # Split by real local-day boundaries; a DST day is not assumed to be 24 hours.
        while left < right:
            day = left.astimezone(ZoneInfo(timezone)).date()
            stop = min(right, day_boundary(day + timedelta(days=1), ZoneInfo(timezone)))
            minutes = max(0, int((stop - left).total_seconds() // 60))
            daily[day] = daily.get(day, 0) + minutes
            left = stop
    cap = preferences.workload_tolerance_minutes_per_day
    return sum(min(minutes, cap) if cap is not None else minutes for minutes in daily.values())


def current_findings(items, now, start, end, timezone, preferences, busy, weights):
    findings, relevant = [], []
    by_id = {i.id: i for i in items}
    for item in items:
        if item.availability_state == "inaccessible":
            continue
        due = instant(item.effective_due.timestamp) if item.effective_due.timestamp else None
        if due and not start <= due < end:
            continue
        if (
            item.effective_due.local_date
            and not start.astimezone(ZoneInfo(timezone)).date()
            <= item.effective_due.local_date
            <= end.astimezone(ZoneInfo(timezone)).date()
        ):
            continue
        if completion_reason(item):
            continue
        relevant.append(item)
        sources = [evidence(item)]
        verified_pending = (
            item.submission_state == "not_submitted"
            and item.submission_evidence == "returned"
            and item.personal_progress != "student_marked_done"
        )
        if due and (due >= now or verified_pending):
            kind = "overdue_work" if due < now else "upcoming_deadline"
            findings.append(
                finding(
                    kind,
                    [item.course_id],
                    [item.id],
                    item.title,
                    {
                        "due": item.effective_due.model_dump(mode="json"),
                        "submission_state": item.submission_state,
                        "submission_evidence": item.submission_evidence,
                        "personal_progress": item.personal_progress,
                    },
                    sources,
                    "Check whether late submission is accepted and choose a recovery action."
                    if due < now
                    else "Confirm remaining work and reserve a study period before the reported deadline.",
                    due=due,
                    consequence="The reported submission deadline has passed; any penalty or recoverability is unknown."
                    if due < now
                    else "Work may need completion before the reported deadline; grade impact is not inferred.",
                )
            )
        elif item.timeliness_state == "missing" and verified_pending:
            findings.append(
                finding(
                    "missing_work",
                    [item.course_id],
                    [item.id],
                    item.title,
                    {
                        "timeliness_state": "missing",
                        "submission_evidence": item.submission_evidence,
                    },
                    sources,
                    "Verify the missing-work flag and ask whether work can still be submitted.",
                    consequence="Canvas reports missing work; timing and penalty remain unknown.",
                )
            )
        if not due:
            findings.append(
                finding(
                    "uncertain_timing",
                    [item.course_id],
                    [item.id],
                    item.title,
                    {"due": item.effective_due.model_dump(mode="json")},
                    sources,
                    "Verify the applicable date, time and timezone before assigning urgency.",
                    status="uncertain",
                )
            )
        elif due < now and not verified_pending:
            findings.append(
                finding(
                    "uncertain_completion",
                    [item.course_id],
                    [item.id],
                    item.title,
                    {
                        "submission_state": item.submission_state,
                        "submission_evidence": item.submission_evidence,
                        "personal_progress": item.personal_progress,
                    },
                    sources,
                    "Check the submission receipt; an unknown status is not proof of missing work.",
                    status="uncertain",
                )
            )
        if item.prerequisites:
            unresolved = [
                p for p in item.prerequisites if p not in by_id or not completion_reason(by_id[p])
            ]
            if unresolved:
                # An unavailable dependency is not proof of deletion or unfinished work.
                findings.append(
                    finding(
                        "prerequisite_needs_review",
                        [item.course_id],
                        [item.id],
                        item.title,
                        {
                            "unresolved_prerequisites": unresolved,
                            "prerequisite_coverage": item.prerequisite_coverage,
                        },
                        sources,
                        "Verify access to required material and prerequisite completion before planning dependent work.",
                        due=due,
                        status="uncertain",
                    )
                )
    dated = sorted(
        [i for i in relevant if i.effective_due.timestamp],
        key=lambda i: (i.effective_due.timestamp, i.id),
    )
    # Consecutive 72-hour components avoid O(n^2) alerts and overlapping cluster spam.
    clusters = []
    for item in dated:
        due = instant(item.effective_due.timestamp)
        if due < now:
            continue
        if not clusters or due - instant(clusters[-1][0].effective_due.timestamp) > timedelta(
            hours=72
        ):
            clusters.append([])
        clusters[-1].append(item)
    for group in clusters:
        if len(group) < 2:
            continue
        major = [i for i in group if weights.get(i.id, {}).get("percent", 0) >= 10]
        chosen = major if len(major) >= 2 else group
        findings.append(
            finding(
                "major_assessment_cluster" if len(major) >= 2 else "deadline_cluster",
                {i.course_id for i in chosen},
                [i.id for i in chosen],
                "Assessments fall within a 72-hour window",
                {
                    "deadlines": [
                        {
                            "work_id": i.id,
                            "due": i.effective_due.timestamp.isoformat(),
                            "verified_weight": weights.get(i.id),
                        }
                        for i in chosen
                    ]
                },
                [evidence(i) for i in chosen],
                "Review the clustered work together and allocate available time across courses.",
                due=min(i.effective_due.timestamp for i in chosen),
                consequence="At least two assessments each have a verified structural course weight of 10% or more."
                if len(major) >= 2
                else "Several deadlines are close together; this does not establish a time conflict or major grade impact.",
            )
        )
    # Workload risk uses only explicitly supported, current estimates and supplied availability.
    if preferences.available_windows:
        for group in clusters:
            supported = [
                i
                for i in group
                if i.effort_remaining
                and i.effort_remaining.origin in {"student_estimate", "instructor_estimate"}
                and timedelta(0) <= now - i.effort_remaining.as_of <= timedelta(days=30)
            ]
            if not supported:
                continue
            deadline = max(i.effective_due.timestamp for i in supported)
            minimum = sum(i.effort_remaining.minimum_minutes for i in supported)
            free = availability(preferences, busy, now, deadline, timezone)
            if minimum > free:
                findings.append(
                    finding(
                        "availability_shortfall",
                        {i.course_id for i in supported},
                        [i.id for i in supported],
                        "Estimated work exceeds supplied availability",
                        {
                            "minimum_estimated_minutes": minimum,
                            "available_minutes": free,
                            "estimates": [
                                i.effort_remaining.model_dump(mode="json") for i in supported
                            ],
                            "availability_basis": "explicit_user_windows_minus_busy_times",
                        },
                        [evidence(i) for i in supported],
                        "Review the estimates and availability, then adjust the plan or seek an extension.",
                        due=deadline,
                        status="conditional_on_user_inputs",
                    )
                )
    return findings, relevant


def plan_findings(by_id, plans, busy, now):
    findings = []
    plan_work = set()
    for plan in plans:
        blocks = plan.get("proposal", {}).get("blocks", [])
        for block in blocks:
            work_id = block.get("work_id")
            item = by_id.get(work_id)
            if not item or completion_reason(item):
                continue
            plan_work.add(work_id)
            try:
                a, b = (
                    instant(datetime.fromisoformat(block["start"])),
                    instant(datetime.fromisoformat(block["end"])),
                )
            except (ValueError, KeyError):
                continue
            if b <= now:
                continue
            conflicts = [w.model_dump(mode="json") for w in busy if a < w.end and w.start < b]
            if conflicts or (item.effective_due.timestamp and b > item.effective_due.timestamp):
                findings.append(
                    finding(
                        "study_plan_conflict",
                        [item.course_id],
                        [item.id],
                        item.title,
                        {
                            "block_start": a.isoformat(),
                            "block_end": b.isoformat(),
                            "busy_conflicts": conflicts,
                            "due": item.effective_due.model_dump(mode="json"),
                        },
                        [evidence(item)],
                        "Move the study block before the deadline and outside supplied busy periods.",
                        due=item.effective_due.timestamp,
                        status="conditional_on_user_inputs",
                    )
                )
    return findings, plan_work


def analyze(
    snapshot,
    baseline,
    *,
    now,
    start,
    end,
    timezone,
    preferences=None,
    busy=(),
    weights=None,
    supplemental=(),
    acknowledgements=None,
    plans=(),
):
    preferences = preferences or SemesterPreferences()
    weights, acknowledgements = weights or {}, acknowledgements or {}
    now, start, end = instant(now), instant(start), instant(end)
    items = [WorkItem.model_validate(i) for i in snapshot.items]
    items = [i for i in items if i.availability_state != "inaccessible"]
    by_id = {i.id: i for i in items}
    findings, relevant = current_findings(
        items, now, start, end, timezone, preferences, busy, weights
    )
    findings.extend(supplemental)
    comparable = bool(
        baseline
        and baseline.complete
        and snapshot.complete
        and sorted(baseline.course_ids) == sorted(snapshot.course_ids)
        and aware(baseline.created_at) < aware(snapshot.created_at)
    )
    history = "confirmed_comparison" if comparable else "incomplete_historical_comparison"
    paired = bool(
        baseline
        and aware(baseline.created_at) < aware(snapshot.created_at)
        and sorted(baseline.course_ids) == sorted(snapshot.course_ids)
    )
    changes = compare_snapshots([baseline, snapshot]) if paired else []
    for change in changes:
        item = by_id.get(change["work_id"])
        if not item or item not in relevant:
            continue
        field = change.get("field")
        if change.get("kind") == "first_observed":
            if not comparable:
                continue
            kind, action = (
                "newly_observed_assessment",
                "Review this first observed assessment; its creation time is unknown.",
            )
        elif field in {"effective_due", "available_from", "closes_at"}:
            kind, action = (
                "assessment_date_changed",
                "Check the revised date and update affected study blocks.",
            )
        elif field in {"instruction_hash", "submission_requirement"}:
            kind, action = (
                "requirements_changed",
                "Compare the current requirements with your work; the exact requirement difference needs inspection.",
            )
        else:
            continue  # Titles, points and ordinary status updates are not automatically alerts.
        findings.append(
            finding(
                kind,
                [item.course_id],
                [item.id],
                item.title,
                {
                    "field": field,
                    "old": change.get("old"),
                    "new": change.get("new"),
                    "observation": change.get("kind"),
                },
                [
                    evidence(item),
                    {
                        "source_type": "snapshot_comparison",
                        "previous_snapshot": baseline.id,
                        "snapshot_id": snapshot.id,
                        "observed_at": aware(snapshot.created_at).isoformat(),
                        "source": next(i["source"] for i in baseline.items if i["id"] == item.id),
                    },
                ]
                if field
                else [evidence(item)],
                action,
                due=item.effective_due.timestamp,
                status="confirmed_newly_observed_change"
                if comparable
                else "unverified_suspected_change",
            )
        )
    plan_issues, plan_work = plan_findings(by_id, plans, busy, now)
    findings.extend(plan_issues)
    for f in findings[:]:
        if (
            f["kind"] in {"assessment_date_changed", "requirements_changed"}
            and set(f["work_ids"]) & plan_work
        ):
            findings.append(
                finding(
                    "study_plan_needs_revision",
                    f["course_ids"],
                    f["work_ids"],
                    f["title"],
                    {"changed_issue": f["finding_revision"]},
                    f["evidence"],
                    "Revalidate the saved study plan against this newly observed source change.",
                    status=f["evidence_status"],
                )
            )
    # Resolve only comparable observations whose source objects are still accessible.
    if comparable:
        old_items = [WorkItem.model_validate(i) for i in baseline.items if i["id"] in by_id]
        previous, _ = current_findings(
            old_items,
            now,
            start,
            end,
            timezone,
            preferences,
            busy,
            weights,
        )
        previous.extend(plan_findings({i.id: i for i in old_items}, plans, busy, now)[0])
        active = {f["issue_key"] for f in findings}
        for old in previous:
            # Missing coverage, an unknown new date or moving outside this report
            # cannot establish resolution. Only comparable, still visible facts can.
            current = [by_id[w] for w in old["work_ids"] if w in by_id]
            resolved = (
                bool(current)
                and len(current) == len(old["work_ids"])
                and all(
                    completion_reason(i)
                    or (
                        i.effective_due.timestamp
                        and start <= instant(i.effective_due.timestamp) < end
                    )
                    for i in current
                )
            )
            if old["kind"] == "prerequisite_needs_review":
                resolved &= all(i.prerequisite_coverage == "known" for i in current)
            if old["kind"] in {"overdue_work", "missing_work"}:
                resolved &= all(
                    completion_reason(i)
                    or (
                        old["kind"] == "overdue_work"
                        and i.effective_due.timestamp
                        and instant(i.effective_due.timestamp) >= now
                    )
                    for i in current
                )
            if old["issue_key"] not in active and resolved:
                old.update(
                    lifecycle="resolved_finding",
                    evidence_status="supported_by_comparable_snapshots",
                    next_action="No repeated warning is needed; review the current source if further action is expected.",
                )
                old["evidence"] = [evidence(by_id[w]) for w in old["work_ids"]]
                findings.append(old)
    priorities = {p.course_id: p.priority for p in preferences.course_priorities}
    unique = {f["finding_revision"]: f for f in findings}
    for f in unique.values():
        fresh = timedelta(0) <= now - aware(snapshot.created_at) <= timedelta(minutes=5)
        if not fresh:
            f["evidence_status"] = "stale_observation"
        f["acknowledged"] = acknowledgements.get(f["issue_key"]) == f["finding_revision"]
        if f["lifecycle"] != "resolved_finding":
            f["lifecycle"] = (
                "previously_acknowledged_finding"
                if f["acknowledged"]
                else "confirmed_newly_observed_change"
                if f["evidence_status"] == "confirmed_newly_observed_change"
                else "unverified_suspected_change"
                if not comparable
                and f["kind"] in {"requirements_changed", "assessment_date_changed"}
                else "current_observation"
            )
        due = next(
            (
                i.effective_due.timestamp
                for i in relevant
                if i.id in f["work_ids"] and i.effective_due.timestamp
            ),
            None,
        )
        if f["applicable_at"]:
            due = datetime.fromisoformat(f["applicable_at"])
        hours = (due - now).total_seconds() / 3600 if due else None
        temporal = fresh and f["evidence_status"] not in {
            "uncertain",
            "stale_observation",
            "unverified_suspected_change",
        }
        tier = 4 if not temporal or hours is None else 1 if hours <= 24 else 2 if hours <= 72 else 3
        weight = max((weights[w]["percent"] for w in f["work_ids"] if w in weights), default=None)
        f["priority"] = {
            "tier": tier,
            "label": {1: "act_soon", 2: "plan_soon", 3: "plan", 4: "clarify"}[tier],
            "hours_until_reported_date": round(hours, 2)
            if temporal and hours is not None
            else None,
            "verified_weight_percent": weight,
            "course_preference": min((priorities.get(c, 5) for c in f["course_ids"]), default=5),
            "basis": "Heuristic: evidence and known timing, then user course priority, then verified structural weight, then stable issue ID. Unknown values do not become urgency or grade loss.",
            "freshness": "current" if fresh else "stale",
        }
        f["priority"]["planning_factors"] = {
            "dependency_review": f["kind"]
            in {"prerequisite_needs_review", "prerequisite_material_unavailable"},
            "known_plan_conflict": f["kind"] == "study_plan_conflict",
            "supported_workload_shortfall": f["kind"] == "availability_shortfall",
        }
        if preferences.preferred_study_periods and f["kind"] in {
            "upcoming_deadline",
            "study_plan_conflict",
            "availability_shortfall",
        }:
            f["next_action"] += (
                " Prefer your saved study periods within confirmed availability; preferred periods alone are not free time."
            )
    ordered = sorted(
        unique.values(),
        key=lambda f: (
            f["lifecycle"] == "resolved_finding",
            f["acknowledged"],
            f["priority"]["tier"],
            f["priority"]["course_preference"],
            -(f["priority"]["verified_weight_percent"] or 0),
            f["issue_key"],
        ),
    )
    return {
        "engine": ENGINE,
        "analysis_as_of": now.isoformat(),
        "history_status": history,
        "baseline": baseline.id if baseline else None,
        "snapshot_id": snapshot.id,
        "collection_complete": snapshot.complete,
        "analysis_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
        },
        "findings": ordered,
        "current_obligations": [i.model_dump(mode="json") for i in relevant],
        "recommended_priorities": [
            f["issue_key"]
            for f in ordered
            if not f["acknowledged"] and f["lifecycle"] != "resolved_finding"
        ][:10],
        "outstanding_uncertainties": [
            "Source coverage is incomplete; absent findings are not proof of no risk."
        ]
        if not snapshot.complete
        else [],
        "limitations": [
            "Rankings are transparent heuristics, not guarantees or probabilities of academic outcomes.",
            "History describes observations, never creation times. Missing baselines cannot establish new events.",
            "No deadline overlap alone proves an attendance conflict. Workload and calendar findings depend on explicit user inputs.",
            "No health, disability or protected characteristic is inferred.",
        ],
    }
