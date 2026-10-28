"""Synthetic authorization server: no external identity or academic records."""

import asyncio
import logging
from datetime import timedelta
from typing import get_args
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.auth import JWTVerifier
from canvas_bridge.authorization import SCOPES
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.file_delivery import DownloadLogFilter
from canvas_bridge.jobs import enqueue_refresh, work_once
from canvas_bridge.linking import (
    begin_link,
    delete_account,
    digest,
    disconnect,
    exchange,
    finish_link,
    refresh_credential,
    revoke_token,
    terminate_sessions,
)
from canvas_bridge.oauth_security import binding, callback_url, challenge, requested_scopes
from canvas_bridge.policy import Capability, Endpoint, OAuthCapabilities
from canvas_bridge.storage import Connection, Job, OAuthState, PrincipalState
from tests.test_file_delivery import original as original
from tests.test_mcp_contract import running as running
from tests.test_oauth import configure


class OAuthProvider:
    def __init__(self, bridge):
        self.bridge = bridge
        self.codes, self.refresh_tokens, self.requests = {}, set(), []
        self.counter = 0
        self.rotation = False
        self.failure = None
        self.response_patch = {}

    def authorize(self, url):
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        code = f"synthetic-code-{len(self.codes)}"
        self.codes[code] = params
        return code, params

    def handle(self, request):
        self.requests.append(request)
        assert str(request.url) == "https://canvas.synthetic.invalid/login/oauth2/token"
        if self.failure == "network":
            raise httpx.ConnectError("private-fixture-error")
        if self.failure == "invalid_grant":
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "private-fixture-error"}
            )
        values = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if values.get("client_id") != "fixture" or values.get("client_secret") != "fixture-only":
            return httpx.Response(401, json={"error": "invalid_client"})
        if values.get("grant_type") == "authorization_code":
            grant = self.codes.get(values.get("code"))
            if (
                not grant
                or grant["redirect_uri"] != values.get("redirect_uri")
                or grant.get("code_challenge") != challenge(values.get("code_verifier", ""))
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
            del self.codes[values["code"]]
        elif values.get("refresh_token") not in self.refresh_tokens:
            return httpx.Response(400, json={"error": "invalid_grant"})
        elif self.rotation:
            self.refresh_tokens.remove(values["refresh_token"])
        self.counter += 1
        refresh = f"synthetic-refresh-{self.counter}"
        self.refresh_tokens.add(refresh)
        result = {
            "access_token": f"synthetic-access-{self.counter}",
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        result.update(self.response_patch)
        return httpx.Response(200, json=result)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def oauth_provider(bridge, monkeypatch):
    configure(bridge, monkeypatch)
    institution = bridge.registry.entries["synthetic"]
    institution.capabilities = frozenset(get_args(Capability))
    institution.scopes = sorted(set(SCOPES.values()))
    provider = OAuthProvider(bridge)
    monkeypatch.setattr("canvas_bridge.linking.public_client", provider.client)
    return provider


async def linked(bridge, owner, provider):
    code, params = provider.authorize(begin_link(bridge, owner, "synthetic", "browser"))
    result = await finish_link(
        bridge,
        params["state"],
        "browser",
        code,
        callback=params["redirect_uri"],
        expected_owner=owner,
    )
    assert "synthetic-access" not in result.model_dump_json()
    return result.data["connection_id"]


def expire(bridge, ref):
    with bridge.store.transaction() as session:
        session.get(Connection, ref).token_expires_at = utcnow() - timedelta(seconds=1)


async def test_code_interception_pkce_redirect_and_one_use(bridge, owner, oauth_provider):
    code, params = oauth_provider.authorize(begin_link(bridge, owner, "synthetic", "browser"))
    with bridge.store.transaction() as session:
        record = session.get(OAuthState, digest(params["state"]))
        payload = bridge.vault.open(record.payload, owner, record.digest)
        assert payload["verifier"] not in record.payload
    institution = bridge.registry.entries["synthetic"]
    for mutation in (
        {"code_verifier": "stolen-code-without-verifier"},
        {"redirect_uri": "https://evil.invalid/callback"},
    ):
        with pytest.raises(DomainError):
            await exchange(
                institution,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": params["redirect_uri"],
                    "code_verifier": payload["verifier"],
                    **mutation,
                },
                bridge=bridge,
            )
    result = await finish_link(bridge, params["state"], "browser", code)
    assert result.status == "ok"
    with pytest.raises(DomainError):
        await finish_link(bridge, params["state"], "browser", code)
    assert oauth_provider.counter == 1


@pytest.mark.parametrize(
    "attack", ["callback", "owner", "issuer", "capabilities", "redirect_record"]
)
async def test_callback_context_rejected_before_exchange(bridge, owner, oauth_provider, attack):
    code, params = oauth_provider.authorize(begin_link(bridge, owner, "synthetic", "browser"))
    options = {"callback": params["redirect_uri"], "expected_owner": owner}
    if attack == "callback":
        options["callback"] += "/wrong"
    elif attack == "owner":
        options["expected_owner"] = "another-user"
    elif attack == "issuer":
        options["response_issuer"] = "https://another-institution.invalid"
    elif attack == "capabilities":
        bridge.registry.entries["synthetic"].capabilities = frozenset({"courses"})
    else:
        with bridge.store.transaction() as session:
            session.get(
                OAuthState, digest(params["state"])
            ).redirect = "https://evil.invalid/callback"
    with pytest.raises(DomainError):
        await finish_link(bridge, params["state"], "browser", code, **options)
    assert not oauth_provider.requests


async def test_rotation_and_verified_identity(bridge, owner, oauth_provider):
    bridge.registry.entries["synthetic"].oauth.refresh_rotation = "rotating"
    oauth_provider.rotation = True
    ref = await linked(bridge, owner, oauth_provider)
    expire(bridge, ref)
    encrypted = await refresh_credential(bridge, owner, ref)
    secret = bridge.vault.open(encrypted, owner, ref)
    assert secret["refresh_token"] == "synthetic-refresh-2"
    assert "synthetic-refresh-1" not in oauth_provider.refresh_tokens
    with bridge.store.transaction() as session:
        assert session.get(Connection, ref).authentication_state == "verified"
    assert callback_url(bridge, bridge.registry.entries["synthetic"]) in oauth_provider.requests[
        -1
    ].content.decode().replace("%3A", ":").replace("%2F", "/")


@pytest.mark.parametrize("failure", ["invalid_grant", "network", "wrong_user", "missing_rotation"])
async def test_failed_refresh_disables_cache_and_no_resurrection(
    bridge, owner, oauth_provider, failure
):
    if failure == "missing_rotation":
        bridge.registry.entries["synthetic"].oauth.refresh_rotation = "rotating"
    ref = await linked(bridge, owner, oauth_provider)
    courses = await bridge.list_courses(owner, ref)
    course = courses.data["courses"][0]["id"]
    bridge.select_courses(owner, ref, [course], "UTC")
    enqueue_refresh(bridge, owner, ref)
    expire(bridge, ref)
    if failure in {"invalid_grant", "network"}:
        oauth_provider.failure = failure
    elif failure == "wrong_user":
        bridge.synthetic.data["user"]["id"] = 999
    else:
        oauth_provider.response_patch["refresh_token"] = "synthetic-refresh-1"
    with pytest.raises(DomainError):
        await refresh_credential(bridge, owner, ref)
    assert not bridge.authorize(owner, ref, course).allowed
    with bridge.store.transaction() as session:
        conn = session.get(Connection, ref)
        assert conn.entitlement_at is None
        assert conn.authentication_state in {"revoked", "unverified"}
        if failure in {"invalid_grant", "wrong_user"}:
            assert conn.credential is None


@pytest.mark.parametrize(
    "patch",
    [
        {"expires_in": 0},
        {"expires_in": 86400},
        {"expires_in": "3600"},
        {"token_type": "other"},
        {"access_token": ""},
        {"scope": "url:POST|/api/v1/courses"},
    ],
)
async def test_malformed_grants_never_create_connection(bridge, owner, oauth_provider, patch):
    oauth_provider.response_patch = patch
    code, params = oauth_provider.authorize(begin_link(bridge, owner, "synthetic", "browser"))
    with pytest.raises(DomainError):
        await finish_link(bridge, params["state"], "browser", code)
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Connection))


async def test_account_switch_requires_disconnect(bridge, owner, oauth_provider):
    ref = await linked(bridge, owner, oauth_provider)
    with pytest.raises(DomainError, match="Disconnect"):
        begin_link(bridge, owner, "synthetic", "another-browser")
    await disconnect(bridge, owner, ref)
    assert begin_link(bridge, owner, "synthetic", "another-browser")


async def test_scope_and_institution_changes_fail_before_network(bridge, owner, oauth_provider):
    ref = await linked(bridge, owner, oauth_provider)
    with bridge.store.transaction() as session:
        conn = session.get(Connection, ref)
        original = bridge.vault.open(conn.credential, owner, ref)
        assert original["identity_binding"] == binding(bridge, bridge.registry.entries["synthetic"])
    bridge.registry.entries["synthetic"].origin = "https://other-institution.invalid"
    before = len(bridge.synthetic.requests)
    result = await bridge.list_courses(owner, ref)
    assert result.status == "reconnect_required"
    assert len(bridge.synthetic.requests) == before
    assert len(oauth_provider.requests) == 1


async def test_enabled_capabilities_limit_scopes_and_reads(bridge, owner, oauth_provider):
    institution = bridge.registry.entries["synthetic"]
    institution.capabilities = frozenset({"courses", "course_membership"})
    assert set(requested_scopes(institution)) == {
        SCOPES[Endpoint.PROFILE],
        SCOPES[Endpoint.COURSES],
        SCOPES[Endpoint.COURSE],
    }
    ref = await linked(bridge, owner, oauth_provider)
    courses = await bridge.list_courses(owner, ref)
    course = courses.data["courses"][0]["id"]
    bridge.select_courses(owner, ref, [course], "UTC")
    for resource in ("grades", "files", "discussions", "submissions"):
        assert not bridge.authorize(owner, ref, course, resource).allowed


async def test_provider_config_is_not_optional_or_public_desktop_secret(
    bridge, owner, oauth_provider
):
    bridge.registry.entries["synthetic"].oauth = None
    with pytest.raises(DomainError):
        begin_link(bridge, owner, "synthetic", "browser")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OAuthCapabilities(
            client_type="public_desktop",
            pkce="S256",
            refresh_rotation="stable",
            granular_scopes=True,
            documentation_reference="fixture",
        )


async def test_application_tokens_are_revoked_without_other_user_impact(
    bridge, owner, token_factory
):
    verifier = JWTVerifier(bridge.settings, bridge.store)
    old = token_factory()
    other = token_factory(sub="other-user")
    accepted = await verifier.verify_token(old)
    assert accepted and await verifier.verify_token(other)
    with bridge.store.transaction() as session:
        generation = bridge.store.principal(session, owner).generation
    terminate_sessions(bridge, owner, generation)
    assert await verifier.verify_token(old) is None
    assert await verifier.verify_token(other)
    with pytest.raises(DomainError):
        verifier.require_current(accepted)
    with bridge.store.transaction() as session:
        assert session.get(PrincipalState, owner).tokens_valid_after


async def test_deletion_revokes_application_token(bridge, owner, token_factory):
    verifier = JWTVerifier(bridge.settings, bridge.store)
    token = token_factory()
    await delete_account(bridge, owner)
    assert await verifier.verify_token(token) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "upstream-canvas"},
        {"iss": "https://canvas.synthetic.invalid"},
        {"exp": 1},
        {"exp": utcnow() + timedelta(days=1)},
    ],
)
async def test_application_issuer_audience_expiry_lifetime(bridge, token_factory, overrides):
    assert (
        await JWTVerifier(bridge.settings, bridge.store).verify_token(token_factory(**overrides))
        is None
    )


async def test_pending_and_running_job_stops_on_disconnect(bridge, owner, seeded, monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def pending(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(bridge, "refresh", pending)
    enqueue_refresh(bridge, owner, seeded)
    task = asyncio.create_task(work_once(bridge))
    await asyncio.wait_for(started.wait(), 2)
    await disconnect(bridge, owner, seeded)
    await asyncio.wait_for(task, 2)
    assert stopped.is_set()
    with bridge.store.transaction() as session:
        assert not session.scalar(select(Job))


async def test_revocation_network_failure_is_not_confirmation(bridge, oauth_provider):
    bridge.synthetic = None
    oauth_provider.failure = "network"
    assert (
        await revoke_token(
            bridge,
            "synthetic",
            {
                "access_token": "private-fixture",
                "upstream_origin": "https://canvas.synthetic.invalid",
            },
        )
        == "not_confirmed"
    )


async def test_changed_origin_never_receives_revocation_bearer(bridge, oauth_provider):
    bridge.synthetic = None
    result = await revoke_token(
        bridge,
        "synthetic",
        {
            "access_token": "private-fixture",
            "upstream_origin": "https://different-origin.invalid",
        },
    )
    assert result == "not_confirmed" and not oauth_provider.requests


def test_oauth_callback_query_secrets_are_not_access_logged():
    for path in ("/settings/callback?code=secret", "/settings/canvas/callback/key?state=secret"):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, path, (), None)
        assert not DownloadLogFilter().filter(record)


async def test_unavailable_pkce_and_unscoped_provider_require_explicit_review(
    bridge, owner, oauth_provider
):
    institution = bridge.registry.entries["synthetic"]
    institution.oauth.pkce = "unsupported"
    institution.oauth.granular_scopes = False
    params = parse_qs(urlsplit(begin_link(bridge, owner, "synthetic", "browser")).query)
    assert "code_challenge" not in params and "scope" not in params
    assert params["state"] and params["redirect_uri"]
    assert requested_scopes(institution) == []


async def test_failed_permission_refresh_removes_previous_cache_lease(
    bridge, owner, seeded, monkeypatch
):
    from canvas_bridge.canvas import Collection

    _, courses = bridge.selected(owner, seeded)
    assert bridge.authorize(owner, seeded, courses[0].id).allowed

    async def unavailable(*args, **kwargs):
        return Collection(complete=False, failure="retry_later")

    monkeypatch.setattr("canvas_bridge.canvas.CanvasClient.collection", unavailable)
    assert (await bridge.list_courses(owner, seeded)).status == "partial_data"
    assert not bridge.authorize(owner, seeded, courses[0].id).allowed
    with bridge.store.transaction() as session:
        assert session.get(Connection, seeded).entitlement_at is None


async def test_disconnect_invalidates_and_removes_temporary_file(bridge, owner, seeded, original):
    _, file, _ = original
    prepared = await bridge.original_files.prepare(owner, seeded, file)
    delivery = bridge.original_files.records[prepared.data["delivery_id"]]
    assert delivery.path.exists()
    await disconnect(bridge, owner, seeded)
    assert delivery.revoked and not delivery.path.exists()
    assert delivery.id not in bridge.original_files.records
    assert not bridge.original_files.capabilities


@pytest.mark.contract
async def test_revocation_rejected_on_existing_http_connection(
    running, bridge, owner, token_factory
):
    raw = token_factory()
    headers = {"Authorization": "Bearer " + raw, "Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(headers=headers) as client:
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        assert (await client.post(running + "/mcp", json=request)).status_code == 200
        terminate_sessions(bridge, owner, 0)
        response = await client.post(running + "/mcp", json=request)
        assert response.status_code == 401 and raw not in response.text
        other = await client.post(
            running + "/mcp",
            json=request,
            headers={"Authorization": "Bearer " + token_factory(sub="another-account")},
        )
        assert other.status_code == 200


@pytest.mark.contract
async def test_midflight_session_revocation_blocks_mcp_release(
    running, bridge, owner, token_factory, monkeypatch
):
    original_status = bridge.connection_status

    def revoke_before_release(principal):
        result = original_status(principal)
        terminate_sessions(bridge, owner, 0)
        result.summary = "PRIVATE-REVOKED-RESULT"
        return result

    monkeypatch.setattr(bridge, "connection_status", revoke_before_release)
    async with httpx.AsyncClient(
        headers={
            "Authorization": "Bearer " + token_factory(),
            "Accept": "application/json, text/event-stream",
        }
    ) as client:
        response = await client.post(
            running + "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_connection_status", "arguments": {}},
            },
        )
        assert response.json()["result"]["structuredContent"]["status"] == "permission_denied"
        assert "PRIVATE-REVOKED-RESULT" not in response.text


def test_identity_migration_and_old_credentials_remain_unverified(tmp_path, bridge):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from canvas_bridge.storage import Store

    config = Config("alembic.ini")
    config.attributes["database_url"] = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    command.upgrade(config, "head")
    store = Store(config.attributes["database_url"])
    store.protect(bridge.vault)
    try:
        columns = {c["name"] for c in inspect(store.engine).get_columns("principal_states")}
        assert "tokens_valid_after" in columns
        with store.transaction() as session:
            conn = Connection(id="old", owner="fixture", institution="fixture", canvas_user="101")
            session.add(conn)
            session.flush()
            assert conn.authentication_state == "unverified"
    finally:
        store.close()
