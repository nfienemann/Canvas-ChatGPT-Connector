"""Fail-closed development readiness; this module never changes runtime permission."""

import hashlib
import html
import json
import re
import tomllib
from datetime import UTC, datetime, timedelta

from canvas_bridge.academic.contracts import SDK_VERSION
from canvas_bridge.compliance.inventory import (
    bounded_json,
    source_state,
    test_index,
    validate_repository,
)
from canvas_bridge.compliance.models import CheckRun, Counts, EvidenceError, TestRun, safe_text

TARGETS = ("offline_core", "institutional_pilot", "public_connected_plugin")


def dependency_inventory(root):
    python = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    node = bounded_json(root / "ui/page-reader/package-lock.json")
    packages = [
        {"ecosystem": "python", "name": p["name"], "version": p.get("version", "unresolved")}
        for p in python["package"]
    ]
    packages += [
        {
            "ecosystem": "node",
            "name": key.rsplit("node_modules/", 1)[-1] or node["name"],
            "version": p.get("version", "unresolved"),
        }
        for key, p in node["packages"].items()
    ]
    if any(
        not re.fullmatch(r"[A-Za-z0-9_@./+-]{1,150}", p[field])
        for p in packages
        for field in ("name", "version")
    ):
        raise EvidenceError("INVALID_DEPENDENCY_METADATA")
    return {
        "scope": "All locked groups/platforms; vulnerability checks separately cover the installed audit environment.",
        "packages": packages,
        "sbom_command": "uv export --locked --all-groups --format cyclonedx1.5; python scripts/supply_chain.py --python-sbom <export>",
    }


def current(receipt, source, today):
    return (
        receipt.source.digest == source.digest
        and receipt.source.commit == source.commit
        and receipt.source_unchanged
        and today - timedelta(days=7) <= receipt.finished_on <= today
    )


def approval_status(approval, today):
    if (
        approval.status in {"GRANTED", "RESTRICTED"}
        and approval.expires_on
        and approval.expires_on <= today
    ):
        return "EXPIRED"
    return approval.status


def generate(root, category="synthetic_demo", *, results=None, checks=None, today=None):
    today = today or datetime.now(UTC).date()
    registry = validate_repository(root)
    source = source_state(root)
    known = test_index(root)
    run = TestRun.model_validate(bounded_json(results)) if results and results.exists() else None
    if run and (set(run.cases) - known):
        raise EvidenceError("UNKNOWN_RECORDED_TEST")
    runs = {}
    if checks:
        for path in sorted(checks.glob("*.json")):
            receipt = CheckRun.model_validate(bounded_json(path))
            if receipt.check not in registry.required_checks or receipt.check in runs:
                raise EvidenceError("UNKNOWN_OR_DUPLICATE_CHECK_RECEIPT")
            runs[receipt.check] = receipt
    fresh = run is not None and current(run, source, today)
    outcomes = {}
    for check in registry.required_checks:
        receipt = runs.get(check)
        outcomes[check] = {
            "status": "NOT_RUN"
            if not receipt
            else "STALE"
            if not current(receipt, source, today)
            else receipt.status,
            "findings": receipt.findings if receipt else None,
            "advisories": receipt.advisories if receipt else [],
            "coverage_notes": receipt.coverage_notes if receipt else [],
        }
    tests = {
        "status": "NOT_RUN"
        if not run
        else "STALE"
        if not fresh
        else "PASSED"
        if run.exit_code == 0
        and not run.interrupted
        and run.cases
        and not any(c.failed or c.error for c in run.cases.values())
        else "FAILED",
        "finished_on": run.finished_on.isoformat() if run else None,
        "runtime": run.runtime if run else None,
        "complete_selection": run.complete_selection if run else False,
        "totals": {
            name: sum(getattr(c, name) for c in run.cases.values()) if run else 0
            for name in Counts.model_fields
        },
        "cases": {name: counts.model_dump() for name, counts in run.cases.items()} if run else {},
    }
    controls = []
    regressions = []
    for incident in registry.operational_regressions:
        names = {
            name
            for ref in incident.tests
            for name in known
            if name == ref or name.startswith(ref + "::")
        }
        verified = (
            bool(names)
            and fresh
            and tests["status"] == "PASSED"
            and all(run.cases.get(name, Counts()).verified() for name in names)
        )
        regressions.append(
            {
                **incident.model_dump(mode="json"),
                "status": "TESTED" if verified else "IMPLEMENTED_UNVERIFIED",
                "verification_scope": "Source-bound automated fixtures only; production incident diagnosis is not inferred.",
            }
        )
    from canvas_bridge.source_authorization import registered_inventory

    tool_inventory = registered_inventory()
    for control in registry.controls:
        expected = {
            name
            for ref in control.tests
            for name in known
            if name == ref or name.startswith(ref + "::")
        }
        verified = (
            bool(expected or control.checks)
            and tests["status"] == "PASSED"
            and run.complete_selection
            and all(run.cases.get(name, Counts()).verified() for name in expected)
            and all(outcomes[name]["status"] == "PASSED" for name in control.checks)
        )
        status = control.status
        if status in {"TESTED", "IMPLEMENTED_UNVERIFIED"}:
            status = "TESTED" if verified else "IMPLEMENTED_UNVERIFIED"
        controls.append(
            {
                **control.model_dump(mode="json"),
                "declared_status": control.status,
                "status": status,
                "verification_basis": "current_source_bound_execution"
                if verified
                else "not_established",
            }
        )
    stale_policies = [p.id for p in registry.policies if not p.reviewed_on <= today <= p.review_due]
    gates = {}
    for target in TARGETS:
        blockers = []
        if source.dirty:
            blockers.append("SOURCE_NOT_COMMITTED")
        for control in controls:
            if target in control["targets"] and control["status"] not in {
                "TESTED",
                "NOT_APPLICABLE",
                "REQUIRES_EXTERNAL_APPROVAL",
            }:
                blockers.append("CONTROL:" + control["id"])
        for name, result in outcomes.items():
            if target == "offline_core" and name in {"container_image", "container_runtime"}:
                continue  # The offline artifact still needs its own manual security review.
            if result["status"] != "PASSED":
                blockers.append("CHECK:" + name + ":" + result["status"])
        for review in registry.manual_reviews:
            if target in review.targets and not (
                review.status == "ACCEPTED"
                and review.evidence_reference
                and review.source_digest == source.digest
                and review.expires_on
                and review.expires_on > today
            ):
                blockers.append("MANUAL_REVIEW:" + review.id)
        scope = hashlib.sha256((target + ":" + source.digest).encode()).hexdigest()
        for approval in registry.approvals:
            if target in approval.targets and not (
                approval.status == "GRANTED"
                and approval.verified
                and approval.evidence_reference
                and approval.effective_on
                and approval.expires_on
                and approval.effective_on <= today < approval.expires_on
                and approval.scope_digest == scope
                and not approval.conditions
            ):
                blockers.append("APPROVAL:" + approval.id + ":" + approval_status(approval, today))
        if target != "offline_core":
            blockers.extend("POLICY_REVIEW_OVERDUE:" + name for name in stale_policies)
        gates[target] = {
            "status": "BLOCKED" if blockers else "READY_FOR_AUTHORIZED_RELEASE_REVIEW",
            "scope_digest": scope,
            "blockers": blockers,
            "decision_authority": "Human release owners and external approvers; this report grants nothing.",
        }
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    result = {
        "schema_version": "compliance-report-1",
        "application_version": version,
        "evaluated_on": today.isoformat(),
        "source": source.model_dump(),
        "registry_sha256": hashlib.sha256(registry.model_dump_json().encode()).hexdigest(),
        "assurance": "Developer execution receipts, not independently signed audit evidence or legal compliance.",
        "deployment": {
            "category": category,
            "basis": "operator_declared_review_category",
            "runtime_configuration_inspected": False,
        },
        "provider_capabilities": {
            "provider_api_version": SDK_VERSION,
            "offline_academic": [
                "synthetic_grade_calculation",
                "explicit_local_document_text",
                "local_numeric_grades",
                "aggregate_grade_forecast",
            ],
            "extensions": {
                "sdk_version": SDK_VERSION,
                "projections": ["grade_points_v1"],
                "native_code": "unsupported",
                "registration_grants_permission": False,
            },
            "authorized_canvas": {
                "implemented_adapter": ["get_grade_summary"],
                "live_activation": "NOT_ATTESTED",
                "requires": ["provider", "institution", "user", "recipient"],
            },
            "future_approved_mcp": {"enabled": False, "capabilities": []},
            "note": "Available implementation is not permission or a claim about a deployed service. Report generation enables no provider.",
        },
        "controls": controls,
        "mcp_capability_inventory": tool_inventory,
        "operational_regressions": regressions,
        "tests": tests,
        "dependency_and_security_checks": outcomes,
        "dependency_inventory": dependency_inventory(root),
        "approvals": [
            {
                **a.model_dump(mode="json"),
                "registered_status": a.status,
                "status": approval_status(a, today),
            }
            for a in registry.approvals
        ],
        "manual_reviews": [r.model_dump(mode="json") for r in registry.manual_reviews],
        "policy_mapping": [p.model_dump(mode="json") for p in registry.policies],
        "review_templates": registry.templates,
        "data_flow": registry.data_flow,
        "known_limitations": registry.limitations,
        "release_gates": gates,
        "development_readiness": "TECHNICAL_CHECKS_PASSED"
        if tests["status"] == "PASSED"
        and all(r["status"] == "PASSED" for r in outcomes.values())
        and all(
            c["status"] in {"TESTED", "REQUIRES_EXTERNAL_APPROVAL", "NOT_APPLICABLE"}
            for c in controls
        )
        else "INCOMPLETE_OR_FAILED_TECHNICAL_EVIDENCE",
        "legal_compliance_determination": "NOT_MADE",
    }
    safe_text(result)
    return result


def md(value):
    return html.escape(str(value)).replace("|", "\\|").replace("\n", " ")


def markdown(report):
    lines = [
        "# Canvas Bridge security and governance evidence",
        "",
        "**This is technical evidence, not legal, institutional, provider or platform approval.**",
        "",
    ]
    lines.extend(
        [
            f"Version: {md(report['application_version'])}; commit: `{report['source']['commit']}`; dirty: {report['source']['dirty']}.",
            f"Source snapshot: `{report['source']['digest']}`. Evaluated: {report['evaluated_on']}.",
            f"Review category: {report['deployment']['category']}; deployed configuration was not inspected.",
            "",
            "## Release blockers and outstanding approvals",
            "",
        ]
    )
    for target, gate in report["release_gates"].items():
        lines += [
            f"### {target}: {gate['status']}",
            "",
            *["- " + md(b) for b in gate["blockers"]],
            "",
        ]
    for approval in report["approvals"]:
        lines.append(
            f"- **{approval['id']}: {approval['status']}** — {md(approval['party'])}: {md(approval['requirement'])}"
        )
    lines += [
        "",
        "## Control inventory",
        "",
        "| ID | Status | Objective / enforcement | Verification / residual limitation |",
        "|---|---|---|---|",
    ]
    for control in report["controls"]:
        lines.append(
            f"| {control['id']} | {control['status']} | {md(control['objective'])}; {md(', '.join(control['enforcement']))} | {md(control['automated_scope'])}; manual: {md(control['manual_verification'])}; limitation: {md(control['residual_limitation'])} |"
        )
    lines += [
        "",
        "## Executed verification",
        "",
        f"Tests: **{report['tests']['status']}**; totals: `{json.dumps(report['tests']['totals'], sort_keys=True)}`.",
        "",
        "Source-bound cases and complete control metadata are in report.json. Counts describe the supplied run, not historical logs.",
        "",
    ]
    for check, outcome in report["dependency_and_security_checks"].items():
        lines.append(
            f"- {check}: {outcome['status']}; findings: {outcome['findings'] if outcome['findings'] is not None else 'not enumerated'}"
        )
    lines += [
        "",
        "## Operational regressions",
        "",
        "Verification applies to fictional fixtures; historical production root causes remain unverified unless stated.",
        "",
    ]
    for incident in report["operational_regressions"]:
        lines += [
            f"- {incident['id']}: **{incident['status']}**. {md(incident['root_cause'])} Boundary: {md(incident['security_boundary'])}. Remediation: {md(incident['remediation'])}. Remaining: {md(incident['residual_uncertainty'])}."
        ]
    lines += [
        "",
        "## Registered MCP contracts",
        "",
        "Generated from the actual tool registry in an ephemeral synthetic configuration. Schemas and widget references are in report.json. Write tools are omitted by the read-only deployment configuration.",
        "",
        "| Tool | Source authority | LMS network possible | Offline |",
        "|---|---|---|---|",
    ]
    for tool in report["mcp_capability_inventory"]:
        lines.append(
            f"| {tool['name']} | {md(', '.join(tool['authorization']))} | {tool['upstream_network']} | {tool['offline_supported']} |"
        )
    for heading, key in (("Data flow", "data_flow"), ("Known limitations", "known_limitations")):
        lines += ["", "## " + heading, "", *["- " + md(item) for item in report[key]]]
    lines += [
        "",
        "## Policy mapping",
        "",
        "Mappings are technical interpretations for review, not legal determinations. Updating a mapping never changes runtime grants.",
        "",
    ]
    for policy in report["policy_mapping"]:
        lines.append(
            f"- [{md(policy['title'])}]({policy['url']}): sections {md(', '.join(policy['sections']))}; effective date {policy['effective_date'] or 'not stated'} ({md(policy['effective_date_note'])}); revision {md(policy['revision'])}; reviewed {policy['reviewed_on']}; next review {policy['review_due']}. {md(policy['interpretation'])}"
        )
    lines += [
        "",
        "## Provider capabilities",
        "",
        md(json.dumps(report["provider_capabilities"], sort_keys=True)),
        "",
        "## Review documents",
        "",
    ]
    lines += [
        f"- {md(name)}: `{path}` (repository template, UNVERIFIED until completed)."
        for name, path in report["review_templates"].items()
    ]
    lines += ["", report["assurance"], ""]
    return "\n".join(lines)


def write_report(report, output):
    # New directories only: no accidental overwrite of an earlier signed review.
    if output.exists() or output.is_symlink():
        raise EvidenceError("NEW_REPORT_DIRECTORY_REQUIRED")
    output.mkdir(parents=True, mode=0o700)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
