"""Conservative cross-provider matching. Links retain all original identities."""

from pydantic import Field

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import AcademicScope, Model, Ref, SourceTag


class ExternalEntityKey(Model):
    provider: Ref
    external_id: Ref
    scope: AcademicScope
    kind: str = Field(pattern=r"^(course|assignment|document)$")
    course_code: str | None = Field(default=None, max_length=100)
    section: str | None = Field(default=None, max_length=100)
    instructor: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sources: tuple[SourceTag, ...] = Field(min_length=1, max_length=100)


def match_entities(left, right):
    boundaries = ("principal", "institution", "term")
    if left.kind != right.kind or any(
        getattr(left.scope, k) != getattr(right.scope, k) for k in boundaries
    ):
        return {
            "status": "distinct",
            "reasons": ["IDENTITY_SCOPE_MISMATCH"],
            "merge_allowed": False,
        }
    signals, collisions = [], []
    for key in ("course_code", "section", "instructor", "start_date", "content_hash"):
        a, b = getattr(left, key), getattr(right, key)
        if a is not None and b is not None:
            (signals if a == b else collisions).append(key)
    if left.provider == right.provider and left.external_id != right.external_id:
        collisions.append("provider_identity")
    if left.kind != "course" and left.scope.course != right.scope.course:
        collisions.append("course_link_required")
    strong = len(signals) >= 3 and "course_code" in signals
    status = "collision" if collisions else "strong_candidate" if strong else "review_required"
    return {
        "status": status,
        "signals": signals,
        "collisions": collisions,
        "merge_allowed": not collisions,
        "confirmation_required": True,
        "proposal_id": fingerprint([left.model_dump(mode="json"), right.model_dump(mode="json")]),
        "originals_preserved": True,
        "permission_union": False,
    }


def canonical_link(left, right, *, confirmed):
    from canvas_bridge.domain import DomainError

    decision = match_entities(left, right)
    if not confirmed or not decision["merge_allowed"]:
        raise DomainError(
            "needs_input",
            "Review the identity signals and confirm a nonconflicting link.",
            reason_code="PROCESS_IDENTITY_REVIEW_REQUIRED",
        )
    return {
        "canonical_id": decision["proposal_id"],
        "aliases": [left.model_dump(mode="json"), right.model_dump(mode="json")],
        "permission_mode": "authorize_each_origin",
        "reversible": True,
    }


def scoped_association(left, right):
    """Distinct adapter namespaces stay on the aliases throughout the review."""
    from canvas_bridge.domain import DomainError

    tags = [k.sources[0] for k in (left, right)]
    if (
        len(left.sources) != 1
        or len(right.sources) != 1
        or {s.origin for s in tags} != {"local_document", "institutional"}
        or any(k.scope != s.scope for k, s in zip((left, right), tags, strict=True))
        or left.scope.principal != right.scope.principal
        or left.scope.term != right.scope.term
        or left.scope.term == "unspecified"
        or left.kind != right.kind
        or not left.course_code
        or left.course_code != right.course_code
        or any(
            a and b and a != b
            for a, b in (
                (left.section, right.section),
                (left.scope.section, right.scope.section),
                (left.instructor, right.instructor),
                (left.start_date, right.start_date),
                (left.content_hash, right.content_hash),
            )
        )
    ):
        raise DomainError(
            "needs_input",
            "Review the two original course scopes and identity signals.",
            reason_code="PROCESS_IDENTITY_REVIEW_REQUIRED",
        )
    pairs = sorted((entity_key(k) for k in (left, right)), key=repr)
    return {
        "canonical_id": fingerprint(["reviewed-scope-association", pairs]),
        "aliases": [k.model_dump(mode="json") for k in (left, right)],
        "permission_mode": "authorize_each_origin",
        "reversible": True,
    }


def entity_key(entity):
    return (
        entity.scope.principal,
        entity.scope.institution,
        entity.scope.term,
        entity.scope.course,
        entity.scope.section,
        entity.sources[0].connection,
        entity.sources[0].id if entity.sources[0].origin == "local_document" else None,
        entity.provider,
        entity.kind,
        entity.external_id,
    )


def unlink(canonical):
    return tuple(ExternalEntityKey.model_validate(item) for item in canonical["aliases"])


def canonical_inventory(entities, confirmed_links):
    """Project explicitly linked aliases once; never infer assignment equivalence.

    Callers must authorize each original before supplying it here. Original
    records remain intact, so deleting a link reverses the projection.
    """
    if len(entities) > 500 or len(confirmed_links) > 500:
        raise ValueError("Identity inventory budget exceeded.")
    aliases = {}
    for link in confirmed_links:
        for entity in unlink(link):
            key = entity_key(entity)
            if key in aliases and aliases[key] != link["canonical_id"]:
                raise ValueError("An alias belongs to conflicting canonical links.")
            aliases[key] = link["canonical_id"]
    groups = {}
    for entity in entities:
        key = entity_key(entity)
        canonical = aliases.get(key, fingerprint(key))
        groups.setdefault(canonical, []).append(entity)
    return [
        {
            "canonical_id": key,
            "aliases": [e.model_dump(mode="json") for e in values],
            "permission_mode": "authorize_each_origin",
        }
        for key, values in sorted(groups.items())
    ]


def assignment_projection(bridge, owner, aliases, entries, calendar):
    """One reviewed parent retains both dated assertions and the LMS event marker."""
    from canvas_bridge.academic.independent_models import IndependentAcademicInput
    from canvas_bridge.academic.study_steps import step_parents
    from canvas_bridge.calendar_sync import calendar_proposal
    from canvas_bridge.domain import WorkItem

    local = next(a for a in aliases if a.sources[0].origin == "local_document")
    institutional = next(a for a in aliases if a.sources[0].origin == "institutional")
    row = bridge.independent.require(owner, local.sources[0].id)
    dataset = IndependentAcademicInput.model_validate(row.content["reviewed_dataset"])
    declared = next(w for w in dataset.work if w.key == local.external_id)
    work = WorkItem.model_validate(entries[institutional.sources[0].id]["work"])
    claims = [
        {
            "source_id": a.sources[0].id,
            "content_hash": a.sources[0].version,
            "locator": a.sources[0].locator,
            "basis": basis,
            "value": value.model_dump(mode="json"),
        }
        for a, basis, value in (
            (local, "user_declared", declared.due),
            (institutional, "observed", work.effective_due),
        )
    ]
    contested = declared.due.kind in {"local_date", "timestamp", "known_none"} and (
        declared.due.kind,
        declared.due.timestamp,
        declared.due.local_date,
    ) != (work.effective_due.kind, work.effective_due.timestamp, work.effective_due.local_date)
    data = {
        "assignment_id": work.id,
        "deadline_assertions": claims,
        "status": "contested" if contested else "reviewed",
        "child_work_ids": sorted(
            k for k, parent in step_parents(dataset).items() if parent == declared.key
        ),
    }
    if calendar:
        proposals = calendar_proposal(
            [] if contested else [work],
            calendar,
            owner,
            institutional.sources[0].connection,
            bridge.retention.clock(),
        )
        data["calendar_projection"] = {
            "status": "contested" if contested else proposals["status"],
            "proposal_count": len(proposals["proposals"]),
            "external_writes": False,
        }
    return {"reviewed_parent": data}
