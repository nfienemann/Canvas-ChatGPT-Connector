"""Phase F on imported synthetic coursework, signed MCP, and the owned state journal."""

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.processes import handoff_models as hm
from canvas_bridge.processes import handoff_service as hs
from canvas_bridge.processes import readiness as rd
from tests.test_independent_intelligence import independent_recipient as independent_recipient
from tests.test_recovery_independence import parsed_locally as parsed_locally

ARCHIVE = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-f/specs.zip"


def content(name):
    with ZipFile(ARCHIVE) as archive:
        return archive.read("phase_f_handoffs/" + name)


def capture(name, data):
    if directory := os.environ.get("BRIDGE_PHASE_F_OUTPUT"):
        p = Path(directory)
        p.mkdir(exist_ok=True, parents=True)
        (p / (name + ".json")).write_text(json.dumps(data, indent=2), "utf8")


def anchor(source, quote):
    return dict(source=source, part=1, surface="text", quote=quote)


async def documents(bridge, owner, version):
    refs = []
    for name, role in [("requirements_and_roles", "brief"), (version, "artifact")]:
        raw = content("fixtures/model_inputs/" + name + ".md")
        doc = await bridge.independent.ingest(
            owner,
            raw,
            name + ".md",
            "text/markdown",
            course="Studio",
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
        )
        refs.append(
            dict(
                logical_id=role,
                role=role,
                document_id=doc,
                content_hash=hashlib.sha256(raw).hexdigest(),
            )
        )
    return refs


def review(bindings, version):
    brief = content("fixtures/model_inputs/requirements_and_roles.md").decode().splitlines()
    draft = content("fixtures/model_inputs/" + version + ".md").decode().splitlines()
    criteria = []
    for i, key in enumerate(["R1", "R2"]):
        missing = i == 1 and version == "handoff_draft"
        criteria.append(
            dict(
                requirement_id=key,
                criterion=brief[2 + i],
                governing=anchor("brief", brief[2 + i]),
                applicability_basis="Brief lists criterion",
                assessment_status="needs_work" if missing else "satisfied",
                rationale="Current artifact passage",
                evidence=[anchor("artifact", draft[2 + i * 2])],
                coverage="complete",
                gap_kind="table" if missing else None,
                action="Add the comparison table" if missing else None,
                completion_condition="A bounded table is present" if missing else None,
            )
        )
    return rd.Review(
        assignment_id="prototype",
        course="Studio",
        term="fall",
        expected_revision=0,
        idempotency_key="readiness",
        membership_complete=True,
        review_scope="Selected prototype",
        bindings=bindings,
        requirements=criteria,
    )


def request(record):
    return dict(
        handoff_id="studio-review",
        record_id=record,
        work_revision=1,
        journal_revision=0,
        idempotency_key="packet-1",
        artifact_logical_id="artifact",
        responsibility=dict(
            assignment_ref="roles",
            revision="1",
            members=[dict(member_id=k, label="Member " + k) for k in ("A", "B", "C")],
            responsible_actor="A",
            recipient_ids=["B"],
            identity_basis="source_assignment",
            source_ref="roles/1",
            evidence=anchor(
                "brief",
                content("fixtures/model_inputs/requirements_and_roles.md").decode().splitlines()[5],
            ),
        ),
        action=dict(
            action_id="REVIEW-1",
            revision="1",
            owner_id="B",
            description="Review the written prototype summary",
            expected_output="Feedback on the written summary",
            prerequisite_ids=["R1"],
        ),
    )


async def seed(bridge, owner, version="handoff_v1"):
    bridge.settings.process_features_enabled = True
    bindings = await documents(bridge, owner, version)
    rec = rd.save(bridge.processes, owner, review(bindings, version)).data["record_id"]
    return request(rec)


async def test_signed_lifecycle(
    bridge, settings, owner, token_factory, parsed_locally, independent_recipient
):
    from contextlib import asynccontextmanager

    from canvas_bridge.storage import IndependentResource
    from tests.test_mcp_contract import running
    from tests.test_permission_consistency_contract import client_session

    req = await seed(bridge, owner)
    record = req["record_id"]
    transcript = []
    async with (
        asynccontextmanager(running.__wrapped__)(bridge, settings, None) as url,
        client_session(url, token_factory()) as session,
    ):

        async def call(name, args, success=True):
            result = (await session.call_tool(name, args)).structuredContent
            transcript.append(dict(tool=name, arguments=args, result=result))
            assert result and (result["status"] == "ok") == success, (
                name,
                result and result["summary"],
                result and result["data"],
            )
            return result["data"]

        async def read(**extra):
            return await call(
                "get_group_handoff", dict(record_id=record, handoff_id="studio-review", **extra)
            )

        capture(
            "schemas",
            [
                t.model_dump(mode="json", exclude_none=True)
                for t in (await session.list_tools()).tools
                if "handoff" in t.name
            ],
        )
        first = await call("prepare_group_handoff", dict(request=req))
        assert first == await call("prepare_group_handoff", dict(request=req))
        p = (await read())["packet"]
        assert p["artifact_readiness"] == "ready" and p["next_action_state"] == "ready"
        assert len(p["assessment"]["criteria"]) == 2 and p["current_ack_state"] == "none"
        base = dict(
            record_id=record,
            work_revision=1,
            handoff_id=req["handoff_id"],
            packet_id=p["packet_id"],
        )
        export = base | dict(journal_revision=1, idempotency_key="payload", output_format="json")
        out = await call("export_group_handoff", dict(request=export))
        assert hashlib.sha256(out["payload"].encode()).hexdigest() == out["content_hash"]
        assert json.loads(out["payload"])["semantic_basis_id"] == p["semantic_basis_id"]
        assert out == await call("export_group_handoff", dict(request=export))
        declared = base | dict(
            output_id=out["output_id"],
            content_hash=out["content_hash"],
            recipient_ids=["B"],
            destination_ref="declared-channel",
            receipt_ref="supplied-1",
            observed_at=datetime.now(UTC).isoformat(),
            journal_revision=2,
            idempotency_key="reported",
        )
        await call("record_handoff_delivery_receipt", dict(request=declared))
        packet = (await read())["packet"]
        assert (
            packet["delivery_state"] == "reported_confirmed"
            and packet["current_ack_state"] == "none"
        )
        response = base | dict(
            journal_revision=3,
            idempotency_key="reply",
            observation_id="reply-B",
            expected_observation_revision=0,
            acknowledged_by="B",
            state="accepted_for_next_step",
            evidence_basis="supplied_relayed_response",
            evidence_ref="synthetic-message",
            observed_at=datetime.now(UTC).isoformat(),
        )
        receipt = await call("record_handoff_response", dict(request=response))
        assert receipt == await call("record_handoff_response", dict(request=response))
        packet = (await read())["packet"]
        assert packet["current_ack_state"] == "accepted_for_next_step"
        assert packet["responses"][0]["recorded_by"] != packet["responses"][0]["acknowledged_by"]
        note = req | dict(
            journal_revision=4,
            idempotency_key="note",
            expected_packet=p["packet_id"],
            presentation_note="Use the saved file.",
        )
        await call("prepare_group_handoff", dict(request=note))
        alias = (await read())["packet"]
        assert (
            alias["semantic_basis_id"] == p["semantic_basis_id"]
            and alias["current_ack_state"] == "accepted_for_next_step"
        )
        change = deepcopy(note)
        change.update(
            journal_revision=5, idempotency_key="reassign", expected_packet=alias["packet_id"]
        )
        change["responsibility"].update(
            responsible_actor="C",
            revision="2",
            identity_basis="explicit_declaration",
            evidence=None,
            source_ref="student-reassignment",
        )
        await call("prepare_group_handoff", dict(request=change))
        changed = (await read())["packet"]
        assert (
            changed["current_ack_state"] == "none"
            and changed["responses"][0]["applicability"] == "historical"
        )
        late = response | dict(
            observation_id="late-B", journal_revision=6, idempotency_key="late", state="received"
        )
        await call("record_handoff_response", dict(request=late))
        stale = await call(
            "prepare_group_handoff", dict(request=change | dict(idempotency_key="stale")), False
        )
        assert stale["reason_code"] == "PROCESS_REVISION_MISMATCH"
        correct = response | dict(
            journal_revision=7,
            idempotency_key="correction",
            expected_observation_revision=1,
            retracted=True,
        )
        await call("record_handoff_response", dict(request=correct))
        await call(
            "restore_group_handoff",
            dict(
                request=base
                | dict(
                    journal_revision=8,
                    idempotency_key="restore",
                    packet_id=changed["packet_id"],
                    expected_packet=changed["packet_id"],
                    fields=["responsibility"],
                )
            ),
        )
        restored = (await read())["packet"]
        assert (
            restored["responsibility"]["responsible_actor"] == "A"
            and restored["current_ack_state"] == "received"
            and restored["presentation_note"] == "Use the saved file."
        )
        archived = (await read(packet_id=p["packet_id"]))["packet"]
        assert (
            archived["selected_packet_ack_state"] == "received"
            and archived["view_mode"] == "historical"
        )
        earlier = (await read(as_of=packet["response_cutoff"]))["packet"]
        assert earlier["current_ack_state"] == "accepted_for_next_step"
        capture("packet-example", packet)
        with bridge.store.transaction() as db:
            doc = db.get(IndependentResource, p["assessment"]["document_id"])
            doc.provenance = doc.provenance | dict(share_text=False)
        await call("get_group_handoff", dict(record_id=record, handoff_id=req["handoff_id"]), False)
        capture("signed-lifecycle", transcript)


class FixtureOutput:
    """Persistent local test adapter. No network sends or external destinations."""

    def __init__(self, folder):
        import sqlite3

        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=True, parents=True)
        self.db = self.folder / "effects.db"
        with sqlite3.connect(self.db) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS effects(owner TEXT,id TEXT,receipt TEXT,PRIMARY KEY(owner,id))"
            )

    async def authorize(self, owner, kind, destination, recipients, sources):
        return bool(sources) and (
            (kind == "downloadable_artifact" and destination == "fixture-files" and not recipients)
            or (
                kind == "delivery"
                and destination == "fixture-inbox"
                and tuple(recipients) == ("B",)
            )
        )

    async def lookup(self, owner, operation_id):
        import sqlite3

        from canvas_bridge.processes.handoff_outputs import Receipt

        with sqlite3.connect(self.db) as db:
            r = db.execute(
                "SELECT receipt FROM effects WHERE owner=? AND id=?", (owner, operation_id)
            ).fetchone()
        return Receipt.model_validate_json(r[0]) if r else None

    async def create_if_absent(self, owner, op, payload):
        import sqlite3

        from canvas_bridge.processes.handoff_outputs import Receipt

        assert hashlib.sha256(payload.encode()).hexdigest() == op["content_hash"]
        key = op["operation_id"]
        with sqlite3.connect(self.db) as db:
            db.execute("BEGIN IMMEDIATE")
            r = db.execute(
                "SELECT receipt FROM effects WHERE owner=? AND id=?", (owner, key)
            ).fetchone()
            if r:
                return Receipt.model_validate_json(r[0])
            path = self.folder / key
            path.write_bytes(payload.encode())
            receipt = Receipt(
                operation_id=key,
                content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                destination_ref=op["destination_ref"],
                recipient_ids=op["recipient_ids"],
                object_id=key,
                revision="1",
                locator="fixture-output/" + key,
            )
            db.execute("INSERT INTO effects VALUES(?,?,?)", (owner, key, receipt.model_dump_json()))
        raise TimeoutError("Response lost after the synthetic effect committed")


def served_handoffs(raw, sock):
    import contextlib

    import uvicorn

    from canvas_bridge.app import create_app
    from canvas_bridge.config import Settings
    from tests.conftest import bridge as create_bridge

    settings = Settings.model_validate_json(raw)
    with contextlib.contextmanager(create_bridge.__wrapped__)(settings) as bridge:
        bridge.processes.handoff_output_adapter = FixtureOutput(
            Path(settings.database_url.removeprefix("sqlite:///")).parent / "outputs"
        )
        uvicorn.Server(
            uvicorn.Config(create_app(settings, bridge), log_level="error", access_log=False)
        ).run(sockets=[sock])


@pytest.mark.skipif(not os.getenv("BRIDGE_PHASE_F_HOST"), reason="Opt-in native synthetic host")
async def test_native_handoff(
    settings, owner, token_factory, tmp_path, parsed_locally, independent_recipient, monkeypatch
):
    import asyncio
    import contextlib

    from tests import test_phase_b_readiness as host
    from tests.conftest import bridge as create_bridge
    from tests.test_permission_consistency_contract import client_session

    settings.database_url = "sqlite:///" + str(tmp_path / "state.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    monkeypatch.setattr(host, "serve", served_handoffs)
    folder = Path(os.environ["BRIDGE_PHASE_F_HOST"])
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    work = tmp_path / "host"
    work.mkdir()
    with contextlib.contextmanager(create_bridge.__wrapped__)(settings) as bridge:
        req = await seed(bridge, owner)
    base = dict(record_id=req["record_id"], handoff_id=req["handoff_id"])
    state = None
    for i, name in enumerate(
        ("prepare_handoff", "record_response", "reconcile_handoff", "retrieve_and_recover")
    ):
        context = base.copy()
        if i == 0:
            context["save_request"] = req
        if i == 1:
            context["response_request"] = base | dict(
                work_revision=1,
                journal_revision=state["journal_revision"],
                idempotency_key="relayed",
                observation_id="B-response",
                expected_observation_revision=0,
                packet_id=state["packet"]["packet_id"],
                acknowledged_by="B",
                state="accepted_for_next_step",
                evidence_basis="supplied_relayed_response",
                evidence_ref="message-B-1",
                observed_at=datetime.now(UTC).isoformat(),
            )
            context["supplied_message"] = (
                "Member B: I accept this version for the written-summary review."
            )
        if i == 2:
            update = deepcopy(req)
            update.update(
                expected_packet=state["packet"]["packet_id"],
                journal_revision=state["journal_revision"],
                idempotency_key="reassignment",
            )
            update["responsibility"].update(
                responsible_actor="C",
                revision="2",
                source_ref="updated-project-declaration",
                identity_basis="explicit_declaration",
                evidence=None,
            )
            context["save_request"] = update
        if i == 3:
            async with (
                host.running(settings) as setup_pid,
                client_session(settings.resource_url, token_factory()) as session,
            ):

                async def invoke(tool, args):
                    r = (await session.call_tool(tool, args)).structuredContent
                    assert r["status"] == "ok", r["summary"]
                    return r["data"]

                state = await invoke("get_group_handoff", base)
                subject = base | dict(packet_id=state["packet"]["packet_id"], work_revision=1)
                exported = await invoke(
                    "export_group_handoff",
                    dict(
                        request=subject
                        | dict(
                            output_format="markdown",
                            idempotency_key="payload",
                            journal_revision=state["journal_revision"],
                        )
                    ),
                )
                job = subject | dict(
                    kind="downloadable_artifact",
                    output_id=exported["output_id"],
                    destination_ref="fixture-files",
                    confirmed=True,
                    recipient_ids=[],
                    idempotency_key="attempt",
                    journal_revision=exported["revision"],
                )
                lost = await invoke("reconcile_handoff_output", dict(request=job))
                assert lost["status"] == "uncertain"
                context["recovery_request"] = job | dict(
                    confirmed=False,
                    reconcile_only=True,
                    idempotency_key="lookup",
                    journal_revision=lost["revision"],
                )
                (folder / "before-restart.json").write_text(
                    json.dumps(
                        dict(
                            pid=setup_pid,
                            output_hash=exported["content_hash"],
                            operation_id=lost["operation_id"],
                            status=lost["status"],
                        ),
                        indent=2,
                    ),
                    "utf8",
                )
        async with host.running(settings) as pid:
            prompt = (
                content("prompts/" + name + ".md").decode()
                + "\nSelected synthetic context: "
                + json.dumps(context)
            )
            answer = await host.review_host(
                settings.resource_url,
                token_factory(),
                prompt,
                work,
                folder,
                name,
                tools=[
                    "prepare_group_handoff",
                    "record_handoff_response",
                    "get_group_handoff",
                    "reconcile_handoff_output",
                ],
                instructions="Use only these coursework MCP tools. No filesystem, shell, web, external services or other tools. Use the supplied exact request for this task and read the saved packet afterward. All member identities are explicitly declared. Keep content readiness, response provenance and delivery separate. Reconcile only the supplied interrupted downloadable fixture output; never deliver a message.",
            )
            assert answer
            async with client_session(settings.resource_url, token_factory()) as session:
                state = (await session.call_tool("get_group_handoff", base)).structuredContent[
                    "data"
                ]
            (folder / (name + "-readback.json")).write_text(
                json.dumps(dict(pid=pid, state=state), indent=2), "utf8"
            )
            p = state["packet"]
            assert p["artifact_readiness"] == "ready" and p["next_action_state"] == "ready"
            if i == 1:
                assert p["current_ack_state"] == "accepted_for_next_step"
            if i >= 2:
                assert (
                    p["responses"][0]["applicability"] == "historical"
                    and p["responsibility"]["responsible_actor"] == "C"
                )
            if i == 3:
                assert (
                    p["operations"][0]["status"] == "confirmed"
                    and p["delivery_state"] == "not_requested"
                )
                effect = p["operations"][0]["receipt"]
                actual = (tmp_path / "outputs" / effect["object_id"]).read_bytes()
                assert hashlib.sha256(actual).hexdigest() == effect["content_hash"]
                (folder / "handoff-example.md").write_bytes(actual)


async def test_roadmap_changed_assignment(bridge, owner, parsed_locally, independent_recipient):
    from canvas_bridge.processes import (
        change_service as change,
    )
    from canvas_bridge.processes import (
        effort_service as effort,
    )
    from canvas_bridge.processes import (
        resource_service as resource,
    )
    from canvas_bridge.processes import (
        study_plan as study,
    )
    from tests.test_phase_c_reconciliation import authored_rows, target_packet
    from tests.test_phase_c_reconciliation import fixture as case
    from tests.test_phase_e_resources import seed as phase_e_seed

    service = bridge.processes
    plan = await phase_e_seed(bridge, owner)
    rid = plan["record_id"]
    f = (await study.view(service, owner, rid)).data["forecasts"][-1]
    baseline = rd.view(service, owner, rid).data
    scenario = case("scenarios")["scenarios"][13]

    async def prepare_layers(plan, f, journal_rev, existing_resource, existing_packet):
        windows = plan["schedule"]["student_windows"]
        # One continuous Phase D parent reservation; E partitions that same forecast.
        req = study.SavePlan(
            record_id=rid,
            work_revision=f["work_revision"],
            journal_revision=journal_rev,
            idempotency_key="study-" + f["forecast_id"],
            demands=[dict(forecast_id=f["forecast_id"])],
            constraints=dict(
                as_of=plan["schedule"]["planning_boundary"],
                availability_coverage="complete",
                availability=[dict(start=windows[0]["start_at"], end=windows[-1]["end_at"])],
            ),
        )
        await study.save(service, owner, req)
        d = (await study.view(service, owner, rid)).data["plan"]
        plan.update(
            journal_revision=journal_rev + 1,
            study_generation=d["generation_id"],
            study_blocks=[
                dict(
                    block_id=d["selected_blocks"][0]["block_id"], step_id="prepare", phase="active"
                )
            ],
            expected_generation=existing_resource,
        )
        plan["process"]["steps"][1]["resource_requirement"]["booking_required"] = True
        await resource.save(service, owner, resource.Save.model_validate(plan))
        e = (await resource.view(service, owner, rid, "TYPED")).data["generation"]
        current = rd.view(service, owner, rid).data
        selected = next(w for w in current["remaining_work"] if w["work_id"] == f["work_id"])
        info = request(rid)
        info["responsibility"].update(
            identity_basis="explicit_declaration", evidence=None, source_ref="project-declaration"
        )
        info["action"].update(
            prerequisite_ids=[],
            description="Review the current revision evidence",
            expected_output="Review comments",
            revision="studio",
        )
        info.update(
            work_revision=f["work_revision"],
            journal_revision=journal_rev + 2,
            work_id=f["work_id"],
            criterion_ids=[selected["requirement_id"]],
            expected_packet=existing_packet,
            process=dict(process_id="TYPED", step_id="run", generation_id=e["generation_id"]),
            idempotency_key="handoff-" + f["forecast_id"],
        )
        await hs.prepare(service, owner, hm.Prepare.model_validate(info))
        packet = (await hs.view(service, owner, rid, info["handoff_id"])).data
        assert packet["packet"]["process_context"]["forecast_id"] == f["forecast_id"]
        assert e["study_generation"] == d["generation_id"]
        assert "conditional" == packet["packet"]["condition_states"]["downstream_execution"]
        assert packet["packet"]["next_action_state"] == "ready"
        return dict(
            plan=d,
            resource=e,
            packet=packet["packet"],
            journal=packet["journal_revision"],
            request=info,
        )

    old = await prepare_layers(plan, f, 1, None, None)
    old_packet = old["packet"]
    await hs.record_response(
        service,
        owner,
        hm.Response(
            record_id=rid,
            work_revision=1,
            handoff_id="studio-review",
            packet_id=old_packet["packet_id"],
            journal_revision=old["journal"],
            idempotency_key="old-response",
            observation_id="reviewer",
            expected_observation_revision=0,
            acknowledged_by="B",
            state="received",
            evidence_basis="supplied_relayed_response",
            evidence_ref="message",
            observed_at=datetime.now(UTC),
        ),
    )
    target = await target_packet(bridge, owner, scenario)
    staged = (
        await change.observe(
            service,
            owner,
            change.Observation(
                record_id=rid, expected_revision=1, target=target, idempotency_key="changed"
            ),
        )
    ).data
    applied = (
        await change.apply_change(
            service,
            owner,
            change.Reassessment(
                record_id=rid,
                expected_revision=staged["revision"],
                change_id=staged["change_id"],
                idempotency_key="reconcile",
                assessments=authored_rows(scenario, target),
                inventory_complete=True,
                material_changes=["PA-R02"],
            ),
        )
    ).data
    current = rd.view(service, owner, rid).data["remaining_work"][0]
    rev = old["journal"] + 1
    f2 = (
        await effort.issue(
            service,
            owner,
            effort.ForecastRequest(
                record_id=rid,
                work_revision=applied["revision"],
                journal_revision=rev,
                idempotency_key="reopened",
                work_id=current["work_id"],
                scope_id="prototype",
                task_family="studio",
                scope_kind="remaining_episode",
                baseline=dict(low=65, high=65),
            ),
        )
    ).data["forecast"]
    updated = deepcopy(plan)
    updated.update(
        forecast_id=f2["forecast_id"],
        work_revision=applied["revision"],
        idempotency_key="resource-update",
    )
    updated["process"]["revision"] = "2"
    updated["process"]["active_demand_mapping"]["parent_forecast_ref"] = f2["forecast_id"]
    for s in updated["process"]["steps"]:
        s.update(episode_id=f2["episode_id"], work_lineage_id=f2.get("lineage_id") or f2["work_id"])
    new = await prepare_layers(
        updated, f2, rev + 1, old["resource"]["generation_id"], old_packet["packet_id"]
    )
    assert (
        new["packet"]["current_ack_state"] == "none"
        and new["packet"]["responses"][0]["applicability"] == "historical"
    )
    assert new["packet"]["work_episode_id"] != old_packet["work_episode_id"]
    assert (
        new["packet"]["assessment"]["artifact_version"]
        != old_packet["assessment"]["artifact_version"]
    )
    capture(
        "roadmap",
        dict(
            source_capture=baseline["selected_bindings"],
            assignment_id=rid,
            old=old,
            reconciliation=applied,
            old_forecast=f,
            current_forecast=f2,
            current=new,
        ),
    )


async def test_c_equivalence_and_material_change(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.processes import change_service as cs

    req = await seed(bridge, owner)
    service = bridge.processes
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    rid = req["record_id"]
    original = (await hs.view(service, owner, rid, req["handoff_id"])).data["packet"]
    response = hm.Response(
        record_id=rid,
        work_revision=1,
        handoff_id=req["handoff_id"],
        packet_id=original["packet_id"],
        journal_revision=1,
        idempotency_key="ack",
        observation_id="reply",
        expected_observation_revision=0,
        acknowledged_by="B",
        state="received",
        evidence_basis="supplied_relayed_response",
        evidence_ref="observed",
        observed_at=datetime.now(UTC),
    )
    await hs.record_response(service, owner, response)
    packets = [original]
    receipts = []
    revision = 1
    for i, file in enumerate(("handoff_v1", "handoff_v2")):
        raw = content("fixtures/model_inputs/" + file + ".md")
        if i == 0:
            raw = b"\n" + raw
        ident = await bridge.independent.ingest(
            owner,
            raw,
            file + "-updated.md",
            "text/markdown",
            course="Studio",
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
        )
        dbrecord = rd.snapshot(service.repository, owner, rid)
        bindings = [
            b
            if b["role"] != "artifact"
            else b | dict(document_id=ident, content_hash=hashlib.sha256(raw).hexdigest())
            for b in dbrecord.data["bindings"]
        ]
        staged = (
            await cs.observe(
                service,
                owner,
                cs.Observation(
                    record_id=rid,
                    expected_revision=revision,
                    target=bindings,
                    idempotency_key="observe" + str(i),
                ),
            )
        ).data
        update = (
            await cs.apply_change(
                service,
                owner,
                cs.Reassessment(
                    record_id=rid,
                    expected_revision=staged["revision"],
                    change_id=staged["change_id"],
                    idempotency_key="change" + str(i),
                    assessments=review(bindings, file).requirements if i else (),
                    inventory_complete=True,
                ),
            )
        ).data
        revision = update["revision"]
        await hs.prepare(
            service,
            owner,
            hm.Prepare.model_validate(
                req
                | dict(
                    work_revision=revision,
                    journal_revision=2 + i,
                    idempotency_key="packet" + str(i),
                    expected_packet=packets[-1]["packet_id"],
                )
            ),
        )
        next_packet = (await hs.view(service, owner, rid, req["handoff_id"])).data["packet"]
        packets.append(next_packet)
        receipts.append(update)
        assert next_packet["artifact_readiness"] == "ready"
        if not i:
            assert next_packet["responses"][0]["applicability"] == "carried_equivalent"
            assert (
                next_packet["assessment"]["criteria"][0]["assessed_at"]
                == original["assessment"]["criteria"][0]["assessed_at"]
            )
        else:
            assert next_packet["responses"][0]["applicability"] == "historical"
    capture("correspondence", dict(packets=packets, receipts=receipts))


@pytest.mark.parametrize(
    "case",
    [
        "draft-review",
        "draft-integrate",
        "ambiguous-role",
        "missing-artifact",
        "partial-coverage",
        "incomplete-inventory",
        "selected-scope",
        "progress-is-separate",
        "wrong-version",
        "missing-requirement",
        "foreign-episode",
    ],
)
async def test_grounded_packet_cases(case, bridge, owner, parsed_locally, independent_recipient):
    from canvas_bridge.domain import DomainError

    version = (
        "handoff_draft"
        if case in {"draft-review", "draft-integrate", "progress-is-separate"}
        else "handoff_v1"
    )
    bridge.settings.process_features_enabled = True
    service = bridge.processes
    docs = await documents(bridge, owner, version)
    raw = review(docs, version).model_dump(mode="json")
    if case == "partial-coverage":
        raw["requirements"][1]["coverage"] = "partial"
    if case in {"incomplete-inventory", "selected-scope"}:
        raw["membership_complete"] = False
    if case == "missing-artifact":
        raw["bindings"][1].update(document_id=None, content_hash=None)
        for r in raw["requirements"]:
            r.update(assessment_status="unknown", evidence=[], coverage="unavailable")
    rid = rd.save(service, owner, rd.Review.model_validate(raw)).data["record_id"]
    req = request(rid)
    if case == "progress-is-separate":
        work = rd.view(service, owner, rid).data["remaining_work"][0]
        rd.update_progress(
            service,
            owner,
            rd.Progress(
                record_id=rid,
                expected_revision=1,
                idempotency_key="done",
                work_id=work["work_id"],
                progress_state="student_marked_done",
            ),
        )
        req.update(work_revision=2, work_id=work["work_id"])
    if case == "wrong-version":
        req["expected_artifact_hash"] = "0" * 64
    if case == "foreign-episode":
        req["expected_episode_id"] = "another-assignment-episode"
    if case == "ambiguous-role":
        req["responsibility"].update(identity_basis="proposed", responsible_actor=None)
    if case == "draft-integrate":
        req["action"]["prerequisite_ids"] = ["R1", "R2"]
    if case == "missing-requirement":
        req["action"]["prerequisite_ids"] = ["R3"]
    if case == "selected-scope":
        req["criterion_ids"] = ["R1"]
    if case in {"wrong-version", "foreign-episode"}:
        with pytest.raises(DomainError) as exc:
            await hs.prepare(service, owner, hm.Prepare.model_validate(req))
        assert exc.value.reason_code == "HANDOFF_BASIS_CHANGED"
        capture(case, dict(status="requires_rebase", reason=exc.value.reason_code))
        return
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    p = (await hs.view(service, owner, rid, req["handoff_id"])).data["packet"]
    expected = {
        "draft-review": ("needs_work", "ready"),
        "draft-integrate": ("needs_work", "needs_work"),
        "ambiguous-role": ("ready", "needs_identity"),
        "missing-artifact": ("unknown", "unknown"),
        "partial-coverage": ("unknown", "ready"),
        "incomplete-inventory": ("unknown", "ready"),
        "selected-scope": ("ready", "ready"),
        "progress-is-separate": ("needs_work", "ready"),
        "missing-requirement": ("ready", "unknown"),
    }
    assert (p["artifact_readiness"], p["next_action_state"]) == expected[case]
    if case == "progress-is-separate":
        assert p["personal_progress"] == "student_marked_done"
    capture(case, p)


async def test_response_populations(bridge, owner, parsed_locally, independent_recipient):
    service = bridge.processes
    req = await seed(bridge, owner)
    req["responsibility"].update(
        recipient_ids=["B", "C"], identity_basis="explicit_declaration", evidence=None
    )
    req["action"].update(acknowledgment_policy="all", required_response="accepted_for_next_step")
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    base = dict(record_id=req["record_id"], work_revision=1, handoff_id=req["handoff_id"])

    async def read():
        return (await hs.view(service, owner, req["record_id"], req["handoff_id"])).data

    state = await read()
    assert state["packet"]["next_action_state"] == "waiting_ack"
    states = []

    async def observe(actor, kind, ident, supersedes=None):
        before = await read()
        q = hm.Response(
            **base,
            packet_id=before["packet"]["packet_id"],
            journal_revision=before["journal_revision"],
            idempotency_key=ident,
            observation_id=ident,
            expected_observation_revision=0,
            acknowledged_by=actor,
            state=kind,
            evidence_basis="supplied_relayed_response",
            evidence_ref=ident,
            observed_at=datetime.now(UTC),
            supersedes=supersedes,
        )
        receipt = await hs.record_response(service, owner, q)
        assert (await hs.record_response(service, owner, q)).data == receipt.data
        result = (await read())["packet"]
        states.append(result)
        return result

    wrong = await observe("A", "received", "nonrecipient")
    assert (
        wrong["responses"][0]["applicability"] == "unresolved"
        and wrong["current_ack_state"] == "none"
    )
    one = await observe("B", "accepted_for_next_step", "accept-B")
    assert one["current_ack_state"] == "partial" and one["next_action_state"] == "waiting_ack"
    both = await observe("C", "accepted_for_next_step", "accept-C")
    assert (
        both["current_ack_state"] == "accepted_for_next_step"
        and both["next_action_state"] == "ready"
    )
    conflict = await observe("B", "changes_requested", "contradiction")
    assert conflict["current_ack_state"] == "conflict" and conflict["artifact_readiness"] == "ready"
    resolved = await observe("B", "accepted_for_next_step", "updated", "contradiction")
    assert resolved["next_action_state"] == "ready"
    capture("member-responses", states)


async def test_delivery_recovery_and_later_edit(
    bridge, owner, tmp_path, parsed_locally, independent_recipient
):
    import sqlite3

    from canvas_bridge.domain import DomainError
    from canvas_bridge.processes import handoff_outputs as ops

    service = bridge.processes
    req = await seed(bridge, owner)
    rid = req["record_id"]
    saved = await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    subject = dict(
        record_id=rid,
        handoff_id=req["handoff_id"],
        work_revision=1,
        packet_id=saved.data["packet_id"],
    )
    output = (
        await hs.export(
            service, owner, hm.Export(**subject, journal_revision=1, idempotency_key="json")
        )
    ).data
    op = hm.OutputOperation(
        **subject,
        journal_revision=2,
        idempotency_key="send-fixture",
        destination_ref="fixture-inbox",
        kind="delivery",
        recipient_ids=["B"],
        output_id=output["output_id"],
        confirmed=True,
    )
    with pytest.raises(DomainError) as exc:
        await ops.operate(service, owner, op)
    assert exc.value.reason_code == "HANDOFF_ADAPTER_UNAVAILABLE"
    service.handoff_output_adapter = FixtureOutput(tmp_path / "fixture")
    denied = op.model_copy(update=dict(recipient_ids=["A"]))
    with pytest.raises(DomainError):
        await ops.operate(service, owner, denied)
    lost = (await ops.operate(service, owner, op)).data
    assert lost["status"] == "uncertain"
    change = deepcopy(req)
    change.update(
        expected_packet=saved.data["packet_id"],
        idempotency_key="update",
        journal_revision=lost["revision"],
        presentation_note="Keep my later note",
    )
    await hs.prepare(service, owner, hm.Prepare.model_validate(change))
    current = (await hs.view(service, owner, rid, req["handoff_id"])).data
    assert current["packet"]["delivery_state"] == "not_requested"
    with pytest.raises(DomainError):
        await ops.operate(
            service,
            owner,
            op.model_copy(
                update=dict(
                    journal_revision=current["journal_revision"], idempotency_key="obsolete"
                )
            ),
        )
    recovered = (
        await ops.operate(
            service,
            owner,
            op.model_copy(
                update=dict(
                    journal_revision=current["journal_revision"],
                    idempotency_key="reconcile",
                    confirmed=False,
                    reconcile_only=True,
                )
            ),
        )
    ).data
    assert recovered["status"] == "confirmed"
    old = (await hs.view(service, owner, rid, req["handoff_id"], saved.data["packet_id"])).data[
        "packet"
    ]
    assert old["delivery_state"] == "confirmed" and old["current_ack_state"] == "none"
    with sqlite3.connect(service.handoff_output_adapter.db) as db:
        assert db.execute("select count(*) from effects").fetchone()[0] == 1
    capture(
        "delivery-recovery",
        dict(initial=lost, recovered=recovered, historical=old, current=current["packet"]),
    )


async def test_action_scoped_conditions_and_inputs(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.domain import DomainError

    service = bridge.processes
    req = await seed(bridge, owner)
    req["conditions"] = [
        dict(
            blocker_id="station",
            state="blocked",
            scope="downstream_execution",
            next_action="Wait for equipment release",
            source_ref="lab-availability",
            revision="1",
        )
    ]
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))

    async def read():
        return (await hs.view(service, owner, req["record_id"], req["handoff_id"])).data

    p = (await read())["packet"]
    assert (
        p["next_action_state"] == "ready"
        and p["condition_states"]["downstream_execution"] == "blocked"
    )
    await hs.record_response(
        service,
        owner,
        hm.Response(
            record_id=req["record_id"],
            work_revision=1,
            handoff_id=req["handoff_id"],
            packet_id=p["packet_id"],
            journal_revision=1,
            idempotency_key="ack",
            observation_id="r",
            expected_observation_revision=0,
            acknowledged_by="B",
            state="received",
            evidence_ref="member-note",
            evidence_basis="supplied_relayed_response",
            observed_at=datetime.now(UTC),
        ),
    )
    req["conditions"][0].update(revision="2", state="conditional")
    req.update(journal_revision=2, idempotency_key="irrelevant", expected_packet=p["packet_id"])
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    independent = (await read())["packet"]
    assert (
        independent["current_ack_state"] == "received"
        and independent["semantic_basis_id"] == p["semantic_basis_id"]
    )
    req["conditions"][0].update(scope="transfer", revision="3", state="blocked")
    req.update(
        journal_revision=3, idempotency_key="relevant", expected_packet=independent["packet_id"]
    )
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    transfer = (await read())["packet"]
    assert (
        transfer["next_action_state"] == "blocked"
        and transfer["next_step"] == "Wait for equipment release"
        and transfer["responses"][0]["applicability"] == "historical"
    )
    req.update(
        conditions=[],
        journal_revision=4,
        idempotency_key="missing",
        expected_packet=transfer["packet_id"],
    )
    req["action"].update(revision="2", required_inputs=[dict(logical_id="unavailable-input")])
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    missing = (await read())["packet"]
    assert missing["next_action_state"] == "unknown" and missing["artifact_readiness"] == "ready"
    old_note = hm.Restore(
        record_id=req["record_id"],
        work_revision=1,
        journal_revision=5,
        handoff_id=req["handoff_id"],
        idempotency_key="stale-restore",
        packet_id=independent["packet_id"],
        expected_packet=missing["packet_id"],
        fields=["action"],
    )
    with pytest.raises(DomainError) as exc:
        await hs.restore(service, owner, old_note)
    assert exc.value.reason_code == "HANDOFF_RESTORE_CONFLICT"
    capture("scoped-conditions", dict(independent=independent, blocked=transfer, missing=missing))


def test_partial_correspondence_keeps_original_observation_unresolved():
    # Independent control over a genuine C transition: an incomplete dependency
    # comparison must never carry the original response to a new artifact.
    original = dict(
        assignment_id="assignment",
        work_episode_id="episode",
        responsibility={"responsible_actor": "A"},
        action={"action_id": "review"},
        conditions=[],
        governing_conditions=["ready"],
        process_step=None,
        process_input_version=None,
        input_versions=[],
        inventory_complete=True,
        artifact=dict(logical_artifact_id="artifact", artifact_version="old", scope_locator="body"),
        requirements=[dict(requirement_id="R1", dependencies={"artifact": "old"})],
    )
    revised = deepcopy(original)
    revised["artifact"]["artifact_version"] = "new"
    revised["requirements"][0]["dependencies"]["artifact"] = "new"
    from types import SimpleNamespace

    record = SimpleNamespace(
        revision=3,
        data=dict(
            change_report=dict(
                base_revision=2,
                applied_revision=3,
                comparisons=[
                    dict(
                        logical_id="artifact",
                        before_hash="old",
                        after_hash="new",
                        change_class="content_equivalent",
                        comparison_coverage="partial",
                        proof_id="insufficient",
                    )
                ],
            )
        ),
    )
    previous = dict(
        semantic_basis=original,
        semantic_basis_id="before",
        equivalent_basis_ids=[],
        work_revision=1,
    )
    current = dict(
        semantic_basis=revised,
        semantic_basis_id="after",
        assessment=dict(criteria=[dict(requirement_id="R1", proof_id=None)]),
    )
    verdict = hs.correspondence(previous, current, record)
    assert verdict == ("unresolved", [])
    capture("incomplete-proof", dict(correspondence=verdict[0], accepted_proofs=verdict[1]))


async def test_resource_condition_reconciliation(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.processes import resource_service as e
    from tests.test_phase_e_resources import seed as seed_e

    req = await seed_e(bridge, owner)
    service = bridge.processes
    rid = req["record_id"]
    req["process"]["steps"][1]["resource_requirement"]["booking_required"] = True
    await e.save(service, owner, e.Save.model_validate(req))
    g = (await e.view(service, owner, rid, "TYPED")).data["generation"]
    f = request(rid)
    f["responsibility"].update(
        identity_basis="explicit_declaration", source_ref="role-declaration", evidence=None
    )
    f.update(
        work_id=g["work_id"],
        process=dict(process_id="TYPED", generation_id=g["generation_id"], step_id="run"),
        journal_revision=2,
    )
    f["action"].update(requires_process_context=True, prerequisite_ids=[])
    await hs.prepare(service, owner, hm.Prepare.model_validate(f))

    async def read():
        return (await hs.view(service, owner, rid, f["handoff_id"])).data["packet"]

    old = await read()
    assert old["next_action_state"] == "conditional"
    await hs.record_response(
        service,
        owner,
        hm.Response(
            record_id=rid,
            work_revision=1,
            journal_revision=3,
            handoff_id=f["handoff_id"],
            packet_id=old["packet_id"],
            idempotency_key="response",
            observation_id="B",
            expected_observation_revision=0,
            acknowledged_by="B",
            state="received",
            evidence_basis="supplied_relayed_response",
            evidence_ref="note",
            observed_at=datetime.now(UTC),
        ),
    )
    updated = deepcopy(req)
    updated.update(
        expected_generation=g["generation_id"],
        trigger="access_change",
        journal_revision=4,
        idempotency_key="access",
    )
    alloc = g["allocations"][0]
    updated["inventory"]["resources"][0].update(
        revision="2",
        reservations=[
            dict(
                id="booking",
                revision="1",
                owner_step_id="run",
                status="confirmed",
                quantity=1,
                unit="station",
                source_ref="fixture-confirmation",
                start_at=alloc["start_at"],
                end_at=alloc["end_at"],
            )
        ],
    )
    await e.save(service, owner, e.Save.model_validate(updated))
    g2 = (await e.view(service, owner, rid, "TYPED")).data["generation"]
    stale = await read()
    assert (
        stale["next_action_state"] == "requires_rebase"
        and stale["process_context"]["scope_state"] == "unknown"
    )
    f.update(expected_packet=old["packet_id"], journal_revision=5, idempotency_key="new-process")
    f["process"]["generation_id"] = g2["generation_id"]
    await hs.prepare(service, owner, hm.Prepare.model_validate(f))
    current = await read()
    assert (
        current["next_action_state"] == "ready"
        and current["responses"][0]["applicability"] == "historical"
    )
    capture("changed-process", dict(old=old, stale=stale, current=current))


async def test_alias_import_and_payload_readback(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.processes import change_service as change

    service = bridge.processes
    req = await seed(bridge, owner, "handoff_draft")
    rid = req["record_id"]
    await hs.prepare(service, owner, hm.Prepare.model_validate(req))
    p = (await hs.view(service, owner, rid, req["handoff_id"])).data["packet"]
    await hs.record_response(
        service,
        owner,
        hm.Response(
            record_id=rid,
            work_revision=1,
            handoff_id=req["handoff_id"],
            packet_id=p["packet_id"],
            journal_revision=1,
            idempotency_key="ack",
            observation_id="reply",
            expected_observation_revision=0,
            acknowledged_by="B",
            state="received",
            evidence_basis="supplied_relayed_response",
            evidence_ref="declared",
            observed_at=datetime.now(UTC),
        ),
    )
    raw = content("fixtures/model_inputs/handoff_draft.md")
    alias = await bridge.independent.ingest(
        owner,
        raw,
        "alternate-name.md",
        "text/markdown",
        course="Studio",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
    )
    target = [
        b | dict(document_id=alias) if b["role"] == "artifact" else b
        for b in rd.snapshot(service.repository, owner, rid).data["bindings"]
    ]
    staged = (
        await change.observe(
            service,
            owner,
            change.Observation(
                record_id=rid, expected_revision=1, target=target, idempotency_key="alias"
            ),
        )
    ).data
    applied = (
        await change.apply_change(
            service,
            owner,
            change.Reassessment(
                record_id=rid,
                expected_revision=staged["revision"],
                change_id=staged["change_id"],
                idempotency_key="apply",
                inventory_complete=True,
            ),
        )
    ).data
    await hs.prepare(
        service,
        owner,
        hm.Prepare.model_validate(
            req
            | dict(
                journal_revision=2,
                work_revision=applied["revision"],
                expected_packet=p["packet_id"],
                idempotency_key="alias-packet",
            )
        ),
    )
    current = (await hs.view(service, owner, rid, req["handoff_id"])).data["packet"]
    assert (
        current["semantic_basis_id"] == p["semantic_basis_id"]
        and current["responses"][0]["applicability"] == "current_exact"
    )
    exported = (
        await hs.export(
            service,
            owner,
            hm.Export(
                record_id=rid,
                work_revision=applied["revision"],
                journal_revision=3,
                idempotency_key="alias-export",
                packet_id=current["packet_id"],
                handoff_id=req["handoff_id"],
                output_format="markdown",
            ),
        )
    ).data
    fetched = (
        await hs.view(
            service,
            owner,
            rid,
            req["handoff_id"],
            packet_id=current["packet_id"],
            output_id=exported["output_id"],
        )
    ).data["exported_output"]
    assert (
        fetched["payload"] == exported["payload"]
        and hashlib.sha256(fetched["payload"].encode()).hexdigest() == exported["content_hash"]
    )
    assert (
        "## Artifact and evidence" in fetched["payload"]
        and "Evidence appendix" in fetched["payload"]
    )
    capture(
        "alias",
        dict(
            before=p["packet_id"],
            after=current,
            applied=applied,
            output_hash=fetched["content_hash"],
        ),
    )
