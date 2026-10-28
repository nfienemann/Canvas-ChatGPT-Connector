"""Fixed developer checks with sanitized outcome receipts; never accepts a shell command."""

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from canvas_bridge.compliance.inventory import source_state
from canvas_bridge.compliance.models import CheckRun, EvidenceError

COMMAND_IDS = frozenset(
    {
        "lint",
        "format",
        "bandit",
        "python_vulnerabilities",
        "node_vulnerabilities",
        "licenses",
        "secret_history",
        "secret_source",
        "container_config",
        "container_image",
        "container_runtime",
    }
)


def command(check, stage, root=None):
    python = sys.executable
    root = root or Path.cwd()
    return {
        "lint": [python, "-m", "ruff", "check", "."],
        "format": [python, "-m", "ruff", "format", "--check", "."],
        "bandit": [python, "-m", "bandit", "-r", "src", "-ll", "-ii"],
        "python_vulnerabilities": [python, "-m", "pip_audit", "--local", "--format", "json"],
        "node_vulnerabilities": [
            "npm.cmd" if sys.platform == "win32" else "npm",
            "audit",
            "--json",
            "--prefix",
            "ui/page-reader",
        ],
        "licenses": [python, "scripts/supply_chain.py", "--output", str(stage), "--stage"],
        "secret_history": [
            python,
            "scripts/security_tools.py",
            "gitleaks",
            "git",
            ".",
            "--redact=100",
            "--no-banner",
            "--log-opts=--all",
        ],
        "secret_source": [
            python,
            "scripts/security_tools.py",
            "gitleaks",
            "dir",
            str(stage / "source"),
            "--redact=100",
            "--no-banner",
            "--config",
            ".gitleaks.toml",
        ],
        "container_config": [
            python,
            "scripts/security_tools.py",
            "trivy",
            "config",
            "--severity",
            "HIGH,CRITICAL",
            "--exit-code",
            "1",
            str(stage / "source"),
        ],
        "container_image": [
            python,
            "scripts/security_tools.py",
            "trivy",
            "image",
            "--scanners",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--exit-code",
            "1",
            "canvas-bridge:ci",
        ],
        "container_runtime": [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777",  # noqa: S108  # nosec B108
            "--mount",
            f"type=bind,src={root / '.local/linux-container-fixtures'},dst=/fixtures,readonly",
            "--mount",
            f"type=bind,src={root / 'scripts/verify_linux_container.py'},dst=/proof.py,readonly",
            "canvas-bridge:ci",
            ".venv/bin/python",
            "/proof.py",
            "verify",
            "/fixtures",
        ],
    }[check]


def python_findings(document, first_party):
    dependencies = document["dependencies"]
    if not dependencies:
        raise EvidenceError("EMPTY_DEPENDENCY_AUDIT")
    notes = ["INSTALLED_ENVIRONMENT_ONLY"]
    unknown = False
    for item in dependencies:
        if "skip_reason" in item:
            if item.get("name") == first_party[0] and item.get("version") in {None, first_party[1]}:
                notes.append("FIRST_PARTY_SOURCE_REVIEW_REQUIRED")
            else:
                unknown = True
    findings = sum(len(item.get("vulns", [])) for item in dependencies)
    advisories = sorted(
        {
            v["id"]
            for item in dependencies
            for v in item.get("vulns", [])
            if re.fullmatch(r"(?:CVE-[0-9-]+|GHSA-[a-z0-9-]+|PYSEC-[0-9-]+)", str(v.get("id", "")))
        }
    )[:200]
    return unknown, findings, advisories, sorted(set(notes))


def run_check(root, check, destination, stage):
    source = source_state(root)
    findings, status, advisories = None, "ERROR", []
    notes = []
    try:
        if check in {"secret_source", "container_config"}:
            from scripts.supply_chain import stage_source

            stage_source(root, stage / "source")
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            result = subprocess.run(  # noqa: S603
                command(check, stage, root),
                cwd=root,
                stdout=output,
                stderr=errors,
                timeout=600,
                check=False,
            )
            status = "PASSED" if result.returncode == 0 else "FAILED"
            if check in {"python_vulnerabilities", "node_vulnerabilities"}:
                output.seek(0)
                raw = output.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise EvidenceError("OVERSIZED_SCANNER_RESULT")
                document = json.loads(raw)
                if check == "python_vulnerabilities":
                    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
                        "project"
                    ]
                    if importlib.metadata.version(project["name"]) != project["version"]:
                        raise EvidenceError("FIRST_PARTY_INSTALLATION_MISMATCH")
                    unknown, findings, advisories, notes = python_findings(
                        document, (project["name"], project["version"])
                    )
                    if unknown:
                        status = "ERROR"
                else:
                    findings = int(document["metadata"]["vulnerabilities"]["total"])
                if findings:
                    status = "FAILED"
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        status = "ERROR"
    run = CheckRun(
        schema_version="check-run-1",
        source=source,
        finished_on=datetime.now(UTC).date(),
        source_unchanged=source_state(root).digest == source.digest,
        check=check,
        status=status,
        findings=findings,
        advisories=advisories,
        coverage_notes=notes,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(run.model_dump_json(indent=2) + "\n")
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=sorted(COMMAND_IDS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        Path(".local").mkdir(exist_ok=True)
        # Scanning/build artifacts remain ignored, outside the fingerprint scope.
        with tempfile.TemporaryDirectory(prefix="compliance-check-", dir=Path(".local")) as folder:
            result = run_check(Path.cwd(), args.check, args.output, Path(folder))
        print(
            json.dumps(
                {"check": result.check, "status": result.status, "findings": result.findings}
            )
        )
        raise SystemExit(0 if result.status == "PASSED" and result.source_unchanged else 1)
    except (EvidenceError, OSError, ValueError):
        print('{"status":"ERROR","reason":"CHECK_EVIDENCE_UNAVAILABLE"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
