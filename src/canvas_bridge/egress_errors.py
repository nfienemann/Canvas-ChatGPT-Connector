"""Reconstruct error envelopes from a fixed vocabulary; never echo arbitrary details."""

from canvas_bridge.authorization import MESSAGES
from canvas_bridge.document_policy import PDF_BATCH_PAGES
from canvas_bridge.document_ranges import range_message, safe_range_fields
from canvas_bridge.domain import Result
from canvas_bridge.egress_error_codes import SAFE_CODES
from canvas_bridge.error_guidance import public_guidance
from canvas_bridge.failure_diagnostics import RULES, current, describe, public_fields
from canvas_bridge.input_diagnostics import CAPABILITIES, diagnostic_fields
from canvas_bridge.integrity.guidance import safe_guidance
from canvas_bridge.integrity.reasons import SAFE_CODES as INTEGRITY_CODES
from canvas_bridge.processes.reasons import READINESS_MESSAGES
from canvas_bridge.processes.reasons import SAFE_CODES as PROCESS_CODES
from canvas_bridge.usage.ledger import REMEDIES as USAGE_MESSAGES

SAFE_CODES = (
    SAFE_CODES
    | RULES.keys()
    | INTEGRITY_CODES
    | frozenset(READINESS_MESSAGES)
    | PROCESS_CODES
    | frozenset(USAGE_MESSAGES)
    | frozenset(
        {
            "CONTENT_WITHHELD_PRIVACY_UNCERTAINTY",
            "PRIVACY_OUTPUT_UNVERIFIED",
            "APPROVAL_REVOKED",
            "APPROVAL_DENIED",
            "APPROVAL_EXPIRED",
            "APPROVAL_NOT_ASSESSED",
            "APPROVAL_PENDING",
            "INDEPENDENT_HASH_REQUIRED",
            "INDEPENDENT_SOURCE_CHANGED",
            "INDEPENDENT_SCHEMA_UNSUPPORTED",
            "INDEPENDENT_GRADES_MISSING",
            "INDEPENDENT_WORK_MISSING",
            "INDEPENDENT_CALENDAR_MISSING",
            "INTEGRITY_SCOPE_MISSING",
            "INTEGRITY_SCOPE_INVALID",
            "EGRESS_INSTITUTIONAL_APPROVAL_DENIED",
            "EGRESS_BEARER_RECIPIENT_UNVERIFIED",
            "EGRESS_CONTENT_HASH_REVIEW_REQUIRED",
            "VISUAL_FORMAT_UNSUPPORTED",
            "RENDER_FILE_SIZE_OR_SIGNATURE",
            "RENDER_INVALID_PAGE_OR_ROTATION",
            "RENDER_PAGE_LIMIT_OR_RANGE",
            "RENDER_PAGE_DIMENSIONS",
            "RENDER_IMAGE_OUTPUT_LIMIT",
            "RENDER_MEMORY_LIMIT",
            "RENDER_DEPENDENCY_UNAVAILABLE",
            "RENDER_UNREADABLE_OR_RENDERING_LIMIT",
            "RENDER_ACTIVE_OR_EXTERNAL_CONTENT",
            "RENDER_CONVERSION_FAILED",
            "RENDER_CONVERSION_PAGE_MISMATCH",
            "RENDER_RENDER_TIMEOUT",
            "RENDER_PPTX_EXPANSION_LIMIT",
            "RENDER_IMAGE_RESOURCE_LIMIT",
            "RENDER_UNSUPPORTED_SLIDE_MEDIA",
            "RENDER_FAILED",
            "EXTRACTION_INVALID_DOCX_STRUCTURE",
            "EXTRACTION_TOO_MANY_PAGES",
            "EXTRACTION_CORRUPT_OR_UNREADABLE",
            "EXTRACTION_OUTPUT_LIMIT",
            "EXTRACTION_OFFICE_RESOURCE_LIMIT",
            "EXTRACTION_INVALID_SLIDE_REFERENCE",
            "EXTRACTION_INVALID_WORKBOOK_STRUCTURE",
            "EXTRACTION_INVALID_WORKBOOK_REFERENCE",
            "EXTRACTION_WORKBOOK_RESOURCE_LIMIT",
            "EXTRACTION_MEMORY_LIMIT",
            "EXTRACTION_DEPENDENCY_UNAVAILABLE",
            "EXTRACTION_INVALID_PPTX_ARCHIVE",
            "EXTRACTION_FAILED",
            "INVENTORY_ASSIGNMENT_LIMIT",
            "INVENTORY_ASSIGNMENT_LINK_LIMIT",
            "INVENTORY_ASSIGNMENT_FILE_UNRESOLVED",
            "INVENTORY_FOLDER_CONTEXT_MISMATCH",
            "INVENTORY_FOLDER_CONFLICT",
            "INVENTORY_FOLDER_CYCLE",
            "INVENTORY_FOLDER_PARENT_MISSING",
            "INVENTORY_FOLDER_IDENTITY_INVALID",
            "PAGINATION_LINK_INVALID",
            "PAGINATION_SCOPE_CHANGED",
            "SHARED_READ_INTERRUPTED",
            "INVENTORY_PAGE_INVALID",
            "INVENTORY_PAGINATION_CYCLE",
            "INVENTORY_STATE_LIMIT",
            "INVENTORY_SCOPE_CHANGED",
            "INVENTORY_CURSOR_INVALID",
        }
    )
)


def safe_error_result(result):
    code = result.data.get("reason_code")
    code = code if isinstance(code, str) and code in SAFE_CODES else "EGRESS_ERROR_REDACTED"
    data = {"reason_code": code}
    if code == "DOCUMENT_RANGE_OUT_OF_BOUNDS" and result.status == "needs_input":
        data.update(safe_range_fields(result.data))
    capability = result.data.get("requested_capability")
    capability = capability if isinstance(capability, str) and capability in CAPABILITIES else None
    if capability:
        data["requested_capability"] = capability
    data.update(diagnostic_fields(code, capability))
    for key in (
        "upstream_http_status",
        "worker_exit_code",
        "limit_bytes",
        "observed_size",
        "retry_after_seconds",
    ):
        value = result.data.get(key)
        lower, upper = {"upstream_http_status": (100, 599), "retry_after_seconds": (0, 86400)}.get(
            key, (-1, 100_000_000)
        )
        if type(value) is int and lower <= value <= upper:
            data[key] = value
    if (
        code == "LOCAL_REQUEST_BUSY"
        and result.data.get("reservation_state") == "expiration_pending"
    ):
        data["reservation_state"] = "expiration_pending"
    if result.data.get("origin") == "file_delivery_provider":
        data["origin"] = "file_delivery_provider"
    from typing import get_args

    from canvas_bridge.domain import InventoryMethod
    from canvas_bridge.error_guidance import retrieval_guidance

    constraint = result.data.get("retrieval_constraint")
    if retrieval_guidance(code, constraint):
        data["retrieval_constraint"] = constraint
    method = result.data.get("retrieval_method")
    if method in get_args(InventoryMethod):
        data["retrieval_method"] = method
    if (
        result.data.get("capability_observation") == "recent_denial"
        and data.get("upstream_http_status") == 403
    ):
        data["capability_observation"] = "recent_denial"
    resource = result.data.get("resource_kind")
    position = result.data.get("course_position")
    if (
        code == "RESOURCE_PERMISSION_DENIED"
        and result.status == "permission_denied"
        and data.get("upstream_http_status") == 403
        and type(position) is int
        and 1 <= position <= 100
        and result.data.get("course_order") in ("request_order", "sorted_selected_ids")
    ):
        data.update(course_position=position, course_order=result.data["course_order"])
    if isinstance(resource, str) and resource in {
        "file",
        "folder",
        "module",
        "assignment",
        "page",
        "course",
        "collection",
    }:
        data["resource_kind"] = resource
    if code == "UPSTREAM_BUDGET_EXHAUSTED" and result.data.get("blocking_scope") == "usage_window":
        data["blocking_scope"] = "usage_window"
    if code == "UPSTREAM_THROTTLED" and result.data.get("blocking_scope") == "cooldown":
        data["blocking_scope"] = "cooldown"
    if code == "SLIDE_RENDER_RESOURCE_LIMIT":
        reason = result.data.get("render_failure_reason")
        if isinstance(reason, str) and reason in {
            "memory_limit",
            "image_output_limit",
            "render_timeout",
            "pptx_expansion_limit",
        }:
            data["render_failure_reason"] = reason
    if code in {"DOCUMENT_WORKER_TIMEOUT", "DOCUMENT_WORKER_CPU_LIMIT"}:
        if result.data.get("operation_state") == "stopped":
            data["operation_state"] = "stopped"
        stage = result.data.get("timeout_stage")
        if isinstance(stage, str) and stage in {
            "text_extraction",
            "ocr",
            "runtime_setup",
            "pptx_conversion",
            "page_rendering",
        }:
            data["timeout_stage"] = stage
            first, last = result.data.get("page_start"), result.data.get("page_end")
            if (
                stage in {"text_extraction", "ocr", "runtime_setup"}
                and type(first) is int
                and type(last) is int
                and 1 <= first <= last <= min(200, first + PDF_BATCH_PAGES - 1)
            ):
                data.update(page_start=first, page_end=last)
                if result.data.get("completed_pages") == []:
                    data["completed_pages"] = []
                if first == last:
                    data["visual_fallback_tool"] = "render_course_file_page"
                    if last < 200:
                        data["resume_page"] = last + 1
                else:
                    data["retry_single_page"] = first
    deadline = result.data.get("deadline_seconds")
    if type(deadline) in (float, int) and 0 < deadline <= 86400:
        data["deadline_seconds"] = deadline
    elapsed = result.data.get("elapsed_ms")
    if type(elapsed) is int and 0 <= elapsed <= 86_400_000:
        data["elapsed_ms"] = elapsed
    stage = result.data.get("processing_stage")
    if isinstance(stage, str) and stage in {
        "runtime_setup",
        "job_setup",
        "sandbox_setup",
        "worker_start",
        "worker_execution",
        "worker_queue",
        "result_read",
        "result_validation",
        "file_download",
        "authorization",
        "source_fetch",
        "text_extraction",
        "pdf_page_render",
        "pptx_conversion",
        "image_delivery",
        "page_rendering",
        "slide_rendering",
        "ocr",
        "zip_expansion",
    }:
        data["processing_stage"] = stage
    if result.data.get("resolution_fallback") == "failed":
        data["resolution_fallback"] = "failed"
    attempt = current.get()
    image_prepared = bool(attempt and attempt.image_prepared)
    if image_prepared or "visual_pipeline" in result.data:
        from canvas_bridge.visual_delivery import lifecycle

        data["visual_pipeline"] = lifecycle(
            rendered=image_prepared, events=attempt.visual_events.values() if attempt else ()
        )
        if image_prepared and attempt.policy in {"deny", "requires_review"}:
            data["visual_pipeline"]["image_release_checked"] = {
                "status": "failed",
                "evidence": "image_release_withheld",
            }
        data["visual_error_category"] = code
    if code in USAGE_MESSAGES:
        summary = USAGE_MESSAGES[code]
        data.update(
            cached_information="requires_current_authorization",
            local_processing_available=True,
            retry_condition="operator_review"
            if code
            in {"PROVIDER_NOT_AUTHORIZED", "BILLING_CONTRACT_UNCONFIGURED", "GOVERNOR_UNAVAILABLE"}
            else "narrow_or_resume_task"
            if code == "TASK_BUDGET_EXCEEDED"
            else "capacity_or_upstream_recovery",
        )
    elif code in {"CONTENT_WITHHELD_PRIVACY_UNCERTAINTY", "PRIVACY_OUTPUT_UNVERIFIED"}:
        summary = "Content was withheld because privacy inspection or a required content review could not be established."
        data["transmitted"] = False
    elif code == "LOCAL_STORAGE_UNAVAILABLE":
        summary = "Independent local storage is unavailable. Retry local access; reconnecting an LMS will not repair this failure."
    elif code == "PIN_CONFLICTS_WITH_SOURCE_TIMING":
        summary = RULES[code].summary
    elif code in {"INDEPENDENT_HASH_REQUIRED", "INDEPENDENT_SOURCE_CHANGED"}:
        summary = "A current source hash is required. Review the authorized source version before retrying."
    elif code in {
        "INDEPENDENT_GRADES_MISSING",
        "INDEPENDENT_WORK_MISSING",
        "INDEPENDENT_CALENDAR_MISSING",
    }:
        summary = "Required independent workflow fields are missing. Review the required fields and next action; no calculation or Calendar action succeeded."
    elif code in {"INTEGRITY_SCOPE_MISSING", "INTEGRITY_SCOPE_INVALID"}:
        summary = "Choose a valid academic-integrity scope. A local course label or authorized independent documents do not require an LMS connection."
    elif code == "INDEPENDENT_SCHEMA_UNSUPPORTED":
        summary = "These records do not use the supported independent academic schema or source format. No calculation succeeded."
    elif code.startswith("INDEPENDENT_INPUT_"):
        summary = "Supply a permitted independent source with valid academic records and its current content hash. No LMS connection is required."
    elif code.startswith("INDEPENDENT_SOURCE_"):
        summary = "This source is unavailable for independent use. Check ownership, provenance, current version and sharing permission. Restricted institutional sources retain their existing requirements."
    elif code.startswith("DOCUMENT_RANGE_") or code == "DOCUMENT_LENGTH_UNAVAILABLE":
        summary = RULES[code].summary
        if "page_count" in data:
            summary = range_message(data["page_start"], data["page_end"], data["page_count"])
    elif code == "VISUAL_FORMAT_UNSUPPORTED":
        summary = "Page-image rendering supports PDF and configured experimental PPTX."
    elif code == "EGRESS_ERROR_REDACTED":
        summary = "This request failed without a safe, specific diagnosis. Give the operator the request ID. No source content is included in this error."
    elif code.startswith("EGRESS_"):
        summary = "Content was not transmitted because classification or permission could not be established. Authorized local analysis remains available."
        data["transmitted"] = False
        original = result.data.get("egress", {})
        if isinstance(original, dict) and original.get("decision") in (
            "DENY",
            "REQUIRES_AUTHORIZED_REVIEW",
        ):
            data["content_decision"] = original["decision"]
        elif result.data.get("content_decision") in ("DENY", "REQUIRES_AUTHORIZED_REVIEW"):
            # The SDK applies this reconstruction again at the final boundary.
            data["content_decision"] = result.data["content_decision"]
        if code == "EGRESS_CLASSIFICATION_UNKNOWN":
            data["processing_stage"] = "source_classification"
    elif code in READINESS_MESSAGES:
        summary = READINESS_MESSAGES[code]
    elif code.startswith("PROCESS_"):
        summary = "This process needs current source access, evidence or an exact confirmed preview. Refresh the relevant source or process record and review the reason code."
        data["transmitted"] = False
    elif code.startswith("INTEGRITY_"):
        summary = "Academic permission for this activity is not established. Review applicable policy evidence or seek instructor clarification. Administrative help remains available when independently authorized."
        data["transmitted"] = False
        data.update(safe_guidance())
    elif code == "CONNECTION_INACTIVE":
        summary = "This connection is disabled. Review connection status and settings; reconnection alone does not establish provider, institutional or sharing approval, or enable live integration."
        data["setup_checks"] = [
            "authentication",
            "provider_approval",
            "institution_approval",
            "data_sharing_approval",
            "deployment_configuration",
        ]
    elif code.startswith("APPROVAL_"):
        summary = (
            "Live Canvas access or sharing is disabled pending verified administrator approvals."
        )
    else:
        summary = MESSAGES.get(
            code,
            "This request could not be completed safely. No source content is included in this error.",
        )
    guidance = public_guidance(code)
    if guidance is not None:
        summary, fields = guidance
        data.update(fields)
    clean = Result(status=result.status, summary=summary, data=data)
    clean.meta.request_id = result.meta.request_id
    attempt = current.get()
    if (
        attempt
        and attempt.diagnostic
        and result.meta.request_id == attempt.request_id
        and result.data.get("diagnostic") == public_fields(attempt.diagnostic)
    ):
        # Reconstruct from the live server observation, never from caller metadata.
        describe(clean, attempt.diagnostic.sanitized_error_release)
    return clean
