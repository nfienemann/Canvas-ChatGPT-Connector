"""Narrow internal capabilities. No raw HTTP, SQL, tokens or approval mutators."""

from abc import ABC, abstractmethod

from canvas_bridge.academic.contracts import (
    CAPABILITIES,
    Capability,
    ProviderManifest,
    compatible,
    unsupported,
)
from canvas_bridge.academic.gateway import AcademicGateway


class AcademicProvider(ABC):
    provider_id: str
    api_version: str | None = None
    supported: frozenset[str] = frozenset()
    capability_fields: dict[str, tuple[str, ...]] = {}
    permission_requirements = ("independent_provider_and_host_authorization",)
    freshness = "unavailable"
    downstream_model_sharing = "unavailable"

    def __init__(self, *, clock):
        self.gateway = AcademicGateway(self, clock=clock)

    def describe(self):
        compatible(self.api_version)
        if self.supported != frozenset(self.capability_fields) or self.supported - set(
            CAPABILITIES
        ):
            unsupported("The provider capability declaration is inconsistent.")
        return ProviderManifest(
            api_version=self.api_version,
            provider=self.provider_id,
            operations={
                name: Capability(
                    supported=name in self.supported,
                    available_fields=self.capability_fields.get(name, ()),
                    permission_requirements=self.permission_requirements,
                    freshness=self.freshness if name in self.supported else "unavailable",
                    downstream_model_sharing=self.downstream_model_sharing
                    if name in self.supported
                    else "unavailable",
                    reason=None if name in self.supported else "not_implemented_for_this_source",
                )
                for name in CAPABILITIES
            },
        )

    def get_source_capabilities(self):
        # Preserve the existing operation-keyed discovery wrapper.
        manifest = self.describe()
        return {
            name: {"api_version": manifest.api_version, **cap.model_dump(mode="json")}
            for name, cap in manifest.operations.items()
        }

    async def list_courses(self, request):
        return await self.gateway.retrieve("list_courses", request)

    async def get_assignments(self, request):
        return await self.gateway.retrieve("get_assignments", request)

    async def get_grade_summary(self, request):
        return await self.gateway.retrieve("get_grade_summary", request)

    async def get_schedule(self, request):
        return await self.gateway.retrieve("get_schedule", request)

    async def get_authorized_document(self, request):
        return await self.gateway.retrieve("get_authorized_document", request)

    @abstractmethod
    def require(self, request, *, phase):
        """Recheck trusted host/provider permission; model metadata cannot grant it."""

    @abstractmethod
    def verify_record(self, record, request):
        """Bind exact references, versions and restrictions to trusted source state."""

    @abstractmethod
    async def retrieve(self, operation, request):
        """Adapter implementation must also enforce require before side effects."""
