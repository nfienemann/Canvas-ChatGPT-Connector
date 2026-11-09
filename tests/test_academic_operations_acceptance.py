"""Exact operations archive through real synthetic imports and a running HTTP MCP service.

Opt in with BRIDGE_TEST_ACADEMIC_OPS_SUITE pointing to the supplied ZIP. Set
BRIDGE_TEST_ACADEMIC_OPS_OUTPUT to keep synthetic request/response receipts.
"""

import hashlib
import io
import json
import os
import random
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest

from canvas_bridge.domain import DomainError
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_permission_consistency_contract import client_session

BUNDLE_HASH = "6e764062a07d490c1d7ed88e05f65e8633854331c42b16b82e00514fc04cc11c"
STUDENT = "Business Student Full Media/01_STUDENT_MATERIALS/"
PARENTS = ("MKT320-A05", "OPS330-A05", "FIN310-A03")
SELECT = (
    *PARENTS,
    "MKT320-N01",
    "OPS330-N01",
    "FIN310-N02",
    "FIN310-U01",
    "BUS_SHARED_Study_Preferences",
    "FIN310-C01",
)
SCENARIOS = (
    "base",
    "single-finance",
    "deadline-extension",
    "lost-evening",
    "analysis-completed",
    "progress-isolated",
    "remaining-estimate",
    "missing-critical-source",
    "clock-advanced",
    "earlier-deadline-pin-conflict",
    "same-state-repeat",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(folder, name, data):
    (folder / (name + ".json")).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def record_input(folder, raw):
    inputs = folder / "controlled-inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / (sha(raw) + ".txt")).write_bytes(raw)


def build_identity():
    root = Path(__file__).resolve().parents[1]
    files = sorted(
        p
        for p in (root / "src/canvas_bridge").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    hashes = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in files}
    git = shutil.which("git")
    assert git
    commit = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=root, text=True).strip()  # noqa: S603 - fixed read-only arguments
    return {
        "base_commit": commit,
        "source_sha256": sha(json.dumps(hashes, sort_keys=True).encode()),
        "files": hashes,
    }


def sourced_dataset(raw, sources, titles, reviews, preference_quote):
    """Bind the supplied step map to real assignment rows and located source passages."""
    dataset = json.loads(raw)
    parents = {}
    for step in dataset["work"]:
        parent, seq = step["key"].rsplit("-S", 1)
        parents[parent] = {"key": parent, "title": titles[parent], "due": step.pop("due")}
        step.update(parent_key=parent, activity_kind="study_step")
        rows = reviews[parent]
        tasks = [r["evidence"] for r in rows if r["kind"] == "student_work"]
        files = [r["evidence"] for r in rows if r["kind"] == "deliverable"]
        # This is a host interpretation. The tool checks the actual cited version and quote.
        if seq == "6":
            step["evidence"] = [preference_quote]
        elif seq == "5":
            step["evidence"] = [
                {
                    **sources[parent],
                    "content_hash": sources[parent]["expected_hash"],
                    "locator": e["locator"],
                    "quote": e["passage"],
                }
                for e in files
            ]
        else:
            indices = {
                "MKT320-A05": [0, 1, 2, 3],
                "OPS330-A05": [0, 1, 2, 3],
                "FIN310-A03": [3, 0, 0, 1],
            }
            e = tasks[indices[parent][int(seq) - 1]]
            step["evidence"] = [
                {
                    "document_id": sources[parent]["document_id"],
                    "content_hash": e["document_version"],
                    "locator": e["locator"],
                    "quote": e["passage"],
                }
            ]
        if not step.get("effort"):
            # The missing investment case cannot ground a completed source-recovery step.
            step["evidence"] = []
    dataset["work"].extend(parents.values())
    return json.dumps(dataset).encode(), parents


def receipt_paths(tmp_path):
    archive_path = Path(os.environ["BRIDGE_TEST_ACADEMIC_OPS_SUITE"])
    assert sha(archive_path.read_bytes()) == BUNDLE_HASH
    output = Path(os.environ.get("BRIDGE_TEST_ACADEMIC_OPS_OUTPUT", tmp_path / "receipts"))
    output.mkdir(parents=True, exist_ok=True)
    return archive_path, output


@pytest.mark.skipif(
    not os.getenv("BRIDGE_TEST_ACADEMIC_OPS_SUITE"), reason="requires supplied operations suite"
)
async def test_exact_operations_over_http(
    bridge, no_lms_running, owner, token_factory, tmp_path, monkeypatch
):
    archive_path, output = receipt_paths(tmp_path)
    build = build_identity()
    record(output, "build-identity", build)
    parser = (
        Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
        if os.name == "nt"
        else tmp_path / "parser"
    )
    bridge.settings.file_reading_enabled = True
    bridge.settings.parser_root = bridge.settings.parser_runtime_root = parser
    clock = datetime.fromisoformat("2026-10-29T12:00:00-04:00")
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: clock)

    async def ingest(raw, name, previous=None, *, course="independent"):
        mime = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}[
            Path(name).suffix
        ]
        replace = (
            {"replace_id": previous["document_id"], "expected_hash": previous["expected_hash"]}
            if previous
            else {}
        )
        ident = await bridge.independent.ingest(
            owner,
            raw,
            name,
            mime,
            course=course,
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
            **replace,
        )
        row = bridge.independent.require(owner, ident)
        assert row.version_hash == sha(raw)
        if name in {"bound-study-steps.txt", "controlled-input.txt", "reimported-study-steps.txt"}:
            record_input(output, raw)
        return {"document_id": ident, "expected_hash": row.version_hash}

    async with client_session(no_lms_running, token_factory(), read_timeout=90) as session:

        async def call(label, tool, args, allowed=("ok", "partial_data")):
            response = await session.call_tool(tool, args)
            body = response.structuredContent
            record(
                output,
                label,
                {
                    "base_commit": build["base_commit"],
                    "source_sha256": build["source_sha256"],
                    "tool": tool,
                    "arguments": args,
                    "result": body,
                },
            )
            assert body and body["status"] in allowed, (
                label,
                body and (body["summary"], body["data"].get("reason_code")),
            )
            return body

        async def workflow(label, **request):
            return await call(label, "run_independent_academic_workflow", {"request": request})

        sources, titles, reviews = {}, {}, {}
        with (
            ZipFile(archive_path) as bundle,
            ZipFile(io.BytesIO(bundle.read("fixture/business-coursework.zip"))) as student,
        ):
            members = [n for n in student.namelist() if n.startswith(STUDENT)]
            for key in SELECT:
                (member,) = [
                    n for n in members if PurePosixPath(n).name.startswith((key + "_", key + "."))
                ]
                name = PurePosixPath(member).name
                if key == "OPS330-N01":
                    # Exact fixture triggers the existing privacy-withholding boundary.
                    with pytest.raises(DomainError) as denied:
                        await ingest(student.read(member), name)
                    assert denied.value.reason_code == "EGRESS_REVIEW_REQUIRED"
                    record(
                        output,
                        "withheld-" + key,
                        {
                            "file_sha256": sha(student.read(member)),
                            "reason_code": denied.value.reason_code,
                        },
                    )
                    continue
                sources[key] = await ingest(student.read(member), name)
                read = await call(
                    "source-" + key,
                    "read_local_document",
                    {"document_id": sources[key]["document_id"], "limit": 5},
                )
                assert read["data"]["content_hash"] == sources[key]["expected_hash"]
                body = read["data"]["parts"][0]["text"]
                if key in PARENTS:
                    titles[key] = body.splitlines()[0].lstrip("# ")
                if key == "BUS_SHARED_Study_Preferences":
                    preference_quote = {
                        "document_id": sources[key]["document_id"],
                        "content_hash": sources[key]["expected_hash"],
                        "locator": "Part 1",
                        "quote": next(
                            line for line in body.splitlines() if "checking file names" in line
                        ),
                    }
            record(output, "selected-sources", sources)
            case_member = next(
                n for n in members if PurePosixPath(n).name.startswith("FIN310-C01_")
            )
            absent = [
                k
                for k in ("MKT320-C01", "OPS330-N02", "OPS330-R04")
                if not any(PurePosixPath(n).name.startswith(k + "_") for n in members)
            ]
            assert len(absent) == 3
            for parent, extra in zip(
                PARENTS, [["MKT320-N01"], ["OPS330-N01"], ["FIN310-N02", "FIN310-U01"]], strict=True
            ):
                documents = [
                    {**sources[parent], "role": "instructions"},
                    *[
                        {**sources[k], "role": "rubric" if k.endswith("U01") else "schedule"}
                        for k in extra
                        if k in sources
                    ],
                ]
                req = await workflow(
                    "requirements-" + parent, capability="requirements", documents=documents
                )
                reviews[parent] = req["data"]["source_work_steps"]["steps"]
                assert all(
                    r["parent_key"] == parent
                    and r["evidence"]["document_version"] == sources[parent]["expected_hash"]
                    for r in reviews[parent]
                )
                assert len([r for r in reviews[parent] if r["kind"] == "deliverable"]) == (
                    4 if parent.startswith("FIN") else 3
                )
            raw_selection = canonical_selection = None
            baseline_events = []
            for scenario in SCENARIOS:
                scenario_path = "scenarios/" + (
                    "base" if scenario == "same-state-repeat" else scenario
                )
                raw = bundle.read(scenario_path + "/academic-input.txt")
                context = json.loads(bundle.read(scenario_path + "/scenario.json"))
                assert sha(raw) == context["input_sha256"]
                clock = datetime.fromisoformat(context["as_of"])
                request = json.loads(bundle.read(scenario_path + "/request.json"))
                raw_selection = await ingest(raw, "controlled-input.txt", raw_selection)
                request["dataset"] = raw_selection
                invalid = scenario == "earlier-deadline-pin-conflict"
                allowed = ("needs_input",) if invalid else ("ok", "partial_data")
                result = await call(
                    "plan-" + scenario,
                    "run_independent_academic_workflow",
                    {"request": request},
                    allowed,
                )
                if invalid:
                    assert result["data"]["reason_code"] == "PIN_CONFLICTS_WITH_SOURCE_TIMING"
                else:
                    totals = result["data"]["effort_summary"]
                    assert (
                        totals["known_remaining_minutes"]
                        == totals["allocated_work_minutes"]
                        + totals["total_known_unallocated_minutes"]
                    )
                canonical, parents = sourced_dataset(
                    raw, sources, titles, reviews, preference_quote
                )
                prior = canonical_selection
                canonical_selection = await ingest(canonical, "bound-study-steps.txt", prior)
                assert prior is None or canonical_selection["document_id"] == prior["document_id"]
                documents = [{**sources[p], "role": "instructions"} for p in parents] + [
                    sources["BUS_SHARED_Study_Preferences"]
                ]
                if "FIN310-A03" in parents:
                    selected_case = sources["FIN310-C01"]
                    if scenario == "missing-critical-source":
                        # Each transition starts from baseline. Drop only this scenario's
                        # copy and send its actual revoked selection to the adapter.
                        selected_case = await ingest(
                            student.read(case_member),
                            PurePosixPath(case_member).name,
                            course="synthetic-dropout",
                        )
                        bridge.independent.delete(owner, selected_case["document_id"])
                    documents.append(selected_case)
                grounded = await call(
                    "grounded-" + scenario,
                    "run_independent_academic_workflow",
                    {
                        "request": {
                            **request,
                            "dataset": canonical_selection,
                            "documents": documents,
                        }
                    },
                    allowed,
                )
                if not invalid:
                    data = grounded["data"]
                    assert data["effort_summary"] == totals
                    assert {check["work_id"] for check in totals["receipt_checks"]} == {
                        parent + "-S6" for parent in parents
                    }
                    assert all(
                        t["status"]
                        == (
                            "source_review_required"
                            if scenario == "missing-critical-source"
                            and t["work_id"] == "FIN310-A03-S1"
                            else "cited_passages_located"
                        )
                        for t in data["study_step_review"]
                    )
                    assert len(data["study_step_review"]) == len(json.loads(raw)["work"])
                    if scenario == "missing-critical-source":
                        assert (
                            data["excluded_sources"]
                            and "FIN310-A03-S1" in totals["unknown_effort_work_ids"]
                        )
                    else:
                        assert not data["excluded_sources"]
                    if scenario == "base":
                        (constraint,) = data["requirement_review"]["conflicts"]
                        assert constraint["parent_key"] == "FIN310-A03"
                        assert (
                            constraint["evidence"]["source_version"]
                            == sources["FIN310-A03"]["expected_hash"]
                        )
                        assert {(r["minimum"], r["maximum"]) for r in constraint["candidates"]} == {
                            (1000, 1400),
                            (800, 1000),
                        }
                        assert (
                            totals["allocated_work_minutes"],
                            totals["capacity_blocked_minutes"],
                            totals["dependency_blocked_minutes"],
                        ) == (1010, 70, 300)
                    if scenario == "lost-evening":
                        assert (
                            totals["allocated_work_minutes"],
                            totals["capacity_blocked_minutes"],
                            totals["dependency_blocked_minutes"],
                        ) == (825, 170, 385)
                    if scenario == "progress-isolated":
                        assert (
                            totals["allocated_work_minutes"] == 240
                            and len(totals["completed_work_ids"]) == 2
                        )
                    if scenario == "clock-advanced":
                        assert [p["work_id"] for p in data["pin_conflicts"]] == ["MKT320-A05-S6"]
                calendar = {
                    "calendar_id": "synthetic",
                    "timezone": "America/New_York",
                    "retrieved_at": clock.isoformat(),
                    "window_start": clock.isoformat(),
                    "window_end": (clock + timedelta(days=12)).isoformat(),
                    "pagination_complete": True,
                    "mapping_search_complete": True,
                    "events": baseline_events,
                }
                cal = (
                    await workflow(
                        "calendar-" + scenario,
                        capability="calendar",
                        dataset=canonical_selection,
                        calendar=calendar,
                    )
                )["data"]
                proposals = cal["proposals"]
                assert (
                    not cal["provider_writes_executed"]
                    and not cal["deletions"]
                    and not cal["ambiguous_matches"]
                )
                if scenario == "base":
                    assert {p["work_id"] for p in proposals} == set(PARENTS)
                    baseline_events = [
                        dict(
                            id="fixture-" + p["work_id"],
                            title=p["title"],
                            start=p["timing"]["start"],
                            end=p["timing"]["end"],
                            status="confirmed",
                            bridge_marker=p["bridge_marker"],
                            version="1",
                        )
                        for p in proposals
                    ]
                elif scenario in ("deadline-extension", "earlier-deadline-pin-conflict"):
                    assert [(p["work_id"], p["action"]) for p in proposals] == [
                        ("MKT320-A05", "update")
                    ]
                    events = [dict(e) for e in baseline_events]
                    event = next(e for e in events if e["id"] == proposals[0]["event_id"])
                    event.update(
                        start=proposals[0]["timing"]["start"],
                        end=proposals[0]["timing"]["end"],
                        version="2",
                    )
                    confirmed = await workflow(
                        "confirmed-" + scenario,
                        capability="calendar",
                        dataset=canonical_selection,
                        calendar={**calendar, "events": events},
                    )
                    assert confirmed["data"]["proposals"] == []
                else:
                    assert proposals == []
                if prior and prior != canonical_selection:
                    stale = await call(
                        "stale-" + scenario,
                        "run_independent_academic_workflow",
                        {"request": {"capability": "planning", "dataset": prior}},
                        ("source_changed",),
                    )
                    assert not stale.get("sources")
            # Calendar readback inputs simulate user-confirmed events. No provider is called.
            base_context = {**calendar, "events": baseline_events}
            for label, extra in [
                ("stale-calendar", {"retrieved_at": (clock - timedelta(hours=1)).isoformat()}),
                ("incomplete-calendar", {"mapping_search_complete": False}),
            ]:
                observed = await workflow(
                    label,
                    capability="calendar",
                    dataset=canonical_selection,
                    calendar={**base_context, **extra},
                )
                assert (
                    observed["data"]["status"] == "needs_input"
                    and not observed["data"]["proposals"]
                )
            reimported = await ingest(
                canonical, "reimported-study-steps.txt", course="synthetic-reimport"
            )
            assert reimported["document_id"] != canonical_selection["document_id"]
            reread = await workflow(
                "reimport-ambiguity",
                capability="calendar",
                dataset=reimported,
                calendar=base_context,
            )
            assert not reread["data"]["proposals"] and len(reread["data"]["ambiguous_matches"]) == 3
            reference = json.loads((output / "plan-base.json").read_text(encoding="utf-8"))[
                "result"
            ]["data"]
            for seed in range(5):
                dataset = json.loads(raw)
                random.Random(seed).shuffle(dataset["work"])
                raw_selection = await ingest(
                    json.dumps(dataset).encode(), "controlled-input.txt", raw_selection
                )
                obs = await workflow(
                    "order-" + str(seed),
                    capability="planning",
                    dataset=raw_selection,
                    plan=request["plan"],
                )
                for field in ("blocks", "effort_summary", "pin_conflicts", "unmet_work"):
                    assert obs["data"][field] == reference[field]
            # Deletion of a source referenced by an integrity context remains fail-closed.
            bridge.independent.delete(owner, canonical_selection["document_id"])
            denied = await call(
                "reimport-after-revocation",
                "run_independent_academic_workflow",
                {
                    "request": {
                        "capability": "calendar",
                        "dataset": reimported,
                        "calendar": base_context,
                    }
                },
                ("permission_denied",),
            )
            assert not denied["sources"]
    assert build_identity() == build, (
        "Product source changed during acceptance; rerun the sequence."
    )
