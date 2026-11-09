"""Reviewed public permission-audit recovery instructions, indexed by stable action ID."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Action:
    kind: Literal["tool", "user", "operator", "wait"]
    instruction: str
    retry_condition: str
    tool_name: str | None = None


DEFINITIONS = {
    "refresh_course_list_then_retry": Action(
        "tool",
        "Call list_courses with the same connection_id. For a partial or failed listing, follow the listing's guidance.",
        "Rerun the original audit once after a complete, successful course listing.",
        "list_courses",
    ),
    "repeat_permission_audit": Action(
        "tool",
        "Run audit_permission_consistency once with the same arguments against the current selection.",
        "If scope changes again, wait until course selection and connection settings are stable.",
        "audit_permission_consistency",
    ),
    "review_provider_authorization": Action(
        "operator",
        "Ask the operator to review authorization for the upstream provider.",
        "Retry after the operator confirms the provider is authorized.",
    ),
    "operator_configuration_required": Action(
        "operator",
        "Ask the operator to configure the provider billing contract.",
        "Retry after the contract is configured.",
    ),
    "use_permitted_cached_or_local_information": Action(
        "user",
        "Use already authorized cached or local information for this task.",
        "Resume upstream checks when the provider budget is available.",
    ),
    "defer_or_narrow_retrieval": Action(
        "user",
        "Narrow the requested courses or resources, or defer the retrieval.",
        "Retry with a smaller request or when the workload pool has capacity.",
    ),
    "wait_for_request_capacity": Action(
        "wait",
        "Wait for the account request limit to clear.",
        "Retry after the reported delay, when available.",
    ),
    "resume_bounded_task": Action(
        "user",
        "Resume with a smaller set of resources for one course.",
        "Retry when the narrowed request fits the task budget.",
    ),
    "retry_after_upstream_recovery": Action(
        "wait",
        "Wait for upstream request capacity or service recovery.",
        "Honor any reported retry delay. If the audit reached its probe limit, retry with fewer resources.",
    ),
    "operator_accounting_recovery_required": Action(
        "operator",
        "Ask the operator to restore provider usage accounting.",
        "Retry after the operator confirms accounting is available.",
    ),
    "investigate_canonical_id_mapping": Action(
        "user",
        "Check the exact course ID returned for this connection. Ask the operator to inspect the mapping if that ID still fails.",
        "Retry with the verified ID or after the operator repairs its mapping.",
    ),
    "review_connection_and_course_references": Action(
        "user",
        "Use the course ID and connection ID returned together for the intended account.",
        "Retry after verifying the pair.",
    ),
    "review_course_selection": Action(
        "user",
        "Review the selected courses in connection settings.",
        "Retry if the intended course is available and explicitly selected.",
    ),
    "inspect_scope_mapping": Action(
        "operator",
        "Ask the operator to compare the selected course with its current enrollment and local access mapping.",
        "Retry after selection and authorized membership agree.",
    ),
    "reconnect_canvas_account": Action(
        "user",
        "Use the approved Canvas link in settings if available, or contact the personal deployment operator.",
        "Retry after the connection is active and its course listing succeeds.",
    ),
    "review_resource_permissions": Action(
        "user",
        "Check whether the resource is visible in Canvas. Ask the course staff about access if needed.",
        "Retry when access to that resource has been confirmed.",
    ),
    "review_resource_capabilities": Action(
        "operator",
        "Ask the operator to review the resource capability and approved endpoint scopes.",
        "Retry when the capability is enabled and authorized.",
    ),
    "refresh_authorized_course_metadata": Action(
        "user",
        "Check the resource in Canvas and obtain its current reference from the authorized course workflow.",
        "Retry when the resource is visible and its reference is current.",
    ),
    "inspect_authorization_evidence": Action(
        "operator",
        "Give the operator the request ID to investigate the authorization decision.",
        "Retry when the operator identifies and resolves the cause.",
    ),
    "use_explicit_resource_workflow_if_needed": Action(
        "user",
        "If you need grades or a syllabus, explicitly request the corresponding course workflow.",
        "Use that workflow only when the resource is needed and access is authorized.",
    ),
}


def recovery_actions(action_ids):
    """Return fresh public records using only known IDs and server-authored values."""
    result = []
    seen = set()
    for action_id in action_ids:
        if not isinstance(action_id, str) or action_id in seen or action_id not in DEFINITIONS:
            continue
        action = DEFINITIONS[action_id]
        record = {
            "action_id": action_id,
            "kind": action.kind,
            "instruction": action.instruction,
            "retry_condition": action.retry_condition,
        }
        if action.tool_name:
            record["tool_name"] = action.tool_name
        result.append(record)
        seen.add(action_id)
    return result
