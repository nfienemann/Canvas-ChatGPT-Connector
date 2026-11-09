"""Reproducible report identities, pooled arithmetic and explicit restatements."""

import json
from datetime import datetime
from fractions import Fraction
from time import monotonic

from pydantic import PrivateAttr
from sqlalchemy import select

from canvas_bridge.analytics.academic_metrics import due_metrics, schedule_metric
from canvas_bridge.analytics.activity_metrics import coordination_metric, effort_metric
from canvas_bridge.analytics.observations import latest
from canvas_bridge.analytics.storage import REPORT, load_history
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.storage import LocalRecord

VERSION = "academic-operations-analytics-1"


class ScopedResult(Result):
    _analytics_bindings: list[tuple[str, str, str]] = PrivateAttr(default_factory=list)


def observations(history, request):
    """Hash eligible versions, including nulls and assumptions, regardless of trace page length."""
    facts = []
    attrs = set()
    for family in request.families:
        attrs.update(
            {
                "deadline_outcomes": ("dues", "outcomes"),
                "personal_completion": ("dues", "progress"),
                "schedule_conflicts": ("schedules", "findings"),
                "effort_calibration": ("forecasts", "actuals"),
                "coordination": ("instrumentation",),
            }[family]
        )
    for attr in sorted(attrs):
        rows = getattr(history, attr)
        selected = (
            [r for r in rows if r.eligible(request)]
            if attr == "forecasts"
            else latest(rows, request).values()
        )
        for row in selected:
            facts.append(row.model_dump(mode="json"))
            history.bindings.update(
                (b.course_id, b.work_id, b.source_version) for b in row.parent_sources
            )
    for kind in (
        ("logical_request", "attempt", "confirmed_effect", "manual_session")
        if "coordination" in request.families
        else ()
    ):
        facts.extend(
            row.model_dump(mode="json")
            for row in latest((r for r in history.actions if r.kind == kind), request).values()
        )
    return sorted({fingerprint(fact) for fact in facts})


def metrics_for(period):
    output = {}
    for family in period["families"]:
        for item in family.get("measures", []):
            output[(family["metric_id"], item["metric_id"])] = item
        for snap in family.get("snapshots", []):
            for item in snap.get("measures", []):
                output[(snap["state"], item["metric_id"])] = item
    return output


def compare(previous, current):
    a, b = metrics_for(previous), metrics_for(current)
    changes = []
    for key in sorted(a.keys() | b.keys()):
        left, right = a.get(key), b.get(key)
        unit = (left or right)["unit"]
        delta = relative = None
        reason = "measurement_unavailable"
        if left and right and left["value"] is not None and right["value"] is not None:
            x, y = (Fraction(m["numerator"], m["denominator"]) for m in (left, right))
            delta = (y - x) * (100 if unit == "fraction" else 1)
            relative = float((y - x) / x) if x else None
            reason = None if x else "zero_reference_value"
        changes.append(
            {
                "family": key[0],
                "metric_id": key[1],
                "value": float(delta) if delta is not None else None,
                "numerator": delta.numerator if delta is not None else None,
                "denominator": delta.denominator if delta is not None else None,
                "unit": "percentage_points" if unit == "fraction" else unit,
                "previous_value": left["value"] if left else None,
                "current_value": right["value"] if right else None,
                "previous_sample_count": left["sample_count"] if left else 0,
                "current_sample_count": right["sample_count"] if right else 0,
                "relative_change_fraction": relative,
                "reason": reason,
            }
        )
    return changes


def summary(period):
    parts = []
    for f in period["families"]:
        name = f["metric_id"]
        metrics = {m["metric_id"]: m for m in f.get("measures", [])}
        if name in ("deadline_outcomes", "personal_completion"):
            deadline = name == "deadline_outcomes"
            m = metrics["missed_rate" if deadline else "completion_rate"]
            label = (
                "known deadline outcomes were missed"
                if deadline
                else "known personal declarations were marked done at the state cutoff"
            )
            if m["denominator"]:
                parts.append(
                    f"{m['numerator']} of {m['denominator']} {label} ({f['unknown']} unknown)"
                )
            elif f["eligible"]:
                parts.append(
                    f"{f['eligible']} due items, all with unknown "
                    + ("timeliness" if deadline else "personal progress")
                )
            elif "no_applicable_items" in f["limitations"]:
                parts.append("No eligible due items for " + name)
            else:
                parts.append("Due inventory unavailable or incomplete for " + name)
        elif name == "schedule_conflicts":
            saved = f["snapshots"][0]
            if saved.get("measures") and (m := saved["measures"][0])["value"] is not None:
                parts.append(
                    f"{m['value']:g} minutes of observed saved-plan overlap ({saved['busy_coverage']} busy coverage)"
                )
            else:
                parts.append("Saved-plan overlap needs both study and busy intervals")
        elif name == "effort_calibration":
            m = metrics["interval_coverage"]
            parts.append(
                f"{m['numerator']} of {m['denominator']} matched actuals inside the forecast range"
                if m["denominator"]
                else "No comparable recorded actual and forecast"
            )
            if f["eligible"] > m["denominator"]:
                parts.append(
                    f"{f['eligible'] - m['denominator']} completed work scope(s) lacked a comparable pair"
                )
        elif name == "coordination":
            m = metrics["recorded_manual_minutes"]
            if m["value"] is not None:
                parts.append(
                    f"{m['value']:g} recorded manual minutes from {m['sample_count']} sessions"
                )
            elif all(
                metrics[k]["value"] is None
                for k in ("logical_requests", "attempts", "confirmed_effects")
            ):
                parts.append("No recorded actions or manual duration for this period")
    return ". ".join(parts) or "The selected measurement has insufficient retained observations."


def history_coverage(history, request):
    output = []
    for kind in (
        "dues",
        "outcomes",
        "progress",
        "schedules",
        "findings",
        "forecasts",
        "actuals",
        "actions",
    ):
        rows = [r for r in getattr(history, kind) if r.eligible(request)]
        times = [r.observed_at for r in rows]
        output.append(
            {
                "kind": kind,
                "first_observed_at": min(times).isoformat() if times else None,
                "last_observed_at": max(times).isoformat() if times else None,
                "observation_count": len(
                    {(tuple(sorted(r.course_ids)), r.source_ref, r.key, r.ordering()) for r in rows}
                ),
            }
        )
    return output


def bound_detail(result):
    # Keep the exact denominators and the evidence fingerprint even when a large
    # inventory cannot fit its individual source traces in one response.
    families = [f for p in result["periods"] for f in p["families"] if f.get("source_refs")]
    while families and len(json.dumps(result).encode()) > 95_000:
        f = max(families, key=lambda f: len(f["source_refs"]))
        n = (len(f["source_refs"]) + 1) // 2
        del f["source_refs"][-n:]
        f["trace_omitted"] += n
        if not f["source_refs"]:
            families.remove(f)


def comparison_context(periods):
    first, second = periods
    context = {
        "previous_elapsed_hours": first["elapsed_hours"],
        "current_elapsed_hours": second["elapsed_hours"],
        "window_duration_changed": first["elapsed_hours"] != second["elapsed_hours"],
        "attribution": "Descriptive changes over the recorded populations.",
        "snapshot_comparisons": [],
    }
    for a, b in zip(first["families"], second["families"], strict=True):
        for x, y in zip(a.get("snapshots", []), b.get("snapshots", []), strict=True):
            context["snapshot_comparisons"].append(
                {
                    "state": x["state"],
                    "previous_snapshot": x.get("snapshot_id"),
                    "current_snapshot": y.get("snapshot_id"),
                    "previous_busy_version": x.get("busy_version"),
                    "current_busy_version": y.get("busy_version"),
                    "busy_context_changed": (
                        x["busy_version"] != y["busy_version"]
                        if x.get("busy_version") and y.get("busy_version")
                        else None
                    ),
                    "previous_busy_coverage": x.get("busy_coverage", "unavailable"),
                    "current_busy_coverage": y.get("busy_coverage", "unavailable"),
                }
            )
    return context


def build(history, request, *, scope_binding, synthetic, now):
    periods, populations = [], []
    for window in request.windows:
        families, membership = due_metrics(history, request, window)
        for name, compute in (
            ("schedule_conflicts", schedule_metric),
            ("effort_calibration", effort_metric),
            ("coordination", coordination_metric),
        ):
            if name in request.families:
                families.append(compute(history, request, window))
        for family in families:
            family["definition_version"] = VERSION
            affected = [
                reason
                for reason in history.limitations
                if reason
                not in {
                    "incomplete_retained_plan",
                    "incomplete_retained_plan_candidate",
                    "incomplete_retained_progress",
                }
                or family["metric_id"]
                in (
                    {"personal_completion"}
                    if reason == "incomplete_retained_progress"
                    else {"schedule_conflicts", "effort_calibration"}
                )
            ]
            if affected:
                family["limitations"] = sorted(set(family["limitations"] + affected))
                if family["availability"] == "available":
                    family["availability"] = "partial"
        periods.append(
            {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "elapsed_hours": (window.end - window.start).total_seconds() / 3600,
                "families": families,
            }
        )
        populations.append(membership)
    request_data = request.model_dump(mode="json", exclude={"restates"})
    coverage = sorted(history.coverage, key=fingerprint)
    digest = fingerprint(
        [
            VERSION,
            scope_binding,
            synthetic,
            request_data,
            observations(history, request),
            sorted(history.bindings),
            coverage,
            sorted(history.limitations),
        ]
    )
    result = {
        "report_id": digest,
        "schema_version": VERSION,
        "input_fingerprint": digest,
        "generated_at": now.isoformat(),
        "course_ids": request.course_ids,
        "timezone": request.timezone,
        "as_of": request.as_of.isoformat(),
        "evidence_cutoff": request.evidence_cutoff.isoformat(),
        "source_selection": "authorized_retained_observations",
        "synthetic": synthetic,
        "inventory_coverage": coverage,
        "measurement_history": history_coverage(history, request),
        "collection_counts": history.scanned,
        "periods": periods,
        "comparison": compare(*periods) if len(periods) == 2 else [],
        "comparison_context": comparison_context(periods) if len(periods) == 2 else None,
        "interpretation": [summary(p) for p in periods],
        "limitations": sorted(set(history.limitations)),
    }
    if "deadline_outcomes" in request.families:
        cohorts = [
            next(f for f in p["families"] if f["metric_id"] == "deadline_outcomes") for p in periods
        ]
        missed = sum(f["counts"]["missed"] for f in cohorts)
        known = sum(f["evaluated"] for f in cohorts)
        eligible = sum(f["eligible"] for f in cohorts)
        from canvas_bridge.analytics.academic_metrics import measure

        result["pooled_deadline_outcomes"] = measure("missed_rate", missed, known) | {
            "eligible": eligible,
            "observation_coverage": measure("observation_coverage", known, eligible),
            "unknown": sum(f["unknown"] for f in cohorts),
        }
    bound_detail(result)
    return result, populations


def restatement(old, new, populations):
    changes = []
    for index, (a, b) in enumerate(zip(old["populations"], populations, strict=True)):
        for family in sorted(a):
            previous, current = {tuple(v) for v in a[family]}, {tuple(v) for v in b[family]}
            changes.append(
                {
                    "period_index": index,
                    "family": family,
                    "added_to_window": sorted(current - previous),
                    "removed_from_window": sorted(previous - current),
                }
            )
    return {
        "prior_report_id": old["report"]["report_id"],
        "prior_evidence_cutoff": old["report"]["evidence_cutoff"],
        "prior_input_fingerprint": old["report"]["input_fingerprint"],
        "cohort_changes": changes,
        "measurement_changes": [
            c | {"period_index": i}
            for i, (a, b) in enumerate(zip(old["report"]["periods"], new["periods"], strict=True))
            for c in compare(a, b)
            if c["previous_value"] != c["current_value"]
            or c["previous_sample_count"] != c["current_sample_count"]
        ],
        "reason": "recomputed_from_selected_observation_versions",
    }


def report(bridge, owner, ref, request, *, save=False):
    start = monotonic()
    if request.evidence_cutoff > utcnow():
        raise DomainError("needs_input", "Select an evidence cutoff at or before the current time.")
    history, epoch = load_history(bridge, owner, ref, request)
    data, populations = build(
        history, request, scope_binding=[owner, ref], synthetic=bool(bridge.synthetic), now=utcnow()
    )
    with bridge.store.transaction() as session:
        if save:
            bridge.store.principal(session, owner)
        conn = bridge.store.connection(session, owner, ref, lock=True)
        if conn.epoch != epoch:
            raise DomainError("source_changed", "Course scope changed during the review.")

        def saved(key):
            return session.scalar(
                select(LocalRecord).where(
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == ref,
                    LocalRecord.kind == REPORT,
                    LocalRecord.key == key,
                )
            )

        if request.restates:
            previous = saved(request.restates)
            compatibility = request.model_dump(mode="json", exclude={"restates", "evidence_cutoff"})
            if (
                not previous
                or previous.payload["request"] != compatibility
                or request.evidence_cutoff
                < datetime.fromisoformat(previous.payload["report"]["evidence_cutoff"])
            ):
                raise DomainError(
                    "needs_input",
                    "Choose a saved report with matching scope, windows, definitions and state cutoff.",
                )
            history.bindings.update(tuple(b) for b in previous.payload["bindings"])
            data["restatement"] = restatement(previous.payload, data, populations)
            data["report_id"] = fingerprint([data["report_id"], request.restates])
        prior_save = saved(data["report_id"]) if save else None
        if prior_save:
            data = dict(prior_save.payload["report"])
        elif save:
            session.add(
                LocalRecord(
                    owner=owner,
                    connection_id=ref,
                    kind=REPORT,
                    key=data["report_id"],
                    payload={
                        "report": data,
                        "populations": populations,
                        "bindings": sorted(history.bindings),
                        "request": request.model_dump(
                            mode="json", exclude={"restates", "evidence_cutoff"}
                        ),
                    },
                )
            )
    data["elapsed_ms"] = round((monotonic() - start) * 1000)
    return present(bridge, data, history.bindings)


def present(bridge, data, bindings):
    partial = any(f["availability"] != "available" for p in data["periods"] for f in p["families"])
    result = ScopedResult(
        status="partial_data" if partial else "ok",
        summary=("Synthetic review. " if bridge.synthetic else "Academic review. ")
        + data["interpretation"][-1],
        data=data,
        meta=bridge.meta(
            display_timezone=data["timezone"],
            freshness="synthetic" if bridge.synthetic else "cached",
        ),
    )
    result._analytics_bindings = sorted(tuple(binding) for binding in bindings)
    return result


def read_saved(bridge, owner, ref, report_id):
    with bridge.store.transaction() as session:
        bridge.store.connection(session, owner, ref)
        row = session.scalar(
            select(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind == REPORT,
                LocalRecord.key == report_id,
            )
        )
        if not row:
            raise DomainError("permission_denied", "This saved review is unavailable.")
        data = row.payload["report"]
        bridge.selected(
            owner, ref, data["course_ids"], resource_type="assignments", operation="read"
        )
        return present(bridge, data, row.payload["bindings"])
