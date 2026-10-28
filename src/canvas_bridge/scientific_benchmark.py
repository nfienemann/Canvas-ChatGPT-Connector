"""Offline retrieval regression census and independently reviewed interpretation intake."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from canvas_bridge.benchmark_lab.dataset import digest, read_json
from canvas_bridge.benchmark_lab.runner import code_fingerprint, environment_receipt
from canvas_bridge.domain import DomainError
from canvas_bridge.figure_inspection import candidates
from canvas_bridge.figure_observations import FigureObservation
from canvas_bridge.parser_worker import extract
from canvas_bridge.scientific_explanations import grounded_explanation

ROOT = Path("benchmarks/scientific/v3")


def corpus(root=ROOT):
    manifest = read_json(root / "manifest.json")
    if manifest.get("schema") != "scientific-benchmark-3" or manifest.get("synthetic") is not True:
        raise ValueError("Unknown or non-synthetic scientific corpus.")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Unsafe fixture path.")
        data = (root / name).read_bytes()
        if len(data) > 10_000_000 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Scientific fixture hash or size mismatch.")
    cases = read_json(root / "cases.json")["cases"]
    if len(cases) != 10 or len({c["id"] for c in cases}) != 10:
        raise ValueError("Scientific fixture case set is incomplete.")
    if set(manifest["files"]) != {
        "cases.json",
        "scientific-fixtures.pdf",
        *(c["id"] + ".png" for c in cases),
    }:
        raise ValueError("The manifest must bind every scientific fixture asset.")
    return manifest, cases


def evaluate(root=ROOT, responses=None, reviews=None):
    attempts = 0

    def deny_network(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ValueError("Scientific benchmarks forbid network connections.")

    with (
        patch("socket.socket.connect", deny_network),
        patch("socket.socket.connect_ex", deny_network),
        patch("socket.getaddrinfo", deny_network),
    ):
        report = _evaluate(root, responses, reviews)
    if attempts:
        raise ValueError("A scientific benchmark attempted a network connection.")
    report["network_calls"] = attempts
    report["network_policy"] = "DNS_and_socket_connections_blocked"
    return report


def _evaluate(root, responses, reviews):
    manifest, cases = corpus(root)
    fingerprint = digest(manifest)
    source = code_fingerprint()
    parsed = extract((root / "scientific-fixtures.pdf").read_bytes(), "pdf")
    settings = SimpleNamespace(visual_candidate_pages=200, visual_candidate_limit=12)
    attempts, reviewers = {}, {}
    system_id = None
    if responses is not None:
        if not isinstance(responses, dict) or set(responses) != {
            "corpus_sha256",
            "system",
            "observations",
        }:
            raise ValueError("Unknown interpretation response fields.")
        if responses.get("corpus_sha256") != fingerprint:
            raise ValueError("Responses must bind the exact scientific corpus.")
        system = responses["system"]
        if (
            not isinstance(system, dict)
            or set(system) != {"id", "version", "execution_reference"}
            or not all(isinstance(v, str) and v.strip() for v in system.values())
        ):
            raise ValueError("Interpretation responses need actual execution provenance.")
        if not isinstance(responses["observations"], list):
            raise ValueError("Interpretation observations must be a list.")
        system_id = system["id"]
        for row in responses["observations"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"case_id", "observation", "image_sha256"}
                or not isinstance(row["case_id"], str)
                or row["image_sha256"] != manifest["files"].get(row["case_id"] + ".png")
            ):
                raise ValueError(
                    "An interpretation must bind its exact image and contain no unscored response fields."
                )
            if row["case_id"] in attempts or row["case_id"] not in {c["id"] for c in cases}:
                raise ValueError("Duplicate or unknown scientific case.")
            attempts[row["case_id"]] = row
    if reviews is not None:
        if (
            not isinstance(reviews, dict)
            or set(reviews) != {"reviews"}
            or not isinstance(reviews["reviews"], list)
        ):
            raise ValueError("Review input must contain only a reviews list.")
        for review in reviews["reviews"]:
            if not isinstance(review, dict) or not isinstance(review.get("case_id"), str):
                raise ValueError("A review needs a case identifier.")
            if review["case_id"] in reviewers or review["case_id"] not in attempts:
                raise ValueError("Review lacks a unique executed observation.")
            reviewers[review["case_id"]] = review
    results = []
    for case in cases:
        selected, scanned = candidates(parsed["pages"], case["figure_label"], None, settings)
        by_query, _ = candidates(parsed["pages"], None, None, settings, case["query"])
        retrieval = bool(
            selected and by_query and selected[0]["page"] == by_query[0]["page"] == case["page"]
        )
        record = {
            "case_id": case["id"],
            "retrieval_pass": retrieval,
            "expected_page": case["page"],
            "selected_page": selected[0]["page"] if selected else None,
            "query_selected_page": by_query[0]["page"] if by_query else None,
            "pages_scanned": scanned,
            "interpretation_state": "not_run",
            "interpretation_correct": None,
        }
        attempt = attempts.get(case["id"])
        if attempt is not None:
            observation = FigureObservation.model_validate(attempt["observation"])
            if not observation.scientific_explanation:
                raise ValueError(
                    "An interpretation attempt must include its structured explanation."
                )
            text = parsed["pages"][case["page"] - 1]["text"]
            grounded_explanation(
                observation.scientific_explanation, observation, text, f"PDF page {case['page']}"
            )
            record["interpretation_state"] = "independent_review_required"
            record["observation_sha256"] = digest(attempt)
            review = reviewers.get(case["id"])
            if review is not None:
                when = datetime.fromisoformat(review["reviewed_at"])
                if (
                    review.get("reviewer_kind") != "human"
                    or not review.get("reviewer_id")
                    or review["reviewer_id"] == system_id
                    or not review.get("expertise")
                    or not review.get("review_record")
                    or when.tzinfo is None
                    or when > datetime.now(UTC)
                    or review.get("corpus_sha256") != fingerprint
                    or review.get("observation_sha256") != digest(attempt)
                    or review.get("rubric_sha256") != digest(case)
                    or review.get("rubric_expert_reviewed") is not True
                ):
                    raise ValueError(
                        "Interpretation review is not independently attested or source-bound."
                    )
                dimensions = review.get("dimensions", {})
                if set(dimensions) != set(case["required_dimensions"]) or any(
                    type(v) is not bool for v in dimensions.values()
                ):
                    raise ValueError("Review must address every expert rubric dimension.")
                record["interpretation_correct"] = all(dimensions.values())
                record["interpretation_state"] = "externally_reviewed_attestation"
        results.append(record)
    reviewed = [r for r in results if r["interpretation_correct"] is not None]
    return {
        "schema": "scientific-benchmark-3",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_sha256": fingerprint,
        "source_sha256": source,
        "source_stable": source == code_fingerprint(),
        "environment": environment_receipt(),
        "interpretation_system": responses["system"] if responses else None,
        "responses_sha256": digest(responses) if responses else None,
        "reviews_sha256": digest(reviews) if reviews else None,
        "retrieval_accuracy": sum(r["retrieval_pass"] for r in results) / len(results),
        "interpretation_accuracy": sum(r["interpretation_correct"] for r in reviewed)
        / len(reviewed)
        if reviewed
        else None,
        "interpretation_reviewed_count": len(reviewed),
        "interpretation_case_count": len(cases),
        "results": results,
        "synthetic": True,
        "limitations": [
            "Retrieval is a deterministic candidate-locator test, not proof of comprehension.",
            "Human review is a recorded external attestation; reviewer identity is not verified by this local evaluator.",
            "No population confidence interval is justified for this curated ten-case census.",
            "No live host visual-delivery or automatic interpretation performance is inferred.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--require-reviewed", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path(".local/benchmarks/scientific-v3/report.json")
    )
    args = parser.parse_args()
    try:
        report = evaluate(
            args.corpus,
            read_json(args.responses) if args.responses else None,
            read_json(args.reviews) if args.reviews else None,
        )
        passed = (
            report["source_stable"]
            and report["retrieval_accuracy"] == 1
            and all(r["interpretation_correct"] is not False for r in report["results"])
            and (not args.require_reviewed or report["interpretation_reviewed_count"] == 10)
        )
        report["gate"] = {
            "passed": passed,
            "require_reviewed": args.require_reviewed,
            "review_complete": report["interpretation_reviewed_count"] == 10,
            "retrieval_pass": report["retrieval_accuracy"] == 1,
            "interpretation_failure": any(
                r["interpretation_correct"] is False for r in report["results"]
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "passed": passed,
                    "retrieval_accuracy": report["retrieval_accuracy"],
                    "interpretation_accuracy": report["interpretation_accuracy"],
                    "reviewed": report["interpretation_reviewed_count"],
                    "report": str(args.output),
                }
            )
        )
        return 0 if passed else 1
    except (ValueError, KeyError, TypeError, OSError, DomainError) as exc:
        print(json.dumps({"passed": False, "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
