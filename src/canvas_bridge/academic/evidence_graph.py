"""Bounded, transport-free academic evidence. Metadata never grants access.

Trusted adapters supply observations after authorization; this module only reasons
over them. Source text is data. No timestamp or assertion can install a policy.
"""

from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from canvas_bridge.academic.models import PermissionContext, Restrictions, SourceReference
from canvas_bridge.evidence import fingerprint

SCHEMA = "academic-evidence-1"


class EntityKind(StrEnum):
    COURSE = "course"
    ASSESSMENT = "assessment"
    ASSIGNMENT = "assignment"
    DEADLINE = "deadline"
    GRADE_RULE = "grade_rule"
    GRADING_CATEGORY = "grading_category"
    LEARNING_OBJECTIVE = "learning_objective"
    LECTURE = "lecture"
    DOCUMENT = "document"
    DOCUMENT_PASSAGE = "document_passage"
    FIGURE = "figure"
    CALENDAR_EVENT = "calendar_event"
    STUDY_OBLIGATION = "study_obligation"
    SOURCE_ASSERTION = "source_assertion"


class RelationKind(StrEnum):
    BELONGS_TO = "BELONGS_TO"
    DESCRIBES = "DESCRIBES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    DEPENDS_ON = "DEPENDS_ON"
    ASSESSES = "ASSESSES"
    SCHEDULED_FOR = "SCHEDULED_FOR"
    DERIVED_FROM = "DERIVED_FROM"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(Model):
    principal: str = Field(min_length=1, max_length=100)
    institution: str = Field(min_length=1, max_length=100)
    connection: str = Field(min_length=1, max_length=100)
    course_id: str = Field(min_length=1, max_length=100)


class Observation(Model):
    id: str
    source: SourceReference
    source_type: str | None = None
    course_id: str
    observed_at: AwareDatetime
    verified_at: AwareDatetime | None = None
    fresh_until: AwareDatetime | None = None
    permission: PermissionContext
    restrictions: Restrictions
    complete: bool = False
    uncertainty: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent(self):
        if self.verified_at and self.verified_at > self.observed_at:
            raise ValueError("Verification cannot postdate observation.")
        if self.fresh_until and self.fresh_until <= self.observed_at:
            raise ValueError("Invalid source freshness interval.")
        return self

    def identity(self):
        # Locator distinguishes passages; observation time is not a new source version.
        return fingerprint([self.source.model_dump(mode="json"), self.source_type, self.course_id])


class Entity(Model):
    id: str
    kind: EntityKind
    reference: str = Field(min_length=1, max_length=300)


class Assertion(Model):
    id: str
    subject: str
    predicate: str = Field(min_length=1, max_length=100)
    value: JsonValue
    basis: Literal["explicit", "calculated", "inferred", "user_provided"]
    sources: tuple[str, ...] = Field(default=(), max_length=500)
    parents: tuple[str, ...] = Field(default=(), max_length=1000)
    uncertainty: tuple[str, ...] = ()


class Relationship(Model):
    kind: RelationKind
    left: str
    right: str
    evidence: tuple[str, ...] = Field(min_length=1, max_length=1000)
    status: Literal["supported", "candidate"] = "supported"


class PrecedenceRule(Model):
    """Trusted application configuration, never populated from document prose."""

    scope: Scope
    predicate: str
    source_types: tuple[str, ...] = Field(min_length=2, max_length=20)
    evidence_assertion: str
    policy_reference: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.source_types)) != len(self.source_types):
            raise ValueError("Precedence source types must be unique.")
        return self


class EvidenceGraph(Model):
    schema_version: Literal["academic-evidence-1"] = SCHEMA
    scope: Scope
    observations: tuple[Observation, ...] = Field(default=(), max_length=1000)
    entities: tuple[Entity, ...] = Field(default=(), max_length=1000)
    assertions: tuple[Assertion, ...] = Field(default=(), max_length=2000)
    relationships: tuple[Relationship, ...] = Field(default=(), max_length=4000)
    complete: bool = False
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def connected(self):
        if len(self.model_dump_json().encode()) > 2_000_000:
            raise ValueError("Evidence graph exceeds its 2 MB budget.")
        sources = {s.id: s for s in self.observations}
        entities = {e.id for e in self.entities}
        assertions = {a.id: a for a in self.assertions}
        if len(sources) != len(self.observations) or len(entities) != len(self.entities):
            raise ValueError("Duplicate source or entity identifiers.")
        if len(assertions) != len(self.assertions) or entities & assertions.keys():
            raise ValueError("Duplicate assertion identifiers.")
        versions = defaultdict(set)
        for s in self.observations:
            p = s.permission
            if (p.principal, p.tenant, p.connection, s.course_id) != (
                self.scope.principal,
                self.scope.institution,
                self.scope.connection,
                self.scope.course_id,
            ):
                raise ValueError(
                    "Evidence crosses the principal, institution, connection or course boundary."
                )
            if s.id != s.identity():
                raise ValueError("Observation identifier does not bind its source.")
            if s.source.version not in {"not-returned", "not-recorded"}:
                versions[(s.source.provider, s.source.id)].add(s.source.version)
        if any(len(v) > 1 for v in versions.values()):
            raise ValueError("A snapshot cannot mix versions of the same source.")
        seen, lineage, lineage_size = set(), {}, 0
        for e in self.entities:
            if e.id != "entity-" + fingerprint([self.scope.model_dump(), str(e.kind), e.reference]):
                raise ValueError("Entity identifier is outside the graph scope.")
        for a in self.assertions:
            if a.id != "assertion-" + fingerprint(a.model_dump(mode="json", exclude={"id"})):
                raise ValueError("Assertion identifier does not bind its content.")
            if a.subject not in entities or not set(a.sources) <= sources.keys():
                raise ValueError("Unknown subject or source.")
            if not set(a.parents) <= seen:
                raise ValueError("Derived facts require preceding parents; cycles are forbidden.")
            if not a.sources and not a.parents:
                raise ValueError(
                    "An assertion needs actual evidence; unsourced facts are forbidden."
                )
            if a.basis in {"calculated", "inferred"} and not a.parents:
                raise ValueError("Calculated and inferred facts need explicit dependencies.")
            lineage[a.id] = set(a.sources).union(*(lineage[p] for p in a.parents))
            lineage_size += len(lineage[a.id])
            if lineage_size > 10_000:
                raise ValueError("Evidence graph exceeds its expanded provenance budget.")
            seen.add(a.id)
        refs = entities | assertions.keys()
        for r in self.relationships:
            if (
                r.left not in refs
                or r.right not in refs
                or not set(r.evidence) <= assertions.keys()
            ):
                raise ValueError("Relationship lacks scoped endpoints or evidence.")
            if (
                r.kind
                in {
                    RelationKind.SUPPORTS,
                    RelationKind.CONTRADICTS,
                    RelationKind.SUPERSEDES,
                    RelationKind.DERIVED_FROM,
                }
                and not {r.left, r.right} <= assertions.keys()
            ):
                raise ValueError("Evidence comparison relationships require assertion endpoints.")
        return self

    def lineage(self, assertion_id):
        assertions = {a.id: a for a in self.assertions}
        if assertion_id not in assertions:
            raise ValueError("Unknown assertion.")
        pending, visited, sources = [assertion_id], set(), set()
        while pending:
            ref = pending.pop()
            if ref in visited:
                continue
            visited.add(ref)
            a = assertions[ref]
            sources.update(a.sources)
            pending.extend(a.parents)
        return tuple(s for s in self.observations if s.id in sources)

    def disclosure(self, assertion_id):
        sources = self.lineage(assertion_id)
        # Classifications accumulate; allowed purposes/recipients only narrow.
        return {
            "classifications": sorted(
                {str(c) for s in sources for c in s.restrictions.classifications}
            ),
            "purposes": sorted(
                set.intersection(
                    *(set(s.restrictions.purposes) & set(s.permission.scope) for s in sources)
                )
            ),
            "recipients": sorted(
                set.intersection(*(set(s.restrictions.recipients) for s in sources))
            ),
            "source_restrictions": [s.restrictions.model_dump(mode="json") for s in sources],
            "expires_at": min(s.permission.expires_at for s in sources).isoformat(),
        }

    def query(self, subject, predicate, *, policy=None):
        candidates = [
            a for a in self.assertions if a.subject == subject and a.predicate == predicate
        ]
        ids = {a.id for a in candidates}
        conflicts = [
            r
            for r in self.relationships
            if r.kind == RelationKind.CONTRADICTS and {r.left, r.right} <= ids
        ]
        supersedes = [
            r
            for r in self.relationships
            if r.kind == RelationKind.SUPERSEDES and {r.left, r.right} <= ids
        ]
        uncertainty = [u for a in candidates for u in a.uncertainty]
        if not self.complete or any(not s.complete for a in candidates for s in self.lineage(a.id)):
            uncertainty.append("Source coverage is incomplete.")
        selected, status = None, "missing_information"
        if candidates:
            status = "unresolved_conflict" if conflicts else "supported_at_available_precision"
            if not conflicts and len({fingerprint(a.value) for a in candidates}) == 1:
                selected = candidates[0].id
            elif not conflicts:
                status = "comparison_indeterminate"
        if policy:
            if policy.scope != self.scope or policy.predicate != predicate:
                raise ValueError("Precedence policy is outside this query scope.")
            witness = next((a for a in self.assertions if a.id == policy.evidence_assertion), None)
            if (
                witness is None
                or witness.basis != "explicit"
                or not all(s.complete and s.verified_at for s in self.lineage(witness.id))
            ):
                raise ValueError("Precedence requires a verified explicit policy assertion.")
            ranked = []
            for a in candidates:
                types = {s.source_type for s in self.lineage(a.id)}
                if len(types) == 1 and next(iter(types)) in policy.source_types:
                    ranked.append((policy.source_types.index(next(iter(types))), a))
            if ranked:
                best = min(rank for rank, _ in ranked)
                winners = [a for rank, a in ranked if rank == best]
                if len({fingerprint(a.value) for a in winners}) == 1:
                    selected, status = winners[0].id, "selected_by_verified_policy"
                else:
                    uncertainty.append("Highest-precedence sources disagree.")
        if supersedes and not policy:
            uncertainty.append(
                "Possible supersession is not authoritative without a verified policy."
            )
        if selected and any(a.basis == "inferred" for a in candidates if a.id == selected):
            selected, status = None, "inference_requires_review"
        if not candidates:
            uncertainty.append("No sourced assertion was observed; absence is not a fact.")
        if predicate == "deadline" and not any(
            isinstance(a.value, dict) and a.value.get("kind") in {"timestamp", "local_date"}
            for a in candidates
        ):
            selected, status = None, "missing_information"
        uncertainty.extend(u for a in candidates for s in self.lineage(a.id) for u in s.uncertainty)
        return {
            "status": status,
            "authority": "configured_policy"
            if status == "selected_by_verified_policy"
            else "not_established",
            "selected_assertion": selected,
            "candidates": [self.assertion_view(a) for a in candidates],
            "conflicts": [r.model_dump(mode="json") for r in conflicts],
            "supersession_candidates": [r.model_dump(mode="json") for r in supersedes],
            "policy_reference": policy.policy_reference if policy else None,
            "policy_evidence": self.assertion_view(witness) if policy else None,
            "uncertainty": list(dict.fromkeys(uncertainty)),
        }

    def assertion_view(self, assertion):
        return {
            **assertion.model_dump(mode="json"),
            "provenance": [
                {
                    "source": s.source.model_dump(mode="json"),
                    "source_type": s.source_type,
                    "institution": self.scope.institution,
                    "course_id": self.scope.course_id,
                    "observed_at": s.observed_at.isoformat(),
                    "verified_at": s.verified_at.isoformat() if s.verified_at else None,
                    "complete": s.complete,
                    "uncertainty": list(s.uncertainty),
                    "decision_reference": s.permission.decision_reference,
                }
                for s in self.lineage(assertion.id)
            ],
            "disclosure": self.disclosure(assertion.id),
        }

    def view(self):
        """A presentation projection, NOT an authorization or release operation."""
        return {
            "schema_version": SCHEMA,
            "course_id": self.scope.course_id,
            "entities": [e.model_dump(mode="json") for e in self.entities],
            "assertions": [self.assertion_view(a) for a in self.assertions],
            "relationships": [r.model_dump(mode="json") for r in self.relationships],
            "complete": self.complete,
            "limitations": list(self.limitations),
            "history_status": "no_prior_snapshot_supplied",
        }

    def related(self, reference, kind):
        return [
            r.model_dump(mode="json")
            for r in self.relationships
            if r.kind == kind and reference in {r.left, r.right}
        ]

    def uncertain_rules(self):
        kinds = {
            e.id
            for e in self.entities
            if e.kind in {EntityKind.GRADE_RULE, EntityKind.GRADING_CATEGORY}
        }
        keys = {(a.subject, a.predicate) for a in self.assertions if a.subject in kinds}
        queries = [self.query(subject, predicate) for subject, predicate in sorted(keys)]
        return [
            q
            for q in queries
            if q["uncertainty"] or q["conflicts"] or q["selected_assertion"] is None
        ]

    def conflicting_documents(self):
        return [
            {
                "relationship": r.model_dump(mode="json"),
                "left_sources": [s.source.model_dump(mode="json") for s in self.lineage(r.left)],
                "right_sources": [s.source.model_dump(mode="json") for s in self.lineage(r.right)],
            }
            for r in self.relationships
            if r.kind == RelationKind.CONTRADICTS
        ]


class Builder:
    """Request-local builder. Never accept a builder or policy from MCP arguments."""

    def __init__(self, scope, *, complete=False, limitations=()):
        self.scope, self.complete, self.limitations = scope, complete, tuple(limitations)
        self.observations, self.entities, self.assertions, self.relationships = {}, {}, {}, []

    def observe(self, **fields):
        source = Observation(id="pending", **fields)
        source = source.model_copy(update={"id": source.identity()})
        existing = self.observations.get(source.id)
        if existing is not None and existing != source:
            raise ValueError("Repeated source observation changed permission or metadata.")
        self.observations[source.id] = source
        return source.id

    def entity(self, kind, reference):
        ref = "entity-" + fingerprint([self.scope.model_dump(), str(kind), reference])
        self.entities[ref] = Entity(id=ref, kind=kind, reference=reference)
        return ref

    def assert_fact(
        self, subject, predicate, value, *, sources=(), parents=(), basis="explicit", uncertainty=()
    ):
        fields = dict(
            subject=subject,
            predicate=predicate,
            value=value,
            basis=basis,
            sources=tuple(dict.fromkeys(sources)),
            parents=tuple(dict.fromkeys(parents)),
            uncertainty=tuple(uncertainty),
        )
        ref = "assertion-" + fingerprint(fields)
        self.assertions[ref] = Assertion(id=ref, **fields)
        for parent in parents:
            self.link(RelationKind.DERIVED_FROM, ref, parent, (parent,))
        return ref

    def link(self, kind, left, right, evidence, *, status="supported"):
        relation = Relationship(
            kind=kind, left=left, right=right, evidence=tuple(evidence), status=status
        )
        if relation not in self.relationships:
            self.relationships.append(relation)

    def build(self):
        return EvidenceGraph(
            scope=self.scope,
            observations=tuple(self.observations.values()),
            entities=tuple(self.entities.values()),
            assertions=tuple(self.assertions.values()),
            relationships=tuple(self.relationships),
            complete=self.complete,
            limitations=self.limitations,
        )


def changes(previous, current):
    """Compare authorized snapshots. Missing collection items are not deletions."""
    if previous is None:
        return {
            "history_status": "no_prior_snapshot_supplied",
            "source_changes": [],
            "invalidated_assertions": [],
            "fact_changes": [],
        }
    if previous.scope != current.scope:
        raise ValueError("Cannot compare evidence across security scopes.")

    def versions(graph):
        result = {}
        for s in graph.observations:
            key = (s.source.provider, s.source.id)
            if key not in result or s.source.version not in {"not-returned", "not-recorded"}:
                result[key] = s.source.version
        return result

    old, new = versions(previous), versions(current)
    changed = {key for key in old if new.get(key) != old[key]}

    # Versionless data and changed disclosure/coverage cannot validate old derivatives.
    def source_state(graph, key):
        return sorted(
            fingerprint(
                {
                    "reference": s.source.model_dump(mode="json"),
                    "complete": s.complete,
                    "restrictions": {
                        **s.restrictions.model_dump(mode="json"),
                        "classifications": sorted(str(c) for c in s.restrictions.classifications),
                        "purposes": sorted(s.restrictions.purposes),
                        "recipients": sorted(s.restrictions.recipients),
                    },
                    "scope": sorted(s.permission.scope),
                }
            )
            for s in graph.observations
            if (s.source.provider, s.source.id) == key
        )

    changed.update(
        key
        for key in old
        if old[key] in {"not-returned", "not-recorded"}
        or source_state(previous, key) != source_state(current, key)
    )
    current_ids = {a.id for a in current.assertions}
    invalid = [
        a.id
        for a in previous.assertions
        if a.id not in current_ids
        or any((s.source.provider, s.source.id) in changed for s in previous.lineage(a.id))
    ]

    def facts(graph):
        grouped = defaultdict(list)
        for a in graph.assertions:
            grouped[(a.subject, a.predicate)].append(a)
        return grouped

    previous_facts, current_facts = facts(previous), facts(current)
    fact_changes = []
    for subject, predicate in sorted(previous_facts.keys() | current_facts.keys()):
        before = previous_facts[(subject, predicate)]
        after = current_facts[(subject, predicate)]
        if sorted(fingerprint(a.value) for a in before) != sorted(
            fingerprint(a.value) for a in after
        ):
            fact_changes.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "change_kind": "newly_observed"
                    if not before
                    else "not_observed"
                    if not after
                    else "value_changed",
                    "previous_assertions": [previous.assertion_view(a) for a in before],
                    "current_assertions": [current.assertion_view(a) for a in after],
                }
            )
    return {
        "history_status": "compared_authorized_observations",
        "baseline_verified": bool(previous.observations)
        and all(s.verified_at is not None for s in previous.observations),
        "source_changes": [
            {
                "provider": key[0],
                "source_id": key[1],
                "previous_version": old.get(key),
                "current_version": new.get(key),
                "change_kind": "newly_observed"
                if key not in old
                else "not_observed"
                if key not in new
                else "version_changed"
                if old.get(key) != new.get(key)
                else "evidence_or_restrictions_changed",
            }
            for key in sorted(old.keys() | new.keys())
            if old.get(key) != new.get(key) or key in changed
        ],
        "invalidated_assertions": invalid,
        "fact_changes": fact_changes,
        "recalculation_required": any(
            a.id in invalid and a.basis == "calculated" for a in previous.assertions
        ),
    }


class EvidenceSession:
    """Two in-memory snapshots, no automatic durable grade history.

    `authorize` is a trusted application callback rechecking original source access
    for the exact purpose/recipient, including historical versions. It must raise
    on denial. Never construct this from document/model-supplied callbacks.
    """

    def __init__(self, scope, *, authorize, purpose, recipient, clock):
        self.scope, self.authorize = scope, authorize
        self.purpose, self.recipient, self.clock = purpose, recipient, clock
        self._current, self._previous = None, None

    def _check(self, graph):
        from canvas_bridge.egress_models import ContentClassification as CC

        if graph.scope != self.scope:
            raise ValueError("Evidence session scope mismatch.")
        now: datetime = self.clock()
        for source in graph.observations:
            if (
                source.observed_at > now
                or source.permission.expires_at <= now
                or (source.fresh_until and source.fresh_until <= now)
            ):
                raise PermissionError("Evidence is expired or not yet observed.")
            if (
                self.purpose not in source.permission.scope
                or self.purpose not in source.restrictions.purposes
                or self.recipient not in source.restrictions.recipients
            ):
                raise PermissionError("Evidence is not authorized for this use.")
            if source.restrictions.classifications & {
                CC.UNKNOWN_OR_UNCLASSIFIED,
                CC.THIRD_PARTY_EDUCATIONAL_RECORD,
                CC.RESTRICTED_ASSESSMENT,
                CC.CONFIDENTIAL_RESEARCH,
            }:
                raise PermissionError("Restricted or unclassified evidence is withheld.")
        self.authorize(graph)

    def update(self, graph):
        # Reparse so constructed/copied Pydantic objects cannot bypass invariants.
        graph = EvidenceGraph.model_validate_json(graph.model_dump_json())
        self._check(graph)
        if self._current:
            self._check(self._current)
        delta = changes(self._current, graph)
        self._check(graph)
        self._previous, self._current = self._current, graph
        return delta

    def query(self, subject, predicate, *, policy=None):
        if self._current is None:
            raise ValueError("No evidence has been observed.")
        self._check(self._current)
        result = self._current.query(subject, predicate, policy=policy)
        self._check(self._current)
        return result

    def history(self):
        if self._current is None:
            return changes(None, None)
        self._check(self._current)
        if self._previous:
            self._check(self._previous)
        result = changes(self._previous, self._current)
        self._check(self._current)
        if self._previous:
            self._check(self._previous)
        return result

    def clear(self):
        self._previous = self._current = None
