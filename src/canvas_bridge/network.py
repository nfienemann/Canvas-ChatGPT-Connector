"""Outbound transport resolves once, rejects non-public IPs, then connects to
the validated numeric address while TLS verifies the original hostname.
"""

import asyncio
import logging
import socket
import ssl
from contextlib import asynccontextmanager
from contextvars import ContextVar
from weakref import WeakKeyDictionary

import httpcore
import httpx

from canvas_bridge.domain import DomainError
from canvas_bridge.policy import public_ip
from canvas_bridge.request_limits import RequestLimits

network_permit = ContextVar("network_permit", default=None)
_loop_limits = WeakKeyDictionary()


def outbound_limits():
    # Every client, retry, download and identity request shares one process quota.
    loop = asyncio.get_running_loop()
    if loop not in _loop_limits:
        _loop_limits[loop] = RequestLimits()
    return _loop_limits[loop]


def deny_network():
    raise DomainError(
        "permission_denied",
        "An authorized request context is required for external access.",
        reason_code="POLICY_CONTEXT_REQUIRED",
    )


class GuardedHTTP:
    """Every send (including mock transports, retries and redirects) is fenced."""

    def __init__(self, client, check):
        self._client, self._check = client, check

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self._check(method, str(url))
        token = network_permit.set((method, str(url)))
        try:
            async with self._client.stream(method, url, **kwargs) as response:
                yield response
        finally:
            network_permit.reset(token)

    async def send(self, request, **kwargs):
        self._check(request.method, str(request.url))
        token = network_permit.set((request.method, str(request.url)))
        try:
            return await self._client.send(request, **kwargs)
        finally:
            network_permit.reset(token)

    async def aclose(self):
        await self._client.aclose()


def infrastructure_http(client, *, method, url):
    """Exact identity/credential-cleanup endpoint; cannot fetch academic content."""

    def check(actual_method, actual_url):
        if actual_method != method or actual_url != url:
            deny_network()

    return GuardedHTTP(client, check)


class PublicBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host,
        port,
        timeout=None,
        local_address=None,
        socket_options=None,  # noqa: ASYNC109
    ):
        if port != 443:
            raise DomainError("permission_denied", "Only outbound HTTPS is permitted.")
        async with asyncio.timeout(min(timeout or 8, 8)):
            addresses = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        if not addresses or any(not public_ip(item[4][0]) for item in addresses):
            raise DomainError("permission_denied", "Non-public outbound address blocked.")
        return await self.backend.connect_tcp(
            addresses[0][4][0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):  # noqa: ASYNC109
        raise DomainError("permission_denied", "Unix socket access is not permitted.")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class CoreStream(httpx.AsyncByteStream):
    def __init__(self, stream, lease, deadline):
        self.stream, self.lease = stream, lease
        self.deadline = deadline

    async def __aiter__(self):
        try:
            async with asyncio.timeout_at(self.deadline):
                async for chunk in self.stream:
                    yield chunk
        except TimeoutError as exc:
            self.lease.failure()
            raise httpx.ReadTimeout("Upstream stream deadline exceeded.") from exc
        except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError) as exc:
            self.lease.failure()
            raise httpx.ReadError("Upstream stream unavailable.") from exc

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            self.lease.close()


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicBackend(),
            max_connections=20,
            retries=0,
        )

    async def handle_async_request(self, request):
        if network_permit.get() != (request.method, str(request.url)):
            deny_network()
        lease = outbound_limits().acquire(request.url.host)
        deadline = asyncio.get_running_loop().time() + 90
        handed_off = False
        try:
            async with asyncio.timeout(15):
                response = await self.pool.handle_async_request(
                    httpcore.Request(
                        method=request.method,
                        url=httpcore.URL(
                            scheme=request.url.raw_scheme,
                            host=request.url.raw_host,
                            port=request.url.port,
                            target=request.url.raw_path,
                        ),
                        headers=request.headers.raw,
                        content=request.stream,
                        extensions=request.extensions,
                    )
                )
            lease.response(response.status, httpx.Headers(response.headers))
            result = httpx.Response(
                response.status,
                headers=response.headers,
                stream=CoreStream(response.stream, lease, deadline),
                extensions=response.extensions,
            )
            handed_off = True
            return result
        except (
            httpcore.NetworkError,
            httpcore.TimeoutException,
            httpcore.ProtocolError,
            TimeoutError,
        ) as exc:
            lease.failure()
            raise httpx.RequestError("Upstream transport unavailable.", request=request) from exc
        finally:
            if not handed_off:
                lease.close()

    async def aclose(self):
        await self.pool.aclose()


def public_client(timeout: float = 8) -> httpx.AsyncClient:
    # MCP may configure the root logger at INFO. HTTPX logs full signed URLs
    # there, and httpcore DEBUG may include private headers. Keep upstream
    # wire diagnostics out of application logs; our own errors use safe types.
    for name in ("httpx", "httpcore"):
        wire_logger = logging.getLogger(name)
        wire_logger.disabled = True
        wire_logger.propagate = False
        wire_logger.setLevel(logging.CRITICAL + 1)
        if not wire_logger.handlers:
            wire_logger.addHandler(logging.NullHandler())
    return httpx.AsyncClient(
        transport=PublicTransport(),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )
