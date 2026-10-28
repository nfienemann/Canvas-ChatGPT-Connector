"""Bounded process-local admission; no credentials, URLs or approval decisions stored."""

import math
import time
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

from canvas_bridge.domain import DomainError


def retry_after(value, *, wall_time=time.time):
    """Honor seconds or HTTP dates. Never shorten a provider's requested delay."""
    if not value or len(value) > 128:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = date.replace(tzinfo=date.tzinfo or UTC).timestamp() - wall_time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


@dataclass
class Bucket:
    tokens: float
    updated: float
    active: int = 0
    failures: int = 0
    blocked_until: float = 0
    probe: bool = False
    generation: int = 0


class RequestLimits:
    """Atomic within one event loop, with no unbounded waiting queue.

    Hosts are validated before admission. Keys must never be raw model arguments.
    A live deployment with multiple processes needs an additional shared ingress
    quota; these limits still apply independently inside every process.
    """

    def __init__(
        self,
        *,
        total=16,
        per_key=4,
        burst=40,
        rate=5,
        max_keys=1024,
        threshold=5,
        recovery=30,
        clock=time.monotonic,
        wall_time=time.time,
    ):
        self.total, self.per_key, self.burst, self.rate = total, per_key, burst, rate
        self.max_keys, self.threshold, self.recovery = max_keys, threshold, recovery
        self.clock, self.wall_time = clock, wall_time
        self.active = 0
        self.buckets = {}

    def acquire(self, key):
        now = self.clock()
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= self.max_keys:
                # Never evict active leases, open circuits or provider cooldowns.
                self.buckets = {
                    k: b
                    for k, b in self.buckets.items()
                    if b.active or b.blocked_until > now or now - b.updated < 3600
                }
            if len(self.buckets) >= self.max_keys:
                self.deny()
            bucket = self.buckets[key] = Bucket(self.burst, now)
        bucket.tokens = min(self.burst, bucket.tokens + max(0, now - bucket.updated) * self.rate)
        bucket.updated = now
        if (
            self.active >= self.total
            or bucket.active >= self.per_key
            or bucket.tokens < 1
            or bucket.blocked_until > now
            or bucket.probe
            or (bucket.failures >= self.threshold and bucket.active)
        ):
            self.deny()
        bucket.tokens -= 1
        bucket.active += 1
        self.active += 1
        bucket.probe = bucket.failures >= self.threshold
        return Lease(self, bucket)

    @staticmethod
    def deny():
        raise DomainError(
            "retry_later",
            "Request capacity is temporarily unavailable. Try again later.",
            reason_code="RATE_LIMITED",
        )


class Lease:
    def __init__(self, limits, bucket):
        self.limits, self.bucket = limits, bucket
        self.closed = False
        self.generation = bucket.generation

    def response(self, status, headers):
        b, limits = self.bucket, self.limits
        delay = retry_after(headers.get("retry-after"), wall_time=limits.wall_time)
        if status == 429 or status >= 500:
            self.failure()
            b.blocked_until = max(
                b.blocked_until,
                limits.clock() + (delay if delay is not None else 1 if status == 429 else 0),
            )
        else:
            # An older concurrent success must not clear a newly opened circuit.
            if self.generation == b.generation:
                b.failures = 0
        try:
            remaining = float(headers.get("x-rate-limit-remaining", "inf"))
        except ValueError:
            remaining = math.inf
        if remaining <= 0:
            b.blocked_until = max(
                b.blocked_until, limits.clock() + (delay if delay is not None else 1)
            )

    def failure(self):
        self.bucket.generation += 1
        self.bucket.failures += 1
        if self.bucket.failures >= self.limits.threshold:
            self.bucket.blocked_until = max(
                self.bucket.blocked_until, self.limits.clock() + self.limits.recovery
            )

    def close(self):
        if not self.closed:
            self.closed = True
            self.bucket.active -= 1
            self.limits.active -= 1
            self.bucket.probe = False


class AdmissionMiddleware:
    """Bound all HTTP work, including unauthenticated/JWKS and download routes."""

    def __init__(self, app, limits=None, deadline_seconds=240):
        self.app = app
        self.limits = limits or RequestLimits(total=32, per_key=32, burst=120, rate=20)
        self.deadline_seconds = deadline_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            lease = self.limits.acquire("http")
        except DomainError:
            from starlette.responses import JSONResponse

            return await JSONResponse(
                {"error": "Service capacity temporarily unavailable."},
                status_code=429,
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )(scope, receive, send)
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            import asyncio

            async with asyncio.timeout(self.deadline_seconds):
                return await self.app(scope, receive, guarded_send)
        except TimeoutError:
            if started:
                # An incomplete streaming response must be closed by the server.
                raise
            from starlette.responses import JSONResponse

            return await JSONResponse(
                {"error": "Request deadline exceeded."},
                status_code=504,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
        finally:
            lease.close()
