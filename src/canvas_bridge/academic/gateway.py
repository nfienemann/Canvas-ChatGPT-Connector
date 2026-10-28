"""In-process authorization receipts, bound to exact normalized bytes and source policy.

This is not a login system or upstream approval authority. Adapters reuse the
host's verified principal/policies. PermissionContext in JSON is never authority.
"""

import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from canvas_bridge.academic.models import AcademicDataset, Course
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_policy import dangerous_reference
from canvas_bridge.privacy_text import inspect_text


@dataclass(frozen=True)
class AcademicRequest:
    principal: str
    tenant: str
    connection: str
    resource: str | None = None
    recipient: str = "local"
    purpose: str = "grade_planning"


@dataclass(frozen=True, repr=False)
class AuthorizedInput:
    _payload: str
    _proof: bytes
    _request: AcademicRequest
    _operation: str | None = None


def denied():
    raise DomainError(
        "permission_denied",
        "This academic source is not authorized for the requested use.",
        reason_code="RESOURCE_PERMISSION_DENIED",
    )


class AcademicGateway:
    def __init__(self, provider, *, clock=utcnow):
        self.provider, self.clock = provider, clock
        self._key = secrets.token_bytes(32)

    def _capability(self, request, operation):
        manifest = self.provider.describe()
        capability = manifest.operations.get(operation)
        if capability is None or not capability.supported:
            raise DomainError(
                "unsupported_feature",
                "This source does not support the requested academic capability.",
                reason_code="UNSUPPORTED_FEATURE",
            )
        if (
            request.recipient != "local"
            and capability.downstream_model_sharing != "per_request_authorization"
        ):
            denied()
        return capability

    def _validate(self, dataset, request, phase, operation):
        self.provider.require(request, phase=phase)
        capability = self._capability(request, operation)
        if (
            len(dataset.records()) > capability.limits.max_records
            or len(dataset.model_dump_json().encode()) > capability.limits.max_bytes
        ):
            raise DomainError(
                "unsupported_feature", "The provider exceeded its declared resource budget."
            )
        if dataset.provider != self.provider.provider_id or not dataset.records():
            denied()
        now = self.clock()
        for record in dataset.records():
            if isinstance(record, Course) and request.resource and record.id != request.resource:
                denied()
            if record.provenance.observed_at > now or (
                record.provenance.fresh_until and record.provenance.fresh_until <= now
            ):
                denied()
            scope = record.permission
            restrictions = record.restrictions
            if (
                (scope.principal, scope.tenant, scope.connection)
                != (request.principal, request.tenant, request.connection)
                or scope.expires_at <= now
                or request.purpose not in scope.scope
                or request.purpose not in restrictions.purposes
                or request.recipient not in restrictions.recipients
                or (
                    request.resource
                    and getattr(record, "course_id", request.resource)
                    not in {None, request.resource}
                )
            ):
                denied()
            if restrictions.classifications & {
                CC.UNKNOWN_OR_UNCLASSIFIED,
                CC.THIRD_PARTY_EDUCATIONAL_RECORD,
                CC.RESTRICTED_ASSESSMENT,
                CC.CONFIDENTIAL_RESEARCH,
            }:
                denied()
            self.provider.verify_record(record, request)

    def _issue(self, dataset, request, operation):
        # Reparse, even for model_copy/model_construct objects, and preserve all labels.
        dataset = AcademicDataset.model_validate_json(dataset.model_dump_json())
        self._validate(dataset, request, "analysis", operation)
        # Last local privacy inspection; findings stay uncertainty, never a license change.
        for record in dataset.records():
            for source in (record.provenance.source, *record.provenance.derived_from):
                if source.uri and (dangerous_reference(source.uri) or inspect_text(source.uri)[1]):
                    denied()
            for name in ("title", "text"):
                value = getattr(record, name, None)
                if value is not None and inspect_text(value)[1]:
                    denied()
        payload = dataset.model_dump_json()
        if len(payload.encode()) > 2_000_000:
            raise DomainError(
                "unsupported_feature",
                "Normalized academic evidence exceeds the bounded input size.",
            )
        proof = hmac.digest(
            self._key, (repr((request, operation)) + payload).encode(), hashlib.sha256
        )
        return AuthorizedInput(payload, proof, request, operation)

    async def retrieve(self, operation, request):
        self.provider.require(request, phase="retrieve")
        capability = self._capability(request, operation)
        try:
            async with asyncio.timeout(capability.limits.timeout_seconds):
                dataset = await self.provider.retrieve(operation, request)
        except TimeoutError:
            raise DomainError(
                "unsupported_feature", "The provider exceeded its time budget."
            ) from None
        if (
            len(dataset.records()) > capability.limits.max_records
            or len(dataset.model_dump_json().encode()) > capability.limits.max_bytes
        ):
            raise DomainError(
                "unsupported_feature", "The provider exceeded its declared resource budget."
            )
        return self._issue(dataset, request, operation)

    def consume(self, authorized):
        if not isinstance(authorized, AuthorizedInput):
            denied()
        proof = hmac.digest(
            self._key,
            (repr((authorized._request, authorized._operation)) + authorized._payload).encode(),
            hashlib.sha256,
        )
        if not hmac.compare_digest(proof, authorized._proof):
            denied()
        dataset = AcademicDataset.model_validate_json(authorized._payload)
        self._validate(dataset, authorized._request, "analysis", authorized._operation)
        return dataset

    def release(self, authorized):
        dataset = self.consume(authorized)
        self._validate(dataset, authorized._request, "release", authorized._operation)
        return dataset
