import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from canvas_bridge.connection_guard import connection_read_guard
from canvas_bridge.domain import DomainError, Result


async def test_failed_parallel_refresh_waits_until_reader_finishes(
    bridge, owner, seeded, monkeypatch
):
    entered = asyncio.Event()
    refresh = AsyncMock(return_value=Result(status="partial_data", summary="Unavailable"))
    monkeypatch.setattr(bridge, "_list_courses_locked", refresh)

    async def other_session():
        entered.set()
        return await bridge.list_courses(owner, seeded)

    async with connection_read_guard(bridge, owner, seeded):
        task = asyncio.create_task(other_session())
        await entered.wait()
        await asyncio.sleep(0)
        refresh.assert_not_awaited()
        bridge.selected(owner, seeded)  # Other session cannot invalidate this read's lease.
        async with connection_read_guard(bridge, owner, seeded):
            pass  # Same-task nested refresh must not deadlock.
    await task
    refresh.assert_awaited_once()


async def test_busy_timeout_does_not_invalidate_scope(bridge, owner, seeded):
    async def contender():
        with pytest.raises(DomainError) as caught:
            async with connection_read_guard(bridge, owner, seeded, wait_seconds=0.01):
                pytest.fail("contender entered the critical section")
        assert caught.value.reason_code == "AUTHORIZATION_BUSY"

    async with connection_read_guard(bridge, owner, seeded):
        await asyncio.create_task(contender())
        bridge.selected(owner, seeded)


async def test_cancellation_releases_guard(bridge, owner, seeded):
    entered = asyncio.Event()

    async def reader():
        async with connection_read_guard(bridge, owner, seeded):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(reader())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with connection_read_guard(bridge, owner, seeded, wait_seconds=0.01):
        bridge.selected(owner, seeded)


async def test_guard_does_not_hide_revocation(bridge, owner, seeded):
    async with connection_read_guard(bridge, owner, seeded):
        with bridge.store.transaction() as db:
            bridge.store.connection(db, owner, seeded).entitlement_at = None
        with pytest.raises(DomainError) as caught:
            bridge.selected(owner, seeded)
        assert caught.value.reason_code == "STALE_SCOPE_SNAPSHOT"


async def test_unrelated_connection_is_not_blocked(bridge, owner, seeded):
    async def other_connection():
        async with connection_read_guard(bridge, owner, "other", wait_seconds=0.01):
            return True

    async with connection_read_guard(bridge, owner, seeded):
        assert await asyncio.create_task(other_connection())


@pytest.mark.parametrize("blocked", [True, False])
async def test_postgres_session_lock_cleanup(monkeypatch, blocked):
    import psycopg
    from sqlalchemy.engine import make_url

    connections = []

    class Session:
        closed = False

        def execute(self, sql, values):
            assert len(values) == 1 and type(values[0]) is int
            allowed = "shared" in sql or not blocked
            return SimpleNamespace(fetchone=lambda: (allowed,))

        def close(self):
            self.closed = True

    def connect(*args, **kwargs):
        session = Session()
        connections.append(session)
        return session

    monkeypatch.setattr(psycopg, "connect", connect)
    locks = {}
    bridge = SimpleNamespace(
        store=SimpleNamespace(
            engine=SimpleNamespace(
                dialect=SimpleNamespace(name="postgresql"),
                url=make_url("postgresql+psycopg://synthetic@localhost/fixture"),
            )
        ),
        lock=lambda key: locks.setdefault(key, asyncio.Lock()),
    )
    if blocked:
        with pytest.raises(DomainError, match="Another request"):
            async with connection_read_guard(bridge, "owner", "connection", wait_seconds=0.02):
                pytest.fail("blocked lock acquired")
    else:
        entered = asyncio.Event()

        async def reader():
            async with connection_read_guard(bridge, "owner", "connection"):
                async with connection_read_guard(bridge, "owner", "connection"):
                    assert len(connections) == 1
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(reader())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(connections) == 1 and connections[0].closed
    assert not any(lock.locked() for lock in locks.values())


def test_busy_error_survives_safe_release_without_arbitrary_details():
    from canvas_bridge.egress_errors import safe_error_result

    result = safe_error_result(
        Result(
            status="retry_later",
            summary="untrusted text",
            data={
                "reason_code": "AUTHORIZATION_BUSY",
                "private_details": "must not escape",
            },
        )
    )
    assert result.data == {
        "reason_code": "AUTHORIZATION_BUSY",
        "error_origin": "bridge_authorization",
        "recommended_action": "wait_for_active_request_then_retry",
        "retry_condition": "active_request_finished",
    }
    assert "Reconnecting is not required" in result.summary
    assert "must not escape" not in result.model_dump_json()
