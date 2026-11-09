"""Project scoped readiness and response applicability from authorized, versioned records."""

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import (
    effort_service as effort,
)
from canvas_bridge.processes import (
    readiness as rd,
)
from canvas_bridge.processes import (
    resource_service as resources,
)
from canvas_bridge.processes.state import failure


def assess(record, logical_id, criterion_ids):
    bindings = {b["logical_id"]: b for b in record.data["bindings"]}
    artifact = bindings.get(logical_id)
    if not artifact or artifact["role"] != "artifact":
        failure("HANDOFF_ARTIFACT_SCOPE")
    rows = {r["requirement_id"]: r for r in record.data["requirements"]}
    ids = sorted(criterion_ids or rows)
    projected = []
    for ident in ids:
        r = rows.get(ident)
        if not r:
            projected.append(
                dict(
                    requirement_id=ident,
                    criterion=ident,
                    assessment_status="unknown",
                    applicability="unknown",
                    required=True,
                    evidence=[],
                    dependency_versions={},
                    reason="requirement_unavailable",
                )
            )
            continue
        deps = rd.dependencies(r, [rd.Binding.model_validate(v) for v in bindings.values()])
        available = all(bindings.get(k, {}).get("document_id") for k in deps)
        if r["coverage_rule"] in {"absence", "all_claims"}:
            # Older readiness records may have been approved after inspecting only
            # one artifact. Do not carry that assertion onto an unexamined file.
            inspected = {e["source"] for e in r.get("reviewed_extent", []) if e["parts"]}
            available &= all(
                b["logical_id"] in inspected for b in bindings.values() if b["role"] == "artifact"
            )
        applicable = r["applicability"]
        state = r["assessment_status"]
        reason = "current_assessment"
        if applicable == "not_applicable" and r.get("applicability_basis"):
            state = "not_applicable"
        elif (
            applicable != "applicable"
            or not available
            or not artifact.get("document_id")
            or logical_id not in deps
            or r["coverage"] != "complete"
            or record.data.get("pending_change")
        ):
            state, reason = "unknown", "unavailable_or_incomplete_evidence"
        evidence = []
        if state not in {"unknown", "not_applicable"}:
            for a in [r["governing"], *r["evidence"]]:
                b = bindings[a["source"]]
                evidence.append(
                    a | dict(document_id=b["document_id"], content_hash=b["content_hash"])
                )
        projected.append(
            dict(
                requirement_id=ident,
                criterion=r["criterion"],
                required=r["required"],
                applicability=applicable,
                assessment_status=state,
                reason=reason,
                coverage=r["coverage"],
                evidence=evidence,
                reviewed_extent=r.get("reviewed_extent", []),
                assessed_at=r.get("original_assessed_at", record.data["assessed_at"]),
                validated_at=r.get("carry_forward_validated_at"),
                proof_id=r.get("carry_forward_proof"),
                dependency_versions={k: bindings[k]["content_hash"] for k in sorted(deps)},
                work_id=(r.get("work_item") or {}).get("work_id"),
                evidence_sources=[
                    dict(
                        logical_id=k,
                        content_hash=bindings[k]["content_hash"],
                        document_id=bindings[k]["document_id"],
                    )
                    for k in sorted(deps)
                ],
                next_step=r.get("action") or r.get("followup"),
            )
        )
    complete = (
        bool(ids)
        and all(k in rows for k in ids)
        and (bool(criterion_ids) or record.data["membership_complete"])
    )
    status = rd.summarize(projected, complete)["summary_status"]
    return dict(
        logical_artifact_id=logical_id,
        artifact_version=artifact.get("content_hash"),
        document_id=artifact.get("document_id"),
        scope_locator="selected_criteria",
        inventory_complete=complete,
        artifact_readiness=status,
        criteria=projected,
    )


def work_context(record, work_id, criterion_ids=()):
    if not work_id:
        selected_ids = set(criterion_ids) or {
            r["requirement_id"] for r in record.data["requirements"]
        }
        # C materializes lineage history on first reconciliation. Seed initial
        # episodes identically so merely recording an alias cannot rotate a handoff.
        episodes = {
            k: v["episode_id"]
            for k, v in record.data.get("work_history", {}).items()
            if k in selected_ids and v.get("episode_id")
        }
        for row in record.data["requirements"]:
            if row["requirement_id"] in selected_ids and row.get("work_item"):
                episodes[row["requirement_id"]] = effort.episode(row["work_item"], record.id)
        return dict(
            work_lineage_id=record.id,
            work_episode_id=fingerprint([record.id, "assignment", sorted(episodes.items())]),
            work_occurrence_id=record.id,
            personal_progress="unset",
        )
    selected = next(
        (
            w
            for w in rd.project(record.data, record.data["requirements"])["remaining_work"]
            if w["work_id"] == work_id
        ),
        None,
    )
    if not selected:
        failure("READINESS_WORK_UNAVAILABLE")
    return dict(
        work_lineage_id=selected.get("lineage_id")
        or fingerprint([record.id, selected["requirement_id"], selected["gap_kind"]]),
        work_episode_id=effort.episode(selected, record.id),
        work_occurrence_id=work_id,
        personal_progress=selected["progress_state"],
    )


def process_context(data, record, work, link):
    if not link:
        return dict(scope_state="absent", blockers=[], process_ref=None)
    history = data.get("resource_generations", [])
    latest = resources.previous(data, record.id, link["process_id"])
    g = next(
        (
            g
            for g in history
            if g["record_id"] == record.id
            and g["process"]["id"] == link["process_id"]
            and g["generation_id"] == link["generation_id"]
        ),
        None,
    )
    context = (
        next(
            (
                h
                for h in resources.projection(g, history)["handoff"]
                if h["step_id"] == link["step_id"]
            ),
            None,
        )
        if g
        else None
    )
    current = bool(
        g
        and latest == g
        and context
        and g["work_episode_id"] == work["work_episode_id"]
        and g["work_revision"] == record.revision
    )
    blocks = []
    for b in (context or {}).get("blocker_refs", []):
        scope = (
            "transfer"
            if b["blocker_id"] in link["transfer_blockers"]
            else "requested_action"
            if b["blocker_id"] in link["action_blockers"]
            else "downstream_execution"
        )
        blocks.append(
            b
            | dict(
                scope=scope,
                state=b["state"]
                if current and b["state"] in {"conditional", "blocked", "ready"}
                else "unknown",
            )
        )
    known = {b["blocker_id"] for b in blocks} | set(
        (context or {}).get("resource_allocation_refs", [])
    )
    for scope, refs in (
        ("transfer", link["transfer_blockers"]),
        ("requested_action", link["action_blockers"]),
    ):
        for missing in sorted(set(refs) - known):
            blocks.append(
                dict(
                    blocker_id=missing,
                    scope=scope,
                    state="unknown",
                    source_ref=link["generation_id"],
                    next_action="Verify the selected blocker on this process step.",
                )
            )
    part = None
    if context:
        step = next(s for s in g["process"]["steps"] if s["id"] == link["step_id"])
        part = fingerprint(
            [
                step,
                [
                    e
                    for e in g["process"]["dependencies"]
                    if link["step_id"] in (e["from_step"], e["to_step"])
                ],
                [s for s in g["process"]["supplies"] if s["step_id"] == link["step_id"]],
                [a for a in g["allocations"] if a["step_id"] == link["step_id"]],
                context["reservation_support_refs"],
            ]
        )
    return dict(
        scope_state="current" if current else "unknown",
        blockers=blocks,
        process_ref=link["generation_id"],
        condition_version=part,
        forecast_id=g["forecast_id"] if g else None,
        resource_artifacts=(context or {}).get("required_artifact_refs", []),
        handoff_basis_id=(context or {}).get("handoff_basis_id"),
        step_id=link["step_id"],
        logical_receipt_refs=(context or {}).get("logical_receipt_refs", []),
    )


def context_for(data, record, work, link, declared, at):
    from datetime import datetime

    context = process_context(data, record, work, link)
    for c in declared:
        context["blockers"].append(
            c
            | dict(
                basis="supplied_condition",
                state="unknown"
                if c["expires_at"] and at >= datetime.fromisoformat(c["expires_at"])
                else c["state"],
            )
        )
    return context


def inputs_for(record, action):
    available = {b["logical_id"]: b for b in record.data["bindings"]}
    resolved = []
    for ref in action.get("required_inputs", []):
        b = available.get(ref["logical_id"], {})
        known = bool(
            b.get("document_id")
            and (not ref["expected_hash"] or b["content_hash"] == ref["expected_hash"])
        )
        resolved.append(
            dict(
                logical_id=ref["logical_id"],
                content_hash=b.get("content_hash"),
                availability_state="available" if known else "unknown",
            )
        )
    return resolved


def condition_states(context, action, link):
    def aggregate(scope):
        selected = [b for b in context["blockers"] if b["scope"] == scope]
        states = [b["state"] for b in selected]
        if context["scope_state"] != "current" and (
            any(b.get("basis") != "supplied_condition" for b in selected)
            or (
                link
                and (
                    (scope == "transfer" and link["transfer_blockers"])
                    or (scope == "requested_action" and link["action_blockers"])
                )
            )
            or scope == "downstream_execution"
            and action["requires_process_context"]
        ):
            return "unknown"
        return next(
            (state for state in ("blocked", "unknown", "conditional") if state in states), "ready"
        )

    return {k: aggregate(k) for k in ("transfer", "requested_action", "downstream_execution")}


def basis(record, assessment, work, role, action, context, link):
    relevant = [
        {
            k: b.get(k)
            for k in ("blocker_id", "scope", "state", "source_ref", "revision", "expires_at")
        }
        for b in context["blockers"]
        if b["scope"] != "downstream_execution" or action["requires_process_context"]
    ]
    states = condition_states(context, action, link)
    selected = [
        dict(
            requirement_id=r["requirement_id"],
            criterion=r["criterion"],
            applicability=r["applicability"],
            required=r["required"],
            assessment_status=r["assessment_status"],
            dependencies=r["dependency_versions"],
            evidence_scope=[
                {k: a[k] for k in ("source", "part", "surface", "quote")} for a in r["evidence"]
            ],
            reviewed_extent=r.get("reviewed_extent", []),
            coverage=r.get("coverage", "unavailable"),
        )
        for r in assessment["criteria"]
    ]
    return dict(
        assignment_id=record.id,
        work_episode_id=work["work_episode_id"],
        artifact=dict(
            logical_artifact_id=assessment["logical_artifact_id"],
            artifact_version=assessment["artifact_version"],
            scope_locator=assessment["scope_locator"],
        ),
        requirements=selected,
        inventory_complete=assessment["inventory_complete"],
        responsibility=dict(
            assignment_ref=role["assignment_ref"],
            revision=role["revision"],
            responsible_actor=role["responsible_actor"],
            recipient_ids=sorted(role["recipient_ids"]),
            identity_basis=role["identity_basis"],
            source_ref=role["source_ref"],
            member_ids=sorted(m["member_id"] for m in role["members"]),
        ),
        action=action,
        input_versions=inputs_for(record, action),
        process_step=[link["process_id"], link["step_id"]] if link else None,
        conditions=sorted(relevant, key=lambda b: b["blocker_id"]),
        process_input_version=context.get("condition_version")
        if action["requires_process_context"]
        else None,
        governing_conditions=[
            states["transfer"],
            states["requested_action"],
            states["downstream_execution"] if action["requires_process_context"] else "ready",
        ],
    )


def identity_supported(role):
    members = {row["member_id"]: row["label"] for row in role["members"]}
    actors = {role["responsible_actor"], *role["recipient_ids"]}
    if (
        role["identity_basis"] not in {"explicit_declaration", "source_assignment"}
        or not role["recipient_ids"]
        or not actors <= members.keys()
    ):
        return False
    if role["identity_basis"] == "source_assignment":
        import re

        quote = (role.get("evidence") or {}).get("quote", "")

        # A name match only checks the supplied assignment passage. It cannot
        # resolve a roster, grant access, or identify the authenticated recorder.
        def mentioned(actor):
            # Short IDs are ambiguous in prose (articles, grades, initials).
            # Require a qualified mention or a distinct, unambiguous label.
            label = members[actor].strip()
            terms = [f"member {actor}"]
            if len(actor) > 2:
                terms.append(actor)
            if (
                len(label) > 2
                and sum(m.strip().casefold() == label.casefold() for m in members.values()) == 1
            ):
                terms.append(label)
            return any(
                re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", quote, re.I) for term in terms
            )

        return all(mentioned(actor) for actor in actors)
    return True


def next_state(packet, acks):
    action = packet["action"]
    role = packet["responsibility"]
    members = {m["member_id"] for m in role["members"]}
    if (
        not identity_supported(role)
        or role["responsible_actor"] not in members
        or not role["recipient_ids"]
        or not set(role["recipient_ids"]) <= members
        or action["owner_id"] not in members
    ):
        return "needs_identity"
    if not packet.get("current_basis", True):
        return "requires_rebase"
    states = condition_states(packet["process_context"], action, packet["process_link"])
    gates = {states["transfer"], states["requested_action"]}
    if action["requires_process_context"]:
        gates.add(states["downstream_execution"])
    prereqs = {
        r["requirement_id"]: r["assessment_status"] for r in packet["assessment"]["criteria"]
    }
    evidence = {prereqs.get(k, "unknown") for k in action["prerequisite_ids"]}
    if "blocked" in gates:
        return "blocked"
    if "conflict" in evidence:
        return "conflict"
    if "needs_work" in evidence:
        return "needs_work"
    if any(v["availability_state"] != "available" for v in packet.get("input_versions", [])):
        return "unknown"
    if not packet["assessment"]["document_id"] or "unknown" in evidence | gates:
        return "unknown"
    if "conditional" in gates:
        return "conditional"
    if action["acknowledgment_policy"] != "optional":
        selected = action["acknowledgment_members"] or role["recipient_ids"]
        matches = [acks.get(m) == action["required_response"] for m in selected]
        if not (any(matches) if action["acknowledgment_policy"] == "any" else all(matches)):
            return "waiting_ack"
    return "ready"
