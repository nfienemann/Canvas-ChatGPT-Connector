"""Disposable 1,000-item local reference workload; never loads operator configuration."""

import argparse
import asyncio
import hashlib
import json
import math
import platform
import statistics
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.config import Settings
from canvas_bridge.domain import opaque_id, utcnow
from canvas_bridge.egress_models import RecipientIdentity
from canvas_bridge.evidence import fingerprint
from canvas_bridge.library import safety
from canvas_bridge.library.contracts import IntakeRequest
from canvas_bridge.library.models import Account, Grant, Item, Representation, Version
from canvas_bridge.library_safety_worker import inspect
from canvas_bridge.parser_worker import extract
from canvas_bridge.policy import Registry
from canvas_bridge.service import Bridge
from canvas_bridge.storage import BrowserSession, Store
from canvas_bridge.synthetic import SyntheticProvider
from canvas_bridge.vault import Vault


def seed(bridge, count):
    owner, now = hashlib.sha256(b"fictional-library-benchmark-owner").hexdigest(), utcnow()
    browser = BrowserSession(
        digest=hashlib.sha256(b"fictional-benchmark-session").hexdigest(),
        owner=owner,
        csrf="fictional-benchmark-csrf",
        credential="synthetic-only",
        generation=0,
        expires_at=now + timedelta(hours=1),
    )
    profile = bridge.independent.profile()
    grants = {
        "allow_processing": True,
        "purpose": "study",
        "recipients": [
            {"profile": profile.model_dump(mode="json"), "channels": ["metadata", "text"]}
        ],
        "policy_version": "private-library-1",
        "action_receipt": "fictional-seed",
    }
    ids, total, derived = [], 0, 0
    with bridge.library.transaction(owner) as (session, account, principal):
        account = Account(owner=owner, committed=0, slots=count, derived_bytes=0)
        session.add_all([account, browser])
        session.flush()
        for index in range(count):
            raw = f"Fictional source {index}: ATP supports cellular work. Synthetic benchmark only.\n".encode()
            digest, version_id, key, item_id = (
                hashlib.sha256(raw).hexdigest(),
                opaque_id(),
                opaque_id(),
                opaque_id(),
            )
            bridge.library.objects.put_chunk(owner, key, 0, raw)
            bridge.library.objects.publish(owner, key, len(raw), digest)
            item = Item(
                owner=owner,
                id=item_id,
                current=version_id,
                metadata_value={
                    "title": f"Fictional note {index}",
                    "tags": ["fixture"],
                    "collection_id": "synthetic",
                },
            )
            session.add(item)
            session.flush()
            version = Version(
                owner=owner,
                id=version_id,
                item=item_id,
                object_key=key,
                size=len(raw),
                digest=digest,
                kind="txt",
                processing="ready",
                provenance={
                    "schema_version": "library-provenance-1",
                    "owner": owner,
                    "sha256": digest,
                    "action_receipt": "fictional-seed",
                    "institutional_connection": None,
                    "source_origin": "independent_user_supplied",
                    "acquisition_channel": "browser_upload",
                    "filename": f"fictional-{index}.txt",
                    "retention": {"mode": "until_deleted"},
                },
            )
            session.add(version)
            session.flush()
            parsed = extract(raw, "txt")
            size = len(json.dumps(parsed).encode())
            session.add_all(
                [
                    Grant(owner=owner, id=version_id, payload=grants),
                    Representation(
                        owner=owner,
                        version=version_id,
                        digest=fingerprint(parsed),
                        size=size,
                        payload=parsed,
                        expires_at=now + timedelta(hours=24),
                    ),
                ]
            )
            ids.append(item_id)
            total += len(raw)
            derived += size
        account.committed, account.derived_bytes = total, derived
    return owner, browser, ids, total


def distribution(samples, target):
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "median_seconds": round(statistics.median(samples), 6),
        "p95_seconds": round(ordered[math.ceil(len(samples) * 0.95) - 1], 6),
        "target_seconds": target,
        "met_target": ordered[math.ceil(len(samples) * 0.95) - 1] <= target,
    }


async def run(count=1000, samples=20):
    with tempfile.TemporaryDirectory(prefix="bridge-library-benchmark-") as directory:
        root = Path(directory)
        Vault.create(root / "vault.key")
        (root / "journal").touch()
        settings = Settings(
            _env_file=None,
            profile="synthetic",
            database_url="sqlite:///" + (root / "fixture.sqlite").as_posix(),
            vault_key_file=root / "vault.key",
            deletion_journal=root / "journal",
            library_enabled=True,
            library_root=root / "objects",
            file_reading_enabled=True,
        )
        store = Store(settings.database_url)
        store.create_fixture_schema()
        bridge = Bridge(
            settings,
            store,
            Vault(settings.vault_key_file),
            Registry(settings.institutions_file),
            SyntheticProvider(),
        )
        token = request_authorization.set(
            RequestAuthorization(
                "library-benchmark",
                recipient="chatgpt",
                egress_identity=RecipientIdentity("chatgpt"),
            )
        )
        original_scanner, validated_at = safety.scan, 0

        async def scanner(data, kind, config, preview=False):
            nonlocal validated_at
            result = inspect(data, kind, preview)
            validated_at = time.perf_counter()
            return result

        try:
            owner, browser, ids, size = seed(bridge, count)
            safety.scan = scanner
            times = {"list": [], "search": [], "finalize_after_validation": []}
            for index in range(samples):
                start = time.perf_counter()
                listed = bridge.library.list(owner, limit=20)
                times["list"].append(time.perf_counter() - start)
                assert len(listed.data["items"]) == min(20, count)
                start = time.perf_counter()
                found = bridge.library.search(owner, "ATP")
                times["search"].append(time.perf_counter() - start)
                assert found.data["hits"] and found.data["scanned_items"] <= 20
                current = bridge.library.get(owner, ids[index % count], browser=True).data
                raw = f"Fictional replacement {index}: ATP remains a synthetic marker.".encode()
                request = IntakeRequest(
                    authorization_action_id=hashlib.sha256(browser.csrf.encode()).hexdigest(),
                    idempotency_key=opaque_id(),
                    files=[
                        {
                            "selection_id": "0",
                            "file_name": "fictional.txt",
                            "declared_bytes": len(raw),
                            "maximum_bytes": len(raw),
                        }
                    ],
                    purpose="study",
                )
                receipt = bridge.library.create_intake(
                    browser,
                    request,
                    replacement={
                        "item_id": current["item_id"],
                        "expected_version_id": current["version_id"],
                        "expected_revision": current["metadata_revision"],
                        "expected_permission_revision": current["permission_revision"],
                    },
                )
                ident, selection_id = receipt["intake_id"], receipt["files"][0]["selection_id"]
                sha = hashlib.sha256(raw).hexdigest()
                bridge.library.put_chunk(browser, ident, selection_id, 0, sha, raw)
                result = await bridge.library.complete(browser, ident, {selection_id: sha})
                times["finalize_after_validation"].append(time.perf_counter() - validated_at)
                assert result["status"] == "complete"
            health = bridge.library.health(verify_originals=True)
            assert health["quota_drift_accounts"] == 0 and health["originals_failed"] == 0
            assert bridge.synthetic.requests == []
            return {
                "generated_at": utcnow().isoformat(),
                "environment": {
                    "os": platform.system(),
                    "python": platform.python_version(),
                    "database": "disposable SQLite file",
                    "storage": "encrypted local directory",
                    "concurrency": 1,
                },
                "items_per_owner": count,
                "initial_original_bytes": size,
                "corpus": "Short fictional TXT; preseeded real-parser representations, no OCR/native conversion.",
                "scope": "Service calls including database/encryption/current authorization; excludes HTTP/network and safety-worker startup. No hosted or real-client claim.",
                "results": {
                    key: distribution(value, 3 if key == "search" else 2)
                    for key, value in times.items()
                },
                "isolation": {
                    "upstream_requests": 0,
                    "quota_drift_accounts": 0,
                    "originals_failed": 0,
                },
            }
        finally:
            safety.scan = original_scanner
            request_authorization.reset(token)
            store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--items", type=int, choices=range(1, 1001), default=1000)
    parser.add_argument("--samples", type=int, choices=range(1, 101), default=20)
    args = parser.parse_args()
    report = asyncio.run(run(args.items, args.samples))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["results"]))
    raise SystemExit(0 if all(r["met_target"] for r in report["results"].values()) else 1)
