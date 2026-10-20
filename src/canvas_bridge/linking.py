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
from canvas_bridge.network import public_client
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import BrowserSession, Connection, OAuthState, aware


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def credentials(institution) -> tuple[str, str]:
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
    institution = bridge.registry.require(institution_id)
    if bridge.settings.profile == "synthetic":
        raise DomainError("unsupported_feature", "Live linking is disabled in synthetic mode.")
    client_id, _ = credentials(institution)
    if not institution.scopes or any(
        not scope.startswith("url:GET|") for scope in institution.scopes
    ):
        raise DomainError("unsupported_feature", "Reviewed academic read scopes are required.")
    state = secrets.token_urlsafe(32)
    callback = bridge.settings.resource_url.rstrip("/") + "/settings/canvas/callback"
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        if expected_generation is not None and principal.generation != expected_generation:
            raise DomainError("permission_denied", "Sign in again before linking an account.")
        session.add(
            OAuthState(
                digest=digest(state),
                owner=owner,
                institution=institution_id,
                redirect=callback,
                browser_digest=digest(browser_nonce),
                expires_at=utcnow() + timedelta(minutes=10),
                generation=principal.generation,
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
                "scope": " ".join(institution.scopes),
            }
        )
    )


async def exchange(institution, data: dict, http: httpx.AsyncClient | None = None) -> dict:
    client_id, client_secret = credentials(institution)
    client = http or public_client()
    try:
        async with client.stream(
            "POST",
            institution.origin + "/login/oauth2/token",
            data={
                **data,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise DomainError("reconnect_required", "Canvas authorization was not completed.")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 32_000:
                    raise DomainError("reconnect_required", "Invalid authorization response.")
            import json

            result = json.loads(raw)
            if not isinstance(result.get("access_token"), str):
                raise DomainError("reconnect_required", "Canvas did not return an access grant.")
            return {
                k: result[k] for k in ("access_token", "refresh_token", "expires_in") if k in result
            }
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError(
            "reconnect_required", "Canvas authorization is temporarily unavailable."
        ) from exc
    finally:
        if http is None:
            await client.aclose()


async def finish_link(bridge, state: str, browser_nonce: str, code: str | None) -> Result:
    with bridge.store.transaction() as session:
        hint = session.get(OAuthState, digest(state))
        if hint is None or hint.institution == "__identity__":
            raise DomainError("permission_denied", "Authorization session expired or is invalid.")
        principal = bridge.store.principal(session, hint.owner)
        record = session.scalar(
            select(OAuthState).where(OAuthState.digest == digest(state)).with_for_update()
        )
        if (
            record is None
            or aware(record.expires_at) < utcnow()
            or not secrets.compare_digest(record.browser_digest, digest(browser_nonce))
            or record.generation != principal.generation
        ):
            raise DomainError("permission_denied", "Authorization session expired or is invalid.")
        owner, institution_id, redirect = record.owner, record.institution, record.redirect
        generation = record.generation
        session.delete(record)
    if not code:
        return Result(
            status="needs_input", summary="Canvas authorization cancelled; no connection created."
        )
    institution = bridge.registry.require(institution_id)
    token = await exchange(
        institution,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
        },
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
    client = CanvasClient(institution, token["access_token"], bridge.settings)
    try:
        profile = await client.one(Endpoint.PROFILE)
    finally:
        await client.close()
    from canvas_bridge.policy import source_id

    canvas_user = source_id(profile["id"])
    connection_id = opaque_id()
    # Reconnect creates a new connection/epoch; old tombstones remain effective.
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        cancelled = principal.generation != generation
        if not cancelled:
            session.add(
                Connection(
                    id=connection_id,
                    owner=owner,
                    institution=institution_id,
                    canvas_user=canvas_user,
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
            summary="Authorization was cancelled by account deletion.",
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
    now = utcnow()
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, ref, lock=True)
        if conn.token_expires_at and aware(conn.token_expires_at) > now + timedelta(seconds=60):
            return conn.credential
        if conn.refresh_lease_until and aware(conn.refresh_lease_until) > now:
            raise DomainError("retry_later", "Authorization refresh is already in progress.")
        conn.refresh_lease_until = now + timedelta(seconds=30)
        epoch, encrypted, institution_id = conn.epoch, conn.credential, conn.institution
    institution = bridge.registry.require(institution_id)
    secret = bridge.vault.open(encrypted, owner, ref)
    try:
        if not secret.get("refresh_token"):
            raise DomainError("reconnect_required", "Reconnect this account to renew access.")
        renewed = await exchange(
            institution,
            {
                "grant_type": "refresh_token",
                "refresh_token": secret["refresh_token"],
            },
        )
        renewed.setdefault("refresh_token", secret["refresh_token"])
        sealed = bridge.vault.seal(renewed, owner, ref)
        with bridge.store.transaction() as session:
            conn = bridge.store.connection(session, owner, ref, lock=True)
            if conn.epoch != epoch:
                raise DomainError("source_changed", "Connection changed during token renewal.")
            conn.credential = sealed
            conn.token_expires_at = utcnow() + timedelta(
                seconds=max(0, int(renewed.get("expires_in", 3600)))
            )
            conn.refresh_lease_until = None
        return sealed
    except Exception:
        with bridge.store.transaction() as session:
            conn = session.scalar(
                select(Connection).where(Connection.id == ref, Connection.owner == owner)
            )
            if conn and conn.epoch == epoch:
                conn.refresh_lease_until = None
        raise


async def revoke_token(bridge, institution_id: str, secret: dict) -> str:
    if bridge.synthetic:
        return "not_applicable"
    try:
        institution = bridge.registry.require(institution_id)
        async with public_client() as client:
            async with client.stream(
                "DELETE",
                institution.origin + "/login/oauth2/token",
                headers={"Authorization": f"Bearer {secret['access_token']}"},
                follow_redirects=False,
            ) as response:
                return "confirmed" if response.status_code in {200, 204} else "not_confirmed"
    except (DomainError, httpx.HTTPError, ValueError):
        return "not_confirmed"


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
        bridge.settings.vault_key_file.read_bytes(),
        ref,
        epoch,
    )
    outcome = bridge.store.disconnect(owner, ref)
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
            "calendar_events": "unchanged",
            "independent_copies": "ChatGPT conversations, prior exports and provider records are controlled separately.",
        },
    )


async def delete_account(bridge, owner: str, expected_generation: int | None = None) -> Result:
    from canvas_bridge.lifecycle import journal_delete

    grants = []
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
            bridge.settings.vault_key_file.read_bytes(),
            "principal:" + owner,
            principal.generation + 1,
        )
        principal.generation += 1
        for row in connections:
            outcome = bridge.store.disconnect_in_session(session, row)
            if outcome["credential"]:
                grants.append((row.id, outcome))
            session.delete(row)
        session.execute(delete(OAuthState).where(OAuthState.owner == owner))
        session.execute(delete(BrowserSession).where(BrowserSession.owner == owner))
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
            "remote_revocations": outcomes,
            "retained": "Minimal principal-generation and deletion fences needed to prevent restoration.",
            "independent_copies": "ChatGPT conversations, institution records and downloaded copies are controlled separately.",
        },
    )
