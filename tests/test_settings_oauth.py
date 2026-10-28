"""Browser OAuth interop and mix-up defenses without a live identity provider."""

import base64
import hashlib
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from canvas_bridge.app import create_app
from canvas_bridge.linking import digest
from canvas_bridge.storage import OAuthState


@pytest.mark.parametrize("path", ["", "/", "/private", "/private/"])
@pytest.mark.parametrize("read_only", [True, False])
async def test_T12_oauth_discovery_preserves_exact_resource_and_issuer(
    settings, bridge, path, read_only
):
    settings.resource_url = "https://resource.invalid" + path
    settings.issuer_url = "https://issuer.invalid" + path
    settings.mcp_read_only = read_only
    metadata_path = "/.well-known/oauth-protected-resource" + (path if path != "/" else "")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url="https://resource.invalid",
    ) as client:
        response = await client.get(metadata_path, headers={"Origin": "https://client.invalid"})
        assert response.status_code == 200
        assert response.json() == {
            "resource": settings.resource_url,
            "authorization_servers": [settings.issuer_url],
            "scopes_supported": ["academic:read"]
            if read_only
            else ["academic:read", "preferences:write"],
            "bearer_methods_supported": ["header"],
        }
        assert response.headers["access-control-allow-origin"] == "*"
        preflight = await client.options(
            metadata_path,
            headers={
                "Origin": "https://client.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "*"
        denied = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert denied.status_code == 401
        assert (
            'resource_metadata="https://resource.invalid' + metadata_path + '"'
            in denied.headers["www-authenticate"]
        )


@pytest.fixture
def identity_exchange(settings, token_factory, monkeypatch):
    settings.browser_client_id = "settings-fixture"
    settings.browser_authorization_url = settings.issuer_url + "/oauth2/authorize"
    settings.browser_token_url = settings.issuer_url + "/oauth2/token"
    calls = []

    async def exchange(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": token_factory()})

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as http:
            yield http

    monkeypatch.setattr("canvas_bridge.settings_ui.public_client", client)
    return calls


async def start(client):
    response = await client.get("/settings/login")
    assert response.status_code == 307
    values = parse_qs(urlsplit(response.headers["location"]).query)
    return values, urlsplit(values["redirect_uri"][0]).path


@pytest.mark.parametrize("require_issuer", [True, False])
async def test_T12_T19_browser_oauth_pkce_exact_redirect_and_replay(
    bridge, settings, identity_exchange, require_issuer
):
    settings.browser_require_issuer_parameter = require_issuer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        params = {"state": values["state"][0], "code": "fixture-code"}
        if require_issuer:
            params["iss"] = settings.issuer_url
        else:
            assert callback.endswith(hashlib.sha256(settings.issuer_url.encode()).hexdigest())
        result = await client.get(callback, params=params)
        assert result.status_code == 303
        assert "bridge_session" in result.cookies
        assert len(identity_exchange) == 1
        exchange = parse_qs(identity_exchange[0].content.decode())
        assert str(identity_exchange[0].url) == settings.browser_token_url
        assert exchange["redirect_uri"] == values["redirect_uri"]
        assert exchange["resource"] == values["resource"]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"][0].encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert values["code_challenge"] == [challenge]
        assert values["code_challenge_method"] == ["S256"]
        assert (await client.get(callback, params=params)).status_code == 403
        assert len(identity_exchange) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_issuer",
        "empty_issuer",
        "duplicate_issuer",
        "duplicate_code",
        "unbound_path",
        "wrong_path",
        "wrong_cookie",
        "changed_issuer",
        "changed_token_url",
        "changed_client",
        "changed_resource",
        "changed_mode",
    ],
)
async def test_T12_T19_browser_bound_callback_rejects_mixup_before_exchange(
    bridge, settings, identity_exchange, attack
):
    settings.browser_require_issuer_parameter = False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        params = [("state", values["state"][0]), ("code", "fixture-code")]
        if attack == "wrong_issuer":
            params.append(("iss", "https://wrong.invalid"))
        elif attack == "empty_issuer":
            params.append(("iss", ""))
        elif attack == "duplicate_issuer":
            params.extend([("iss", "https://wrong.invalid"), ("iss", settings.issuer_url)])
        elif attack == "duplicate_code":
            params.append(("code", "second-code"))
        elif attack == "unbound_path":
            callback = "/settings/callback"
        elif attack == "wrong_path":
            callback = "/settings/callback/other-provider"
        elif attack == "wrong_cookie":
            client.cookies.clear()
        elif attack == "changed_issuer":
            settings.issuer_url = "https://changed.invalid"
        elif attack == "changed_token_url":
            settings.browser_token_url += "/changed"
        elif attack == "changed_client":
            settings.browser_client_id = "changed-client"
        elif attack == "changed_resource":
            settings.resource_url += "/changed"
        elif attack == "changed_mode":
            settings.browser_require_issuer_parameter = True
        result = await client.get(callback, params=params)
        assert result.status_code == 403
        assert not identity_exchange
        assert "bridge_session" not in result.cookies


async def test_T12_T19_default_callback_requires_issuer_and_rejects_legacy_state(
    bridge, settings, identity_exchange
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        params = {"state": values["state"][0], "code": "fixture-code"}
        assert (await client.get(callback, params=params)).status_code == 403
        # States created before endpoint/issuer binding must restart sign-in.
        state_digest = digest(params["state"])
        with bridge.store.transaction() as database:
            row = database.get(OAuthState, state_digest)
            payload = bridge.vault.open(row.payload, "identity", state_digest)
            payload.pop("context")
            row.payload = bridge.vault.seal(payload, "identity", state_digest)
        params["iss"] = settings.issuer_url
        assert (await client.get(callback, params=params)).status_code == 403
        assert not identity_exchange


async def test_browser_sign_out_expires_all_existing_sessions(
    bridge, settings, identity_exchange, token_factory
):
    import re

    from canvas_bridge.auth import JWTVerifier

    raw = token_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        response = await client.get(
            callback,
            params={"state": values["state"][0], "code": "fixture", "iss": settings.issuer_url},
        )
        assert response.status_code == 303
        settings_page = await client.get("/settings")
        csrf = re.search(r'name="csrf" value="([^"]+)"', settings_page.text)[1]
        denied = await client.post(
            "/settings/sign-out", data={"csrf": "wrong"}, headers={"Origin": settings.resource_url}
        )
        assert denied.status_code == 403
        result = await client.post(
            "/settings/sign-out", data={"csrf": csrf}, headers={"Origin": settings.resource_url}
        )
        assert result.status_code == 200 and "Signed out" in result.text
        assert "bridge_session" not in client.cookies
    assert await JWTVerifier(settings, bridge.store).verify_token(raw) is None


async def test_application_account_switch_cannot_reuse_existing_browser(
    bridge, settings, identity_exchange, token_factory, monkeypatch
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        assert (
            await client.get(
                callback,
                params={"state": values["state"][0], "code": "fixture", "iss": settings.issuer_url},
            )
        ).status_code == 303
        cookie = client.cookies["bridge_session"]
        values, callback = await start(client)

        @asynccontextmanager
        async def other_client():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json={"access_token": token_factory(sub="another-account")}
                    )
                )
            ) as http:
                yield http

        monkeypatch.setattr("canvas_bridge.settings_ui.public_client", other_client)
        result = await client.get(
            callback,
            params={"state": values["state"][0], "code": "fixture", "iss": settings.issuer_url},
        )
        assert result.status_code == 403 and "Sign out before switching" in result.text
        assert client.cookies["bridge_session"] == cookie


async def test_pending_login_cannot_reopen_session_after_sign_out(
    bridge, owner, settings, identity_exchange, monkeypatch
):
    from datetime import timedelta

    from canvas_bridge.domain import utcnow
    from canvas_bridge.linking import terminate_sessions

    now = utcnow()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        state_digest = digest(values["state"][0])
        with bridge.store.transaction() as database:
            record = database.get(OAuthState, state_digest)
            payload = bridge.vault.open(record.payload, "identity", state_digest)
            payload["started_at"] = (now - timedelta(seconds=10)).timestamp()
            record.payload = bridge.vault.seal(payload, "identity", state_digest)
        monkeypatch.setattr("canvas_bridge.linking.utcnow", lambda: now - timedelta(seconds=5))
        terminate_sessions(bridge, owner, 0)
        # The synthetic issuer mints a NEW valid JWT after the cutoff; the older
        # authorization transaction still cannot undo sign-out.
        result = await client.get(
            callback,
            params={
                "state": values["state"][0],
                "code": "fixture",
                "iss": settings.issuer_url,
            },
        )
        assert result.status_code == 403 and "bridge_session" not in result.cookies


async def test_unverified_connection_settings_do_not_fetch_and_allow_disconnect(
    bridge, owner, seeded, settings, identity_exchange, monkeypatch
):
    from canvas_bridge.storage import Connection

    with bridge.store.transaction() as database:
        database.get(Connection, seeded).authentication_state = "unverified"

    async def forbidden(*args):
        pytest.fail("Unverified settings must not fetch upstream courses.")

    monkeypatch.setattr(bridge, "list_courses", forbidden)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        assert (
            await client.get(
                callback,
                params={
                    "state": values["state"][0],
                    "code": "fixture",
                    "iss": settings.issuer_url,
                },
            )
        ).status_code == 303
        page = await client.get("/settings")
        assert page.status_code == 200 and "Authentication: unverified" in page.text
        assert 'action="/settings/disconnect"' in page.text
        assert 'action="/settings/sign-out"' in page.text


async def test_browser_revocation_during_fetch_blocks_response(
    bridge, owner, seeded, settings, identity_exchange, monkeypatch
):
    from canvas_bridge.linking import terminate_sessions

    original = bridge.list_courses

    async def revoke_after_fetch(*args):
        result = await original(*args)
        terminate_sessions(bridge, owner, 0)
        return result

    monkeypatch.setattr(bridge, "list_courses", revoke_after_fetch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        await client.get(
            callback,
            params={
                "state": values["state"][0],
                "code": "fixture",
                "iss": settings.issuer_url,
            },
        )
        result = await client.get("/settings")
        assert result.status_code == 403
        assert "Synthetic Cell Biology" not in result.text
