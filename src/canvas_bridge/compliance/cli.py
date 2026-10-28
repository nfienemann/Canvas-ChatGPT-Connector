"""Repository-only report command; it never initializes application Settings."""

import json
from pathlib import Path

from pydantic import ValidationError

from canvas_bridge.compliance.inventory import validate_repository
from canvas_bridge.compliance.models import EvidenceError
from canvas_bridge.compliance.report import TARGETS, generate, write_report


def arguments(sub):
    parser = sub.add_parser(
        "compliance-report", help="Generate sanitized technical evidence; grants no approval."
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".local/compliance-report"))
    parser.add_argument(
        "--category", choices=(*TARGETS, "synthetic_demo"), default="synthetic_demo"
    )
    parser.add_argument(
        "--results", type=Path, help="Sanitized pytest recorder JSON, never a raw log."
    )
    parser.add_argument(
        "--checks", type=Path, help="Directory of source-bound fixed-check receipts."
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--require-technical", action="store_true")
    parser.add_argument("--enforce-release", choices=TARGETS)


def run(args):
    try:
        root = args.repository.resolve()
        if args.validate_only:
            registry = validate_repository(root)
            print(
                json.dumps(
                    {
                        "registry": "valid",
                        "controls": len(registry.controls),
                        "authorization_granted": False,
                    }
                )
            )
            return 0
        report = generate(root, args.category, results=args.results, checks=args.checks)
        write_report(report, args.output)
        print(
            json.dumps(
                {
                    "report": "written",
                    "development_readiness": report["development_readiness"],
                    "release_gates": {
                        name: gate["status"] for name, gate in report["release_gates"].items()
                    },
                    "legal_compliance_determination": "NOT_MADE",
                }
            )
        )
        if args.require_technical and report["development_readiness"] != "TECHNICAL_CHECKS_PASSED":
            return 2
        if (
            args.enforce_release
            and report["release_gates"][args.enforce_release]["status"] == "BLOCKED"
        ):
            return 2
        return 0
    except (EvidenceError, ValidationError, OSError, ValueError):
        # Never print a validation error containing the original malicious/private input.
        print('{"report":"not_generated","reason":"INVALID_OR_UNAVAILABLE_EVIDENCE"}')
        return 1
