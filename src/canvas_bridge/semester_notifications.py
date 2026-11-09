"""Notification eligibility for a separately approved host. Never starts a job."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_bridge.domain import utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning_dates import instant


def notification_decision(
    report, preferences, now, timezone, *, delivered=None, last_delivery=None, approved_host=False
):
    """Pure preview. approved_host is server-owned integration state, not an MCP argument.

    A host must commit a provider receipt before recording delivery. Preparing or
    reading a report does not count as delivery and does not start monitoring.
    """
    result = {
        "active": False,
        "delivery_state": "not_requested",
        "eligible_findings": [],
        "deduplicated_count": 0,
        "requires_explicit_host_schedule": True,
    }
    if not preferences.opted_in:
        return result
    if not approved_host:
        return result | {"delivery_state": "approved_host_schedule_required"}
    local = now.astimezone(ZoneInfo(timezone)).time().replace(tzinfo=None)
    start, end = preferences.quiet_start, preferences.quiet_end
    quiet = start <= local < end if start < end else local >= start or local < end
    if quiet:
        return result | {"delivery_state": "quiet_hours"}
    interval = timedelta(days=1 if preferences.frequency == "daily" else 7)
    if last_delivery and now - datetime.fromisoformat(last_delivery) < interval:
        return result | {"delivery_state": "frequency_limit"}
    try:
        age = instant(now) - instant(datetime.fromisoformat(report["analysis_as_of"]))
        if not timedelta(0) <= age <= timedelta(minutes=5):
            return result | {"delivery_state": "fresh_authorized_analysis_required"}
    except (KeyError, ValueError, TypeError):
        return result | {"delivery_state": "fresh_authorized_analysis_required"}
    delivered = delivered or {}
    eligible = []
    delivery_courses = set()
    for f in report["findings"]:
        if (
            not set(f["course_ids"]) <= set(preferences.course_ids)
            or f["acknowledged"]
            or f["lifecycle"] == "resolved_finding"
        ):
            continue
        if f["priority"]["freshness"] != "current" or f["evidence_status"] in {
            "uncertain",
            "unverified_suspected_change",
        }:
            continue
        if delivered.get(f["issue_key"]) == f["finding_revision"]:
            result["deduplicated_count"] += 1
            continue
        delivery_courses.update(f["course_ids"])
        eligible.append({"issue_key": f["issue_key"], "finding_revision": f["finding_revision"]})
    return result | {
        "delivery_state": "eligible_for_approved_host"
        if eligible
        else "no_new_actionable_findings",
        "eligible_findings": eligible,
        "delivery_key": fingerprint(eligible) if eligible else None,
        "delivery_course_ids": sorted(delivery_courses),
    }


def delivery_receipt_state(state, decision, *, provider_receipt, delivered_at):
    """Trusted adapter boundary after confirmed delivery, never exposed as an MCP tool.

    Uncertain/failed sends must be reconciled by the adapter with the stable
    delivery_key; it must not call this helper or blindly re-send. This pure
    helper does not authorize sending, schedule work, or persist anything.
    """
    delivered_at = instant(delivered_at)
    if not provider_receipt or decision["delivery_state"] != "eligible_for_approved_host":
        raise ValueError(
            "A confirmed provider delivery receipt and eligible decision are required."
        )
    delivered = dict(state.get("delivered", {}))
    for row in decision["eligible_findings"]:
        delivered[row["issue_key"]] = row["finding_revision"]
    receipt_hash = fingerprint(provider_receipt)
    # This is the existing trusted post-delivery boundary. Preserve a small
    # course-bound receipt for analytics only when the decision carries that scope.
    effects = dict(state.get("confirmed_deliveries", {}))
    if decision.get("delivery_key") and decision.get("delivery_course_ids"):
        effects.setdefault(
            decision["delivery_key"],
            {
                "receipt_hash": receipt_hash,
                "course_ids": decision["delivery_course_ids"],
                "delivered_at": delivered_at.isoformat(),
                "observed_at": utcnow().isoformat(),
            },
        )
    return state | {
        "confirmed_deliveries": dict(list(effects.items())[-200:]),
        "delivered": dict(list(delivered.items())[-1000:]),
        "last_delivery": delivered_at.isoformat(),
        "provider_receipt_hash": receipt_hash,
    }
