import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import httpx

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.network import public_client
from canvas_bridge.policy import Endpoint, Institution, route, source_id, validate_continuation


@dataclass
class Collection:
    items: list[dict] = field(default_factory=list)
    complete: bool = False
    pages: int = 0
    failure: str | None = None
    reason_code: str | None = None
    upstream_http_status: int | None = None


def upstream_error(status: int, headers) -> DomainError:
    if status == 401:
        # A bare 401 is ambiguous in Canvas. Only an explicit invalid_token
        # challenge establishes credential failure, not course scope loss.
        expired = "invalid_token" in headers.get("www-authenticate", "").lower()
        return DomainError(
            "reconnect_required" if expired else "permission_denied",
            "Canvas authentication could not be verified.",
            reason_code="UPSTREAM_AUTH_EXPIRED" if expired else "UNKNOWN_AUTHORIZATION_FAILURE",
            upstream_http_status=status,
        )
    if status == 403:
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


class CanvasClient:
    """Only reviewed academic GET routes. Credentials never leave this origin."""

    def __init__(
        self,
        institution: Institution,
        token: str,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
    ):
        self.institution = institution
        self.token = token
        self.settings = settings
        self.http = http or public_client(settings.request_timeout_seconds)
        self.owns_http = http is None
        self.authorize = lambda endpoint, ids, resource=None: None
        self.observe = lambda endpoint, ids, error: None

    async def close(self):
        if self.owns_http:
            await self.http.aclose()

    def url(self, endpoint: Endpoint, **ids: str) -> str:
        return f"{self.institution.origin}{route(endpoint, **ids)}"

    async def _get(self, url: str) -> tuple[dict | list, str | None]:
        for attempt in range(3):
            try:
                async with self.http.stream(
                    "GET",
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code == 401:
                        raise upstream_error(response.status_code, response.headers)
                    if response.status_code in {403, 404}:
                        raise upstream_error(response.status_code, response.headers)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            raise upstream_error(response.status_code, response.headers)
                        try:
                            delay = min(max(float(response.headers.get("Retry-After", 0)), 0), 3)
                        except ValueError:
                            delay = 1
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
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.settings.max_response_bytes:
                            raise DomainError(
                                "retry_later", "Canvas response exceeded the safe size limit."
                            )
                    import json

                    payload = json.loads(content)
                    next_link = response.links.get("next", {}).get("url")
                    return payload, next_link
            except (httpx.HTTPError, ValueError) as exc:
                raise DomainError(
                    "retry_later",
                    "Canvas is temporarily unavailable.",
                    reason_code="UPSTREAM_UNAVAILABLE",
                ) from exc
        raise DomainError("retry_later", "Canvas request budget exhausted.")

    async def one(
        self,
        endpoint: Endpoint,
        *,
        course_content: Literal["grades", "syllabus", "metadata"] = "grades",
        **ids: str,
    ) -> dict:
        # Match assignment-list semantics. Canvas omits the current user's
        # submission from a single assignment unless explicitly requested.
        params = [("include[]", "submission")] if endpoint == Endpoint.ASSIGNMENT else []
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
            payload, _ = await self._get(str(httpx.URL(self.url(endpoint, **ids), params=params)))
        except DomainError as exc:
            self.observe(endpoint, ids, exc)
            raise
        self.authorize(endpoint, ids, resource)
        if not isinstance(payload, dict):
            raise DomainError("partial_data", "Canvas returned an unexpected object.")
        return payload

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

    async def collection(
        self,
        endpoint: Endpoint,
        *,
        window: tuple[datetime, datetime] | None = None,
        calendar_kind: Literal["event", "assignment"] = "event",
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
        if endpoint == Endpoint.ASSIGNMENTS:
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
        try:
            self.authorize(endpoint, ids)
            async with asyncio.timeout(self.settings.refresh_budget_seconds):
                while url and result.pages < self.settings.max_pages:
                    self.authorize(endpoint, ids)
                    if url in seen:
                        raise DomainError("partial_data", "Canvas repeated a pagination cursor.")
                    seen.add(url)
                    validate_continuation(url, original)
                    payload, url = await self._get(url)
                    if not isinstance(payload, list) or any(
                        not isinstance(x, dict) for x in payload
                    ):
                        raise DomainError(
                            "partial_data", "Canvas returned an unexpected collection."
                        )
                    result.items.extend(payload)
                    result.pages += 1
                result.complete = url is None
                if not result.complete:
                    result.failure = "request_budget"
            self.authorize(endpoint, ids)
        except TimeoutError:
            result.failure = "retry_later"
        except DomainError as exc:
            self.observe(endpoint, ids, exc)
            if exc.status in {"reconnect_required", "permission_denied", "source_changed"}:
                # Never keep records from a now-denied collection.
                result.items.clear()
            result.failure = exc.status
            result.reason_code = exc.reason_code
            result.upstream_http_status = exc.upstream_http_status
        return result
