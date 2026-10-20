"""Changes between consecutive complete observations; never fabricated history."""

from canvas_bridge.evidence import fingerprint
from canvas_bridge.storage import aware

FIELDS = (
    "title",
    "effective_due",
    "available_from",
    "closes_at",
    "points_possible",
    "submission_requirement",
    "instruction_hash",
    "submission_state",
    "assessment_state",
)


def compare_snapshots(rows):
    changes = []
    for before, after in zip(rows, rows[1:], strict=False):
        old, new = ({x["id"]: x for x in r.items} for r in (before, after))
        for key in sorted(old.keys() | new.keys()):
            events = []
            if key not in old:
                events.append({"kind": "first_observed"})
            elif key not in new:
                events.append({"kind": "no_longer_observed", "not_proof_of_deletion": True})
            else:
                for field in FIELDS:
                    # Old snapshots have no instruction fingerprint. Upgrading
                    # the schema is not evidence that instructions changed.
                    if field not in old[key] or field not in new[key]:
                        continue
                    if field == "instruction_hash" and (
                        old[key][field] is None or new[key][field] is None
                    ):
                        continue
                    if old[key][field] != new[key][field]:
                        events.append(
                            {"field": field, "old": old[key][field], "new": new[key][field]}
                        )
            for event in events:
                source = new.get(key, old.get(key, {})).get("source", {})
                event.update(
                    work_id=key,
                    observed_at=aware(after.created_at).isoformat(),
                    source_modified_at=source.get("source_updated_at"),
                    source_url=source.get("url"),
                    previous_snapshot=before.id,
                    snapshot_id=after.id,
                )
                event["notification_key"] = fingerprint(
                    [after.owner, after.connection_id, after.id, key, event]
                )
                changes.append(event)
    return changes
