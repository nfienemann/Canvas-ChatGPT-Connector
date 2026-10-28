"""Explicit fictional approvals for tests that exercise a live-profile code path."""

import base64
import hashlib
import json
import os
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from canvas_bridge.approval_admin import seal_evidence, sign_record
from canvas_bridge.approval_policy import CATEGORIES
from canvas_bridge.domain import utcnow


class Approvals:
    def __init__(self, settings):
        root = settings.vault_key_file.parent / "fictional-approvals"
        root.mkdir(exist_ok=True)
        self.settings, self.root = settings, root
        settings.mcp_chatgpt_client_ids = frozenset({"fixture-chatgpt-client"})
        self.key = Ed25519PrivateKey.generate()
        self.evidence = seal_evidence(b"FICTIONAL TEST EVIDENCE ONLY", os.urandom(32))
        digest = hashlib.sha256(self.evidence).hexdigest()
        (root / (digest + ".sealed")).write_bytes(self.evidence)
        settings.approval_evidence_root = root
        settings.approval_records_file = root / "approvals.json"
        settings.approval_trust_file = root / "trust.json"
        settings.approval_trust_file.write_text(
            json.dumps(
                {
                    "administrators": [
                        {
                            "key_id": "fixture-admin",
                            "public_key": base64.b64encode(
                                self.key.public_key().public_bytes_raw()
                            ).decode(),
                            "organization": "Fictional review authority",
                            "authorities": ["provider", "institution", "sharing"],
                            "institutions": ["synthetic"],
                        }
                    ]
                }
            )
        )
        self.records = [
            {
                "record_id": authority + "-fixture",
                "authority": authority,
                "approving_organization": "Fictional review authority",
                "approving_authority": "Test administrator",
                "written_authorization_reference": "CONFIDENTIAL-FICTIONAL-REFERENCE",
                "evidence_sha256": digest,
                "state": "APPROVED",
                "verification_status": "verified",
                "verified_by": "Fictional verifier",
                "verified_at": (utcnow() - timedelta(minutes=5)).isoformat(),
                "institutions": ["synthetic"],
                "mechanisms": ["rest_api", "mcp"],
                "deployment_modes": ["personal", "hosted"],
                "activities": ["retrieve", "share", "link", "refresh"],
                "data_categories": sorted(CATEGORIES),
                "recipients": ["local", "chatgpt", "user_download"],
                "effective_at": (utcnow() - timedelta(days=1)).isoformat(),
                "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
            }
            for authority in ("provider", "institution", "sharing")
        ]
        self.save()

    def save(self):
        self.settings.approval_records_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "records": [
                        sign_record(record, "fixture-admin", self.key.private_bytes_raw())
                        for record in self.records
                    ],
                }
            )
        )


def install_identity_fixture(bridge):
    # Explicit synthetic protocol configuration and fixture identity, separate
    # from the signed fictional approvals installed below. Never used in runtime.
    from typing import get_args

    from sqlalchemy import select

    from canvas_bridge.oauth_security import binding
    from canvas_bridge.policy import Capability, OAuthCapabilities
    from canvas_bridge.storage import Connection

    institution = bridge.registry.entries["synthetic"]
    institution.capabilities = frozenset(get_args(Capability))
    institution.oauth = OAuthCapabilities(
        pkce="S256",
        refresh_rotation="stable",
        granular_scopes=True,
        documentation_reference="fictional-fixture-only",
    )
    with bridge.store.transaction() as session:
        for conn in session.scalars(
            select(Connection).where(Connection.institution == "synthetic")
        ):
            if conn.credential:
                secret = bridge.vault.open(conn.credential, conn.owner, conn.id)
                expected = binding(bridge, institution)
                if secret.get("identity_binding") != expected:
                    secret["identity_binding"] = expected
                    conn.credential = bridge.vault.seal(secret, conn.owner, conn.id)
                conn.authentication_state = "verified"


def install_approvals(bridge):
    install_identity_fixture(bridge)
    return Approvals(bridge.settings)
