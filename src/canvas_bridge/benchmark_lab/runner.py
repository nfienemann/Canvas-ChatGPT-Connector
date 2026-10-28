"""Reproducible runs, imported comparison evidence, and non-compensating gates."""

import hashlib
import importlib.metadata
import json
import platform
import re
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from canvas_bridge.benchmark_lab import SCHEMA
from canvas_bridge.benchmark_lab.adapters import bounded_execute
from canvas_bridge.benchmark_lab.dataset import digest, read_json
from canvas_bridge.benchmark_lab.evaluate import compare, evaluate, summarize, verify_gold


def code_fingerprint():
    root = Path(__file__).resolve().parents[1]
    files = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.suffix in {".py", ".json"} and p.is_file()
    }
    return digest(files)


def environment_receipt():
    versions = {}
    for name in ("pydantic", "pypdf", "pillow", "mcp", "defusedxml"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    lock = Path(__file__).resolve().parents[3] / "uv.lock"
    facts = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": versions,
        "dependency_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
        if lock.is_file()
        else None,
    }
    return {**facts, "environment_sha256": digest(facts)}


def selected(corpus, tier, comparison_set):
    return [t for t in corpus.tasks(tier) if not comparison_set or t["comparison_eligible"]]


def envelope(corpus, tasks, observations, system, selection, reviews=()):
    verify_gold(corpus)
    results = [
        evaluate(
            task,
            observations.get(task["id"]),
            corpus,
            reviews=reviews,
            system_id=system["id"],
            system_kind=system["kind"],
            operation_mapping=system.get("operation_mapping"),
        )
        for task in tasks
    ]
    report = {
        "schema": SCHEMA,
        "corpus_sha256": corpus.fingerprint,
        "task_set_sha256": digest([t["id"] for t in tasks]),
        "selection": selection,
        "system": system,
        "generated_at": datetime.now(UTC).isoformat(),
        "results": results,
        "observations": observations,
        "metrics": summarize(results, list(observations.values())),
        "comparison": {
            "status": "not_run",
            "reason": "No accepted previous-stable report or external comparison run supplied.",
        },
        "gate": {
            "objective_pass": not any(r["state"] == "failed" for r in results),
            "critical_pass": not any(r["critical"] and r["state"] != "passed" for r in results),
            "review_complete": not any(r["state"] == "review_required" for r in results),
        },
        "limitations": [
            "No superiority, institutional approval or deployed ChatGPT claim follows from this synthetic backend run.",
            "Interpretive free text requires independent human review; deterministic checks cover structured claims only.",
            "A corpus fingerprint binds inputs and gold. Public fixtures may be contaminated in model studies.",
        ],
    }
    report["run_id"] = digest(
        {"corpus": corpus.fingerprint, "system": system, "observations": observations}
    )
    return report


async def run(corpus, *, tier="fast", comparison_set=False):
    before = code_fingerprint()
    observations = {}
    tasks = selected(corpus, tier, comparison_set)
    for task in tasks:
        tracemalloc.start()
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        attempts = [0]

        def deny_network(*args, attempts=attempts, **kwargs):
            attempts[0] += 1
            raise RuntimeError("BENCHMARK_NETWORK_FORBIDDEN")

        try:
            with (
                patch("socket.socket.connect", deny_network),
                patch("socket.socket.connect_ex", deny_network),
                patch("socket.getaddrinfo", deny_network),
            ):
                obs = await bounded_execute(task, corpus.sources, corpus.path, corpus.data["clock"])
        except Exception as exc:
            # Never echo payloads, credentials, raw tracebacks or private path strings.
            obs = {
                "scenario_id": task["id"],
                "answer": {},
                "evidence": {},
                "uncertainty": [],
                "operations": [],
                "error": type(exc).__name__,
            }
        obs["network_requests"] = attempts[0]
        obs.update(
            latency_ms=(time.perf_counter_ns() - start) / 1_000_000,
            cpu_ms=(time.process_time_ns() - cpu) / 1_000_000,
            python_peak_bytes=tracemalloc.get_traced_memory()[1],
        )
        tracemalloc.stop()
        observations[task["id"]] = obs
    after = code_fingerprint()
    system = {
        "id": "canvas-bridge-current",
        "kind": "bridge_backend",
        "version_sha256": before,
        "measurement_scope": "backend_workflow",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "network": "none",
        "telemetry": "locally_measured",
        "source_stable": before == after,
        "environment": environment_receipt(),
    }
    report = envelope(
        corpus, tasks, observations, system, "comparison" if comparison_set else "all"
    )
    if before != after:
        report["gate"]["objective_pass"] = False
        report["limitations"].append(
            "Source files changed during execution; this run cannot certify one revision."
        )
    return report


def imported(corpus, path, *, tier="full", reviews=()):
    candidate = read_json(path)
    if candidate.get("schema") != SCHEMA or candidate.get("corpus_sha256") != corpus.fingerprint:
        raise ValueError("Candidate must identify the exact corpus/answer version.")
    system = candidate["system"]
    if system.get("kind") not in {"normalized_model", "alternative_tools", "previous_bridge"}:
        raise ValueError("Unsupported external comparison kind.")
    for key in (
        "id",
        "version_sha256",
        "configuration_sha256",
        "measurement_scope",
        "run_receipt",
        "input_export_sha256",
    ):
        if not isinstance(system.get(key), str) or not system[key]:
            raise ValueError("External execution/configuration provenance is incomplete: " + key)
    if any(
        not re.fullmatch(r"[a-f0-9]{64}", system[k])
        for k in ("version_sha256", "configuration_sha256", "input_export_sha256")
    ):
        raise ValueError("External version/configuration digests must be SHA-256.")
    export = corpus.export(tier)
    if system["input_export_sha256"] != digest(export):
        raise ValueError("The external run did not attest the exact normalized input export.")
    if system["kind"] == "alternative_tools" and not all(
        system.get(k)
        for k in ("installation_receipt", "authorization_reference", "tool_configuration")
    ):
        raise ValueError(
            "Alternative tools need actual installation, authorization and configuration receipts."
        )
    if system["kind"] == "alternative_tools" and (
        not isinstance(system.get("operation_mapping"), dict)
        or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in system["operation_mapping"].items()
        )
    ):
        raise ValueError("Alternative operations need an explicit reviewed semantic mapping.")
    if system["kind"] != "alternative_tools" and system.get("operation_mapping"):
        raise ValueError("Only configured alternative tools may map their native operation names.")
    rows = candidate["observations"]
    tasks = selected(corpus, tier, True)
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid response inventory.")
    observations = {}
    allowed = {t["id"] for t in tasks}
    for row in rows:
        permitted = {
            "scenario_id",
            "answer",
            "evidence",
            "uncertainty",
            "operations",
            "response_text",
            "human_correction_steps",
            "tool_calls",
            "network_requests",
            "latency_ms",
            "cpu_ms",
            "python_peak_bytes",
            "error",
            "input_tokens",
            "output_tokens",
        }
        if not isinstance(row, dict) or set(row) - permitted:
            raise ValueError("Unreviewed response fields are not accepted.")
        if row.get("scenario_id") not in allowed or row["scenario_id"] in observations:
            raise ValueError("Duplicate or unknown result ID.")
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
            value = row.get(key)
            if value is not None and (
                type(value) not in {int, float} or value < 0 or value > 1e15 or value != value
            ):
                raise ValueError("Invalid operational measurement.")
        if not isinstance(row.get("evidence", {}), dict) or not isinstance(
            row.get("operations", []), list
        ):
            raise ValueError("Invalid evidence/operation shape.")
        if not isinstance(row.get("answer", {}), dict) or not isinstance(
            row.get("response_text", ""), str
        ):
            raise ValueError("Invalid answer shape.")
        if not isinstance(row.get("uncertainty", []), list) or any(
            not isinstance(s, str) for s in row.get("uncertainty", [])
        ):
            raise ValueError("Invalid uncertainty shape.")
        for citations in row.get("evidence", {}).values():
            if not isinstance(citations, list) or any(
                not isinstance(c, dict) or set(c) != {"source_id", "sha256", "locator", "uri"}
                for c in citations
            ):
                raise ValueError("Invalid citation shape.")
        for operation in row.get("operations", []):
            if (
                not isinstance(operation, dict)
                or not isinstance(operation.get("name"), str)
                or set(operation) - {"name", "scope", "success", "method"}
            ):
                raise ValueError("Invalid operation trace.")
        observations[row["scenario_id"]] = row
    # Claims about an external execution remain submitter attestations, never installed-by-us evidence.
    system = {**system, "telemetry": "external_attestation_not_independently_verified"}
    return envelope(corpus, tasks, observations, system, "comparison", reviews)


def trend(report, baseline_path):
    baseline = read_json(baseline_path)
    report["comparison"] = {"status": "paired", **compare(report, baseline)}
    report["gate"]["no_regressions"] = report["comparison"]["release_pass"]
    return report


def markdown(report):
    lines = [
        "# Academic benchmark execution",
        "",
        f"System: `{report['system']['id']}`. Scope: `{report['system']['measurement_scope']}`.",
        f"Corpus: `{report['corpus_sha256']}`. Run: `{report['run_id']}`.",
        "",
        "| Category | Tasks | Pass | Fail | Review | Exact accuracy | Citation accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in report["metrics"]["categories"].items():

        def pct(value):
            return "unscored" if value is None else f"{value:.1%}"

        lines.append(
            f"| {name} | {m['tasks']} | {m.get('passed', 0)} | {m.get('failed', 0)} | {m.get('review_required', 0)} | {pct(m.get('exact_answer_accuracy'))} | {pct(m.get('source_attribution_accuracy'))} |"
        )
    lines += [
        "",
        "Gates: `" + json.dumps(report["gate"], sort_keys=True) + "`.",
        "",
        "No single aggregate score is calculated. Numeric error, unsupported claims, uncertainty, resource use, privacy and authorization counts are in the adjacent JSON report.",
        "",
        "Comparison: `" + json.dumps(report["comparison"], sort_keys=True) + "`.",
        "",
        report["metrics"]["confidence_interval_reason"],
        "",
        "Failures and pending reviews:",
        "",
    ]
    for row in report["results"]:
        if row["state"] != "passed":
            lines.append(
                f"- `{row['scenario_id']}`: {row['state']}; {', '.join(row['reasons']) or 'independent rubric review required'}."
            )
    lines += ["", *["- " + s for s in report["limitations"]], ""]
    return "\n".join(lines)


def save(report, corpus, path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    (path / "report.md").write_text(markdown(report), encoding="utf-8")
    tasks = {t["id"]: t for t in corpus.scenarios}
    for row in report["results"]:
        if row["state"] != "failed":
            continue
        task = tasks[row["scenario_id"]]
        capsule = {
            "schema": SCHEMA,
            "corpus_sha256": corpus.fingerprint,
            "system": report["system"],
            "task": task,
            "gold": corpus.gold[task["id"]],
            "result": row,
            "observation": report["observations"].get(task["id"]),
            "sources": [corpus.sources[s] for s in task["source_ids"]],
            "reproduction": "Run the named scenario against this exact versioned corpus and source revision; evaluate the captured observation to reproduce the scoring failure.",
        }
        folder = path / "failures" / report["run_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (task["id"] + ".json")).write_text(
            json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
