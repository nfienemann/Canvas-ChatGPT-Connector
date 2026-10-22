import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError
from canvas_bridge.network import public_client
from canvas_bridge.policy import validate_https

READ_SCOPE = "academic:read"
WRITE_SCOPE = "preferences:write"
SETTINGS_SCOPE = "settings:write"
logger = logging.getLogger(__name__)


def _reject_token(reason: str) -> None:
    # Operator-only, fixed reason codes. Never log tokens, claims, key IDs,
    # exception messages, request headers or URLs at this boundary.
    logger.warning(
        "mcp_auth_rejected %s",
        json.dumps({"reason_code": reason, "timestamp": datetime.now(UTC).isoformat()}),
    )
    return None


def principal_id(issuer: str, subject: str) -> str:
    return hashlib.sha256(f"{issuer}\0{subject}".encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    owner: str
    scopes: frozenset[str]


def request_identity(scope: str = READ_SCOPE) -> Identity:
    token = get_access_token()
    if not token or not token.subject or not token.claims:
        raise DomainError("permission_denied", "Authentication required.")
    if scope not in token.scopes:
        raise DomainError("permission_denied", "The required permission was not granted.")
    return Identity(
        owner=principal_id(token.claims["iss"], token.subject),
        scopes=frozenset(token.scopes),
    )


class JWTVerifier(TokenVerifier):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.keys: list[dict] = []
        self.loaded_at = 0.0
        self.lock = asyncio.Lock()

    async def _keys(self):
        async with self.lock:
            if time.monotonic() - self.loaded_at < 300 and self.keys:
                return self.keys
            if self.settings.profile == "synthetic" and self.settings.local_jwks_file:
                content = json.loads(self.settings.local_jwks_file.read_text(encoding="utf-8"))
            elif self.settings.jwks_url:
                from urllib.parse import urlsplit

                url = self.settings.jwks_url
                validate_https(url, {f"https://{urlsplit(url).hostname}"})
                async with public_client() as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 100_000:
                                raise ValueError("Key document exceeds limit.")
                        content = json.loads(raw)
            else:
                raise ValueError("No configured key source.")
            self.keys = content["keys"]
            self.loaded_at = time.monotonic()
            return self.keys

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or len(token) > 16_384:
            return _reject_token("MCP_TOKEN_FORMAT_INVALID")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                return _reject_token("MCP_TOKEN_HEADER_REJECTED")
            candidates = [
                key
                for key in await self._keys()
                if key.get("kid") == header["kid"]
                and key.get("kty") == "RSA"
                and key.get("use", "sig") == "sig"
                and key.get("alg", "RS256") == "RS256"
            ]
            if len(candidates) != 1:
                return _reject_token("MCP_SIGNING_KEY_UNRESOLVED")
            claims = jwt.decode(
                token,
                jwt.PyJWK.from_dict(candidates[0]).key,
                algorithms=["RS256"],
                issuer=self.settings.issuer_url,
                audience=self.settings.resource_url,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
                return _reject_token("MCP_SUBJECT_INVALID")
            if self.settings.profile == "personal" and subject != self.settings.personal_subject:
                return _reject_token("MCP_PERSONAL_SUBJECT_MISMATCH")
            scope = claims.get("scope", "")
            if not isinstance(scope, str):
                return _reject_token("MCP_SCOPE_CLAIM_INVALID")
            scopes = scope.split()
            if READ_SCOPE not in scopes:
                return _reject_token("MCP_REQUIRED_SCOPE_MISSING")
            return AccessToken(
                token=token,
                client_id=str(claims.get("azp", claims.get("client_id", "oauth"))),
                subject=subject,
                scopes=scopes,
                expires_at=claims["exp"],
                resource=self.settings.resource_url,
                claims={"iss": self.settings.issuer_url},
            )
        except (
            jwt.PyJWTError,
            ValueError,
            KeyError,
            TypeError,
            OSError,
            httpx.HTTPError,
            DomainError,
        ) as exc:
            # Fail closed, including when a key cache has expired and the issuer is down.
            reason = "MCP_TOKEN_VALIDATION_FAILED"
            for kind, code in (
                (jwt.ExpiredSignatureError, "MCP_TOKEN_EXPIRED"),
                (jwt.ImmatureSignatureError, "MCP_TOKEN_NOT_YET_VALID"),
                (jwt.InvalidSignatureError, "MCP_SIGNATURE_INVALID"),
                (jwt.InvalidIssuerError, "MCP_ISSUER_MISMATCH"),
                (jwt.InvalidAudienceError, "MCP_AUDIENCE_MISMATCH"),
                (jwt.MissingRequiredClaimError, "MCP_REQUIRED_CLAIM_MISSING"),
                (OSError, "MCP_KEY_SOURCE_UNAVAILABLE"),
                (httpx.HTTPError, "MCP_KEY_SOURCE_UNAVAILABLE"),
                (DomainError, "MCP_KEY_SOURCE_UNAVAILABLE"),
            ):
                if isinstance(exc, kind):
                    reason = code
                    break
            return _reject_token(reason)
