"""Completed-work and recorded coordination metrics."""

from collections import Counter

from canvas_bridge.analytics.academic_metrics import TRACE_LIMIT, counted, measure
from canvas_bridge.analytics.observations import latest


def mismatch(actual, forecast):
    if actual.minutes is None:
        return "unknown_actual_minutes"
    if not actual.complete_duration:
        return "incomplete_duration"
    if forecast is None:
        return "missing_bound_forecast"
    if forecast.parent != actual.parent:
        return "parent_assignment_mismatch"
    if forecast.work_revision != actual.work_revision:
        return "work_revision_mismatch"
    if (forecast.unit_id, forecast.scope_id) != (actual.unit_id, actual.scope_id):
        return "scope_mismatch"
    if (forecast.effective_at or forecast.observed_at) > actual.start:
        return "forecast_after_measured_work_start"
    if actual.duration_basis == "cumulative":
        if (
            actual.minutes_before_scope is None
            or actual.baseline_at != (forecast.effective_at or forecast.observed_at)
            or forecast.scope_kind != "remaining_work"
        ):
            return "missing_phase_baseline"
    return None


def effort_metric(history, request, window):
    forecasts = {}
    for forecast in sorted(
        (f for f in history.forecasts if f.eligible(request)), key=lambda f: f.ordering()
    ):
        versions = forecasts.setdefault((tuple(sorted(forecast.course_ids)), forecast.key), {})
        if forecast.version in versions and versions[forecast.version] != forecast:
            raise ValueError("A frozen forecast revision has conflicting inputs.")
        versions[forecast.version] = forecast
    actuals = latest(history.actuals, request)
    excluded = Counter()
    pairs, budgets, points, sources = [], [], [], []
    unplaced = unfinished = outside = 0
    for (courses, _), actual in actuals.items():
        if not actual.completed:
            unfinished += int(window.contains(actual.start))
            continue
        if actual.completion is None:
            unplaced += 1
            continue
        if not window.contains(actual.completion):
            outside += 1
            continue
        versions = forecasts.get((courses, actual.forecast_id), {})
        # Newly saved forecasts receive new keys. Legacy revisioned bindings without an
        # explicit revision refer to the original frozen forecast.
        forecast = versions.get(actual.forecast_version or min(versions, default=0))
        reason = mismatch(actual, forecast)
        trace = {
            "work_id": actual.parent,
            "course_ids": list(courses),
            "actual_source": actual.citation(),
            "forecast_source": forecast.citation() if forecast else None,
            "reason": reason,
        }
        sources.append(trace)
        if reason:
            excluded[reason] += 1
            continue
        minutes = actual.minutes - (actual.minutes_before_scope or 0)
        trace.update(
            forecast_id=forecast.key,
            work_revision=forecast.work_revision,
            unit_id=forecast.unit_id,
            scope_id=forecast.scope_id,
            scope_kind=forecast.scope_kind,
            origin=forecast.origin,
            estimated_at=forecast.estimated_at.isoformat() if forecast.estimated_at else None,
            minimum_minutes=forecast.minimum,
            maximum_minutes=forecast.maximum,
            planning_budget_minutes=forecast.budget,
            point_estimate_minutes=forecast.point,
            actual_minutes=minutes,
            duration_basis=actual.duration_basis,
            minutes_before_scope=actual.minutes_before_scope,
            started_at=actual.start.isoformat(),
            completed_at=actual.completion.isoformat(),
        )
        # Stage 6 already authorized this exact pair. Only explicitly version-bound
        # records enter prospective scoring; legacy report denominators stay intact.
        if actual.forecast_version is not None:
            from canvas_bridge.analytics.effort_history import stage6_scope
            from canvas_bridge.analytics.personal_forecast import evaluate_frozen

            try:
                scope = stage6_scope(
                    actual,
                    forecast,
                    owner="authorized-report",
                    family="recorded_work",
                    policy="stage6_original",
                )
            except ValueError:
                trace["evaluations"] = []
            else:
                trace["evaluations"] = evaluate_frozen(scope, request.evidence_cutoff)
        pairs.append((minutes, forecast.minimum <= minutes <= forecast.maximum))
        if forecast.budget is not None:
            budgets.append(minutes - forecast.budget)
        if forecast.point is not None:
            points.append(minutes - forecast.point)
    n = len(pairs)
    completed = sum(excluded.values()) + n
    reasons = sorted(excluded)
    if not n:
        reasons.append(
            "actual_effort_unavailable"
            if not completed or "unknown_actual_minutes" in excluded
            else "no_matched_work"
        )
    if not points:
        reasons.append("no_explicit_point_forecasts")
    if not budgets:
        reasons.append("no_recorded_planning_budgets")
    if unplaced:
        reasons.append("missing_completion_time")
    if unfinished:
        reasons.append("unfinished_work")
    return {
        "metric_id": "effort_calibration",
        "source_basis": "recorded_completed_work_and_bound_forecast",
        "availability": "unavailable" if not n else "partial" if reasons else "available",
        "eligible": completed,
        "evaluated": n,
        "unplaceable": unplaced,
        "out_of_window": outside,
        "unfinished_scope_count": unfinished,
        "zero_actual_pair_count": sum(actual == 0 for actual, _ in pairs),
        "exclusions": [{"reason": k, "count": v} for k, v in sorted(excluded.items())],
        "measures": [
            measure("pair_coverage", n, completed),
            measure("interval_coverage", sum(inside for _, inside in pairs), n),
            measure("budget_signed_error_minutes", sum(budgets), len(budgets), unit="minutes"),
            measure(
                "budget_absolute_error_minutes",
                sum(map(abs, budgets)),
                len(budgets),
                unit="minutes",
            ),
            measure("point_mae_minutes", sum(map(abs, points)), len(points), unit="minutes"),
            measure("point_bias_minutes", sum(points), len(points), unit="minutes"),
        ],
        "source_refs": sources[:TRACE_LIMIT],
        "trace_omitted": max(0, len(sources) - TRACE_LIMIT),
        "limitations": reasons,
    }


def coordination_metric(history, request, window):
    groups = {}
    trace = []
    unplaced = 0
    for kind in ("logical_request", "attempt", "confirmed_effect", "manual_session"):
        records = latest((r for r in history.actions if r.kind == kind), request)
        groups[kind] = [r for r in records.values() if window.contains(r.effective_at)]
        unplaced += sum(r.effective_at is None for r in records.values())
        trace += [
            r.citation()
            | {
                "kind": kind,
                "key": r.key,
                "effect_key": r.effect_key,
                "manual_minutes": r.manual_minutes,
            }
            for r in groups[kind]
        ]
    sessions = groups["manual_session"]
    minutes = [r.manual_minutes for r in sessions if r.manual_minutes is not None]
    effects = {
        r.effect_key
        for r in groups["confirmed_effect"]
        if r.basis == "confirmed_action_receipt" and r.effect_key
    }
    runtimes = [r.elapsed_ms for r in groups["logical_request"] if r.elapsed_ms is not None]
    limitations = []
    measures = []
    for name, kind, count in (
        ("logical_requests", "logical_request", len(groups["logical_request"])),
        ("attempts", "attempt", len(groups["attempt"])),
        ("confirmed_effects", "confirmed_effect", len(effects)),
    ):
        # A missing collection is unknown. A retained collector can explicitly attest a known empty window.
        covered = any(
            c.collection == kind
            and c.start <= window.start
            and c.end >= window.end
            and set(c.course_ids) == set(request.course_ids)
            for c in latest(history.instrumentation, request).values()
        )
        value = count if count or covered else None
        if value is None:
            limitations.append("no_recorded_" + name)
        measures.append(counted(name, value, unit="count", sample=count))
    if not minutes or len(minutes) != len(sessions):
        limitations.append("manual_duration_unavailable_or_partial")
    measures.extend(
        [
            counted(
                "recorded_manual_minutes",
                sum(minutes) if minutes else None,
                unit="minutes",
                sample=len(minutes),
            ),
            measure("manual_duration_coverage", len(minutes), len(sessions)),
            counted(
                "system_runtime_ms",
                sum(runtimes) if runtimes else None,
                unit="milliseconds",
                sample=len(runtimes),
            ),
        ]
    )
    return {
        "metric_id": "coordination",
        "availability": "unavailable"
        if not any(m["value"] is not None for m in measures)
        else "partial"
        if limitations
        else "available",
        "source_basis": "recorded_actions_receipts_and_manual_sessions",
        "manual_session_count": len(sessions),
        "unplaceable": unplaced,
        "measures": measures,
        "source_refs": trace[:TRACE_LIMIT],
        "trace_omitted": max(0, len(trace) - TRACE_LIMIT),
        "limitations": limitations,
    }
