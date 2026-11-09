"""Serialize course reads and membership refreshes, without caching authority.

PostgreSQL session locks also coordinate separate application/operator processes.
Revocations and selection changes remain independent and the response fence still
checks them. SQLite synthetic fixtures use the process-local guard only.
"""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from contextvars import ContextVar

from canvas_bridge.domain import DomainError

_held = ContextVar("connection_read_guard", default=())


async def _thread_call(fn):
    # Psycopg async mode cannot run on Windows' default Proactor event loop.
    # Finish a short database call before closing its connection on cancellation.
    work = asyncio.create_task(asyncio.to_thread(fn))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await asyncio.shield(work)
        raise


@asynccontextmanager
async def connection_read_guard(bridge, owner, ref, *, wait_seconds=60):
    if not ref:
        yield
        return
    engine = bridge.store.engine
    key = (id(engine), owner, ref)
    task = asyncio.current_task()
    # A child task inherits ContextVars but must not inherit lock ownership.
    if (key, task) in _held.get():
        yield
        return
    lock = bridge.lock("authorization-read:" + owner + ":" + ref)
    acquired = False
    holder = {}
    token = None
    started = asyncio.get_running_loop().time()
    try:
        try:
            async with asyncio.timeout(wait_seconds):
                await lock.acquire()
                acquired = True
                if engine.dialect.name == "postgresql":
                    import psycopg

                    from canvas_bridge.maintenance import LOCK_ID

                    url = engine.url.set(drivername="postgresql").render_as_string(
                        hide_password=False
                    )

                    def connect():
                        holder["connection"] = psycopg.connect(
                            url,
                            autocommit=True,
                            connect_timeout=5,
                            options="-c statement_timeout=5000",
                        )

                    await _thread_call(connect)
                    connection = holder["connection"]

                    def try_lock(sql, key):
                        return connection.execute(sql, (key,)).fetchone()[0]

                    if not await _thread_call(
                        lambda: try_lock("SELECT pg_try_advisory_lock_shared(%s)", LOCK_ID)
                    ):
                        raise DomainError(
                            "retry_later",
                            "Database maintenance is active.",
                            reason_code="AUTHORIZATION_BUSY",
                        )
                    digest = hashlib.sha256(
                        ("canvas-read-v1\0" + owner + "\0" + ref).encode()
                    ).digest()
                    advisory_key = int.from_bytes(digest[:8], "big", signed=True)
                    while not await _thread_call(  # noqa: ASYNC110 - PostgreSQL lock holders have no asyncio event.
                        lambda: try_lock("SELECT pg_try_advisory_lock(%s)", advisory_key)
                    ):
                        await asyncio.sleep(0.1)
        except TimeoutError as exc:
            raise DomainError(
                "retry_later",
                "Another request is using this Canvas connection. Retry after it finishes.",
                reason_code="AUTHORIZATION_BUSY",
                details={
                    "deadline_seconds": wait_seconds,
                    "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000),
                },
            ) from exc
        token = _held.set((*_held.get(), (key, task)))
        yield
    finally:
        if token is not None:
            _held.reset(token)
        try:
            if "connection" in holder:
                # Close releases both session locks, including on cancellation.
                await _thread_call(holder["connection"].close)
        finally:
            if acquired:
                lock.release()
