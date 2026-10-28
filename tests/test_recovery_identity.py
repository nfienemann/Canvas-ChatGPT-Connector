"""Canonical-origin and identity diagnostics with a fictional OAuth issuer."""

import json

import httpx
import pytest
from sqlalchemy import select

from canvas_bridge.app import create_app
from canvas_bridge.storage import OAuthState
from tests.test_settings_oauth import identity_exchange as identity_exchange
from tests.test_settings_oauth import start


async def test_noncanonical_login_redirects_before_state_or_cookie(
    settings, bridge, identity_exchange
):
    settings.resource_url = "https://canonical.invalid"
    app = create_app(settings, bridge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        for path in ("/settings", "/settings/login"):
            result = await client.get(path + "?next=https://attacker.invalid&code=private-marker")
            assert result.status_code == 303
            assert result.headers["location"] == "https://canonical.invalid" + path
            assert "set-cookie" not in result.headers
            assert "private-marker" not in result.text
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(OAuthState)))
    assert identity_exchange == []


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("cookie", "OAUTH_BROWSER_COOKIE_MISSING"),
        ("origin", "OAUTH_CALLBACK_ORIGIN_MISMATCH"),
        ("state", "OAUTH_STATE_UNKNOWN"),
        ("issuer", "OAUTH_ISSUER_MISMATCH"),
    ],
)
async def test_safe_callback_failure_reasons(settings, bridge, identity_exchange, failure, reason):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        params = {
            "state": values["state"][0],
            "iss": settings.issuer_url,
            "code": "secret-fixture-code",
        }
        if failure == "cookie":
            client.cookies.clear()
        elif failure == "state":
            params["state"] = "another-state"
        elif failure == "issuer":
            params["iss"] = "https://wrong.invalid"
        elif failure == "origin":
            callback = "http://localhost:8000" + callback
        response = await client.get(callback, params=params)
        assert response.status_code == 403 and reason in response.text
        assert (
            "secret-fixture-code" not in response.text and values["state"][0] not in response.text
        )
    assert identity_exchange == []


async def test_personal_subject_failure_never_uses_email_equality(
    settings, bridge, identity_exchange, monkeypatch
):
    async def fixture_keys(self):
        return json.loads(settings.local_jwks_file.read_text())["keys"]

    monkeypatch.setattr("canvas_bridge.auth.JWTVerifier._keys", fixture_keys)
    settings.profile = "personal"
    settings.personal_subject = "different-stable-subject"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, bridge)),
        base_url=settings.resource_url,
    ) as client:
        values, callback = await start(client)
        response = await client.get(
            callback,
            params={"state": values["state"][0], "iss": settings.issuer_url, "code": "fictional"},
        )
        assert response.status_code == 403
        assert "MCP_PERSONAL_SUBJECT_MISMATCH" in response.text
        assert "different-stable-subject" not in response.text
        assert "email equality does not establish identity" in response.text


async def test_authorization_stages_do_not_treat_oauth_as_approval(bridge, owner, seeded):
    from canvas_bridge.authorization_status import stages

    result = stages(bridge, owner, bridge.registry.entries["synthetic"])
    assert result["provider_approval"] == "NOT_ASSESSED"
    assert result["institution_approval"] == "NOT_ASSESSED"
    assert result["upstream_identity"] == "verified"
    assert not result["link_action_available"]
