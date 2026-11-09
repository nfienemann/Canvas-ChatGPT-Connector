"""Prospective, episode-scoped effort calibration from independent measured scopes."""

from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
from math import ceil, floor
from statistics import median

from canvas_bridge.analytics.effort_history import (
    Estimate,
    HistoryScope,
    Instant,
    Scope,
    selected_actual,
    union,
)
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import Model, Ref


class Override(Model):
    override_id: Ref
    scope_id: Ref
    episode_id: Ref
    known_at: Instant
    values: Estimate
    basis: Ref


class Target(Scope):
    forecast_id: Ref
    user_id: Ref
    cutoff: Instant
    baseline: Estimate
    baseline_origin: Ref
    manual_override: Override | None = None
    completed: bool = False


def metric(actual, values, budget):
    return dict(
        point_error_minutes=float(actual - values.point) if values.point is not None else None,
        absolute_point_error_minutes=float(abs(actual - values.point))
        if values.point is not None
        else None,
        inside_range=values.low <= actual <= values.high if values.low is not None else None,
        budget_error_minutes=float(actual - budget) if budget is not None else None,
        absolute_budget_error_minutes=float(abs(actual - budget)) if budget is not None else None,
    )


def evaluate_frozen(scope, cutoff):
    """Score each distinct prospective issue against the actual known at this cutoff."""
    if (
        not scope.completion.complete
        or scope.completion.known_at > cutoff
        or scope.coverage.state != "complete"
        or scope.coverage.known_at > cutoff
    ):
        return []
    actual, refs, _, reason = selected_actual(scope, cutoff)
    if reason:
        return []
    result = []
    seen = set()
    for f in scope.forecasts:
        key = f.canonical_forecast_id or f.forecast_id
        if (
            key in seen
            or f.scope_id != scope.scope_id
            or not f.frozen_at <= f.known_at <= min(cutoff, scope.scope_start_at)
        ):
            continue
        seen.add(key)
        result.append(
            dict(
                forecast_id=f.forecast_id,
                scope_id=scope.scope_id,
                episode_id=scope.episode_id,
                observation_refs=refs,
                actual_minutes=float(actual),
                evaluation_cutoff=cutoff.isoformat(),
                baseline=metric(actual, f.baseline, f.baseline.high),
                published=metric(actual, f.published, f.budget),
            )
        )
    return result


def candidate(scope, target, actual):
    if (scope.episode_id, scope.scope_id) == (target.episode_id, target.scope_id):
        return None, "target_outcome"
    for key in ("user_id", "task_family", "scope_kind", "baseline_policy"):
        if getattr(scope, key) != getattr(target, key):
            return None, "cohort_" + key
    if not scope.completion.complete:
        return None, "unfinished_scope"
    if scope.completion.completed_at > target.cutoff:
        return None, "completion_after_cutoff"
    if scope.completion.known_at > target.cutoff:
        return None, "completion_not_known_at_cutoff"
    if scope.coverage.state != "complete" or scope.coverage.known_at > target.cutoff:
        return None, "incomplete_actual_coverage"
    prospective = [
        f
        for f in scope.forecasts
        if f.baseline_policy == target.baseline_policy
        and f.scope_id == scope.scope_id
        and f.frozen_at <= scope.scope_start_at
        and f.frozen_at <= f.known_at <= min(target.cutoff, scope.scope_start_at)
    ]
    if not prospective:
        return None, "missing_prospective_baseline"
    f = min(prospective, key=lambda f: (-f.frozen_at.timestamp(), f.forecast_id))
    minutes, refs, spans, reason = actual
    if reason:
        return None, reason
    return (scope, f, minutes, refs, spans), None


def forecast(histories: list[HistoryScope], target: Target):
    pairs = []
    excluded = []

    def omit(scope, reason):
        excluded.append(dict(history_id=scope.history_id, reason=reason))

    # First union within each episode so multiple representations of one
    # episode occupy the clock only once. Count distinct episodes on each span.
    measured = [
        selected_actual(s, target.cutoff) if s.user_id == target.user_id else None
        for s in histories
    ]
    sessions = defaultdict(list)
    for scope, actual in zip(histories, measured, strict=True):
        if actual:
            sessions[scope.episode_id].extend(actual[2])
    events = defaultdict(int)
    for spans in sessions.values():
        for start, end in union(spans):
            events[start] += 1
            events[end] -= 1
    overlap = []
    active = 0
    previous = None
    for instant, change in sorted(events.items()):
        if active > 1:
            overlap.append((previous, instant))
        active += change
        previous = instant
    ends = [end for _, end in overlap]
    ambiguous = set()
    for scope, actual in zip(histories, measured, strict=True):
        for start, end in actual[2] if actual else ():
            index = bisect_right(ends, start)
            if index < len(overlap) and overlap[index][0] < end:
                ambiguous.add(scope.history_id)
                break
    for scope, actual in zip(histories, measured, strict=True):
        pair, reason = candidate(scope, target, actual)
        if scope.history_id in ambiguous:
            reason = "cross_episode_overlap"
        if reason:
            omit(scope, reason)
        else:
            pairs.append(pair)
    pairs.sort(
        key=lambda p: (
            -p[0].completion.completed_at.timestamp(),
            -p[0].scope_start_at.timestamp(),
            -p[1].frozen_at.timestamp(),
            p[0].history_id,
        )
    )
    training = []
    seen = set()
    evaluation = []
    for pair in pairs:
        scope, f, actual, refs, _ = pair
        key = (scope.episode_id, scope.scope_id, f.canonical_forecast_id or f.forecast_id)
        if key in seen:
            omit(scope, "duplicate_forecast_actual_pair")
            continue
        seen.add(key)
        evaluation.append(
            dict(
                history_id=scope.history_id,
                forecast_id=f.forecast_id,
                actual_minutes=float(actual),
                observation_refs=refs,
                baseline=metric(actual, f.baseline, f.baseline.high),
                published=metric(
                    actual, f.published, f.budget if f.budget is not None else f.published.high
                ),
            )
        )
        if not f.baseline.point:
            omit(
                scope,
                "missing_baseline_point" if f.baseline.point is None else "zero_baseline_point",
            )
            continue
        reason = None
        for prior, *_ in training:
            if prior.episode_id != scope.episode_id:
                continue
            if prior.scope_id == scope.scope_id:
                reason = "duplicate_completed_scope"
            elif (
                prior.scope_start_at < scope.scope_end_at
                and scope.scope_start_at < prior.scope_end_at
            ):
                reason = "overlapping_completed_scope"
            elif not (scope.disjoint_subscope_coverage and prior.disjoint_subscope_coverage):
                reason = "unverified_independent_subscope"
            if reason:
                break
        if reason:
            omit(scope, reason)
        else:
            training.append(pair)
    training.sort(
        key=lambda p: (-p[0].completion.completed_at.timestamp(), p[0].episode_id, p[0].scope_id)
    )
    for scope, *_ in training[20:]:
        omit(scope, "history_limit")
    training = training[:20]
    ratios = [actual / f.baseline.point for _, f, actual, _, _ in training]
    n = len(ratios)
    middle = median(ratios) if n else None
    factor = (3 + n * middle) / (3 + n) if n else Fraction(1)
    raw = {
        k: None if value is None else value * factor
        for k, value in target.baseline.model_dump().items()
    }
    unknown = raw["low"] is None
    zero_remaining = target.completed or target.baseline.high == 0
    if zero_remaining:
        raw = dict.fromkeys(raw, Fraction(0))
        suggestion = Estimate(low=0, point=0, high=0)
        state = "completed_or_zero_remaining"
    elif unknown:
        suggestion = Estimate()
        state = "baseline_unknown"
    else:
        low = max(1, floor(raw["low"]))
        high = max(low, ceil(raw["high"]))
        if high > 100_000:
            raise ValueError("Forecast exceeds the supported planner range.")
        point = (
            min(high, max(low, floor(raw["point"] + Fraction(1, 2))))
            if raw["point"] is not None
            else None
        )
        suggestion = Estimate(low=low, point=point, high=high)
        state = "range_only" if point is None else "point_and_range"
    effective = suggestion
    override = target.manual_override
    override_state = "absent"
    if override:
        if target.completed:
            override_state = "inapplicable_completed_scope"
        elif (override.scope_id, override.episode_id) == (
            target.scope_id,
            target.episode_id,
        ) and override.known_at <= target.cutoff:
            effective = override.values
            override_state = "applied"
        else:
            override_state = "outside_current_scope_or_cutoff"
    support = "cold_start" if not n else "limited_history" if n < 3 else "supported_history"
    return dict(
        forecast_id=target.forecast_id,
        scope_id=target.scope_id,
        episode_id=target.episode_id,
        cutoff=target.cutoff.isoformat(),
        policy="median_ratio_shrinkage_v1",
        baseline=target.baseline.model_dump(),
        baseline_origin=target.baseline_origin,
        baseline_state=state,
        matched_pair_count=len(evaluation),
        training_count=n,
        training_history_ids=[p[0].history_id for p in training],
        training_forecast_ids=[p[1].forecast_id for p in training],
        training_snapshot_id=fingerprint(
            [(p[0].history_id, p[1].forecast_id, str(p[2]), p[3]) for p in training]
        ),
        actual_minutes={p["history_id"]: p["actual_minutes"] for p in evaluation},
        ratio_median=str(middle) if n else None,
        factor=str(factor),
        raw={k: str(v) if v is not None else None for k, v in raw.items()},
        calibration_suggestion=suggestion.model_dump(),
        published=effective.model_dump(),
        planning_budget_minutes=effective.high,
        override_state=override_state,
        history_support=support,
        support="user_override"
        if override_state == "applied"
        else state
        if state == "baseline_unknown"
        else support,
        excluded=excluded,
        evaluations=evaluation,
        metric_denominators={
            k: sum(
                p["published"][k] is not None and p["baseline"][k] is not None for p in evaluation
            )
            for k in ("point_error_minutes", "inside_range", "budget_error_minutes")
        },
    )
