"""Canvas authorization lifecycle; never used to authorize academic writes."""

import asyncio
import hashlib
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, select

from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError, Result, opaque_id, utcnow
from canvas_bridge.network import GuardedHTTP, infrastructure_http, public_client
from canvas_bridge.oauth_security import (
    binding,
    callback_url,
    challenge,
    requested_scopes,
    require_oauth,
    token_response,
)
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import BrowserSession, Connection, OAuthState, aware


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def credentials(institution) -> tuple[str, str]:
    require_oauth(institution)
    client_id = os.environ.get(institution.client_id_env or "")
    client_secret = os.environ.get(institution.client_secret_env or "")
    if not client_id or not client_secret:
        raise DomainError(
            "unsupported_feature", "Institution OAuth configuration is not available."
        )
    return client_id, client_secret


def begin_link(
    bridge,
    owner: str,
    institution_id: str,
    browser_nonce: str,
    expected_generation: int | None = None,
) -> str:
    if bridge.settings.profile == "personal":
        raise DomainError("unsupported_feature", "Private testing uses operator-only setup.")
    institution = bridge.registry.require(institution_id)
    if bridge.settings.profile == "synthetic":
        raise DomainError("unsupported_feature", "Live linking is disabled in synthetic mode.")
    bridge.require_policy(institution_id, {"identity"}, activity="link")
    client_id, _ = credentials(institution)
    scopes = requested_scopes(institution)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48) if institution.oauth.pkce == "S256" else None
    callback = callback_url(bridge, institution)
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        if expected_generation is not None and principal.generation != expected_generation:
            raise DomainError("permission_denied", "Sign in again before linking an account.")
        from canvas_bridge.personal import no_existing_connection

        no_existing_connection(session, owner, institution_id)
        session.add(
            OAuthState(
                digest=digest(state),
                owner=owner,
                institution=institution_id,
                redirect=callback,
                browser_digest=digest(browser_nonce),
                expires_at=utcnow() + timedelta(minutes=10),
                generation=principal.generation,
                payload=bridge.vault.seal(
                    {"verifier": verifier, "binding": binding(bridge, institution)},
                    owner,
                    digest(state),
                ),
            )
        )
    return (
        institution.origin
        + "/login/oauth2/auth?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": callback,
                "state": state,
                **({"scope": " ".join(scopes)} if scopes else {}),
                **(
                    {"code_challenge": challenge(verifier), "code_challenge_method": "S256"}
                    if verifier
                    else {}
                ),
            }
        )
    )


async def exchange(
    institution, data: dict, http: httpx.AsyncClient | None = None, *, bridge=None
) -> dict:
    if bridge is None or bridge.settings.profile == "synthetic":
        raise DomainError(
            "permission_denied",
            "Live OAuth requires a policy-bound service.",
            reason_code="POLICY_CONTEXT_REQUIRED",
        )
    activity = "refresh" if data.get("grant_type") == "refresh_token" else "link"
    endpoint = institution.origin + "/login/oauth2/token"
    expected_binding = binding(bridge, institution)
    origin = institution.origin

    def check(method, url):
        if method != "POST" or url != endpoint or binding(bridge, institution) != expected_binding:
            raise DomainError("permission_denied", "Unapproved credential endpoint.")
        bridge.require_policy(institution.id, {"identity"}, activity=activity)

    check("POST", endpoint)
    client_id, client_secret = credentials(institution)
    client = GuardedHTTP(http or public_client(), check)
    try:
        async with client.stream(
            "POST",
            endpoint,
            data={
                **data,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            follow_redirects=False,
        ) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 32_000:
                    raise DomainError("reconnect_required", "Invalid authorization response.")
            import json

            result = json.loads(raw)
            if response.status_code != 200:
                invalid = isinstance(result, dict) and result.get("error") == "invalid_grant"
                raise DomainError(
                    "reconnect_required",
                    "Canvas authorization was not completed.",
                    reason_code="OAUTH_GRANT_REJECTED" if invalid else "UPSTREAM_AUTH_UNVERIFIED",
                )
            check("POST", endpoint)
            return {**token_response(result, institution), "upstream_origin": origin}
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError(
            "reconnect_required", "Canvas authorization is temporarily unavailable."
        ) from exc
    finally:
        if http is None:
            await client.aclose()


async def finish_link(
    bridge,
    state: str,
    browser_nonce: str,
    code: str | None,
    *,
    callback: str | None = None,
    response_issuer: str | None = None,
    expected_owner: str | None = None,
) -> Result:
    if bridge.settings.profile == "personal":
        raise DomainError("unsupported_feature", "Private testing uses operator-only setup.")
    with bridge.store.transaction() as session:
        hint = session.get(OAuthState, digest(state))
        if hint is None or hint.institution == "__identity__":
            raise DomainError("permission_denied", "Authorization session expired or is invalid.")
        principal = bridge.store.principal(session, hint.owner)
        institution = bridge.registry.require(hint.institution)
        record = session.scalar(
            select(OAuthState).where(OAuthState.digest == digest(state)).with_for_update()
        )
        if (
            record is None
            or aware(record.expires_at) < utcnow()
            or not secrets.compare_digest(record.browser_digest, digest(browser_nonce))
            or record.generation != principal.generation
            or record.redirect != callback_url(bridge, institution)
            or (callback is not None and callback != record.redirect)
            or (expected_owner is not None and expected_owner != record.owner)
            or (response_issuer is not None and response_issuer != institution.origin)
            or (
                institution.oauth and institution.oauth.issuer_parameter and response_issuer is None
            )
        ):
            raise DomainError("permission_denied", "Authorization session expired or is invalid.")
        owner, institution_id, redirect = record.owner, record.institution, record.redirect
        generation = record.generation
        payload = bridge.vault.open(record.payload, record.owner, record.digest)
        if payload.get("binding") != binding(bridge, institution):
            raise DomainError("permission_denied", "OAuth configuration changed; start again.")
        session.delete(record)
    if not code:
        return Result(
            status="needs_input", summary="Canvas authorization cancelled; no connection created."
        )
    institution = bridge.registry.require(institution_id)
    bridge.require_policy(institution_id, {"identity"}, activity="link")
    token = await exchange(
        institution,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            **({"code_verifier": payload["verifier"]} if payload.get("verifier") else {}),
        },
        bridge=bridge,
    )
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        cancelled = principal.generation != generation
    if cancelled:
        remote = await revoke_token(bridge, institution_id, token)
        return Result(
            status="permission_denied",
            summary="Authorization was cancelled by account deletion.",
            data={"connection_created": False, "remote_revocation": remote},
        )
    http = bridge.synthetic.client() if bridge.synthetic else None
    client = CanvasClient(institution, token["access_token"], bridge.settings, http)
    client.authorize = link_profile_authorizer(bridge, owner, institution_id, generation)
    try:
        profile = await client.one(Endpoint.PROFILE)
        from canvas_bridge.policy import source_id

        canvas_user = source_id(profile.get("id"))
    except BaseException:
        await revoke_token(bridge, institution_id, token)
        raise
    finally:
        await client.close()
        if http:
            await http.aclose()
    if payload["binding"] != binding(bridge, institution):
        await revoke_token(bridge, institution_id, token)
        raise DomainError("reconnect_required", "Connection configuration changed during linking.")
    token["identity_binding"] = binding(bridge, institution)
    connection_id = opaque_id()
    # Reconnect creates a new connection/epoch; old tombstones remain effective.
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        cancelled = principal.generation != generation
        if not cancelled:
            # Serialize concurrent link completions; switching requires disconnect.
            if session.scalar(
                select(Connection.id).where(
                    Connection.owner == owner,
                    Connection.institution == institution_id,
                    Connection.state == "active",
                )
            ):
                cancelled = True
        if not cancelled:
            session.add(
                Connection(
                    id=connection_id,
                    owner=owner,
                    institution=institution_id,
                    canvas_user=canvas_user,
                    authentication_state="verified",
                    credential=bridge.vault.seal(token, owner, connection_id),
                    token_expires_at=utcnow()
                    + timedelta(seconds=max(0, int(token.get("expires_in", 3600)))),
                )
            )
    if cancelled:
        # Do not retain a newly returned grant after deletion. Revoke separately
        # and report uncertainty instead of resurrecting the local connection.
        remote = await revoke_token(bridge, institution_id, token)
        return Result(
            status="permission_denied",
            summary="Authorization was cancelled because the account or active connection changed.",
            data={"connection_created": False, "remote_revocation": remote},
        )
    return Result(
        summary="Canvas authorization completed. Select courses before retrieving work.",
        data={
            "connection_id": connection_id,
            "institution": institution_id,
        },
    )


async def refresh_credential(bridge, owner: str, ref: str) -> str:
    bridge.connection_policy(owner, ref, {"identity"}, activity="refresh")
    now = utcnow()
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, ref, lock=True)
        if conn.token_expires_at and aware(conn.token_expires_at) > now + timedelta(seconds=60):
            return conn.credential
        if conn.refresh_lease_until and aware(conn.refresh_lease_until) > now:
            raise DomainError("retry_later", "Authorization refresh is already in progress.")
        conn.refresh_lease_until = now + timedelta(seconds=30)
        epoch, encrypted, institution_id = conn.epoch, conn.credential, conn.institution
        expected_user, lease = conn.canvas_user, conn.refresh_lease_until
    institution = bridge.registry.require(institution_id)
    secret = bridge.vault.open(encrypted, owner, ref)
    renewed = None
    try:
        oauth = require_oauth(institution)
        if secret.get("identity_binding") != binding(bridge, institution):
            raise DomainError("reconnect_required", "Connection configuration changed; reconnect.")
        if not secret.get("refresh_token"):
            raise DomainError("reconnect_required", "Reconnect this account to renew access.")
        renewed = await exchange(
            institution,
            {
                "grant_type": "refresh_token",
                "refresh_token": secret["refresh_token"],
                "redirect_uri": callback_url(bridge, institution),
            },
            bridge=bridge,
        )
        if oauth.refresh_rotation == "rotating" and (
            not renewed.get("refresh_token") or renewed["refresh_token"] == secret["refresh_token"]
        ):
            raise DomainError("reconnect_required", "Refresh-token rotation was not confirmed.")
        renewed.setdefault("refresh_token", secret["refresh_token"])

        def check_profile(endpoint, ids, resource=None):
            if endpoint != Endpoint.PROFILE:
                raise DomainError("permission_denied", "Refresh may only verify the current user.")
            with bridge.store.transaction() as session:
                current = bridge.store.connection(session, owner, ref)
                if current.epoch != epoch or current.credential != encrypted:
                    raise DomainError("permission_denied", "Connection changed during renewal.")
            bridge.require_policy(institution_id, {"identity"}, activity="refresh")

        http = bridge.synthetic.client() if bridge.synthetic else None
        client = CanvasClient(institution, renewed["access_token"], bridge.settings, http)
        client.authorize = check_profile
        try:
            profile = await client.one(Endpoint.PROFILE)
            from canvas_bridge.policy import source_id

            if source_id(profile.get("id")) != expected_user:
                raise DomainError(
                    "reconnect_required",
                    "Upstream account changed during renewal.",
                    reason_code="OAUTH_IDENTITY_MISMATCH",
                )
        finally:
            await client.close()
            if http:
                await http.aclose()
        renewed["identity_binding"] = binding(bridge, institution)
        if renewed["identity_binding"] != secret["identity_binding"]:
            raise DomainError(
                "reconnect_required", "Connection configuration changed during renewal."
            )
        sealed = bridge.vault.seal(renewed, owner, ref)
        with bridge.store.transaction() as session:
            conn = bridge.store.connection(session, owner, ref, lock=True)
            if (
                conn.epoch != epoch
                or conn.credential != encrypted
                or not conn.refresh_lease_until
                or aware(conn.refresh_lease_until) != aware(lease)
                or aware(lease) <= utcnow()
            ):
                raise DomainError("source_changed", "Connection changed during token renewal.")
            conn.credential = sealed
            conn.authentication_state = "verified"
            conn.entitlement_at = None
            conn.token_expires_at = utcnow() + timedelta(
                seconds=max(0, int(renewed.get("expires_in", 3600)))
            )
            conn.refresh_lease_until = None
        return sealed
    except BaseException as exc:
        if renewed:
            await revoke_token(bridge, institution_id, renewed)
        fatal = getattr(exc, "reason_code", None) in {
            "OAUTH_GRANT_REJECTED",
            "OAUTH_IDENTITY_MISMATCH",
        }
        with bridge.store.transaction() as session:
            conn = session.scalar(
                select(Connection).where(Connection.id == ref, Connection.owner == owner)
            )
            if conn and conn.epoch == epoch and conn.credential == encrypted:
                conn.refresh_lease_until = None
                conn.authentication_state = "unverified"
                conn.entitlement_at = None
                conn.epoch += 1
        bridge.invalidate_access(owner, ref)
        if fatal:
            await disconnect(bridge, owner, ref)
        raise


async def revoke_token(bridge, institution_id: str, secret: dict) -> str:
    if bridge.synthetic:
        return "not_applicable"
    try:
        institution = bridge.registry.require(
            institution_id, personal=bridge.settings.profile == "personal"
        )
        if secret.get("upstream_origin") != institution.origin:
            # A changed registry domain must never receive an older bearer token.
            return "not_confirmed"
        async with public_client() as client:
            endpoint = institution.origin + "/login/oauth2/token"
            # Revocation is credential cleanup, never data retrieval or a fallback.
            guarded = infrastructure_http(client, method="DELETE", url=endpoint)
            async with guarded.stream(
                "DELETE",
                institution.origin + "/login/oauth2/token",
                headers={"Authorization": f"Bearer {secret['access_token']}"},
                follow_redirects=False,
            ) as response:
                return "confirmed" if response.status_code in {200, 204} else "not_confirmed"
    except (DomainError, httpx.HTTPError, ValueError):
        return "not_confirmed"


def link_profile_authorizer(bridge, owner, institution_id, generation):
    def authorize(endpoint, ids, resource=None):
        if endpoint != Endpoint.PROFILE:
            raise DomainError("permission_denied", "Linking may only verify the current user.")
        with bridge.store.transaction() as session:
            principal = bridge.store.principal(session, owner)
            if principal.generation != generation:
                raise DomainError("permission_denied", "Account deletion cancelled linking.")
        bridge.require_policy(institution_id, {"identity"}, activity="link")

    return authorize


async def disconnect(bridge, owner: str, ref: str) -> Result:
    from canvas_bridge.lifecycle import journal_delete

    with bridge.store.transaction() as session:
        row = session.scalar(
            select(Connection).where(Connection.owner == owner, Connection.id == ref)
        )
        if row is None:
            raise DomainError("permission_denied", "Connection unavailable.")
        epoch = row.epoch + 1
    # Journal is durably flushed before removal, and must live outside backup rollback.
    journal_delete(
        bridge.settings.deletion_journal,
        bridge.vault.key,
        ref,
        epoch,
        now=bridge.retention.clock(),
    )
    outcome = bridge.store.disconnect(owner, ref)
    bridge.invalidate_access(owner, ref)
    from canvas_bridge.worker_storage import pending

    temporary = pending(
        owner, ref, namespace=bridge.processing_namespace
    ) + bridge.original_files.pending_cleanup(owner, ref)
    receipt = bridge.retention.receipt(owner, "disconnect", outcome["deleted_rows"], temporary)
    remote = "not_applicable" if bridge.synthetic else "not_confirmed"
    if not bridge.synthetic and outcome["credential"]:
        try:
            secret = bridge.vault.open(outcome["credential"], owner, ref)
            remote = await revoke_token(bridge, outcome["institution"], secret)
        except Exception:
            remote = "not_confirmed"
    return Result(
        summary="Local access disabled and active connection data removed.",
        data={
            "local_access": "disabled",
            "active_store": "purged",
            "deletion_epoch": outcome["epoch"],
            "remote_revocation": remote,
            "local_deletion_receipt": receipt,
            "calendar_events": "unchanged",
            "independent_copies": "ChatGPT conversations, prior exports and provider records are controlled separately.",
        },
    )


def terminate_sessions(bridge, owner, generation):
    """Revoke existing application JWTs and browsers using the existing principal fence."""
    from canvas_bridge.lifecycle import journal_delete
    from canvas_bridge.storage import Job

    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        if principal.generation != generation:
            raise DomainError("permission_denied", "This settings session was revoked.")
        journal_delete(
            bridge.settings.deletion_journal,
            bridge.vault.key,
            "principal:" + owner,
            principal.generation + 1,
            now=bridge.retention.clock(),
        )
        principal.generation += 1
        principal.tokens_valid_after = utcnow()
        for conn in session.scalars(
            select(Connection).where(Connection.owner == owner).with_for_update()
        ):
            conn.epoch += 1
            bridge.invalidate_access(owner, conn.id)
        for cls in (BrowserSession, OAuthState, Job):
            session.execute(delete(cls).where(cls.owner == owner))


async def delete_account(bridge, owner: str, expected_generation: int | None = None) -> Result:
    from canvas_bridge.lifecycle import journal_delete
    from canvas_bridge.storage import IndependentResource

    grants, counts = [], {}
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        if expected_generation is not None and principal.generation != expected_generation:
            raise DomainError("permission_denied", "This settings session is no longer valid.")
        connections = list(
            session.scalars(
                select(Connection)
                .where(Connection.owner == owner)
                .order_by(Connection.id)
                .with_for_update()
            )
        )
        # One owner-level journal fence also covers pending grants with no connection yet.
        journal_delete(
            bridge.settings.deletion_journal,
            bridge.vault.key,
            "principal:" + owner,
            principal.generation + 1,
            now=bridge.retention.clock(),
        )
        principal.generation += 1
        principal.tokens_valid_after = utcnow()
        for row in connections:
            outcome = bridge.store.disconnect_in_session(session, row)
            for name, count in outcome["deleted_rows"].items():
                counts[name] = counts.get(name, 0) + count
            bridge.invalidate_access(owner, row.id)
            if outcome["credential"]:
                grants.append((row.id, outcome))
            session.delete(row)
        session.execute(delete(OAuthState).where(OAuthState.owner == owner))
        session.execute(delete(BrowserSession).where(BrowserSession.owner == owner))
        for independent in session.scalars(
            select(IndependentResource).where(
                IndependentResource.owner == owner,
                IndependentResource.kind != "institutional_lineage",
            )
        ):
            from canvas_bridge.worker_storage import invalidate

            invalidate(owner, independent.id, namespace=bridge.processing_namespace)
            session.delete(independent)
    from canvas_bridge.worker_storage import pending

    temporary = sum(
        pending(owner, row.id, namespace=bridge.processing_namespace) for row in connections
    ) + bridge.original_files.pending_cleanup(owner)
    receipt = bridge.retention.receipt(owner, "delete_account", counts, temporary)
    # Local removal commits for every institution before attempting any network operation.
    outcomes = []
    deadline = asyncio.get_running_loop().time() + bridge.settings.refresh_budget_seconds
    for ref, grant in grants:
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                status = "not_confirmed"
            else:
                async with asyncio.timeout(remaining):
                    token = bridge.vault.open(grant["credential"], owner, ref)
                    status = await revoke_token(bridge, grant["institution"], token)
        except Exception:
            status = "not_confirmed"
        outcomes.append({"institution": grant["institution"], "remote_revocation": status})
    return Result(
        summary="All local account records deleted; access and pending linking sessions stopped.",
        data={
            "local_access": "disabled",
            "active_store": "purged",
            "connection_count": len(connections),
            "local_deletion_receipt": receipt,
            "remote_revocations": outcomes,
            "retained": "Minimal principal-generation and deletion fences needed to prevent restoration.",
            "independent_copies": "ChatGPT conversations, institution records and downloaded copies are controlled separately.",
        },
    )
