"""Discard peer bodies and identities at the upstream boundary, before any cache.

Structural records live only for the current bounded scan. They are not peer
content disclosure. No display-name matching or anonymity reconstruction occurs.
"""

import re

from canvas_bridge.normalize import plain_text
from canvas_bridge.privacy.identity import IdentityClass
from canvas_bridge.privacy_text import WITHHELD, inspect_text


def minimize_thread(
    payload, identity, *, full_view=False, max_entries=10000, text_limit=50000, parent_entry=None
):
    reasons, aliases = set(), set()
    visited = 0

    def names(value, depth=0):
        nonlocal visited
        visited += 1
        if depth > 32 or visited > 100000 or len(aliases) > 256:
            reasons.add("privacy_inspection_limit")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "user_name",
                    "display_name",
                    "name",
                    "short_name",
                    "login_id",
                } and isinstance(item, str):
                    aliases.add(item)
                elif isinstance(item, (dict, list)):
                    names(item, depth + 1)
        elif isinstance(value, list):
            for item in value[: max_entries + 1]:
                names(item, depth + 1)

    names(payload)
    count = 0

    def flatten(values, *, flat=False):
        nonlocal count
        out = []
        if not isinstance(values, list):
            reasons.add("unsupported_response")
            return out
        stack = [(row, parent_entry, 0) for row in reversed(values)]
        while stack:
            row, parent, depth = stack.pop()
            count += 1
            if count > max_entries or depth > 32:
                reasons.add("entry_limit")
                break
            if not isinstance(row, dict):
                reasons.add("unsupported_response")
                continue
            uid = row.get("user_id")
            own = identity.classify(
                uid if type(uid) in {int, str} and re.fullmatch(r"[0-9]{1,20}", str(uid)) else None
            )
            # Only numeric authoritative user IDs establish ownership. Anonymous
            # records remain unknown even if user_name happens to match.
            state = (
                "self"
                if own == IdentityClass.FIRST_PARTY_VERIFIED
                else "other"
                if own == IdentityClass.THIRD_PARTY
                else "unknown"
            )
            record = {
                k: row[k]
                for k in (
                    "id",
                    "parent_id",
                    "created_at",
                    "updated_at",
                    "deleted",
                    "has_more_replies",
                )
                if k in row and not isinstance(row[k], (dict, list))
            }
            record["identity_state"] = state
            if "parent_id" in row and isinstance(row["parent_id"], (dict, list)):
                record["parent_unknown"] = True
            if "deleted" in row and type(row["deleted"]) is not bool:
                reasons.add("deleted_entry_uncertainty")
                record["message_available"] = False
            if "recent_replies" in row and type(row.get("has_more_replies")) is not bool:
                # Missing truncation metadata cannot establish complete replies.
                record["has_more_replies"] = True
            if "parent_id" not in row:
                if flat:
                    record["parent_unknown"] = True
                else:
                    record["parent_id"] = parent
            elif parent is not None and str(row.get("parent_id")) != str(parent):
                record["parent_unknown"] = True
            record.setdefault("message_available", isinstance(row.get("message"), str))
            if state == "self" and row.get("deleted") is not True:
                message = row.get("message")
                if isinstance(message, str):
                    text = plain_text(message, text_limit + 1)
                    record["text_truncated"] = (
                        len(text) > text_limit or len(message) > (text_limit + 1) * 4
                    )
                    record["message_text"] = (
                        WITHHELD
                        if "privacy_inspection_limit" in reasons
                        else inspect_text(text[:text_limit], aliases)[0]
                    )
            out.append(record)
            for key in ("replies", "recent_replies"):
                if key in row:
                    if not isinstance(row[key], list):
                        reasons.add("missing_replies")
                        continue
                    stack.extend((child, row.get("id"), depth + 1) for child in reversed(row[key]))
        return out

    if full_view:
        if not isinstance(payload, dict):
            return {
                "records": [],
                "new_records": [],
                "reasons": ["unsupported_response"],
                "reconciled": False,
            }
        records = flatten(payload.get("view"))
        new = flatten(payload["new_entries"], flat=True) if "new_entries" in payload else []
        reconciled = isinstance(payload.get("new_entries"), list)
    else:
        records, new, reconciled = flatten(payload), [], False
    return {
        "records": records,
        "new_records": new,
        "reasons": sorted(reasons),
        "reconciled": reconciled,
    }
