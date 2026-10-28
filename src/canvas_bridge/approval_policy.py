"""External approval evidence is independent of credentials and user permissions.

Only signed administrator records are accepted. The service has no signing key,
approval mutation endpoint, MCP argument, or automatic approval discovery.
"""

import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, Field, ValidationError, model_validator

from canvas_bridge.domain import DomainError, Model, opaque_id, utcnow
from canvas_bridge.egress_models import EgressGovernance

Authority = Literal["provider", "institution", "sharing"]
Category = Literal[
    "identity",
    "courses",
    "assignments",
    "submissions",
    "grades",
    "syllabus",
    "files",
    "modules",
    "pages",
    "quizzes",
    "discussions",
    "calendar",
    "announcements",
]
CATEGORIES = frozenset(Category.__args__)
SAFE_MESSAGE = (
    "Live Canvas access or sharing is disabled because the required authorization "
    "could not be established. An authorized administrator must review approvals. "
    "Offline and synthetic academic tools remain available."
)
logger = logging.getLogger("canvas_bridge.approval_policy")


class ApprovalState(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Conditions(Model):
    # Empty allowlist means all resources within the other explicitly listed scopes.
    resource_allowlist: frozenset[str] = frozenset()
    resource_denylist: frozenset[str] = frozenset()
    local_processing_only: bool = False
    # Conditions outside the implemented vocabulary cannot be silently ignored.
    unimplemented: list[str] = Field(default_factory=list, max_length=100)


class ApprovalRecord(Model):
    record_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    authority: Authority
    provider: Literal["instructure_canvas"] = "instructure_canvas"
    approving_organization: str = Field(min_length=1, max_length=200)
    approving_authority: str = Field(min_length=1, max_length=200)
    written_authorization_reference: str = Field(min_length=1, max_length=1000)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: ApprovalState = ApprovalState.NOT_ASSESSED
    verification_status: Literal["unverified", "verified", "failed"] = "unverified"
    verified_by: str = Field(min_length=1, max_length=200)
    verified_at: AwareDatetime
    institutions: frozenset[str] = Field(min_length=1)
    # MCP must be explicit even though this implementation retrieves via REST.
    mechanisms: frozenset[Literal["rest_api", "mcp"]] = Field(min_length=1)
    deployment_modes: frozenset[Literal["personal", "hosted"]] = Field(min_length=1)
    activities: frozenset[Literal["retrieve", "share", "link", "refresh"]] = Field(min_length=1)
    data_categories: frozenset[Category] = Field(min_length=1)
    recipients: frozenset[Literal["local", "chatgpt", "user_download"]] = Field(min_length=1)
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    conditions: Conditions = Field(default_factory=Conditions)
    # A broad sharing grant alone never classifies content or approves an AI environment.
    egress: EgressGovernance | None = None

    @model_validator(mode="after")
    def bounded(self):
        if self.expires_at <= self.effective_at or "*" in self.institutions:
            raise ValueError("Approvals require bounded dates and explicit institutions.")
        return self


class TrustedAdministrator(Model):
    key_id: str = Field(min_length=1, max_length=100)
    public_key: str
    organization: str = Field(min_length=1, max_length=200)
    authorities: frozenset[Authority] = Field(min_length=1)
    institutions: frozenset[str] = Field(min_length=1)


class TrustStore(Model):
    administrators: list[TrustedAdministrator] = Field(max_length=100)


class SignedRecord(Model):
    key_id: str
    record: dict
    signature: str


class ApprovalBundle(Model):
    schema_version: Literal[1] = 1
    records: list[SignedRecord] = Field(max_length=1000)


class SealedEvidence(Model):
    algorithm: Literal["AES-256-GCM"] = "AES-256-GCM"
    nonce: str
    ciphertext: str

    @model_validator(mode="after")
    def encrypted_envelope(self):
        if len(base64.b64decode(self.nonce, validate=True)) != 12:
            raise ValueError("Invalid evidence nonce")
        if len(base64.b64decode(self.ciphertext, validate=True)) < 16:
            raise ValueError("Invalid encrypted evidence")
        return self


def canonical_bytes(record: dict) -> bytes:
    """Sign the original JSON object, not a reserialized Pydantic set."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def read_bounded(path: Path, maximum=2_000_000) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Oversized policy file")
    return data


class ApprovalStore:
    def __init__(self, settings):
        self.settings = settings

    def load(self):
        """Reload on every decision: no positive cache surviving revocation."""
        s = self.settings
        if not s.approval_records_file or not s.approval_trust_file or not s.approval_evidence_root:
            return [], "APPROVAL_NOT_ASSESSED"
        try:
            trust = TrustStore.model_validate_json(read_bounded(s.approval_trust_file))
            bundle = ApprovalBundle.model_validate_json(read_bounded(s.approval_records_file))
            keys = {a.key_id: a for a in trust.administrators}
            if len(keys) != len(trust.administrators):
                raise ValueError("Duplicate administrator")
            records, ids, boundaries = [], set(), set()
            for signed in bundle.records:
                admin = keys[signed.key_id]
                key = Ed25519PublicKey.from_public_bytes(
                    base64.b64decode(admin.public_key, validate=True)
                )
                key.verify(
                    base64.b64decode(signed.signature, validate=True),
                    canonical_bytes(signed.record),
                )
                record = ApprovalRecord.model_validate(signed.record)
                record_boundaries = {
                    (record.authority, institution) for institution in record.institutions
                }
                if (
                    record.record_id in ids
                    or boundaries & record_boundaries
                    or record.authority not in admin.authorities
                    or record.approving_organization != admin.organization
                    or not record.institutions <= admin.institutions
                ):
                    raise ValueError("Untrusted approval authority")
                # Evidence is an encrypted envelope stored outside the repository.
                # Never open it here, fetch a reference URL, or return it to MCP.
                evidence = read_bounded(
                    s.approval_evidence_root / (record.evidence_sha256 + ".sealed"), 16_000_000
                )
                if hashlib.sha256(evidence).hexdigest() != record.evidence_sha256:
                    raise ValueError("Evidence mismatch")
                SealedEvidence.model_validate_json(evidence)
                ids.add(record.record_id)
                boundaries.update(record_boundaries)
                records.append(record)
            return records, None
        except (OSError, ValueError, KeyError, TypeError, ValidationError, InvalidSignature):
            return [], "APPROVAL_RECORDS_INVALID"


@dataclass(frozen=True)
class PolicyRequest:
    institution: str
    deployment: str
    categories: frozenset[str]
    recipient: str = "local"
    activity: str = "retrieve"
    mechanisms: frozenset[str] = frozenset({"rest_api", "mcp"})
    resource: str | None = None


@dataclass
class PolicyDecision:
    allowed: bool
    reason_code: str
    authority: str
    state: str
    decision_id: str = field(default_factory=opaque_id)

    def public(self):
        # Deliberately excludes organizations, references, evidence, and key identities.
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "authority": self.authority,
            "state": self.state,
            "decision_id": self.decision_id,
        }

    def require(self):
        if not self.allowed:
            raise DomainError(
                "permission_denied",
                SAFE_MESSAGE,
                reason_code=self.reason_code,
                details={"authorization_policy": self.public()},
            )
        return self


class ApprovalGateway:
    def __init__(self, settings):
        self.store = ApprovalStore(settings)

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        decision = self._evaluate(request)
        from canvas_bridge.authorization import request_authorization

        context = request_authorization.get()
        logger.info(
            "integration_policy %s",
            json.dumps(
                {
                    **decision.public(),
                    "request_id": context.request_id if context else decision.decision_id,
                    "tool_name": context.tool_name if context else "internal_policy_check",
                    "provider": "instructure_canvas",
                    "institution_reference": hashlib.sha256(
                        request.institution.encode()
                    ).hexdigest()[:24],
                    "deployment": request.deployment,
                    "categories": sorted(request.categories & CATEGORIES),
                    "recipient": request.recipient,
                    "activity": request.activity,
                    "timestamp": utcnow().isoformat(),
                },
                sort_keys=True,
            ),
        )
        return decision

    def _evaluate(
        self, request: PolicyRequest, *, authorities=("provider", "institution", "sharing")
    ) -> PolicyDecision:
        records, failure = self.store.load()
        if failure:
            return self._decision(False, failure, "provider", "NOT_ASSESSED")
        if not request.categories or not request.categories <= CATEGORIES:
            return self._decision(False, "APPROVAL_SCOPE_MISMATCH", "provider", "RESTRICTED")
        now = utcnow()
        restricted = False
        for authority in authorities:
            candidates = [
                r
                for r in records
                if r.authority == authority and request.institution in r.institutions
            ]
            # Negative records are vetoes for the institution, including a revoked grant
            # that another overlapping positive record might otherwise mask.
            for r in candidates:
                if r.state in {ApprovalState.DENIED, ApprovalState.REVOKED, ApprovalState.EXPIRED}:
                    return self._decision(False, "APPROVAL_" + r.state, authority, r.state)
            matches = [
                r
                for r in candidates
                if (
                    request.deployment in r.deployment_modes
                    and request.mechanisms <= r.mechanisms
                    and request.categories <= r.data_categories
                    and request.recipient in r.recipients
                    and request.activity in r.activities
                )
            ]
            if not matches:
                return self._decision(
                    False,
                    "APPROVAL_SCOPE_MISMATCH" if candidates else "APPROVAL_NOT_ASSESSED",
                    authority,
                    "RESTRICTED" if candidates else "NOT_ASSESSED",
                )
            # All matching conditions apply; overlapping approvals cannot bypass a limit.
            for r in matches:
                state = r.state
                restricted = restricted or state == ApprovalState.RESTRICTED
                code = None
                if r.verification_status != "verified" or r.verified_at > now:
                    code, state = "APPROVAL_UNVERIFIED", ApprovalState.NOT_ASSESSED
                elif state not in {ApprovalState.APPROVED, ApprovalState.RESTRICTED}:
                    code = state if state == ApprovalState.APPROVAL_PENDING else "APPROVAL_" + state
                elif r.expires_at <= now:
                    code, state = "APPROVAL_EXPIRED", ApprovalState.EXPIRED
                elif r.effective_at > now:
                    code, state = "APPROVAL_NOT_EFFECTIVE", ApprovalState.APPROVAL_PENDING
                elif (
                    r.conditions.unimplemented
                    or (r.conditions.local_processing_only and request.recipient != "local")
                    or (
                        r.conditions.resource_allowlist
                        and request.resource not in r.conditions.resource_allowlist
                    )
                    or (
                        r.conditions.resource_denylist
                        and (
                            request.resource is None
                            or request.resource in r.conditions.resource_denylist
                        )
                    )
                ):
                    code, state = "APPROVAL_CONTENT_RESTRICTED", ApprovalState.RESTRICTED
                if code:
                    return self._decision(False, code, authority, state)
        return self._decision(
            True, "APPROVAL_AUTHORIZED", "all", "RESTRICTED" if restricted else "APPROVED"
        )

    @staticmethod
    def _decision(allowed, code, authority, state):
        return PolicyDecision(allowed, code, authority, state)


def resource_categories(resource):
    return frozenset({"courses" if resource == "course" else resource})
