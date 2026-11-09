"""Frozen, network-free lexical retrieval comparison; no host interpretation claims."""

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from canvas_bridge.parser_worker import extract
from canvas_bridge.usefulness.search import RANKER, ranked_passages

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def source_bytes(document):
    text, kind = document["text"], document["format"]
    if kind == "docx":
        from tests.test_docx_reading import docx, paragraph

        return docx(paragraph(text))
    if kind == "pptx":
        from tests.test_presentation_reading import deck

        return deck([text])
    if kind == "pdf":
        from tests.test_file_reading import scientific_pdf

        return scientific_pdf([text])
    return text.encode()


def run():
    root = ROOT / "benchmarks/usefulness"
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen corpus fingerprint changed.")
    documents = json.loads((root / "corpus.json").read_text())["documents"]
    cases = json.loads((root / "gold.json").read_text())["cases"]
    rows = []
    for doc in documents:
        raw = source_bytes(doc)
        rows.append(
            SimpleNamespace(
                id=doc["id"],
                version_hash=hashlib.sha256(raw).hexdigest(),
                content={
                    "format": doc["format"],
                    "course": doc["course"],
                    "parsed": extract(raw, doc["format"]),
                },
            )
        )
    results, times = [], []
    for case in cases:
        selected = [r for r in rows if r.id in case.get("scope", [r.id for r in rows])]
        outputs = {}
        for mode in ("literal", "conceptual"):
            start = time.perf_counter()
            hits, _, _ = ranked_passages(selected, case["query"], mode)
            elapsed = time.perf_counter() - start
            outputs[mode] = {
                "top_five": [h["document_id"] for h in hits[:5]],
                "passed": case["expected"] in {h["document_id"] for h in hits[:5]}
                if case["expected"]
                else not hits,
            }
            if mode == "conceptual":
                times.append(elapsed)
        results.append({"id": case["id"], "category": case["category"], **outputs})
    categories = {}
    for category in sorted({r["category"] for r in results}):
        subset = [r for r in results if r["category"] == category]
        categories[category] = {
            "total": len(subset),
            **{m: sum(r[m]["passed"] for r in subset) for m in ("literal", "conceptual")},
        }
    # Owner imports remain capped at twenty. This separate pure-ranker scaling
    # sample adds eighty distractors; it is not 100-document service acceptance.
    hundred = rows + [
        SimpleNamespace(
            id=f"distractor-{i}",
            version_hash="0" * 64,
            content={
                "format": "txt",
                "course": "fictional",
                "parsed": {
                    "coverage": "text_only",
                    "pages": [
                        {
                            "text": f"Fictional unrelated orbital mechanics entry {i}.",
                            "state": "extracted",
                        }
                    ],
                },
            },
        )
        for i in range(80)
    ]
    scaling = []
    for _ in range(30):
        start = time.perf_counter()
        ranked_passages(hundred, "experimental control", "conceptual")
        scaling.append(time.perf_counter() - start)
    answerable = sum(r["conceptual"]["passed"] for r in results if r["category"] != "unanswerable")
    return {
        "corpus_hashes": manifest,
        "ranker": RANKER,
        "runtime": platform.python_version(),
        "system": platform.system(),
        "architecture": platform.machine(),
        "concurrency": 1,
        "categories": categories,
        "answerable_top_five": answerable,
        "answerable_total": 34,
        "gate_passed": answerable >= 29
        and categories["exact"]["conceptual"] == 10
        and categories["unanswerable"]["conceptual"] == 6
        and categories["paraphrase"]["conceptual"] > categories["paraphrase"]["literal"],
        "warm_20_document_p95_seconds": sorted(times)[int(len(times) * 0.95) - 1],
        "ranker_only_100_document_p95_seconds": sorted(scaling)[int(len(scaling) * 0.95) - 1],
        "ranker_only_100_document_median_seconds": statistics.median(scaling),
        "limits": [
            "Fictional, hand-authored small lexical corpus; no independent expert or student pilot review.",
            "Five formats parsed in-process using the actual parser; isolation tested separately.",
            "Warm ranker timings exclude authentication, egress, host latency and cold extraction.",
            "No embeddings, remote inference, provider calls, or claimed learning gains.",
        ],
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "categories",
                    "answerable_top_five",
                    "gate_passed",
                    "warm_20_document_p95_seconds",
                    "ranker_only_100_document_p95_seconds",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["gate_passed"] else 1)
