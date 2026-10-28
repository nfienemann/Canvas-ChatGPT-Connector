import asyncio
from datetime import UTC, datetime
from email.utils import format_datetime

import httpcore
import httpx
import pytest

from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError
from canvas_bridge.network import (
    CoreStream,
    GuardedHTTP,
    PublicTransport,
    network_permit,
    outbound_limits,
)
from canvas_bridge.policy import Endpoint
from canvas_bridge.request_limits import AdmissionMiddleware, RequestLimits, retry_after


class Clock:
    value = 1000.0

    def __call__(self):
        return self.value


def limited(**kwargs):
    clock = Clock()
    return RequestLimits(clock=clock, wall_time=clock, **kwargs), clock


@pytest.mark.parametrize(
    "value,expected",
    [
        ("60", 60),
        ("0", 0),
        ("-1", 0),
        ("nan", None),
        ("inf", None),
        ("bad", None),
        ("9" * 129, None),
        (None, None),
    ],
)
def test_retry_delay_is_finite_and_bounded_input(value, expected):
    assert retry_after(value) == expected


def test_http_date_and_large_retry_delay_not_shortened():
    limits, clock = limited()
    date = format_datetime(datetime.fromtimestamp(clock() + 3600, UTC), usegmt=True)
    assert retry_after(date, wall_time=clock) == 3600
    lease = limits.acquire("approved.invalid")
    lease.response(429, {"retry-after": date})
    lease.close()
    clock.value += 3599
    with pytest.raises(DomainError):
        limits.acquire("approved.invalid")
    clock.value += 1
    limits.acquire("approved.invalid").close()


def test_concurrency_is_global_and_per_key_and_releases_once():
    limits, _ = limited(total=2, per_key=1)
    first = limits.acquire("one")
    with pytest.raises(DomainError):
        limits.acquire("one")
    second = limits.acquire("two")
    with pytest.raises(DomainError):
        limits.acquire("three")
    first.close()
    first.close()
    second.close()
    assert limits.active == 0


def test_token_bucket_and_memory_are_bounded():
    limits, clock = limited(burst=1, rate=1, max_keys=1)
    limits.acquire("one").close()
    with pytest.raises(DomainError):
        limits.acquire("one")
    clock.value += 1
    limits.acquire("one").close()
    with pytest.raises(DomainError):
        limits.acquire("two")
    clock.value += 3601
    limits.acquire("two").close()
    assert len(limits.buckets) == 1


def test_circuit_breaker_single_probe_and_recovery():
    limits, clock = limited(threshold=2)
    for _ in range(2):
        lease = limits.acquire("one")
        lease.response(503, {})
        lease.close()
    with pytest.raises(DomainError):
        limits.acquire("one")
    clock.value += 30
    probe = limits.acquire("one")
    with pytest.raises(DomainError):
        limits.acquire("one")
    probe.response(200, {})
    probe.close()
    limits.acquire("one").close()


def test_old_success_cannot_reset_new_circuit_and_cooldown_not_evicted():
    limits, clock = limited(threshold=1, max_keys=1)
    old = limits.acquire("one")
    failed = limits.acquire("one")
    failed.response(503, {"retry-after": "10000"})
    failed.close()
    old.response(200, {})
    old.close()
    assert limits.buckets["one"].failures == 1
    clock.value += 4000
    with pytest.raises(DomainError):
        limits.acquire("two")
    with pytest.raises(DomainError):
        limits.acquire("one")


def test_rate_remaining_zero_defers_new_work():
    limits, clock = limited()
    lease = limits.acquire("one")
    lease.response(200, {"x-rate-limit-remaining": "0"})
    lease.close()
    with pytest.raises(DomainError):
        limits.acquire("one")
    clock.value += 1
    limits.acquire("one").close()


class Stream:
    async def __aiter__(self):
        yield b"synthetic"

    async def aclose(self):
        pass


class Pool:
    def __init__(self, status=200, headers=None):
        self.calls = 0
        self.status, self.headers = status, headers or []

    async def handle_async_request(self, request):
        self.calls += 1
        return httpcore.Response(self.status, headers=self.headers, content=Stream())

    async def aclose(self):
        pass


async def test_transport_limits_share_clients_and_hold_stream_until_close(monkeypatch):
    limits, _ = limited(total=1)
    monkeypatch.setattr("canvas_bridge.network.outbound_limits", lambda: limits)
    transports = [PublicTransport(), PublicTransport()]
    for transport in transports:
        transport.pool = Pool()
    async with (
        httpx.AsyncClient(transport=transports[0]) as a,
        httpx.AsyncClient(transport=transports[1]) as b,
    ):
        ga, gb = GuardedHTTP(a, lambda *_: None), GuardedHTTP(b, lambda *_: None)
        response = await ga.send(httpx.Request("GET", "https://one.invalid"), stream=True)
        with pytest.raises(DomainError):
            await gb.send(httpx.Request("GET", "https://two.invalid"), stream=True)
        assert transports[1].pool.calls == 0
        await response.aclose()
        async with gb.stream("GET", "https://two.invalid") as response:
            assert await response.aread() == b"synthetic"
    assert limits.active == 0 and network_permit.get() is None


async def test_transport_unapproved_request_cannot_consume_capacity_or_send():
    transport = PublicTransport()
    transport.pool = Pool()
    with pytest.raises(DomainError):
        await transport.handle_async_request(httpx.Request("GET", "https://one.invalid"))
    assert transport.pool.calls == 0 and outbound_limits().active == 0


async def test_cancelled_network_releases_admission(monkeypatch):
    limits, _ = limited()
    monkeypatch.setattr("canvas_bridge.network.outbound_limits", lambda: limits)
    transport = PublicTransport()
    entered = asyncio.Event()

    class WaitingPool(Pool):
        async def handle_async_request(self, request):
            entered.set()
            await asyncio.Event().wait()

    transport.pool = WaitingPool()
    async with httpx.AsyncClient(transport=transport) as http:
        guarded = GuardedHTTP(http, lambda *_: None)
        task = asyncio.create_task(guarded.send(httpx.Request("GET", "https://one.invalid")))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert limits.active == 0 and network_permit.get() is None


async def test_long_retry_after_stops_canvas_retry_loop(bridge):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(
            bridge.registry.require("synthetic", True), "synthetic-token", bridge.settings, http
        )
        with pytest.raises(DomainError):
            await client.one(Endpoint.FILE, course="11", file="1")
    assert len(calls) == 1


async def test_ingress_applies_to_auth_download_and_unknown_routes_without_header_keys():
    limits, clock = limited(burst=1)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=AdmissionMiddleware(app, limits)), base_url="http://test"
    ) as http:
        assert (await http.get("/settings/callback")).status_code == 200
        for path in ("/mcp", "/downloads/guessed", "/unknown"):
            response = await http.get(
                path, headers={"X-Forwarded-For": "127.0.0.2", "Authorization": "Bearer secret"}
            )
            assert response.status_code == 429
            assert "secret" not in response.text
        clock.value += 1
        assert (await http.get("/health")).status_code == 200
    assert limits.active == 0 and list(limits.buckets) == ["http"]


async def test_file_lock_survives_waiters_and_retention_sweep(bridge):
    key = "file:synthetic:1"
    lock = bridge.lock(key)
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)
    lock.release()
    await bridge.retention.sweep()
    assert bridge.lock(key) is lock
    await waiter
    lock.release()


async def test_body_deadline_stops_slow_stream_and_frees_slot():
    limits, _ = limited()

    class SlowStream(Stream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"unreachable"

    stream = CoreStream(SlowStream(), limits.acquire("one"), asyncio.get_running_loop().time())
    with pytest.raises(httpx.ReadTimeout):
        async for _ in stream:
            pytest.fail("Expired stream cannot yield bytes")
    await stream.aclose()
    assert limits.active == 0 and limits.buckets["one"].failures == 1


async def test_ingress_total_deadline_cancels_slow_handler_without_leaking_details():
    limits, _ = limited()
    cancelled = asyncio.Event()

    async def stalled(scope, receive, send):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    app = AdmissionMiddleware(stalled, limits, deadline_seconds=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post("/settings/callback?code=secret")
    assert response.status_code == 504 and "secret" not in response.text
    assert cancelled.is_set() and limits.active == 0
