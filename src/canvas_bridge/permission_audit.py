"""Read-only permission report. Does not refresh or repair any stored state."""

import asyncio

from sqlalchemy import select

from canvas_bridge.authorization import RESOURCES, digest, log_decision, scope_version
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.storage import Connection, Course, Tombstone, aware

ACTIONS = {
    "IDENTIFIER_MAPPING_FAILURE": "investigate_canonical_id_mapping",
    "IDENTIFIER_CONNECTION_MISMATCH": "review_connection_and_course_references",
    "COURSE_NOT_SELECTED": "review_course_selection",
    "SELECTED_SCOPE_MISMATCH": "inspect_scope_mapping",
    "STALE_SCOPE_SNAPSHOT": "reconcile_scope_snapshots",
    "CONNECTION_INACTIVE": "reconnect_canvas_account",
    "UPSTREAM_AUTH_EXPIRED": "reconnect_canvas_account",
    "UPSTREAM_AUTH_UNVERIFIED": "reconnect_canvas_account",
    "RESOURCE_PERMISSION_DENIED": "review_resource_permissions",
    "MISSING_RESOURCE_CAPABILITY": "review_resource_capabilities",
    "UPSTREAM_UNAVAILABLE": "retry_after_upstream_recovery",
    "RESOURCE_UNAVAILABLE": "refresh_authorized_course_metadata",
    "UNKNOWN_AUTHORIZATION_FAILURE": "inspect_authorization_evidence",
    "NO_SAFE_METADATA_PROBE": "use_explicit_resource_workflow_if_needed",
}


async def audit_permissions(
    bridge, owner, ref, course_id=None, resource_types=None, include_upstream_checks=False
):
    resources = list(dict.fromkeys(resource_types if resource_types is not None else RESOURCES))
    if not resources or len(resources) > len(RESOURCES) or set(resources) - set(RESOURCES):
        raise DomainError("needs_input", "Choose one to seven supported resource types.")
    with bridge.store.transaction() as session:
        conn = session.scalar(
            select(Connection).where(Connection.owner == owner, Connection.id == ref)
        )
        if conn is None:
            # Same shape for nonexistent and foreign connections: no existence oracle.
            bridge.authorize(owner, ref, course_id or "", track=False).require()
        inactive = conn.state != "active" or session.get(Tombstone, ref) is not None
        rows = list(
            session.scalars(
                select(Course).where(Course.owner == owner, Course.connection_id == ref)
            )
        )
        version = scope_version(conn, rows, bridge.registry.entries.get(conn.institution))
        courses = [course_id] if course_id is not None else [c.id for c in rows if c.selected]
        if len(courses) > min(30, bridge.settings.max_courses):
            raise DomainError(
                "needs_input", "Audit one course or reduce the selected-course scope."
            )
    checks = []
    credential_state = (
        "unavailable"
        if not conn.credential
        else "expired"
        if (conn.token_expires_at and aware(conn.token_expires_at) <= utcnow())
        else "present_not_verified"
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + bridge.settings.refresh_budget_seconds
    probes = 0
    upstream_auth_failure = None
    for target in courses:
        for resource in resources:
            d = bridge.authorize(owner, ref, target, resource, "metadata", track=False)
            if d.credential_state in {"expired", "unavailable"}:
                credential_state = d.credential_state
            classification = (
                "consistent"
                if d.allowed
                or d.reason_code
                in {"COURSE_NOT_SELECTED", "MISSING_RESOURCE_CAPABILITY", "CONNECTION_INACTIVE"}
                else "indeterminate"
            )
            if d.reason_code == "SELECTED_SCOPE_MISMATCH" or d.identifier_state == "inconsistent":
                classification = "inconsistent"
            check = {
                "course_id": d.course.id if d.course else None,
                "resource": resource,
                "advertised_selected": d.advertised_selected,
                "connection_owned": d.connection_owned,
                "identifier_state": d.identifier_state,
                "scope_authorized": d.scope_authorized,
                "resource_capability": d.resource_capability,
                "authorization_freshness": d.authorization_freshness,
                "scope_snapshot_version": d.scope_snapshot_version,
                "upstream_permission": "not_checked",
                "upstream_http_status": None,
                "result": classification,
                "reason_code": d.reason_code,
            }
            if include_upstream_checks and d.allowed:
                if upstream_auth_failure:
                    check.update(
                        result="not_checked",
                        reason_code=upstream_auth_failure,
                        upstream_permission="unknown",
                    )
                elif resource in {"grades", "syllabus"}:
                    check.update(result="not_checked", reason_code="NO_SAFE_METADATA_PROBE")
                elif probes >= 30 or loop.time() >= deadline:
                    check.update(result="not_checked", reason_code="UPSTREAM_UNAVAILABLE")
                else:
                    probes += 1
                    try:
                        async with asyncio.timeout(max(0.001, deadline - loop.time())):
                            async with bridge.client(
                                owner, ref, refresh_credentials=False, track_authorization=False
                            ) as client:
                                code = await client.probe_metadata(resource, d.course.source_id)
                        check.update(
                            upstream_permission="allowed",
                            upstream_http_status=code,
                            reason_code="UPSTREAM_METADATA_ACCESS_CONFIRMED",
                        )
                        credential_state = "accepted_for_metadata_request"
                    except (DomainError, TimeoutError) as exc:
                        reason = (
                            exc.reason_code or "UNKNOWN_AUTHORIZATION_FAILURE"
                            if isinstance(exc, DomainError)
                            else "UPSTREAM_UNAVAILABLE"
                        )
                        code = exc.upstream_http_status if isinstance(exc, DomainError) else None
                        check.update(
                            upstream_permission="denied"
                            if reason == "RESOURCE_PERMISSION_DENIED"
                            else "unknown",
                            upstream_http_status=code,
                            result="consistent"
                            if reason == "RESOURCE_PERMISSION_DENIED"
                            else "indeterminate",
                            reason_code=reason,
                        )
                        if reason == "UPSTREAM_AUTH_EXPIRED":
                            credential_state = "expired_or_rejected"
                        if code == 401 or reason == "UPSTREAM_AUTH_EXPIRED":
                            upstream_auth_failure = reason
                    log_decision(
                        owner,
                        ref,
                        target,
                        resource,
                        d,
                        http_status=check["upstream_http_status"],
                        reason=check["reason_code"],
                    )
            check["recommended_action"] = ACTIONS.get(check["reason_code"], "none")
            checks.append(check)

    # Never silently retry/re-authorize a changed request. Discard probe conclusions
    # when local scope/capabilities changed while it was in flight.
    with bridge.store.transaction() as session:
        current = session.scalar(
            select(Connection).where(Connection.owner == owner, Connection.id == ref)
        )
        if current is None:
            raise DomainError(
                "permission_denied",
                "Connection unavailable.",
                reason_code="CONNECTION_OWNERSHIP_MISMATCH",
            )
        rows = list(
            session.scalars(
                select(Course).where(Course.owner == owner, Course.connection_id == ref)
            )
        )
        after_version = scope_version(
            current, rows, bridge.registry.entries.get(current.institution)
        )
    changed = after_version != version
    if changed:
        for check in checks:
            check.update(
                scope_authorized=False,
                upstream_permission="unknown",
                result="inconsistent",
                reason_code="STALE_SCOPE_SNAPSHOT",
                recommended_action="reconcile_scope_snapshots",
            )
    else:
        for check in checks:
            if not check["course_id"]:
                continue
            current_decision = bridge.authorize(
                owner, ref, check["course_id"], check["resource"], "metadata", track=False
            )
            if not current_decision.allowed and check["reason_code"] in {
                "AUTHORIZED_LOCAL_SCOPE",
                "UPSTREAM_METADATA_ACCESS_CONFIRMED",
                "NO_SAFE_METADATA_PROBE",
                "RESOURCE_PERMISSION_DENIED",
                "UPSTREAM_UNAVAILABLE",
                "RESOURCE_UNAVAILABLE",
            }:
                check.update(
                    scope_authorized=current_decision.scope_authorized,
                    upstream_permission="unknown",
                    result="indeterminate",
                    reason_code=current_decision.reason_code,
                    authorization_freshness=current_decision.authorization_freshness,
                    recommended_action=ACTIONS.get(
                        current_decision.reason_code, "inspect_authorization_evidence"
                    ),
                )
                credential_state = current_decision.credential_state
    reasons = [c["reason_code"] for c in checks]
    if inactive:
        reasons.append("CONNECTION_INACTIVE")
    elif credential_state in {"expired", "unavailable"}:
        reasons.append(
            "UPSTREAM_AUTH_EXPIRED" if credential_state == "expired" else "UPSTREAM_AUTH_UNVERIFIED"
        )
    mismatch = any(c["result"] == "inconsistent" for c in checks)
    unresolved = any(c["result"] in {"indeterminate", "not_checked"} for c in checks)
    restricted = any(c["reason_code"] in ACTIONS for c in checks)
    status = "partial_data" if mismatch or unresolved or restricted else "ok"
    if any(
        r in {"UPSTREAM_AUTH_EXPIRED", "UPSTREAM_AUTH_UNVERIFIED", "CONNECTION_INACTIVE"}
        for r in reasons
    ):
        status = "reconnect_required"
    elif (
        course_id
        and reasons
        and all(
            r
            in {
                "IDENTIFIER_MAPPING_FAILURE",
                "IDENTIFIER_CONNECTION_MISMATCH",
                "COURSE_NOT_SELECTED",
            }
            for r in reasons
        )
    ):
        status = "permission_denied"
    recommendations = list(
        dict.fromkeys(c["recommended_action"] for c in checks if c["recommended_action"] != "none")
    )
    if not recommendations and any(r in ACTIONS for r in reasons):
        recommendations = list(dict.fromkeys(ACTIONS[r] for r in reasons if r in ACTIONS))
    return Result(
        status=status,
        summary="Permission consistency audit completed with restrictions or unresolved evidence."
        if status != "ok"
        else "Local permission checks agree; upstream permissions are reported only where checked.",
        data={
            "connection_state": current.state,
            "credential_state": credential_state,
            "scope_consistency": "mismatch"
            if mismatch
            else "indeterminate"
            if unresolved
            else "consistent",
            "scope_snapshot_version": version,
            "current_scope_snapshot_version": after_version,
            "correlation_id": digest(owner + "\0" + ref),
            "checks": checks,
            "recommended_action": recommendations[0] if recommendations else "none",
            "recommended_actions": recommendations,
            "upstream_checks_requested": include_upstream_checks,
            "upstream_requests": probes,
            "state_modified": False,
            "limitations": [
                "Selection, local authorization, upstream endpoint access and extraction are separate stages.",
                "A successful metadata request does not authorize every item in that resource collection.",
                "Metadata probes do not refresh student-enrollment evidence or establish all resource privileges.",
                "Grade and syllabus permission cannot be conclusively probed here without content reads.",
                "No historical advertised scope was retained; compare correlation IDs and scope versions across calls.",
                "Only this account's mappings can distinguish a different owned connection; no foreign-owner lookup or automatic ID repair occurs.",
            ],
        },
        meta=bridge.meta(
            freshness="synthetic" if bridge.synthetic else "cached" if not probes else "live"
        ),
    )
