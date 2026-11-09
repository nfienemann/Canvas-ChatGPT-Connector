"""Run the offline imported-corpus benchmark and keep per-case honest receipts."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--select", help="Optional pytest case selection for a focused rerun.")
    parser.add_argument(
        "--visual-observations",
        type=Path,
        help="Optional hash-bound observations from actual model pixel review; never generated from gold.",
    )
    parser.add_argument(
        "--office-root",
        type=Path,
        help="Trusted public LibreOffice runtime for isolated native tests.",
    )
    parser.add_argument(
        "--parser-root", type=Path, help="Dedicated disposable parser work/cache root."
    )
    parser.add_argument(
        "--slide-observations",
        type=Path,
        help="Hash-bound human/model observation of the original rendered slide.",
    )
    parser.add_argument(
        "--acknowledgment-receipt",
        type=Path,
        help="Receipt from the separately completed genuine UI acknowledgment test.",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_hashes = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ("src/canvas_bridge", "tests", "migrations", "governance", "docs/schemas")
        for p in sorted((ROOT / folder).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    for name in (
        "tests/stress_support.py",
        "tests/stress_repair_cases.py",
        "scripts/run_stress_repair.py",
        "scripts/run_integrity_acknowledgment_demo.py",
    ):
        source_hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    commit = subprocess.run(  # noqa: S603 - resolved Git executable and fixed read-only arguments.
        [shutil.which("git"), "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    build = {
        "commit": commit,
        "working_source_hashes": source_hashes,
        "source_fingerprint": hashlib.sha256(
            json.dumps(source_hashes, sort_keys=True).encode()
        ).hexdigest(),
        "suite": "product_integration",
        "installed_connector": "NOT_RUN",
        "fixture_self_checks": "SEPARATE_SUITE",
        "started_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "dependencies": {
            name: version(name) for name in ("mcp", "pydantic", "sqlalchemy", "pytest", "alembic")
        },
        "visual_observations_sha256": hashlib.sha256(
            args.visual_observations.read_bytes()
        ).hexdigest()
        if args.visual_observations
        else None,
        "external_acceptance_receipts": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in (
                ("slide", args.slide_observations),
                ("acknowledgment", args.acknowledgment_receipt),
            )
            if path
        },
    }
    (output / "build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "tests/stress_repair_cases.py", "-q", "--tb=short"]
    if args.select:
        command += ["-k", args.select]
    result = subprocess.run(  # noqa: S603 - fixed interpreter/test path, shell=False; selection is a pytest expression.
        command,
        cwd=ROOT,
        env={
            **os.environ,
            "CANVAS_BRIDGE_STRESS_OUTPUT": str(output),
            "CANVAS_BRIDGE_STRESS_BUILD": build["source_fingerprint"],
            **{
                name: str(path.resolve())
                for name, path in (
                    ("CANVAS_BRIDGE_TEST_OFFICE_ROOT", args.office_root),
                    ("CANVAS_BRIDGE_TEST_PARSER_ROOT", args.parser_root),
                    ("CANVAS_BRIDGE_SLIDE_OBSERVATIONS", args.slide_observations),
                    ("CANVAS_BRIDGE_ACK_RECEIPT", args.acknowledgment_receipt),
                )
                if path
            },
            **(
                {"CANVAS_BRIDGE_VISUAL_OBSERVATIONS": str(args.visual_observations.resolve())}
                if args.visual_observations
                else {}
            ),
        },
        check=False,
    )
    cases = [
        json.loads(p.read_text())
        for p in sorted(output.glob("*-*.json"))
        if p.stem[:2] in {"GR", "DE", "RQ", "AI", "VI", "PL", "KN", "DG", "DP", "ST", "OP"}
    ]
    cases = [c for c in cases if c.get("source_fingerprint") == build["source_fingerprint"]]
    unchanged = all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
        for name, digest in source_hashes.items()
    )
    summary = {
        "source_fingerprint": build["source_fingerprint"],
        "source_unchanged_during_run": unchanged,
        "finished_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "counts": dict(Counter(c["status"] for c in cases)),
        "cases": [
            {"id": c["case"]["id"], "status": c["status"], "detail": c["detail"]} for c in cases
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("case_count", "counts", "source_fingerprint")}))
    return result.returncode if unchanged else 2


if __name__ == "__main__":
    raise SystemExit(main())
