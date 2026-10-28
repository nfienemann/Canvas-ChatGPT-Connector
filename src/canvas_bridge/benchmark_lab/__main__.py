"""Run with python -m canvas_bridge.benchmark_lab; no network or model credentials."""

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from canvas_bridge.benchmark_lab.dataset import Corpus, read_json
from canvas_bridge.benchmark_lab.evaluate import verify_gold
from canvas_bridge.benchmark_lab.runner import imported, run, save, trend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run", "export", "evaluate"))
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/academic/v1"))
    parser.add_argument("--tier", choices=("fast", "full"), default="fast")
    parser.add_argument("--output", type=Path, default=Path(".local/benchmarks/current"))
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--comparison-set", action="store_true")
    parser.add_argument("--require-baseline", action="store_true")
    parser.add_argument("--require-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        corpus = Corpus(args.corpus)
        verify_gold(corpus)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "corpus_sha256": corpus.fingerprint,
                        "courses": len(corpus.data["courses"]),
                        "scenarios": len(corpus.scenarios),
                        "gold": "independently_recomputed",
                    }
                )
            )
            return 0
        if args.command == "export":
            export = corpus.export(args.tier)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            for task in export["tasks"]:
                for source in task["sources"]:
                    asset = source["payload"].get("asset")
                    if asset:
                        destination = args.output.parent / asset
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if (
                            destination.exists()
                            and destination.read_bytes() != (corpus.path / asset).read_bytes()
                        ):
                            raise ValueError("Export would overwrite a different asset.")
                        shutil.copyfile(corpus.path / asset, destination)
            args.output.write_text(json.dumps(export, indent=2) + "\n", encoding="utf-8")
            return 0
        if args.command == "evaluate":
            if not args.candidate:
                raise ValueError("--candidate is required.")
            report = imported(
                corpus,
                args.candidate,
                tier=args.tier,
                reviews=read_json(args.reviews) if args.reviews else (),
            )
        else:
            if args.reviews:
                raise ValueError(
                    "Review files apply to imported candidate observations via evaluate."
                )
            report = asyncio.run(run(corpus, tier=args.tier, comparison_set=args.comparison_set))
        if args.baseline:
            trend(report, args.baseline)
        elif args.require_baseline:
            report["gate"]["baseline_available"] = False
        save(report, corpus, args.output)
        gate = report["gate"]
        passed = all(v for k, v in gate.items() if k != "review_complete" or args.require_reviewed)
        print(
            json.dumps(
                {"passed": passed, "gates": gate, "report": str(args.output / "report.json")}
            )
        )
        return 0 if passed else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "invalid_benchmark_input", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
