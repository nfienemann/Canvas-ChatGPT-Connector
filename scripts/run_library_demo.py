"""Disposable zero-LMS browser acceptance fixture; never loads .env or personal storage."""

import argparse
import asyncio
import contextlib
import json
import tempfile
from datetime import timedelta
from pathlib import Path

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa

from canvas_bridge.app import create_app
from canvas_bridge.config import Settings
from canvas_bridge.domain import utcnow
from canvas_bridge.jobs import worker
from canvas_bridge.policy import Registry
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Store
from canvas_bridge.synthetic import SyntheticProvider
from canvas_bridge.vault import Vault


async def serve(port):
    with tempfile.TemporaryDirectory(prefix="bridge-library-demo-") as directory:
        root = Path(directory).resolve()  # noqa: ASYNC240 - one-time disposable fixture setup.
        assert root.parent == Path(tempfile.gettempdir()).resolve()  # noqa: ASYNC240
        Vault.create(root / "vault.key")
        (root / "journal").touch()
        signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key()))
        key.update(kid="fictional-library", alg="RS256", use="sig")
        (root / "jwks.json").write_text(json.dumps({"keys": [key]}))
        settings = Settings(
            _env_file=None,
            profile="synthetic",
            database_url="sqlite:///" + (root / "library.sqlite").as_posix(),
            resource_url=f"http://127.0.0.1:{port}",
            local_jwks_file=root / "jwks.json",
            vault_key_file=root / "vault.key",
            deletion_journal=root / "journal",
            library_enabled=True,
            library_root=root / "objects",
            file_reading_enabled=True,
            parser_root=root / "parser",
        )
        token = jwt.encode(
            {
                "iss": settings.issuer_url,
                "aud": settings.resource_url,
                "sub": "fictional-library-owner",
                "iat": utcnow(),
                "exp": utcnow() + timedelta(hours=1),
                "scope": "academic:read preferences:write settings:write",
            },
            signing,
            algorithm="RS256",
            headers={"kid": "fictional-library"},
        )
        (root / "demo-token").write_text(token)
        store = Store(settings.database_url)
        store.create_fixture_schema()
        bridge = Bridge(
            settings,
            store,
            Vault(settings.vault_key_file),
            Registry(settings.institutions_file),
            SyntheticProvider(),
        )
        task = asyncio.create_task(worker(bridge))
        try:
            print(f"Disposable fictional library: {settings.resource_url}/settings", flush=True)
            await uvicorn.Server(
                uvicorn.Config(
                    create_app(settings, bridge),
                    host="127.0.0.1",
                    port=port,
                    access_log=False,
                    log_level="warning",
                )
            ).serve()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    asyncio.run(serve(args.port))
