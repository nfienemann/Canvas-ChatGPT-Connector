"""Source-bound process acceptance gate, using the existing pytest receipt format.

Run after the synthetic suite, not against private coursework. A green backend
report never establishes deployed client acceptance or external approval.
"""

import argparse
import json
import re
from pathlib import Path

from canvas_bridge.compliance.inventory import source_state, test_index
from canvas_bridge.compliance.models import TestRun
from canvas_bridge.processes import VERSION


def evaluate_run(run, expected_digest, required):
    failures = []
    if run.source.digest != expected_digest or not run.source_unchanged:
        failures.append("SOURCE_CHANGED")
    if run.exit_code or run.interrupted or not run.complete_selection:
        failures.append("TEST_RUN_INCOMPLETE_OR_FAILED")
    if not required:
        failures.append("TEST_INVENTORY_MISSING")
    statuses = {}
    for name in sorted(required):
        counts = run.cases.get(name)
        statuses[name] = (
            "passed"
            if counts and counts.verified()
            else "missing"
            if counts is None
            else "failed_or_skipped"
        )
    if any(s != "passed" for s in statuses.values()):
        failures.append("PROCESS_REGRESSION")
    specifications = {}
    for number in range(1, 18):
        cases = [name for name in statuses if re.search(rf"test_cb{number:02d}(?:_|$)", name)]
        specifications[f"CB-{number:02d}"] = {
            "cases": len(cases),
            "passed": sum(statuses[n] == "passed" for n in cases),
        }
        if not cases:
            failures.append(f"CB_{number:02d}_ACCEPTANCE_MISSING")
    return {
        "schema_version": "process-evaluation-1",
        "component_version": VERSION,
        "source_digest": run.source.digest,
        "source_unchanged": run.source_unchanged,
        "passed": not failures,
        "blocking_reasons": failures,
        "test_cases": len(statuses),
        "passing_cases": sum(s == "passed" for s in statuses.values()),
        "specifications": specifications,
        "critical_regressions_allowed": 0,
        "extraction_precision_recall": "not_measured_here; use the existing academic benchmark lab",
        "model_interpretation_accuracy": "not_measured",
        "deployment_acceptance": "not_established",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if args.results.stat().st_size > 5_000_000:
        raise ValueError("Receipt exceeds the inspection limit.")
    run = TestRun.model_validate_json(args.results.read_text(encoding="utf-8"))
    required = {node for node in test_index(root) if node.startswith("tests/test_process_")}
    report = evaluate_run(run, source_state(root).digest, required)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "test_cases": report["test_cases"],
                "blocking_reasons": report["blocking_reasons"],
            }
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
