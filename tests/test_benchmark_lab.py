"""Gold independence, real academic workflows, adversarial scoring and release gates."""

import json
import shutil
import socket
from copy import deepcopy
from pathlib import Path

import pytest

from canvas_bridge.benchmark_lab import SCHEMA
from canvas_bridge.benchmark_lab.adapters import execute
from canvas_bridge.benchmark_lab.dataset import CATEGORIES, Corpus, digest, read_json
from canvas_bridge.benchmark_lab.evaluate import compare, evaluate, verify_gold
from canvas_bridge.benchmark_lab.oracle import rational
from canvas_bridge.benchmark_lab.runner import envelope, imported, run, save

CORPUS_PATH = Path(__file__).resolve().parents[1] / "benchmarks/academic/v1"


@pytest.fixture
def corpus():
    return Corpus(CORPUS_PATH)


def task(corpus, ident="grade-mat101"):
    return next(t for t in corpus.scenarios if t["id"] == ident)


@pytest.mark.parametrize(
    "ident", [t["id"] for t in read_json(CORPUS_PATH / "scenarios.json") if t["tier"] == "fast"]
)
async def test_real_workflows_against_independent_gold(corpus, ident):
    item = task(corpus, ident)
    observation = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    result = evaluate(item, observation, corpus)
    assert result["state"] == "passed", result


def test_corpus_has_required_courses_categories_assets_and_independent_calculations(corpus):
    assert len(corpus.data["courses"]) >= 12
    assert {t["category"] for t in corpus.scenarios} == set(CATEGORIES)
    assert corpus.manifest["synthetic"] is True
    verify_gold(corpus)
    assert rational("(80+45)/150*100").numerator == 250
    assert rational("(80+45)/150*100").denominator == 3
    for suffix in ("pdf", "pptx"):
        assert (corpus.path / f"assets/scientific-lecture.{suffix}").stat().st_size > 20_000


def test_gold_rebuild_is_byte_stable_across_checkout_line_endings(corpus, tmp_path, monkeypatch):
    from scripts import build_academic_benchmarks

    destination = tmp_path / "v1"
    shutil.copytree(corpus.path / "assets", destination / "assets")
    monkeypatch.setattr(build_academic_benchmarks, "ROOT", destination)
    build_academic_benchmarks.build()
    rebuilt = Corpus(destination)
    assert rebuilt.fingerprint == corpus.fingerprint
    for filename in (
        "dataset.json",
        "gold.json",
        "scenarios.json",
        "rubrics.json",
        "manifest.json",
    ):
        assert b"\r\n" not in (destination / filename).read_bytes()


@pytest.mark.parametrize(
    "formula", ["__import__('os').system('bad')", "2 ** 1000000", "True+1", "1/0", "[1,2]", "a+1"]
)
def test_oracle_never_executes_formula_code(formula):
    with pytest.raises((ValueError, ZeroDivisionError)):
        rational(formula)


def test_hash_bound_corpus_rejects_changed_gold_and_media(corpus, tmp_path):
    destination = tmp_path / "corpus"
    shutil.copytree(corpus.path, destination)
    (destination / "gold.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        Corpus(destination)


def test_no_gold_or_peer_payload_in_model_export(corpus):
    export = corpus.export()
    text = json.dumps(export)
    assert "required_evidence" not in text and "success_conditions" not in text
    assert "PEER_PRIVATE_CANARY" not in text
    assert "privacy-known-self" not in text
    assert all(s["authorized"] for t in export["tasks"] for s in t["sources"])


async def test_mutated_production_calculator_cannot_define_its_own_gold(corpus, monkeypatch):
    from canvas_bridge.academic import grade_engine

    original = grade_engine.calculate

    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        result["calculated_percentage"] = "99.0000"
        return result

    monkeypatch.setattr(grade_engine, "calculate", broken)
    item = task(corpus)
    observation = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    result = evaluate(item, observation, corpus)
    assert result["state"] == "failed"
    assert "faulty_calculation" in result["failures"]


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("wrong_number", "faulty_calculation"),
        ("wrong_hash", "stale_information"),
        ("wrong_locator", "presentation_or_citation_failure"),
        ("wrong_url", "presentation_or_citation_failure"),
        ("missing_citation", "presentation_or_citation_failure"),
        ("extra_claim", "unsupported_inference"),
        ("mutation_tool", "authorization_failure"),
        ("peer_disclosure", "authorization_failure"),
        ("missing_operation", "tool_orchestration_failure"),
        ("failed_operation", "tool_orchestration_failure"),
    ],
)
async def test_adversarial_answers_cannot_pass(corpus, mutation, expected):
    item = task(corpus)
    observed = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    if mutation == "wrong_number":
        observed["answer"]["percentage"] = "99"
    if mutation == "wrong_hash":
        observed["evidence"]["percentage"][0]["sha256"] = "0" * 64
    if mutation == "wrong_locator":
        observed["evidence"]["percentage"][0]["locator"] = "invented page 200"
    if mutation == "wrong_url":
        observed["evidence"]["percentage"][0]["uri"] = "https://wrong.invalid/source"
    if mutation == "missing_citation":
        observed["evidence"] = {}
    if mutation == "extra_claim":
        observed["answer"]["instructor_error_confirmed"] = True
    if mutation == "mutation_tool":
        observed["operations"].append({"name": "edit_grade", "method": "POST"})
    if mutation == "peer_disclosure":
        observed["response_text"] = "PEER_PRIVATE_CANARY"
    if mutation == "missing_operation":
        observed["operations"] = []
    if mutation == "failed_operation":
        observed["operations"][0]["success"] = False
    result = evaluate(item, observed, corpus)
    assert result["state"] == "failed" and expected in result["failures"]


async def test_missing_uncertainty_and_unreviewed_prose_never_pass(corpus):
    item = task(corpus, "grade-phy220")
    observed = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    observed["uncertainty"] = []
    assert "incomplete_source_coverage" in evaluate(item, observed, corpus)["failures"]
    item = task(corpus)
    observed = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    observed["response_text"] = (
        "An additional free-form claim that deterministic fields do not judge."
    )
    assert evaluate(item, observed, corpus)["state"] == "review_required"


async def test_full_run_separates_visual_review_from_text_extraction(corpus, tmp_path):
    report = await run(corpus, tier="full")
    assert report["gate"] == {
        "objective_pass": True,
        "critical_pass": True,
        "review_complete": False,
    }
    pending = [r["scenario_id"] for r in report["results"] if r["state"] == "review_required"]
    assert pending == ["interpret-figure-pdf", "interpret-figure-pptx"]
    assert report["metrics"]["confidence_intervals"] is None
    assert report["metrics"]["categories"]["figure_interpretation"]["exact_answer_accuracy"] is None
    assert report["metrics"]["operational"]["network_requests"]["total"] == 0
    save(report, corpus, tmp_path)
    assert "review_required" in (tmp_path / "report.md").read_text(encoding="utf-8")


async def test_network_attempt_is_blocked_and_fails_closed(corpus, monkeypatch):
    async def malicious(*args):
        socket.getaddrinfo("university.benchmark.invalid", 443)

    monkeypatch.setattr("canvas_bridge.benchmark_lab.runner.bounded_execute", malicious)
    monkeypatch.setattr(corpus, "tasks", lambda tier: [task(corpus)])
    report = await run(corpus)
    assert not report["gate"]["critical_pass"]
    assert report["observations"]["grade-mat101"]["network_requests"] == 1
    assert "authorization_failure" in report["results"][0]["failures"]


async def test_changed_code_during_run_cannot_certify_revision(corpus, monkeypatch):
    calls = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr("canvas_bridge.benchmark_lab.runner.code_fingerprint", lambda: next(calls))
    monkeypatch.setattr(corpus, "tasks", lambda tier: [task(corpus)])
    report = await run(corpus)
    assert not report["gate"]["objective_pass"]
    assert not report["system"]["source_stable"]


async def test_regression_cannot_be_offset_by_improvement_and_has_capsule(corpus, tmp_path):
    items = [task(corpus), task(corpus, "grade-bio201")]
    observations = {
        t["id"]: await execute(t, corpus.sources, corpus.path, corpus.data["clock"]) for t in items
    }
    system = {"id": "fixture", "kind": "bridge_backend", "measurement_scope": "backend_workflow"}
    current = envelope(corpus, items, observations, system, "all")
    baseline = deepcopy(current)
    baseline["results"][1]["state"] = "failed"
    current["results"][0]["state"] = "failed"
    current["results"][0]["failures"] = ["faulty_calculation"]
    comparison = compare(current, baseline)
    assert comparison["regressions"] == [items[0]["id"]]
    assert comparison["improvements"] == [items[1]["id"]]
    assert not comparison["release_pass"]
    save(current, corpus, tmp_path)
    capsule = read_json(tmp_path / "failures" / current["run_id"] / (items[0]["id"] + ".json"))
    assert capsule["gold"] == corpus.gold[items[0]["id"]]
    assert capsule["sources"] and capsule["observation"]
    baseline["corpus_sha256"] = "other"
    with pytest.raises(ValueError, match="identical corpus"):
        compare(current, baseline)


async def test_imported_baseline_requires_real_provenance_and_no_specialized_tools(
    corpus, tmp_path
):
    item = task(corpus)
    observation = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    observation.pop("trace")
    observation["operations"] = [{"name": "model_reasoning", "scope": "model", "success": True}]
    candidate = {
        "schema": SCHEMA,
        "corpus_sha256": corpus.fingerprint,
        "system": {
            "id": "fictional-test-model",
            "kind": "normalized_model",
            "version_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "measurement_scope": "model_end_to_end",
            "run_receipt": "synthetic-test-only-not-real-model-evidence",
            "input_export_sha256": digest(corpus.export("fast")),
        },
        "observations": [observation],
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    result = imported(corpus, path, tier="fast")
    assert result["results"][0]["state"] == "passed"
    assert not result["gate"]["objective_pass"]  # Missing tasks count as failures.
    candidate["observations"][0]["tool_calls"] = 1
    path.write_text(json.dumps(candidate), encoding="utf-8")
    result = imported(corpus, path, tier="fast")
    assert "authorization_failure" in result["results"][0]["failures"]
    candidate["system"]["kind"] = "alternative_tools"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="actual installation"):
        imported(corpus, path, tier="fast")
    candidate["system"].pop("run_receipt")
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        imported(corpus, path, tier="fast")


async def test_model_cannot_approve_its_own_interpretive_rubric(corpus):
    item = task(corpus, "interpret-figure-pdf")
    observation = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    rubric = corpus.rubrics[item["rubric"]]
    review = {
        "scenario_id": item["id"],
        "reviewer_kind": "model",
        "reviewer_id": "model-under-test",
        "observation_sha256": digest(observation),
        "corpus_sha256": corpus.fingerprint,
        "rubric_sha256": digest(rubric),
        "expertise": "claimed",
        "reviewed_at": "2030-10-21T12:00:00Z",
        "review_record": "fictional",
        "dimensions": {d["id"]: "pass" for d in rubric["dimensions"]},
    }
    assert (
        evaluate(item, observation, corpus, reviews=[review], system_id="model-under-test")["state"]
        == "review_required"
    )


def test_duplicate_json_keys_and_nonfinite_values_are_rejected(tmp_path):
    path = tmp_path / "bad.json"
    for text in ('{"x":1,"x":2}', '{"x":NaN}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            read_json(path)


def test_cli_exports_only_input_packet_and_requires_real_baseline(corpus, tmp_path, monkeypatch):
    from canvas_bridge.benchmark_lab.__main__ import main

    output = tmp_path / "packet/tasks.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark",
            "export",
            "--corpus",
            str(corpus.path),
            "--tier",
            "full",
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    assert (output.parent / "assets/scientific-lecture.pdf").read_bytes() == (
        corpus.path / "assets/scientific-lecture.pdf"
    ).read_bytes()
    assert not (output.parent / "gold.json").exists()
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark",
            "run",
            "--corpus",
            str(corpus.path),
            "--require-baseline",
            "--output",
            str(tmp_path / "run"),
        ],
    )
    assert main() == 1
    assert read_json(tmp_path / "run/report.json")["gate"]["baseline_available"] is False


async def test_unknown_telemetry_stays_unknown_and_unreviewed_extra_fields_rejected(
    corpus, tmp_path
):
    item = task(corpus)
    observed = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    observed.pop("trace")
    observed.pop("human_correction_steps")
    observed["operations"] = [{"name": "model_reasoning"}]
    candidate = {
        "schema": SCHEMA,
        "corpus_sha256": corpus.fingerprint,
        "system": {
            "id": "fictional-test-model",
            "kind": "normalized_model",
            "version_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "measurement_scope": "model_end_to_end",
            "run_receipt": "synthetic-test-only",
            "input_export_sha256": digest(corpus.export("fast")),
        },
        "observations": [observed],
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    result = imported(corpus, path, tier="fast")
    assert result["metrics"]["operational"]["human_correction_steps"]["total"] is None
    observed["unchecked_summary"] = "An unsupported factual claim cannot hide in an extra field."
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="Unreviewed response"):
        imported(corpus, path, tier="fast")


async def test_alternative_mapping_cannot_hide_forbidden_operation(corpus):
    item = task(corpus)
    observed = await execute(item, corpus.sources, corpus.path, corpus.data["clock"])
    observed["operations"] = [{"name": "edit_grade", "method": "GET"}]
    result = evaluate(
        item,
        observed,
        corpus,
        system_kind="alternative_tools",
        operation_mapping={"edit_grade": "grade"},
    )
    assert result["state"] == "failed" and result["metrics"]["authorization_violations"] == 1
