"""Recompute Phase C measurements from the captured product and host evidence."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def check_scenarios(root, bundle):
    expected = json.loads(bundle.read("phase_c_reconciliation/fixtures/expected_transitions.json"))
    results = {}
    for case in expected["results"]:
        key = case["scenario_id"]
        data = read(root / (key + ".json"))
        view = data["view"]
        report = data["report"]["change_report"]
        rows = {r["requirement_id"]: r for r in view["requirements"]}
        assert {k: r["assessment_status"] for k, r in rows.items()} == case["row_statuses"], key
        assert (
            view["summary_status"] == case["readiness"]
            and len(view["review_followups"]) == case["review_followup_count"]
        )
        assert set(case["counts"].items()) <= set(view["counts"].items())
        assert len(view["remaining_work"]) == case["work_counts"]["active"]
        assert (
            sum(w["progress_state"] == "student_marked_done" for w in view["remaining_work"])
            == case["work_counts"]["current_done"]
        )
        actions = {a["requirement_id"]: a["work_action"] for a in report.get("work_actions", [])}
        assert actions == {a["requirement_id"]: a["action"] for a in case["work_actions"]}
        impacts = {r["requirement_id"]: r["impact_status"] for r in report.get("impacts", [])}
        if report["processing_state"] == "applied":
            assert impacts == case["impacts"], key
            for r in rows.values():
                if r["assessment_origin"] in {"carried_forward", "unchanged"}:
                    assert (
                        r["original_assessed_at"]
                        and r["original_assessor_basis"]
                        and r["carry_forward_proof"]
                        and r["carry_forward_validated_at"]
                    )
        else:
            assert key == "PHC-S16" and report["processing_state"] == "compensated"
        results[key] = dict(
            criterion_status_checks=len(rows),
            impact_checks=len(impacts),
            work_actions=dict(Counter(actions.values())),
            declared_done=case["work_counts"]["current_done"],
            work_eligible=[
                w["work_id"]
                for w in view["remaining_work"]
                if w["progress_state"] != "student_marked_done"
            ],
            carried_checks=sum(
                r.get("assessment_origin") in {"carried_forward", "unchanged"}
                for r in rows.values()
            ),
            report_ref=key + ".json",
            revision=view["revision"],
            summary=view["summary_status"],
        )
    return results


def check_host(root, name):
    folder = root / "native" / name
    events = [
        json.loads(line) for line in (folder / "host-events.jsonl").read_text("utf8").splitlines()
    ]
    items = [e["item"] for e in events if e["type"] == "item.completed"]
    assert all(
        i["type"] in {"agent_message", "mcp_tool_call", "reasoning", "plan_update"} for i in items
    )
    answer = (folder / "host-answer.txt").read_bytes()
    sha = hashlib.sha256(answer).hexdigest()
    assert sha == read(folder / "host-status.json")["final_answer_sha256"]
    assert [i["text"] for i in items if i["type"] == "agent_message"][
        -1
    ].strip() == answer.decode().strip()
    calls = []
    for i in (i for i in items if i["type"] == "mcp_tool_call"):
        assert i["server"] == "coursework"
        body = {}
        if i.get("result"):
            try:
                body = json.loads(i["result"]["content"][0]["text"])
            except (IndexError, KeyError, ValueError):
                pass
        calls.append(
            dict(
                tool=i["tool"],
                arguments=i["arguments"],
                status=body.get("status"),
                data=body.get("data", {}),
                event_id=i["id"],
                error=i.get("error"),
            )
        )
    state = read(root / "native" / (("restored" if name == "compensate" else name) + "-state.json"))
    observed = state["change_report"]
    commits = [
        c
        for c in calls
        if c["tool"] in {"reconcile_assignment_change", "compensate_assignment_change"}
        and c["status"] == "ok"
    ]
    if name == "compensate" and not commits:
        assert (root / "native/compensation-boundary.json").is_file()
        assert any("requires approval" in str(c["error"]) for c in calls)
    else:
        assert commits and commits[-1]["data"]["revision"] == observed["applied_revision"]
    views = [
        c["data"] for c in calls if c["tool"] == "get_assignment_readiness" and c["status"] == "ok"
    ]
    assert views and views[-1]["revision"] == observed["applied_revision"]
    new_requests = [
        c for c in calls if c["tool"] == "reconcile_assignment_change" and c["status"] == "ok"
    ]
    return dict(
        answer_sha256=sha,
        host_version=read(folder / "host-status.json")["host_version"],
        tool_attempts=len(calls),
        confirmed_writes=[
            c["data"]
            for c in calls
            if c["status"] == "ok"
            and c["tool"]
            in {
                "reconcile_assignment_change",
                "observe_assignment_change",
                "compensate_assignment_change",
            }
        ],
        reassessed_criteria=[
            r["requirement_id"]
            for c in new_requests
            for r in c["arguments"]["request"].get("assessments", [])
        ],
        admitted_source_parts=[
            dict(
                document_id=c["arguments"]["document_id"],
                parts=[p["part"] for p in c["data"].get("parts", [])],
            )
            for c in calls
            if c["tool"] == "read_local_document" and c["status"] == "ok"
        ],
        final_readiness=views[-1]["summary_status"],
        counts=views[-1]["counts"],
        revision=observed["applied_revision"],
        decisions=observed.get("action_counts", {}),
        source="native/" + name + "/host-events.jsonl",
        host_recovery_blocked=name == "compensate" and not commits,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-c/specs.zip"
    with ZipFile(package) as bundle:
        results = check_scenarios(args.directory, bundle)
    native = {
        n: check_host(args.directory, n)
        for n in (
            "corrected",
            "amendment",
            "duration",
            "added",
            "recurrence",
            "missing",
            "compensate",
        )
    }
    recall = args.directory / "native/pending-recall"
    if recall.is_dir():
        events = [
            json.loads(line)
            for line in (recall / "host-events.jsonl").read_text("utf8").splitlines()
        ]
        items = [e["item"] for e in events if e["type"] == "item.completed"]
        assert all(
            i["type"] in {"agent_message", "mcp_tool_call", "reasoning", "plan_update"}
            for i in items
        )
        tools = [i for i in items if i["type"] == "mcp_tool_call"]
        assert {i["tool"] for i in tools} == {
            "get_assignment_readiness",
            "get_assignment_change",
        } and all(i["server"] == "coursework" for i in tools)
        snapshots = {
            i["tool"]: json.loads(i["result"]["content"][0]["text"])["data"]
            for i in tools
            if i.get("result")
        }
        assert (
            snapshots["get_assignment_readiness"]["pending_observation"]["change_id"]
            == snapshots["get_assignment_change"]["change_report"]["change_id"]
        )
        answer = (recall / "host-answer.txt").read_bytes()
        assert [i["text"] for i in items if i["type"] == "agent_message"][
            -1
        ].strip() == answer.decode().strip()
        sha = hashlib.sha256(answer).hexdigest()
        assert sha == read(recall / "host-status.json")["final_answer_sha256"]
        native["pending-recall"] = dict(
            answer_sha256=sha,
            tool_attempts=len(tools),
            confirmed_writes=[],
            reassessed_criteria=[],
            admitted_source_parts=[],
            revision=snapshots["get_assignment_readiness"]["revision"],
            final_readiness=snapshots["get_assignment_change"]["pending_projection"][
                "summary_status"
            ],
            source="native/pending-recall/host-events.jsonl",
            host_recovery_blocked=False,
        )
    restart = read(args.directory / "native/restart.json")
    assert restart["before"] != restart["after"]
    output = dict(
        scenarios=results,
        native=native,
        real_process_restarts=1,
        host_attempts=sum(n["tool_attempts"] for n in native.values()),
    )
    (args.directory / "audit.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
