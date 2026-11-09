"""Membership evidence and operational clocks. Historical times never authorize reads."""

from datetime import UTC, timedelta

from canvas_bridge.storage import aware

MEMBERSHIP_FIELDS = (
    "last_course_list_attempt_at",
    "last_course_list_outcome",
    "last_complete_course_list_at",
    "membership_evidence_at",
    "membership_lease_expires_at",
    "membership_lease_state",
)


def utc_timestamp(value):
    return aware(value).astimezone(UTC).isoformat() if value is not None else None


def membership_state(evidence, evaluated_at, lease_seconds):
    if evidence is None:
        return "missing"
    age = (evaluated_at - aware(evidence)).total_seconds()
    if age < 0:
        return "invalid_clock"
    return "within_lease" if age <= lease_seconds else "expired"


def membership_fields(conn, evaluated_at, lease_seconds):
    evidence = conn.entitlement_at
    return {
        "last_course_list_attempt_at": utc_timestamp(conn.last_course_list_attempt_at),
        "last_course_list_outcome": conn.last_course_list_outcome or "unknown",
        "last_complete_course_list_at": utc_timestamp(conn.last_complete_course_list_at),
        "membership_evidence_at": utc_timestamp(evidence),
        "membership_lease_expires_at": utc_timestamp(
            aware(evidence) + timedelta(seconds=lease_seconds) if evidence else None
        ),
        "membership_lease_state": membership_state(evidence, evaluated_at, lease_seconds),
    }
