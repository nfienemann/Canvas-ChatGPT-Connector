import asyncio
import random
from dataclasses import dataclass, field

import httpx

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError
from canvas_bridge.network import public_client
from canvas_bridge.policy import Endpoint, Institution, route, validate_continuation


@dataclass
class Collection:
    items: list[dict] = field(default_factory=list)
    complete: bool = False
    pages: int = 0
    failure: str | None = None


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
                        status = (
                            "reconnect_required"
                            if "www-authenticate" in response.headers
                            else "permission_denied"
                        )
                        raise DomainError(status, "Canvas access could not be authorized.")
                    if response.status_code in {403, 404}:
                        raise DomainError(
                            "permission_denied", "The Canvas resource is unavailable."
                        )
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            raise DomainError(
                                "retry_later", "Canvas could not finish this refresh."
                            )
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
                raise DomainError("retry_later", "Canvas is temporarily unavailable.") from exc
        raise DomainError("retry_later", "Canvas request budget exhausted.")

    async def one(self, endpoint: Endpoint, **ids: str) -> dict:
        # Match assignment-list semantics. Canvas omits the current user's
        # submission from a single assignment unless explicitly requested.
        params = [("include[]", "submission")] if endpoint == Endpoint.ASSIGNMENT else []
        if endpoint == Endpoint.COURSE:
            params = [
                ("include[]", key)
                for key in (
                    "syllabus_body",
                    "total_scores",
                    "grading_periods",
                    "current_grading_period_scores",
                )
            ]
        payload, _ = await self._get(str(httpx.URL(self.url(endpoint, **ids), params=params)))
        if not isinstance(payload, dict):
            raise DomainError("partial_data", "Canvas returned an unexpected object.")
        return payload

    async def collection(self, endpoint: Endpoint, **ids: str) -> Collection:
        # Query values are determined here, never passed through from a tool.
        params: list[tuple[str, str]] = [("per_page", "100")]
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
        if endpoint == Endpoint.PAGE:
            raise DomainError("permission_denied", "This route is not a collection.")
        original = str(httpx.URL(self.url(endpoint, **ids), params=params))
        url: str | None = original
        result = Collection()
        seen: set[str] = set()
        try:
            async with asyncio.timeout(self.settings.refresh_budget_seconds):
                while url and result.pages < self.settings.max_pages:
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
        except TimeoutError:
            result.failure = "retry_later"
        except DomainError as exc:
            if exc.status in {"reconnect_required", "permission_denied"}:
                # Never keep records from a now-denied collection.
                result.items.clear()
            result.failure = exc.status
        return result
