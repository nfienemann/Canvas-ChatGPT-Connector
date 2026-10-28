"""Pseudonyms are scoped personal data, never authorization or anonymization."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import StrEnum


class IdentityClass(StrEnum):
    FIRST_PARTY_VERIFIED = "FIRST_PARTY_VERIFIED"
    THIRD_PARTY = "THIRD_PARTY"
    UNKNOWN = "UNKNOWN"
    SYSTEM_ENTITY = "SYSTEM_ENTITY"


class FieldClass(StrEnum):
    SAFE_ACADEMIC = "SAFE_ACADEMIC"
    FIRST_PARTY_ONLY = "FIRST_PARTY_ONLY"
    THIRD_PARTY_DIRECT_IDENTIFIER = "THIRD_PARTY_DIRECT_IDENTIFIER"
    QUASI_IDENTIFIER = "QUASI_IDENTIFIER"
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"


@dataclass(frozen=True)
class PrivacyIdentity:
    # Constructed only from the server's verified Connection, never tool input.
    canvas_user: str | None = None

    def classify(self, canonical_id):
        if not self.canvas_user or canonical_id is None:
            return IdentityClass.UNKNOWN
        return (
            IdentityClass.FIRST_PARTY_VERIFIED
            if str(canonical_id) == self.canvas_user
            else IdentityClass.THIRD_PARTY
        )


def pseudonym(
    vault_key: bytes,
    *,
    institution: str,
    owner: str,
    connection: str,
    course: str,
    entity_type: str,
    canonical_id: str,
    epoch: int,
    rotation: str,
):
    values = (
        institution,
        owner,
        connection,
        course,
        entity_type,
        canonical_id,
        str(epoch),
        rotation,
    )
    if len(vault_key) < 32 or any(not isinstance(v, str) or not v for v in values):
        raise ValueError("Invalid pseudonym scope")
    key = hmac.digest(vault_key, b"canvas-bridge/privacy/pseudonym-key/v1", "sha256")
    # JSON arrays are unambiguous, unlike delimiter concatenation. No mapping or
    # raw identifier is retained. Rotation is operator-controlled, not MCP input.
    message = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode()
    return "person_" + hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def scoped_pseudonym(bridge, owner, connection, course, entity_type, canonical_id):
    """Internal reference generation for already encountered records. No roster
    fetch, reverse map, model-callable resolver or credential-derived identity.
    """
    from canvas_bridge.domain import DomainError, utcnow
    from canvas_bridge.oauth_security import require_connection_identity
    from canvas_bridge.storage import aware

    bridge.authorize(owner, connection, course, "course").require()
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, connection)
        # Synthetic OAuth has no real token issuer, but its privacy lifecycle
        # must still honor the same explicit identity and revocation states.
        if conn.authentication_state != "verified" or not conn.canvas_user:
            raise DomainError(
                "permission_denied",
                "Verified connection identity is required.",
                reason_code="UPSTREAM_AUTH_UNVERIFIED",
            )
        if conn.token_expires_at and aware(conn.token_expires_at) <= utcnow():
            raise DomainError(
                "reconnect_required",
                "The connection has expired.",
                reason_code="UPSTREAM_AUTH_EXPIRED",
            )
        require_connection_identity(bridge, conn)
        return pseudonym(
            bridge.vault.key,
            institution=conn.institution,
            owner=owner,
            connection=connection,
            course=course,
            entity_type=entity_type,
            canonical_id=canonical_id,
            epoch=conn.epoch,
            rotation=bridge.settings.privacy_pseudonym_revision,
        )
