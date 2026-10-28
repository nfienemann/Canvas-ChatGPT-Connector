"""Provider-neutral internal contracts, populated by authorized adapters.

These are not client authorization claims. Transport requests accept references
and user declarations; the service resolves authority and provenance itself.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

Ref = Annotated[str, Field(min_length=1, max_length=200)]
ChangeReason = Literal[
    "create", "correction", "supersession", "rollback", "delete", "revocation", "merge", "unmerge"
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AcademicScope(Model):
    principal: Ref
    institution: Ref
    term: Ref
    course: Ref
    section: Ref | None = None
    subject: Ref | None = None


class SourceTag(Model):
    id: Ref
    version: Ref
    origin: Literal["local_document", "institutional", "user_declaration", "synthetic"]
    scope: AcademicScope
    connection: Ref | None = None
    locator: str = Field(min_length=1, max_length=500)
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    sensitivity: Literal["personal", "course", "research", "public"] = "personal"
    retention: Literal["retain_while_authorized", "delete_on_revocation"] = "delete_on_revocation"

    @model_validator(mode="after")
    def valid(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("Source must have a positive validity interval.")
        if (self.origin == "institutional") != bool(self.connection):
            raise ValueError("Only institutional sources carry a connection.")
        return self

    @property
    def key(self):
        return f"{self.origin}:{self.connection or ''}:{self.id}@{self.version}"


class EvidenceCoverage(Model):
    source: SourceTag
    unit: Literal["page", "slide", "section", "record"]
    total: int | None = Field(default=None, ge=1, le=10000)
    seen: frozenset[int] = Field(default=frozenset(), max_length=10000)
    unreadable: frozenset[int] = Field(default=frozenset(), max_length=10000)
    extraction: Literal["complete", "partial", "unreadable", "not_checked"]

    @model_validator(mode="after")
    def valid(self):
        if self.seen & self.unreadable or any(i < 1 for i in self.seen | self.unreadable):
            raise ValueError("Coverage units must be positive and disjoint.")
        if self.total and any(i > self.total for i in self.seen | self.unreadable):
            raise ValueError("Coverage exceeds the source extent.")
        if self.extraction == "complete" and not self.complete:
            raise ValueError("Complete extraction must account for every unit.")
        return self

    @property
    def complete(self):
        return bool(self.total and len(self.seen) == self.total and not self.unreadable)


class EvidenceClaim(Model):
    id: Ref
    entity: Ref
    field: Ref
    value: JsonValue
    coverage: EvidenceCoverage
    basis: Literal["observed", "user_declared", "inferred"] = "user_declared"
    authority: Literal["unverified", "official", "instructor"] = "unverified"
    issuer: Ref | None = None
    effective_at: AwareDatetime | None = None
    supersedes: tuple[Ref, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def authority_boundary(self):
        if self.authority != "unverified" and (
            self.basis != "observed"
            or self.coverage.source.origin not in {"institutional", "synthetic"}
        ):
            raise ValueError(
                "User declarations and local imports cannot assert official authority."
            )
        return self


class UncertaintyAssessment(Model):
    status: Literal["sufficient", "provisional", "insufficient", "stale", "contested"]
    reasons: tuple[str, ...]
    missing: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    permission_established: Literal[False] = False


class ResolutionDecision(Model):
    status: Literal["resolved", "unresolved", "stale"]
    selected: Ref | None = None
    candidates: tuple[EvidenceClaim, ...]
    superseded: tuple[Ref, ...] = ()
    reasons: tuple[str, ...]
    clarification: str | None = None


class AcademicRecord(Model):
    id: Ref
    kind: Literal[
        "claim",
        "plan",
        "reminder",
        "projection",
        "portfolio",
        "assignment",
        "concept",
        "identity",
        "clarification",
        "annotation",
    ]
    scope: AcademicScope
    revision: int = Field(default=1, ge=1)
    data: dict[str, JsonValue]
    sources: tuple[SourceTag, ...] = Field(min_length=1, max_length=100)
    depends_on: tuple[Ref, ...] = Field(default=(), max_length=100)
    state: Literal["valid", "stale", "quarantined"] = "valid"
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def scope_boundary(self):
        if any(s.scope.principal != self.scope.principal for s in self.sources):
            raise ValueError("Cross-principal records are forbidden.")
        if len(set(self.depends_on)) != len(self.depends_on) or self.id in self.depends_on:
            raise ValueError("Invalid dependency identity.")
        return self


class StateRevision(Model):
    id: Ref
    actor: Ref
    reason: ChangeReason
    before: AcademicRecord | None
    after: AcademicRecord | None
    affected: tuple[Ref, ...]
    created_at: AwareDatetime
    impacts: tuple[dict[str, JsonValue], ...] = Field(default=(), max_length=500)


class ChangePreview(Model):
    id: Ref
    state_version: int
    actor: Ref
    reason: ChangeReason
    before: AcademicRecord | None
    after: AcademicRecord | None
    affected: tuple[Ref, ...]
    expires_at: AwareDatetime


class ProcessState(Model):
    schema_version: Literal["academic-processes-1"] = "academic-processes-1"
    version: int = Field(default=0, ge=0)
    records: dict[str, AcademicRecord] = Field(default_factory=dict, max_length=500)
    revisions: tuple[StateRevision, ...] = Field(default=(), max_length=500)
    # Persisted reverse index; values are recomputed and checked before use.
    dependents: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    receipts: dict[str, dict[str, JsonValue]] = Field(default_factory=dict, max_length=500)

    @model_validator(mode="after")
    def consistent(self):
        expected = {key: [] for key in self.records}
        for key, record in self.records.items():
            if key != record.id:
                raise ValueError("Record key mismatch.")
            for parent in record.depends_on:
                if parent not in expected:
                    raise ValueError("Missing dependency.")
                expected[parent].append(key)
        index = {k: tuple(sorted(v)) for k, v in expected.items()}
        if self.dependents != index:
            raise ValueError("Dependency index mismatch.")
        pending = set(self.records)
        while pending:
            ready = {k for k in pending if not (set(self.records[k].depends_on) & pending)}
            if not ready:
                raise ValueError("Dependency cycle.")
            pending -= ready
        return self
