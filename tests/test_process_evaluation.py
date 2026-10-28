"""CB-14 non-compensating safety gate and source-bound replay reporting."""

from datetime import date

from canvas_bridge.compliance.models import Counts, Source
from canvas_bridge.compliance.models import TestRun as Run
from canvas_bridge.processes.evaluation import evaluate_run


def receipt():
    cases = {
        f"tests/test_process_fixture.py::test_cb{i:02d}_acceptance": Counts(passed=1, collected=1)
        for i in range(1, 18)
    }
    return Run(
        schema_version="test-run-1",
        source=Source(commit=None, dirty=True, digest="a" * 64, files=1),
        finished_on=date(2030, 1, 1),
        source_unchanged=True,
        exit_code=0,
        interrupted=False,
        complete_selection=True,
        cases=cases,
        runtime="windows",
    )


def test_cb14_critical_safety_failure_blocks_even_when_other_cases_pass():
    run = receipt()
    key = "tests/test_process_fixture.py::test_cb07_acceptance"
    failed = run.model_copy(update={"cases": run.cases | {key: Counts(failed=1, collected=1)}})
    result = evaluate_run(failed, "a" * 64, set(run.cases))
    assert not result["passed"] and "PROCESS_REGRESSION" in result["blocking_reasons"]
    assert result["specifications"]["CB-07"]["passed"] == 0


def test_cb14_missing_skipped_or_stale_evidence_cannot_pass():
    run = receipt()
    assert evaluate_run(run, "a" * 64, set(run.cases))["passed"]
    assert not evaluate_run(run, "b" * 64, set(run.cases))["passed"]
    assert not evaluate_run(run.model_copy(update={"cases": {}}), "a" * 64, set(run.cases))[
        "passed"
    ]
    key = next(iter(run.cases))
    skipped = run.model_copy(update={"cases": run.cases | {key: Counts(skipped=1, collected=1)}})
    assert not evaluate_run(skipped, "a" * 64, set(run.cases))["passed"]


def test_cb14_does_not_claim_model_accuracy_or_deployment_from_unit_results():
    run = receipt()
    report = evaluate_run(run, "a" * 64, set(run.cases))
    assert report["model_interpretation_accuracy"] == "not_measured"
    assert report["deployment_acceptance"] == "not_established"
