import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from canvas_bridge.domain import DomainError
from canvas_bridge.jobs import claim
from canvas_bridge.linking import begin_link, delete_account
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Connection, Job, OAuthState, PrincipalState, Store
from tests.conftest import seed
from tests.test_oauth import configure

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_bridge(bridge, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL must name a disposable PostgreSQL database.")
    schema = "fixture_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped_url = scoped.render_as_string(hide_password=False)
    monkeypatch.setenv("BRIDGE_DATABASE_URL", scoped_url)
    command.upgrade(Config("alembic.ini"), "head")
    store = Store(scoped_url)
    service = Bridge(bridge.settings, store, bridge.vault, bridge.registry, bridge.synthetic)
    try:
        yield service
    finally:
        store.close()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


async def test_T35_postgresql_migration_read_roundtrip_and_rollback(pg_bridge, owner):
    ref = await seed(pg_bridge, owner)
    result = await pg_bridge.refresh(owner, ref)
    assert result.complete and len(result.items) == 5
    with pg_bridge.store.transaction() as session:
        assert session.get(Connection, ref).last_success
    command.downgrade(Config("alembic.ini"), "base")
    assert "connections" not in inspect(pg_bridge.store.engine).get_table_names()
    command.upgrade(Config("alembic.ini"), "head")
    assert "connections" in inspect(pg_bridge.store.engine).get_table_names()


async def test_T13_T21_pool_reuse_never_reuses_another_owner(pg_bridge, owner):
    first = await seed(pg_bridge, owner)
    second = await seed(pg_bridge, "other-owner", "connection-two")
    snapshot = await pg_bridge.refresh(owner, first)
    for _ in range(5):
        with pytest.raises(DomainError):
            pg_bridge.snapshot("other-owner", second, snapshot.id)
        with pytest.raises(DomainError):
            pg_bridge.snapshot("other-owner", first, snapshot.id)
        assert pg_bridge.snapshot(owner, first, snapshot.id).id == snapshot.id


async def test_T18_T40_concurrent_local_versions_do_not_overwrite(pg_bridge, owner):
    ref = await seed(pg_bridge, owner)

    def write(value):
        try:
            return pg_bridge.store.save_local(
                owner, ref, "preferences", "default", {"value": value}, 0
            )
        except DomainError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [1, 2]))
    assert sum(x == "conflict" for x in results) == 1
    assert sum(isinstance(x, dict) for x in results) == 1


async def test_T39_worker_admin_connection_checks_job_ownership(pg_bridge, owner):
    ref = await seed(pg_bridge, owner)
    with pg_bridge.store.transaction() as session:
        session.add(
            Job(
                owner="foreign-owner",
                connection_id=ref,
                epoch=0,
                kind="refresh",
                payload={},
                state="pending",
            )
        )
    assert claim(pg_bridge) is None
    with pg_bridge.store.transaction() as session:
        assert session.scalar(select(Job)).state == "cancelled"


async def test_T18_T43_postgres_account_deletion_and_link_race(pg_bridge, owner, monkeypatch):
    import asyncio

    await seed(pg_bridge, owner)
    configure(pg_bridge, monkeypatch)

    def deleting():
        return asyncio.run(delete_account(pg_bridge, owner, 0))

    def linking():
        try:
            return begin_link(pg_bridge, owner, "synthetic", "browser", 0)
        except DomainError:
            return "revoked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion, authorization = pool.submit(deleting), pool.submit(linking)
        assert deletion.result(timeout=10).data["active_store"] == "purged"
        assert authorization.result(timeout=10)
    with pg_bridge.store.transaction() as session:
        assert not session.scalar(select(Connection).where(Connection.owner == owner))
        assert not session.scalar(select(OAuthState).where(OAuthState.owner == owner))
        assert session.get(PrincipalState, owner).generation == 1


def test_T13_T18_postgres_concurrent_personal_import_keeps_one_grant(pg_bridge, owner, monkeypatch):
    import asyncio
    from threading import Barrier

    from canvas_bridge.personal import link_personal_token

    pg_bridge.settings.profile = "personal"
    pg_bridge.settings.personal_subject = "student-one"
    pg_bridge.settings.live_access_enabled = True
    pg_bridge.synthetic = None
    pg_bridge.registry.entries["synthetic"].status = "personal_testing"
    barrier = Barrier(2)

    async def profile(*args):
        await asyncio.to_thread(barrier.wait, timeout=5)
        return {"id": 101}

    monkeypatch.setattr("canvas_bridge.personal.CanvasClient.one", profile)

    def import_token(token):
        try:
            return asyncio.run(link_personal_token(pg_bridge, "synthetic", "101", token))
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(import_token, ["fixture-one", "fixture-two"]))
    assert sum(item == "needs_input" for item in outcomes) == 1
    with pg_bridge.store.transaction() as session:
        connections = list(session.scalars(select(Connection)))
        assert len(connections) == 1 and connections[0].owner == owner
        row = connections[0]
        assert pg_bridge.vault.open(row.credential, owner, row.id)["access_token"] in {
            "fixture-one",
            "fixture-two",
        }
