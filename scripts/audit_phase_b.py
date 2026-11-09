"""Recompute Phase B transcript, restart, readback and fixture checks from frozen evidence."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def journey(folder):
    events = [
        json.loads(line) for line in (folder / "native-events.jsonl").read_text("utf8").splitlines()
    ]
    completed = [e["item"] for e in events if e["type"] == "item.completed"]
    assert all(
        i["type"] in {"agent_message", "mcp_tool_call", "reasoning", "plan_update"}
        for i in completed
    )
    answer = (folder / "native-answer.txt").read_bytes()
    digest = hashlib.sha256(answer).hexdigest()
    assert digest == load(folder / "native-status.json")["final_answer_sha256"]
    assert [i["text"] for i in completed if i["type"] == "agent_message"][
        -1
    ].strip() == answer.decode().strip()
    tools = []
    for i in completed:
        if i["type"] != "mcp_tool_call":
            continue
        assert i["server"] == "coursework"
        body = {}
        if i.get("result"):
            text = i["result"]["content"][0].get("text", "")
            try:
                body = json.loads(text)
            except ValueError:
                pass
        tools.append((i["tool"], i["arguments"], body, i["id"]))
    return tools, digest


def verify(root, bundle):
    expected = json.loads(bundle.read("phase_b_readiness/fixtures/expected_readiness.json"))
    expected = {s["scenario_id"]: s for s in expected["results"]}
    observed = load(root / "authored-scenarios.json")
    assessed = 0
    for key, view in observed.items():
        oracle = expected[key]
        assert (
            view["counts"] == oracle["counts"]
            and view["summary_status"] == oracle["summary_status"]
        )
        assert len(view["remaining_work"]) == oracle["current_work_item_count"]
        assert len(view["review_followups"]) == oracle["review_followup_count"]
        actual = {r["requirement_id"]: r["assessment_status"] for r in view["requirements"]}
        checks = {
            r["requirement_id"]: r["assessment_status"]
            if r["version_match"] == "current"
            else "unknown"
            for r in oracle["requirement_results"]
        }
        assert actual == checks, (key, actual, checks)
        rows = {r["requirement_id"]: r for r in view["requirements"]}
        for expected_row in oracle["requirement_results"]:
            actual_row = rows[expected_row["requirement_id"]]
            assert actual_row["version_match"] == expected_row["version_match"], key
            assert actual_row["coverage"] == expected_row["evidence_coverage"], key
        assessed += len(checks)
    assert len(observed) == 14
    results = {}
    for case in ("baseline", "missing_deck"):
        p = root / case
        restart = load(p / "restart.json")
        assert restart["before_pid"] != restart["after_pid"] and restart["same_database"]
        records = {}
        for name in (
            ("save", "recall", "progress", "revised") if case == "baseline" else ("save", "recall")
        ):
            calls, digest = journey(p / name)
            views = [
                b["data"]
                for t, _, b, _ in calls
                if t == "get_assignment_readiness" and b.get("status") == "ok"
            ]
            assert views, (case, name, "no successful readback")
            target = (
                "PHB-S04"
                if case == "missing_deck"
                else {"revised": "PHB-S03", "progress": "PHB-S09"}.get(name, "PHB-S01")
            )
            view = views[-1]
            assert (
                view["summary_status"] == expected[target]["summary_status"]
                and view["counts"] == expected[target]["counts"]
            ), (case, name, view["counts"])
            assert len(view["remaining_work"]) == expected[target]["current_work_item_count"]
            assert len(view["review_followups"]) == expected[target]["review_followup_count"], (
                case,
                name,
            )
            writes = [
                b["data"]
                for t, _, b, _ in calls
                if t in {"save_assignment_readiness", "record_readiness_progress"}
                and b.get("status") == "ok"
            ]
            if name in {"save", "revised"}:
                assert writes and writes[-1]["revision"] == view["revision"]
                inputs = next(
                    a["review"]
                    for t, a, b, _ in reversed(calls)
                    if t == "save_assignment_readiness" and b.get("status") == "ok"
                )
                ids = {s["document_id"] for s in inputs["bindings"] if s["document_id"]}
                reads = {
                    a["document_id"]
                    for t, a, b, _ in calls
                    if t == "read_local_document" and b.get("status") == "ok"
                }
                assert reads == ids, (case, name, "read coverage", reads, ids)
            if name == "progress":
                assert any(
                    w["progress_state"] == "student_marked_done" and w["rereview_needed"]
                    for w in view["remaining_work"]
                )
                assert any("effort_summary" in v.get("plan", {}) for v in views)
            if name == "recall":
                assert not writes
                for field in (
                    "revision",
                    "assessed_at",
                    "record_id",
                    "requirements",
                    "remaining_work",
                    "bindings",
                    "counts",
                ):
                    assert records["save"][field] == view[field], (case, field)
            records[name] = view
            results[case + "/" + name] = dict(
                answer_sha256=digest,
                record_id=view["record_id"],
                record_revision=view["revision"],
                assessed_at=view["assessed_at"],
                summary_status=view["summary_status"],
                counts=view["counts"],
                work_items=len(view["remaining_work"]),
                followups=len(view["review_followups"]),
                tool_attempts=len(calls),
                confirmed_writes=writes,
                tool_outcomes=[
                    dict(tool=t, status=b.get("status"), event_id=i) for t, _, b, i in calls
                ],
                plan_summary=next(
                    (v["plan"]["effort_summary"] for v in reversed(views) if "plan" in v), None
                ),
            )
        persisted = load(p / "persisted.json")
        assert persisted["revision"] == list(records.values())[-1]["revision"]
    return dict(
        authored_scenarios=len(observed),
        criterion_status_comparisons=assessed,
        native_journeys=results,
        observation_boundary="Actual MCP tool responses in each ephemeral host and its final answer. Internal context assembly is unexposed.",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-b/specs.zip"
    with ZipFile(bundle) as z:
        report = verify(args.output, z)
    (args.output / "capture-audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    main()
