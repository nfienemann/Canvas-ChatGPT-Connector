"""Stage, apply and compensate a version-bound transition through the owned process journal."""

from typing import Annotated, Literal

from pydantic import Field

from canvas_bridge.domain import Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import readiness as rd
from canvas_bridge.processes.change_impact import assess_impacts, targeted_rows
from canvas_bridge.processes.change_observation import bindings, compare, source_entries
from canvas_bridge.processes.change_work import reconcile
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.state import failure


class ChangeRequest(Model):
    record_id: Ref
    expected_revision: int = Field(ge=1)
    idempotency_key: Ref


class Observation(ChangeRequest):
    selection_mode: Literal["explicit", "refresh"] = "explicit"
    target: tuple[rd.Binding, ...] = Field(min_length=1, max_length=6)
    advertised_hashes: dict[rd.Key, rd.Digest] = Field(default_factory=dict, max_length=6)
    source_parents: dict[rd.Key, rd.Digest] = Field(default_factory=dict, max_length=6)
    partial_parts: dict[rd.Key, list[Annotated[int, Field(ge=1, le=200)]]] = Field(
        default_factory=dict, max_length=6
    )


class Removal(Model):
    requirement_id: rd.Key
    authority: rd.Anchor


class Reassessment(ChangeRequest):
    change_id: Ref
    assessments: tuple[rd.Criterion, ...] = Field(default=(), max_length=40)
    removals: tuple[Removal, ...] = Field(default=(), max_length=40)
    inventory_complete: bool
    material_changes: tuple[rd.Key, ...] = Field(default=(), max_length=40)


class Compensation(ChangeRequest):
    applied_revision: int = Field(ge=1)


def commit(service, owner, request, build, effect_id=None, replaced_tags=()):
    return service.repository.save_readiness(
        owner,
        request.record_id,
        request.expected_revision,
        request.idempotency_key,
        fingerprint([type(request).__name__, request.model_dump(mode="json")]),
        build,
        replaced_tags=replaced_tags,
        effect_id=effect_id
        or fingerprint(
            [type(request).__name__, request.model_dump(mode="json", exclude={"idempotency_key"})]
        ),
    )


def base_for(service, owner, request):
    service.enabled()
    return rd.snapshot(service.repository, owner, request.record_id, request.expected_revision)


def replaced_sources(record, target):
    """Exact old versions lost to an in-place replacement; never read their cached text."""
    new = {b.logical_id: b for b in target}
    return {
        b.logical_id
        for b in bindings(record.data)
        if b.document_id
        and b.logical_id in new
        and new[b.logical_id].document_id == b.document_id
        and new[b.logical_id].content_hash != b.content_hash
    }


def replacement_tags(record, target, entries):
    changed = replaced_sources(record, target)
    ids = {b.document_id: b.content_hash for b in bindings(record.data) if b.logical_id in changed}
    return {
        t.key: entries[t.id]["tag"]
        for t in record.sources
        if t.id in ids and t.version == ids[t.id]
    }


async def observe(service, owner, request):
    previous = base_for(service, owner, request)
    old = bindings(previous.data)
    replaced = replaced_sources(previous, request.target)
    accessible = [b for b in old if b.logical_id not in replaced]
    await rd.authorize_bindings(service.bridge, owner, accessible)
    await rd.authorize_bindings(service.bridge, owner, request.target)
    prior = {b.logical_id: b for b in old}
    by_key = {b.logical_id: b for b in request.target}
    if prior.keys() - by_key.keys():
        failure(
            "READINESS_SELECTION_INVALID",
            "Keep a logical binding for explicitly unavailable replacements.",
        )
    old_entries = (
        source_entries(service, owner, previous, accessible)
        if any(b.document_id for b in accessible)
        else {}
    )
    new_entries = source_entries(service, owner, previous, request.target)
    for key, parts in request.partial_parts.items():
        if (
            key not in by_key
            or not by_key[key].document_id
            or not set(parts) <= new_entries[by_key[key].document_id]["coverage"].seen
        ):
            failure("READINESS_EXTENT_INVALID")
    comparisons = [
        dict(
            logical_id=b.logical_id,
            role=b.role,
            before_hash=prior[b.logical_id].content_hash,
            after_hash=b.content_hash,
            comparison_coverage="unavailable",
            changed_sections=[],
            change_class="incomparable",
            reason="prior_version_unavailable",
        )
        if b.logical_id in replaced
        else compare(service, owner, prior.get(b.logical_id), b)
        for b in request.target
    ]
    if (
        request.source_parents.keys() - by_key.keys()
        or request.advertised_hashes.keys() - by_key.keys()
    ):
        failure("READINESS_SELECTION_INVALID")
    for c in comparisons:
        logical = c["logical_id"]
        if logical in request.advertised_hashes:
            if c["after_hash"] and c["after_hash"] != request.advertised_hashes[logical]:
                failure("READINESS_VERSION_MISMATCH")
            c["advertised_hash"] = request.advertised_hashes[logical]
        if logical in request.source_parents:
            c["parent_hash"] = request.source_parents[logical]
            if c["parent_hash"] != c["before_hash"] and c["comparison_coverage"] != "complete":
                c.update(change_class="incomparable", comparison_coverage="partial")
        if (
            c["logical_id"] in request.partial_parts
            and c.get("parent_hash")
            and c["parent_hash"] != c["before_hash"]
        ):
            c["change_class"] = "incomparable"
        if c["logical_id"] in request.partial_parts:
            c["comparison_coverage"] = "partial"
    if request.selection_mode == "refresh":
        for comparison in comparisons:
            if (
                comparison.get("parent_hash")
                and comparison["parent_hash"] != comparison["before_hash"]
            ):
                comparison.update(change_class="incomparable", comparison_coverage="partial")
    impacts = assess_impacts(
        previous, request.target, comparisons, old_entries, new_entries, request.partial_parts
    )
    for comparison in comparisons:
        name = comparison["logical_id"]
        if comparison.get("proof_kind") != "nonblank_lines":
            continue
        old_lines = old_entries[prior[name].document_id]["text"].splitlines()
        new_lines = new_entries[by_key[name].document_id]["text"].splitlines()
        remaps = []
        for row in previous.data["requirements"]:
            for anchor in (row["governing"], *row["evidence"]):
                if anchor["source"] != name:
                    continue
                old_at = [i for i, line in enumerate(old_lines, 1) if anchor["quote"] in line]
                new_at = [i for i, line in enumerate(new_lines, 1) if anchor["quote"] in line]
                if len(old_at) == len(new_at) == 1 and old_at != new_at:
                    remaps.append(
                        dict(
                            requirement_id=row["requirement_id"],
                            before_line=old_at[0],
                            after_line=new_at[0],
                        )
                    )
        comparison["locator_remaps"] = remaps
    target = [b.model_dump(mode="json") for b in request.target]
    change_id = fingerprint(
        [
            previous.id,
            previous.data["assessment_revision"],
            sorted((b.logical_id, b.role, b.content_hash) for b in request.target),
            request.partial_parts,
            request.advertised_hashes,
            request.source_parents,
            request.selection_mode,
        ]
    )

    current = rd.snapshot(service.repository, owner, request.record_id)
    historical_parent = False
    if request.selection_mode == "refresh":
        logical_history = current.data.get("binding_history", {})
        historical_parent = any(
            c.get("parent_hash")
            and c["parent_hash"] != c["before_hash"]
            and c["after_hash"] in logical_history.get(c["logical_id"], [])
            for c in comparisons
        )
    if (
        historical_parent
        or current.revision != request.expected_revision
        and current.data.get("change_report", {}).get("change_id") != change_id
        and current.data.get("pending_change", {}).get("change_id") != change_id
    ):
        receipt = service.repository.observe_historical(
            owner,
            request.record_id,
            request.expected_revision,
            request.idempotency_key,
            fingerprint([type(request).__name__, request.model_dump(mode="json")]),
            change_id,
        )
        return Result(
            summary="Historical observation recorded against its original base.", data=receipt
        )

    def build(before, now):
        stage = dict(
            change_id=change_id,
            processing_state="pending",
            base_revision=previous.revision,
            target=target,
            comparisons=comparisons,
            impacts=impacts,
            partial_parts=request.partial_parts,
            observed_at=now.isoformat(),
            selection_mode=request.selection_mode,
        )
        sources = {t.key: t for t in previous.sources if t.id in {b.document_id for b in old}}
        sources.update({e["tag"].key: e["tag"] for e in new_entries.values()})
        return before.model_copy(
            update=dict(
                revision=before.revision + 1,
                updated_at=now,
                sources=tuple(sources.values()),
                data=before.data | {"pending_change": stage},
            )
        )

    receipt = commit(
        service,
        owner,
        request,
        build,
        replaced_tags=replacement_tags(previous, request.target, new_entries),
        effect_id=fingerprint(["observe", previous.id, request.expected_revision, change_id]),
    )
    return Result(summary="Change observation saved.", data=receipt | dict(change_id=change_id))


async def apply_change(service, owner, request):
    previous = base_for(service, owner, request)
    stage = previous.data.get("pending_change")
    if not stage or stage["change_id"] != request.change_id:
        failure("PROCESS_REVISION_MISMATCH")
    if any(
        c.get("parent_hash")
        and c["parent_hash"] != c["before_hash"]
        and c["comparison_coverage"] != "complete"
        for c in stage["comparisons"]
    ):
        failure("CHANGE_PARENT_UNRESOLVED")
    target = tuple(rd.Binding.model_validate(b) for b in stage["target"])
    replaced = replaced_sources(previous, target)
    await rd.authorize_bindings(
        service.bridge, owner, [b for b in bindings(previous.data) if b.logical_id not in replaced]
    )
    await rd.authorize_bindings(service.bridge, owner, target)
    entries = source_entries(service, owner, previous, target)
    rows, origins = targeted_rows(
        previous, stage, request, entries, {b.logical_id: b for b in target}
    )
    for index, row in enumerate(rows):
        # The old measurement remains historical when a selected replacement has no verified bytes.
        if row.coverage_rule == "recorded_run" and any(
            c["role"] == "artifact" and not c["after_hash"] for c in stage["comparisons"]
        ):
            rows[index] = row.model_copy(
                update=dict(
                    assessment_status="unknown",
                    coverage="unavailable",
                    followup="review_changed_source",
                    gap_kind=None,
                    action=None,
                    completion_condition=None,
                )
            )
    if set(request.material_changes) - {r.requirement_id for r in request.assessments}:
        failure("READINESS_SELECTION_INVALID")
    review = rd.Review(
        assignment_id=previous.data["assignment_id"],
        course=previous.scope.course,
        term=previous.scope.term,
        expected_revision=request.expected_revision,
        idempotency_key=request.idempotency_key,
        review_scope=previous.data["review_scope"],
        membership_complete=request.inventory_complete,
        bindings=target,
        requirements=rows,
        requested_work=[
            r["requirement_id"]
            for r in previous.data["requirements"]
            if r.get("work_item", {}).get("work_basis") == "explicit_user_request"
            and r["requirement_id"] in origins
            and origins[r["requirement_id"]] == "carried_forward"
        ],
    )
    # Newly enumerated governing criteria cannot silently inherit an old complete inventory.
    from canvas_bridge.processes.change_impact import governing_sections

    recognized = set().union(
        *(
            governing_sections(entries[b.document_id]["text"]).keys()
            for b in target
            if b.role == "brief" and b.document_id
        )
    )
    if recognized - {r.requirement_id for r in rows}:
        review = review.model_copy(update={"membership_complete": False})
    equivalences = {}
    for c in stage["comparisons"]:
        if c["role"] != "artifact" or c["comparison_coverage"] != "complete":
            continue
        if c.get("proof_kind") == "all_native_parts":
            equivalences[(c["before_hash"], c["after_hash"])] = c["proof_id"]
        if c.get("proof_kind") == "all_native_parts" or c["change_class"] == "alias_only":
            for saved_row in previous.data["requirements"]:
                proof = saved_row.get("measurement_equivalence")
                if proof and proof["selected_hash"] == c["before_hash"]:
                    equivalences[(saved_row["measured_artifact_hash"], c["after_hash"])] = (
                        fingerprint([proof, c["proof_id"]])
                    )
    key, prepare = rd.prepare_review(service, owner, review, equivalent_payloads=equivalences)
    if key != previous.id:
        failure("PROCESS_SCOPE_MISMATCH")
    old = {r["requirement_id"]: r for r in previous.data["requirements"]}

    # The new generation may outlive access to its predecessor. Never copy old-only
    # heading text into a report released under the target sources' permissions.
    permitted_comparisons = []
    for c in stage["comparisons"]:
        b = next(b for b in target if b.logical_id == c["logical_id"])
        text = entries[b.document_id]["text"] if b.document_id else ""
        permitted_comparisons.append(
            c
            | {
                "changed_sections": [
                    h if h in text else fingerprint(h) for h in c["changed_sections"]
                ]
            }
        )

    def build(before, now):
        record = prepare(before, now)
        data = record.data
        for row in data["requirements"]:
            ident = row["requirement_id"]
            alias_only = all(c["change_class"] == "alias_only" for c in stage["comparisons"])
            row["assessment_origin"] = (
                "unchanged"
                if alias_only and origins[ident] == "carried_forward"
                else origins[ident]
            )
            if origins[ident] == "pending" and old.get(ident, {}).get("measured_artifact_hash"):
                row["historical_measurement_hash"] = old[ident]["measured_artifact_hash"]
            if origins[ident] == "carried_forward":
                row["original_assessor_basis"] = old[ident].get(
                    "original_assessor_basis", old[ident]["basis"]
                )
                row["carry_forward_validated_at"] = now.isoformat()
                row["original_assessed_at"] = old[ident].get(
                    "original_assessed_at", before.data["assessed_at"]
                )
                row["original_assessment_revision"] = old[ident].get(
                    "original_assessment_revision", before.data["assessment_revision"]
                )
                evidence = next(i for i in stage["impacts"] if i["requirement_id"] == ident)
                row["carry_forward_proof"] = fingerprint(evidence)
            for (measured, selected), proof in equivalences.items():
                if row.get("measured_artifact_hash") == measured:
                    row["measurement_equivalence"] = dict(
                        measured_hash=measured, selected_hash=selected, proof_id=proof
                    )
        material = set(request.material_changes)
        for comparison in stage["comparisons"]:
            if comparison["role"] == "brief":
                for label in comparison["changed_sections"]:
                    parts = label.split()
                    if (
                        parts
                        and parts[0] in old
                        and parts[0] in origins
                        and origins[parts[0]] == "reassessed"
                    ):
                        rid = parts[0]
                        updated = next(
                            r for r in data["requirements"] if r["requirement_id"] == rid
                        )
                        if updated["governing"]["quote"] != old[rid]["governing"]["quote"]:
                            material.add(rid)
        history, progress, actions, fields = reconcile(before, record, stage, material)
        lineage = dict(before.data.get("binding_history", {}))
        for c in stage["comparisons"]:
            seq = list(lineage.get(c["logical_id"], []))
            for version in (c["before_hash"], c["after_hash"]):
                if version and (not seq or seq[-1] != version):
                    seq.append(version)
            lineage[c["logical_id"]] = seq[-32:]
        if (
            all(c["change_class"] == "alias_only" for c in stage["comparisons"])
            and not request.assessments
            and not request.removals
        ):
            data.update(
                assessment_revision=before.data["assessment_revision"],
                assessed_at=before.data["assessed_at"],
            )
        data.update(
            work_history=history,
            binding_history=lineage,
            personal_fields=fields,
            progress=progress,
            change_report=dict(
                change_id=stage["change_id"],
                base_revision=stage["base_revision"],
                applied_revision=record.revision,
                processing_state="applied",
                impacts=stage["impacts"]
                + [
                    dict(
                        requirement_id=k, impact_status="affected", dependency_ids=[], proof_ids=[]
                    )
                    for k in sorted(
                        origins.keys() - {i["requirement_id"] for i in stage["impacts"]}
                    )
                ],
                comparisons=permitted_comparisons,
                work_actions=actions,
                removed_requirement_ids=[r.requirement_id for r in request.removals],
            ),
        )
        return record

    return Result(
        summary="Reconciled readiness generation committed.",
        data=commit(
            service,
            owner,
            request,
            build,
            replaced_tags=replacement_tags(previous, target, entries),
        ),
    )


async def report(service, owner, record_id):
    service.enabled()
    record = rd.snapshot(service.repository, owner, record_id)
    stage = record.data.get("pending_change")
    saved = stage or record.data.get("change_report")
    if not saved:
        failure("PROCESS_RECORD_UNAVAILABLE")
    selected = [rd.Binding.model_validate(b) for b in stage["target"]] if stage else []
    lost = replaced_sources(record, selected)
    await rd.authorize_bindings(
        service.bridge, owner, [b for b in bindings(record.data) if b.logical_id not in lost]
    )
    if stage:
        await rd.authorize_bindings(
            service.bridge, owner, [rd.Binding.model_validate(b) for b in stage["target"]]
        )
    from collections import Counter

    saved = dict(saved)
    impacts = saved.get("impacts", [])
    actions = saved.get("work_actions", [])
    saved["impact_counts"] = dict(Counter(i["impact_status"] for i in impacts))
    saved["action_counts"] = dict(Counter(a["work_action"] for a in actions))
    data = dict(record_id=record.id, revision=record.revision, change_report=saved)
    data["attempts"] = service.repository.observation_attempts(owner, record.id)
    if stage:
        statuses = {
            r["requirement_id"]: r["assessment_status"] for r in record.data["requirements"]
        }
        pending = [
            r
            | {
                "assessment_status": statuses[r["requirement_id"]]
                if r["impact_status"] == "unaffected"
                else "unknown"
            }
            for r in stage["impacts"]
        ]
        data["current_selection"] = pending
        stored = {r["requirement_id"]: r for r in record.data["requirements"]}
        inventory_known = record.data["membership_complete"] and not any(
            c["role"] == "brief" and c["change_class"] not in {"alias_only", "content_equivalent"}
            for c in stage["comparisons"]
        )
        data["pending_projection"] = rd.summarize(
            [
                stored.get(p["requirement_id"], {"required": True, "applicability": "unknown"})
                | {"assessment_status": p["assessment_status"]}
                for p in pending
            ],
            inventory_known,
        )

    return Result(
        summary="Saved change and work reconciliation.",
        data=data,
        sources=service.citations(
            owner,
            [
                t
                for t in record.sources
                if not any(
                    b.logical_id in lost and b.document_id == t.id and b.content_hash == t.version
                    for b in bindings(record.data)
                )
            ],
        ),
    )


async def compensate(service, owner, request):
    current = base_for(service, owner, request)
    applied = rd.snapshot(service.repository, owner, current.id, request.applied_revision)
    change = applied.data.get("change_report", {})
    if (
        current.data.get("pending_change")
        or change.get("applied_revision") != applied.revision
        or current.data.get("change_report", {}).get("applied_revision") != request.applied_revision
        or current.data.get("assessment_revision") != applied.data["assessment_revision"]
        or change.get("processing_state") != "applied"
    ):
        failure("PROCESS_REVISION_MISMATCH")
    prior = rd.snapshot(service.repository, owner, current.id, change["base_revision"])
    await rd.authorize_bindings(service.bridge, owner, bindings(current.data))
    await rd.authorize_bindings(service.bridge, owner, bindings(prior.data))

    def build(before, now):
        restored = dict(prior.data["progress"])
        actions = {
            a["current_occurrence_id"]: a
            for a in change["work_actions"]
            if a["current_occurrence_id"]
        }
        for key, state in before.data["progress"].items():
            if state == applied.data["progress"].get(key):
                continue
            action = actions.get(key)
            if not action or action["work_action"] not in {"keep", "update"}:
                failure(
                    "PROCESS_REVISION_MISMATCH",
                    "Later progress applies to a changed episode; review before compensating.",
                )
            restored[action["prior_occurrence_id"]] = state
        personal = dict(prior.data.get("personal_fields", {}))
        for key, values in before.data.get("personal_fields", {}).items():
            if values == applied.data.get("personal_fields", {}).get(key, {}):
                continue
            action = actions.get(key)
            if not action or action["work_action"] not in {"keep", "update"}:
                failure("PROCESS_REVISION_MISMATCH")
            personal[action["prior_occurrence_id"]] = values
        data = prior.data | dict(
            progress=restored,
            personal_fields=personal,
            change_report=dict(
                change_id=change["change_id"],
                processing_state="compensated",
                compensated_revision=applied.revision,
                base_revision=prior.revision,
                applied_revision=before.revision + 1,
            ),
        )
        return prior.model_copy(
            update=dict(data=data, revision=before.revision + 1, updated_at=now)
        )

    return Result(
        summary="Scoped reconciliation compensation committed.",
        data=commit(service, owner, request, build),
    )
