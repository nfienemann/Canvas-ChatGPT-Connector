"""Criterion-local impact proofs and targeted assembly of the next readiness generation."""

import re

from canvas_bridge.processes import readiness as rd
from canvas_bridge.processes.change_observation import bindings, sections
from canvas_bridge.processes.state import failure


def governing_sections(text):
    grouped = {}
    for label, body in sections(text).items():
        if not label:
            continue
        ident = label.split()[0]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\d", ident):
            grouped.setdefault(ident, []).append((label, body))
    return grouped


def scoped_amendment(before, after):
    """Recognize explicitly limited amendments, while retaining other governing context."""
    old, new = sections(before), sections(after)
    if not old or not new:
        return False
    old_preamble = set(old[""].splitlines())
    new_lines = [s for s in new[""].splitlines() if s and s not in old_preamble]
    # Additional prose or instructions outside a recognized scope require a fresh review.
    metadata = r"Brief version [\w-]+ applies to the [\w -]+\."
    declaration = r"This complete (?:synthetic )?(?:instructor )?amendment (?:replaces only [\w-]+ from [\w-]+|changes only [\w-]+'s maximum from \d+ to \d+ seconds|retains [\w-]+ through [\w-]+ and adds [\w-]+|removes [\w-]+ from the required criterion set)\."
    retained = r"[\w, -]+ (?:retain|maintain) their (?:existing )?criterion identity and wording\."
    if not any(re.fullmatch(declaration, s) for s in new_lines):
        return False
    if not all(
        any(re.fullmatch(p, s) for p in (metadata, declaration, retained)) for s in new_lines
    ):
        return False
    return all(
        not s or s in new[""].splitlines() or re.fullmatch(metadata, s)
        for s in old[""].splitlines()
    )


def reference_proof(row, before, after):
    """Narrow proofs for a structured reference packet. Unrecognized prose needs review."""
    old, new = sections(before), sections(after)
    if not old or not new or old.get("") != new.get(""):
        return False
    added = new.keys() - old.keys()
    modified = {k for k in old.keys() & new.keys() if old[k].strip() != new[k].strip()}
    if old.keys() - new.keys():
        return False
    if not modified and len(added) == 1:
        heading = next(iter(added))
        return bool(
            heading.casefold().endswith("administrative contact")
            and re.fullmatch(
                r"The [\w -]+ contact label is [\w -]+\.\s+This contact label supplies administrative metadata for the reference packet\.",
                new[heading].strip(),
            )
        )
    if row["coverage_rule"] != "all_claims" or "source version" not in row["criterion"].lower():
        return False
    amendment = "Field-specific source amendment"
    if amendment not in modified or len(added) != 1:
        return False
    # Versioned records describe data. An inserted instruction, qualification or
    # changed historical sample cannot inherit a citation-resolution assessment.
    added_id = next(iter(added))
    lines = [line for line in new[added_id].splitlines() if line.strip()]
    patterns = [
        r"Record status is current\.",
        r"(?:Synthetic )?issue date is [\d-]+\.",
        r"The study recorded \d+ [\w ]+ in \d+ [\w ]+\.",
        r"The reported [\w ]+ is [\d.]+%, calculated as [\d /\u00d7.]+\.",
    ]
    if len(lines) != len(patterns) or not all(
        re.fullmatch(p, t, re.I) for p, t in zip(patterns, lines, strict=True)
    ):
        return False
    changed_block = new[amendment].strip().splitlines()
    if len(changed_block) != 3 or not (
        re.fullmatch(
            re.escape(added_id) + r" supersedes [\w-]+ only for the [\w-]+ field\.",
            changed_block[0],
        )
        and re.fullmatch(
            r"The archived [\w ,]+ sample values and source identities remain available for historical attribution\.",
            changed_block[1],
        )
        and re.fullmatch(
            r"[\w-]+ explicitly applies this source amendment to [\w-]+\.", changed_block[2]
        )
        and not changed_block[2].endswith(" " + row["requirement_id"] + ".")
    ):
        return False
    return all(
        old[h].replace("Record status is current.", "Record status is archived.").strip()
        == new[h].strip()
        for h in modified - {amendment}
    )


def assess_impacts(record, new_bindings, changes, old_entries, new_entries, partial):
    previous = {b.logical_id: b for b in bindings(record.data)}
    selected = {b.logical_id: b for b in new_bindings}
    impacts = []
    for row in record.data["requirements"]:
        ident = row["requirement_id"]
        deps = rd.dependencies(row, previous.values())
        statuses = []
        proofs = []
        for d in changes:
            name = d["logical_id"]
            if name not in deps:
                continue
            kind = d["change_class"]
            if name in partial:
                parts = {
                    a["part"] for a in [row["governing"], *row["evidence"]] if a["source"] == name
                }
                if (
                    (
                        d.get("proof_kind") == "all_native_parts"
                        and row["coverage_rule"] == "recorded_run"
                    )
                    or row["coverage_rule"] in {"absence", "all_claims"}
                    or not parts.issubset(partial[name])
                ):
                    statuses.append("unknown")
                    continue
            if kind in {"alias_only", "content_equivalent"}:
                proofs.append(d["proof_id"])
                continue
            if kind in {"incomparable", "unavailable"}:
                statuses.append(
                    "affected"
                    if row["coverage_rule"] == "recorded_run" and d["role"] == "artifact"
                    else "unknown"
                )
                continue
            if (
                d["role"] == "brief"
                and name in previous
                and name in selected
                and d["comparison_coverage"] == "complete"
            ):
                left, right = (
                    e[b.document_id]["text"]
                    for b, e in ((previous[name], old_entries), (selected[name], new_entries))
                )
                a, b = governing_sections(left), governing_sections(right)
                other_changes = [
                    h
                    for h in d["changed_sections"]
                    if h and h.split()[0] not in a.keys() | b.keys()
                ]
                if (
                    not other_changes
                    and scoped_amendment(left, right)
                    and ident in a
                    and a[ident] == b.get(ident)
                ):
                    proofs.append(d["proof_id"])
                    continue
            if (
                d["role"] == "reference"
                and d["comparison_coverage"] == "complete"
                and name in previous
                and name in selected
            ):
                left = old_entries[previous[name].document_id]
                right = new_entries[selected[name].document_id]
                if reference_proof(row, left["text"], right["text"]):
                    proofs.append(d["proof_id"])
                    continue
            statuses.append("affected")
        impact = "unknown" if "unknown" in statuses else "affected" if statuses else "unaffected"
        impacts.append(
            dict(
                requirement_id=ident,
                impact_status=impact,
                dependency_ids=sorted(deps),
                proof_ids=proofs,
            )
        )
    known = {r["requirement_id"] for r in record.data["requirements"]}
    for b in new_bindings:
        if b.role != "brief" or not b.document_id:
            continue
        for ident in sorted(governing_sections(new_entries[b.document_id]["text"]).keys() - known):
            impacts.append(
                dict(
                    requirement_id=ident,
                    impact_status="affected",
                    correspondence="new_criterion",
                    dependency_ids=[b.logical_id],
                    proof_ids=[],
                )
            )
            known.add(ident)
    return impacts


def prior_input(row):
    return rd.Criterion.model_validate(
        {k: v for k, v in row.items() if k in rd.Criterion.model_fields}
    )


def pending_row(old, reason):
    row = prior_input(old)
    return row.model_copy(
        update=dict(
            assessment_status="unknown",
            rationale="Current evidence requires targeted review.",
            followup=reason,
            evidence=(),
            reviewed_extent=(),
            coverage="unavailable",
            measured_artifact_hash=None,
            candidate_assessments=(),
            action=None,
            completion_condition=None,
            gap_kind=None,
        )
    )


def targeted_rows(record, stage, request, entries, by_key):
    previous = {r["requirement_id"]: r for r in record.data["requirements"]}
    updates = {r.requirement_id: r for r in request.assessments}
    removed = {r.requirement_id: r for r in request.removals}
    if (
        len(updates) != len(request.assessments)
        or len(removed) != len(request.removals)
        or updates.keys() & removed.keys()
        or removed.keys() - previous.keys()
    ):
        failure("READINESS_DUPLICATE_REQUIREMENT")
    for ident, item in removed.items():
        if (
            not request.inventory_complete
            or by_key.get(item.authority.source) is None
            or by_key[item.authority.source].role != "brief"
        ):
            failure("READINESS_REQUIREMENT_SOURCE_REQUIRED")
        source = by_key[item.authority.source]
        if (
            item.authority.source in stage["partial_parts"]
            or not source.document_id
            or not entries[source.document_id]["coverage"].complete
        ):
            failure("READINESS_EXTENT_INVALID")
        rd.check_anchor(item.authority, by_key, entries)
        if (
            not re.search(
                r"\b(?:remove[sd]?|retire[sd]?|withdraw[n]?|no longer required|not applicable)\b",
                item.authority.quote,
                re.I,
            )
            or ident not in item.authority.quote
        ):
            failure("READINESS_REQUIREMENT_SOURCE_REQUIRED")
    rows = []
    origins = {}
    impacts = {r["requirement_id"]: r["impact_status"] for r in stage["impacts"]}
    additions = {
        r["requirement_id"]: r
        for r in stage["impacts"]
        if r.get("correspondence") == "new_criterion"
    }
    for ident in sorted(previous.keys() | updates.keys() | additions.keys()):
        if ident in removed:
            continue
        if ident in updates:
            row = updates[ident]
            for extent in row.reviewed_extent:
                allowed = stage["partial_parts"].get(extent.source)
                if allowed is not None and set(extent.parts) - set(allowed):
                    failure("READINESS_EXTENT_INVALID")
            for a in [
                row.governing,
                *row.evidence,
                *(a for c in row.candidate_assessments for a in c.evidence),
            ]:
                allowed = stage["partial_parts"].get(a.source)
                if allowed is not None and a.part not in allowed:
                    failure("READINESS_EXTENT_INVALID")
            origins[ident] = "reassessed"
        elif ident in additions:
            name = additions[ident]["dependency_ids"][0]
            section = governing_sections(entries[by_key[name].document_id]["text"])[ident]
            quote = next(
                (line.strip()[:1200] for line in section.splitlines() if line.strip()), None
            )
            if not quote:
                failure("READINESS_REQUIREMENT_SOURCE_REQUIRED")
            row = rd.Criterion(
                requirement_id=ident,
                criterion=quote,
                governing=rd.Anchor(source=name, part=1, quote=quote),
                applicability="unknown",
                applicability_basis="New governing section awaits scope review.",
                rationale="No current assessment has been supplied.",
                followup="review_new_criterion",
            )
            origins[ident] = "pending"
        elif impacts[ident] == "unaffected":
            row = prior_input(previous[ident])
            origins[ident] = "carried_forward"
        else:
            row = pending_row(previous[ident], "review_changed_source")
            origins[ident] = "pending"
        rows.append(row)
    return rows, origins
