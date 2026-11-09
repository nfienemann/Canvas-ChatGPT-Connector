"""Synthetic Phase B journeys with independent host contexts and a restarted SQLite-backed service."""

import asyncio
import contextlib
import json
import multiprocessing
import os
import socket
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
import uvicorn

from canvas_bridge.app import create_app
from canvas_bridge.config import Settings
from canvas_bridge.processes.readiness import Review
from tests.conftest import bridge as bridge_fixture
from tests.test_permission_consistency_contract import client_session
from tests.test_phase_a_benchmark import HOST_TOOLS, review_host, save, sha
from tests.test_recovery_independence import parsed_locally as parsed_locally

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "benchmarks/academic/phase-b/specs.zip"
NATIVE = os.getenv("BRIDGE_PHASE_B_OUTPUT")


def member(name):
    with ZipFile(BUNDLE) as archive:
        return archive.read("phase_b_readiness/" + name)


def serve(raw, sock):
    settings = Settings.model_validate_json(raw)
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        server = uvicorn.Server(
            uvicorn.Config(create_app(settings, bridge), log_level="error", access_log=False)
        )
        server.run(sockets=[sock])


@contextlib.asynccontextmanager
async def running(settings):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        settings.resource_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        process = multiprocessing.get_context("spawn").Process(
            target=serve, args=(settings.model_dump_json(), sock)
        )
        process.start()
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                async with asyncio.timeout(60):
                    while process.is_alive():
                        try:
                            if (
                                await client.get(
                                    settings.resource_url + "/.well-known/oauth-protected-resource"
                                )
                            ).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise RuntimeError("Service stopped during startup.")
            yield process.pid
        finally:
            process.terminate()
            await asyncio.to_thread(process.join, 20)
            assert not process.is_alive()


async def import_case(bridge, owner, case):
    index = json.loads(member("reference/phase_a_fixture/index.json"))
    packet = next(c for c in index["cases"] if c["case_id"] == case)
    bindings = []
    roles = {
        "brief.md": "brief",
        "deck.pptx": "artifact",
        "references.md": "reference",
        "rehearsal.txt": "measurement",
    }
    for f in packet["model_input_files"]:
        raw = member("reference/phase_a_fixture/" + f["path"])
        assert sha(raw) == f["sha256"]
        name = Path(f["path"]).name
        mime = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }[Path(name).suffix]
        ident = await bridge.independent.ingest(
            owner,
            raw,
            name,
            mime,
            course="BenchLink",
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
        )
        bindings.append(
            dict(
                logical_id=roles[name],
                role=roles[name],
                document_id=ident,
                content_hash=f["sha256"],
            )
        )
    if case == "missing_deck":
        bindings.append(
            dict(logical_id="artifact", role="artifact", document_id=None, content_hash=None)
        )
    return bindings


@pytest.mark.skipif(not NATIVE, reason="Opt-in real Codex host benchmark")
@pytest.mark.parametrize("case", ["baseline", "missing_deck"])
async def test_host_journey(case, settings, owner, token_factory, tmp_path):
    from canvas_bridge.processes.readiness import Progress

    settings.database_url = "sqlite:///" + str(tmp_path / "state.db")
    settings.process_features_enabled = True
    settings.file_reading_enabled = True
    settings.parser_runtime_root = settings.parser_root = (
        Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    )
    out = Path(NATIVE) / case
    out.mkdir(parents=True)
    workdir = tmp_path / "host"
    workdir.mkdir()
    tools = [
        *HOST_TOOLS,
        "save_assignment_readiness",
        "get_assignment_readiness",
        "record_readiness_progress",
    ]
    instruction = (
        "Use only the coursework MCP tools; no filesystem, shell, external or other tools. Follow read_local_document continuations. Use run_independent_academic_workflow for a requirements review. For saves use the exact selected bindings, brief requirement IDs and governed passages. Select the appropriate coverage_rule, inspected artifact parts for absence/all_claims and measured_artifact_hash for recorded_run. Cite precise source quotes; notes means native speaker notes. Use a stable machine-readable gap_kind, action and completion_condition for each needs_work criterion. After a confirmed save get_assignment_readiness to report its actual projection. The backend schema for the review argument is "
        + json.dumps(Review.model_json_schema())
        + "; progress argument: "
        + json.dumps(Progress.model_json_schema())
    )

    async def host(name, prompt, context):
        folder = out / name
        folder.mkdir()
        answer = await review_host(
            settings.resource_url,
            token_factory(),
            member("prompts/" + prompt + ".md").decode()
            + "\nSelected context: "
            + json.dumps(context),
            workdir,
            folder,
            "native",
            tools=tools,
            instructions=instruction,
        )
        assert answer
        return [
            json.loads(line)["item"]
            for line in (folder / "native-events.jsonl").read_text("utf8").splitlines()
            if json.loads(line)["type"] == "item.completed"
            and json.loads(line)["item"]["type"] == "mcp_tool_call"
        ]

    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        bindings = await import_case(bridge, owner, case)
        ctx = dict(
            assignment_id="BenchLink",
            course="BenchLink",
            term="fall-2026",
            expected_revision=0,
            bindings=bindings,
        )
        async with running(settings) as pid:
            async with client_session(settings.resource_url, token_factory()) as session:
                catalog = await session.list_tools()
                save(
                    out,
                    "schemas.json",
                    [t.model_dump(mode="json") for t in catalog.tools if t.name in tools],
                )
            await host(
                "save", "missing_deck" if case == "missing_deck" else "review_and_remember", ctx
            )
            inventory = bridge.processes.repository.inventory(owner)
            save(out, "inventory.json", inventory)
            assert len(inventory["records"]) == 1
            ident = inventory["records"][0]["id"]
        async with running(settings) as pid2:
            save(out, "restart.json", dict(before_pid=pid, after_pid=pid2, same_database=True))
            await host("recall", "recall_readiness", dict(record_id=ident))
            if case == "baseline":
                await host("progress", "progress_and_plan", dict(record_id=ident))
                revised = await import_case(bridge, owner, "corrected")
                current = bridge.processes.repository.read(owner, ident)
                await host(
                    "revised",
                    "review_revised_version",
                    ctx
                    | dict(bindings=revised, expected_revision=current.revision, record_id=ident),
                )
            current = bridge.processes.repository.read(owner, ident)
            save(
                out, "persisted.json", current.model_dump(mode="json", exclude={"scope", "sources"})
            )


def authored_review(bindings, label):
    """Translate only the supplied evaluator payload. Native host tests never call this adapter."""
    d = json.loads(member("fixtures/readiness_inputs.json"))
    payload = next(
        a for a in d["assessment_payloads"] if a["assessment_id"] == "BL-ASSESS-" + label + "-01"
    )
    evidence = {e["evidence_id"]: e for e in d["evidence_catalog"]}
    logical = {b["content_hash"]: b["logical_id"] for b in bindings}

    def anchor(key):
        e = evidence[key]
        loc = e["locator"]
        return dict(
            source=logical[e["source_sha256"]],
            part=loc.get("slide_number", 1),
            surface={"native_notes": "notes", "slide": "slide"}.get(loc.get("surface"), "text"),
            quote=e["quote"],
        )

    rows = []
    for criterion, r in zip(
        d["requirement_set"]["requirements"], payload["requirement_results"], strict=True
    ):
        ident = r["requirement_id"]
        status = r["assessment_status"]
        gap = r.get("gap_kind")
        coverage = r["evidence_coverage"]
        rule = {"PA-R03": "all_claims", "PA-R04": "recorded_run"}.get(ident, "passage")
        if ident == "PA-R01" and status != "satisfied":
            rule = "absence"
        ev = [anchor(k) for k in r["evidence_refs"] if evidence[k]["source_sha256"] in logical]
        if ident == "PA-R03" and label == "BASELINE":
            ev.append(anchor("EV-BASE-NOTES"))
        rows.append(
            dict(
                requirement_id=ident,
                criterion=criterion["criterion"],
                governing=anchor("EV-" + ident),
                applicability_basis="Explicit in the assignment brief.",
                assessment_status=status,
                rationale=r["rationale"],
                coverage=coverage,
                coverage_rule=rule,
                evidence=ev,
                candidate_assessments=[
                    dict(
                        candidate_id=c["candidate_id"],
                        assessment_status=c["assessment_status"],
                        claim=c["claim"],
                        evidence=[anchor(k) for k in c["evidence_refs"]],
                    )
                    for c in r.get("candidate_assessments", [])
                ],
                reviewed_extent=[
                    dict(source="artifact", parts=list(range(1, 6 if label == "PARTIAL" else 8)))
                ]
                if rule in {"absence", "all_claims"} and label != "MISSING"
                else [],
                followup=r.get("unknown_reason"),
                gap_kind=gap,
                action=("Revise " + criterion["title"]) if gap else None,
                completion_condition=criterion["criterion"] if gap else None,
                measured_artifact_hash=next(
                    (b["content_hash"] for b in bindings if b["role"] == "artifact"), None
                )
                or payload["binding"]["artifact_sha256"]
                if ident == "PA-R04"
                else None,
            )
        )
    return Review(
        assignment_id="primary",
        course="BenchLink",
        term="fall-2026",
        expected_revision=0,
        idempotency_key=label,
        membership_complete=True,
        review_scope="Assignment brief",
        bindings=bindings,
        requirements=rows,
    )


def test_projection_controls():
    from canvas_bridge.processes.readiness import summarize

    for case in json.loads(member("fixtures/contract_controls.json"))["controls"]:
        rows = [
            r
            | {
                "assessment_status": r["assessment_status"]
                if r["version_match"] == "current"
                else "unknown"
            }
            for r in case["rows"]
        ]
        result = summarize(rows, case["membership_complete"])
        assert result["summary_status"] == case["expected_summary_status"], case["id"]
        for field, key in [
            ("optional", "expected_optional"),
            ("applicable_required", "expected_applicable_required"),
            ("unknown_applicability_required", "expected_unknown_applicability_required"),
            ("not_applicable_required", "expected_excluded_required"),
        ]:
            assert result["counts"][field] == case[key]


async def test_authored_journeys(bridge, owner, tmp_path, request):
    if not NATIVE:
        request.getfixturevalue("parsed_locally")
    import copy
    from datetime import timedelta

    from canvas_bridge.domain import DomainError
    from canvas_bridge.planning import PlanRequest
    from canvas_bridge.processes import readiness

    bridge.settings.process_features_enabled = True
    bridge.settings.file_reading_enabled = True
    if os.name == "nt":
        bridge.settings.parser_runtime_root = bridge.settings.parser_root = (
            Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
        )
    service = bridge.processes
    baseline = await import_case(bridge, owner, "baseline")
    corrected = await import_case(bridge, owner, "corrected")
    missing = [
        b if b["role"] != "artifact" else b | dict(document_id=None, content_hash=None)
        for b in baseline
    ]
    expected = {
        e["scenario_id"]: e
        for e in json.loads(member("fixtures/expected_readiness.json"))["results"]
    }
    actual = {}

    def check(number, result):
        name = f"PHB-S{number:02d}"
        d = result.data
        actual[name] = d
        target = expected[name]
        assert (
            d["summary_status"],
            d["counts"],
            len(d["remaining_work"]),
            len(d["review_followups"]),
        ) == (
            target["summary_status"],
            target["counts"],
            target["current_work_item_count"],
            target["review_followup_count"],
        ), name

    first = authored_review(baseline, "BASELINE")
    receipt = readiness.save(service, owner, first).data
    key = receipt["record_id"]

    def view(**kwargs):
        return readiness.view(service, owner, key, **kwargs)

    check(1, view())
    check(2, view())
    assert readiness.save(service, owner, first).data == receipt
    correct = authored_review(corrected, "CORRECTED")
    original = view().data
    selection = readiness.Selection(
        requirement_set_revision=original["requirement_set_revision"], bindings=corrected
    )
    check(7, view(selection=selection))
    # Reimport selects the same artifact content within this assignment.
    duplicate = await import_case(bridge, owner, "baseline")
    check(
        6,
        view(
            selection=readiness.Selection(
                requirement_set_revision=original["requirement_set_revision"], bindings=duplicate
            )
        ),
    )
    task = original["remaining_work"][0]["work_id"]
    progress = readiness.Progress(
        record_id=key,
        work_id=task,
        expected_revision=1,
        idempotency_key="done",
        progress_state="student_marked_done",
    )
    readiness.update_progress(service, owner, progress)
    check(9, view())
    with pytest.raises(DomainError):
        readiness.save(
            service,
            owner,
            first.model_copy(update=dict(idempotency_key="stale", expected_revision=1)),
        )
    rereview = first.model_copy(update=dict(expected_revision=2, idempotency_key="rereview"))
    readiness.save(service, owner, rereview)
    check(10, view())
    assert view().data["remaining_work"][0]["progress_state"] == "student_marked_done"
    assert view(revision=1).data["remaining_work"][0]["progress_state"] == "unknown"
    at = bridge.retention.clock()
    proposal = view(
        plan=PlanRequest(windows=[dict(start=at + timedelta(hours=1), end=at + timedelta(hours=2))])
    )
    assert "plan" in proposal.data
    readiness.save(service, owner, correct.model_copy(update=dict(expected_revision=3)))
    check(3, view())
    broken = copy.deepcopy(correct.model_dump(mode="json"))
    broken.update(expected_revision=4, idempotency_key="reject")
    broken["requirements"][0]["evidence"][0]["quote"] = "absent text"
    with pytest.raises(DomainError, match="exact passage"):
        readiness.save(service, owner, Review.model_validate(broken))
    assert view().data["revision"] == 4
    check(14, view())
    for number, packet, label in [
        (4, missing, "MISSING"),
        (11, baseline, "CONFLICT"),
        (12, corrected, "PARTIAL"),
        (8, corrected, "CORRECTED"),
        (5, baseline, "BASELINE"),
        (13, baseline, "BASELINE"),
    ]:
        req = authored_review(packet, label).model_dump(mode="json")
        req.update(assignment_id=f"scope-{number}", idempotency_key=f"save-{number}")
        if number == 8:
            req["bindings"] = [
                b if b["role"] != "measurement" else baseline[-1] for b in req["bindings"]
            ]
            req["requirements"][-1] = first.requirements[-1].model_dump(mode="json")
        if number in {5, 13}:
            for row in req["requirements"]:
                row.update(
                    assessment_status="unknown",
                    followup="awaiting_review",
                    measured_artifact_hash=None,
                    coverage="unavailable",
                    evidence=[],
                    reviewed_extent=[],
                )
        new = readiness.save(service, owner, Review.model_validate(req)).data
        check(number, readiness.view(service, owner, new["record_id"]))
    # Freshness affects only criteria dependent on the inaccessible source.
    from canvas_bridge.storage import IndependentResource

    with bridge.store.transaction() as session:
        row = session.get(IndependentResource, corrected[1]["document_id"])
        row.expires_at = at - timedelta(minutes=1)
    limited = view()
    assert any(b["availability"] == "unavailable" for b in limited.data["bindings"])
    assert not any(s.id == corrected[1]["document_id"] for s in limited.sources)
    if NATIVE:
        save(Path(NATIVE), "authored-scenarios.json", actual)


async def test_readiness_concurrent_commit_and_rollback(settings, owner, tmp_path, monkeypatch):
    import threading

    from canvas_bridge.domain import DomainError
    from canvas_bridge.parser_worker import extract
    from canvas_bridge.processes import readiness

    # Exercise independent transactions against the same durable SQLite database.
    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_document", parser)
    settings.database_url = "sqlite:///" + str(tmp_path / "concurrent.db")
    settings.process_features_enabled = True
    trace = {}
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        packet = await import_case(bridge, owner, "baseline")
        request = authored_review(packet, "BASELINE")

        def submit(review):
            return readiness.save(bridge.processes, owner, review).data

        original = submit(request)
        ident = original["record_id"]
        before = readiness.view(bridge.processes, owner, ident).data
        ready = threading.Barrier(2)

        def race(key):
            ready.wait(timeout=10)
            try:
                return submit(
                    request.model_copy(update=dict(idempotency_key=key, expected_revision=1))
                )
            except DomainError as exc:
                return dict(reason_code=exc.reason_code)

        first, second = await asyncio.gather(
            asyncio.to_thread(race, "one"), asyncio.to_thread(race, "two")
        )
        trace.update(before=before, competing_results=[first, second])
        assert sum(r.get("revision") == 2 for r in (first, second)) == 1
        assert {r.get("reason_code") for r in (first, second)} == {
            None,
            "PROCESS_REVISION_MISMATCH",
        }
        repo = bridge.processes.repository
        write = repo._save

        def injected(*args):
            write(*args)
            raise RuntimeError("synthetic failure before transaction exit")

        retry = request.model_copy(update=dict(expected_revision=2, idempotency_key="retry"))
        with monkeypatch.context() as patch:
            patch.setattr(repo, "_save", injected)
            with pytest.raises(RuntimeError, match="synthetic failure"):
                submit(retry)
        recovered = readiness.view(bridge.processes, owner, ident).data
        assert (
            recovered["revision"] == 2 and recovered["remaining_work"] == before["remaining_work"]
        )
        trace.update(
            after_failure=recovered,
            retry=submit(retry),
            failure="synthetic failure before transaction exit",
        )
        assert trace["retry"]["revision"] == 3
        with pytest.raises(DomainError):
            readiness.view(bridge.processes, "other-owner", ident)
        bad = retry.model_dump(mode="json")
        bad["bindings"][0]["content_hash"] = "0" * 64
        with pytest.raises(DomainError) as mismatch:
            submit(Review.model_validate(bad))
        assert mismatch.value.reason_code == "READINESS_VERSION_MISMATCH"
        trace["bad_hash"] = mismatch.value.reason_code
        if NATIVE:
            save(Path(NATIVE), "concurrency.json", trace)


async def test_readiness_wire_contract(bridge, settings, owner, token_factory, parsed_locally):
    from datetime import timedelta

    from canvas_bridge.storage import IndependentResource
    from tests.test_mcp_contract import running as http_server

    settings.process_features_enabled = True
    packet = await import_case(bridge, owner, "baseline")
    review = authored_review(packet, "BASELINE").model_dump(mode="json")
    receipts = []
    async for url in http_server.__wrapped__(bridge, settings, None):
        async with client_session(url, token_factory(), read_timeout=120) as session:

            async def call(tool, args):
                result = (await session.call_tool(tool, args)).structuredContent
                receipts.append(dict(tool=tool, arguments=args, result=result))
                return result

            receipt = await call("save_assignment_readiness", {"review": review})
            assert receipt["status"] == "ok", receipt["summary"]
            assert receipt["data"]["revision"] == 1
            key = receipt["data"]["record_id"]
            replay = await call("save_assignment_readiness", {"review": review})
            assert replay["data"] == receipt["data"]
            from copy import deepcopy

            for error in ("wrong_quote", "invalid_part", "wrong_hash"):
                bad = deepcopy(review)
                bad.update(expected_revision=1, idempotency_key=error)
                if error == "wrong_quote":
                    bad["requirements"][0]["governing"]["quote"] = "A different unobserved passage."
                elif error == "invalid_part":
                    bad["requirements"][0]["governing"]["part"] = 99
                else:
                    bad["bindings"][0]["content_hash"] = "0" * 64
                rejected = await call("save_assignment_readiness", {"review": bad})
                assert (
                    rejected["data"]["reason_code"]
                    == {
                        "invalid_part": "READINESS_LOCATOR_INVALID",
                        "wrong_quote": "READINESS_QUOTE_MISMATCH",
                        "wrong_hash": "INDEPENDENT_SOURCE_CHANGED",
                    }[error]
                )

            at = bridge.retention.clock()
            result = await call(
                "get_assignment_readiness",
                dict(
                    record_id=key,
                    plan=dict(
                        windows=[
                            dict(
                                start=(at + timedelta(hours=1)).isoformat(),
                                end=(at + timedelta(hours=2)).isoformat(),
                            )
                        ]
                    ),
                ),
            )
            assert result["status"] == "ok", result["summary"]
            assert result["data"]["revision"] == 1
            assert len(result["data"]["plan"]["effort_summary"]["unknown_effort_work_ids"]) == 3
            assert len(result["data"]["remaining_work"]) == 3
            task = result["data"]["remaining_work"][0]["work_id"]
            changed = await call(
                "record_readiness_progress",
                dict(
                    request=dict(
                        record_id=key,
                        expected_revision=1,
                        idempotency_key="done",
                        work_id=task,
                        progress_state="student_marked_done",
                    )
                ),
            )
            assert changed["data"]["revision"] == 2
            reread = await call("get_assignment_readiness", dict(record_id=key))
            assert reread["data"]["remaining_work"][0]["progress_state"] == "student_marked_done"
            with bridge.store.transaction() as db:
                item = db.get(IndependentResource, packet[1]["document_id"])
                item.provenance = item.provenance | {"share_text": False}
            limited = await call("get_assignment_readiness", dict(record_id=key))
            assert not any(s["id"] == packet[1]["document_id"] for s in limited["sources"])
            assert limited["data"]["counts"]["unknown"] >= 1
            denied = await call(
                "save_assignment_readiness",
                {"review": review | {"expected_revision": 2, "idempotency_key": "withheld"}},
            )
            assert denied["status"] != "ok"
            if NATIVE:
                save(Path(NATIVE), "wire-contract.json", receipts)


async def test_readiness_scope_and_review_controls(bridge, owner, parsed_locally):
    from canvas_bridge.processes import readiness

    bridge.settings.process_features_enabled = True
    bindings = await import_case(bridge, owner, "baseline")
    source = member("fixtures/control_requirements.md")
    ident = await bridge.independent.ingest(
        owner,
        source,
        "control_requirements.md",
        "text/markdown",
        course="BenchLink",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
    )
    selection = dict(
        logical_id="controls", role="brief", document_id=ident, content_hash=sha(source)
    )
    first = authored_review(bindings, "BASELINE")
    req = first.model_dump(mode="json")
    req.update(assignment_id="scope-controls", bindings=[*bindings, selection])

    def row(line, required, applicability):
        quote = next(s for s in source.decode().splitlines() if s.startswith(line))
        anchor = dict(source="controls", part=1, surface="text", quote=quote)
        return dict(
            requirement_id=line,
            criterion=quote,
            governing=anchor,
            required=required,
            applicability=applicability,
            applicability_basis=quote,
            assessment_status="needs_work" if not required else "unknown",
            rationale=quote,
            evidence=[anchor],
            coverage="complete",
            gap_kind="polish",
            action="Review visual polish",
            completion_condition="Complete the requested review",
        )

    rows = [
        row("CR-OPTIONAL", False, "applicable"),
        row("CR-EXEMPT", True, "not_applicable"),
        row("CR-UNKNOWN", True, "unknown"),
    ]
    req.update(
        requirements=rows,
        requested_work=["CR-OPTIONAL"],
        expected_revision=0,
        idempotency_key="scope-controls",
    )
    receipt = readiness.save(bridge.processes, owner, Review.model_validate(req)).data
    key = receipt["record_id"]
    v = readiness.view(bridge.processes, owner, key).data
    assert v["summary_status"] == "unknown" and v["counts"]["applicable_required"] == 0
    assert v["remaining_work"][0]["work_basis"] == "explicit_user_request"
    changed = readiness.Selection(requirement_set_revision="another", bindings=req["bindings"])
    assert (
        readiness.view(bridge.processes, owner, key, selection=changed).data["summary_status"]
        == "unknown"
    )
    no_work = Review.model_validate(
        req
        | dict(
            requirements=list(reversed(rows)),
            requested_work=[],
            expected_revision=1,
            idempotency_key="reorder",
        )
    )
    readiness.save(bridge.processes, owner, no_work)
    reordered = readiness.view(bridge.processes, owner, key).data
    assert (
        reordered["requirement_set_revision"] == v["requirement_set_revision"]
        and not reordered["remaining_work"]
    )
    conflict = authored_review(bindings, "CONFLICT")
    saved = readiness.save(bridge.processes, owner, conflict).data
    old = readiness.view(bridge.processes, owner, saved["record_id"]).data
    disputed = next(r for r in old["requirements"] if r["assessment_status"] == "conflict")
    assert {c["assessment_status"] for c in disputed["candidate_assessments"]} == {
        "satisfied",
        "needs_work",
    }
    resolved = first.model_copy(update=dict(expected_revision=1, idempotency_key="resolved"))
    readiness.save(bridge.processes, owner, resolved)
    assert readiness.view(bridge.processes, owner, saved["record_id"], revision=1).data == old
    if NATIVE:
        save(
            Path(NATIVE),
            "scope-controls.json",
            dict(
                optional=v,
                reordered=reordered,
                conflict=old,
                resolved=readiness.view(bridge.processes, owner, saved["record_id"]).data,
            ),
        )
