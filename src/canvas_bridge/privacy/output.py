"""Conservative field classification for the existing heterogeneous Result contract.

The frozen vocabulary is inventoried from reviewed academic producers; it is NOT
learned from provider responses, tool arguments, environment or model output.
Endpoint schemas provide the stricter record-specific collection boundary.
"""

import json
from contextvars import ContextVar
from pathlib import Path

from canvas_bridge.analytics.privacy import FIELDS as ANALYTICS_FIELDS
from canvas_bridge.library.privacy import FIELDS as LIBRARY_FIELDS
from canvas_bridge.permission_recovery import recovery_actions
from canvas_bridge.privacy.identity import FieldClass
from canvas_bridge.privacy_text import VERSION, WITHHELD, inspect_text
from canvas_bridge.processes.privacy import FIELDS as PROCESS_FIELDS
from canvas_bridge.registrar import FIELDS as REGISTRAR_FIELDS
from canvas_bridge.usefulness.privacy import FIELDS as USEFULNESS_FIELDS

FIELDS = frozenset(json.loads(Path(__file__).with_name("output_fields.json").read_text()))
FIELDS |= ANALYTICS_FIELDS
FIELDS |= PROCESS_FIELDS
FIELDS |= USEFULNESS_FIELDS
FIELDS |= LIBRARY_FIELDS
FIELDS |= REGISTRAR_FIELDS
FIELDS |= {
    "pin_conflicts",
    "effort_summary",
    "known_remaining_minutes",
    "allocated_work_minutes",
    "total_known_unallocated_minutes",
    "capacity_blocked_minutes",
    "dependency_blocked_minutes",
    "other_unallocated_minutes",
    "uncredited_block_minutes",
    "unknown_effort_work_ids",
    "completed_work_ids",
    "receipt_verification_work_ids",
    "receipt_checks",
    "unresolved_requirement_ids",
    "inferred_deadline_parents",
    "deadline_basis",
    "study_step_review",
    "source_work_steps",
    "steps",
}
FIELDS |= {
    "error_origin",  # Fixed public error taxonomy, reconstructed before release.
    "retry_condition",
    "retry_after_seconds",
    "cached_information",
    "local_processing_available",
    "drop_basis",
    "audit_coverage",
    "source_retrieval",
    "graph_construction",
    "entity_matching",
    "unmatched_occurrences",
    "matched_identifier",
    "assignment_title",
    "compared_cross_source_pairs",
    "cross_source_comparison",
    "cross_source_consistency",
    "deadline_wording",
    "raw_date",
    "obligation_groups",
    "occurrences",
    "timeout_stage",
    "year",
    "month",
    "day",
    "clock",
    "possible_utc",
    "normalization_status",
    "next_actions",
    "source_slide_count",
    # Course inventory coverage and opaque ancestor IDs; no folder names/URLs.
    "folders",
    "inventory_operation",
    "inventory_recovery",
    "retrieval_constraint",
    "attempted_methods",
    "failed_methods",
    "verified_file_references",
    "capability_observation",
    "requested_operation",
    "origin",
    "page_identity",
    "folder_graph",
    "parent_id",
}
# Reviewed integrity envelopes; these names do not convey authority by themselves.
FIELDS |= frozenset(
    {
        "academic_integrity",
        "integrity_boundary",
        "completion_permission",
        "substantive_content",
        "permission_established",
        "acknowledgment_eligible",
        "acknowledgment_valid",
        "acknowledgment_notice",
        "acknowledgment_id",
        "public_policy_lookup",
        "source_coverage",
        "local_course",
        "assessment_id",
        "document_ids",
        "authority",
        "verification",
        "effective_at",
        "academic_term",
        "supersedes",
        "issuer",
        "limitation",
        "source_version",
        "assessment_only",
        "exam_only",
        "condition",
        "effect",
        "activities",
        "allowed_activity_scope",
        "assistance_evidence",
        "authorship_guidance",
        "editable_disclosure_template",
        "permission_evidence_status",
        "reevaluated_from",
        "prior_policy_version_valid",
        "acknowledgments",
        "revoked",
        "permitted_alternatives",
        "applicable_limits",
        "evidence_needed",
        "clarification_suggestions",
        "required_fields",
        "supported_schema_version",
        "setup_checks",
    }
)
source_refs: ContextVar[frozenset[str]] = ContextVar(
    "privacy_owned_source_refs", default=frozenset()
)
REFERENCE_MAPS = {
    "work_accounting",
    "timing_constraints",
    "effort_overrides",
    "priority_overrides",
    "date_only_timezones",
    "importance",
}
DIRECT = frozenset(
    "email student_email student_name teacher_email canvas_user user_id student_id owner grader_id author_id author creator lastmodifiedby last_modified_by login_id sis_user_id sortable_name short_name avatar_url display_name pronouns address phone participants roster readers writers".split()
)
SENSITIVE = frozenset(
    "submission_comments submission_body user student instructor author participants roster password access_token refresh_token client_secret authorization credentials secret evidence_reference written_authorization_reference".split()
)
SCALARS = frozenset(
    "id title name summary text description body excerpt quote url uri filename path source_id course_id connection_id file_id material_id resource_id request_id content_hash semantic_hash version_hash bytes_sha256 source_version mimeType content_type author_id user_id student_id".split()
)


def field_class(key):
    if key.lower() in DIRECT:
        return FieldClass.THIRD_PARTY_DIRECT_IDENTIFIER
    if key.lower() in SENSITIVE:
        return FieldClass.SENSITIVE_CONTENT
    return FieldClass.SAFE_ACADEMIC if key in FIELDS else FieldClass.UNKNOWN_FIELD


def filter_output(payload, *, own_canvas_user=None, reviewed_diagnostic=None):
    from canvas_bridge.egress_policy import dangerous_reference

    redacted = third_party = hidden = False
    aliases = set()
    person_rows = set()
    nodes = 0

    def scan(value, depth=0):
        nonlocal third_party, hidden, nodes
        nodes += 1
        if depth > 40 or nodes > 100_000:
            raise ValueError("Privacy inspection limit")
        if isinstance(value, dict):
            if set(value) & {
                "email",
                "student_email",
                "student_name",
                "login_id",
                "sis_user_id",
                "avatar_url",
                "sortable_name",
                "short_name",
                "pronouns",
            }:
                # A person-shaped object with no verified ID is UNKNOWN, not an
                # academic object just because it used generic `id`/`name` keys.
                if own_canvas_user is None or str(value.get("user_id")) != own_canvas_user:
                    third_party = True
                    person_rows.add(id(value))
                    aliases.update(
                        v
                        for k, v in value.items()
                        if k in {"name", "display_name", "short_name", "login_id"}
                        and isinstance(v, str)
                        and len(v) <= 200
                    )
            for key in ("user_id", "student_id"):
                if key in value and (own_canvas_user is None or str(value[key]) != own_canvas_user):
                    third_party = True
                    aliases.update(
                        v
                        for k, v in value.items()
                        if k in {"name", "display_name", "short_name", "login_id"}
                        and isinstance(v, str)
                        and len(v) <= 200
                    )
            for key, item in value.items():
                if (
                    key.lower() in DIRECT
                    and isinstance(item, str)
                    and 3 <= len(item) <= 200
                    and not (key == "author" and item == "self")
                ):
                    aliases.add(item)
                if key.lower() in {"author", "user", "student", "instructor", "participants"}:
                    people = item if isinstance(item, list) else [item]
                    for person in people:
                        if isinstance(person, dict):
                            aliases.update(
                                v
                                for k, v in person.items()
                                if k in {"name", "display_name", "short_name", "login_id"}
                                and isinstance(v, str)
                                and 3 <= len(v) <= 200
                            )
                scan(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                scan(item, depth + 1)
        elif isinstance(value, str):
            hidden |= dangerous_reference(value)

    scan(payload)
    if len(aliases) > 256:
        raise ValueError("Privacy inspection limit")

    verified_auth = None

    def project(value, parent=""):
        nonlocal redacted, verified_auth
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if (
                    key == "recovery_actions"
                    and value is payload.get("data")
                    and isinstance(item, list)
                ):
                    reviewed = recovery_actions(
                        row.get("action_id") for row in item if isinstance(row, dict)
                    )
                    redacted |= reviewed != item
                    out[key] = reviewed
                    continue
                if key == "authentication_diagnostic" and value is payload.get("data"):
                    from canvas_bridge.failure_diagnostics import current

                    attempt = current.get()
                    if (
                        attempt
                        and attempt.auth_observation
                        and item == attempt.auth_observation.model_dump()
                    ):
                        verified_auth = item
                        out[key] = project(item, key)
                    else:
                        redacted = True
                    continue
                if key == "author" and item == "self":
                    # A fixed role label discloses no person identifier.
                    out[key] = "self"
                    continue
                if id(value) in person_rows and key in {"id", "name", "display_name"}:
                    redacted = True
                    continue
                if parent in REFERENCE_MAPS:
                    if key not in source_refs.get():
                        redacted = True
                        continue
                elif value is verified_auth or (
                    reviewed_diagnostic is not None
                    and value is reviewed_diagnostic.get("authentication_diagnostic")
                ):
                    pass  # Exact server observation, still inspect every value.
                elif reviewed_diagnostic is not None and (
                    (
                        value is payload.get("data")
                        and key == "diagnostic"
                        and item is reviewed_diagnostic
                    )
                    or value is reviewed_diagnostic
                ):
                    pass  # Exact server-built scalar fields still traverse text inspection.
                elif field_class(key) != FieldClass.SAFE_ACADEMIC:
                    redacted = True
                    continue
                if key in SCALARS and isinstance(item, (dict, list)):
                    redacted = True
                    continue
                out[key] = project(item, key)
            return out
        if isinstance(value, list):
            return [project(v, parent) for v in value]
        if isinstance(value, str):
            clean, changed = inspect_text(value, aliases)
            redacted |= changed
            return clean
        return value

    return project(payload), redacted, third_party, hidden


def metadata(filtered=False, *, content=""):
    return {
        "policy_version": VERSION,
        "enabled": True,
        "filtered": filtered,
        "content_status": "content_withheld_privacy_uncertainty"
        if WITHHELD in content
        else "minimized_and_inspected",
    }
