import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError
from canvas_bridge.policy import Endpoint
from canvas_bridge.usage import models as m
from canvas_bridge.usage.admin import VendorStatement
from canvas_bridge.usage.dashboard import render
from canvas_bridge.usage.evidence import audit
from canvas_bridge.usage.fair_queue import FairQueue
from canvas_bridge.usage.ledger import UpstreamUsageGovernor
from tests.test_usage_governor import ctx, policy, spend
from tests.test_usage_governor import ledger as ledger


def test_all_outbound_paths_are_in_reviewed_inventory(tmp_path):
    assert audit(Path.cwd()) == []
    source = tmp_path / "src/canvas_bridge/extensions"
    source.mkdir(parents=True)
    (source / "rogue.py").write_text("import httpx\nhttpx.get('https://fictional.invalid')\n")
    assert audit(tmp_path) == ["extensions/rogue.py:unreviewed_http_import"]


def test_operator_dashboard_has_aggregate_units_and_escapes_text(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    spend(governor)
    report = governor.report()
    report["provider"] = "<script>private</script>"
    page = render(report)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "Available units" in page and "Vendor spend" in page and "N/A" in page
    assert report["included_allowance"] == 100 and report["reserve_remaining"] == 0


@pytest.mark.parametrize(
    "code",
    [
        "PROVIDER_NOT_AUTHORIZED",
        "BILLING_CONTRACT_UNCONFIGURED",
        "UPSTREAM_BUDGET_EXHAUSTED",
        "WORKLOAD_POOL_DEFERRED",
        "OWNER_RATE_LIMITED",
        "TASK_BUDGET_EXCEEDED",
        "UPSTREAM_THROTTLED",
        "LOCAL_REQUEST_BUSY",
        "UPSTREAM_CIRCUIT_OPEN",
        "GOVERNOR_UNAVAILABLE",
    ],
)
def test_public_governor_errors_are_stable_and_do_not_reveal_contract(code):
    from canvas_bridge.domain import Result
    from canvas_bridge.egress_errors import safe_error_result

    result = safe_error_result(
        Result(
            status="retry_later",
            summary="PRIVATE-CONTRACT",
            data={"reason_code": code, "allowance": 123456, "contract_id": "PRIVATE-CONTRACT"},
        )
    )
    assert result.data["reason_code"] == code
    assert result.data["local_processing_available"] is True
    assert "PRIVATE-CONTRACT" not in result.model_dump_json()
    assert "123456" not in result.model_dump_json()


async def test_explicit_legacy_throttle_403_retries_and_charges(bridge):
    count = [0]

    def handle(request):
        count[0] += 1
        return (
            httpx.Response(
                403,
                json={"errors": [{"message": "Rate Limit Exceeded"}]},
                headers={"Retry-After": "0"},
            )
            if count[0] == 1
            else httpx.Response(200, json={"id": 1})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(
            bridge.registry.require("synthetic", True), "fake", bridge.settings, http
        )
        client.bind_usage(bridge, "fixture")
        await client.one(Endpoint.PROFILE)
    assert count[0] == 2
    assert bridge.usage.report()["uncertain"] == 1


async def test_local_transport_rejection_refunds_before_send(ledger, monkeypatch):
    from canvas_bridge.network import GuardedHTTP, PublicTransport
    from canvas_bridge.request_limits import RequestLimits
    from canvas_bridge.usage.transport import UsageBinding
    from tests.test_request_limits import Pool

    limits = RequestLimits(total=1)
    occupied = limits.acquire("other.invalid")
    monkeypatch.setattr("canvas_bridge.network.outbound_limits", lambda: limits)
    transport = PublicTransport()
    transport.pool = Pool()
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(mode="production_approved"))
    usage = UsageBinding(
        governor,
        b"fictional-key",
        owner="owner",
        tenant="tenant",
        token="fixture-token",
        mode="production_approved",
    )
    async with httpx.AsyncClient(transport=transport) as client:
        guarded = GuardedHTTP(client, lambda *_: None, usage=usage)
        with pytest.raises(DomainError):
            await guarded.send(httpx.Request("GET", "https://canvas.invalid/api/v1/courses"))
    occupied.close()
    assert transport.pool.calls == 0
    assert governor.report()["available"] == 100
    assert governor.report()["operations"][0]["estimated_units"] == 0
    assert governor.report()["operations"][0]["attempts"] == 0
    with ledger.connect() as db:
        assert db.scalar(select(m.attempts.c.state)) == "CANCELLED_BEFORE_SEND"


@pytest.mark.parametrize("case", ["resume", "revoked", "long_delay"])
async def test_bounded_cooldown_wait_reauthorizes_without_reserving(ledger, monkeypatch, case):
    from canvas_bridge.network import GuardedHTTP
    from canvas_bridge.usage.transport import UsageBinding

    now, permitted, waits, sends = [datetime.now(UTC).timestamp()], [True], [], []
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now[0])
    usage = UsageBinding(
        governor, b"fictional-key", owner="o", tenant="t", token="fake", mode="offline_synthetic"
    )

    def authorize(*_):
        if not permitted[0]:
            raise DomainError("permission_denied", "Fixture authorization revoked")

    def handle(request):
        sends.append(request)
        return httpx.Response(
            503 if len(sends) == 1 else 200,
            headers={"Retry-After": "9999" if case == "long_delay" else "1"},
        )

    async def sleep(delay):
        assert governor.report()["reserved"] == 0
        waits.append(delay)
        now[0] += delay
        permitted[0] = case != "revoked"

    monkeypatch.setattr("canvas_bridge.usage.transport.asyncio.sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        guarded = GuardedHTTP(http, authorize, usage=usage)
        url = "https://canvas.invalid/api/v1/courses"
        await guarded.send(httpx.Request("GET", url))
        if case == "resume":
            response = await guarded.send(httpx.Request("GET", url))
            assert response.status_code == 200 and len(sends) == 2
            assert waits == [1.005]
        else:
            with pytest.raises(DomainError) as error:
                await guarded.send(httpx.Request("GET", url))
            if case == "long_delay":
                assert error.value.data["retry_after_seconds"] == 9999
            assert len(sends) == 1
            assert bool(waits) is (case == "revoked")
    assert governor.report()["uncertain"] == 1
    assert governor.report()["reserved"] == 0


async def test_request_coalescing_integrates_with_canvas_authorization(bridge):
    requests = []

    async def handle(request):
        requests.append(request)
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={"id": 3, "name": "Fictional assignment"})

    token = request_authorization.set(RequestAuthorization("get_assignment_details"))
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            clients = [
                CanvasClient(
                    bridge.registry.require("synthetic", True), "fake", bridge.settings, http
                )
                for _ in range(10)
            ]
            for client in clients:
                client.bind_usage(bridge, "fixture", scope="epoch-one")
            results = await asyncio.gather(
                *(c.one(Endpoint.ASSIGNMENT, course="1", assignment="3") for c in clients)
            )
            assert len(results) == 10 and len(requests) == 1
            assert bridge.usage.report()["settled"] == 1
    finally:
        request_authorization.reset(token)


async def test_fair_queue_rotates_owners_and_does_not_starve_sync():
    queue, order = FairQueue(capacity=1), []
    first = await queue.acquire("occupant", "interactive")

    async def work(owner, workload):
        ticket = await queue.acquire(owner, workload)
        order.append((owner, workload))
        await asyncio.sleep(0)
        ticket.close()

    tasks = [asyncio.create_task(work("runaway", "interactive")) for _ in range(10)]
    tasks += [
        asyncio.create_task(work("second", "interactive")),
        asyncio.create_task(work("sync", "scheduled_sync")),
    ]
    await asyncio.sleep(0)
    first.close()
    await asyncio.gather(*tasks)
    assert order.index(("second", "interactive")) < 4
    assert order.index(("sync", "scheduled_sync")) < 7
    assert queue.active == 0


def test_uncertain_attempt_refund_requires_verified_statement(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    attempt = spend(governor, status=429)
    statement = VendorStatement(
        statement_id="verified-failure",
        contract_id="synthetic-fixture",
        cycle=governor.report()["id"],
        total_units=0,
        as_of=datetime.now(UTC),
        status="final",
        settlements={attempt.attempt_id: 0},
        evidence_sha256="1" * 64,
        reason="verified_nonbillable",
    )
    governor.reconcile(statement, "operator")
    assert governor.report()["uncertain"] == 0
    assert governor.report()["available"] == 100
    governor.reconcile(statement, "operator")
    assert governor.report()["available"] == 100


def test_lagging_invoice_cannot_hide_external_usage_with_later_calls(ledger):
    now = [datetime(2026, 10, 1, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now[0])
    spend(governor)
    cutoff = datetime.fromtimestamp(now[0], UTC)
    now[0] += 86400
    for _ in range(9):
        spend(governor)
    statement = VendorStatement(
        statement_id="lagged-report",
        contract_id="synthetic-fixture",
        cycle=governor.report()["id"],
        total_units=5,
        as_of=cutoff,
        status="verified",
        evidence_sha256="4" * 64,
        reason="external_usage",
    )
    governor.reconcile(statement, "operator")
    assert governor.report()["external"] == 4
    assert governor.report()["available"] == 86
    governor.reconcile(statement, "operator")
    assert governor.report()["available"] == 86


def test_reservation_cannot_cross_contract_cycle_before_send(ledger):
    from tests.test_usage_governor import reserve

    now = [datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now[0])
    attempt = ctx()
    reserve(governor, attempt)
    now[0] += 2
    with pytest.raises(DomainError) as exc:
        governor.sent(attempt.attempt_id, lambda: None)
    assert exc.value.reason_code == "WORKLOAD_POOL_DEFERRED"
    governor.finish(attempt.attempt_id, failed=True)
    assert governor.report()["available"] == 100
    spend(governor)
    assert governor.report()["settled"] == 1


def test_late_statement_after_detail_retention_uses_durable_aggregate(ledger):
    now = [datetime(2026, 6, 15, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now[0])
    spend(governor)
    period = governor.report()["id"]
    now[0] = datetime(2026, 10, 20, tzinfo=UTC).timestamp()
    governor.recover()
    with ledger.connect() as db:
        assert db.scalar(select(m.attempts.c.id)) is None
    governor.reconcile(
        VendorStatement(
            statement_id="delayed-final",
            contract_id="synthetic-fixture",
            cycle=period,
            total_units=1,
            as_of=datetime.fromtimestamp(now[0], UTC),
            status="final",
            evidence_sha256="5" * 64,
            reason="verified_vendor_total",
        ),
        "operator",
    )
    report = governor.report(cycle=period)
    assert report["settled"] == 1 and report["external"] == 0
    assert report["available"] == 99 and not report["quarantined"]


def test_accounting_quarantine_survives_cycle_rollover(ledger):
    now = [datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC).timestamp()]
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy(), clock=lambda: now[0])
    with pytest.raises(DomainError):
        spend(governor, actual_units=5)
    now[0] += 2
    with pytest.raises(DomainError) as exc:
        spend(governor)
    assert exc.value.reason_code == "UPSTREAM_BUDGET_EXHAUSTED"
    assert governor.report()["contract_quarantined"] is True


@pytest.mark.parametrize("failure", ["accounting", "throttle"])
def test_reserved_attempt_rechecks_new_stop_before_send(ledger, failure):
    from tests.test_usage_governor import reserve

    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    first, second = ctx(token_key="shared"), ctx(token_key="shared")
    reserve(governor, first)
    reserve(governor, second)
    governor.sent(first.attempt_id, lambda: None)
    if failure == "accounting":
        with pytest.raises(DomainError):
            governor.finish(first.attempt_id, status=200, actual_units=5)
    else:
        governor.finish(first.attempt_id, status=429, headers={"retry-after": "100"})
    with pytest.raises(DomainError) as exc:
        governor.sent(second.attempt_id, lambda: None)
    assert exc.value.reason_code == (
        "UPSTREAM_BUDGET_EXHAUSTED" if failure == "accounting" else "UPSTREAM_THROTTLED"
    )
    governor.finish(second.attempt_id, failed=True)
    assert governor.report()["reserved"] == 0
    assert governor.report()["uncertain"] == 1
    with ledger.connect() as db:
        assert (
            db.scalar(select(m.attempts.c.state).where(m.attempts.c.id == second.attempt_id))
            == "CANCELLED_BEFORE_SEND"
        )


def test_restore_never_mints_new_capacity(ledger):
    governor = UpstreamUsageGovernor(ledger, fixture_policy=policy())
    spend(governor)
    with ledger.connect() as db:
        records = {
            t.name: [dict(r) for r in db.execute(select(t)).mappings()]
            for t in m.metadata.sorted_tables
            if t is not m.lock
        }
    target = create_engine("sqlite:///:memory:")
    m.metadata.create_all(target)
    restored = UpstreamUsageGovernor(target, fixture_policy=policy())
    with target.begin() as db:
        restored.restore_history(db, records)
    with pytest.raises(DomainError) as exc:
        spend(restored)
    assert exc.value.reason_code == "GOVERNOR_UNAVAILABLE"
    statement = VendorStatement(
        statement_id="restore-checkpoint",
        contract_id="synthetic-fixture",
        cycle=restored.report()["id"],
        total_units=8,
        as_of=datetime.now(UTC),
        status="final",
        evidence_sha256="2" * 64,
        reason="verified_restore_checkpoint",
        release_restore_hold=True,
    )
    restored.reconcile(statement, "operator")
    spend(restored)
    assert restored.report()["available"] == 91
    target.dispose()


def test_standalone_migration_creates_accounting_tables(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "migrated.db"))
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path("migrations/versions/f17a6b204c31_api_usage_governor.py")
    spec = importlib.util.spec_from_file_location("usage_migration_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
    inspector = inspect(engine)
    for name, table in m.metadata.tables.items():
        assert {c.name for c in table.columns} == {c["name"] for c in inspector.get_columns(name)}
    engine.dispose()


@pytest.mark.postgres
def test_postgres_governor_100_contenders_and_durable_restart(settings):
    from concurrent.futures import ThreadPoolExecutor

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL must identify a disposable PostgreSQL database.")
    schema = "fixture_usage_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f"CREATE SCHEMA {schema}"))
    isolated = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = create_engine(isolated)
    try:
        # Exercise the shipped migration, not only metadata.create_all.
        config = Config()
        config.set_main_option("script_location", "migrations")
        config.attributes["database_url"] = isolated
        config.attributes["vault_key_file"] = settings.vault_key_file
        command.upgrade(config, "head")

        def attempt(_):
            governor = UpstreamUsageGovernor(engine, fixture_policy=policy(25))
            try:
                spend(governor, ctx(owner_id=uuid4().hex))
                return 1
            except DomainError as exc:
                assert exc.reason_code == "UPSTREAM_BUDGET_EXHAUSTED"
                return 0

        with ThreadPoolExecutor(max_workers=20) as pool:
            assert sum(pool.map(attempt, range(100))) == 25
        assert UpstreamUsageGovernor(engine).report()["settled"] == 25
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.mark.parametrize("stage", ["queued", "reserved", "send", "body"])
async def test_cancel_then_serial_request_releases_inventory_capacity(ledger, monkeypatch, stage):
    from canvas_bridge.network import GuardedHTTP
    from canvas_bridge.usage.transport import UsageBinding

    governor = UpstreamUsageGovernor(
        ledger,
        fixture_policy=policy(
            allocation={"pool_mode": "priority_weighted_fair_queue"},
            limits={"max_concurrency_per_token": 1},
        ),
    )
    usage = UsageBinding(
        governor,
        b"synthetic-key",
        owner="owner",
        tenant="tenant",
        token="fixture",
        mode="offline_synthetic",
    )
    entered = asyncio.Event()
    first = True

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"fixture"

    async def handle(request):
        if first and stage == "send":
            entered.set()
            await asyncio.Event().wait()
        if first and stage == "body":
            return httpx.Response(200, stream=Body())
        return httpx.Response(200, json=[])

    sent = governor.sent

    def mark_sent(*args):
        if first and stage == "reserved":
            raise asyncio.CancelledError
        return sent(*args)

    monkeypatch.setattr(governor, "sent", mark_sent)
    queue = FairQueue()
    governor.queues[asyncio.get_running_loop()] = queue
    holder = await queue.acquire(usage.owner, "interactive") if stage == "queued" else None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        guarded = GuardedHTTP(client, lambda *_: None, usage=usage)

        async def read():
            async with guarded.stream("GET", "https://canvas.invalid/api/v1/courses") as response:
                return await response.aread()

        task = asyncio.create_task(read())
        if stage == "queued":
            await asyncio.sleep(0)
            assert queue.pending["interactive"]
        if stage in {"send", "body"}:
            await asyncio.wait_for(entered.wait(), 5)
        if stage != "reserved":
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        if holder:
            holder.close()
        assert queue.active == 0 and not queue.owners
        with ledger.connect() as db:
            states = list(db.scalars(select(m.attempts.c.state)))
        assert (
            states
            == {
                "queued": [],
                "reserved": ["CANCELLED_BEFORE_SEND"],
                "send": ["UNCERTAIN"],
                "body": ["UNCERTAIN"],
            }[stage]
        )
        first = False
        assert await read() == b"[]"
        assert governor.report()["reserved"] == 0


@pytest.mark.parametrize("cancel_leader", [False, True])
async def test_shared_reader_cancellation_and_attempt_accounting(bridge, cancel_leader):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handle(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"id": 3})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:

        async def read():
            client = CanvasClient(
                bridge.registry.require("synthetic", True), "fake", bridge.settings, http
            )
            client.bind_usage(bridge, "fixture", scope="epoch-one")
            token = request_authorization.set(RequestAuthorization("get_assignment_details"))
            try:
                return await client.one(Endpoint.ASSIGNMENT, course="1", assignment="3")
            finally:
                request_authorization.reset(token)

        leader = asyncio.create_task(read())
        await asyncio.wait_for(entered.wait(), 5)
        follower = asyncio.create_task(read())
        await asyncio.sleep(0)
        assert [count for _, count in bridge.upstream_cache.flights.values()] == [1]
        cancelled, survivor = (leader, follower) if cancel_leader else (follower, leader)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        release.set()
        if cancel_leader:
            with pytest.raises(DomainError) as interrupted:
                await survivor
            assert interrupted.value.reason_code == "SHARED_READ_INTERRUPTED"
            assert interrupted.value.status == "retry_later"
        else:
            assert (await survivor)["id"] == 3
        assert not bridge.upstream_cache.flights
        assert (await read())["id"] == 3
        with bridge.usage.transaction() as db:
            states = list(db.scalars(select(m.attempts.c.state)))
        assert sorted(states) == sorted(["UNCERTAIN" if cancel_leader else "SETTLED", "SETTLED"])
