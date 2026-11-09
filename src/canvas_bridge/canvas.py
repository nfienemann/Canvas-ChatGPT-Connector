import asyncio
import hashlib
import math
import random
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs, parse_qsl, urlsplit
from urllib.request import parse_http_list

import httpx

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.network import GuardedHTTP, deny_network, public_client
from canvas_bridge.policy import Endpoint, Institution, route, source_id, validate_continuation
from canvas_bridge.request_limits import retry_after


def inventory_parallelism(bridge):
    """Plan bounded reads inside policy ceilings. Each send still requires admission."""
    with bridge.usage.transaction() as db:
        policy = bridge.usage.policy(db)
    limits = policy.limits
    if policy.allocation.pool_mode == "priority_weighted_fair_queue":
        return 1  # The dispatcher grants one ticket per owner.
    return min(
        3,
        limits.max_concurrency_per_owner,
        limits.max_concurrency_per_token,
        limits.max_concurrency_per_tenant,
        limits.max_global_concurrency - limits.interactive_slots,
    )


@dataclass
class Collection:
    items: list[dict] = field(default_factory=list)
    complete: bool = False
    pages: int = 0
    failure: str | None = None
    reason_code: str | None = None
    upstream_http_status: int | None = None
    retry_after_seconds: int | None = None
    failed_method: str | None = None
    folder_failures: dict = field(default_factory=dict)
    recent_denial: bool = False
    retrieval_constraint: str | None = None

    # One transport receipt per accepted page when requested by the caller.
    page_receipts: list[tuple[int, dict]] = field(default_factory=list)

    @property
    def inventory_failure(self):
        # Keep the fail-closed transport status separate from the observed outcome.
        if self.reason_code == "RESOURCE_UNAVAILABLE":
            return "unavailable"
        return self.failure

    def failure_fields(self):
        from canvas_bridge.domain import Result
        from canvas_bridge.egress_errors import safe_error_result

        if not self.reason_code:
            return {}
        data = safe_error_result(
            Result(
                status="partial_data",
                summary="",
                data={
                    "reason_code": self.reason_code,
                    "upstream_http_status": self.upstream_http_status,
                    "retry_after_seconds": self.retry_after_seconds,
                },
            )
        ).data
        return {
            key: data[key]
            for key in ("reason_code", "upstream_http_status", "retry_after_seconds")
            if key in data
        }


def inventory_page_identity(url):
    """Stable diagnostic identity without retaining a course URL in audit logs."""
    parsed = urlsplit(url)
    query = [
        (k, str(int(v)) if k in {"page", "per_page"} and v.isdecimal() else v)
        for k, v in parse_qsl(parsed.query)
    ]
    if not any(k == "page" for k, _ in query):
        query.append(("page", "1"))
    if not any(k == "per_page" for k, _ in query):
        query.append(("per_page", "100"))
    return hashlib.sha256(
        repr((parsed.scheme, parsed.netloc, parsed.path, sorted(query))).encode()
    ).hexdigest()


class InventoryCapabilities:
    """Recent observations can suppress a denied enumeration, never authorize a read."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.entries = OrderedDict()

    def observe(self, key, code):
        self.entries[key] = (self.clock() + 20, code)
        self.entries.move_to_end(key)
        if len(self.entries) > 256:
            self.entries.popitem(last=False)

    def denied(self, key):
        expiry, code = self.entries.get(key, (0, None))
        if expiry <= self.clock():
            self.entries.pop(key, None)
            return None
        return code


def bearer_error(headers, code):
    header = headers.get("www-authenticate", headers.get("WWW-Authenticate", ""))
    if len(header) > 2048:
        return False
    scheme, _, parameters = header.partition(" ")
    if scheme.casefold() != "bearer":
        return False
    errors = []
    for item in parse_http_list(parameters):
        key, sep, value = item.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_-]+", key.strip()):
            return False  # Ambiguous or multiple challenges.
        if key.strip().casefold() == "error":
            errors.append(value.strip())
    return len(errors) == 1 and errors[0] in (code, f'"{code}"')


def upstream_error(status: int, headers, *, throttled=False) -> DomainError:
    from canvas_bridge.failure_diagnostics import current

    error = _classify_response(status, headers, throttled=throttled)
    if attempt := current.get():
        attempt.canvas_responses.add((error.reason_code, status))
    return error


def _classify_response(status: int, headers, *, throttled=False) -> DomainError:
    if status == 429 or (status == 403 and throttled):
        delay = retry_after(headers.get("Retry-After"))
        return DomainError(
            "retry_later",
            "Canvas requests are temporarily throttled.",
            reason_code="UPSTREAM_THROTTLED",
            upstream_http_status=status,
            details={"retry_after_seconds": math.ceil(delay)} if delay is not None else {},
        )
    if status == 401:
        # A bare 401 is ambiguous in Canvas. Only an explicit invalid_token
        # challenge establishes credential failure, not course scope loss.
        rejected = bearer_error(headers, "invalid_token")
        return DomainError(
            "reconnect_required" if rejected else "permission_denied",
            "Canvas authentication could not be verified.",
            reason_code="UPSTREAM_CREDENTIAL_REJECTED"
            if rejected
            else "UNKNOWN_AUTHORIZATION_FAILURE",
            upstream_http_status=status,
        )
    if status == 403:
        if bearer_error(headers, "insufficient_scope"):
            return DomainError(
                "permission_denied",
                "Canvas reported insufficient OAuth scope for this endpoint.",
                reason_code="UPSTREAM_SCOPE_INSUFFICIENT",
                upstream_http_status=403,
            )
        return DomainError(
            "permission_denied",
            "The requested Canvas resource cannot be accessed with the current permissions.",
            reason_code="RESOURCE_PERMISSION_DENIED",
            upstream_http_status=status,
        )
    if status == 404:
        return DomainError(
            "permission_denied",
            "The resource is unavailable; absence and denied visibility cannot be distinguished.",
            reason_code="RESOURCE_UNAVAILABLE",
            upstream_http_status=status,
        )
    return DomainError(
        "retry_later",
        "The connector could not verify resource access because the upstream service was unavailable.",
        reason_code="UPSTREAM_UNAVAILABLE",
        upstream_http_status=status,
    )


def observe_resource(endpoint, exc):
    if exc.upstream_http_status is not None:
        exc.details["resource_kind"] = {
            Endpoint.FILE: "file",
            Endpoint.FOLDER: "folder",
            Endpoint.ASSIGNMENT: "assignment",
            Endpoint.PAGE: "page",
            Endpoint.COURSE: "course",
        }.get(endpoint, "collection")


class CanvasClient:
    """Only reviewed academic GET routes. Credentials never leave this origin."""

    def __init__(
        self,
        institution: Institution,
        token: str,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
    ):
        self.rejected_epoch: int | None = None
        self.institution = institution
        self.token = token
        self.settings = settings
        self._offline_transport = bool(http and isinstance(http._transport, httpx.MockTransport))
        self.http = GuardedHTTP(
            http or public_client(settings.request_timeout_seconds), self.check_request
        )
        self.owns_http = http is None
        self.authorize = self._unbound
        self.observe = lambda endpoint, ids, error: None
        from canvas_bridge.privacy.identity import PrivacyIdentity

        self.privacy_identity = PrivacyIdentity()
        self._fixture_store = None
        self.usage_cache = None
        self.inventory_capabilities = None
        self.inventory_requests_remaining = None
        if self.settings.profile == "synthetic" and self._offline_transport:
            # Standalone adapter tests still use durable accounting; Bridge clients
            # replace this lazy fixture binding with the shared service ledger.
            self.http.usage = self._standalone_usage

    def _standalone_usage(self, method, url):
        if self._fixture_store is None:
            from canvas_bridge.storage import Store
            from canvas_bridge.usage.ledger import UpstreamUsageGovernor
            from canvas_bridge.usage.policy import synthetic_policy
            from canvas_bridge.usage.transport import UsageBinding

            self._fixture_store = Store("sqlite:///:memory:")
            self._fixture_store.create_fixture_schema()
            self.http.usage = UsageBinding(
                UpstreamUsageGovernor(
                    self._fixture_store.engine, fixture_policy=synthetic_policy()
                ),
                b"synthetic-accounting-key",
                owner="fixture",
                tenant="fixture",
                token=self.token,
                mode="offline_synthetic",
            )
        return self.http.usage(method, url)

    def bind_usage(self, bridge, owner, *, scope=None):
        from canvas_bridge.usage.transport import binding

        self.http.usage = binding(bridge, owner, self.institution.id, self.token, scope=scope)
        self.usage_cache = bridge.upstream_cache

    def _unbound(self, endpoint, ids, resource=None):
        if self.settings.profile != "synthetic":
            deny_network()
        self.require_offline()

    def require_offline(self):
        if self.settings.profile == "synthetic" and (
            not self._offline_transport
            or not (urlsplit(self.institution.origin).hostname or "").endswith(".invalid")
        ):
            raise DomainError(
                "permission_denied",
                "Synthetic mode cannot contact real Canvas.",
                reason_code="SYNTHETIC_NETWORK_DISABLED",
            )

    def check_request(self, method, url):
        self.require_offline()
        parsed = urlsplit(url)
        if method != "GET" or f"{parsed.scheme}://{parsed.netloc}" != self.institution.origin:
            deny_network()
        for endpoint in Endpoint:
            pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[0-9]{1,20})", re.escape(endpoint.value))
            match = re.fullmatch(pattern, parsed.path)
            if match:
                ids = match.groupdict()
                if endpoint == Endpoint.FOLDER_FILES:
                    course = getattr(self, "_verified_folders", {}).get(ids["folder"])
                    if course is None:
                        deny_network()
                    ids["course"] = course
                query = parse_qs(parsed.query)
                if endpoint in {Endpoint.ANNOUNCEMENTS, Endpoint.CALENDAR_EVENTS}:
                    contexts = query.get("context_codes[]", [])
                    if len(contexts) != 1 or not re.fullmatch(r"course_[0-9]{1,20}", contexts[0]):
                        deny_network()
                    ids["course"] = contexts[0][7:]
                self.authorize(endpoint, ids)
                if "syllabus_body" in query.get("include[]", []):
                    self.authorize(Endpoint.COURSE, ids, "syllabus")
                if set(query.get("include[]", [])) & {
                    "total_scores",
                    "current_grading_period_scores",
                    "submission",
                }:
                    self.authorize(endpoint, ids, "grades")
                if "submission" in query.get("include[]", []):
                    self.authorize(endpoint, ids, "submissions")
                return
        deny_network()

    async def close(self):
        if self.owns_http:
            await self.http.aclose()
        if self._fixture_store:
            self._fixture_store.close()

    def url(self, endpoint: Endpoint, **ids: str) -> str:
        return f"{self.institution.origin}{route(endpoint, **ids)}"

    def inventory_key(self, url):
        if self.inventory_capabilities is None:
            return None
        path = urlsplit(url).path
        if not re.fullmatch(
            r"/api/v1/(?:courses/[0-9]+/(?:files|folders(?:/[0-9]+)?)|folders/[0-9]+/files)", path
        ):
            return None
        binding = self.http.usage
        return (
            binding.tenant,
            binding.owner,
            self.inventory_connection,
            binding.token,
            binding.scope,
            getattr(self, "_verified_folders", {}).get(path.split("/")[-2])
            if path.startswith("/api/v1/folders/")
            else None,
            url,
        )

    async def _get(self, url: str, *, attempts: int = 3) -> tuple[dict | list, str | None]:
        payload, next_link, _ = await self._get_with_receipt(url, attempts=attempts)
        return payload, next_link

    async def _get_with_receipt(self, url: str, *, attempts: int = 3):
        from canvas_bridge.authorization import request_authorization
        from canvas_bridge.usage.transport import pseudonym

        key = self.inventory_key(url)
        if key is not None and (reason := self.inventory_capabilities.denied(key)):
            self.check_request("GET", url)
            raise DomainError(
                "permission_denied",
                "Canvas recently denied this inventory route.",
                reason_code=reason,
                upstream_http_status=403,
                details={"capability_observation": "recent_denial"},
            )
        context = request_authorization.get()
        # TTL reuse requires the public result provenance path. Direct internal
        # calls always fetch; authorization/entitlement probes are never cached.
        if self.usage_cache and context:
            self.check_request("GET", url)
            governor, ctx, operation, _ = self.http.usage.describe("GET", url)
            if operation.cache_eligible:
                with governor.transaction() as db:
                    policy = governor.policy(db)
                key = pseudonym(
                    self.http.usage.key,
                    ctx.owner_id,
                    ctx.tenant_id,
                    ctx.token_key,
                    ctx.resource_scope,
                    url,
                    context.recipient,
                )

                def authorize():
                    self.check_request("GET", url)

                async def fetch(validators):
                    return await self._fetch(url, attempts=attempts, validators=validators)

                value, evidence = await self.usage_cache.get(
                    key, authorize, fetch, ttl=policy.limits.cache_ttl_seconds
                )
                context.usage_cache.append(evidence)
                governor.note_cache(evidence["source"])
                return *value, evidence
        payload, next_link, _ = await self._fetch(url, attempts=attempts)
        return payload, next_link, {"source": "upstream", "retrieved_at": utcnow().isoformat()}

    async def _fetch(self, url: str, *, attempts: int = 3, validators=None):
        from canvas_bridge.workflow_budget import count_bytes, count_request

        self.check_request("GET", url)
        if hasattr(self.http.usage, "governor"):
            governor = self.http.usage.governor
            with governor.transaction() as db:
                attempts = min(attempts, governor.policy(db).limits.retries_per_attempt + 1)
        for attempt in range(attempts):
            started = asyncio.get_running_loop().time()
            try:
                if self.inventory_requests_remaining is not None:
                    if self.inventory_requests_remaining <= 0:
                        raise DomainError(
                            "retry_later",
                            "The inventory recovery request budget is exhausted.",
                            reason_code="TASK_BUDGET_EXCEEDED",
                        )
                    self.inventory_requests_remaining -= 1
                count_request()
                async with self.http.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept-Encoding": "identity",
                        **(validators or {}),
                    },
                    follow_redirects=False,
                ) as response:
                    if response.status_code == 304 and validators:
                        self.check_request("GET", url)
                        return None, None, dict(response.headers)
                    if response.status_code == 401:
                        raise upstream_error(response.status_code, response.headers)
                    from canvas_bridge.usage.transport import explicit_throttle

                    throttled = response.status_code == 429
                    if response.status_code == 403:
                        error_body = bytearray()
                        async for chunk in response.aiter_bytes():
                            error_body.extend(chunk)
                            if len(error_body) > 32000:
                                break
                        throttled = explicit_throttle(403, error_body)
                        response.extensions["bridge_throttle"] = throttled
                    if response.status_code in {403, 404} and not throttled:
                        error = upstream_error(response.status_code, response.headers)
                        key = self.inventory_key(url)
                        if key is not None and response.status_code == 403:
                            self.inventory_capabilities.observe(key, error.reason_code)
                        raise error
                    if throttled or response.status_code >= 500:
                        if attempt == attempts - 1:
                            raise upstream_error(
                                response.status_code, response.headers, throttled=throttled
                            )
                        delay = retry_after(response.headers.get("Retry-After"))
                        if delay is None:
                            delay = 1
                        if delay > 3:
                            # The transport retains the full cooldown across clients.
                            # Do not shorten it to fit this request's latency budget.
                            raise upstream_error(
                                response.status_code, response.headers, throttled=throttled
                            )
                        await response.aclose()
                        await asyncio.sleep(max(delay, 0.15 * 2**attempt) + random.uniform(0, 0.1))  # noqa: S311
                        continue
                    if 300 <= response.status_code < 400:
                        raise DomainError(
                            "permission_denied", "Canvas API redirects are not permitted."
                        )
                    if response.status_code != 200:
                        raise DomainError(
                            "unsupported_feature", "Canvas did not return the expected resource."
                        )
                    content = bytearray()
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise DomainError("retry_later", "Encoded API responses are unsupported.")
                    async for chunk in response.aiter_bytes():
                        count_bytes(len(chunk))
                        content.extend(chunk)
                        if len(content) > self.settings.max_response_bytes:
                            raise DomainError(
                                "retry_later", "Canvas response exceeded the safe size limit."
                            )
                    import json

                    payload = json.loads(content)
                    self.check_request("GET", url)
                    key = self.inventory_key(url)
                    if key is not None and isinstance(payload, (list, dict)):
                        self.inventory_capabilities.observe(key, None)
                    next_link = next(
                        (
                            link["url"]
                            for link in response.links.values()
                            if "next" in link.get("rel", "").lower().split()
                        ),
                        None,
                    )
                    return payload, next_link, dict(response.headers)
            except ValueError as exc:
                raise DomainError(
                    "operation_failed",
                    "Canvas returned an unreadable response.",
                    reason_code="UPSTREAM_RESPONSE_INVALID",
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < attempts - 1:
                    await asyncio.sleep(1 + 0.15 * 2**attempt)
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise DomainError(
                        "retry_later",
                        "The provider request timed out.",
                        reason_code="UPSTREAM_REQUEST_TIMEOUT",
                        details={
                            "elapsed_ms": round(
                                (asyncio.get_running_loop().time() - started) * 1000
                            )
                        },
                    ) from exc
                raise DomainError(
                    "retry_later",
                    "Canvas is temporarily unavailable.",
                    reason_code="UPSTREAM_UNAVAILABLE",
                ) from exc
        raise DomainError("retry_later", "Canvas request budget exhausted.")

    async def discussion_page(self, endpoint: Endpoint, *, cursor=None, receipts=None, **ids):
        """One allowlisted page. Raw peer data never leaves this method.

        Pagination uses the existing exact-origin/path/query fence. Budgets for
        the entire topic, including nested reply pages, live in the scanner.
        """
        allowed = {
            Endpoint.DISCUSSION_VIEW,
            Endpoint.DISCUSSION_ENTRIES,
            Endpoint.DISCUSSION_REPLIES,
        }
        if endpoint not in allowed:
            raise DomainError("permission_denied", "Unsupported discussion route.")
        params = (
            {"include_new_entries": "1"}
            if endpoint == Endpoint.DISCUSSION_VIEW
            else {"per_page": "100"}
        )
        original = str(httpx.URL(self.url(endpoint, **ids), params=params))
        url = cursor or original
        validate_continuation(url, original)
        self.authorize(endpoint, ids)
        try:
            payload, next_link, receipt = await self._get_with_receipt(
                url, attempts=self.settings.discussion_retry_attempts
            )
        except DomainError as exc:
            observe_resource(endpoint, exc)
            self.observe(endpoint, ids, exc)
            raise
        self.authorize(endpoint, ids)
        from canvas_bridge.privacy.discussions import minimize_thread

        minimized = minimize_thread(
            payload,
            self.privacy_identity,
            full_view=endpoint == Endpoint.DISCUSSION_VIEW,
            max_entries=self.settings.discussion_max_entries,
            text_limit=self.settings.discussion_text_limit,
            parent_entry=ids.get("entry"),
        )
        if receipts is not None:
            receipts.append(receipt)
        return minimized, next_link

    async def one(
        self,
        endpoint: Endpoint,
        *,
        course_content: Literal["grades", "syllabus", "metadata"] = "grades",
        discussion_checkpoints: bool = False,
        receipts: list[dict] | None = None,
        **ids: str,
    ) -> dict:
        # Match assignment-list semantics. Canvas omits the current user's
        # submission from a single assignment unless explicitly requested.
        params = [("include[]", "submission")] if endpoint == Endpoint.ASSIGNMENT else []
        if discussion_checkpoints:
            if endpoint != Endpoint.ASSIGNMENT:
                raise DomainError("permission_denied", "Checkpoint dates require an assignment.")
            params = [("include[]", "checkpoints")]
        resource = None
        if endpoint == Endpoint.COURSE:
            resource = "course" if course_content == "metadata" else course_content
            params = [
                ("include[]", key)
                for key in (
                    (
                        "syllabus_body",
                        "total_scores",
                        "grading_periods",
                        "current_grading_period_scores",
                    )
                    if course_content == "grades"
                    else ("syllabus_body",)
                    if course_content == "syllabus"
                    else ()
                )
            ]
            if course_content == "grades":
                self.authorize(Endpoint.ENROLLMENTS, ids, "grades")
        self.authorize(endpoint, ids, resource)
        try:
            url = str(httpx.URL(self.url(endpoint, **ids), params=params))
            if receipts is None:
                payload, next_link = await self._get(url)
            else:
                payload, next_link, receipt = await self._get_with_receipt(url)
        except DomainError as exc:
            observe_resource(endpoint, exc)
            self.observe(endpoint, ids, exc)
            raise
        self.authorize(endpoint, ids, resource)
        if not isinstance(payload, dict):
            raise DomainError(
                "partial_data",
                "Canvas returned an unexpected object.",
                reason_code="UPSTREAM_RESPONSE_INVALID",
            )
        from canvas_bridge.privacy.upstream import minimize_upstream

        minimized = minimize_upstream(endpoint, payload, self.privacy_identity)
        if endpoint == Endpoint.DISCUSSION_DATES and next_link:
            minimized["overrides_uncertain"] = True
        if receipts is not None:
            receipts.append(receipt)
        return minimized

    async def probe_metadata(self, resource: str, course: str) -> int:
        """One GET, no includes, no pagination/retry, no response body consumption.

        HTTP 200 only proves this endpoint accepted the request. It says nothing
        about individual locked files, extraction, or enrollment completeness.
        Grades/syllabus have no safe conclusive metadata probe here.
        """
        endpoints = {
            "course": Endpoint.COURSE,
            "files": Endpoint.FILES,
            "modules": Endpoint.MODULES,
            "assignments": Endpoint.ASSIGNMENTS,
            "quizzes": Endpoint.QUIZZES,
        }
        endpoint = endpoints.get(resource)
        if endpoint is None:
            raise DomainError(
                "unsupported_feature",
                "No content-free permission probe is enabled.",
                reason_code="NO_SAFE_METADATA_PROBE",
            )
        ids = {"course": source_id(course)}
        self.authorize(endpoint, ids, resource)
        params = {} if resource == "course" else {"per_page": "1"}
        url = str(httpx.URL(self.url(endpoint, **ids), params=params))
        try:
            async with self.http.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                follow_redirects=False,
            ) as response:
                status = response.status_code
                if status != 200:
                    raise upstream_error(status, response.headers)
                self.authorize(endpoint, ids, resource)
                return status
        except httpx.HTTPError as exc:
            raise DomainError(
                "retry_later",
                "The upstream metadata probe was unavailable.",
                reason_code="UPSTREAM_UNAVAILABLE",
            ) from exc

    async def folder_files_page(self, course, folder, *, cursor=None):
        """Bind the global folder route to fresh, course-qualified metadata."""
        course, folder = source_id(course), source_id(folder)
        self._verified_folders = {}
        try:
            metadata = await self.one(Endpoint.FOLDER, course=course, folder=folder)
        except DomainError as exc:
            exc.details["failed_method"] = "folder_metadata"
            raise
        if (
            str(metadata.get("id")) != folder
            or metadata.get("context_type") != "Course"
            or str(metadata.get("context_id")) != course
            or metadata.get("locked_for_user") is True
            or metadata.get("hidden_for_user") is True
            or metadata.get("for_submissions") is True
        ):
            raise DomainError(
                "permission_denied",
                "Folder is not accessible in this course.",
                reason_code="RESOURCE_PERMISSION_DENIED",
                details={"failed_method": "folder_metadata"},
            )
        from canvas_bridge.inventory_recovery import track_method

        track_method("folder_files")
        self._verified_folders[folder] = course
        try:
            return await self.inventory_page(
                Endpoint.FOLDER_FILES, course=course, folder=folder, cursor=cursor
            )
        finally:
            self._verified_folders = {}

    async def inventory_page(self, endpoint: Endpoint, *, cursor=None, **ids):
        """One bounded inventory page through the ordinary authorization boundary.

        The continuation is an internal value: callers must seal it with owner,
        connection and selected-scope bindings before exposing a public cursor.
        Assignment discovery does not request submission/grade expansions.
        """
        allowed = {
            Endpoint.COURSES,
            Endpoint.FILES,
            Endpoint.FOLDERS,
            Endpoint.FOLDER_FILES,
            Endpoint.MODULES,
            Endpoint.MODULE_ITEMS,
            Endpoint.ASSIGNMENTS,
        }
        if endpoint not in allowed:
            raise DomainError("permission_denied", "Unsupported inventory route.")
        params = [("per_page", "100")]
        if endpoint == Endpoint.COURSES:
            params += [("enrollment_type", "student"), ("enrollment_state", "active")]
        original = str(httpx.URL(self.url(endpoint, **ids), params=params))
        url = cursor or original
        validate_continuation(url, original)
        self.authorize(endpoint, ids)
        started = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(self.settings.refresh_budget_seconds):
                payload, next_link = await self._get(url)
        except TimeoutError as exc:
            raise DomainError(
                "retry_later",
                "Inventory page timed out; resume the same continuation.",
                reason_code="INVENTORY_BRANCH_TIMEOUT",
                details={
                    "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000),
                    "deadline_seconds": self.settings.refresh_budget_seconds,
                },
            ) from exc
        except DomainError as exc:
            observe_resource(endpoint, exc)
            self.observe(endpoint, ids, exc)
            raise
        self.authorize(endpoint, ids)
        if (
            not isinstance(payload, list)
            or len(payload) > 100
            or any(not isinstance(x, dict) for x in payload)
        ):
            raise DomainError(
                "partial_data",
                "Canvas returned an invalid inventory page.",
                reason_code="INVENTORY_PAGE_INVALID",
            )
        if next_link:
            validate_continuation(next_link, original)
            if inventory_page_identity(next_link) == inventory_page_identity(url):
                raise DomainError(
                    "partial_data",
                    "Canvas repeated an inventory page.",
                    reason_code="INVENTORY_PAGINATION_CYCLE",
                )
        from canvas_bridge.privacy.upstream import minimize_upstream

        return (
            [minimize_upstream(endpoint, item, self.privacy_identity) for item in payload],
            next_link,
            inventory_page_identity(url),
        )

    async def collection(
        self,
        endpoint: Endpoint,
        *,
        window: tuple[datetime, datetime] | None = None,
        calendar_kind: Literal["event", "assignment"] = "event",
        include_submission: bool = True,
        budget_seconds: float | None = None,
        workload_deadline: float | None = None,
        record_page_receipts: bool = False,
        **ids: str,
    ) -> Collection:
        # Query values are determined here, never passed through from a tool.
        params: list[tuple[str, str]] = [("per_page", "100")]
        if endpoint == Endpoint.CALENDAR_EVENTS:
            if (
                window is None
                or any(t.tzinfo is None or t.utcoffset() is None for t in window)
                or not timedelta(0) < window[1] - window[0] <= timedelta(days=31)
                or calendar_kind not in {"event", "assignment"}
            ):
                raise DomainError(
                    "needs_input", "Calendar reads require a bounded aware date window."
                )
            params += [
                ("context_codes[]", "course_" + source_id(ids.get("course", ""))),
                ("type", calendar_kind),
                ("start_date", window[0].isoformat()),
                ("end_date", window[1].isoformat()),
                ("excludes[]", "child_events"),
                ("excludes[]", "assignment"),
            ]
        if endpoint == Endpoint.COURSES:
            params += [("enrollment_type", "student"), ("enrollment_state", "active")]
        if endpoint == Endpoint.ASSIGNMENTS and include_submission:
            params += [("include[]", "submission")]
        if endpoint == Endpoint.ENROLLMENTS:
            params += [
                ("type[]", "StudentEnrollment"),
                ("state[]", "active"),
                ("include[]", "current_points"),
            ]
        if endpoint == Endpoint.ANNOUNCEMENTS:
            course = source_id(ids.get("course", ""))
            now = utcnow()
            params += [
                ("context_codes[]", "course_" + course),
                ("start_date", (now - timedelta(days=180)).isoformat()),
                ("end_date", now.isoformat()),
                ("active_only", "true"),
            ]
        if endpoint == Endpoint.PAGE:
            raise DomainError("permission_denied", "This route is not a collection.")
        original = str(httpx.URL(self.url(endpoint, **ids), params=params))
        url: str | None = original
        result = Collection()
        seen: set[str] = set()
        loop = asyncio.get_running_loop()
        duration = self.settings.refresh_budget_seconds
        if budget_seconds is not None:
            duration = min(duration, max(0, budget_seconds))
        deadline = loop.time() + duration
        if workload_deadline is not None:
            if endpoint != Endpoint.ASSIGNMENTS or budget_seconds is not None:
                raise ValueError("Workload deadlines apply only to assignment audits.")
            deadline = min(
                workload_deadline, loop.time() + self.settings.workload_refresh_budget_seconds
            )
        try:
            self.authorize(endpoint, ids)
            # Internal callers may reserve time for other inventory branches.
            # Catch that timeout here so completed pages are not discarded by
            # an outer cancellation. This never expands the configured budget.
            try:
                async with asyncio.timeout_at(deadline):
                    while url and result.pages < min(self.settings.max_pages, 20):
                        if workload_deadline is not None and loop.time() >= deadline:
                            raise TimeoutError
                        self.authorize(endpoint, ids)
                        if url in seen:
                            raise DomainError(
                                "partial_data",
                                "Canvas repeated a pagination cursor.",
                                reason_code="INVENTORY_PAGINATION_CYCLE",
                            )
                        seen.add(url)
                        validate_continuation(url, original)
                        receipt = None
                        if record_page_receipts:
                            payload, url, receipt = await self._get_with_receipt(url)
                        else:
                            payload, url = await self._get(url)
                        if not isinstance(payload, list) or any(
                            not isinstance(x, dict) for x in payload
                        ):
                            raise DomainError(
                                "partial_data",
                                "Canvas returned an unexpected collection.",
                                reason_code="UPSTREAM_RESPONSE_INVALID",
                            )
                        from canvas_bridge.privacy.upstream import minimize_upstream

                        result.items.extend(
                            minimize_upstream(endpoint, item, self.privacy_identity)
                            for item in payload
                        )
                        result.pages += 1
                        if receipt is not None:
                            result.page_receipts.append((len(payload), receipt))
                    result.complete = url is None
                    if not result.complete:
                        result.failure = "request_budget"
                        result.reason_code = "TASK_BUDGET_EXCEEDED"
            except TimeoutError:
                if workload_deadline is not None:
                    result.failure = "refresh_budget_exhausted"
                    result.reason_code = "INVENTORY_BRANCH_TIMEOUT"
                elif budget_seconds is not None:
                    result.failure = "request_budget"
                    result.reason_code = "INVENTORY_BRANCH_TIMEOUT"
                else:
                    result.failure = "retry_later"
                    result.reason_code = "UPSTREAM_REQUEST_TIMEOUT"
            self.authorize(endpoint, ids)
        except DomainError as exc:
            observe_resource(endpoint, exc)
            self.observe(endpoint, ids, exc)
            if exc.status in {"reconnect_required", "permission_denied", "source_changed"}:
                # Never keep records from a now-denied collection.
                result.items.clear()
                result.complete = False
            result.failure = exc.status
            result.reason_code = exc.reason_code
            result.upstream_http_status = exc.upstream_http_status
            result.retry_after_seconds = exc.details.get("retry_after_seconds")
            result.retrieval_constraint = exc.details.get("retrieval_constraint")
            result.recent_denial = exc.details.get("capability_observation") == "recent_denial"
        return result
