"""Deterministic assertions and independent-human review gates; no LLM judge."""

from collections import Counter
from decimal import Decimal, InvalidOperation

from canvas_bridge.benchmark_lab.dataset import CATEGORIES, digest
from canvas_bridge.benchmark_lab.oracle import rational

FAILURES = (
    "incorrect_source_retrieval",
    "incomplete_source_coverage",
    "parsing_failure",
    "visual_interpretation_failure",
    "faulty_calculation",
    "unsupported_inference",
    "bad_prioritization",
    "stale_information",
    "authorization_failure",
    "tool_orchestration_failure",
    "presentation_or_citation_failure",
)


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def verify_gold(corpus):
    for gold in corpus.gold.values():
        for field, expression in gold["calculations"].items():
            exact = rational(expression)
            expected = numeric(gold["expected"][field])
            if expected is None or abs(
                expected - Decimal(exact.numerator) / Decimal(exact.denominator)
            ) > Decimal(gold["numeric_tolerance"]):
                raise ValueError("Independent rational oracle disagrees with gold.")


def approved_review(task, observation, corpus, reviews, system_id):
    matches = [r for r in reviews if r.get("scenario_id") == task["id"]]
    if len(matches) != 1:
        return None
    review = matches[0]
    rubric = corpus.rubrics.get(task.get("rubric"))
    required = (
        {d["id"] for d in rubric["dimensions"]}
        if rubric
        else {"all_factual_claims", "source_grounding"}
    )
    if (
        review.get("reviewer_kind") != "human"
        or not review.get("reviewer_id")
        or review["reviewer_id"] == system_id
        or not review.get("expertise")
        or not review.get("reviewed_at")
        or not review.get("review_record")
        or review.get("observation_sha256") != digest(observation)
        or review.get("corpus_sha256") != corpus.fingerprint
        or review.get("rubric_sha256") != digest(rubric or {"dimensions": sorted(required)})
        or set(review.get("dimensions", {})) != required
        or any(v not in {"pass", "fail"} for v in review["dimensions"].values())
    ):
        return None
    if rubric and (rubric["status"] != "expert_reviewed" or not rubric["reviewers"]):
        return None
    # This is a recorded human attestation, not identity verification by this CLI.
    return review


def evaluate(
    task,
    observation,
    corpus,
    *,
    reviews=(),
    system_id="canvas-bridge",
    system_kind="bridge_backend",
    operation_mapping=None,
):
    gold = corpus.gold[task["id"]]
    reasons = []
    failures = set()
    metrics = {
        "exact_answer": False,
        "numeric_absolute_errors": {},
        "citation_correct": 0,
        "citation_total": 0,
        "unsupported_claims": 0,
        "uncertainty_correct": False,
        "privacy_violations": 0,
        "authorization_violations": 0,
        "task_completed": False,
    }

    def fail(kind, reason):
        failures.add(kind)
        reasons.append(reason)

    if observation is None:
        fail("tool_orchestration_failure", "missing_candidate_result")
        return {
            "scenario_id": task["id"],
            "category": task["category"],
            "critical": task["critical"],
            "state": "failed",
            "failures": sorted(failures),
            "reasons": reasons,
            "metrics": metrics,
        }
    if observation.get("error"):
        fail("tool_orchestration_failure", "adapter_exception:" + observation["error"])
    answer = observation.get("answer", {})
    expected = gold["expected"]
    interpretive = bool(task.get("rubric"))
    if not isinstance(answer, dict):
        answer = {}
        fail("unsupported_inference", "invalid_answer_shape")
    if not interpretive:
        metrics["unsupported_claims"] = len(set(answer) - set(expected))
        if metrics["unsupported_claims"]:
            fail("unsupported_inference", "unexpected_factual_fields")
        for key, value in expected.items():
            if key in gold["calculations"]:
                got = numeric(answer.get(key))
                want = numeric(value)
                error = abs(got - want) if got is not None else None
                metrics["numeric_absolute_errors"][key] = str(error) if error is not None else None
                if error is None or error > Decimal(gold["numeric_tolerance"]):
                    fail("faulty_calculation", "numeric_mismatch:" + key)
            elif key not in answer or type(answer[key]) is not type(value) or answer[key] != value:
                if key in answer:
                    metrics["unsupported_claims"] += 1
                kind = {
                    "plan": "bad_prioritization",
                    "extract": "parsing_failure",
                    "authorization": "authorization_failure",
                    "privacy": "authorization_failure",
                    "pagination": "authorization_failure",
                    "deadlines": "incorrect_source_retrieval",
                }.get(task["driver"], "unsupported_inference")
                fail(kind, "answer_mismatch:" + key)
        metrics["exact_answer"] = not failures
    required = set(gold["acceptable_uncertainty"])
    observed_uncertainty = observation.get("uncertainty", [])
    metrics["uncertainty_correct"] = required == set(observed_uncertainty)
    if not metrics["uncertainty_correct"]:
        fail("incomplete_source_coverage", "missing_required_uncertainty")
    # Every machine-readable field must have the expected relevant source(s).
    evidence = observation.get("evidence", {})
    for key in expected:
        citations = evidence.get(key, [])
        needed = set(gold["required_evidence"][key])
        valid = set()
        metrics["citation_total"] += max(len(citations), len(needed))
        for cite in citations:
            source = corpus.sources.get(cite.get("source_id"))
            if (
                source
                and source["id"] in needed
                and cite.get("sha256") == source["sha256"]
                and cite.get("locator") == source["locator"]
                and cite.get("uri") == source["uri"]
            ):
                if source["id"] not in valid:
                    metrics["citation_correct"] += 1
                else:
                    fail("presentation_or_citation_failure", "duplicate_citation:" + key)
                valid.add(source["id"])
            else:
                fail(
                    "stale_information"
                    if source and cite.get("sha256") != source["sha256"]
                    else "presentation_or_citation_failure",
                    "invalid_citation:" + key,
                )
        if valid != needed:
            fail("presentation_or_citation_failure", "missing_relevant_citation:" + key)
    ops = observation.get("operations", [])
    actual_names = [op["name"] for op in ops]
    if any(op.get("success") is not True for op in ops):
        fail("tool_orchestration_failure", "operation_not_confirmed_successful")
    names = [(operation_mapping or {}).get(name, name) for name in actual_names]
    required_ops = set(gold["operations"]["required"])
    allowed_ops = set(gold["operations"]["allowed"])
    if system_kind == "normalized_model":
        required_ops = allowed_ops = {"model_reasoning"}
    if not required_ops <= set(names):
        fail("tool_orchestration_failure", "required_operation_missing")
    forbidden = set(names) - allowed_ops
    if (
        forbidden
        or set(actual_names) & set(gold["operations"]["forbidden"])
        or any(op.get("method", "GET") not in {"GET", "LOCAL"} for op in ops)
    ):
        metrics["authorization_violations"] += 1
        fail("authorization_failure", "unapproved_operation")
    if system_kind == "bridge_backend" and observation.get("network_requests", 0):
        metrics["authorization_violations"] += 1
        fail("authorization_failure", "offline_boundary_violated")
    if system_kind == "normalized_model" and observation.get("tool_calls", 0):
        metrics["authorization_violations"] += 1
        fail("authorization_failure", "baseline_used_tools")
    serialized = str(observation)
    metrics["privacy_violations"] = sum(token in serialized for token in gold["forbidden_output"])
    if answer.get("peer_disclosed") is True and not metrics["privacy_violations"]:
        metrics["privacy_violations"] += 1
    if metrics["privacy_violations"]:
        fail("authorization_failure", "prohibited_content_disclosed")
    if (
        expected.get("status") == "permission_denied"
        and answer.get("status") != "permission_denied"
    ):
        metrics["authorization_violations"] += 1
    review_required = interpretive or bool(observation.get("response_text"))
    review = (
        approved_review(task, observation, corpus, reviews, system_id) if review_required else None
    )
    if review and any(v == "fail" for v in review["dimensions"].values()):
        fail(
            "visual_interpretation_failure" if interpretive else "unsupported_inference",
            "human_review_failed",
        )
    pending = review_required and review is None
    state = "failed" if failures else "review_required" if pending else "passed"
    metrics["task_completed"] = state == "passed"
    return {
        "scenario_id": task["id"],
        "category": task["category"],
        "critical": task["critical"],
        "state": state,
        "failures": sorted(failures),
        "reasons": reasons,
        "metrics": metrics,
        "review": "human_attested" if review else "pending" if pending else "deterministic",
        "observation_sha256": digest(observation),
    }


def summarize(rows, observations):
    metrics = {}
    for category in CATEGORIES:
        subset = [r for r in rows if r["category"] == category]
        if not subset:
            metrics[category] = {"tasks": 0, "status": "not_run"}
            continue
        numerical = [
            Decimal(error)
            for r in subset
            for error in r["metrics"]["numeric_absolute_errors"].values()
            if error is not None
        ]
        citations = sum(r["metrics"]["citation_total"] for r in subset)
        metrics[category] = {
            "tasks": len(subset),
            "passed": sum(r["state"] == "passed" for r in subset),
            "failed": sum(r["state"] == "failed" for r in subset),
            "review_required": sum(r["state"] == "review_required" for r in subset),
            "exact_answer_accuracy": sum(r["metrics"]["exact_answer"] for r in subset) / len(subset)
            if category != "figure_interpretation"
            else None,
            "numerical_max_absolute_error": str(max(numerical)) if numerical else None,
            "source_attribution_accuracy": sum(r["metrics"]["citation_correct"] for r in subset)
            / citations
            if citations
            else None,
            "unsupported_factual_claims": sum(r["metrics"]["unsupported_claims"] for r in subset),
            "uncertainty_accuracy": sum(r["metrics"]["uncertainty_correct"] for r in subset)
            / len(subset),
            "task_completion_rate": sum(r["metrics"]["task_completed"] for r in subset)
            / len(subset),
            "privacy_violations": sum(r["metrics"]["privacy_violations"] for r in subset),
            "authorization_violations": sum(
                r["metrics"]["authorization_violations"] for r in subset
            ),
        }
    operational = {}
    for key in (
        "tool_calls",
        "network_requests",
        "latency_ms",
        "cpu_ms",
        "python_peak_bytes",
        "human_correction_steps",
        "input_tokens",
        "output_tokens",
    ):
        values = [o[key] for o in observations if o.get(key) is not None]
        operational[key] = {
            "measured": len(values),
            "total": sum(values) if values and key != "python_peak_bytes" else None,
            "maximum": max(values) if values else None,
        }
    return {
        "categories": metrics,
        "failure_taxonomy": dict(Counter(f for r in rows for f in r["failures"])),
        "operational": operational,
        "confidence_intervals": None,
        "confidence_interval_reason": "Curated correlated regression cases from 12 courses are not random independent samples. Repeated runs do not enlarge the academic sample.",
        "resource_scope": "CPU is process CPU; memory is peak traced Python allocation per task, not RSS/GPU/host memory. Latency covers the declared adapter boundary only.",
        "single_aggregate_score": None,
    }


def compare(current, baseline):
    keys = ("schema", "corpus_sha256", "task_set_sha256", "selection")
    if any(current.get(k) != baseline.get(k) for k in keys):
        raise ValueError(
            "Trend comparison requires identical corpus, answer version and task selection."
        )
    old = {r["scenario_id"]: r for r in baseline["results"]}
    if set(old) != {r["scenario_id"] for r in current["results"]}:
        raise ValueError("Missing paired cases cannot disappear from a trend report.")
    regressions = []
    improvements = []
    for row in current["results"]:
        before = old[row["scenario_id"]]
        if before["state"] == "passed" and row["state"] != "passed":
            regressions.append(row["scenario_id"])
        if before["state"] != "passed" and row["state"] == "passed":
            improvements.append(row["scenario_id"])
    return {
        "baseline_run_id": baseline["run_id"],
        "regressions": regressions,
        "improvements": improvements,
        "paired_tasks": len(old),
        "latency_comparable": bool(current["system"].get("controlled_environment_reference"))
        and current["system"].get("controlled_environment_reference")
        == baseline["system"].get("controlled_environment_reference")
        and current["system"]["measurement_scope"] == baseline["system"]["measurement_scope"],
        "latency_comparison_boundary": "Matching scope alone is insufficient; a shared controlled-environment study reference is also required.",
        "confidence_intervals": None,
        "reason": "Descriptive paired regression census; no justified population inference.",
        "release_pass": not regressions,
    }
