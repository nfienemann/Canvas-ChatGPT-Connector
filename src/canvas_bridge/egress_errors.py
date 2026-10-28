"""Reconstruct error envelopes from a fixed vocabulary; never echo arbitrary details."""

from canvas_bridge.authorization import MESSAGES
from canvas_bridge.domain import Result
from canvas_bridge.egress_error_codes import SAFE_CODES
from canvas_bridge.input_diagnostics import CAPABILITIES, diagnostic_fields
from canvas_bridge.integrity.guidance import safe_guidance
from canvas_bridge.integrity.reasons import SAFE_CODES as INTEGRITY_CODES
from canvas_bridge.processes.reasons import SAFE_CODES as PROCESS_CODES

SAFE_CODES = (
    SAFE_CODES
    | INTEGRITY_CODES
    | PROCESS_CODES
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
        }
    )
)


def safe_error_result(result):
    code = result.data.get("reason_code")
    code = code if isinstance(code, str) and code in SAFE_CODES else "EGRESS_ERROR_REDACTED"
    data = {"reason_code": code}
    capability = result.data.get("requested_capability")
    capability = capability if isinstance(capability, str) and capability in CAPABILITIES else None
    if capability:
        data["requested_capability"] = capability
    data.update(diagnostic_fields(code, capability))
    for key in ("upstream_http_status", "worker_exit_code", "limit_bytes", "observed_size"):
        value = result.data.get(key)
        if type(value) is int and -1 <= value <= 100_000_000:
            data[key] = value
    stage = result.data.get("processing_stage")
    if isinstance(stage, str) and stage in {
        "file_download",
        "authorization",
        "source_fetch",
        "text_extraction",
        "pdf_page_render",
        "pptx_conversion",
        "image_delivery",
        "zip_expansion",
    }:
        data["processing_stage"] = stage
    if "visual_pipeline" in result.data:
        from canvas_bridge.visual_delivery import lifecycle

        data["visual_pipeline"] = lifecycle()
        data["visual_error_category"] = code
    if code in {"CONTENT_WITHHELD_PRIVACY_UNCERTAINTY", "PRIVACY_OUTPUT_UNVERIFIED"}:
        summary = "Content was withheld because privacy inspection or a required content review could not be established."
        data["transmitted"] = False
    elif code == "LOCAL_STORAGE_UNAVAILABLE":
        summary = "Independent local storage is unavailable. Retry local access; reconnecting an LMS will not repair this failure."
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
    elif code == "VISUAL_FORMAT_UNSUPPORTED":
        summary = "Page-image rendering supports PDF and configured experimental PPTX."
    elif code == "EGRESS_ERROR_REDACTED":
        summary = "This request could not be completed safely. No source content is included in this error."
    elif code.startswith("EGRESS_"):
        summary = "Content was not transmitted because classification or permission could not be established. Authorized local analysis remains available."
        data["transmitted"] = False
        original = result.data.get("egress", {})
        if isinstance(original, dict) and original.get("decision") in (
            "DENY",
            "REQUIRES_AUTHORIZED_REVIEW",
        ):
            data["content_decision"] = original["decision"]
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
    clean = Result(status=result.status, summary=summary, data=data)
    clean.meta.request_id = result.meta.request_id
    return clean
