"""Abrupt child-process loss against disposable SQLite; no production services."""

import asyncio
import hashlib
import multiprocessing
import os
from datetime import timedelta

import pytest

from canvas_bridge.config import Settings
from canvas_bridge.policy import Registry
from canvas_bridge.service import Bridge
from canvas_bridge.storage import BrowserSession, Store
from canvas_bridge.synthetic import SyntheticProvider
from canvas_bridge.vault import Vault
from tests.test_private_library import browser as browser
from tests.test_private_library import library as library
from tests.test_private_library import selection


def _crash(values, owner, browser_digest, intake, selection_id, boundary, raw):
    from canvas_bridge.library import safety
    from canvas_bridge.library_safety_worker import inspect

    settings = Settings(_env_file=None, **values)
    store = Store(settings.database_url)
    bridge = Bridge(
        settings,
        store,
        Vault(settings.vault_key_file),
        Registry(settings.institutions_file),
        SyntheticProvider(),
    )

    async def scan(data, kind, settings, preview=False):
        return inspect(data, kind, preview)

    safety.scan = scan  # Fault test isolates persistence, not OS sandbox acceptance.
    with store.transaction() as session:
        browser = session.get(BrowserSession, browser_digest)
    operation = "put_chunk" if boundary == "chunk" else "publish"
    original = getattr(bridge.library.objects, operation)

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(91)  # Kill only this disposable test child, without transaction cleanup.

    setattr(bridge.library.objects, operation, crash)
    digest = hashlib.sha256(raw).hexdigest()
    if boundary == "chunk":
        bridge.library.put_chunk(browser, intake, selection_id, 0, digest, raw)
    else:
        asyncio.run(bridge.library.complete(browser, intake, {selection_id: digest}))


@pytest.mark.parametrize("boundary", ["chunk", "publish"])
async def test_abrupt_process_loss_recovers_exactly_once(
    library, browser, owner, tmp_path, boundary
):
    database = "sqlite:///" + (tmp_path / "crash.sqlite").as_posix()
    settings = library.bridge.settings.model_copy(update={"database_url": database})
    store = Store(database)
    store.create_fixture_schema()
    bridge = Bridge(
        settings, store, library.bridge.vault, library.bridge.registry, library.bridge.synthetic
    )
    raw = b"Fictional abrupt termination recovery."
    digest = hashlib.sha256(raw).hexdigest()
    try:
        with store.transaction() as session:
            store.principal(session, owner)
            session.add(
                BrowserSession(
                    **{
                        column.name: getattr(browser, column.name)
                        for column in BrowserSession.__table__.columns
                    }
                )
            )
        receipt = bridge.library.create_intake(browser, selection(browser, raw))
        intake, ident = receipt["intake_id"], receipt["files"][0]["selection_id"]
        if boundary == "publish":
            bridge.library.put_chunk(browser, intake, ident, 0, digest, raw)
        child = multiprocessing.get_context("spawn").Process(
            target=_crash,
            args=(settings.model_dump(), owner, browser.digest, intake, ident, boundary, raw),
        )
        child.start()
        child.join(60)
        if child.is_alive():
            child.terminate()
            child.join(10)
        assert child.exitcode == 91
        assert bridge.library.list(owner, browser=True).data["items"] == []
        if boundary == "chunk":
            assert bridge.library.receipt(owner, intake)["files"][0]["offset"] == 0
            bridge.library.put_chunk(browser, intake, ident, 0, digest, raw)
        else:
            # Recover after the crashed worker's durable heavy-operation lease expires.
            now = bridge.library.now
            bridge.retention.clock = lambda: now + timedelta(minutes=6)
        first = await bridge.library.complete(browser, intake, {ident: digest})
        second = await bridge.library.complete(browser, intake, {ident: digest})
        item = first["files"][0]["items"][0]
        assert first["files"][0]["items"] == second["files"][0]["items"]
        assert bridge.library.bytes(owner, item["version_id"]) == raw
        assert bridge.library.status(owner).data["quota"]["committed_bytes"] == len(raw)
        assert bridge.library.health()["quota_drift_accounts"] == 0
    finally:
        store.close()
