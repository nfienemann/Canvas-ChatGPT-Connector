"""Execute fictional rule measurements and summarize actual source-bound workflow tests."""

import argparse
import json
from pathlib import Path

from canvas_bridge.compliance.inventory import source_state
from canvas_bridge.compliance.models import TestRun
from canvas_bridge.domain import utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.integrity.engine import evaluate_academic_assistance
from canvas_bridge.integrity.models import Activity as A
from canvas_bridge.integrity.models import Coverage, PolicySource, Verification

CASES = (
    (
        "explicit_course_prohibition",
        "All AI use is prohibited in this course.",
        A.DRAFT,
        "PROHIBITED_CONFIRMED",
        "prohibition_detection",
    ),
    (
        "assessed_code_prohibition",
        "AI is prohibited for assessed coding.",
        A.CODE,
        "PROHIBITED_CONFIRMED",
        "prohibition_detection",
    ),
    (
        "exam_prohibition",
        "AI is prohibited during exams.",
        A.ANSWER,
        "PROHIBITED_CONFIRMED",
        "prohibition_detection",
    ),
    (
        "permitted_brainstorming",
        "AI may be used for brainstorming but not writing.",
        A.BRAINSTORM,
        "PERMITTED_CONDITIONAL",
        "activity_scope",
    ),
    (
        "forbidden_drafting",
        "AI may be used for brainstorming but not writing.",
        A.DRAFT,
        "PROHIBITED_CONFIRMED",
        "activity_scope",
    ),
    (
        "permitted_grammar",
        "AI may be used only for spelling and grammar.",
        A.GRAMMAR,
        "PERMITTED_CONDITIONAL",
        "activity_scope",
    ),
    (
        "forbidden_rewrite",
        "AI may be used only for spelling and grammar.",
        A.REWRITE,
        "PROHIBITED_CONFIRMED",
        "activity_scope",
    ),
    (
        "grade_administration",
        "AI is prohibited on assignments.",
        A.ADMINISTRATION,
        "PERMITTED_CONDITIONAL",
        "administrative_availability",
    ),
    (
        "requirement_review",
        "AI is prohibited on assignments.",
        A.REQUIREMENTS,
        "PERMITTED_CONDITIONAL",
        "administrative_availability",
    ),
    (
        "sample_not_adopted",
        "Sample policy: AI is prohibited.",
        A.DRAFT,
        "NO_POLICY_FOUND",
        "false_positive_cases",
    ),
    ("negation", "AI is not prohibited.", A.DRAFT, "AMBIGUOUS", "false_positive_cases"),
    (
        "academic_discussion",
        "AI is discussed in this course.",
        A.DRAFT,
        "NO_POLICY_FOUND",
        "false_positive_cases",
    ),
    ("no_rule", "There is no AI policy.", A.DRAFT, "NO_POLICY_FOUND", "false_positive_cases"),
    (
        "permission_required",
        "Students must obtain instructor permission before using AI.",
        A.DRAFT,
        "PERMISSION_REQUIRED",
        "mandatory_requirements",
    ),
    (
        "approved_tool_required",
        "Only institution-approved AI tools may be used.",
        A.DRAFT,
        "PERMISSION_REQUIRED",
        "mandatory_requirements",
    ),
    (
        "conditional_permission_cannot_grant_itself",
        "AI may be used for brainstorming with instructor permission.",
        A.BRAINSTORM,
        "PERMISSION_REQUIRED",
        "mandatory_requirements",
    ),
    (
        "adopted_sample_is_binding",
        "We adopt this sample policy: AI is prohibited on assignments.",
        A.DRAFT,
        "PROHIBITED_CONFIRMED",
        "prohibition_detection",
    ),
    (
        "citation_condition",
        "AI tools may be used if properly cited.",
        A.DRAFT,
        "PERMITTED_CONDITIONAL",
        "source_and_disclosure",
    ),
    (
        "false_authorship",
        "AI is permitted.",
        A.FALSE_DECLARATION,
        "PROHIBITED_CONFIRMED",
        "source_and_disclosure",
    ),
)
WORKFLOW_MEASURES = {
    "override_rejection": [
        "test_real_mcp_denial_acknowledgment_scope_and_offline_tools",
        "test_acknowledgment_expiration_egress_denial_and_source_deletion",
    ],
    "cross_tool_bypass_rejection": [
        "test_offline_restriction_and_known_copy_cannot_escape_by_switching_tools",
        "test_automatic_reader_discovery_enforces_broad_learning_prohibition",
        "test_administrative_label_never_releases_completion_package",
        "test_future_unclassified_tool_fails_closed",
    ],
    "policy_version_invalidation": [
        "test_eligible_acknowledgment_owner_scope_expiry_and_policy_change",
        "test_public_review_has_no_fetch_or_override_and_hash_binds_content",
        "test_rowan_reference_profile_requires_permission_and_expires",
    ],
    "offline_compatibility": [
        "test_offline_mcp_acknowledgment_and_denied_category_change",
        "test_offline_restriction_and_known_copy_cannot_escape_by_switching_tools",
    ],
}


def measure():
    rows = []
    for name, text, activity, expected, group in CASES:
        source = PolicySource(
            id="fictional-syllabus",
            version=fingerprint(text),
            kind="syllabus",
            authority="instructor",
            verification=Verification.OFFICIAL_SOURCE_CONFIRMED,
            course_id="fictional-course",
            retrieved_at=utcnow(),
            coverage=Coverage.READ_COMPLETE,
            parts=[{"locator": "Fictional section 4", "text": text}],
        )
        decision = evaluate_academic_assistance(activity, [source])
        rows.append(
            {
                "scenario": name,
                "measure": group,
                "expected": expected,
                "observed": str(decision.state),
                "allowed": decision.allowed,
                "passed": decision.state == expected,
                "cited_rules": len(decision.rules),
                "all_rule_citations_complete": all(
                    r.source_version and r.locator and r.passage for r in decision.rules
                ),
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = source_state(root)
    run = TestRun.model_validate_json(args.results.read_text(encoding="utf-8"))
    current = (
        run.source.digest == source.digest
        and run.source.commit == source.commit
        and run.source_unchanged
    )
    required_files = {"tests/test_integrity_engine.py", "tests/test_integrity_workflows.py"}
    tests = {k: v for k, v in run.cases.items() if k.split("::", 1)[0] in required_files}
    verified_tests = (
        current
        and run.complete_selection
        and not run.interrupted
        and run.exit_code == 0
        and {k.split("::", 1)[0] for k in tests} == required_files
        and all(counts.verified() for counts in tests.values())
    )
    rows = measure()
    measures = {
        group: {
            "passed": sum(r["passed"] for r in rows if r["measure"] == group),
            "total": sum(r["measure"] == group for r in rows),
        }
        for group in sorted({r["measure"] for r in rows})
    }
    workflow_measures = {}
    for group, names in WORKFLOW_MEASURES.items():
        keys = ["tests/test_integrity_workflows.py::" + name for name in names]
        workflow_measures[group] = {
            "tests": keys,
            "passed": sum(tests[k].passed for k in keys if k in tests),
            "failed_or_error": sum(tests[k].failed + tests[k].error for k in keys if k in tests),
            "skipped": sum(tests[k].skipped for k in keys if k in tests),
            "missing_receipts": sum(k not in tests for k in keys),
            "verified": verified_tests and all(k in tests and tests[k].verified() for k in keys),
        }
    restrictions = [
        r for r in rows if r["expected"] in {"PROHIBITED_CONFIRMED", "PERMISSION_REQUIRED"}
    ]
    non_prohibitions = [r for r in rows if r["measure"] == "false_positive_cases"]
    citations = [r for r in rows if r["cited_rules"]]
    output = {
        "schema_version": "integrity-evidence-1",
        "source_digest": source.digest,
        "source_bound_test_receipt_current": current,
        "integrity_test_selection_verified": verified_tests,
        "recorded_test_outcomes": {k: v.model_dump() for k, v in tests.items()},
        "fixture_measurements": measures,
        "missed_restrictions": {
            "erroneously_allowed": sum(r["allowed"] for r in restrictions),
            "applicable_fixture_cases": len(restrictions),
        },
        "false_positive_prohibitions": {
            "confirmed_prohibitions": sum(
                r["observed"] == "PROHIBITED_CONFIRMED" for r in non_prohibitions
            ),
            "negative_fixture_cases": len(non_prohibitions),
        },
        "citation_completeness": {
            "complete": sum(r["all_rule_citations_complete"] for r in citations),
            "cases_with_policy_rules": len(citations),
        },
        "workflow_measurements": workflow_measures,
        "fixture_results": rows,
        "external_approval": "NOT_ESTABLISHED",
        "general_semantic_accuracy": "NOT_MEASURED",
        "scope": "Fictional deterministic policy cases and recorded local workflow/MCP tests; not an institutional or legal certification.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                "current_receipt": current,
                "fixture_cases": len(rows),
                "passed": sum(r["passed"] for r in rows),
            }
        )
    )
    return 0 if verified_tests and all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
