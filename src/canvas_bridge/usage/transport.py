"""Server-owned operation registry and the final per-attempt transport facade."""

import asyncio
import hmac
import math
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from canvas_bridge.authorization import request_authorization
from canvas_bridge.domain import DomainError
from canvas_bridge.policy import Endpoint
from canvas_bridge.usage.ledger import deny
from canvas_bridge.usage.policy import UsageContext, canonical


@dataclass(frozen=True)
class Operation:
    name: str
    method: str = "GET"
    max_requests: int = 40
    max_pages: int = 20
    max_documents: int = 6
    max_body_bytes: int = 2_000_000
    timeout_seconds: int = 15
    retry_eligible: bool = True
    cache_eligible: bool = False
    risk: str = "read"


OPERATIONS = {
    "canvas." + endpoint.name.lower(): Operation(
        "canvas." + endpoint.name.lower(),
        cache_eligible=endpoint in {Endpoint.ASSIGNMENT, Endpoint.PAGE},
    )
    for endpoint in Endpoint
}
OPERATIONS.update(
    {
        "canvas.file_download": Operation(
            "canvas.file_download", max_body_bytes=50 * 1024 * 1024, timeout_seconds=90
        ),
        "canvas.oauth_exchange": Operation(
            "canvas.oauth_exchange",
            method="POST",
            max_body_bytes=32000,
            retry_eligible=False,
            risk="credential_exchange",
        ),
        "canvas.oauth_revoke": Operation(
            "canvas.oauth_revoke",
            method="DELETE",
            max_body_bytes=32000,
            retry_eligible=False,
            risk="credential_cleanup",
        ),
    }
)
EXPLORATORY_TOOLS = frozenset(
    {"audit_course_access", "audit_canvas_permissions", "get_course_material_inventory"}
)


@dataclass(frozen=True)
class RequestSpec:
    request: httpx.Request
    stream: bool = True


class GovernedProviderTransport(Protocol):
    async def request(self, ctx: UsageContext, request: RequestSpec) -> httpx.Response: ...


def pseudonym(key, *parts):
    return hmac.digest(key, canonical(parts), "sha256").hex()


class UsageBinding:
    def __init__(self, governor, key, *, owner, tenant, token, mode, operation=None, scope=None):
        self.governor, self.key = governor, key
        self.owner = pseudonym(key, "owner", owner)
        self.tenant = pseudonym(key, "tenant", tenant)
        self.token = pseudonym(key, "token", token)
        self.mode, self.fixed_operation, self.scope = mode, operation, scope
        self.task = uuid4().hex
        self.last_attempt = {}

    def __call__(self, method, url):
        return self.describe(method, url, track=True)

    def describe(self, method, url, *, track=False):
        name = self.fixed_operation
        if name is None:
            path = urlsplit(url).path
            for endpoint in Endpoint:
                pattern = re.sub(r"\\\{(\w+)\\\}", r"[0-9]{1,20}", re.escape(endpoint.value))
                if re.fullmatch(pattern, path):
                    name = "canvas." + endpoint.name.lower()
                    break
        operation = OPERATIONS.get(name)
        if not operation or operation.method != method:
            deny("PROVIDER_NOT_AUTHORIZED")
        context = request_authorization.get()
        task = context.request_id if context else self.task
        workload = (
            "scheduled_sync"
            if context and context.tool_name == "governed_scheduled_refresh"
            else "exploratory"
            if context and context.tool_name in EXPLORATORY_TOOLS
            else "interactive"
        )
        lineage = task, name, pseudonym(self.key, url)
        ctx = UsageContext(
            "canvas",
            None,
            self.tenant,
            self.owner,
            pseudonym(self.key, "task", task),
            name,
            workload,
            self.scope,
            self.token,
            parent_attempt_id=self.last_attempt.get(lineage),
        )
        if track:
            self.last_attempt[lineage] = ctx.attempt_id
        # Binding lifetime is normally one tool call; bound unusually long clients.
        if len(self.last_attempt) > 200:
            self.last_attempt.clear()
        return self.governor, ctx, operation, self.mode


def binding(bridge, owner, institution, token, *, operation=None, scope=None):
    return UsageBinding(
        bridge.usage,
        bridge.vault.key,
        owner=owner,
        tenant=institution,
        token=token,
        # A fixture governor is constructed only by trusted synthetic startup or
        # an explicit test harness. It remains mock-only even when an approval
        # fixture exercises personal/hosted authorization code paths.
        mode=bridge.usage.fixture_policy.mode
        if bridge.usage.fixture_policy is not None
        else "personal_development"
        if bridge.usage.development_policy is not None
        else "production_approved",
        operation=operation,
        scope=scope,
    )


class AccountedStream(httpx.AsyncByteStream):
    """Hold reservations/concurrency through body receipt and cancellation."""

    def __init__(self, stream, governor, ctx, response, operation, ticket=None):
        self.stream, self.governor, self.ctx = stream, governor, ctx
        self.response, self.operation = response, operation
        self.closed, self.complete, self.failed = False, False, False
        self.bytes = 0
        self.ticket = ticket
        self.deadline = asyncio.get_running_loop().time() + operation.timeout_seconds

    async def __aiter__(self):
        size = 0
        try:
            async with asyncio.timeout_at(self.deadline):
                async for chunk in self.stream:
                    size += len(chunk)
                    self.bytes = size
                    if size > self.operation.max_body_bytes:
                        deny("TASK_BUDGET_EXCEEDED")
                    yield chunk
            self.complete = True
        except BaseException:
            self.failed = True
            raise

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.stream.aclose()
        finally:
            try:
                self.governor.finish(
                    self.ctx.attempt_id,
                    status=self.response.status_code,
                    headers=self.response.headers,
                    failed=self.failed or not self.complete,
                    body_bytes=self.bytes,
                    throttled=self.response.extensions.get("bridge_throttle", False),
                )
            finally:
                if self.ticket:
                    self.ticket.close()


async def governed_send(client, request, check, usage, **kwargs):
    """No await between the final authorization/SENT commit and HTTP send."""
    check(request.method, str(request.url))
    governor, ctx, operation, mode = usage(request.method, str(request.url))
    is_mock = isinstance(client._transport, httpx.MockTransport)
    if (mode in {"offline_synthetic", "authorized_mock_provider"}) != is_mock:
        deny("PROVIDER_NOT_AUTHORIZED")
    if mode == "offline_synthetic" and not (request.url.host or "").endswith(".invalid"):
        deny("PROVIDER_NOT_AUTHORIZED")
    from canvas_bridge.network import PublicTransport, network_permit, usage_admission

    if (
        mode in {"production_approved", "personal_development"}
        and type(client._transport) is not PublicTransport
    ):
        deny("PROVIDER_NOT_AUTHORIZED")

    def authorize():
        check(request.method, str(request.url))

    ticket = None
    with governor.transaction() as db:
        policy = governor.policy(db, ctx.provider_id)
    # Permit a short bounded wait for sequential pages or a safe fallback after
    # a failed endpoint. Never shorten a longer Retry-After or hold a reservation
    # while sleeping. Authorization and every limit are checked again below.
    delay = governor.cooldown_seconds(ctx.token_key)
    if delay > 3:
        authorize()
        raise DomainError(
            "retry_later",
            "Upstream cooldown is still active; retry after the indicated delay.",
            reason_code="UPSTREAM_THROTTLED",
            details={"retry_after_seconds": math.ceil(delay), "blocking_scope": "cooldown"},
        )
    if 0 < delay <= 3:
        await asyncio.sleep(delay + 0.005)
    if policy.allocation.pool_mode == "priority_weighted_fair_queue":
        from canvas_bridge.usage.fair_queue import FairQueue

        loop = asyncio.get_running_loop()
        queue = governor.queues.setdefault(loop, FairQueue(policy.limits.max_global_concurrency))
        try:
            ticket = await queue.acquire(ctx.owner_id, ctx.workload_class)
        except TimeoutError:
            deny("LOCAL_REQUEST_BUSY")
    handed_off = False
    reserved = False
    permit = network_permit.set((request.method, str(request.url)))
    admission = usage_admission.set(lambda: governor.sent(ctx.attempt_id, authorize))
    try:
        governor.reserve(ctx, authorize=authorize, operation=operation, mode=mode)
        reserved = True
        if is_mock:
            governor.sent(ctx.attempt_id, authorize)
        response = await client.send(request, stream=True, **kwargs)
        if response.is_closed:
            governor.finish(
                ctx.attempt_id,
                status=response.status_code,
                headers=response.headers,
                body_bytes=len(response.content),
                throttled=explicit_throttle(response.status_code, response.content),
            )
            if ticket:
                ticket.close()
            if len(response.content) > operation.max_body_bytes:
                deny("TASK_BUDGET_EXCEEDED")
        else:
            response.stream = AccountedStream(
                response.stream, governor, ctx, response, operation, ticket
            )
        handed_off = True
        return response
    finally:
        network_permit.reset(permit)
        usage_admission.reset(admission)
        if not handed_off:
            try:
                if reserved:
                    governor.finish(ctx.attempt_id, failed=True)
            finally:
                if ticket:
                    ticket.close()


def explicit_throttle(status, content):
    if status == 429:
        return True
    if status != 403 or len(content) > 32000:
        return False
    import json

    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError):
        return False
    return isinstance(payload, dict) and payload.get("errors") == [
        {"message": "Rate Limit Exceeded"}
    ]
