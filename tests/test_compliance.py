"""Evidence must be factual, bounded, source-bound, and unable to grant permission."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from canvas_bridge.compliance.cli import run
from canvas_bridge.compliance.inventory import (
    bounded_json,
    safe_path,
    source_state,
    validate_repository,
)
from canvas_bridge.compliance.inventory import (
    test_index as index_tests,
)
from canvas_bridge.compliance.models import CheckRun, Counts, EvidenceError, Registry
from canvas_bridge.compliance.models import TestRun as EvidenceRun
from canvas_bridge.compliance.pytest_plugin import Recorder
from canvas_bridge.compliance.report import generate, markdown, write_report


@pytest.fixture
def root():
    return Path.cwd()


def passing_claims(root, tmp_path):
    """Fabricated unit-test receipts; never used as real project verification."""
    source = source_state(root)
    now = datetime.now(UTC).date()
    receipt = EvidenceRun(
        schema_version="test-run-1",
        source=source,
        finished_on=now,
        source_unchanged=True,
        exit_code=0,
        interrupted=False,
        complete_selection=True,
        runtime="other",
        cases={name: Counts(passed=1, collected=1) for name in index_tests(root)},
    )
    tests = tmp_path / "tests.json"
    tests.write_text(receipt.model_dump_json(), encoding="utf-8")
    checks = tmp_path / "checks"
    checks.mkdir()
    for name in validate_repository(root).required_checks:
        check = CheckRun(
            schema_version="check-run-1",
            source=source,
            finished_on=now,
            source_unchanged=True,
            check=name,
            status="PASSED",
            findings=0,
        )
        (checks / (name + ".json")).write_text(check.model_dump_json(), encoding="utf-8")
    return tests, checks


def test_registry_covers_required_documents_and_explicit_approval_parties(root):
    registry = validate_repository(root)
    assert len(registry.templates) == 15
    assert len(registry.controls) >= 18
    assert all(a.status == "MISSING" for a in registry.approvals)
    assert all(c.status != "TESTED" for c in registry.controls)


def test_files_alone_never_mean_tested_or_releasable(root):
    report = generate(root)
    assert report["tests"]["status"] == "NOT_RUN"
    assert all(c["status"] != "TESTED" for c in report["controls"])
    assert all(gate["status"] == "BLOCKED" for gate in report["release_gates"].values())
    assert report["legal_compliance_determination"] == "NOT_MADE"


def test_passing_code_checks_cannot_clear_missing_approvals(root, tmp_path):
    tests, checks = passing_claims(root, tmp_path)
    report = generate(root, results=tests, checks=checks)
    assert any(c["status"] == "TESTED" for c in report["controls"])
    for gate in report["release_gates"].values():
        assert gate["status"] == "BLOCKED"
        assert any(item.startswith("MANUAL_REVIEW:") for item in gate["blockers"])
    assert (
        "APPROVAL:APR-PROVIDER:MISSING"
        in report["release_gates"]["institutional_pilot"]["blockers"]
    )
    assert (
        "APPROVAL:APR-PROVIDER:MISSING" not in report["release_gates"]["offline_core"]["blockers"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_source",
        "future_date",
        "old_date",
        "failed",
        "interrupted",
        "skipped",
        "missing_case",
        "changed_during_run",
    ],
)
def test_stale_partial_skipped_or_failed_runs_cannot_promote_controls(root, tmp_path, mutation):
    tests, checks = passing_claims(root, tmp_path)
    data = bounded_json(tests)
    case = next(
        name for name in data["cases"] if name.startswith("tests/test_approval_policy.py::")
    )
    if mutation == "stale_source":
        data["source"]["digest"] = "0" * 64
    elif mutation in {"future_date", "old_date"}:
        delta = 1 if mutation == "future_date" else -8
        data["finished_on"] = (datetime.now(UTC).date() + timedelta(days=delta)).isoformat()
    elif mutation == "failed":
        data["exit_code"] = 1
    elif mutation == "interrupted":
        data["interrupted"] = True
    elif mutation == "changed_during_run":
        data["source_unchanged"] = False
    elif mutation == "missing_case":
        del data["cases"][case]
    else:
        data["cases"][case] = {"collected": 1, "skipped": 1}
    tests.write_text(json.dumps(data), encoding="utf-8")
    report = generate(root, results=tests, checks=checks)
    control = next(c for c in report["controls"] if c["id"] == "CB-AUTH-01")
    assert control["status"] == "IMPLEMENTED_UNVERIFIED"


def test_report_is_reproducible_and_does_not_load_settings(root, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Evidence generation touched live settings")

    monkeypatch.setattr("canvas_bridge.config.Settings.__init__", forbidden)
    monkeypatch.setenv("BRIDGE_ACCESS_TOKEN", "private-canary-do-not-export")
    first = generate(root)
    assert first == generate(root)
    assert "private-canary-do-not-export" not in json.dumps(first)
    output = tmp_path / "public"
    write_report(first, output)
    assert "NOT_MADE" in (output / "report.json").read_text(encoding="utf-8")
    with pytest.raises(EvidenceError):
        write_report(first, output)


def test_unknown_private_evidence_fields_are_rejected_without_echo(root, tmp_path, capsys):
    evidence = tmp_path / "private.json"
    evidence.write_text(
        json.dumps({"raw_authentication_log": "protected-student-canary"}), encoding="utf-8"
    )
    args = SimpleNamespace(
        repository=root,
        category="synthetic_demo",
        results=evidence,
        checks=None,
        output=tmp_path / "out",
        validate_only=False,
        require_technical=False,
        enforce_release=None,
    )
    assert run(args) == 1
    assert "protected-student-canary" not in capsys.readouterr().out
    assert not args.output.exists()


def test_sensitive_registry_correspondence_is_not_an_approval_export(root):
    registry = bounded_json(root / "governance/controls.json")
    registry["approvals"][0]["correspondence"] = "Confidential evidence"
    with pytest.raises(ValidationError):
        Registry.model_validate(registry)
    del registry["approvals"][0]["correspondence"]
    registry["approvals"][0]["requirement"] = "access_token=synthetic-private-canary"
    with pytest.raises((ValueError, EvidenceError)):
        Registry.model_validate(registry)


def test_recorder_omits_parameters_messages_stdout_and_teardown_errors_override_pass(
    root, tmp_path
):
    recorder = Recorder(root, tmp_path / "outcomes.json")
    base = "tests/test_compliance.py::test_files_alone_never_mean_tested_or_releasable"
    node = base + "[protected-student-canary]"
    recorder.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=node)]))
    recorder.pytest_runtest_logreport(
        SimpleNamespace(nodeid=node, when="call", passed=True, failed=False, skipped=False)
    )
    recorder.pytest_runtest_logreport(
        SimpleNamespace(
            nodeid=node,
            when="teardown",
            passed=False,
            failed=True,
            skipped=False,
            longrepr="private-log-canary",
        )
    )
    recorder.pytest_sessionfinish(None, 1)
    text = recorder.destination.read_text(encoding="utf-8")
    assert "canary" not in text
    result = json.loads(text)
    assert result["cases"][base]["error"] == 1
    assert result["cases"][base]["passed"] == 0


def test_expired_and_restricted_claims_remain_blocked(root, monkeypatch):
    registry = validate_repository(root)
    for approval in registry.approvals:
        approval.status = "GRANTED"
        approval.verified = True
        approval.evidence_reference = "SYNTHETIC-EVIDENCE"
        approval.effective_on = datetime.now(UTC).date() - timedelta(days=2)
        approval.expires_on = datetime.now(UTC).date() - timedelta(days=1)
        approval.scope_digest = "0" * 64
    monkeypatch.setattr(
        "canvas_bridge.compliance.report.validate_repository", lambda root: registry
    )
    report = generate(root)
    assert any(
        b.startswith("APPROVAL:APR-PROVIDER:")
        for b in report["release_gates"]["institutional_pilot"]["blockers"]
    )
    assert report["approvals"][0]["status"] == "EXPIRED"
    registry.approvals[0].status = "RESTRICTED"
    registry.approvals[0].expires_on = datetime.now(UTC).date() + timedelta(days=1)
    assert (
        "APPROVAL:APR-PROVIDER:RESTRICTED"
        in generate(root)["release_gates"]["institutional_pilot"]["blockers"]
    )


def test_repository_references_cannot_escape_or_follow_links(tmp_path):
    with pytest.raises(EvidenceError):
        safe_path(tmp_path, "../private.env")
    with pytest.raises(EvidenceError):
        safe_path(tmp_path, "C:/private.env")


def test_release_gate_exit_code_stays_failed_while_report_is_written(root, tmp_path):
    args = SimpleNamespace(
        repository=root,
        category="offline_core",
        results=None,
        checks=None,
        output=tmp_path / "out",
        validate_only=False,
        require_technical=False,
        enforce_release="offline_core",
    )
    assert run(args) == 2
    assert (args.output / "report.json").is_file()


def test_markdown_retains_blockers_and_does_not_claim_legal_compliance(root):
    text = markdown(generate(root))
    assert "APR-PROVIDER: MISSING" in text
    assert "offline_core: BLOCKED" in text
    assert "not legal" in text


def test_unknown_test_ids_in_imported_results_fail_closed(root, tmp_path):
    tests, checks = passing_claims(root, tmp_path)
    data = bounded_json(tests)
    data["cases"]["private/student-record"] = {"passed": 1, "collected": 1}
    tests.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EvidenceError):
        generate(root, results=tests, checks=checks)


def test_missing_result_file_generates_incomplete_report_for_failed_ci(root, tmp_path):
    result = generate(root, results=tmp_path / "never-created.json")
    assert result["tests"]["status"] == "NOT_RUN"


def test_filtered_parameter_run_cannot_certify_full_control(root, tmp_path):
    tests, checks = passing_claims(root, tmp_path)
    data = bounded_json(tests)
    data["complete_selection"] = False
    tests.write_text(json.dumps(data), encoding="utf-8")
    report = generate(root, results=tests, checks=checks)
    assert report["tests"]["status"] == "PASSED"
    assert all(c["status"] != "TESTED" for c in report["controls"])
    recorder = Recorder(root, tmp_path / "filtered.json", complete_selection=True)
    recorder.pytest_deselected([object()])
    assert not recorder.complete_selection


def test_declared_tested_status_requires_execution_not_registry_assertion(root, monkeypatch):
    registry = validate_repository(root)
    registry.controls[0].status = "TESTED"
    monkeypatch.setattr(
        "canvas_bridge.compliance.report.validate_repository", lambda root: registry
    )
    assert generate(root)["controls"][0]["status"] == "IMPLEMENTED_UNVERIFIED"


def test_registry_broken_references_and_fixture_changes_are_rejected(root, monkeypatch, tmp_path):
    from canvas_bridge.compliance.inventory import validate_fixtures

    registry = bounded_json(root / "governance/controls.json")
    registry["controls"][0]["enforcement"] = ["src/canvas_bridge/missing.py"]
    original = bounded_json
    monkeypatch.setattr(
        "canvas_bridge.compliance.inventory.bounded_json",
        lambda path: registry if path.name == "controls.json" else original(path),
    )
    with pytest.raises(EvidenceError, match="MISSING_ENFORCEMENT"):
        validate_repository(root)
    monkeypatch.setattr("canvas_bridge.compliance.inventory.bounded_json", original)
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance/fixtures.json").write_text(
        json.dumps(
            {
                "schema_version": "fictional-fixtures-1",
                "origin": "generated-fictional-only",
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    fixture = tmp_path / "tests/fixtures/unreviewed.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fictional_canary":"not approved as fixture"}', encoding="utf-8")
    monkeypatch.setattr(
        "canvas_bridge.compliance.inventory.git", lambda *args: "tests/fixtures/unreviewed.json\0"
    )
    with pytest.raises(EvidenceError, match="UNREVIEWED"):
        validate_fixtures(tmp_path)


def test_positive_vulnerability_findings_cannot_be_labeled_passed(root):
    with pytest.raises(ValidationError):
        CheckRun(
            schema_version="check-run-1",
            source=source_state(root),
            finished_on=datetime.now(UTC).date(),
            source_unchanged=True,
            check="python_vulnerabilities",
            status="PASSED",
            findings=1,
        )


def test_dependency_audit_distinguishes_own_source_from_unknown_third_party():
    from canvas_bridge.compliance.checks import python_findings

    own = {"name": "canvas-bridge", "version": "0.1.0", "skip_reason": "Unpublished local project"}
    clean = {"name": "fictional-dependency", "version": "1.0", "vulns": []}
    result = python_findings({"dependencies": [own, clean]}, ("canvas-bridge", "0.1.0"))
    assert result[:3] == (False, 0, [])
    assert "FIRST_PARTY_SOURCE_REVIEW_REQUIRED" in result[3]
    without_version = {key: value for key, value in own.items() if key != "version"}
    assert not python_findings(
        {"dependencies": [without_version, clean]}, ("canvas-bridge", "0.1.0")
    )[0]
    unknown = {"name": "unknown-package", "version": "1", "skip_reason": "No advisory data"}
    assert python_findings({"dependencies": [own, unknown]}, ("canvas-bridge", "0.1.0"))[0]
    assert python_findings({"dependencies": [own]}, ("canvas-bridge", "0.2.0"))[0]
    with pytest.raises(EvidenceError):
        python_findings({"dependencies": []}, ("canvas-bridge", "0.1.0"))


def test_failed_or_stale_security_check_stays_release_blocking(root, tmp_path):
    tests, checks = passing_claims(root, tmp_path)
    path = checks / "python_vulnerabilities.json"
    data = bounded_json(path)
    data.update(status="FAILED", findings=2, advisories=["CVE-2026-99999"])
    path.write_text(json.dumps(data), encoding="utf-8")
    report = generate(root, results=tests, checks=checks)
    assert report["dependency_and_security_checks"]["python_vulnerabilities"]["findings"] == 2
    assert (
        "CHECK:python_vulnerabilities:FAILED" in report["release_gates"]["offline_core"]["blockers"]
    )
    data.update(status="PASSED", findings=0, advisories=[])
    data["source"]["digest"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    assert (
        generate(root, results=tests, checks=checks)["dependency_and_security_checks"][
            "python_vulnerabilities"
        ]["status"]
        == "STALE"
    )
