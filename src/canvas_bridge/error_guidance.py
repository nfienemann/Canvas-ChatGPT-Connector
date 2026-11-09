"""Reviewed public failure explanations; caller text cannot supply guidance."""

# (origin, next action, retry condition, explanation). No identifiers or source text.
GUIDANCE = {
    "PAGINATION_LINK_INVALID": (
        "upstream_inventory",
        "retry_affected_collection",
        "valid_provider_continuation",
        "Canvas supplied an invalid or unsupported continuation. Refresh the affected collection. If it recurs, report the request ID.",
    ),
    "PAGINATION_SCOPE_CHANGED": (
        "source_access",
        "report_request_id",
        "valid_provider_continuation",
        "The continuation changed the approved route or query scope. Ask the operator to inspect pagination using the request ID.",
    ),
    "SHARED_READ_INTERRUPTED": (
        "bridge_admission",
        "retry_affected_request",
        "fresh_authorized_request",
        "The shared provider read was interrupted. Retry the request.",
    ),
    "UPSTREAM_SCOPE_INSUFFICIENT": (
        "source_access",
        "review_endpoint_oauth_scope",
        "authorized_endpoint_scope",
        "Canvas reported insufficient OAuth scope. Ask the operator to compare the read endpoint with the developer key and granted scopes.",
    ),
    "DOCUMENT_SANDBOX_SETUP_TIMEOUT": (
        "document_runtime",
        "check_runtime_setup_and_retry",
        "runtime_setup_completed",
        "Sandbox permission setup exceeded its time budget. No document worker was started by this attempt. Retry once; if setup times out again, ask the operator to check the renderer installation and filesystem using the request ID.",
    ),
    "DOCUMENT_RUNTIME_SETUP_FAILED": (
        "document_runtime",
        "check_runtime_installation",
        "runtime_repaired",
        "The isolated document runtime could not be prepared. Ask the operator to check its installation, filesystem access and available disk space using the request ID. Reconnecting to Canvas will not repair this runtime.",
    ),
    "UNSUPPORTED_FILE_FORMAT": (
        "document_parser",
        "use_supported_text_format",
        "supported_document_input",
        "This file type is not supported by the text reader. Supported formats are PDF, DOCX, PPTX, XLSX, TXT and Markdown. Standalone image transcription is not provided by this tool.",
    ),
    "LOCAL_REQUEST_BUSY": (
        "bridge_admission",
        "wait_for_active_request_then_retry",
        "active_request_finished",
        "Another request is using available Canvas request capacity. Let it finish, then retry. Reconnecting is not required.",
    ),
    "AUTHORIZATION_BUSY": (
        "bridge_authorization",
        "wait_for_active_request_then_retry",
        "active_request_finished",
        "A connection read or database maintenance operation is still active. Wait for it to finish, then retry; no authorization check was bypassed. Reconnecting is not required.",
    ),
    "STALE_SCOPE_SNAPSHOT": (
        "bridge_authorization",
        "refresh_course_list_then_retry",
        "successful_membership_refresh",
        "The selected-course authorization snapshot or its lease is no longer current. Refresh the course list successfully before retrying. Authentication alone does not refresh course access.",
    ),
    "UPSTREAM_THROTTLED": (
        "provider_access",
        "honor_retry_after_then_retry",
        "provider_cooldown_finished",
        "Canvas access is throttled or a provider cooldown is active. Honor the reported retry delay; if none is available, wait before retrying. This code alone does not establish a Canvas HTTP 429.",
    ),
    "UPSTREAM_CIRCUIT_OPEN": (
        "provider_access",
        "wait_for_recovery_probe_then_retry",
        "provider_recovery",
        "Provider access is paused after repeated failures while a recovery probe is active. Wait for recovery before retrying.",
    ),
    "EGRESS_CLASSIFICATION_UNKNOWN": (
        "content_governance",
        "request_source_classification_review",
        "authorized_source_review",
        "The source's content classification is unknown, so sharing was withheld. An authorized reviewer must classify this source; reconnecting will not supply that review.",
    ),
    "EGRESS_GOVERNANCE_MISSING": (
        "content_governance",
        "review_source_and_recipient_permissions",
        "authorized_source_review",
        "Required source or recipient permission evidence is missing. Review the applicable sharing permissions; Canvas sign-in alone does not authorize release.",
    ),
    "EGRESS_CONTENT_HASH_REVIEW_REQUIRED": (
        "content_governance",
        "review_current_source_version",
        "authorized_current_version_review",
        "The current source version needs an exact content review before sharing. Approval for an older or different version cannot be reused.",
    ),
    "EGRESS_MODALITY_REVIEW_REQUIRED": (
        "content_governance",
        "review_requested_modality_permission",
        "authorized_modality_review",
        "The requested image, text or original-file channel needs its own sharing review. Permission for another channel does not cover this request.",
    ),
    "RENDER_DEPENDENCY_UNAVAILABLE": (
        "document_runtime",
        "check_renderer_installation",
        "runtime_repaired",
        "A required rendering dependency is unavailable. Check the configured renderer installation; text extraction may remain independently available.",
    ),
    "RENDER_IMAGE_OUTPUT_LIMIT": (
        "document_runtime",
        "request_smaller_render_if_supported",
        "smaller_supported_render",
        "The rendered image exceeded the output limit, including any bounded fallback. Try a smaller supported render; this is not an authorization failure.",
    ),
    "RENDER_PAGE_LIMIT_OR_RANGE": (
        "document_runtime",
        "check_page_number_and_document_limits",
        "valid_page_request",
        "The requested page is outside the available range or configured page limit. Check document status and request a valid page.",
    ),
    "DOCUMENT_WORKER_TIMEOUT": (
        "document_runtime",
        "retry_bounded_document_processing",
        "bounded_retry",
        "Document processing exceeded its time budget. Retry once with a narrower supported request; repeated failures need operator investigation using the request ID.",
    ),
    "INVENTORY_PAGINATION_CYCLE": (
        "upstream_inventory",
        "retain_partial_inventory_and_report_request_id",
        "upstream_pagination_repaired",
        "Inventory pagination repeated a page. Traversal stopped to avoid a loop; retain partial results and report the request ID. The course inventory is incomplete.",
    ),
    "INVENTORY_CURSOR_INVALID": (
        "bridge_inventory",
        "restart_inventory_with_current_scope",
        "new_inventory_checkpoint",
        "The inventory continuation is invalid, expired or unavailable. Start a fresh inventory in the current selected scope; do not treat previous partial discovery as complete.",
    ),
    "RESOURCE_PERMISSION_DENIED": (
        "source_access",
        "check_resource_access_in_canvas",
        "resource_access_restored",
        "Access to this resource was denied. Check its availability in Canvas; a working account connection does not prove access to every course resource.",
    ),
}


def public_guidance(code):
    entry = GUIDANCE.get(code)
    if entry is None:
        return None
    origin, action, condition, summary = entry
    return summary, {
        "error_origin": origin,
        "recommended_action": action,
        "retry_condition": condition,
    }


COVERAGE_WARNINGS = {
    "missing_page_evidence": "The assignment source did not confirm a complete page read. Its workload is unknown.",
    "INVENTORY_BRANCH_TIMEOUT": "This source reached its time limit. Retry the affected source separately; the observed pages may omit work.",
    "refresh_budget_exhausted": "The refresh time budget ended before this course completed. Retry this course separately; missing items do not establish that no work is due.",
    "UPSTREAM_REQUEST_TIMEOUT": "The provider request timed out. Coverage is incomplete; retry the affected course separately.",
    "TASK_BUDGET_EXCEEDED": "The request budget ended before discovery completed. Retry the affected course separately.",
    "UPSTREAM_UNAVAILABLE": "Canvas could not complete the collection request. Retry the affected course separately.",
    "invalid_source_item": "A source item could not be processed. Missing work may remain in this course.",
    "request_budget": "The request budget ended before source discovery completed. Retry the affected course separately; coverage remains incomplete.",
    "permission_denied": "Source access was denied. Check this resource's availability in Canvas; account sign-in alone does not establish access.",
    "reconnect_required": "Source authentication requires reconnection. Review connection status before retrying; course access remains unverified.",
    "retry_later": "This source is temporarily unavailable. Wait before retrying the affected course; missing items remain unknown.",
}


def public_coverage_warning(warning):
    if not warning:
        return None
    if isinstance(warning, str) and warning in GUIDANCE:
        return GUIDANCE[warning][3]
    if any(warning == entry[3] for entry in GUIDANCE.values()):
        return warning
    if warning in COVERAGE_WARNINGS.values():
        return warning  # Repeated final-boundary minimization is idempotent.
    return COVERAGE_WARNINGS.get(warning, "Coverage limitation reported.")


# A local route ceiling and an observed Canvas file flag require different remedies.
RETRIEVAL_GUIDANCE = {
    "configured_endpoint_scope": (
        "MISSING_RESOURCE_CAPABILITY",
        "review_configured_read_endpoint",
        "This read endpoint is outside Bridge's configured scope ceiling. Ask the operator to check the approved endpoint configuration.",
    ),
    "file_unpublished": (
        "RESOURCE_PERMISSION_DENIED",
        "check_file_publication",
        "Canvas marks this file unpublished. Ask the course owner to check its publication state.",
    ),
    "file_hidden": (
        "RESOURCE_PERMISSION_DENIED",
        "check_file_visibility",
        "Canvas marks this file hidden. Ask the course owner to check student visibility.",
    ),
    "file_locked": (
        "RESOURCE_PERMISSION_DENIED",
        "check_file_availability",
        "Canvas marks this file locked. Check its availability dates with the course owner.",
    ),
    "file_visibility_unknown": (
        "UNKNOWN_AUTHORIZATION_FAILURE",
        "verify_current_resource_access",
        "Canvas did not establish student visibility for this file. Check whether it opens in the student account.",
    ),
}


def retrieval_guidance(code, constraint):
    rule = RETRIEVAL_GUIDANCE.get(constraint) if isinstance(constraint, str) else None
    return rule[1:] if rule and rule[0] == code else None
