"""Strict public evidence schemas; raw logs and private approval evidence are excluded."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal[
    "NOT_IMPLEMENTED",
    "IN_PROGRESS",
    "IMPLEMENTED_UNVERIFIED",
    "TESTED",
    "REQUIRES_EXTERNAL_APPROVAL",
    "NOT_APPLICABLE",
]
Target = Literal["offline_core", "institutional_pilot", "public_connected_plugin"]
Category = Literal[
    "offline_core", "synthetic_demo", "institutional_pilot", "public_connected_plugin"
]
Digest = str


class EvidenceError(ValueError):
    """Only static error codes reach the console; validation inputs never do."""


def safe_text(value):
    if isinstance(value, str):
        if re.search(
            r"-----BEGIN .*PRIVATE KEY|\beyJ[a-zA-Z0-9_-]{15,}\.|"
            r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\b\d{3}-\d{2}-\d{4}\b|"
            r"(?i:bearer\s+[a-z0-9._-]{12,}|(?:access_token|refresh_token|client_secret|password)\s*[:=]\s*\S+)",
            value,
        ):
            raise EvidenceError("SENSITIVE_EVIDENCE_REJECTED")
    elif isinstance(value, dict):
        for key, item in value.items():
            safe_text(key)
            safe_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            safe_text(item)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def public_text(self):
        safe_text(self.model_dump(mode="json"))
        return self


class Control(Strict):
    id: str = Field(pattern=r"^CB-[A-Z]+-[0-9]{2}$")
    objective: str
    requirements: list[str] = Field(min_length=1)
    owner: str
    components: list[str] = Field(min_length=1)
    enforcement: list[str] = Field(min_length=1)
    tests: list[str]
    checks: list[str]
    automated_scope: str
    manual_verification: str
    status: Status
    residual_limitation: str
    targets: list[Target] = Field(min_length=1)


class PolicySource(Strict):
    id: str
    title: str
    url: str
    effective_date: date | None
    effective_date_note: str
    revision: str
    sections: list[str]
    reviewed_on: date
    review_due: date
    interpretation: str
    controls: list[str]
    applicability: str


class Approval(Strict):
    id: str
    party: str
    requirement: str
    targets: list[Target]
    status: Literal["MISSING", "REQUESTED", "GRANTED", "RESTRICTED", "EXPIRED", "REJECTED"]
    verified: bool = False
    evidence_reference: str | None = Field(default=None, pattern=r"^[A-Z0-9_-]{3,80}$")
    effective_on: date | None = None
    expires_on: date | None = None
    scope_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    conditions: list[str] = []


class ManualReview(Strict):
    id: str
    requirement: str
    owner: str
    targets: list[Target]
    status: Literal["MISSING", "IN_PROGRESS", "ACCEPTED", "REJECTED"]
    evidence_reference: str | None = Field(default=None, pattern=r"^[A-Z0-9_-]{3,80}$")
    source_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    expires_on: date | None = None


class OperationalRegression(Strict):
    id: str = Field(pattern=r"^CB-REC-[0-9]{2}$")
    reproduction_fixture: str
    root_cause: str
    security_boundary: str
    remediation: str
    tests: list[str] = Field(min_length=1)
    status: Status = "IMPLEMENTED_UNVERIFIED"
    residual_uncertainty: str


class Registry(Strict):
    schema_version: Literal["controls-1"]
    controls: list[Control] = Field(min_length=1)
    policies: list[PolicySource] = Field(min_length=1)
    approvals: list[Approval] = Field(min_length=1)
    manual_reviews: list[ManualReview] = Field(min_length=1)
    required_checks: list[str]
    templates: dict[str, str]
    data_flow: list[str]
    limitations: list[str]
    operational_regressions: list[OperationalRegression] = Field(default_factory=list)


class Source(Strict):
    commit: str | None = Field(pattern=r"^[a-f0-9]{40,64}$")
    dirty: bool
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    files: int = Field(ge=1)
    scope: Literal["reviewed-source-v1"] = "reviewed-source-v1"


class Counts(Strict):
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    error: int = Field(default=0, ge=0)
    collected: int = Field(default=0, ge=0)

    def verified(self):
        return (
            self.collected > 0
            and self.passed == self.collected
            and not (self.failed or self.error or self.skipped)
        )


class TestRun(Strict):
    schema_version: Literal["test-run-1"]
    source: Source
    finished_on: date
    source_unchanged: bool
    exit_code: int
    interrupted: bool
    complete_selection: bool = False
    cases: dict[str, Counts]
    runtime: Literal["windows", "linux", "darwin", "other"]


class CheckRun(Strict):
    schema_version: Literal["check-run-1"]
    source: Source
    finished_on: date
    source_unchanged: bool
    check: str
    status: Literal["PASSED", "FAILED", "ERROR"]
    findings: int | None = Field(default=None, ge=0)
    advisories: list[str] = []
    coverage_notes: list[
        Literal["FIRST_PARTY_SOURCE_REVIEW_REQUIRED", "INSTALLED_ENVIRONMENT_ONLY"]
    ] = []

    @model_validator(mode="after")
    def consistent_findings(self):
        if self.status == "PASSED" and self.findings:
            raise ValueError("Findings cannot be labeled passed.")
        if any(
            not re.fullmatch(r"(?:CVE-[0-9-]+|GHSA-[a-z0-9-]+|PYSEC-[0-9-]+)", item)
            for item in self.advisories
        ):
            raise ValueError("Only public advisory identifiers are accepted.")
        return self


class FixtureCatalog(Strict):
    schema_version: Literal["fictional-fixtures-1"]
    origin: Literal["generated-fictional-only"]
    files: dict[str, str]
