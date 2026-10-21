"""Outbound transport resolves once, rejects non-public IPs, then connects to
the validated numeric address while TLS verifies the original hostname.
"""

import asyncio
import logging
import socket
import ssl

import httpcore
import httpx

from canvas_bridge.domain import DomainError
from canvas_bridge.policy import public_ip


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
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicBackend(),
            max_connections=20,
            retries=0,
        )

    async def handle_async_request(self, request):
        try:
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
            return httpx.Response(
                response.status,
                headers=response.headers,
                stream=CoreStream(response.stream),
                extensions=response.extensions,
            )
        except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError) as exc:
            raise httpx.RequestError("Upstream transport unavailable.", request=request) from exc

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
