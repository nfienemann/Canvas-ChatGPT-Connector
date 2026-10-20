import ipaddress
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field, model_validator

from canvas_bridge.domain import DomainError, Model


class Institution(Model):
    id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    name: str
    origin: str | None = None
    status: Literal[
        "candidate",
        "access_pending",
        "personal_testing",
        "pilot_supported",
        "supported",
        "temporarily_degraded",
        "unsupported",
        "retired",
    ]
    scopes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    client_id_env: str | None = None
    client_secret_env: str | None = None
    # Exact operator-reviewed storage origins. Never inferred from a redirect.
    download_origins: list[str] = Field(default_factory=list)
    download_origin_templates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonical_origin(self):
        if self.origin:
            u = urlsplit(self.origin)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.username
                or u.password
                or u.port not in {None, 443}
                or u.path not in {"", "/"}
                or u.query
                or u.fragment
                or "\\" in self.origin
                or "%" in u.netloc
                or "*" in u.netloc
                or any(ord(c) < 33 for c in self.origin)
            ):
                raise ValueError("Institution origins must be canonical HTTPS origins.")
            self.origin = f"https://{u.hostname}"
        normalized = []
        for origin in self.download_origins:
            u = urlsplit(origin)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.username
                or u.password
                or u.port not in {None, 443}
                or u.path
                or u.query
                or u.fragment
                or "*" in origin
                or "\\" in origin
                or "%" in u.netloc
                or any(ord(c) < 33 for c in origin)
            ):
                raise ValueError("Download origins must be exact canonical HTTPS origins.")
            normalized.append(f"https://{u.hostname}")
        self.download_origins = list(dict.fromkeys(normalized))
        for template in self.download_origin_templates:
            candidate = template.replace("{file_id}", "1")
            u = urlsplit(candidate)
            if (
                template.count("{file_id}") != 1
                or "{" in candidate
                or "}" in candidate
                or candidate != f"https://{u.hostname}"
                or u.port is not None
                or "*" in candidate
                or "%" in candidate
                or "\\" in candidate
                or any(ord(c) < 33 for c in candidate)
            ):
                raise ValueError(
                    "Download templates require one file_id in an exact HTTPS hostname."
                )
        return self


class Registry:
    def __init__(self, path: Path):
        content = json.loads(path.read_text(encoding="utf-8"))
        self.entries = {i.id: i for i in map(Institution.model_validate, content["institutions"])}

    def require(
        self, institution: str, synthetic: bool = False, *, personal: bool = False
    ) -> Institution:
        item = self.entries.get(institution)
        if item is None or not item.origin:
            raise DomainError(
                "unsupported_feature", "This institution has no approved access path."
            )
        allowed = {"pilot_supported", "supported"}
        if personal:
            allowed.add("personal_testing")
        if not synthetic and item.status not in allowed:
            raise DomainError(
                "unsupported_feature", "This institution is not enabled for live access."
            )
        return item


class Endpoint(StrEnum):
    PROFILE = "/api/v1/users/self/profile"
    COURSES = "/api/v1/courses"
    COURSE = "/api/v1/courses/{course}"
    ASSIGNMENTS = "/api/v1/courses/{course}/assignments"
    ASSIGNMENT_GROUPS = "/api/v1/courses/{course}/assignment_groups"
    ASSIGNMENT = "/api/v1/courses/{course}/assignments/{assignment}"
    SUBMISSION = "/api/v1/courses/{course}/assignments/{assignment}/submissions/self"
    ENROLLMENTS = "/api/v1/users/self/enrollments"
    MODULES = "/api/v1/courses/{course}/modules"
    MODULE_ITEMS = "/api/v1/courses/{course}/modules/{module}/items"
    PAGES = "/api/v1/courses/{course}/pages"
    PAGE = "/api/v1/courses/{course}/pages/page_id:{page}"
    ANNOUNCEMENTS = "/api/v1/announcements"
    QUIZZES = "/api/v1/courses/{course}/quizzes"
    DISCUSSIONS = "/api/v1/courses/{course}/discussion_topics"
    CALENDAR_EVENTS = "/api/v1/calendar_events"
    FILE = "/api/v1/courses/{course}/files/{file}"
    FILES = "/api/v1/courses/{course}/files"


def source_id(value: str | int) -> str:
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise DomainError("permission_denied", "Invalid source identifier.")
    return value


def route(endpoint: Endpoint, **ids: str) -> str:
    if not isinstance(endpoint, Endpoint):
        raise DomainError("permission_denied", "This API route is not permitted.")
    return endpoint.value.format(**{key: source_id(value) for key, value in ids.items()})


def public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validate_https(url: str, allowed_origins: set[str]) -> None:
    u = urlsplit(url)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.fragment
        or u.port not in {None, 443}
        or "\\" in url
        or "%" in u.netloc
        or f"https://{u.hostname}" not in allowed_origins
    ):
        raise DomainError("permission_denied", "Outbound destination is not approved.")


def validate_continuation(url: str, original: str) -> None:
    base, nxt = urlsplit(original), urlsplit(url)
    validate_https(url, {f"https://{base.hostname}"})
    if base.path != nxt.path or "%" in nxt.path:
        raise DomainError("permission_denied", "Unsafe pagination route.")

    def immutable(pairs):
        return sorted((k, v) for k, v in pairs if k not in {"page", "per_page"})

    base_pairs, next_pairs = parse_qsl(base.query), parse_qsl(nxt.query)
    if immutable(base_pairs) != immutable(next_pairs):
        raise DomainError("permission_denied", "Pagination changed the authorized query.")
    for key, value in next_pairs:
        if key in {"page", "per_page"} and not re.fullmatch(r"[0-9]{1,7}", value):
            raise DomainError("permission_denied", "Invalid pagination value.")
        if key == "per_page" and not 1 <= int(value) <= 100:
            raise DomainError("permission_denied", "Pagination exceeds the request budget.")
