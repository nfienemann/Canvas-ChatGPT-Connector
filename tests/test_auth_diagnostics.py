"""Synthetic rejection evidence without changing the OAuth acceptance boundary."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from canvas_bridge.auth import JWTVerifier
from canvas_bridge.domain import utcnow


def rejection(caplog, raw, reason):
    records = [r for r in caplog.records if r.name == "canvas_bridge.auth"]
    assert len(records) == 1
    event = json.loads(records[0].getMessage().removeprefix("mcp_auth_rejected "))
    assert set(event) == {"reason_code", "timestamp"}
    assert event["reason_code"] == reason
    assert raw not in caplog.text
    for private in ("private@example.invalid", "student-one", "test-key", "secret-fixture"):
        assert private not in caplog.text


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": 1}, "MCP_TOKEN_EXPIRED"),
        ({"nbf": utcnow() + timedelta(hours=1)}, "MCP_TOKEN_NOT_YET_VALID"),
        ({"aud": "https://secret-fixture.invalid"}, "MCP_AUDIENCE_MISMATCH"),
        ({"iss": "https://secret-fixture.invalid"}, "MCP_ISSUER_MISMATCH"),
        ({"sub": ""}, "MCP_SUBJECT_INVALID"),
        ({"scope": "offline_access"}, "MCP_REQUIRED_SCOPE_MISSING"),
        ({"scope": ["academic:read"]}, "MCP_SCOPE_CLAIM_INVALID"),
        ({"exp": None}, "MCP_REQUIRED_CLAIM_MISSING"),
        ({"azp": 123}, "MCP_CLIENT_ID_INVALID"),
        ({"azp": ""}, "MCP_CLIENT_ID_INVALID"),
        ({"client_id": "conflicting-client"}, "MCP_CLIENT_ID_AMBIGUOUS"),
    ],
)
async def test_rejection_reason_is_redacted(settings, token_factory, caplog, overrides, reason):
    raw = token_factory(email="private@example.invalid", **overrides)
    assert await JWTVerifier(settings).verify_token(raw) is None
    rejection(caplog, raw, reason)


async def test_wrong_personal_subject_stays_denied(settings, token_factory, caplog, monkeypatch):
    verifier = JWTVerifier(settings)
    keys = await verifier._keys()
    settings.profile = "personal"
    settings.personal_subject = "different-owner"
    monkeypatch.setattr(verifier, "_keys", AsyncMock(return_value=keys))
    raw = token_factory(email="private@example.invalid")
    assert await verifier.verify_token(raw) is None
    rejection(caplog, raw, "MCP_PERSONAL_SUBJECT_MISMATCH")


@pytest.mark.parametrize("mode", ["signature", "key_id", "algorithm", "malformed"])
async def test_signature_and_header_failures_stay_denied(
    settings, token_factory, signing_key, caplog, mode
):
    claims = jwt.decode(token_factory(), options={"verify_signature": False})
    if mode == "signature":
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        raw = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "test-key"})
        reason = "MCP_SIGNATURE_INVALID"
    elif mode == "key_id":
        raw = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "secret-fixture"})
        reason = "MCP_SIGNING_KEY_UNRESOLVED"
    elif mode == "algorithm":
        raw = jwt.encode(
            claims, "secret-fixture" * 4, algorithm="HS256", headers={"kid": "test-key"}
        )
        reason = "MCP_TOKEN_HEADER_REJECTED"
    else:
        raw = "secret-fixture.malformed"
        reason = "MCP_TOKEN_VALIDATION_FAILED"
    assert await JWTVerifier(settings).verify_token(raw) is None
    rejection(caplog, raw, reason)


async def test_key_fetch_exception_does_not_leak_message(
    settings, token_factory, caplog, monkeypatch
):
    verifier = JWTVerifier(settings)
    monkeypatch.setattr(
        verifier, "_keys", AsyncMock(side_effect=httpx.ConnectError("secret-fixture"))
    )
    raw = token_factory()
    assert await verifier.verify_token(raw) is None
    rejection(caplog, raw, "MCP_KEY_SOURCE_UNAVAILABLE")


async def test_valid_token_is_unchanged_and_not_logged(settings, token_factory, caplog):
    raw = token_factory(email="private@example.invalid")
    accepted = await JWTVerifier(settings).verify_token(raw)
    assert accepted is not None
    assert accepted.subject == "student-one"
    assert accepted.token == raw
    assert "academic:read" in accepted.scopes
    assert not [r for r in caplog.records if r.name == "canvas_bridge.auth"]
