"""Disposable PostgreSQL gate; never replaced by a local SQLite pass."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.service import Bridge
from canvas_bridge.storage import BrowserSession, Store
from tests.test_postgres import pg_bridge as pg_bridge
from tests.test_private_library import browser as browser
from tests.test_private_library import selection

pytestmark = pytest.mark.postgres


def test_postgres_library_shared_quota_and_ingress(pg_bridge, browser, owner, tmp_path):
    pg_bridge.settings.library_enabled = True
    pg_bridge.settings.library_root = tmp_path / "pg-library"
    pg_bridge.settings.library_quota_bytes = 16
    with pg_bridge.store.transaction() as session:
        pg_bridge.store.principal(session, owner)
        session.add(
            BrowserSession(
                **{c.name: getattr(browser, c.name) for c in BrowserSession.__table__.columns}
            )
        )
    second = Bridge(
        pg_bridge.settings,
        Store(pg_bridge.store.engine.url.render_as_string(hide_password=False)),
        pg_bridge.vault,
        pg_bridge.registry,
        pg_bridge.synthetic,
    )
    try:

        def admit(index):
            target = pg_bridge if index % 2 else second
            return target.library.create_intake(browser, selection(browser, b"0123456789"))[
                "files"
            ][0]["state"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            states = list(pool.map(admit, range(8)))
        assert states.count("created") == 1
        for _ in range(4):
            pg_bridge.library.claim_operation(owner, "ingress")
        with pytest.raises(DomainError):
            second.library.claim_operation(owner, "ingress")
        assert second.library.health()["quota_drift_accounts"] == 0
    finally:
        second.store.close()
