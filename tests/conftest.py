import json
import os
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from canvas_bridge.auth import principal_id
from canvas_bridge.config import Settings
from canvas_bridge.domain import utcnow
from canvas_bridge.policy import Registry
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Connection, Store
from canvas_bridge.synthetic import SyntheticProvider
from canvas_bridge.vault import Vault


@pytest.fixture(scope="session")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings(tmp_path, signing_key):
    (tmp_path / "vault.key").write_bytes(os.urandom(32))
    (tmp_path / "deletions.jsonl").touch()
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    key.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    (tmp_path / "jwks.json").write_text(json.dumps({"keys": [key]}))
    return Settings(
        _env_file=None,
        profile="synthetic",
        database_url="sqlite:///:memory:",
        issuer_url="https://fixture-issuer.invalid",
        resource_url="http://127.0.0.1:8000",
        local_jwks_file=tmp_path / "jwks.json",
        vault_key_file=tmp_path / "vault.key",
        deletion_journal=tmp_path / "deletions.jsonl",
    )


@pytest.fixture
def token_factory(settings, signing_key):
    def make(**overrides):
        claims = {
            "iss": settings.issuer_url,
            "aud": settings.resource_url,
            "sub": "student-one",
            "iat": utcnow(),
            "exp": utcnow() + timedelta(hours=1),
            "scope": "academic:read preferences:write settings:write",
        }
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})

    return make


@pytest.fixture
def bridge(settings):
    store = Store(settings.database_url)
    store.create_fixture_schema()
    service = Bridge(
        settings,
        store,
        Vault(settings.vault_key_file),
        Registry(settings.institutions_file),
        SyntheticProvider(),
    )
    yield service
    store.close()


@pytest.fixture
def owner(settings):
    return principal_id(settings.issuer_url, "student-one")


async def seed(bridge, owner, ref="connection-one"):
    with bridge.store.transaction() as session:
        session.add(
            Connection(
                id=ref,
                owner=owner,
                institution="synthetic",
                canvas_user="101",
                credential=bridge.vault.seal(
                    {"access_token": "fixture-provider-token"}, owner, ref
                ),
            )
        )
    courses = await bridge.list_courses(owner, ref)
    bridge.select_courses(owner, ref, [c["id"] for c in courses.data["courses"]], "UTC")
    return ref


@pytest.fixture
async def seeded(bridge, owner):
    return await seed(bridge, owner)
