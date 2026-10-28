"""Fixed input diagnostics before SDK validation; never serialize exception text.

Only these reviewed contracts are inspected. This does not authorize or acquire
sources, and valid requests still traverse the entire normal tool pipeline.
"""

from pydantic import ValidationError

from canvas_bridge.academic.independent_models import IndependentRequest
from canvas_bridge.domain import Result
from canvas_bridge.integrity.models import AssistanceRequest, Scope

CAPABILITIES = frozenset(IndependentRequest.model_fields["capability"].annotation.__args__)
CONTRACTS = {
    "run_independent_academic_workflow": ("request", IndependentRequest),
    "get_academic_integrity_policy": ("scope", Scope),
    "check_academic_assistance_permission": ("request", AssistanceRequest),
    "get_integrity_guidance": ("request", AssistanceRequest),
    "prepare_academic_assistance": ("request", AssistanceRequest),
    "provide_instructor_permission_evidence": ("scope", Scope),
}


def input_error(tool, arguments):
    contract = CONTRACTS.get(tool)
    if not contract or not isinstance(arguments, dict):
        return None
    key, model = contract
    raw = arguments.get(key)
    if key == "scope" and key not in arguments:
        return Result(
            status="needs_input", summary="", data={"reason_code": "INTEGRITY_SCOPE_MISSING"}
        )
    if not isinstance(raw, dict):
        return None
    try:
        model.model_validate(raw)
    except ValidationError as exc:
        # Values, messages and contexts are private, including malicious inputs.
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        kinds = {e["type"] for e in errors}
        code = None
        if kinds == {"independent_input_missing"}:
            code = "INDEPENDENT_INPUT_MISSING"
        elif kinds == {"integrity_scope_missing"}:
            code = "INTEGRITY_SCOPE_MISSING"
        elif kinds == {"integrity_scope_invalid"}:
            code = "INTEGRITY_SCOPE_INVALID"
        elif model is AssistanceRequest and all(
            e["type"] == "missing" and e["loc"] == ("scope",) for e in errors
        ):
            code = "INTEGRITY_SCOPE_MISSING"
        elif (
            tool == "run_independent_academic_workflow"
            and any(e["loc"][-1:] == ("document_id",) for e in errors)
            and all(
                e["type"] == "missing" and e["loc"][-1:] in {("document_id",), ("expected_hash",)}
                for e in errors
            )
        ):
            code = "INDEPENDENT_INPUT_MISSING"
        elif tool == "run_independent_academic_workflow" and all(
            e["loc"]
            and e["loc"][-1] == "expected_hash"
            and e["type"] in {"missing", "string_pattern_mismatch", "string_type"}
            for e in errors
        ):
            code = "INDEPENDENT_HASH_REQUIRED"
        if code:
            capability = raw.get("capability")
            return Result(
                status="needs_input",
                summary="",
                data={
                    "reason_code": code,
                    "requested_capability": capability
                    if isinstance(capability, str) and capability in CAPABILITIES
                    else None,
                },
            )
    return None


def diagnostic_fields(code, capability=None):
    """Rebuild remediation solely from constants, including on repeated egress."""
    if code in {
        "INDEPENDENT_GRADES_MISSING",
        "INDEPENDENT_WORK_MISSING",
        "INDEPENDENT_CALENDAR_MISSING",
    }:
        field = {
            "INDEPENDENT_GRADES_MISSING": "grades",
            "INDEPENDENT_WORK_MISSING": "work",
            "INDEPENDENT_CALENDAR_MISSING": "calendar",
        }[code]
        return {
            "required_fields": [field],
            "next_action": "Supply a fresh authorized Calendar read with complete event and mapping coverage; missing Calendar data is unknown. No event will be written."
            if field == "calendar"
            else "Import permitted academic records containing this field, then select the new document and its current hash.",
        }
    if code == "INDEPENDENT_INPUT_MISSING":
        fields = (
            ["dataset.document_id", "dataset.expected_hash"]
            if capability in {"planning", "grades", "calendar"}
            else ["documents[].document_id", "documents[].expected_hash"]
            if capability in {"assessment", "requirements"}
            else ["dataset or documents", "document_id", "expected_hash"]
        )
        return {
            "required_fields": fields,
            "next_action": "Import permitted sources in signed-in document settings, then select their IDs and current hashes from get_local_document_status. No LMS connection is required.",
        }
    if code in {"INDEPENDENT_HASH_REQUIRED", "INDEPENDENT_SOURCE_CHANGED"}:
        return {
            "required_fields": ["expected_hash"],
            "next_action": "Read get_local_document_status for an authorized selection, review the current version, then restart with its content_hash. Do not reuse a stale continuation.",
        }
    if code in {"INDEPENDENT_SCHEMA_UNSUPPORTED", "INDEPENDENT_INPUT_INVALID"}:
        return {
            "supported_schema_version": "independent-academic-1",
            "next_action": "Validate the permitted TXT or Markdown JSON records against the documented independent-academic-1 schema and reimport corrected records. No calculation succeeded.",
        }
    if code in {"INTEGRITY_SCOPE_MISSING", "INTEGRITY_SCOPE_INVALID"}:
        return {
            "required_fields": [
                "scope.local_course or scope.document_ids or (scope.connection_id and scope.course_id)"
            ],
            "next_action": "Select a local course label or authorized independent documents. Only an institutional scope needs both connection_id and course_id. A local label grants no authority.",
        }
    return {}
