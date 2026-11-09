from scripts.benchmark_usefulness import run


def test_U04_frozen_retrieval_benchmark():
    result = run()
    assert result["gate_passed"], result["categories"]
    assert result["answerable_top_five"] >= 29


def test_U02_twelve_frozen_obligation_scenarios():
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from canvas_bridge.academic.independent_engine import work_items
    from canvas_bridge.academic.independent_models import IndependentAcademicInput
    from canvas_bridge.domain import Source
    from canvas_bridge.planning import is_actionable
    from canvas_bridge.usefulness.engine import obligations

    corpus = json.loads(
        (Path(__file__).parents[1] / "benchmarks/usefulness/obligations.json").read_text()
    )
    now = datetime(2026, 10, 29, tzinfo=UTC)
    source = Source(
        id="fictional",
        url="",
        title="Fictional reviewed obligations",
        retrieved_at=now,
        content_hash="a" * 64,
    )
    baseline = 0
    for case in corpus["cases"]:
        work = {
            "key": "target",
            "title": case["id"],
            "due": {"kind": "local_date", "local_date": "2026-11-08"},
            **case["work"],
        }
        data = {"schema_version": "independent-academic-1", "work": [work]}
        if case.get("group"):
            data["work"] += [{"key": k, "title": k} for k in ("one", "two")]
            data["requirement_groups"] = [
                {
                    "key": "choice",
                    "members": ["target", "one", "two"],
                    "minimum": 2,
                    "selected": ["one", "two"],
                    "basis": "Explicitly complete two of three",
                }
            ]
        dataset = IndependentAcademicInput.model_validate(data)
        result = obligations(dataset, source, now=now)
        state = next(a["state"] for a in result["accounting"] if a["work_id"] == "target")
        actual = state if state in {"optional", "unresolved", "excluded"} else "actionable"
        assert actual == case["expected"], case["id"]
        assert all(a["official_submission"] == "unknown" for a in result["activities"])
        # Earlier generic planning lacks the new requirement/report/group filters.
        previous = "actionable" if is_actionable(work_items(dataset, source)[0]) else "excluded"
        baseline += previous == case["expected"]
    assert len(corpus["cases"]) == 12 and baseline < 12
