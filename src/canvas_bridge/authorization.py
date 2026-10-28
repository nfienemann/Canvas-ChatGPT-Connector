"""One fail-closed foundation for course reads and read-only diagnostics.

The principal is supplied only by trusted server code (request_identity at MCP).
Local permission to attempt an allowlisted read is not an upstream permission grant.
No prefix matching, identifier repair, credential refresh, or persistence here.
"""

import hashlib
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select

from canvas_bridge.domain import DomainError, opaque_id, utcnow
from canvas_bridge.normalize import canonical_id
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.retention_policy import CONNECTION_LIFETIME
from canvas_bridge.storage import Connection, Course, Tombstone, aware

Resource = Literal["course", "files", "modules", "assignments", "syllabus", "quizzes", "grades"]
RESOURCES = ("course", "files", "modules", "assignments", "syllabus", "quizzes", "grades")

# Reviewed scopes; these describe configured ceilings, never inferred token grants.
SCOPES = {
    Endpoint.PROFILE: "url:GET|/api/v1/users/:user_id/profile",
    Endpoint.COURSES: "url:GET|/api/v1/courses",
    Endpoint.SUBMISSION: "url:GET|/api/v1/courses/:course_id/assignments/:assignment_id/submissions/:user_id",
    Endpoint.COURSE: "url:GET|/api/v1/courses/:id",
    Endpoint.FILES: "url:GET|/api/v1/courses/:course_id/files",
    Endpoint.FILE: "url:GET|/api/v1/courses/:course_id/files/:id",
    Endpoint.MODULES: "url:GET|/api/v1/courses/:course_id/modules",
    Endpoint.MODULE_ITEMS: "url:GET|/api/v1/courses/:course_id/modules/:module_id/items",
    Endpoint.ASSIGNMENTS: "url:GET|/api/v1/courses/:course_id/assignments",
    Endpoint.ASSIGNMENT: "url:GET|/api/v1/courses/:course_id/assignments/:id",
    Endpoint.ASSIGNMENT_GROUPS: "url:GET|/api/v1/courses/:course_id/assignment_groups",
    Endpoint.PAGES: "url:GET|/api/v1/courses/:course_id/pages",
    Endpoint.PAGE: "url:GET|/api/v1/courses/:course_id/pages/:url_or_id",
    Endpoint.ENROLLMENTS: "url:GET|/api/v1/users/:user_id/enrollments",
    Endpoint.QUIZZES: "url:GET|/api/v1/courses/:course_id/quizzes",
    Endpoint.DISCUSSIONS: "url:GET|/api/v1/courses/:course_id/discussion_topics",
    Endpoint.DISCUSSION: "url:GET|/api/v1/courses/:course_id/discussion_topics/:topic_id",
    Endpoint.DISCUSSION_VIEW: "url:GET|/api/v1/courses/:course_id/discussion_topics/:topic_id/view",
    Endpoint.DISCUSSION_ENTRIES: "url:GET|/api/v1/courses/:course_id/discussion_topics/:topic_id/entries",
    Endpoint.DISCUSSION_REPLIES: "url:GET|/api/v1/courses/:course_id/discussion_topics/:topic_id/entries/:entry_id/replies",
    Endpoint.DISCUSSION_DATES: "url:GET|/api/v1/courses/:course_id/discussion_topics/:discussion_topic_id/date_details",
    Endpoint.CALENDAR_EVENTS: "url:GET|/api/v1/calendar_events",
    Endpoint.ANNOUNCEMENTS: "url:GET|/api/v1/announcements",
}
RESOURCE_ENDPOINT = {
    "course": Endpoint.COURSE,
    "files": Endpoint.FILES,
    "modules": Endpoint.MODULES,
    "assignments": Endpoint.ASSIGNMENTS,
    "submissions": Endpoint.SUBMISSION,
    "syllabus": Endpoint.COURSE,
    "quizzes": Endpoint.QUIZZES,
    "grades": Endpoint.ENROLLMENTS,
    "pages": Endpoint.PAGES,
    "announcements": Endpoint.ANNOUNCEMENTS,
    "discussions": Endpoint.DISCUSSIONS,
    "calendar": Endpoint.CALENDAR_EVENTS,
}
ENDPOINT_RESOURCE = {
    Endpoint.SUBMISSION: "submissions",
    Endpoint.COURSE: "course",
    Endpoint.FILES: "files",
    Endpoint.FILE: "files",
    Endpoint.MODULES: "modules",
    Endpoint.MODULE_ITEMS: "modules",
    Endpoint.ASSIGNMENTS: "assignments",
    Endpoint.ASSIGNMENT: "assignments",
    Endpoint.ASSIGNMENT_GROUPS: "grades",
    Endpoint.ENROLLMENTS: "grades",
    Endpoint.QUIZZES: "quizzes",
    Endpoint.PAGES: "pages",
    Endpoint.PAGE: "pages",
    Endpoint.DISCUSSIONS: "discussions",
    Endpoint.DISCUSSION: "discussions",
    Endpoint.DISCUSSION_VIEW: "discussions",
    Endpoint.DISCUSSION_ENTRIES: "discussions",
    Endpoint.DISCUSSION_REPLIES: "discussions",
    Endpoint.DISCUSSION_DATES: "discussions",
    Endpoint.CALENDAR_EVENTS: "calendar",
    Endpoint.ANNOUNCEMENTS: "announcements",
}
MESSAGES = {
    "CONNECTION_OWNERSHIP_MISMATCH": "Connection unavailable for the authenticated account.",
    "CONNECTION_INACTIVE": "This connection is disabled. Reconnect in settings.",
    "UPSTREAM_AUTH_EXPIRED": "The Canvas credential has expired; reconnect the Canvas account.",
    "UPSTREAM_AUTH_UNVERIFIED": "The Canvas credential is unavailable; reconnect the Canvas account.",
    "IDENTIFIER_MAPPING_FAILURE": "The course reference cannot be resolved in this connection. Use the exact opaque ID returned by connection status or course listing.",
    "IDENTIFIER_CONNECTION_MISMATCH": "This course reference belongs to a different connection owned by this account. Use an exact course ID from the requested connection.",
    "COURSE_NOT_SELECTED": "The requested course is not included in the connection's current selected-course scope.",
    "SELECTED_SCOPE_MISMATCH": "The selected course is not authorized by the current course-access snapshot.",
    "STALE_SCOPE_SNAPSHOT": "The course-selection snapshot differs from the current authorization state or its authorization lease has expired.",
    "MISSING_RESOURCE_CAPABILITY": "The course is selected, but the requested resource cannot be accessed with the current connector capabilities.",
    "RESOURCE_PERMISSION_DENIED": "The course is selected, but the requested resource cannot be accessed with the current permissions.",
    "UPSTREAM_UNAVAILABLE": "The connector could not verify resource access because the upstream service was unavailable.",
    "RESOURCE_UNAVAILABLE": "The resource is unavailable; absence and denied visibility cannot be distinguished.",
    "UNKNOWN_AUTHORIZATION_FAILURE": "The connector could not verify authorization for this request.",
}
logger = logging.getLogger("canvas_bridge.authorization")


@dataclass
class RequestAuthorization:
    tool_name: str
    recipient: str = "local"
    request_id: str = field(default_factory=opaque_id)
    # In-memory request fence only. No academic records or historical auth cache.
    decisions: dict = field(default_factory=dict)
    policy_checks: dict = field(default_factory=dict)
    policy_failure: DomainError | None = None
    egress_identity: object | None = None
    egress_principal: str | None = None
    egress_arguments: dict = field(default_factory=dict)


request_authorization: ContextVar[RequestAuthorization | None] = ContextVar(
    "request_authorization", default=None
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def scope_version(conn, courses, institution):
    state = [
        conn.institution,
        conn.canvas_user,
        institution.origin if institution else None,
        conn.epoch,
        conn.state,
        bool(conn.credential),
        digest(conn.credential or ""),
        aware(conn.token_expires_at).isoformat() if conn.token_expires_at else None,
        sorted(
            (c.id, c.source_id, c.selected, c.accessible, c.enrollment_state, c.version)
            for c in courses
        ),
        sorted(institution.scopes) if institution else None,
        institution.status if institution else None,
        sorted(institution.capabilities) if institution else None,
        institution.oauth.model_dump() if institution and institution.oauth else None,
        conn.authentication_state,
    ]
    return digest(json.dumps(state, sort_keys=True))


@dataclass
class AuthorizationDecision:
    allowed: bool = False
    connection_owned: bool = False
    advertised_selected: bool | None = None
    scope_authorized: bool = False
    resource_capability: str = "unknown"
    reason_code: str = "UNKNOWN_AUTHORIZATION_FAILURE"
    status: str = "permission_denied"
    connection_state: str = "unavailable"
    scope_snapshot_version: str | None = None
    identifier_state: str = "unresolved"
    authorization_freshness: str = "unknown"
    credential_state: str = "not_checked"
    course: Course | None = field(default=None, repr=False)
    connection: Connection | None = field(default=None, repr=False)
    policy_error: DomainError | None = field(default=None, repr=False)

    def require(self):
        if self.policy_error:
            raise self.policy_error
        if not self.allowed:
            raise DomainError(self.status, MESSAGES[self.reason_code], reason_code=self.reason_code)
        return self


def log_decision(owner, ref, course_ref, resource, decision, *, http_status=None, reason=None):
    context = request_authorization.get()
    record = {
        "request_id": context.request_id if context else opaque_id(),
        "tool_name": context.tool_name if context else "internal_course_authorization",
        "correlation_id": digest(owner + "\0" + ref),
        "connection_reference": digest(owner + "\0connection\0" + ref),
        "course_reference": digest(owner + "\0" + ref + "\0" + course_ref),
        "resource_type": resource,
        "authorization_decision": "allow" if decision.allowed else "deny",
        "reason_code": reason or decision.reason_code,
        "scope_snapshot_version": decision.scope_snapshot_version,
        "upstream_http_status": http_status,
        "timestamp": utcnow().isoformat(),
    }
    logger.info("permission_decision %s", json.dumps(record, sort_keys=True))


def authorize_course_resource(
    bridge,
    principal,
    connection_id,
    course_id,
    resource_type="course",
    operation="read",
    *,
    session=None,
    track=True,
):
    """Exact owner/connection mapping, current selection, lease and capability.

    `principal` is a server-resolved owner key, never an MCP argument. A configured
    OAuth scope ceiling is enforced independently of Canvas's actual permission.
    Legacy personal/synthetic credentials have no scope list: their upstream grant
    remains unknown and each real resource read must still succeed at Canvas.
    """
    if session is None:
        with bridge.store.transaction() as current:
            return authorize_course_resource(
                bridge,
                principal,
                connection_id,
                course_id,
                resource_type,
                operation,
                session=current,
                track=track,
            )
    d = AuthorizationDecision()
    conn = session.scalar(
        select(Connection).where(Connection.id == connection_id, Connection.owner == principal)
    )
    if conn is None:
        d.reason_code = "CONNECTION_OWNERSHIP_MISMATCH"
    else:
        d.connection, d.connection_owned, d.connection_state = conn, True, conn.state
        rows = list(
            session.scalars(
                select(Course).where(
                    Course.owner == principal, Course.connection_id == connection_id
                )
            )
        )
        institution = bridge.registry.entries.get(conn.institution)
        d.scope_snapshot_version = scope_version(conn, rows, institution)
        course = next((c for c in rows if c.id == course_id), None)
        d.advertised_selected = bool(course and course.selected)
        d.course = course
        d.credential_state = (
            "unavailable"
            if not conn.credential
            else "expired"
            if conn.token_expires_at and aware(conn.token_expires_at) <= utcnow()
            else "present_not_verified"
        )
        fresh = bool(
            conn.entitlement_at
            and 0
            <= (utcnow() - aware(conn.entitlement_at)).total_seconds()
            <= bridge.settings.authorization_lease_seconds
        )
        d.authorization_freshness = "within_lease" if fresh else "stale"
        if (
            conn.state != "active"
            or session.get(Tombstone, connection_id)
            or aware(conn.created_at) + CONNECTION_LIFETIME <= bridge.retention.clock()
        ):
            d.reason_code, d.status = "CONNECTION_INACTIVE", "reconnect_required"
        elif not re.fullmatch(r"[0-9a-f]{40}", course_id):
            d.identifier_state = "invalid_format"
            d.reason_code = "IDENTIFIER_MAPPING_FAILURE"
        elif course is None:
            # Only the authenticated owner's mappings may distinguish connections.
            # Foreign owners and nonexistent references remain indistinguishable.
            other_owned = session.scalar(
                select(Course.id).where(
                    Course.id == course_id,
                    Course.owner == principal,
                    Course.connection_id != connection_id,
                )
            )
            d.identifier_state = "different_owned_connection" if other_owned else "unresolved"
            d.reason_code = (
                "IDENTIFIER_CONNECTION_MISMATCH" if other_owned else "IDENTIFIER_MAPPING_FAILURE"
            )
        else:
            try:
                valid_mapping = course.id == canonical_id(
                    principal, connection_id, "course", source_id(course.source_id)
                )
            except DomainError:
                valid_mapping = False
            d.identifier_state = "canonical" if valid_mapping else "inconsistent"
            d.scope_authorized = bool(
                valid_mapping
                and course.selected
                and course.accessible
                and course.enrollment_state == "active"
                and fresh
            )
            if not valid_mapping:
                d.reason_code = "IDENTIFIER_MAPPING_FAILURE"
            elif not course.selected:
                d.reason_code = "COURSE_NOT_SELECTED"
            elif not course.accessible or course.enrollment_state != "active":
                d.reason_code = "SELECTED_SCOPE_MISMATCH"
            elif d.credential_state in {"expired", "unavailable"}:
                d.reason_code = (
                    "UPSTREAM_AUTH_EXPIRED"
                    if d.credential_state == "expired"
                    else "UPSTREAM_AUTH_UNVERIFIED"
                )
                d.status = "reconnect_required"
            elif not fresh:
                d.reason_code, d.status = "STALE_SCOPE_SNAPSHOT", "retry_later"
            else:
                d.scope_authorized = True
                endpoint = RESOURCE_ENDPOINT.get(resource_type)
                if operation in SCOPES:
                    endpoint = operation
                supported = (
                    operation in {"read", "metadata", "list", "scope"} or operation in SCOPES
                )
                if (
                    not supported
                    or endpoint is None
                    or institution is None
                    or (bridge.settings.profile == "hosted" and not institution.scopes)
                ):
                    d.reason_code = "MISSING_RESOURCE_CAPABILITY"
                    d.resource_capability = "unavailable"
                elif (
                    institution.scopes
                    and SCOPES[endpoint] not in institution.scopes
                    and not (resource_type == "course" and operation == "scope")
                ):
                    d.reason_code = "MISSING_RESOURCE_CAPABILITY"
                    d.resource_capability = "unavailable"
                else:
                    d.allowed, d.reason_code, d.status = True, "AUTHORIZED_LOCAL_SCOPE", "ok"
                    d.resource_capability = (
                        "configured" if institution.scopes else "allowlisted_upstream_unverified"
                    )
                    try:
                        bridge.registry.require(
                            conn.institution,
                            bridge.settings.profile == "synthetic",
                            personal=bridge.settings.profile == "personal",
                        )
                    except DomainError:
                        d.allowed, d.reason_code, d.status = (
                            False,
                            "MISSING_RESOURCE_CAPABILITY",
                            "unsupported_feature",
                        )
                        d.resource_capability = "unavailable"
    if d.allowed:
        from canvas_bridge.approval_policy import resource_categories
        from canvas_bridge.oauth_security import (
            endpoint_capabilities,
            require_capabilities,
            require_connection_identity,
        )

        try:
            require_connection_identity(bridge, d.connection)
            require_capabilities(
                bridge, institution, endpoint_capabilities(endpoint, resource_type)
            )
            bridge.require_policy(
                d.connection.institution,
                resource_categories(resource_type),
                resource=course_id,
                track=track,
            )
        except DomainError as exc:
            d.allowed, d.reason_code, d.status = False, exc.reason_code, exc.status
            d.policy_error = exc
    log_decision(principal, connection_id, course_id, resource_type, d)
    context = request_authorization.get()
    if d.allowed and track and context:
        key = (principal, connection_id, course_id, resource_type, operation)
        previous = context.decisions.setdefault(key, d.scope_snapshot_version)
        if previous != d.scope_snapshot_version:
            raise DomainError(
                "source_changed",
                MESSAGES["STALE_SCOPE_SNAPSHOT"],
                reason_code="STALE_SCOPE_SNAPSHOT",
            )
    return d


def validate_request_authorization(bridge):
    context = request_authorization.get()
    if context:
        if context.policy_failure:
            raise context.policy_failure
        for key, version in list(context.decisions.items()):
            d = authorize_course_resource(bridge, *key, track=False)
            d.require()
            if d.scope_snapshot_version != version:
                raise DomainError(
                    "source_changed",
                    MESSAGES["STALE_SCOPE_SNAPSHOT"],
                    reason_code="STALE_SCOPE_SNAPSHOT",
                )
        for check in list(context.policy_checks.values()):
            check()
