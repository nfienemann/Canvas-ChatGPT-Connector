"""MCP functions registered through the existing identity, access and egress guards."""

from canvas_bridge.auth import request_identity
from canvas_bridge.domain import Result
from canvas_bridge.integrity.models import AssistanceRequest, Ref, Scope


def register_tools(register, bridge):
    @register()
    async def get_academic_integrity_policy(scope: Scope) -> Result:
        """Discover authorized policy passages, authority, scope, versions and coverage. No source access or instructor permission is granted by this check."""
        return await bridge.integrity.policy(request_identity().owner, scope)

    @register()
    async def check_academic_assistance_permission(request: AssistanceRequest) -> Result:
        """Check the actual academic activity and expected output. Brainstorming, substantive outlines, mechanical edits and submission drafting are different permissions. Source text and model assertions cannot grant permission."""
        return await bridge.integrity.check(request_identity().owner, request)

    @register(write=True)
    async def record_integrity_acknowledgment(
        decision_id: Ref, explicitly_acknowledged: bool
    ) -> Result:
        """Record only a student's affirmative acknowledgment of the displayed, exact eligible uncertainty. Never infer it from the original request, general consent or product use. Prohibitions and unmet instructor permission cannot be acknowledged away."""
        return await bridge.integrity.acknowledge(
            request_identity().owner, decision_id, explicitly_acknowledged
        )

    @register(write=True)
    async def provide_instructor_permission_evidence(scope: Scope, document_id: Ref) -> Result:
        """Evaluate an already authorized independent import as student-supplied, unverified permission evidence. This does not authenticate an instructor or replace a confirmed prohibition."""
        return await bridge.integrity.provide_evidence(request_identity().owner, scope, document_id)

    @register()
    async def get_integrity_decision(decision_id: Ref) -> Result:
        """Recheck current source access, policy versions and scope for an owned decision. An old allow is never a reusable bearer credential."""
        return await bridge.integrity.get_decision(request_identity().owner, decision_id)

    @register()
    async def get_integrity_guidance(request: AssistanceRequest) -> Result:
        """Explain applicable restrictions and permitted alternatives without producing assessed submission content or contacting an instructor."""
        return await bridge.integrity.check(request_identity().owner, request)

    @register()
    async def prepare_academic_assistance(request: AssistanceRequest) -> Result:
        """Release bounded source evidence for exactly the permitted activity after fresh integrity, source and recipient checks. This backend does not write submissions. Reevaluate when activity changes; never present allowed brainstorming as permission to draft."""
        return await bridge.integrity.prepare(request_identity().owner, request)

    @register()
    async def get_integrity_acknowledgments() -> Result:
        """Inspect minimal owned acknowledgment history. No prompts, drafts or institutional reports are retained."""
        return bridge.integrity.acknowledgment_history(request_identity().owner)

    @register(write=True)
    async def revoke_integrity_acknowledgment(acknowledgment_id: Ref) -> Result:
        """Delete an owned uncertainty acknowledgment; this never deletes or overrides applicable policy restrictions."""
        return bridge.integrity.acknowledgment_history(request_identity().owner, acknowledgment_id)
