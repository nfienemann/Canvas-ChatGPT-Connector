"""Public v1 contracts. Capability descriptions are never authorization grants."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from canvas_bridge.domain import DomainError

SDK_VERSION = "1.0.0"
Version = Annotated[
    str, Field(pattern=r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")
]
FIELDS = {
    "list_courses": ("courses",),
    "get_assignments": ("courses", "assignments", "assignments.deadline"),
    "get_grade_summary": ("courses", "categories", "assessments", "grading_rules"),
    "get_schedule": ("courses", "events"),
    "get_authorized_document": ("documents", "documents.parts"),
}
CAPABILITIES = tuple(FIELDS)


def unsupported(message="This interface or capability is not supported."):
    raise DomainError("unsupported_feature", message, reason_code="UNSUPPORTED_FEATURE")


def compatible(required, host=SDK_VERSION):
    """Stable releases only; same major and required minimum <= host."""
    pattern = r"(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})"
    if not all(isinstance(v, str) and re.fullmatch(pattern, v) for v in (required, host)):
        unsupported()
    need, current = (tuple(map(int, v.split("."))) for v in (required, host))
    if need[0] != current[0] or need[0] == 0 or need > current:
        unsupported()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderLimits(Contract):
    max_records: int = Field(default=512, ge=1, le=512)
    max_bytes: int = Field(default=2_000_000, ge=1024, le=2_000_000)
    timeout_seconds: int = Field(default=120, ge=1, le=120)


class Capability(Contract):
    supported: bool
    available_fields: tuple[str, ...] = ()
    permission_requirements: tuple[str, ...] = Field(min_length=1, max_length=12)
    freshness: Literal[
        "fictional_at_request", "user_supplied_unverified", "upstream_scope_verified", "unavailable"
    ]
    read_only: Literal[True] = True
    downstream_model_sharing: Literal["per_request_authorization", "local_only", "unavailable"]
    permission_granted: Literal[False] = False
    limits: ProviderLimits = Field(default_factory=ProviderLimits)
    reason: Literal["not_implemented_for_this_source"] | None = None


class ProviderManifest(Contract):
    api_version: Version
    normalized_schema: Literal["academic-1"] = "academic-1"
    provider: str = Field(min_length=1, max_length=100)
    operations: dict[str, Capability]

    @model_validator(mode="after")
    def explicit_capabilities(self):
        compatible(self.api_version)
        if set(self.operations) != set(CAPABILITIES):
            raise ValueError("All v1 capability states must be explicit.")
        for name, cap in self.operations.items():
            if set(cap.available_fields) - set(FIELDS[name]):
                raise ValueError("Unknown v1 fields.")
            if cap.supported != bool(cap.available_fields):
                raise ValueError("Supported operations must declare fields.")
            if not cap.supported and (
                cap.reason is None or cap.downstream_model_sharing != "unavailable"
            ):
                raise ValueError("Unsupported operations cannot advertise sharing.")
        return self
