import argparse
import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

import jwt
import uvicorn
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select, text

from canvas_bridge.app import create_app, create_bridge
from canvas_bridge.auth import principal_id
from canvas_bridge.config import Settings
from canvas_bridge.domain import opaque_id, utcnow
from canvas_bridge.storage import Connection


def initialize_demo():
    if Path(".env").exists():
        current = Settings()
        if current.profile != "synthetic":
            raise RuntimeError("A live configuration exists; refusing to replace it.")
    folder = Path(".local").resolve()
    folder.mkdir(exist_ok=True)
    private_file = folder / "issuer-private.pem"
    if not private_file.exists():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_file.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    else:
        private_key = serialization.load_pem_private_key(private_file.read_bytes(), password=None)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "local-synthetic", "use": "sig", "alg": "RS256"})
    (folder / "jwks.json").write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    if not (folder / "vault.key").exists():
        (folder / "vault.key").write_bytes(os.urandom(32))
    if not (folder / "deletions.jsonl").exists():
        (folder / "deletions.jsonl").touch()
    if not Path(".env").exists():
        Path(".env").write_text(
            "BRIDGE_PROFILE=synthetic\n"
            f"BRIDGE_DATABASE_URL={os.environ.get('BRIDGE_DATABASE_URL', 'sqlite:///.local/bridge.db')}\n"
            "BRIDGE_RESOURCE_URL=http://127.0.0.1:8000\n"
            "BRIDGE_ISSUER_URL=https://synthetic.invalid\n"
            f"BRIDGE_LOCAL_JWKS_FILE={folder.as_posix()}/jwks.json\n"
            f"BRIDGE_VAULT_KEY_FILE={folder.as_posix()}/vault.key\n"
            f"BRIDGE_DELETION_JOURNAL={folder.as_posix()}/deletions.jsonl\n",
            encoding="utf-8",
        )
    settings = Settings()
    token = jwt.encode(
        {
            "iss": settings.issuer_url,
            "aud": settings.resource_url,
            "sub": "synthetic-student",
            "iat": utcnow(),
            "exp": utcnow() + timedelta(hours=24),
            "scope": "academic:read preferences:write settings:write",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "local-synthetic"},
    )
    (folder / "demo-token").write_text(token, encoding="utf-8")
    command.upgrade(Config("alembic.ini"), "head")
    bridge = create_bridge(settings)
    owner = principal_id(settings.issuer_url, "synthetic-student")
    with bridge.store.transaction() as session:
        conn = session.scalar(
            select(Connection).where(
                Connection.owner == owner,
                Connection.state == "active",
            )
        )
        if not conn:
            ref = opaque_id()
            conn = Connection(
                id=ref,
                owner=owner,
                institution="synthetic",
                canvas_user="101",
                credential=bridge.vault.seal({"access_token": os.urandom(32).hex()}, owner, ref),
            )
            session.add(conn)
            session.flush()
        ref = conn.id

    async def seed_courses():
        result = await bridge.list_courses(owner, ref)
        bridge.select_courses(owner, ref, [c["id"] for c in result.data["courses"]], "UTC")

    asyncio.run(seed_courses())
    bridge.store.close()
    print("Synthetic environment initialized. Credentials are private under .local/.")
    print("Start: uv run canvas-bridge serve")
    print("Settings: http://127.0.0.1:8000/settings")
    print("Protocol check: uv run canvas-bridge verify-read")


async def verify_read(settings: Settings):
    if settings.profile != "synthetic":
        raise RuntimeError("This automatic demonstration is restricted to synthetic records.")
    import httpx

    token = settings.local_jwks_file.with_name("demo-token").read_text(encoding="utf-8").strip()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        async with streamable_http_client(
            settings.resource_url.rstrip("/") + "/mcp", http_client=http
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                status = await session.call_tool("get_connection_status", {})
                payload = status.structuredContent
                ref = payload["data"]["connections"][0]["id"]
                workload = await session.call_tool(
                    "get_workload",
                    {
                        "connection_id": ref,
                        "start": utcnow().isoformat(),
                        "end": (utcnow() + timedelta(days=7)).isoformat(),
                        "timezone": "UTC",
                    },
                )
                result = workload.structuredContent
                if workload.isError or result["status"] != "ok" or not result["data"]["items"]:
                    raise RuntimeError("Synthetic workload protocol check failed.")
                plan = await session.call_tool(
                    "propose_study_plan",
                    {
                        "connection_id": ref,
                        "snapshot_id": result["meta"]["snapshot_id"],
                        "request": {"opportunity_minutes": 45},
                    },
                )
                if plan.isError or not plan.structuredContent["data"].get("recommendations"):
                    raise RuntimeError("Synthetic planning protocol check failed.")
                print(
                    json.dumps(
                        {
                            "environment": "local_synthetic",
                            "protocol": initialized.protocolVersion,
                            "tool_count": len(tools.tools),
                            "observed_obligations": len(result["data"]["items"]),
                            "workload_status": result["status"],
                            "planning": "verified",
                            "actual_chatgpt": "not_tested",
                            "live_canvas": "not_tested",
                        },
                        indent=2,
                    )
                )


def doctor(settings: Settings):
    checks = {
        "profile": settings.profile,
        "vault_key_present": settings.vault_key_file.is_file(),
        "institution_registry_present": settings.institutions_file.is_file(),
        "local_keys_present": bool(settings.local_jwks_file and settings.local_jwks_file.is_file()),
        "live_access_enabled": settings.live_access_enabled,
        "calendar_writes_enabled": False,
        "model_api_key_required": False,
    }
    try:
        bridge = create_bridge(settings)
        with bridge.store.engine.connect() as connection:
            checks["database_reachable"] = connection.execute(text("SELECT 1")).scalar() == 1
            checks["migration"] = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        bridge.store.close()
    except Exception as exc:
        checks["database_error_type"] = type(exc).__name__
    print(json.dumps(checks, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Canvas Bridge operator tools; no student CLI required."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init-demo", "serve", "doctor", "verify-read", "worker", "purge"):
        sub.add_parser(name)
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("destination", type=Path)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    restore_parser.add_argument("--journal", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "init-demo":
        initialize_demo()
        return
    settings = Settings()
    if args.command == "serve":
        uvicorn.run(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            access_log=False,
            server_header=False,
            proxy_headers=False,
        )
    elif args.command == "doctor":
        doctor(settings)
    elif args.command == "verify-read":
        asyncio.run(verify_read(settings))
    else:
        bridge = create_bridge(settings)
        if args.command == "worker":
            from canvas_bridge.jobs import worker

            asyncio.run(worker(bridge))
        elif args.command == "purge":
            print(json.dumps({"expired_snapshots_removed": bridge.store.purge_history()}))
        elif args.command == "backup":
            from canvas_bridge.lifecycle import backup

            print(json.dumps(backup(bridge, args.destination)))
        elif args.command == "restore":
            from canvas_bridge.lifecycle import restore

            print(json.dumps(restore(bridge, args.source, args.journal)))
        bridge.store.close()


if __name__ == "__main__":
    main()
