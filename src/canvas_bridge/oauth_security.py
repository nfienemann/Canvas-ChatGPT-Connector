"""Protocol and capability checks on the existing connection identity boundary."""

import base64
import hashlib
import json
import os

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.policy import Endpoint


def unavailable(message="Reviewed institution OAuth capabilities are required."):
    return DomainError("reconnect_required", message, reason_code="UPSTREAM_AUTH_UNVERIFIED")


def require_oauth(institution):
    if institution.oauth is None:
        raise unavailable()
    return institution.oauth


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def callback_url(bridge, institution):
    # Distinct even when the provider cannot return an issuer parameter.
    key = hashlib.sha256(f"{institution.id}\0{institution.origin}".encode()).hexdigest()
    return bridge.settings.resource_url.rstrip("/") + "/settings/canvas/callback/" + key


def endpoint_capabilities(endpoint, resource=None):
    from canvas_bridge.authorization import ENDPOINT_RESOURCE

    if endpoint == Endpoint.PROFILE:
        return set()
    if endpoint == Endpoint.COURSES:
        return {"courses", "course_membership"} | ({resource} if resource else set())
    required = {ENDPOINT_RESOURCE.get(endpoint, "unknown")}
    if endpoint == Endpoint.ENROLLMENTS:
        required.add("course_membership")
    if resource:
        required.add("courses" if resource == "course" else resource)
    return {"courses" if c == "course" else c for c in required}


def require_capabilities(bridge, institution, capabilities):
    if bridge.settings.profile != "synthetic" and not set(capabilities) <= institution.capabilities:
        raise DomainError(
            "permission_denied",
            "This workflow is not enabled for this institution.",
            reason_code="MISSING_RESOURCE_CAPABILITY",
        )


def requested_scopes(institution):
    from canvas_bridge.authorization import SCOPES

    oauth = require_oauth(institution)
    known = set(SCOPES.values())
    if any(s not in known for s in institution.scopes):
        raise unavailable("Only reviewed read scopes are supported.")
    scopes = sorted(
        {
            scope
            for endpoint, scope in SCOPES.items()
            if scope in institution.scopes
            and endpoint_capabilities(endpoint) <= institution.capabilities
        }
    )
    if oauth.granular_scopes and not {SCOPES[Endpoint.PROFILE], SCOPES[Endpoint.COURSES]} <= set(
        scopes
    ):
        raise unavailable("Profile and course discovery scopes are required.")
    return scopes if oauth.granular_scopes else []


def binding(bridge, institution):
    """A changed origin, client, capability or scope cannot reuse an older grant."""
    value = {
        "institution": institution.id,
        "origin": institution.origin,
        "client_id": os.environ.get(institution.client_id_env or "", ""),
        "oauth": institution.oauth.model_dump() if institution.oauth else None,
        "capabilities": sorted(institution.capabilities),
        "scopes": sorted(institution.scopes),
        "redirect": callback_url(bridge, institution),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def require_connection_identity(bridge, conn):
    if bridge.settings.profile == "synthetic":
        return
    institution = bridge.registry.require(
        conn.institution, personal=bridge.settings.profile == "personal"
    )
    if conn.authentication_state != "verified":
        raise unavailable("Upstream identity must be verified before accessing coursework.")
    from canvas_bridge.storage import aware

    if conn.token_expires_at and aware(conn.token_expires_at) <= utcnow():
        raise DomainError(
            "reconnect_required",
            "The Canvas credential has expired.",
            reason_code="UPSTREAM_AUTH_EXPIRED",
        )
    if bridge.settings.profile == "hosted":
        require_oauth(institution)
    try:
        secret = bridge.vault.open(conn.credential, conn.owner, conn.id)
        if secret.get("identity_binding") != binding(bridge, institution):
            raise unavailable("Connection configuration changed; reconnect this account.")
    except DomainError:
        raise
    except Exception:
        raise unavailable() from None


def token_response(result, institution):
    oauth = require_oauth(institution)
    if not isinstance(result, dict):
        raise unavailable("Invalid authorization response.")
    access = result.get("access_token")
    expires = result.get("expires_in")
    refresh = result.get("refresh_token")
    if (
        not isinstance(access, str)
        or not 1 <= len(access) <= 16384
        or any(ord(c) < 33 or ord(c) > 126 for c in access)
        or str(result.get("token_type", "")).lower() != "bearer"
        or type(expires) is not int
        or not 0 < expires <= oauth.max_access_token_seconds
        or (
            "refresh_token" in result
            and (not isinstance(refresh, str) or not 1 <= len(refresh) <= 16384)
        )
    ):
        raise unavailable("Invalid authorization response.")
    if "scope" in result:
        scopes = result["scope"]
        if not isinstance(scopes, str) or set(scopes.split()) != set(requested_scopes(institution)):
            raise unavailable("The provider returned a different permission scope.")
    return {k: result[k] for k in ("access_token", "refresh_token", "expires_in") if k in result}
