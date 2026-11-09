"""Reconcile version-bound work occurrences without treating progress as artifact evidence."""

from canvas_bridge.evidence import fingerprint


def reconcile(before, after, stage, material_changes):
    old = {r["requirement_id"]: r for r in before.data["requirements"]}
    new = {r["requirement_id"]: r for r in after.data["requirements"]}
    history = {k: dict(v) for k, v in before.data.get("work_history", {}).items()}
    actions = []
    progress = {}
    fields = {}
    alias_only = all(c["change_class"] == "alias_only" for c in stage["comparisons"])
    for ident in sorted(old.keys() | new.keys()):
        previous = old.get(ident, {})
        current = new.get(ident, {})
        prior = previous.get("work_item")
        work = current.get("work_item")
        lineage = history.get(ident)
        if prior:
            lineage = dict(
                lineage or {},
                lineage_id=prior.get(
                    "lineage_id", fingerprint([before.id, ident, previous["gap_kind"]])
                ),
                episode_id=prior.get(
                    "episode_id", fingerprint([before.id, prior["work_id"], "episode"])
                ),
                occurrence_id=prior["work_id"],
                gap_kind=previous["gap_kind"],
                state="active",
                prior_progress=before.data["progress"].get(prior["work_id"], "unknown"),
            )
        if not lineage and not work:
            continue
        if not work:
            if not prior and (not lineage or lineage["state"] != "pending"):
                continue
            if not current or current.get("applicability") == "not_applicable":
                action = "retire"
            elif current["assessment_status"] == "satisfied":
                action = "resolve"
            else:
                action = "review_needed"
            lineage["state"] = {
                "resolve": "resolved",
                "retire": "retired",
                "review_needed": "pending",
            }[action]
        else:
            if not lineage:
                action = "create"
                lineage = dict(lineage_id=fingerprint([before.id, ident, current["gap_kind"]]))
            elif (
                lineage["state"] in {"resolved", "retired"}
                or ident in material_changes
                or lineage.get("gap_kind") != current["gap_kind"]
            ):
                action = "reopen"
            elif prior and (
                previous["action"] != current["action"]
                or previous["completion_condition"] != current["completion_condition"]
                or before.data["requirement_set_revision"] != after.data["requirement_set_revision"]
                or any(
                    c.get("proof_kind") == "nonblank_lines"
                    and c["logical_id"] in {a["source"] for a in previous["evidence"]}
                    for c in stage["comparisons"]
                )
            ):
                action = "update"
            else:
                action = "keep"
            fresh = action in {"create", "reopen"}
            if fresh:
                lineage["episode_id"] = fingerprint(
                    [lineage["lineage_id"], stage["change_id"], ident]
                )
            state = "not_started" if fresh else lineage.get("prior_progress", "unknown")
            occurrence = (
                fingerprint([work["work_id"], lineage["episode_id"]])
                if fresh or not prior
                else (
                    prior["work_id"]
                    if alias_only or before.data["bindings"] == after.data["bindings"]
                    else fingerprint([work["work_id"], lineage["episode_id"]])
                )
            )
            work.update(
                work_id=occurrence,
                lineage_id=lineage["lineage_id"],
                episode_id=lineage["episode_id"],
                progress_basis="system_default"
                if fresh or state in {"unknown", "not_started"}
                else "user_declaration",
            )
            progress[occurrence] = state
            if not fresh:
                original_fields = before.data.get("personal_fields", {}).get(
                    prior["work_id"] if prior else lineage.get("occurrence_id"), {}
                )
                fields[occurrence] = dict(original_fields)
            if (
                fresh
                and prior
                and before.data.get("personal_fields", {}).get(prior["work_id"], {}).get("effort")
            ):
                work["effort_review_needed"] = True
                work["historical_estimate_revision"] = stage["base_revision"]
            lineage.update(
                state="active",
                occurrence_id=occurrence,
                gap_kind=current["gap_kind"],
                prior_progress=state,
            )
        history[ident] = lineage
        actions.append(
            dict(
                requirement_id=ident,
                work_action=action,
                lineage_id=lineage["lineage_id"],
                episode_id=lineage["episode_id"],
                prior_occurrence_id=prior["work_id"] if prior else None,
                current_occurrence_id=work["work_id"] if work else None,
            )
        )
    reasons = {
        "keep": "same_fulfillment_scope",
        "update": "continuing_gap_rebound",
        "reopen": "recurrence_or_new_fulfillment",
        "resolve": "current_satisfaction",
        "retire": "supported_scope_exclusion",
        "create": "new_supported_gap",
        "review_needed": "insufficient_current_evidence",
    }
    for decision in actions:
        decision["action_reason"] = reasons[decision["work_action"]]
    return history, progress, actions, fields
