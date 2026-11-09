"""Trusted content-governance vocabulary. Never populated from course instructions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.domain import Model


class ContentClassification(StrEnum):
    PUBLIC_OR_APPROVED = "PUBLIC_OR_APPROVED"
    FIRST_PARTY_EDUCATIONAL_RECORD = "FIRST_PARTY_EDUCATIONAL_RECORD"
    THIRD_PARTY_EDUCATIONAL_RECORD = "THIRD_PARTY_EDUCATIONAL_RECORD"
    INSTRUCTOR_OWNED_COURSE_CONTENT = "INSTRUCTOR_OWNED_COURSE_CONTENT"
    RESTRICTED_ASSESSMENT = "RESTRICTED_ASSESSMENT"
    CONFIDENTIAL_RESEARCH = "CONFIDENTIAL_RESEARCH"
    UNKNOWN_OR_UNCLASSIFIED = "UNKNOWN_OR_UNCLASSIFIED"
    OWNER_AUTHORIZED_PRIVATE_COURSE_CONTENT = "OWNER_AUTHORIZED_PRIVATE_COURSE_CONTENT"


class ReleaseDecision(StrEnum):
    ALLOW = "ALLOW"
    ALLOW_MINIMIZED = "ALLOW_MINIMIZED"
    ALLOW_REDACTED = "ALLOW_REDACTED"
    DENY = "DENY"
    REQUIRES_AUTHORIZED_REVIEW = "REQUIRES_AUTHORIZED_REVIEW"


Channel = Literal[
    "structured",
    "text",
    "visual",
    "original",
    "temporary_url",
    "metadata",
    "error",
    "external_processing",
]
Purpose = Literal[
    "schedule",
    "grade_planning",
    "study",
    "document_reading",
    "visual_analysis",
    "original_download",
    "metadata",
    "diagnostics",
    "preferences",
    "status",
]


class PrivateCourseContentGrant(Model):
    """Explicit owner-attested private sharing; not independent institutional certification."""

    course_ids: frozenset[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:-]{1,100}$")]] = Field(
        min_length=1, max_length=100
    )
    permission_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    channels: frozenset[Literal["structured", "text", "visual"]] = Field(min_length=1)
    max_output_bytes: int = Field(default=20_000_000, gt=0, le=20_000_000)


class PrivateCourseListing(Model):
    """Explicit private metadata consent; no assertion about recipient processing terms."""

    owner: str = Field(pattern=r"^[a-f0-9]{64}$")
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=200)
    allow_permission_diagnostics: bool = False
    allow_course_material_inventory: bool = False
    course_content: PrivateCourseContentGrant | None = None
    scope: Literal[
        "minimized_course_listing", "minimized_study_metadata", "reviewed_private_text"
    ] = "minimized_course_listing"


class RecipientPolicy(Model):
    policy_id: str = Field(min_length=1, max_length=100)
    recipient: Literal["chatgpt", "external_ai", "document_processor", "user_download"]
    # Exact operator-reviewed plan/workspace; no product-wide retention assumption.
    environment: str = Field(min_length=1, max_length=200)
    workspace: str = Field(min_length=1, max_length=200)
    plan: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=200)
    classifications: frozenset[ContentClassification] = Field(min_length=1)
    purposes: frozenset[Purpose] = Field(min_length=1)
    channels: frozenset[Channel] = Field(min_length=1)
    retention_days: int = Field(ge=0, le=3650)
    training: bool
    downstream_processing: frozenset[
        Literal["inference", "storage", "indexing", "training", "document_processing"]
    ]
    max_output_bytes: int = Field(gt=0, le=100_000_000)

    def identity(self):
        return RecipientIdentity(
            self.recipient, self.issuer, self.client_id, self.environment, self.workspace
        )

    def review_digest(self):
        from canvas_bridge.evidence import fingerprint

        data = self.model_dump(mode="json")
        return fingerprint({k: sorted(v) if isinstance(v, list) else v for k, v in data.items()})


class ContentReview(Model):
    # Exact opaque source and immutable version, not filename or text-pattern matching.
    source_id: str = Field(min_length=1, max_length=100)
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    extracted_text_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    classification: ContentClassification
    purposes: frozenset[Purpose] = Field(min_length=1)
    reviewed_channels: frozenset[Channel] = Field(min_length=1)
    # Distinct from content ownership or extraction coverage; signed admin review.
    privacy_reviewed_channels: frozenset[Channel] = Field(default_factory=frozenset)
    privacy_review_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    content_owner_permission_reference: str | None = Field(
        default=None, min_length=1, max_length=1000
    )


class EgressGovernance(Model):
    policy_version: str = Field(min_length=1, max_length=100)
    recipients: list[RecipientPolicy] = Field(max_length=50)
    content_reviews: list[ContentReview] = Field(default_factory=list, max_length=2000)
    max_retention_days: int = Field(ge=0, le=3650)
    allow_training: bool = False
    allowed_processing: frozenset[
        Literal["inference", "storage", "indexing", "training", "document_processing"]
    ]

    @model_validator(mode="after")
    def unique(self):
        if len({r.policy_id for r in self.recipients}) != len(self.recipients):
            raise ValueError("Duplicate recipient policy")
        if len({(r.source_id, r.version) for r in self.content_reviews}) != len(
            self.content_reviews
        ):
            raise ValueError("Conflicting content reviews")
        return self


@dataclass(frozen=True)
class RecipientIdentity:
    recipient: str
    issuer: str = ""
    client_id: str = ""
    environment: str = ""
    workspace: str = ""


@dataclass(frozen=True)
class SourceContext:
    institution: str
    owner: str
    source_id: str
    version: str
    kind: str
    classification: ContentClassification = ContentClassification.UNKNOWN_OR_UNCLASSIFIED
    subject: str | None = None
    restricted: bool = False
    confidential: bool = False
    derived: bool = False
    content_sha256: str | None = None
    authorization_resource: str | None = None
    data_category: str | None = None
    extracted_text_sha256: str | None = None
    version_consistent: bool = True


@dataclass(frozen=True)
class Transfer:
    principal: str
    recipient: RecipientIdentity
    purpose: str
    channel: str
    sources: tuple[SourceContext, ...]
    amount: int
    authorized: bool
    privacy_filtered: bool
    minimized: bool = False
    redacted: bool = False
