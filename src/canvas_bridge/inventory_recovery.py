"""Content-free route evidence for partial course-file discovery."""

import re
from typing import get_args

from canvas_bridge.authorization import request_authorization
from canvas_bridge.domain import InventoryMethod
from canvas_bridge.egress_errors import SAFE_CODES
from canvas_bridge.error_guidance import retrieval_guidance

METHODS = get_args(InventoryMethod)
ACTIONS = {
    "UPSTREAM_SCOPE_INSUFFICIENT": "review_endpoint_oauth_scope",
    "MISSING_RESOURCE_CAPABILITY": "review_bridge_endpoint_configuration",
    "UPSTREAM_CREDENTIAL_REJECTED": "renew_canvas_authentication",
    "UPSTREAM_AUTH_EXPIRED": "renew_canvas_authentication",
    "UPSTREAM_THROTTLED": "honor_provider_cooldown",
    "UPSTREAM_UNAVAILABLE": "wait_for_provider_recovery",
    "RESOURCE_UNAVAILABLE": "check_resource_availability_in_canvas",
    "RESOURCE_PERMISSION_DENIED": "check_student_access_and_endpoint_permissions",
    "UNKNOWN_AUTHORIZATION_FAILURE": "verify_current_resource_access",
    "UNCLASSIFIED_FAILURE": "review_request_diagnostics",
}


def inventory_action(code, constraint=None):
    guidance = retrieval_guidance(code, constraint)
    return guidance[0] if guidance else ACTIONS.get(code, "resume_bounded_inventory")


def track_method(method):
    from canvas_bridge.failure_diagnostics import current

    attempt = current.get()
    if attempt and attempt.operation in {"list_course_files", "read_course_file"}:
        attempt.last_retrieval_method = method
        if method not in attempt.retrieval_methods:
            attempt.retrieval_methods.append(method)


def remember_assignments(row, references):
    """Keep previously observed governance parents even when a later route is partial."""
    if references:
        parents = set(row.file_state.get("inventory_assignment_refs", []))
        parents.update(references)
        if len(parents) > 512:
            from canvas_bridge.domain import DomainError

            raise DomainError(
                "operation_failed",
                "File inventory lineage exceeds the bound.",
                reason_code="INVENTORY_STATE_LIMIT",
            )
        row.file_state = {**row.file_state, "inventory_assignment_refs": sorted(parents)}


def recovery_report(data, course, request_id, methods, failures, complete=False):
    """Rebuild only reviewed facts. Unknown IDs do not enter operator logs."""
    attempted = list(dict.fromkeys(m for m in methods if isinstance(m, str) and m in METHODS))
    issues = []
    for method, detail, ref in failures:
        if method not in METHODS or not isinstance(detail, dict):
            continue
        code = detail.get("reason_code")
        if not isinstance(code, str) or code == "INVENTORY_NOT_ATTEMPTED" or not code:
            continue
        if method not in attempted and code == "INVENTORY_REQUEST_BUDGET":
            continue
        if code not in SAFE_CODES:
            code = "UNCLASSIFIED_FAILURE"
        http = detail.get("upstream_http_status")
        observed_http = type(http) is int and 100 <= http <= 599
        issue = {
            "inventory_operation": method,
            "reason_code": code,
            "origin": "canvas_api" if observed_http else "bridge",
            "recommended_action": inventory_action(code, detail.get("retrieval_constraint")),
        }
        constraint = detail.get("retrieval_constraint")
        if retrieval_guidance(code, constraint):
            issue["retrieval_constraint"] = constraint
            if constraint != "configured_endpoint_scope":
                issue["origin"] = "canvas_metadata"
        if observed_http:
            issue["upstream_http_status"] = http
        if detail.get("capability_observation") == "recent_denial":
            issue["capability_observation"] = "recent_denial"
        if isinstance(ref, str) and re.fullmatch(r"[a-f0-9]{40}", ref):
            issue["resource_id"] = ref
        original = detail.get("request_id")
        issue["request_id"] = (
            original
            if isinstance(original, str) and re.fullmatch(r"[0-9a-f]{32}", original)
            else request_id
        )
        if issue not in issues:
            issues.append(issue)
    truncated = len(issues) > 16
    if truncated:
        # Preserve a representative of each branch before additional resource details.
        first = {}
        for issue in issues:
            first.setdefault(issue["inventory_operation"], issue)
        kept = list(first.values())
        issues = (kept + [issue for issue in issues if issue not in kept])[:16]
    return {
        "truncated": truncated,
        "requested_operation": "list_course_files",
        "course_id": course,
        "request_id": request_id,
        "attempted_methods": attempted,
        "failed_methods": issues,
        "verified_file_references": sum(
            f.get("access_state") == "available_at_inventory_check" for f in data.get("files", [])
        ),
        "document_content_included": False,
        "completeness": "complete" if complete else "partial",
    }


def attach_recovery(result, course, engine):
    if result.status == "ok":
        return result
    ctx = request_authorization.get()
    ident = ctx.request_id if ctx else result.meta.request_id
    result.meta.request_id = ident
    data = result.data
    status = data.get("inventory_status", {})
    methods = status.get("retrieval_methods", [])
    failures = [
        (detail.get("failed_method", branch), detail, None)
        for branch, detail in data.get("inventory_reason_codes", {}).items()
    ]
    for key, method in (
        ("file_metadata_failures", "file"),
        ("module_item_failures", "module_items"),
    ):
        failures += [(method, detail, ref) for ref, detail in status.get(key, {}).items()]
    failures += [("file", detail, None) for detail in status.get("known_lookup_failures", [])]
    failures += [
        (detail.get("failed_method"), detail, ref)
        for ref, detail in status.get("folder_lookup_failures", {}).items()
    ]
    if data.get("reason_code"):
        failures.append((data.get("inventory_operation"), data, None))
    data["inventory_recovery"] = recovery_report(data, course, ident, methods, failures)
    from canvas_bridge.failure_events import record_branch

    observed = set()
    # The public recovery summary is capped at sixteen resource details. Journal
    # distinct branch outcomes before that cap, without storing resource IDs.
    for method, detail, _ in failures:
        if method not in METHODS or not isinstance(detail, dict):
            continue
        if detail.get("request_id", ident) != ident:
            continue
        code = detail.get("reason_code")
        if not isinstance(code, str) or code not in SAFE_CODES:
            continue
        fields = {
            key: detail[key]
            for key in (
                "upstream_http_status",
                "retrieval_constraint",
                "capability_observation",
                "retry_after_seconds",
            )
            if isinstance(detail.get(key), (str, int))
        }
        signature = (method, code, tuple(fields.items()))
        if signature in observed:
            continue
        observed.add(signature)
        record_branch(
            engine,
            {**fields, "reason_code": code, "retrieval_method": method},
            branch=method,
            pages=detail.get("pages_consumed"),
        )
    return result


def project_recovery(result, arguments):
    """Only copy the registered course and bounded reviewed route details."""
    value = result.data.get("inventory_recovery")
    if not isinstance(value, dict):
        return None
    course = arguments.get("course_id")
    if not isinstance(course, str) or course != value.get("course_id"):
        return None
    issues = value.get("failed_methods", [])
    methods = value.get("attempted_methods", [])
    if not isinstance(issues, list) or not isinstance(methods, list):
        return None
    report = recovery_report(
        result.data,
        course,
        result.meta.request_id,
        methods[: len(METHODS)],
        [
            (i.get("inventory_operation"), i, i.get("resource_id"))
            for i in issues[:16]
            if isinstance(i, dict)
        ],
    )
    report["truncated"] |= value.get("truncated") is True
    return report
