"""Pure obligation accounting, limited practice checks and meaningful transition digests."""

import re
from datetime import UTC, datetime

from canvas_bridge.academic.independent_engine import work_items
from canvas_bridge.academic.study_steps import step_parents
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning import PlanRequest, propose

PRACTICE = {
    "control_purpose": "Generated ungraded practice: in a new experiment testing light exposure on seedlings, name a comparison group and explain what it helps isolate.",
    "result_implication": "Generated ungraded practice: a fictional treatment increased the measured response from 4 to 6 units. Write one sentence reporting the result and a separate sentence stating a cautious implication.",
    "claim_evidence": "Generated ungraded practice: choose a claim from a permitted reading, cite one supporting observation, and state one limitation.",
    "axis_units": "Generated ungraded practice: on a permitted figure, identify each axis and its units, then describe one supported comparison without inventing values.",
    "clarify": "Clarify which part of the cited feedback you want to address; no instructor message has been sent.",
}


def check_control(response):
    text = response.casefold()
    names_control = bool(
        re.search(r"\b(control|comparison|untreated|placebo|vehicle|without|no light)\b", text)
    )
    explains_purpose = bool(
        re.search(
            r"\b(to isolate|to compare|to account for|to attribute|provides? a baseline|so that|because)\b",
            text,
        )
    )
    return {
        "named_comparison": names_control,
        "explained_purpose": explains_purpose,
        "outcome": "criteria_detected_needs_review"
        if names_control and explains_purpose
        else "incomplete",
        "evaluation_method": "bounded_keyword_check_not_semantic_grading",
        "mastery_established": False,
    }


def obligations(dataset, source, *, now, plan=None):
    items = work_items(dataset, source)
    parents = step_parents(dataset)
    decomposed = set(parents.values())
    statuses, eligible = {}, []
    grouped = {}
    for group in dataset.requirement_groups:
        for key in group.members:
            grouped[key] = (
                "unresolved_choice"
                if len(group.selected) < group.minimum
                else "selected"
                if key in group.selected
                else "optional_group_alternative"
            )
    for work, item in zip(dataset.work, items, strict=True):
        reason = (
            grouped[work.key]
            if grouped.get(work.key) not in {None, "selected"}
            else "optional"
            if work.requirement == "optional"
            else "requirement_unresolved"
            if work.requirement == "unresolved"
            else "responsibility_unresolved"
            if work.responsibility != "self"
            else "student_reports_" + work.reported_status
            if work.reported_status != "unknown" and not work.revision_requested
            else "student_marked_done"
            if work.progress == "student_marked_done" and not work.revision_requested
            else "planned_in_study_steps"
            if work.key in decomposed
            else None
        )
        if reason:
            statuses[work.key] = {
                "state": "optional"
                if "optional" in reason
                else "unresolved"
                if "unresolved" in reason
                else "excluded",
                "reason": reason,
            }
        else:
            eligible.append(item)
    # These owner-reported states resolve edges only inside this imported graph.
    # Optional, inaccessible and unresolved rows supply no completion evidence.
    completed = {
        key
        for key, state in statuses.items()
        if state["reason"]
        in {
            "student_marked_done",
            "student_reports_submitted",
            "student_reports_graded",
            "student_reports_excused",
        }
    }
    proposal = propose(eligible, plan or PlanRequest(), now, completed_prerequisites=completed)
    summary = proposal["effort_summary"]
    summary["completed_work_ids"] = sorted(completed)
    summary["unresolved_requirement_ids"] = sorted(
        key for key, status in statuses.items() if status["state"] == "unresolved"
    )
    # A named receipt check remains part of the step's existing estimate. It
    # creates neither an extra allocation nor evidence of submission.
    checks = [
        row
        for row in dataset.work
        if row.key not in statuses
        and (
            row.completion_rule == "verify_submission_receipt"
            or (
                not row.completion_rule
                and row.key in parents
                and re.match(
                    r"(?:check|verify)\b.*\b(?:submission evidence|submission receipt|receipt evidence)\b",
                    row.title.removeprefix(parents[row.key] + " / ").strip(),
                    re.I,
                )
            )
        )
    ]
    summary["receipt_verification_work_ids"] = sorted(row.key for row in checks)
    summary["receipt_checks"] = [
        {"work_id": row.key, "title": row.title} for row in sorted(checks, key=lambda r: r.key)
    ]
    for step, parent in parents.items():
        timing = proposal["timing_constraints"].get(step)
        if timing:
            timing.update(parent_key=parent, deadline_basis="inherited_planning_cutoff")
    accounting = proposal.pop("work_accounting", {})
    accounting.update(statuses)
    if any(v["state"] == "unresolved" for v in statuses.values()):
        proposal["information_status"] = "uncertain"
    return {
        "activities": [
            w.model_dump(mode="json")
            | {
                "official_submission": "unknown",
                "course": source.course_id or source.id,
                "source_id": source.id,
                "content_hash": source.content_hash,
            }
            for w in dataset.work
        ],
        "requirement_groups": [g.model_dump(mode="json") for g in dataset.requirement_groups],
        "accounting": [{"work_id": key, **value} for key, value in accounting.items()],
        "plan": proposal,
        "inventory_hash": fingerprint([dataset.model_dump(mode="json"), source.content_hash]),
        "coverage": "complete_selected_records" if dataset.complete else "partial_reviewed_records",
        "caught_up": False,
        "limitations": [
            "Imported states are student-provided assertions, not official receipts. Unchecked activity types remain unknown."
        ],
    }


def semantic(work):
    # Transport and parser details are deliberately absent; evidence hashes remain separate.
    fields = {k: v for k, v in work.items() if k not in {"evidence", "requirement_basis"}}
    if "title" in fields:
        fields["title"] = " ".join(fields["title"].split())
    if fields.get("effort"):
        fields["effort"] = {k: v for k, v in fields["effort"].items() if k != "as_of"}
    for field in ("due", "opens", "closes"):
        if isinstance(fields.get(field), dict):
            fields[field] = {k: v for k, v in fields[field].items() if k != "raw"}
            if fields[field].get("timestamp"):
                fields[field]["timestamp"] = (
                    datetime.fromisoformat(fields[field]["timestamp"]).astimezone(UTC).isoformat()
                )
    return fields


def transitions(before, after, transition_id, *, plans=()):
    old = {w["key"]: w for w in before.get("dataset", {}).get("work", [])}
    new = {w["key"]: w for w in after.get("dataset", {}).get("work", [])}
    events = []
    for key in sorted(old.keys() & new.keys()):
        left, right = semantic(old[key]), semantic(new[key])
        fields = [k for k in left.keys() | right.keys() if left.get(k) != right.get(k)]
        if not fields:
            continue
        category, action, affected = (
            "review_suggested",
            "Review the cited change before replanning.",
            [],
        )
        due_old, due_new = left.get("due", {}), right.get("due", {})
        basis = "changed_reviewed_records_not_verified_instructor_activity"
        if "due" in fields and due_old.get("kind") == due_new.get("kind"):
            kind = due_new.get("kind")
            field = "timestamp" if kind == "timestamp" else "local_date"
            earlier = (
                datetime.fromisoformat(due_new[field]) < datetime.fromisoformat(due_old[field])
                if kind == "timestamp" and due_new.get(field) and due_old.get(field)
                else bool(
                    due_new.get(field) and due_old.get(field) and due_new[field] < due_old[field]
                )
            )
            if kind in {"timestamp", "local_date"} and earlier:
                category, action = (
                    "action_needed",
                    "Review work planned after the earlier deadline. No plan or calendar was changed.",
                )
                for plan in plans:
                    for block in plan.data["value"].get("blocks", []):
                        if block.get("work_id") != key:
                            continue
                        if kind == "timestamp":
                            conflict = datetime.fromisoformat(
                                block["end"]
                            ) > datetime.fromisoformat(due_new[field])
                        else:
                            # Cross-day impact only; a date-only source supplies no exact deadline time.
                            # Without a reviewed display timezone, this is only
                            # a request to inspect the block, not an exact conflict.
                            conflict = (
                                datetime.fromisoformat(block["end"]).date().isoformat()
                                > due_new[field]
                            )
                        if conflict:
                            affected.append(plan.id)
                basis = (
                    "earlier_same_precision_deadline; date_only_is_not_an_exact_reschedule"
                    if kind == "local_date"
                    else "earlier_explicit_instant"
                )
        elif "due" in fields:
            basis = "date_precision_changed_requires_review"
        events.append(
            {
                "event_id": fingerprint([transition_id, key, sorted(fields)]),
                "work_id": key,
                "category": category,
                "changed_fields": sorted(fields),
                "old_value": left,
                "new_value": right,
                "old_evidence": old[key].get("evidence", []),
                "new_evidence": new[key].get("evidence", []),
                "impact_basis": basis,
                "affected_plan_ids": sorted(set(affected)),
                "recommended_action": action,
                "acknowledgment": "unacknowledged",
                "delivery": "not_requested",
            }
        )
    for key in sorted(new.keys() - old.keys()):
        events.append(
            {
                "event_id": fingerprint([transition_id, key, "newly_reviewed"]),
                "work_id": key,
                "category": "informational",
                "changed_fields": ["newly_reviewed"],
                "new_evidence": new[key].get("evidence", []),
                "recommended_action": "Review newly included work; publication time is unknown.",
                "impact_basis": "first_observation_not_instructor_publication",
                "delivery": "not_requested",
            }
        )
    return events
