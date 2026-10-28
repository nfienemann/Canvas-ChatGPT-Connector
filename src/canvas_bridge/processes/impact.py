"""Canonical field changes produce stable proposals, never calendar mutations."""

from datetime import datetime

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.state import descendants

SCHEDULING_FIELDS = frozenset(
    {"deadline", "due_at", "duration", "effort", "prerequisites", "availability"}
)
REVIEW_FIELDS = frozenset({"requirements", "policy", "weight", "score", "completion", "stage"})


def canonical_fields(record):
    if "canonical_fields" in record.data:
        return record.data["canonical_fields"]
    # Parser diagnostics and observation timestamps are not academic changes.
    return {
        k: v for k, v in record.data.items() if k in SCHEDULING_FIELDS | REVIEW_FIELDS | {"title"}
    }


def impact_proposals(state, before, after, *, now):
    if before.id != after.id or before.scope != after.scope:
        raise ValueError("Impact requires the same canonical record and scope.")
    old, new = canonical_fields(before), canonical_fields(after)
    diff = {
        key: {"before": old.get(key), "after": new.get(key)}
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    }
    if not diff:
        return []
    event_id = fingerprint(
        [before.id, before.scope.model_dump(), before.revision, after.revision, diff]
    )
    material = bool(diff.keys() & SCHEDULING_FIELDS)
    review = bool(diff.keys() & REVIEW_FIELDS)
    proposals = []
    # A canonical change remains reviewable even before a downstream plan exists.
    # Once dependencies exist, proposals point to the records needing repair.
    for ident in descendants(state, before.id) or (before.id,):
        record = state.records[ident]
        deadline = record.data.get("deadline")
        try:
            date = datetime.fromisoformat(deadline) if isinstance(deadline, str) else None
            seconds = (date - now).total_seconds() if date and date.tzinfo else None
        except ValueError:
            seconds = None
        proposals.append(
            {
                "id": fingerprint([event_id, ident]),
                "event_id": event_id,
                "record_id": ident,
                "classification": "action_required"
                if material
                else "review_needed"
                if review
                else "informational",
                "diff": diff,
                "reschedule_proposed": material and record.kind in {"plan", "reminder"},
                "deadline_seconds": seconds,
                "external_action": False,
                "approval_required_for_external_write": True,
            }
        )
    return sorted(
        proposals,
        key=lambda p: (p["deadline_seconds"] is None, p["deadline_seconds"] or 0, p["id"]),
    )
