"""Publication rights are independent of assistance permission and local creation."""

from typing import Literal

from pydantic import AwareDatetime, Field

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import Model, Ref, SourceTag


class PortfolioPart(Model):
    id: Ref
    source: SourceTag
    origin: Literal[
        "student_authored",
        "assigned_reading",
        "lms_material",
        "group_work",
        "lab_research",
        "third_party_asset",
        "patient_data",
    ]
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PublicationReview(Model):
    """Trusted human-review registry entry; never populated from document prose."""

    part_id: Ref
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_version: Ref
    permission: Literal["allowed", "prohibited", "unknown"]
    reviewed_at: AwareDatetime
    expires_at: AwareDatetime
    review_reference: Ref
    attribution_checked: bool = False
    privacy_checked: bool = False
    collaborators_checked: bool = False
    research_release_checked: bool = False


def publication_clearance(parts, reviews, *, now, assistance_decision=None):
    if not parts or len(parts) > 100 or len({p.id for p in parts}) != len(parts):
        raise ValueError("Choose a bounded, unique artifact inventory.")
    checklist, approved = [], []
    for part in parts:
        checks = [
            r
            for r in reviews
            if r.part_id == part.id
            and r.content_hash == part.content_hash
            and r.source_version == part.source.version
            and r.reviewed_at <= now < r.expires_at
        ]
        reasons = []
        if part.source.expires_at <= now:
            reasons.append("SOURCE_AUTHORIZATION_RECHECK_REQUIRED")
        if len(checks) != 1 or checks[0].permission != "allowed":
            reasons.append("PUBLICATION_PERMISSION_UNVERIFIED")
        else:
            review = checks[0]
            if not review.privacy_checked:
                reasons.append("PRIVACY_REVIEW_REQUIRED")
            if not review.attribution_checked:
                reasons.append("ATTRIBUTION_REVIEW_REQUIRED")
            if part.origin == "group_work" and not review.collaborators_checked:
                reasons.append("COLLABORATOR_CREDIT_AND_CONSENT_REQUIRED")
            if part.origin == "lab_research" and not review.research_release_checked:
                reasons.append("UNPUBLISHED_RESEARCH_REVIEW_REQUIRED")
        if part.origin == "patient_data":
            reasons.append("PATIENT_DATA_EXPORT_UNSUPPORTED")
        if not checks and part.origin == "group_work":
            reasons.append("COLLABORATOR_CREDIT_AND_CONSENT_REQUIRED")
        if not checks and part.origin == "lab_research":
            reasons.append("UNPUBLISHED_RESEARCH_REVIEW_REQUIRED")
        if reasons:
            checklist.append(
                {
                    "part_id": part.id,
                    "reasons": reasons,
                    "next_step": "obtain_review_or_remove_restricted_content",
                }
            )
        else:
            approved.append(part.id)
    if assistance_decision is not None and (
        not assistance_decision.allowed or assistance_decision.expires_at <= now
    ):
        checklist.append(
            {
                "part_id": "assignment-context",
                "reasons": ["ACADEMIC_INTEGRITY_REVIEW_REQUIRED"],
                "next_step": "review_current_integrity_decision",
            }
        )
    return {
        "clearance_id": fingerprint(
            [
                [p.model_dump(mode="json") for p in parts],
                [r.model_dump(mode="json") for r in reviews],
            ]
        ),
        "status": "cleared_for_reviewed_export" if not checklist else "held_for_review",
        "checklist": checklist,
        "cleared_parts": approved,
        "publish_executed": False,
        "explicit_user_action_required": True,
        "assistance_permission_is_publication_permission": False,
    }


def export_manifest(parts, reviews, *, now, confirmed, authorize, assistance_decision=None):
    from canvas_bridge.domain import DomainError

    clearance = publication_clearance(
        parts, reviews, now=now, assistance_decision=assistance_decision
    )
    if not confirmed or clearance["status"] != "cleared_for_reviewed_export":
        raise DomainError(
            "permission_denied",
            "A current clearance and explicit export request are required.",
            reason_code="PROCESS_PUBLICATION_REVIEW_REQUIRED",
        )
    for part in parts:
        authorize(part.source, "publication_export")
    return {
        "schema_version": "portfolio-manifest-1",
        "clearance": clearance,
        "parts": [p.model_dump(mode="json") for p in parts],
        "published": False,
    }
