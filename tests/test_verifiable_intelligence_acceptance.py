"""Replay the hash-pinned VAI student materials through authenticated local HTTP MCP.

BRIDGE_TEST_VAI_SUITE selects the supplied ZIP. BRIDGE_TEST_VAI_OUTPUT retains
synthetic receipts. The plugin receives only student files or labeled mutations.
"""

import json
import os
import platform
import random
from datetime import datetime
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest
from sqlalchemy.exc import SQLAlchemyError

from tests.test_academic_operations_acceptance import build_identity, record, sha
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally

PACKAGE = "deb9d780c612e3329f6ba8ef4574f920505efa7614e60b5d3ef393011cc153f9"


def claim_signature(data):
    # Preserve every field of the evaluated claims, including their citations,
    # versions, acquisition times and coverage. Only set ordering is incidental.
    review = data["requirement_review"]
    conflicts = []
    for row in review["conflicts"]:
        left, right = sorted(
            (row["left"], row["right"]), key=lambda r: json.dumps(r, sort_keys=True)
        )
        conflicts.append(dict(row, left=left, right=right))
    groups = [
        review["rules"],
        conflicts,
        data["deadline_review"]["obligations"],
        data["source_provenance"],
        data["coverage"],
        data["source_versions"],
        data["excluded_sources"],
    ]
    return [sorted(json.dumps(r, sort_keys=True) for r in rows) for rows in groups]


def replay_paths(tmp_path):
    path = Path(os.environ["BRIDGE_TEST_VAI_SUITE"])
    assert sha(path.read_bytes()) == PACKAGE
    output = Path(os.getenv("BRIDGE_TEST_VAI_OUTPUT", tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    return path, output


@pytest.mark.skipif(not os.getenv("BRIDGE_TEST_VAI_SUITE"), reason="requires supplied VAI suite")
async def test_source_replay(
    bridge, owner, token_factory, no_lms_running, parsed_locally, tmp_path, monkeypatch
):
    path, output = replay_paths(tmp_path)
    clock = datetime.fromisoformat("2026-10-29T12:00:00-04:00")
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: clock)
    build = build_identity()
    record(output, "build", dict(build, runtime=platform.python_version(), clock=clock.isoformat()))
    sources, inputs = {}, {}
    with ZipFile(path) as bundle:
        for item in json.loads(bundle.read("evidence/fixture_files.json")):
            name = PurePosixPath(item["zip_entry"]).name
            raw = bundle.read(item["fixture_path"])
            assert sha(raw) == item["sha256"]
            ident = await bridge.independent.ingest(
                owner,
                raw,
                name,
                "text/plain" if name.endswith(".txt") else "text/markdown",
                own_material=True,
                share_text=True,
                allow_academic_analysis=True,
            )
            key = PurePosixPath(item["fixture_path"]).stem
            inputs[key] = (name, raw)
            sources[key] = {"document_id": ident, "expected_hash": sha(raw)}
    record(output, "sources", {k: dict(v, filename=inputs[k][0]) for k, v in sources.items()})

    async with client_session(no_lms_running, token_factory(), read_timeout=90) as session:

        async def call(label, tool, arguments):
            response = await session.call_tool(tool, arguments)
            body = response.structuredContent
            record(
                output,
                label,
                {"tool": tool, "arguments": arguments, "result": body, "error": response.isError},
            )
            return body

        async def workflow(label, keys, capability="requirements"):
            return await call(
                label,
                "run_independent_academic_workflow",
                {
                    "request": {
                        "capability": capability,
                        "documents": [dict(sources[k], role="instructions") for k in keys],
                    }
                },
            )

        released = {}
        for key, selection in sources.items():
            read = await call(
                "read-" + key,
                "read_local_document",
                {"document_id": selection["document_id"], "limit": 5},
            )
            assert read["data"]["content_hash"] == selection["expected_hash"]
            released[key] = "\n".join(part["text"] for part in read["data"]["parts"])
        # Evaluator only. Check the released passage separately from the original
        # hash: privacy filtering withholds the profile identifier in one quote.
        with ZipFile(path) as bundle:
            oracle = json.loads(bundle.read("source_oracle.json"))
        for case in oracle["cases"]:
            for source in case["sources"]:
                text = released[PurePosixPath(source["fixture_path"]).stem]
                for span in source["quotes"]:
                    quote = span["quote"]
                    if source["source_id"] == "BUS-PREF-01" and "Student ID:" in quote:
                        prefix, identifier = quote.split("Student ID:", 1)
                        assert prefix.rstrip() in text and identifier.strip() not in text
                        assert "[private identifier]" in text
                    else:
                        assert quote in text, (case["id"], source["source_id"], span["line_start"])

        finance = ["SRC002", "SRC003", "SRC005"]
        marketing = ["SRC007", "SRC009"]
        operations = ["SRC010", "SRC011"]
        baseline = {}
        for case, keys in {
            "O01": finance,
            "O02": marketing,
            "O03": ["SRC007", "SRC008"],
            "O04": operations,
            "O05": ["SRC006", "SRC008", "SRC009"],
            "O06": ["SRC001"],
            "O07": ["SRC004"],
            "O08": ["SRC006", "SRC001"],
        }.items():
            body = await workflow(case, keys, "consistency")
            assert body["status"] in {"ok", "partial_data"}, (case, body["summary"])

            baseline[case] = body["data"]

        conflicts = baseline["O01"]["requirement_review"]["conflicts"]
        assert conflicts and all(c["certainty"] == "unresolved_contradiction" for c in conflicts)
        assert all(
            {(c[k]["minimum"], c[k]["maximum"]) for k in ("left", "right")}
            == {(800, 1000), (1000, 1400)}
            for c in conflicts
        )
        ops = baseline["O04"]["requirement_review"]
        assert not ops["conflicts"]
        assert {
            (r["minimum"], r["maximum"])
            for r in ops["rules"]
            if r["type"] == "word_count" and r["mandatory"]
        } == {(1600, 2000)}
        deliverables = [
            r for r in baseline["O03"]["source_work_steps"]["steps"] if r["kind"] == "deliverable"
        ]
        assert len(deliverables) == 3 and all(r["parent_key"] == "MKT320-A05" for r in deliverables)
        assert not baseline["O07"]["deadline_review"]["obligations"]

        for case, keys in [("O01", finance), ("O02", marketing), ("O04", operations)]:
            for seed in [None, 11, 29, 47]:
                order = (
                    list(reversed(keys))
                    if seed is None
                    else random.Random(seed).sample(keys, len(keys))
                )
                reordered = await workflow(f"M01-{case}-{seed}", order, "consistency")
                assert claim_signature(reordered["data"]) == claim_signature(baseline[case])
        duplicate = await workflow("M02-duplicate", [*marketing, marketing[0]])
        assert duplicate is None or duplicate["status"] not in {"ok", "partial_data"}
        unrelated = await workflow("M02-unrelated", [*marketing, "SRC004"], "consistency")
        assert (
            unrelated["data"]["deadline_review"]["obligations"]
            == baseline["O02"]["deadline_review"]["obligations"]
        )

        original_read = bridge.independent.read

        def transient(principal, ident, **kwargs):
            if ident == sources["SRC008"]["document_id"] and kwargs.get("study"):
                raise SQLAlchemyError("synthetic retrieval failure")
            return original_read(principal, ident, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(bridge.independent, "read", transient)
            partial = await workflow("M04-degraded", ["SRC007", "SRC008"])
        assert partial["data"]["excluded_sources"][0]["reason_code"] == "LOCAL_STORAGE_UNAVAILABLE"
        restored = await workflow("M04-restored", ["SRC007", "SRC008"])
        assert restored["data"]["coverage"] == baseline["O03"]["coverage"]
        assert partial["data"]["source_work_steps"] == restored["data"]["source_work_steps"]
        assert sources["SRC008"]["document_id"] not in json.dumps(partial)
        from canvas_bridge.storage import IndependentResource

        with bridge.store.transaction() as db:
            row = db.get(IndependentResource, sources["SRC008"]["document_id"])
            row.provenance = dict(row.provenance, share_text=False)
        revoked = await workflow("M07-revoked", ["SRC007", "SRC008"])
        assert sources["SRC008"]["document_id"] not in json.dumps(revoked)
        await workflow("M07-control", ["SRC007"])

        # Replace the already-read notice before the final version check.
        import canvas_bridge.independent_intelligence as adapter

        name, old = inputs["SRC003"]
        new = old.replace(b"November 8", b"November 9")
        original_before = adapter.before_tool

        async def replace_between_reads(*args, **kwargs):
            if args[3]["document_id"] == sources["SRC005"]["document_id"]:
                await bridge.independent.ingest(
                    owner,
                    new,
                    name,
                    "text/markdown",
                    own_material=True,
                    share_text=True,
                    allow_academic_analysis=True,
                    replace_id=sources["SRC003"]["document_id"],
                    expected_hash=sha(old),
                )
            return await original_before(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(adapter, "before_tool", replace_between_reads)
            stale = await workflow("M03-stale", finance, "consistency")
        assert stale["status"] == "source_changed" and not stale["sources"]
        sources["SRC003"]["expected_hash"] = sha(new)
        fresh = await workflow("M03-refreshed", finance, "consistency")
        changed = [
            r
            for r in fresh["data"]["deadline_review"]["obligations"]
            if r["evidence"]["source_id"] == sources["SRC003"]["document_id"]
        ]
        assert any(r["day"] == 9 and r["assessment_id"] == "FIN310-A03" for r in changed)
        assert all(r["evidence"]["source_version"] == sha(new) for r in changed)
        assert fresh["data"]["requirement_review"] == baseline["O01"]["requirement_review"]
    assert build_identity() == build


def test_submission_and_scope_mutations(tmp_path):
    from datetime import timedelta

    from pydantic import ValidationError

    from canvas_bridge.academic.evidence_graph import (
        Builder,
        EntityKind,
        EvidenceGraph,
        EvidenceSession,
    )
    from canvas_bridge.evidence import reconcile_states
    from tests.test_evidence_graph import SCOPE, observation

    _, output = replay_paths(tmp_path) if os.getenv("BRIDGE_TEST_VAI_SUITE") else (None, tmp_path)
    now = datetime.fromisoformat("2026-10-29T12:05:00-04:00")
    scope = SCOPE.model_copy(update={"course_id": "MKT320"})
    refs = ["test_current_assignment_view", "test_current_submission_view"]
    states = ["submitted", "not_submitted"]
    current = [
        {
            "source": ref,
            "state": state,
            "observed_at": now.isoformat(),
            "assignment_id": "MKT320-A05",
            "course_id": scope.course_id,
        }
        for ref, state in zip(refs, states, strict=True)
    ]
    conflict = reconcile_states(current)
    assert (
        conflict["state"] == "unknown"
        and conflict["conflict"]
        and conflict["observations"] == current
    )

    def synthetic_snapshot(state, when):
        b = Builder(scope, complete=True)
        parent = b.entity(EntityKind.ASSIGNMENT, "MKT320-A05")
        provider = observation(
            b,
            ref=refs[0],
            version=state,
            course_id=scope.course_id,
            observed_at=when,
            verified_at=when,
        )
        b.assert_fact(parent, "submission_state", state, sources=(provider,))
        student = observation(
            b,
            ref="student_declaration",
            course_id=scope.course_id,
            observed_at=now,
            verified_at=now,
        )
        b.assert_fact(
            parent, "personal_completion", "done", sources=(student,), basis="user_provided"
        )
        return b.build(), parent

    later = now + timedelta(minutes=15)
    session = EvidenceSession(
        scope, authorize=lambda g: None, purpose="study", recipient="local", clock=lambda: later
    )
    first, parent = synthetic_snapshot("not_submitted", now)
    second, same_parent = synthetic_snapshot("submitted", later)
    assert parent == same_parent
    session.update(first)
    session.update(second)
    delta = session.history()
    (change,) = delta["fact_changes"]
    assert change["change_kind"] == "value_changed" and change["predicate"] == "submission_state"
    assert first.assertions[-1].basis == "user_provided"
    record(
        output,
        "M05",
        {
            "simultaneous": conflict,
            "personal": first.assertion_view(first.assertions[-1]),
            "history": delta,
        },
    )
    for field, value in [("principal", "second-synthetic-principal"), ("course_id", "FIN310")]:
        mutated = first.model_dump(mode="json")
        mutated["scope"][field] = value
        with pytest.raises(ValidationError, match="boundary"):
            EvidenceGraph.model_validate(mutated)
    record(
        output,
        "M06",
        {
            "control_subject": parent,
            "control": session.query(parent, "personal_completion"),
            "rejected_scope_mutations": ["principal", "course_id"],
        },
    )


@pytest.mark.parametrize(
    ("statement", "expected_conflicts"),
    [
        (
            "The current brief states 1000-1400 words, while the archived rubric states "
            "800-1000; the packet does not explicitly resolve that conflict.",
            1,
        ),
        ("Prices range from 10-20 to 30-40; the brief does not resolve that conflict.", 0),
        ("The brief lists 800-1000 words and 30-40 tables; it does not resolve that conflict.", 0),
    ],
)
def test_reported_range_is_a_scoped_plan_constraint(statement, expected_conflicts):
    from canvas_bridge.academic.study_steps import reported_plan_conflicts
    from tests.test_academic_intelligence import source_doc
    from tests.test_academic_operations import dataset

    parent = "FIN310-A03"
    doc = dict(source_doc(f"{parent} | FIN310 | Brief\n{statement}"), role="instructions")
    assert (
        len(reported_plan_conflicts(dataset([{"key": parent, "title": "Memo"}]), [doc]))
        == expected_conflicts
    )
    assert reported_plan_conflicts(dataset([{"key": "MKT320-A05", "title": "Memo"}]), [doc]) == []
