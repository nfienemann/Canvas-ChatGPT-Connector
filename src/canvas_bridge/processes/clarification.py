"""Student-controlled clarification drafts and narrowly scoped response candidates."""

from typing import Literal

from canvas_bridge.domain import DomainError
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import EvidenceClaim, Model, Ref


class ClarificationRequest(Model):
    id: Ref
    field: Ref
    entity: Ref
    question: str
    evidence_ids: tuple[str, ...]
    status: Literal["drafted", "sent", "awaiting_response", "resolved"] = "drafted"
    status_basis: Literal["draft", "user_confirmed", "provider_confirmed"] = "draft"


def draft_clarification(resolution):
    if resolution.status == "resolved" or not resolution.candidates:
        raise DomainError("needs_input", "Choose an unresolved evidence question.")
    first = resolution.candidates[0]
    field = (
        first.field
        if first.field in {"deadline", "requirements", "weight", "policy", "prerequisite"}
        else "requirement"
    )
    return {
        "request": ClarificationRequest(
            id=fingerprint([c.id for c in resolution.candidates]),
            entity=first.entity,
            field=first.field,
            question=f"Could you clarify which {field} applies to this item and whether an explicit update replaces the earlier source?",
            evidence_ids=tuple(c.id for c in resolution.candidates),
        ),
        "self_service_first": [
            "Review the cited source versions",
            "Check authorized current assignment details and announcements",
        ],
        "message_sent": False,
    }


def confirm_status(request, target, *, confirmed, provider_receipt=False):
    allowed = {"drafted": "sent", "sent": "awaiting_response", "awaiting_response": "resolved"}
    if not confirmed or allowed.get(request.status) != target:
        raise DomainError(
            "needs_input", "Confirm the communication event before recording its status."
        )
    return request.model_copy(
        update={
            "status": target,
            "status_basis": "provider_confirmed" if provider_receipt else "user_confirmed",
        }
    )


def response_candidate(request, claim: EvidenceClaim):
    if claim.entity != request.entity or claim.field != request.field:
        raise DomainError("needs_input", "The response does not address this exact item and field.")
    # A pasted reply is evidence for later review, never an authority upgrade.
    return claim.model_copy(
        update={"basis": "user_declared", "authority": "unverified", "supersedes": ()}
    )
