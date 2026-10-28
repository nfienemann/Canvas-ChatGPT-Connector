"""Fictional administrator-reviewed AI environment; never a live deployment grant."""

from sqlalchemy import select

from canvas_bridge.egress_models import Channel, ContentClassification, Purpose
from canvas_bridge.storage import Material

ENVIRONMENT = "fictional-education-plan"
WORKSPACE = "fictional-private-workspace"


def recipient_claims():
    return {"bridge_recipient_environment": ENVIRONMENT, "bridge_recipient_workspace": WORKSPACE}


def install_governance(bridge, approvals, *, review_materials=False):
    profile = {
        "policy_id": "fictional-chatgpt-education",
        "recipient": "chatgpt",
        "environment": ENVIRONMENT,
        "workspace": WORKSPACE,
        "plan": "fictional-education",
        "issuer": bridge.settings.issuer_url,
        "client_id": "fixture-chatgpt-client",
        "classifications": [str(c) for c in ContentClassification],
        "purposes": list(Purpose.__args__),
        "channels": list(Channel.__args__),
        "retention_days": 7,
        "training": False,
        "downstream_processing": ["inference", "storage"],
        "max_output_bytes": 20_000_000,
    }
    governance = {
        "policy_version": "fictional-governance-1",
        "recipients": [
            profile,
            {
                **profile,
                "recipient": "user_download",
                "policy_id": "fictional-authenticated-download",
            },
        ],
        "max_retention_days": 7,
        "allow_training": False,
        "allowed_processing": ["inference", "storage"],
        "content_reviews": [],
    }
    if review_materials:
        with bridge.store.transaction() as session:
            for row in session.scalars(select(Material)):
                version = (
                    row.file_state.get("governance_source_version")
                    or row.file_state.get("version")
                    or row.version_hash
                )
                if version:
                    content_hash = next(
                        (
                            d.data["bytes_sha256"]
                            for d in bridge.original_files.records.values()
                            if d.file == row.id and d.data["source_version"] == version
                        ),
                        row.version_hash or None,
                    )
                    governance["content_reviews"].append(
                        {
                            "source_id": row.id,
                            "version": version,
                            "classification": "PUBLIC_OR_APPROVED",
                            "content_sha256": content_hash,
                            "purposes": list(Purpose.__args__),
                            "reviewed_channels": list(Channel.__args__),
                            "privacy_reviewed_channels": list(Channel.__args__),
                            "privacy_review_reference": "fictional-privacy-review",
                        }
                    )
    approvals.records[2]["egress"] = governance
    approvals.save()
    return governance
