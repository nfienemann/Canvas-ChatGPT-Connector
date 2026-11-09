"""Immutable contract facts; examples and synthetic allowances grant no live access."""

import calendar
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Annotated, Literal, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")]
Units = Annotated[int, Field(strict=True, ge=0, le=10**12)]
Percent = Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False, decimal_places=4)]
POOLS = ("interactive", "scheduled_sync", "exploratory", "reserve")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Billing(Model):
    status: Literal["unconfigured", "configured", "reconciled", "local_development"] = (
        "unconfigured"
    )
    unit: Literal["commercial_transaction", "local_request"] = "commercial_transaction"
    monthly_allowance: Units | None = None
    signed_allowance: Units | None = None
    charge_model: Literal[
        "pending_contract_definition", "per_request", "endpoint_weighted", "external_counter"
    ] = "pending_contract_definition"
    default_units: Units = 1
    operation_units: dict[Identifier, Units] = Field(default_factory=dict)
    failed_requests: Literal["unknown", "charged", "verified_nonbillable"] = "unknown"
    pagination: Literal["unknown", "per_attempt"] = "unknown"
    retries: Literal["unknown", "per_attempt"] = "unknown"
    redirects: Literal["unknown", "per_attempt"] = "unknown"
    file_downloads: Literal["unknown", "per_attempt"] = "unknown"
    oauth: Literal["unknown", "per_attempt"] = "unknown"
    external_usage: Literal["unknown", "exclusive", "shared"] = "unknown"
    external_usage_buffer_units: Units = 0
    cycle_timezone: str = Field(default="UTC", max_length=80)
    cycle_day: int = Field(default=1, ge=1, le=31)
    safety_margin_pct: Percent = Decimal(5)
    paid_overages: Literal["disabled"] = "disabled"
    evidence_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reporting_delay_days: int = Field(default=30, ge=0, le=366)

    @model_validator(mode="after")
    def valid(self):
        ZoneInfo(self.cycle_timezone)
        if self.status == "local_development":
            if (
                self.unit != "local_request"
                or self.monthly_allowance is None
                or not 1 <= self.monthly_allowance <= 2147483647
                or self.signed_allowance is not None
                or self.evidence_sha256 is not None
                or self.charge_model != "per_request"
                or self.default_units != 1
                or self.operation_units
                or self.failed_requests != "charged"
            ):
                raise ValueError(
                    "Local development counts bounded requests, not vendor billing terms."
                )
            return self
        if self.unit != "commercial_transaction":
            raise ValueError("Commercial contracts require commercial units.")
        if self.status != "unconfigured":
            if (
                self.monthly_allowance is None
                or self.signed_allowance is None
                or self.monthly_allowance > self.signed_allowance
                or self.charge_model == "pending_contract_definition"
                or not self.evidence_sha256
                or "unknown"
                in (
                    self.failed_requests,
                    self.pagination,
                    self.retries,
                    self.redirects,
                    self.file_downloads,
                    self.oauth,
                    self.external_usage,
                )
            ):
                raise ValueError(
                    "Configured contracts require verified counting, allowance and evidence."
                )
            if self.external_usage == "shared" and self.external_usage_buffer_units == 0:
                raise ValueError("Shared contracts require a positive external uncertainty buffer.")
            if self.default_units < 1:
                raise ValueError("The conservative default estimate must be positive.")
        return self


class Allocation(Model):
    pool_mode: Literal[
        "strict_pools", "borrow_unused_nonreserve", "priority_weighted_fair_queue"
    ] = "borrow_unused_nonreserve"
    interactive_pct: Percent = Decimal(55)
    scheduled_sync_pct: Percent = Decimal(25)
    exploratory_pct: Percent = Decimal(10)
    reserve_pct: Percent = Decimal(10)
    lender_floor_pct: Percent = Decimal(10)
    reserve_eligible_operations: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def total(self):
        if sum(getattr(self, p + "_pct") for p in POOLS) != 100:
            raise ValueError("Pool percentages must sum exactly to 100.")
        return self


class Limits(Model):
    per_owner_minute_attempts: int = Field(default=12, ge=1, le=2147483647)
    per_owner_hour_attempts: int = Field(default=120, ge=1, le=2147483647)
    per_owner_daily_attempts: int = Field(default=300, ge=1, le=2147483647)
    per_tenant_daily_units: Units | None = None
    max_attempts_per_task: int = Field(default=40, ge=1, le=100000)
    max_units_per_task: Units = 100
    max_bytes_per_task: int = Field(default=128 * 1024 * 1024, ge=1000, le=512 * 1024 * 1024)
    max_download_attempts_per_task: int = Field(default=6, ge=1, le=40)
    task_seconds: int = Field(default=120, ge=1, le=600)
    max_concurrency_per_token: int = Field(default=1, ge=1, le=10)
    max_concurrency_per_owner: int = Field(default=2, ge=1, le=20)
    max_concurrency_per_tenant: int = Field(default=10, ge=1, le=100)
    max_global_concurrency: int = Field(default=20, ge=1, le=100)
    interactive_slots: int = Field(default=2, ge=0, le=99)
    retries_per_attempt: int = Field(default=2, ge=0, le=2)
    min_interval_seconds: float = Field(default=0.1, ge=0, le=10, allow_inf_nan=False)
    circuit_failures: int = Field(default=5, ge=1, le=20)
    circuit_seconds: int = Field(default=30, ge=1, le=3600)
    reservation_seconds: int = Field(default=180, ge=120, le=600)
    cache_ttl_seconds: int = Field(default=0, ge=0, le=60)

    @model_validator(mode="after")
    def capacity(self):
        if self.interactive_slots >= self.max_global_concurrency:
            raise ValueError("Interactive headroom must be smaller than total capacity.")
        return self


class PartnerBudgetContract(Model):
    schema_version: Literal[1] = 1
    provider: Identifier = "canvas"
    contract_id: Identifier = "unconfigured"
    version: int = Field(default=1, ge=1)
    mode: Literal[
        "offline_synthetic",
        "authorized_mock_provider",
        "production_approved",
        "personal_development",
    ] = "production_approved"
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    billing: Billing = Field(default_factory=Billing)
    allocation: Allocation = Field(default_factory=Allocation)
    limits: Limits = Field(default_factory=Limits)
    kill_switch: bool = False
    usage_thresholds_pct: tuple[Percent, ...] = (Decimal(50), Decimal(70), Decimal(85), Decimal(95))
    pause_exploratory_pct: Percent = Decimal(70)
    pause_sync_pct: Percent = Decimal(85)

    @model_validator(mode="after")
    def valid(self):
        if (self.mode == "personal_development") != (self.billing.status == "local_development"):
            raise ValueError("Local request accounting is restricted to personal development.")
        if self.expires_at <= self.effective_at:
            raise ValueError("Invalid effective interval.")
        if tuple(sorted(set(self.usage_thresholds_pct))) != self.usage_thresholds_pct:
            raise ValueError("Alert thresholds must be unique and increasing.")
        return self

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.model_dump(mode="json"))).hexdigest()

    @property
    def usable(self):
        return int(
            (
                (self.billing.monthly_allowance or 0) * (100 - self.billing.safety_margin_pct) / 100
            ).to_integral_value(rounding=ROUND_FLOOR)
        )

    def targets(self):
        # Largest remainder; stable POOLS order resolves ties. No unit disappears.
        raw = {p: self.usable * getattr(self.allocation, p + "_pct") / 100 for p in POOLS}
        result = {p: int(raw[p]) for p in POOLS}
        for p in sorted(POOLS, key=lambda p: raw[p] - result[p], reverse=True)[
            : self.usable - sum(result.values())
        ]:
            result[p] += 1
        return result

    def cycle(self, now):
        local = now.astimezone(ZoneInfo(self.billing.cycle_timezone))

        def anchor(year, month):
            day = min(self.billing.cycle_day, calendar.monthrange(year, month)[1])
            return datetime(year, month, day, tzinfo=local.tzinfo).astimezone(UTC)

        year, month = local.year, local.month
        if now < anchor(year, month):
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        start = anchor(year, month)
        end = anchor(year + 1, 1) if month == 12 else anchor(year, month + 1)
        return start, end


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


@dataclass(frozen=True)
class UsageContext:
    provider_id: str
    contract_id: str | None
    tenant_id: str | None
    owner_id: str | None
    task_id: str
    operation: str
    workload_class: str
    resource_scope: str | None
    token_key: str
    attempt_id: str = field(default_factory=lambda: uuid4().hex)
    parent_attempt_id: str | None = None


class ProviderBillingPolicy(Protocol):
    def reserve(self, policy: PartnerBudgetContract, operation: str) -> int: ...
    def settle(self, policy: PartnerBudgetContract, operation: str, status: int) -> int: ...


class ContractBillingAdapter:
    def reserve(self, policy, operation):
        return policy.billing.operation_units.get(operation, policy.billing.default_units)

    def settle(self, policy, operation, status):
        if status >= 400 and policy.billing.failed_requests == "verified_nonbillable":
            return 0
        return self.reserve(policy, operation)


def personal_development_policy(
    monthly_requests=3000, owner_request_limit=None, *, max_concurrency=2
):
    """Operator ceiling only; makes no assertion about vendor price or allowance."""
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 4:
        raise ValueError("Personal development concurrency must be an integer from 1 to 4")
    limits = dict(
        max_concurrency_per_token=max_concurrency,
        max_concurrency_per_owner=max(2, max_concurrency),
        # Each redirect is an accounted HTTP attempt. Six document transfers
        # can each require the initial GET plus three approved redirects.
        # Policy-document preflight and the requested document share this cap.
        max_download_attempts_per_task=24,
    )
    if owner_request_limit is not None:
        limits.update(
            per_owner_minute_attempts=owner_request_limit,
            per_owner_hour_attempts=owner_request_limit,
            per_owner_daily_attempts=owner_request_limit,
        )
    return PartnerBudgetContract(
        contract_id="personal-development-local-requests",
        mode="personal_development",
        effective_at=datetime(2000, 1, 1, tzinfo=UTC),
        expires_at=datetime(2100, 1, 1, tzinfo=UTC),
        billing=Billing(
            status="local_development",
            unit="local_request",
            monthly_allowance=monthly_requests,
            charge_model="per_request",
            failed_requests="charged",
        ),
        limits=Limits(**limits),
    )


def synthetic_policy():
    # Finite fictional allowance, only usable with the .invalid mock transport.
    return PartnerBudgetContract(
        contract_id="synthetic-fixture",
        mode="offline_synthetic",
        effective_at=datetime(2000, 1, 1, tzinfo=UTC),
        expires_at=datetime(2100, 1, 1, tzinfo=UTC),
        billing=Billing(
            status="configured",
            monthly_allowance=10**9,
            signed_allowance=10**9,
            charge_model="per_request",
            failed_requests="charged",
            pagination="per_attempt",
            retries="per_attempt",
            redirects="per_attempt",
            file_downloads="per_attempt",
            oauth="per_attempt",
            external_usage="exclusive",
            evidence_sha256="0" * 64,
        ),
        limits=Limits(
            per_owner_minute_attempts=100000,
            per_owner_hour_attempts=1000000,
            per_owner_daily_attempts=10000000,
            max_attempts_per_task=100000,
            max_units_per_task=100000,
            max_concurrency_per_token=10,
            min_interval_seconds=0,
        ),
    )
