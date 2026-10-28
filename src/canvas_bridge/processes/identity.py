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
            key = (
                entity.scope.principal,
                entity.scope.institution,
                entity.scope.term,
                entity.provider,
                entity.kind,
                entity.external_id,
            )
            if key in aliases and aliases[key] != link["canonical_id"]:
                raise ValueError("An alias belongs to conflicting canonical links.")
            aliases[key] = link["canonical_id"]
    groups = {}
    for entity in entities:
        key = (
            entity.scope.principal,
            entity.scope.institution,
            entity.scope.term,
            entity.provider,
            entity.kind,
            entity.external_id,
        )
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
