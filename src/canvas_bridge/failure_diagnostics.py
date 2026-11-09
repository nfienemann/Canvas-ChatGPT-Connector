"""Request-local observations. Public metadata is never evidence of inspection."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import NamedTuple

from canvas_bridge.auth_diagnostics import AuthDiagnostic, tool_observation
from canvas_bridge.document_policy import PDF_BATCH_PAGES
from canvas_bridge.document_ranges import range_message, safe_range_fields
from canvas_bridge.domain import DomainError, FailureDiagnostic, Result, opaque_id
from canvas_bridge.error_guidance import GUIDANCE, retrieval_guidance


class StreamInterrupted(RuntimeError):
    def __init__(self, request_id):
        self.bridge_request_id = request_id
        super().__init__("Bridge stream interrupted")


class Rule(NamedTuple):
    category: str
    stage: str
    status: str
    summary: str
    retry: str = "after_operator_fix"
    action: str = "report_request_id"


def internal(stage, message):
    return Rule("internal", stage, "operation_failed", message)


def verification(message):
    return Rule("privacy", "final_response_verification", "operation_failed", message)


RULES = {
    "PIN_CONFLICTS_WITH_SOURCE_TIMING": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "The supplied pin conflicts with the source timing. Review its original time and "
        "choose a slot within the revised deadline before replanning.",
        "after_review",
        "correct_input",
    ),
    "DIAGNOSTIC_SERIALIZATION_FAILED": verification("Bridge could not verify the error response."),
    "RESOURCE_NOT_REGISTERED": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "Choose a registered resource from the resource catalog.",
        "after_refresh",
        "refresh_resource_catalog",
    ),
    "TRANSPORT_BUSY": Rule(
        "transport",
        "http_transport",
        "retry_later",
        "Request capacity is temporarily unavailable. Wait before retrying.",
        "after_delay",
        "wait_for_capacity",
    ),
    "LOCAL_STORAGE_UNAVAILABLE": Rule(
        "internal",
        "tool_execution",
        "retry_later",
        "Retry when local storage is available.",
        "after_delay",
        "wait_for_recovery",
    ),
    "MCP_ACCESS_DENIED": Rule(
        "authorization",
        "authorization",
        "permission_denied",
        "The current session lacks the required access. Check the session and tool permission.",
        "after_review",
        "check_access",
    ),
    "TOOL_NOT_REGISTERED": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "The requested tool is unavailable. Refresh the tool catalog.",
        "after_refresh",
        "refresh_tool_catalog",
    ),
    "DOCUMENT_RANGE_OUT_OF_BOUNDS": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "Choose a range from 1 through the returned page_count.",
        "after_review",
        "correct_input",
    ),
    "DOCUMENT_RANGE_INVALID": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "Choose an ordered inclusive range from 1 through 200.",
        "after_review",
        "correct_input",
    ),
    "DOCUMENT_LENGTH_UNAVAILABLE": Rule(
        "validation",
        "text_extraction",
        "unsupported_feature",
        "A usable document length could not be established.",
        "after_refresh",
        "restart_document_read",
    ),
    "TOOL_INPUT_INVALID": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "Correct the input using the registered tool schema.",
        "after_review",
        "correct_input",
    ),
    "LOCAL_SEARCH_INPUT_REQUIRED": Rule(
        "validation",
        "input_validation",
        "needs_input",
        "Supply document_id or document_ids for one to twenty imported documents and a nonblank query.",
        "after_review",
        "select_documents_and_query",
    ),
    "LOCAL_CONCEPTUAL_SEARCH_DISABLED": Rule(
        "validation",
        "input_validation",
        "unsupported_feature",
        "Conceptual search is disabled. Use literal mode to search imported documents.",
        "after_review",
        "use_literal_search",
    ),
    "TOOL_EXECUTION_FAILED": internal("tool_execution", "Bridge encountered an internal error."),
    "TOOL_RESULT_FAILED": internal(
        "sdk_result", "The tool reported a failure without a verified explanation."
    ),
    "TOOL_RESPONSE_INVALID": internal("sdk_result", "The tool returned an invalid response."),
    "RESPONSE_INSPECTION_RECEIPT_MISSING": verification(
        "Bridge could not verify its prepared response and withheld the content."
    ),
    "RESPONSE_INSPECTION_RECEIPT_MISMATCH": verification(
        "The prepared response differed from the inspected response. Bridge withheld the content."
    ),
    "PRIVACY_OUTPUT_UNVERIFIED": verification(
        "Final privacy inspection rejected the prepared response. Bridge withheld the content."
    )._replace(status="permission_denied"),
    "PROTOCOL_INPUT_INVALID": Rule(
        "validation",
        "http_transport",
        "needs_input",
        "Correct the malformed protocol request.",
        "after_review",
        "correct_input",
    ),
    "TRANSPORT_FAILED": Rule(
        "transport",
        "http_transport",
        "operation_failed",
        "The transport could not complete the request.",
    ),
    "BUFFERED_OUTPUT_TOO_LARGE": Rule(
        "transport",
        "http_transport",
        "operation_failed",
        "The prepared response exceeded the transport limit. Request a smaller scope.",
        "after_review",
        "reduce_scope",
    ),
    "TRANSPORT_ACCESS_DENIED": Rule(
        "authorization",
        "http_transport",
        "permission_denied",
        "HTTP access was denied. Check the credentials and scope for this request.",
        "after_review",
        "check_access",
    ),
    "UNCLASSIFIED_FAILURE": Rule(
        "unknown",
        "tool_execution",
        "operation_failed",
        "Bridge could not establish a specific cause.",
        "unknown",
    ),
}

# Apply these rules only to reviewed codes. Some legacy codes also occur for
# local resources, so an observed HTTP status is required for provider attribution.
RULES.update(
    {
        "DOCUMENT_DOWNLOAD_TIMEOUT": Rule(
            "upstream",
            "document_download",
            "operation_failed",
            "The document download exceeded its time limit.",
        ),
        "PPTX_CONVERSION_TIMEOUT": internal(
            "pptx_conversion",
            "Presentation conversion timed out. Selecting fewer slides can still require conversion of the entire deck.",
        ),
        "UPSTREAM_RESPONSE_INVALID": Rule(
            "upstream",
            "upstream_request",
            "operation_failed",
            "Canvas returned an unreadable response. Access and content could not be established.",
        ),
        "TRANSPORT_INTERRUPTED": Rule(
            "transport",
            "http_transport",
            "operation_uncertain",
            "The transport request was cancelled. The processing outcome is unknown.",
        ),
        "TRANSPORT_TIMEOUT": Rule(
            "transport",
            "http_transport",
            "operation_failed",
            "Transport delivery timed out.",
        ),
        "CHECKPOINT_COMMIT_UNCERTAIN": Rule(
            "internal",
            "inventory_resume",
            "operation_uncertain",
            "Bridge could not confirm the checkpoint save. Reload the last acknowledged continuation.",
            "after_review",
            "reload_checkpoint",
        ),
        "RESOURCE_AUTHORIZATION_REVOKED": Rule(
            "authorization",
            "authorization",
            "permission_denied",
            "The source is unavailable for this request. Check the current selection and access.",
            "after_review",
            "check_access",
        ),
        "INDEPENDENT_SOURCE_UNAVAILABLE": Rule(
            "authorization",
            "authorization",
            "permission_denied",
            "This selection is unavailable for independent use. Choose a source currently authorized for that use.",
            "after_review",
            "check_access",
        ),
        "CHECKPOINT_STORAGE_UNAVAILABLE": internal(
            "inventory_resume", "Bridge could not read the saved inventory checkpoint."
        ),
        "SLIDE_RENDER_RESOURCE_LIMIT": internal(
            "page_rendering", "Slide rendering exceeded its processing limit."
        ),
        "EXTRACTION_ENCRYPTED_PDF": Rule(
            "validation",
            "text_extraction",
            "unsupported_feature",
            "The reader cannot extract encrypted PDFs. Choose a readable source you are authorized to use.",
            "after_review",
            "choose_supported_source",
        ),
        "EXTRACTION_CORRUPT_OR_UNREADABLE": Rule(
            "validation",
            "text_extraction",
            "unsupported_feature",
            "The document structure could not be read. Check the current source file.",
            "after_review",
            "check_source_file",
        ),
        "OCR_INSTALLATION_UNAVAILABLE": internal(
            "runtime_setup",
            "The OCR runtime is unavailable. Ask the operator to check its installation.",
        ),
        "OCR_EXTRACTION_FAILED": internal("ocr", "OCR failed for the requested content."),
        "PPTX_RENDERER_UNAVAILABLE": internal(
            "pptx_conversion",
            "The configured presentation renderer is unavailable. Ask the operator to check its installation.",
        ),
        "RENDER_IMAGE_INVALID": internal(
            "page_rendering", "Image validation failed. Bridge withheld the image."
        ),
        "RENDER_RENDER_TIMEOUT": internal(
            "page_rendering", "The page render exceeded its time limit."
        ),
        "DOCUMENT_SANDBOX_SETUP_TIMEOUT": internal(
            "runtime_setup", "Sandbox setup timed out before the document worker started."
        ),
        "DOCUMENT_SEARCH_CURSOR_INVALID": Rule(
            "validation",
            "inventory_resume",
            "needs_input",
            "The search continuation is unavailable. Restart the document search without a cursor.",
            "after_review",
            "restart_document_search",
        ),
        "DOCUMENT_SEARCH_SCOPE_CHANGED": Rule(
            "validation",
            "inventory_resume",
            "source_changed",
            "The search scope or inventory changed. Restart the document search without a cursor.",
            "after_refresh",
            "restart_document_search",
        ),
        "CONTINUATION_HASH_REQUIRED": Rule(
            "validation",
            "input_validation",
            "source_changed",
            "Use the content hash from the previous read, or start a new read at offset zero.",
            "after_review",
            "supply_current_hash",
        ),
        "INVENTORY_BRANCH_TIMEOUT": Rule(
            "upstream",
            "upstream_request",
            "retry_later",
            "The collection request timed out. Resume the returned continuation when one is available.",
            "after_delay",
            "resume_affected_collection",
        ),
        "INVENTORY_NOT_ATTEMPTED": Rule(
            "unknown",
            "upstream_request",
            "partial_data",
            "This collection was not checked. Request the affected course separately.",
            "after_review",
            "request_affected_course",
        ),
        "INVENTORY_REQUEST_BUDGET": Rule(
            "internal",
            "upstream_request",
            "partial_data",
            "Discovery reached the request budget. Request the affected course separately or resume an available cursor.",
            "after_review",
            "request_affected_course",
        ),
        "INVENTORY_SCOPE_CHANGED": Rule(
            "authorization",
            "inventory_resume",
            "source_changed",
            "The selected scope changed. Restart inventory for the current scope.",
            "after_refresh",
            "restart_inventory_with_current_scope",
        ),
        "DOCUMENT_PARSER_VERSION_CHANGED": Rule(
            "validation",
            "text_extraction",
            "source_changed",
            "The parser changed. Start a new read for the current parser version.",
            "after_refresh",
            "restart_document_read",
        ),
        "SOURCE_CHANGED": Rule(
            "validation",
            "tool_execution",
            "source_changed",
            "The source changed. Start a new read for the current version.",
            "after_refresh",
            "restart_document_read",
        ),
    }
)

# Decisions emitted by the egress evaluator that have no older guidance entry.
# Each entry names a specific condition and one permitted recovery action.
POLICY_MESSAGES = {
    "EGRESS_USER_NOT_AUTHORIZED": (
        "Source access could not be established. Check access for the current account.",
        "review_access",
    ),
    "EGRESS_RESTRICTED_CONTENT": (
        "The requested material is restricted. Choose material approved for sharing.",
        "choose_approved_material",
    ),
    "EGRESS_UNSUPPORTED_TRANSFER": (
        "This transfer channel is unsupported. Choose an approved channel.",
        "choose_approved_channel",
    ),
    "EGRESS_REVIEW_REQUIRED": (
        "This transfer requires an authorized sharing review. Request that review.",
        "review_policy",
    ),
    "EGRESS_INSTITUTIONAL_APPROVAL_DENIED": (
        "Institutional approval for sharing was denied. Consult the authorized institutional reviewer.",
        "review_policy",
    ),
    "EGRESS_RECIPIENT_UNVERIFIED": (
        "Bridge could not verify the recipient. Ask the operator to verify the intended recipient.",
        "review_recipient",
    ),
    "EGRESS_BEARER_RECIPIENT_UNVERIFIED": (
        "Bridge could not verify the download recipient. Use an authorized authenticated channel.",
        "choose_approved_channel",
    ),
    "EGRESS_RECIPIENT_SCOPE_DENIED": (
        "The recipient lacks permission for this scope. Review the authorized recipient scope.",
        "review_recipient",
    ),
    "EGRESS_PROCESSING_RESTRICTION": (
        "The source restricts this processing. Choose an approved use of the source.",
        "review_policy",
    ),
    "EGRESS_AMOUNT_EXCEEDED": (
        "The requested amount exceeds the sharing allowance. Reduce the requested scope.",
        "reduce_scope",
    ),
    "EGRESS_SOURCE_REVIEW_REQUIRED": (
        "This source needs a sharing review. Request an authorized source review.",
        "review_policy",
    ),
    "EGRESS_CONTENT_OWNER_PERMISSION_REQUIRED": (
        "Sharing requires the content owner's permission. Request an authorized permission review.",
        "review_policy",
    ),
    "EGRESS_EXTERNAL_PROCESSOR_DISABLED": (
        "External processing is disabled. Use a permitted local operation.",
        "use_local_processing",
    ),
    "INTEGRITY_EXPLICIT_PROHIBITION": (
        "The applicable academic policy prohibits this assistance. Choose an activity permitted by that policy.",
        "review_policy",
    ),
}
for _code, (_summary, _action) in POLICY_MESSAGES.items():
    RULES[_code] = Rule(
        "policy", "content_policy", "permission_denied", _summary, "after_review", _action
    )
for _code in (
    "EGRESS_PRIVACY_CHECK_REQUIRED",
    "EGRESS_HIDDEN_FILE_REFERENCE",
    "CONTENT_WITHHELD_PRIVACY_UNCERTAINTY",
):
    RULES[_code] = Rule(
        "privacy",
        "content_policy",
        "permission_denied",
        "Bridge withheld the response because a privacy requirement was unmet.",
    )


# Reuse the existing reviewed messages and actions.
ORIGINS = {
    "source_access": ("authorization", "authorization", "after_review"),
    "bridge_authorization": ("authorization", "authorization", "after_delay"),
    "bridge_admission": ("internal", "tool_execution", "after_delay"),
    "content_governance": ("policy", "content_policy", "after_review"),
    "provider_access": ("upstream", "upstream_request", "after_delay"),
    "upstream_inventory": ("upstream", "upstream_request", "after_operator_fix"),
    "bridge_inventory": ("validation", "input_validation", "after_refresh"),
    "document_runtime": ("internal", "tool_execution", "after_operator_fix"),
    "document_parser": ("validation", "input_validation", "after_review"),
}


@dataclass
class Attempt:
    request_id: str = field(default_factory=opaque_id)
    attempt_id: str = field(default_factory=opaque_id)
    canvas_responses: set = field(default_factory=set)
    tool_authorized: bool = False
    authenticated: bool = False
    auth_observation: AuthDiagnostic | None = None
    operation: str | None = None
    policy: str = "not_evaluated"
    exception: str | None = None
    diagnostic: FailureDiagnostic | None = None
    input_field: str | None = None
    constraint: str | None = None
    delivery: str = "none"
    retrieval_methods: list[str] = field(default_factory=list)
    last_retrieval_method: str | None = None
    source_bytes_obtained: bool = False
    visual_events: dict = field(default_factory=dict)
    image_prepared: bool = False
    inspected_error: Result | None = None
    wire_digest: bytes | None = None
    emergency: str | None = None
    protocol_cause: str | None = None
    transport_deadline: float | None = None
    transport_elapsed_ms: int | None = None
    domain_status: str | None = None
    observed_stage: str = "tool_execution"

    def begin_refresh_attempt(self):
        self.attempt_id = opaque_id()
        self.canvas_responses.clear()
        self.tool_authorized = False
        self.authenticated = False
        self.auth_observation = None
        self.policy = "not_evaluated"
        self.exception = None
        self.diagnostic = None
        self.inspected_error = None
        self.domain_status = None

    def observe_policy(self, decision):
        self.policy = (
            "allow"
            if decision.allowed
            else (
                "requires_review" if decision.decision == "REQUIRES_AUTHORIZED_REVIEW" else "deny"
            )
        )

    def capture(self, exc):
        # Even an exception's class name can be controlled by a provider.
        self.exception = {
            DomainError: "domain",
            RuntimeError: "runtime",
            ValueError: "value",
            TimeoutError: "timeout",
            TypeError: "type",
            OSError: "io",
        }.get(type(exc), "other")


current: ContextVar[Attempt | None] = ContextVar("egress_diagnostic_attempt", default=None)


def rule_for(code, result, attempt):
    from canvas_bridge.authorization import MESSAGES
    from canvas_bridge.integrity.reasons import SAFE_CODES as INTEGRITY_CODES

    if code == "UNCLASSIFIED_FAILURE" and attempt.domain_status:
        # A typed domain outcome can be known even when its reason is unreviewed.
        status = result.status
        category = {
            "authorization": "authorization",
            "content_policy": "policy",
            "final_response_verification": "privacy",
        }.get(attempt.observed_stage, "unknown")
        stage = attempt.observed_stage
        if attempt.policy in {"deny", "requires_review"}:
            category, stage = "policy", "content_policy"
        if status == "permission_denied" and category == "unknown":
            status = "operation_failed"
        return RULES[code]._replace(
            category=category,
            stage=stage,
            status="operation_failed" if status == "retry_later" else status,
        )
    constraint = result.data.get("retrieval_constraint")
    if guidance := retrieval_guidance(code, constraint):
        action, summary = guidance
        return Rule(
            "authorization", "authorization", "permission_denied", summary, "after_review", action
        )
    http = result.data.get("upstream_http_status")
    if result.data.get("origin") == "file_delivery_provider" and code in {
        "RESOURCE_PERMISSION_DENIED",
        "RESOURCE_UNAVAILABLE",
    }:
        return Rule(
            "upstream",
            "document_download",
            "operation_failed" if http == 404 else "permission_denied",
            "The file delivery service could not provide this file. Check whether it opens in your Canvas account.",
            "after_review",
            "check_resource_access_in_canvas",
        )
    if code == "UPSTREAM_SCOPE_INSUFFICIENT" and http == 403:
        return Rule(
            "upstream",
            "upstream_request",
            "permission_denied",
            GUIDANCE[code][3],
            "after_review",
            GUIDANCE[code][1],
        )
    if (code, http) in {("RESOURCE_PERMISSION_DENIED", 403), ("RESOURCE_UNAVAILABLE", 404)}:
        message = (
            "Canvas denied access to the requested resource."
            if http == 403
            else "Canvas returned 404. The route or resource was unavailable to this request."
        )
        return Rule(
            "upstream",
            "upstream_request",
            "permission_denied" if http == 403 else "operation_failed",
            message + " Check the resource in your Canvas account.",
            "after_review",
            "check_resource_access_in_canvas",
        )
    if code == "UNKNOWN_AUTHORIZATION_FAILURE" and http == 401:
        return Rule(
            "upstream",
            "upstream_request",
            "operation_failed",
            "Canvas could not verify this request. The authentication cause is unknown.",
        )
    if code in {"MCP_SESSION_REVOKED", "MCP_TOKEN_EXPIRED"}:
        return RULES["MCP_ACCESS_DENIED"]._replace(action="repair_inbound_credential")
    if code in {"CANVAS_OAUTH_UNAVAILABLE", "CANVAS_OAUTH_EXCHANGE_FAILED"}:
        return Rule(
            "upstream",
            "upstream_request",
            "retry_later",
            "Canvas authorization exchange unavailable.",
            "after_delay",
            "wait_or_contact_operator",
        )
    if code in {"UPSTREAM_AUTH_EXPIRED", "UPSTREAM_CREDENTIAL_REJECTED"}:
        return Rule(
            "upstream",
            "upstream_request",
            "reconnect_required",
            "Renew Canvas authentication, then refresh course access.",
            "after_refresh",
            "reconnect_then_refresh",
        )
    if code in {"DOCUMENT_WORKER_TIMEOUT", "DOCUMENT_WORKER_CPU_LIMIT"}:
        stage = result.data.get("timeout_stage", "tool_execution")
        message = "Document processing exceeded its time limit."
        if stage == "pptx_conversion":
            message += " Selecting fewer slides can still require conversion of the entire deck."
        first, last = result.data.get("page_start"), result.data.get("page_end")
        if (
            type(first) is int
            and type(last) is int
            and 1 <= first <= last <= min(first + PDF_BATCH_PAGES - 1, 200)
        ):
            message += (
                f" Retry PDF page {first} alone."
                if first < last
                else f" Use render_course_file_page for PDF page {first}."
            )
            if first == last and last < 200:
                message += f" Reading can resume at page {last + 1}."
        return internal(stage, message)
    if (
        code == "DOCUMENT_PARSER_VERSION_CHANGED"
        and result.data.get("processing_stage") == "result_validation"
    ):
        return Rule(
            "internal",
            "result_validation",
            "operation_failed",
            "The worker and service parser versions differ. Ask the operator to restart the service with a matching worker before retrying.",
            "after_operator_fix",
            "restart_service_with_matching_parser",
        )
    if code == "DOCUMENT_RANGE_OUT_OF_BOUNDS" and result.status == "needs_input":
        if bounds := safe_range_fields(result.data):
            message = range_message(bounds["page_start"], bounds["page_end"], bounds["page_count"])
            return RULES[code]._replace(summary=message)
    if code in RULES:
        return RULES[code]
    status = result.status
    category, stage, retry = "unknown", "tool_execution", "unknown"
    action = "report_request_id"
    if code in GUIDANCE:
        origin, action, _, _ = GUIDANCE[code]
        category, stage, retry = ORIGINS[origin]
        if code == "STALE_SCOPE_SNAPSHOT":
            retry = "after_refresh"
    elif code in {
        "OWNER_RATE_LIMITED",
        "RATE_LIMITED",
        "UPSTREAM_BUDGET_EXHAUSTED",
        "DOCUMENT_WORKER_BUSY",
        "DOCUMENT_DOWNLOAD_BUSY",
    }:
        category, stage, retry, action = (
            "internal",
            "tool_execution",
            "after_delay",
            "wait_for_capacity",
        )
    elif result.data.get("required_fields") or status == "needs_input":
        category, stage, retry, action = (
            "validation",
            "input_validation",
            "after_review",
            "correct_input",
        )
    elif attempt.policy in {"deny", "requires_review"} or code in INTEGRITY_CODES:
        category, stage, retry, action = "policy", "content_policy", "after_review", "review_policy"
    elif code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_REQUEST_TIMEOUT"}:
        category, stage, retry, action = (
            "upstream",
            "upstream_request",
            "after_delay",
            "wait_for_recovery",
        )
    elif code in MESSAGES:
        category, stage, retry, action = (
            "authorization",
            "authorization",
            "after_review",
            "review_access",
        )
    if status == "permission_denied" and category in {"internal", "validation", "upstream"}:
        status = "operation_failed"
    if status == "retry_later" and retry not in {"after_delay", "after_refresh"}:
        status = "operation_failed"
    return Rule(category, stage, status, result.summary, retry, action)


def describe(result, release):
    attempt = current.get()
    if attempt is None:
        return
    if (
        attempt.diagnostic
        and attempt.diagnostic.sanitized_error_release == release
        and result.data.get("diagnostic") == public_fields(attempt.diagnostic)
    ):
        return
    code = result.data["reason_code"]
    if code == "EGRESS_ERROR_REDACTED":
        code = "UNCLASSIFIED_FAILURE"
    rule = rule_for(code, result, attempt)
    operation = attempt.operation
    label = {
        "prepare_academic_assistance": "Preparing study materials",
        "check_academic_assistance_permission": "Checking academic assistance permission",
    }.get(operation, operation.replace("_", " ").capitalize() if operation else "Request")
    result.meta.request_id = attempt.request_id
    result.status = rule.status
    result.summary = f"{label}: {rule.summary}"
    if rule.action == "report_request_id":
        result.summary += f" Report request {attempt.request_id} to the operator."
    fields = {}
    for key, low, high in (("retry_after_seconds", 0, 86400), ("upstream_http_status", 100, 599)):
        value = result.data.get(key)
        if key == "retry_after_seconds" and rule.retry != "after_delay":
            continue
        if type(value) is int and low <= value <= high:
            fields[key] = value
    if code == "SLIDE_RENDER_RESOURCE_LIMIT" and "render_failure_reason" in result.data:
        fields["render_failure"] = result.data["render_failure_reason"]
    if result.data.get("origin") == "file_delivery_provider":
        fields["origin"] = "file_delivery_provider"
    elif "upstream_http_status" in fields and rule.stage == "upstream_request":
        fields["origin"] = "canvas_api"
    elif result.data.get("retrieval_constraint") in {
        "file_unpublished",
        "file_hidden",
        "file_locked",
        "file_visibility_unknown",
    }:
        fields["origin"] = "canvas_metadata"
    elif rule.category == "policy":
        fields["origin"] = "egress_policy"
    elif rule.category == "authorization" and rule.stage == "authorization":
        fields["origin"] = "bridge_scope"
    if "retrieval_constraint" in result.data:
        fields["retrieval_constraint"] = result.data["retrieval_constraint"]
    if "retrieval_method" in result.data:
        fields["retrieval_method"] = result.data["retrieval_method"]
    if "resource_kind" in result.data:
        fields["resource_kind"] = result.data["resource_kind"]
    scope = {
        "AUTHORIZATION_BUSY": "connection",
        "LOCAL_REQUEST_BUSY": "local_worker",
        "DOCUMENT_WORKER_BUSY": "local_worker",
        "DOCUMENT_DOWNLOAD_BUSY": "local_worker",
        "UPSTREAM_CIRCUIT_OPEN": "circuit_recovery",
        "UPSTREAM_BUDGET_EXHAUSTED": result.data.get("blocking_scope"),
        "UPSTREAM_THROTTLED": "provider_capacity"
        if fields.get("upstream_http_status") in {403, 429}
        else result.data.get("blocking_scope"),
    }.get(code)
    if (
        code == "LOCAL_REQUEST_BUSY"
        and result.data.get("reservation_state") == "expiration_pending"
    ):
        fields["reservation_state"] = "expiration_pending"
    if scope:
        fields["blocking_scope"] = scope
    if (code == "AUTHORIZATION_BUSY" and "deadline_seconds" in result.data) or code in {
        "DOCUMENT_WORKER_TIMEOUT",
        "DOCUMENT_WORKER_CPU_LIMIT",
        "DOCUMENT_DOWNLOAD_TIMEOUT",
        "INVENTORY_BRANCH_TIMEOUT",
        "PPTX_CONVERSION_TIMEOUT",
        "RENDER_RENDER_TIMEOUT",
        "DOCUMENT_SANDBOX_SETUP_TIMEOUT",
        "UPSTREAM_REQUEST_TIMEOUT",
        "TRANSPORT_TIMEOUT",
    }:
        fields["operation_state"] = (
            "not_started"
            if code in {"DOCUMENT_SANDBOX_SETUP_TIMEOUT", "AUTHORIZATION_BUSY"}
            else result.data.get("operation_state", "unknown")
        )
        for key in ("elapsed_ms", "deadline_seconds"):
            if key in result.data:
                fields[key] = result.data[key]
    if operation in {"list_course_files", "read_course_file"}:
        fields["attempted_methods"] = list(attempt.retrieval_methods)
        if (
            "retrieval_method" not in fields
            and attempt.last_retrieval_method
            and rule.stage
            in {
                "upstream_request",
                "authorization",
                "document_download",
                "tool_execution",
                "text_extraction",
                "ocr",
                "runtime_setup",
            }
        ):
            fields["retrieval_method"] = attempt.last_retrieval_method
        if (
            result.data.get("capability_observation") == "recent_denial"
            and fields.get("upstream_http_status") == 403
        ):
            fields["capability_observation"] = "recent_denial"
        fields["source_bytes_obtained"] = attempt.source_bytes_obtained
        fields["inventory_coverage"] = "unknown"
    auth = attempt.auth_observation if code == "TRANSPORT_ACCESS_DENIED" else None
    if auth is None:
        auth = tool_observation(code, fields.get("upstream_http_status"), attempt, result.data)
    if auth and attempt.diagnostic and attempt.diagnostic.code == code:
        auth = attempt.diagnostic.authentication_diagnostic or auth
    if auth:
        result.summary = f"{label}: {auth.explanation}"
        if code == "TRANSPORT_ACCESS_DENIED":
            rule = rule._replace(
                action=auth.recovery_action,
                retry="after_delay" if auth.retry == "after_delay_once" else "after_review",
            )
        if auth.code == "AUTH_ORIGIN_UNKNOWN":
            fields.pop("origin", None)
            rule = rule._replace(
                category="unknown",
                stage=attempt.observed_stage,
                retry="unknown",
                action="report_request_id",
            )
    diagnostic = FailureDiagnostic(
        authentication_diagnostic=auth,
        category=rule.category,
        code=code,
        stage=rule.stage,
        certainty="unknown"
        if (auth and auth.attribution == "unknown")
        or code in {"UNCLASSIFIED_FAILURE", "UNKNOWN_AUTHORIZATION_FAILURE"}
        else "confirmed",
        requested_operation=operation,
        retry=rule.retry,
        next_action=rule.action,
        content_delivery=attempt.delivery,
        request_id=attempt.request_id,
        requested_operation_outcome="partial"
        if attempt.delivery == "partial"
        else ("unknown" if rule.stage == "http_transport" else "failed"),
        requested_content_policy=attempt.policy,
        sanitized_error_release=release,
        **fields,
    )
    attempt.diagnostic = diagnostic
    result.data["diagnostic"] = public_fields(diagnostic)
    if code == "TOOL_INPUT_INVALID" and attempt.input_field:
        result.data["required_fields"] = [attempt.input_field]
        result.summary += f" Check {attempt.input_field} ({attempt.constraint})."


def public_fields(diagnostic):
    data = diagnostic.model_dump(exclude_none=True)
    data["requested_operation"] = diagnostic.requested_operation
    return data
