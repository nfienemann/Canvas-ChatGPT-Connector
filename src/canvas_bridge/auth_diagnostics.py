"""Fixed, public observations for the two independent credential boundaries."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Check = Literal["passed", "failed", "unknown", "not_checked"]


class AuthDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["auth/1"] = "auth/1"
    code: str = Field(pattern=r"^[A-Z0-9_]{1,80}$")
    failure_layer: Literal[
        "none",
        "unknown",
        "client_connection",
        "mcp_transport",
        "bridge_authorization",
        "account_mapping",
        "canvas_connection",
        "canvas_api",
        "authentication_service",
        "bridge_admission",
    ]
    attribution: Literal["confirmed", "unknown"] = "confirmed"
    observation_source: Literal[
        "client_signal",
        "sdk_challenge",
        "jwt_validator",
        "bridge_guard",
        "owner_scoped_store",
        "canvas_response",
        "bridge_admission",
        "canvas_oauth_exchange",
    ]
    bridge_reached: Literal["yes", "unknown"] = "yes"
    canvas_reached: Literal["yes", "no", "unknown"] = "unknown"
    mcp_authentication: Check = "not_checked"
    bridge_authorization: Check = "not_checked"
    canvas_authentication: Check = "not_checked"
    canvas_authorization: Check = "not_checked"
    checked_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    freshness: Literal["this_request", "reported"] = "this_request"
    correlation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    recovery_action: str
    retry: Literal["after_repair_once", "after_delay_once", "none"]
    explanation: str


def observation(code, layer, source, action, explanation, ident, **checks):
    return AuthDiagnostic(
        code=code,
        failure_layer=layer,
        observation_source=source,
        recovery_action=action,
        explanation=explanation,
        correlation_id=ident,
        retry=checks.pop("retry", "after_repair_once"),
        **checks,
    )


def transport_observation(reason, missing, ident):
    checks = {"canvas_reached": "no"}
    if reason in {"MCP_KEY_SOURCE_UNAVAILABLE", "MCP_IDENTITY_STATE_UNAVAILABLE"}:
        return observation(
            reason,
            "authentication_service",
            "jwt_validator",
            "wait_or_contact_operator",
            "Bridge could not complete credential validation. Wait or contact the operator.",
            ident,
            mcp_authentication="unknown",
            retry="after_delay_once",
            **checks,
        )
    if reason in {
        "MCP_PERSONAL_SUBJECT_MISMATCH",
        "MCP_REQUIRED_SCOPE_MISSING",
        "SDK_SCOPE_DENIED",
    }:
        account = reason == "MCP_PERSONAL_SUBJECT_MISMATCH"
        return observation(
            "MCP_ACCOUNT_NOT_AUTHORIZED" if account else "MCP_SCOPE_DENIED",
            "account_mapping" if account else "bridge_authorization",
            "sdk_challenge" if reason == "SDK_SCOPE_DENIED" else "jwt_validator",
            "select_correct_account" if account else "review_client_permission",
            "Use the intended application account."
            if account
            else "Review the permission assigned to this client with the operator.",
            ident,
            mcp_authentication="passed" if reason == "SDK_SCOPE_DENIED" else "unknown",
            bridge_authorization="failed",
            **checks,
        )
    specific = {
        "MCP_TOKEN_EXPIRED": "The presented application credential has expired.",
        "MCP_AUDIENCE_MISMATCH": "The credential has a different resource audience.",
        "MCP_ISSUER_MISMATCH": "The credential has a different issuer.",
    }
    return observation(
        "MCP_CREDENTIAL_MISSING"
        if missing
        else reason
        if reason in specific
        else "MCP_CREDENTIAL_REJECTED",
        "mcp_transport",
        "jwt_validator" if reason else "sdk_challenge",
        "repair_inbound_credential",
        (
            "Bridge received no application credential in the supported format."
            if missing
            else specific.get(reason, "Bridge could not accept the inbound credential.")
        )
        + " Reauthorize the configured client connection.",
        ident,
        mcp_authentication="not_checked" if missing else "failed",
        **checks,
    )


def status_observation(connections, ident):
    has_connections = bool(connections)
    if len(connections) == 1:
        stored = connections[0].get("authentication_state")
        codes = {
            "expired": "UPSTREAM_AUTH_EXPIRED",
            "revoked": "CONNECTION_INACTIVE",
            "unverified": "UPSTREAM_AUTH_UNVERIFIED",
        }
        if stored in codes:
            return observation(
                codes[stored],
                "canvas_connection",
                "owner_scoped_store",
                "review_secure_canvas_setup",
                "Review the stored Canvas connection in the configured secure setup or with its operator.",
                ident,
                mcp_authentication="passed",
                bridge_authorization="passed",
                canvas_reached="no",
            )
    return observation(
        "CONNECTION_STATUS_CHECKED" if has_connections else "CANVAS_CONNECTION_MISSING",
        "none" if has_connections else "canvas_connection",
        "owner_scoped_store",
        "none" if has_connections else "review_secure_canvas_setup",
        "Bridge read the current account's stored connections. Canvas access is unchecked."
        if has_connections
        else "This account has no stored Canvas connection. Review secure setup with the operator.",
        ident,
        mcp_authentication="passed",
        bridge_authorization="passed",
        canvas_reached="no",
        retry="none" if has_connections else "after_repair_once",
    )


def tool_observation(code, http, attempt, data):
    auth = "passed" if attempt.authenticated else "unknown"
    checks = {"mcp_authentication": auth}
    ident = attempt.request_id
    if code == "TRANSPORT_BUSY":
        return observation(
            code,
            "bridge_admission",
            "bridge_admission",
            "wait_or_contact_operator",
            "Bridge admission capacity is exhausted. Wait before retrying.",
            ident,
            canvas_reached="no",
            retry="after_delay_once",
        )
    if code in {"MCP_SESSION_REVOKED", "MCP_TOKEN_EXPIRED"}:
        return observation(
            code,
            "mcp_transport",
            "jwt_validator",
            "repair_inbound_credential",
            "The current application session is no longer valid. Reauthorize the client connection.",
            ident,
            mcp_authentication="failed",
        )
    if code == "MCP_ACCESS_DENIED" and attempt.authenticated:
        return observation(
            code,
            "bridge_authorization",
            "bridge_guard",
            "review_client_permission",
            "Bridge denied this operation. Review the current account and tool permission.",
            ident,
            bridge_authorization="failed",
            **checks,
        )
    if code in {"CONNECTION_OWNERSHIP_MISMATCH", "OAUTH_IDENTITY_MISMATCH"}:
        return observation(
            code,
            "account_mapping",
            "bridge_guard",
            "select_correct_account",
            "Use the intended account and a connection returned for that account.",
            ident,
            bridge_authorization="failed",
            **checks,
        )
    checks["bridge_authorization"] = "passed" if attempt.tool_authorized else "unknown"
    if code == "TRANSPORT_ACCESS_DENIED":
        return observation(
            "AUTH_ORIGIN_UNKNOWN",
            "unknown",
            "bridge_guard",
            "contact_operator",
            "Bridge observed a transport denial without a verified cause. Contact the operator.",
            ident,
            attribution="unknown",
            **checks,
        )
    if code == "OAUTH_GRANT_REJECTED":
        return observation(
            code,
            "authentication_service",
            "canvas_oauth_exchange",
            "review_secure_canvas_setup",
            "The Canvas authorization service rejected this grant. Review secure setup with the operator.",
            ident,
            **checks,
        )
    if code in {"CANVAS_OAUTH_UNAVAILABLE", "CANVAS_OAUTH_EXCHANGE_FAILED"}:
        return observation(
            code,
            "authentication_service",
            "canvas_oauth_exchange",
            "wait_or_contact_operator",
            "Bridge could not complete the Canvas authorization exchange. Contact the operator if it persists.",
            ident,
            retry="after_delay_once",
            **checks,
        )
    if (
        code in {"CONNECTION_INACTIVE", "UPSTREAM_AUTH_UNVERIFIED", "UPSTREAM_AUTH_EXPIRED"}
        and http is None
    ):
        return observation(
            code,
            "canvas_connection",
            "owner_scoped_store",
            "review_secure_canvas_setup",
            "Review the stored connection through the configured secure setup or its operator.",
            ident,
            **checks,
        )
    if (
        data.get("origin") == "file_delivery_provider"
        or data.get("capability_observation") == "recent_denial"
    ):
        return None
    if code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_REQUEST_TIMEOUT"} and http is None:
        return observation(
            code,
            "unknown",
            "bridge_guard",
            "wait_or_contact_operator",
            "Bridge could not verify an upstream response. Wait before retrying.",
            ident,
            attribution="unknown",
            retry="after_delay_once",
            **checks,
        )
    if http is not None and (code, http) not in attempt.canvas_responses:
        if http in {401, 403, 429} or http >= 500:
            return observation(
                "AUTH_ORIGIN_UNKNOWN",
                "unknown",
                "bridge_guard",
                "contact_operator",
                "Bridge lacks a matching current Canvas response. Contact the operator with the request ID.",
                ident,
                attribution="unknown",
                canvas_authentication="unknown",
                **checks,
            )
        return None
    if http == 401 and code in {"UPSTREAM_CREDENTIAL_REJECTED", "UNKNOWN_AUTHORIZATION_FAILURE"}:
        rejected = code == "UPSTREAM_CREDENTIAL_REJECTED"
        return observation(
            code,
            "canvas_api",
            "canvas_response",
            "review_secure_canvas_setup" if rejected else "contact_operator",
            "Canvas rejected the credential. Use the approved Canvas setup or contact its operator."
            if rejected
            else "Canvas returned 401 without a verified cause. Contact the operator.",
            ident,
            canvas_reached="yes",
            canvas_authentication="failed" if rejected else "unknown",
            attribution="confirmed" if rejected else "unknown",
            **checks,
        )
    if http == 403 and code in {"RESOURCE_PERMISSION_DENIED", "UPSTREAM_SCOPE_INSUFFICIENT"}:
        return observation(
            code,
            "canvas_api",
            "canvas_response",
            "review_resource_permission",
            "Canvas denied this resource. Review the permission for this operation.",
            ident,
            canvas_reached="yes",
            canvas_authorization="failed",
            canvas_authentication="unknown",
            **checks,
        )
    if http is not None and (
        code == "UPSTREAM_THROTTLED" or code == "UPSTREAM_UNAVAILABLE" and http >= 500
    ):
        return observation(
            code,
            "canvas_api",
            "canvas_response",
            "wait_or_contact_operator",
            "Canvas reported a capacity or service failure. Wait before retrying.",
            ident,
            canvas_reached="yes",
            retry="after_delay_once",
            **checks,
        )
    return None


def result_observation(tool, result, attempt):
    if tool == "get_connection_status":
        return attempt.auth_observation
    if (
        tool not in {"audit_permission_consistency", "list_courses"}
        or result.status == "ok"
        or attempt.diagnostic
    ):
        return None
    candidates = [result.data]
    if tool == "audit_permission_consistency":
        candidates = [
            row
            for row in result.data.get("checks", [])
            if isinstance(row, dict) and row.get("result") != "not_checked"
        ]
    for row in candidates:
        code, status = row.get("reason_code"), row.get("upstream_http_status")
        if not isinstance(code, str) or (status is not None and type(status) is not int):
            continue
        # An audit's scope check can fail independently of its optional Canvas probe.
        # Describe one observed failure and leave each independent row intact.
        if auth := tool_observation(code, status, attempt, row):
            return auth
    return None
