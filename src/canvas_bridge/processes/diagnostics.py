"""Allowlisted support reports: no exception strings, coursework or identity."""

from canvas_bridge.domain import opaque_id
from canvas_bridge.processes import VERSION

CATEGORIES = {
    "connector": "Check connection status and supported provider capabilities.",
    "parsing": "Review extraction coverage and retry a supported source format.",
    "authorization": "Review the access reason in settings; do not paste credentials.",
    "state": "Refresh current revisions and review recovery options.",
    "sync": "Inspect the action receipt before retrying an uncertain operation.",
    "interpretation": "Inspect the cited source and mark unsupported conclusions unknown.",
}


def support_report(category):
    if category not in CATEGORIES:
        raise ValueError("Unknown diagnostic category.")
    return {
        "schema_version": "academic-support-1",
        "event_id": opaque_id(),
        "correlation_id": opaque_id(),
        "component_version": VERSION,
        "category": category,
        "reason_code": "PROCESS_" + category.upper() + "_REVIEW",
        "next_step": CATEGORIES[category],
        "contains_coursework": False,
        "sharing_status": "preview_only",
    }


def preview_report(report):
    """Accept only our fixed schema and static fields, never freeform log attachments."""
    import json

    expected = support_report(report.get("category"))
    if set(report) != set(expected) or any(
        report[k] != v for k, v in expected.items() if k not in {"event_id", "correlation_id"}
    ):
        raise ValueError("Diagnostic report contains unreviewed fields.")
    for key in ("event_id", "correlation_id"):
        import re

        if not isinstance(report[key], str) or not re.fullmatch(r"[a-f0-9]{32}", report[key]):
            raise ValueError("Invalid opaque diagnostic identity.")
    return {
        "exact_payload": json.dumps(report, sort_keys=True, separators=(",", ":")),
        "sent": False,
        "explicit_sharing_opt_in_required": True,
    }
