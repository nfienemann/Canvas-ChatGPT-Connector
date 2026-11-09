"""Product adapters exercised against independently authored Phase E expected vectors."""

import json
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.processes import resource_engine as engine
from canvas_bridge.processes.resource_models import Candidate, Inventory, Lead, Process, Schedule
from tests.test_independent_intelligence import independent_recipient as independent_recipient
from tests.test_recovery_independence import parsed_locally as parsed_locally

BUNDLE = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-e/specs.zip"


def fixture(name):
    with ZipFile(BUNDLE) as archive:
        return json.loads(archive.read("phase_e_resources/fixtures/" + name + ".json"))


def inputs(name):
    schedules = fixture("schedules")["schedules"]
    s = next(r for r in schedules if r["id"] == name)
    proc = next(r for r in fixture("processes")["processes"] if r["id"] == s["process_ref"])
    inventory = fixture("resources")
    resources = [r | s.get("resource_patches", {}).get(r["id"], {}) for r in inventory["resources"]]
    return (
        Process.model_validate(proc),
        Inventory(
            resources=resources, calendars=inventory["calendars"] + s.get("calendar_additions", [])
        ),
        Schedule.model_validate({k: v for k, v in s.items() if k in Schedule.model_fields}),
    )


def subset(expected, actual):
    if isinstance(expected, dict):
        for key, value in expected.items():
            subset(value, actual[key])
    else:
        assert actual == expected


@pytest.mark.parametrize(
    "scenario",
    [s for s in fixture("scenarios")["scenarios"] if s.get("schedule_refs")],
    ids=lambda s: s["id"],
)
def test_candidates(scenario):
    expected = fixture("expected")["results"][scenario["id"]]["schedule_results"]
    for name in scenario["schedule_refs"]:
        process, inventory, schedule = inputs(name)
        result = engine.plan(process, inventory, schedule, generate=False)
        subset(expected[name], result)
        capture(name, result)
        generated = engine.plan(process, inventory, schedule.model_copy(update=dict(candidates=())))
        if name in {
            "typed",
            "chain",
            "capacity",
            "stable",
            "failure",
            "supply",
            "recurrence",
            "booking",
        }:
            assert generated["status"] == "feasible", generated


def test_operating_clocks_and_leads():
    values = fixture("expected")["results"]
    calendars = {c["id"]: c for c in fixture("resources")["calendars"]}
    for s in fixture("scenarios")["scenarios"]:
        for row in s.get("clock_cases", []):
            start = engine.instant(row["anchor"])
            result = engine.shift_clock(
                start,
                row["minutes"],
                row["clock"],
                calendars,
                row.get("calendar_ref"),
                row["direction"],
            )
            from zoneinfo import ZoneInfo

            observed = dict(
                at=result.isoformat(), elapsed_minutes=abs(engine.minutes(start, result))
            )
            if row.get("calendar_ref"):
                observed["calendar_revision"] = calendars[row["calendar_ref"]]["revision"]
            if row.get("display_timezone"):
                local = result.astimezone(ZoneInfo(row["display_timezone"]))
                observed.update(fold=local.fold, display_at=local.isoformat())
            subset(values[s["id"]]["clock_results"][row["id"]], observed)
            capture(row["id"], observed)
        for row in s.get("lead_cases", []):
            lead = Lead.model_validate({k: v for k, v in row.items() if k in Lead.model_fields})
            observed = engine.lead_bounds(lead, calendars)
            subset(values[s["id"]]["lead_results"][row["id"]], observed)
            capture("lead-" + row["id"], observed)


def capture(name, value):
    import os

    if folder := os.environ.get("BRIDGE_PHASE_E_OUTPUT"):
        output = Path(folder)
        output.mkdir(exist_ok=True, parents=True)
        (output / (name + ".json")).write_text(json.dumps(value, indent=2), "utf8")


class FixtureProvider:
    """Durable conditional fixture effects; a lost response occurs after committing."""

    def __init__(self, path):
        import sqlite3

        self.path = path
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS bases(owner TEXT,axis TEXT,key TEXT,revision TEXT,PRIMARY KEY(owner,axis,key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS effects(owner TEXT,key TEXT, receipt TEXT,PRIMARY KEY(owner,key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS objects(owner TEXT,key TEXT, revision TEXT,PRIMARY KEY(owner,key))"
            )

    def supports(self, kind, resource_id, action):
        return kind in {"reservation", "calendar"} and action in {"create", "update", "remove"}

    async def lookup(self, owner, key):
        import sqlite3

        from canvas_bridge.processes.resource_effects import EffectReceipt

        with sqlite3.connect(self.path) as db:
            saved = db.execute(
                "SELECT receipt FROM effects WHERE owner=? AND key=?", (owner, key)
            ).fetchone()
        return EffectReceipt.model_validate_json(saved[0]) if saved else None

    async def apply(self, owner, o):
        import sqlite3

        from canvas_bridge.processes.resource_effects import EffectReceipt

        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT receipt FROM effects WHERE owner=? AND key=?", (owner, o["operation_id"])
            ).fetchone()
            if prior:
                return EffectReceipt.model_validate_json(prior[0])
            current = db.execute(
                "SELECT revision FROM objects WHERE owner=? AND key=?", (owner, o["logical_id"])
            ).fetchone()
            valid = (current[0] if current else None) == o["expected_provider_revision"]
            for axis in ("resources", "reservations", "calendars"):
                for base in o["expected_bases"][axis]:
                    live = db.execute(
                        "SELECT revision FROM bases WHERE owner=? AND axis=? AND key=?",
                        (owner, axis, base["id"]),
                    ).fetchone()
                    if live is not None and live[0] != base["revision"]:
                        valid = False
            receipt = EffectReceipt(
                operation_id=o["operation_id"],
                payload_hash=o["payload_hash"],
                object_id=o["logical_id"],
                provider_revision=o["operation_id"][:12],
                status="confirmed" if valid else "conflict",
            )
            if valid and o["after"] is None:
                db.execute("DELETE FROM objects WHERE owner=? AND key=?", (owner, o["logical_id"]))
            elif valid:
                db.execute(
                    "INSERT OR REPLACE INTO objects VALUES(?,?,?)",
                    (owner, o["logical_id"], receipt.provider_revision),
                )
            db.execute(
                "INSERT INTO effects VALUES(?,?,?)",
                (owner, o["operation_id"], receipt.model_dump_json()),
            )
        if o["kind"] == "reservation" and valid:
            raise TimeoutError("Fixture reply lost after commit")
        return receipt


async def seed(bridge, owner):
    from canvas_bridge.processes import effort_service as es
    from canvas_bridge.processes import readiness as rd
    from tests.test_phase_b_readiness import authored_review, import_case

    bridge.settings.process_features_enabled = True
    packet = await import_case(bridge, owner, "baseline")
    record = rd.save(bridge.processes, owner, authored_review(packet, "BASELINE")).data["record_id"]
    work = rd.view(bridge.processes, owner, record).data["remaining_work"][0]
    f = (
        await es.issue(
            bridge.processes,
            owner,
            es.ForecastRequest(
                record_id=record,
                work_revision=1,
                journal_revision=0,
                idempotency_key="estimate",
                work_id=work["work_id"],
                scope_id="prototype",
                task_family="studio",
                scope_kind="remaining_episode",
                baseline=dict(low=65, high=65),
            ),
        )
    ).data["forecast"]
    proc, inventory, schedule = inputs("typed")
    steps = [
        s.model_copy(
            update=dict(
                episode_id=f["episode_id"], work_lineage_id=f.get("lineage_id") or f["work_id"]
            )
        )
        for s in proc.steps
    ]
    proc = proc.model_copy(
        update=dict(
            steps=tuple(steps),
            active_demand_mapping=proc.active_demand_mapping.model_copy(
                update=dict(
                    parent_forecast_ref=f["forecast_id"], active_demand_scope_id=f["scope_id"]
                )
            ),
        )
    )
    # Keep wire/restart scenarios prospective on later replays. The canonical
    # arithmetic scenarios above always execute their original dated instants.
    from datetime import timedelta

    delta = bridge.processes.repository.clock() - schedule.planning_boundary
    if delta >= timedelta(0):
        advance = timedelta(weeks=delta.days // 7 + 1)

        def shifted(spans):
            return tuple(
                w.model_copy(update=dict(start_at=w.start_at + advance, end_at=w.end_at + advance))
                for w in spans
            )

        inventory = inventory.model_copy(
            update=dict(
                calendars=tuple(
                    c.model_copy(update=dict(windows=shifted(c.windows)))
                    for c in inventory.calendars
                )
            )
        )
        schedule = schedule.model_copy(
            update=dict(
                planning_boundary=schedule.planning_boundary + advance,
                deadline_at=schedule.deadline_at + advance,
                student_windows=shifted(schedule.student_windows),
            )
        )
    return dict(
        record_id=record,
        work_revision=1,
        journal_revision=1,
        idempotency_key="plan",
        forecast_id=f["forecast_id"],
        process=proc.model_dump(mode="json"),
        inventory=inventory.model_dump(mode="json"),
        schedule=schedule.model_copy(update=dict(candidates=())).model_dump(mode="json"),
    )


async def test_signed_resource_lifecycle(
    bridge, settings, owner, token_factory, parsed_locally, independent_recipient, tmp_path
):
    from contextlib import asynccontextmanager

    from canvas_bridge.storage import IndependentResource
    from tests.test_mcp_contract import running
    from tests.test_permission_consistency_contract import client_session

    start = await seed(bridge, owner)
    rid = start["record_id"]
    req = start["process"]["steps"][1]["resource_requirement"]
    req.update(booking_required=True, resource_ids=["FORM-A", "FORM-B"])
    provider = FixtureProvider(tmp_path / "resource-provider.db")
    bridge.processes.resource_provider = provider
    transcript = []
    async with (
        asynccontextmanager(running.__wrapped__)(bridge, settings, None) as url,
        client_session(url, token_factory(), read_timeout=120) as session,
    ):
        from canvas_bridge.processes.surfaces import TOOLS

        capture(
            "schemas",
            [
                t.model_dump(mode="json", exclude_none=True)
                for t in (await session.list_tools()).tools
                if t.name in TOOLS and "resource" in t.name
            ],
        )

        async def call(name, args, success=True):
            result = (await session.call_tool(name, args)).structuredContent
            transcript.append(dict(tool=name, arguments=args, response=result))
            assert (result["status"] == "ok") == success, (name, result["summary"], result["data"])
            return result["data"]

        async def read():
            return await call("get_resource_plan", dict(record_id=rid, process_id="TYPED"))

        saved = await call("save_resource_plan", dict(request=start))
        assert (await call("save_resource_plan", dict(request=start))) == saved
        state = await read()
        g = state["generation"]
        assert g["result"]["active_minutes"] == 65 and g["result"]["passive_elapsed_minutes"] == 120
        resource = next(o for o in g["operations"] if o["kind"] == "reservation")
        linked = next(o for o in g["operations"] if o["kind"] == "calendar" and o["dependencies"])
        other = next(
            o for o in g["operations"] if o["kind"] == "calendar" and not o["dependencies"]
        )

        def operation(op, revision, key):
            return dict(
                request=dict(
                    record_id=rid,
                    work_revision=1,
                    journal_revision=revision,
                    idempotency_key=key,
                    generation_id=g["generation_id"],
                    process_id="TYPED",
                    operation_id=op["operation_id"],
                    confirmed=True,
                )
            )

        assert (
            await call("apply_resource_plan_operation", operation(linked, 2, "too-early"), False)
        )["reason_code"] == "RESOURCE_DEPENDENCY_PENDING"
        first = await call("apply_resource_plan_operation", operation(other, 2, "calendar"))
        lost = await call(
            "apply_resource_plan_operation", operation(resource, first["revision"], "booking")
        )
        assert lost["status"] == "uncertain"
        partial = (await read())["generation"]
        assert partial["confirmed_effect_count"] == 1 and not partial["fully_applied_objects"]
        bridge.processes.resource_provider = FixtureProvider(provider.path)
        found = await call(
            "apply_resource_plan_operation", operation(resource, lost["revision"], "recover")
        )
        assert found["status"] == "confirmed"
        current = (await read())["generation"]
        assert current["confirmed_effect_count"] == 2
        assert not next(h for h in current["handoff"] if h["step_id"] == "run")["blocker_refs"]
        change = deepcopy(start)
        change.update(
            expected_generation=g["generation_id"],
            journal_revision=found["revision"],
            idempotency_key="outage",
            trigger="access_change",
        )
        change["inventory"]["resources"][0].update(
            revision="2", unavailable=change["inventory"]["calendars"][1]["windows"]
        )
        await call("save_resource_plan", dict(request=change))
        repaired = (await read())["generation"]
        assert repaired["allocations"][0]["resource_id"] == "FORM-B"
        assert repaired["result"]["churn"]["changed_existing_block_count"] == 0
        assert sorted(repaired["affected_step_ids"]) == ["finish", "run"]
        assert (
            await call(
                "save_resource_plan", dict(request=change | dict(idempotency_key="stale")), False
            )
        )["reason_code"] == "PROCESS_REVISION_MISMATCH"
        import sqlite3

        with sqlite3.connect(provider.path) as db:
            assert db.execute("select count(*) from effects").fetchone()[0] == 2
        # Confirm an additional independent event. A later provider edit must survive its inverse.
        g = repaired
        available = next(
            o
            for o in g["operations"]
            if o["kind"] == "calendar" and o["status"] == "pending" and not o["dependencies"]
        )
        result = await call(
            "apply_resource_plan_operation",
            operation(available, (await read())["journal_revision"], "finish-event"),
        )
        with sqlite3.connect(provider.path) as db:
            db.execute(
                "UPDATE objects SET revision='later-user-edit' WHERE owner=? AND key=?",
                (owner, available["logical_id"]),
            )
        undo = await call(
            "compensate_resource_effects",
            dict(
                request=dict(
                    record_id=rid,
                    work_revision=1,
                    journal_revision=result["revision"],
                    generation_id=g["generation_id"],
                    process_id="TYPED",
                    operation_ids=[available["operation_id"]],
                    idempotency_key="undo-finish",
                )
            ),
        )
        g = (await read())["generation"]
        inverse = next(
            o for o in g["operations"] if o.get("compensates") == available["operation_id"]
        )
        conflict = await call(
            "apply_resource_plan_operation", operation(inverse, undo["revision"], "protect-edit")
        )
        assert conflict["status"] == "conflict"
        with sqlite3.connect(provider.path) as db:
            assert (
                db.execute(
                    "SELECT revision FROM objects WHERE owner=? AND key=?",
                    (owner, available["logical_id"]),
                ).fetchone()[0]
                == "later-user-edit"
            )
        with ZipFile(BUNDLE) as archive:
            contract = json.loads(archive.read("phase_e_resources/contracts/phase_f_handoff.json"))
        for row in repaired["handoff"]:
            assert set(contract["record_fields"]) <= row.keys()
            assert all(
                set(contract["artifact_ref_fields"]) <= a.keys()
                for a in row["required_artifact_refs"]
            )
            assert all(set(contract["blocker_fields"]) <= b.keys() for b in row["blocker_refs"])
        capture("phase-f-handoff", repaired["handoff"])
        with bridge.store.transaction() as db:
            doc = db.get(
                IndependentResource,
                repaired["handoff"][0]["required_artifact_refs"][0]["artifact_id"],
            )
            doc.provenance = doc.provenance | dict(share_text=False)
        await call("get_resource_plan", dict(record_id=rid, process_id="TYPED"), False)
        capture("signed-lifecycle", transcript)


def served_resources(raw, sock):
    import contextlib

    import uvicorn

    from canvas_bridge.app import create_app
    from canvas_bridge.config import Settings
    from tests.conftest import bridge as create_bridge

    settings = Settings.model_validate_json(raw)
    with contextlib.contextmanager(create_bridge.__wrapped__)(settings) as bridge:
        bridge.processes.resource_provider = FixtureProvider(
            Path(settings.database_url.removeprefix("sqlite:///")).with_suffix(".provider.db")
        )
        uvicorn.Server(
            uvicorn.Config(create_app(settings, bridge), log_level="error", access_log=False)
        ).run(sockets=[sock])


@pytest.mark.skipif(
    not __import__("os").environ.get("BRIDGE_PHASE_E_HOST"), reason="Opt-in native synthetic host"
)
async def test_native_resource_journey(
    settings, owner, token_factory, tmp_path, parsed_locally, independent_recipient, monkeypatch
):
    import contextlib
    import os

    from tests import test_phase_b_readiness as host
    from tests.conftest import bridge as create_bridge
    from tests.test_permission_consistency_contract import client_session

    settings.database_url = "sqlite:///" + str(tmp_path / "state.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    monkeypatch.setattr(host, "serve", served_resources)
    out = Path(os.environ["BRIDGE_PHASE_E_HOST"])
    import asyncio

    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    empty = tmp_path / "host"
    empty.mkdir()
    with contextlib.contextmanager(create_bridge.__wrapped__)(settings) as bridge:
        request = await seed(bridge, owner)
    req = request["process"]["steps"][1]["resource_requirement"]
    req.update(resource_ids=["FORM-A", "FORM-B"], booking_required=True)
    record_id = request["record_id"]
    state = None
    prompts = [
        "plan_lab_studio",
        "explain_latest_start",
        "repair_changed_access",
        "recover_reservations",
    ]
    for n, name in enumerate(prompts):
        selected = dict(record_id=record_id, process_id="TYPED")
        if n == 0:
            selected["save_request"] = request
        if n == 2:
            change = deepcopy(request)
            change.update(
                expected_generation=state["generation"]["generation_id"],
                journal_revision=state["journal_revision"],
                idempotency_key="resource-outage",
                trigger="access_change",
            )
            change["inventory"]["resources"][0].update(
                revision="2", unavailable=change["inventory"]["calendars"][1]["windows"]
            )
            selected["save_request"] = change
        if n == 3:
            async with host.running(settings) as pid:
                async with client_session(
                    settings.resource_url, token_factory(), read_timeout=120
                ) as session:

                    async def call(tool, args):
                        r = (await session.call_tool(tool, args)).structuredContent
                        assert r["status"] == "ok", (r["summary"], r["data"])
                        return r["data"]

                    state = await call(
                        "get_resource_plan", dict(record_id=record_id, process_id="TYPED")
                    )
                    g = state["generation"]
                    other = next(
                        o
                        for o in g["operations"]
                        if o["kind"] == "calendar" and not o["dependencies"]
                    )
                    reserve = next(
                        o for o in g["operations"] if o["kind"] == "reservation" and o["after"]
                    )
                    for i, op in enumerate([other, reserve]):
                        await call(
                            "apply_resource_plan_operation",
                            dict(
                                request=dict(
                                    record_id=record_id,
                                    process_id="TYPED",
                                    work_revision=1,
                                    journal_revision=state["journal_revision"],
                                    generation_id=g["generation_id"],
                                    operation_id=op["operation_id"],
                                    idempotency_key="interrupt-" + str(i),
                                    confirmed=True,
                                )
                            ),
                        )
                        state = await call(
                            "get_resource_plan", dict(record_id=record_id, process_id="TYPED")
                        )
                    selected["authorized_recovery_operation"] = reserve["operation_id"]
                    selected["user_intent"] = (
                        "Reconcile this interrupted reservation with the fixture provider. Leave the other proposed operations unissued."
                    )
                    (out / "before-recovery-restart.json").write_text(
                        json.dumps(dict(pid=pid, state=state), indent=2), "utf8"
                    )
        async with host.running(settings) as pid:
            async with client_session(
                settings.resource_url, token_factory(), read_timeout=120
            ) as session:

                async def call(tool, args):
                    r = (await session.call_tool(tool, args)).structuredContent
                    assert r["status"] == "ok", (r["summary"], r["data"])
                    return r["data"]

                with ZipFile(BUNDLE) as z:
                    prompt = z.read("phase_e_resources/prompts/" + name + ".md").decode()
                answer = await host.review_host(
                    settings.resource_url,
                    token_factory(),
                    prompt + "\nSelected synthetic context: " + json.dumps(selected),
                    empty,
                    out,
                    name,
                    tools=[
                        "save_resource_plan",
                        "get_resource_plan",
                        "apply_resource_plan_operation",
                    ],
                    instructions="Use only the coursework MCP tools. No files, shell, network, other apps or tools. This local fixture provider is synthetic. Use the supplied save_request for the explicit plan or repair and retrieve it afterward. Do not apply proposed effects except the specifically authorized interrupted operation. Report actual scope, active attendance, passive minutes, equipment and booking evidence separately. Use the saved proof scope for latest-start claims.",
                )
                assert answer
                state = await call(
                    "get_resource_plan", dict(record_id=record_id, process_id="TYPED")
                )
                (out / (name + "-readback.json")).write_text(
                    json.dumps(dict(pid=pid, state=state), indent=2), "utf8"
                )
                assert state["generation"]["result"]["active_minutes"] == 65
                if n >= 2:
                    assert state["generation"]["allocations"][0]["resource_id"] == "FORM-B"
                if n == 3:
                    assert state["generation"]["confirmed_effect_count"] == 2


def test_validation_and_isolated_unknown():
    from pydantic import ValidationError

    raw = fixture("scenarios")["scenarios"][7]
    expected = fixture("expected")["results"][raw["id"]]["input_results"]
    captured = {}
    for case in raw["invalid_cases"]:
        r = case["process"]
        if case["id"] == "negative":
            with pytest.raises(ValidationError):
                Process.model_validate(r)
        result = engine.validate_process(r)
        subset(expected[case["id"]], result)
        captured[case["id"]] = result
    proc, inv, s = inputs("failure")
    uncertain = proc.steps[0].model_copy(
        update=dict(
            run_duration=proc.steps[0].run_duration.model_copy(update=dict(maximum_minutes=None))
        )
    )
    result = engine.plan(proc.model_copy(update=dict(steps=(uncertain, proc.steps[1]))), inv, s)
    assert result["blocked_step_ids"] == [uncertain.id]
    assert result["known_steps_plan"]["active_minutes"] == 30
    capture("typed-validation", captured | dict(partial=result))


def test_phase_d_bindings_and_overlap():
    from canvas_bridge.processes.resource_service import StudyBinding, inherited_schedule

    proc, inventory, schedule = inputs("stable")
    step = proc.steps[0]
    parent = dict(work_id="parent", episode_id=step.episode_id)
    existing = dict(
        block_id="persisted-d",
        task_id="parent",
        episode_id=step.episode_id,
        start=schedule.base_blocks[0].start_at.isoformat(),
        end=schedule.base_blocks[0].end_at.isoformat(),
        locked=True,
    )
    from canvas_bridge.domain import DomainError

    with pytest.raises(DomainError):
        inherited_schedule(
            schedule,
            None,
            dict(selected_blocks=[existing]),
            schedule.planning_boundary,
            [],
            parent,
            proc,
        )
    bound = inherited_schedule(
        schedule,
        None,
        dict(selected_blocks=[existing]),
        schedule.planning_boundary,
        [StudyBinding(block_id="persisted-d", step_id=step.id)],
        parent,
        proc,
    )
    result = engine.plan(proc, inventory, bound)
    assert result["churn"]["changed_existing_block_count"] == 0 and result[
        "protected_block_ids"
    ] == [step.id + "/active"]
    capture("phase-d-binding", dict(parent=existing, checked=result))


async def test_observation_only_and_native_calendar(
    bridge, owner, parsed_locally, independent_recipient
):
    from datetime import UTC, datetime

    from canvas_bridge.domain import DomainError
    from canvas_bridge.processes import resource_effects as effects
    from canvas_bridge.processes import resource_service as service

    start = await seed(bridge, owner)
    start["process"]["steps"][1]["resource_requirement"]["booking_required"] = True
    process = bridge.processes
    await service.save(process, owner, service.Save.model_validate(start))

    async def read():
        return (await service.view(process, owner, start["record_id"], "TYPED")).data

    data = await read()
    g = data["generation"]
    reservation = next(o for o in g["operations"] if o["kind"] == "reservation")
    common = dict(
        record_id=start["record_id"],
        work_revision=1,
        generation_id=g["generation_id"],
        process_id="TYPED",
    )
    with pytest.raises(DomainError) as exc:
        await effects.apply(
            process,
            owner,
            effects.Apply(
                **common,
                operation_id=reservation["operation_id"],
                journal_revision=2,
                idempotency_key="book",
                confirmed=True,
            ),
        )
    assert exc.value.reason_code == "RESOURCE_OBSERVATION_ONLY"
    op = next(o for o in g["operations"] if o["kind"] == "calendar" and not o["dependencies"])
    ctx = dict(
        calendar_id="studio",
        timezone="UTC",
        window_start=start["schedule"]["planning_boundary"],
        window_end=start["schedule"]["deadline_at"],
        mapping_search_complete=True,
        pagination_complete=True,
        availability_complete=True,
        events=[],
    )

    def request(rev, key, events, prepare):
        return effects.CalendarReadback(
            **common,
            journal_revision=rev,
            idempotency_key=key,
            operation_id=op["operation_id"],
            calendar=ctx | dict(events=events, retrieved_at=datetime.now(UTC)),
            prepare_confirmed_action=prepare,
        )

    await effects.check_calendar(process, owner, request(2, "prepare", [], True))
    states = (await read())["generation"]["operations"]
    assert (
        next(o for o in states if o["operation_id"] == op["operation_id"])["status"]
        == "host_issued"
    )
    event = dict(
        id="event",
        title="Study",
        version="r1",
        start=op["after"]["start_at"],
        end=op["after"]["end_at"],
        bridge_marker=op["marker"],
        status="confirmed",
    )
    await effects.check_calendar(process, owner, request(3, "observe", [event], False))
    g = (await read())["generation"]
    assert g["confirmed_effect_count"] == 1 and g["apply_status"] == "partially_applied"
    capture(
        "host-calendar",
        dict(observed=g["current_effects"], remaining=g["unresolved_operation_ids"]),
    )


@pytest.mark.parametrize("axis", ["resources", "reservations", "calendars"])
async def test_provider_changed_snapshot_has_no_effect(
    axis, bridge, owner, parsed_locally, independent_recipient, tmp_path
):
    import sqlite3

    from canvas_bridge.processes import resource_effects as effects
    from canvas_bridge.processes import resource_service as service

    request = await seed(bridge, owner)
    r = request["inventory"]["resources"][0]
    r["reservations"] = [
        dict(
            id="other",
            revision="1",
            owner_step_id="other-step",
            status="confirmed",
            unit="station",
            quantity=1,
            **dict(start_at="2026-11-09T22:00:00Z", end_at="2026-11-09T23:00:00Z"),
        )
    ]
    request["process"]["steps"][1]["resource_requirement"]["booking_required"] = True
    provider = FixtureProvider(tmp_path / (axis + ".db"))
    bridge.processes.resource_provider = provider
    await service.save(bridge.processes, owner, service.Save.model_validate(request))
    g = (await service.view(bridge.processes, owner, request["record_id"], "TYPED")).data[
        "generation"
    ]
    op = next(o for o in g["operations"] if o["kind"] == "reservation")
    k = op["expected_bases"][axis][0]["id"]
    with sqlite3.connect(provider.path) as db:
        db.execute("INSERT INTO bases VALUES(?,?,?,?)", (owner, axis, k, "later"))
    result = await effects.apply(
        bridge.processes,
        owner,
        effects.Apply(
            record_id=request["record_id"],
            work_revision=1,
            journal_revision=2,
            generation_id=g["generation_id"],
            operation_id=op["operation_id"],
            process_id="TYPED",
            idempotency_key="stale",
            confirmed=True,
        ),
    )
    assert result.data["status"] == "conflict"
    with sqlite3.connect(provider.path) as db:
        assert db.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
    capture(
        "stale-" + axis,
        dict(
            expected=op["expected_bases"], changed=k, outcome=result.data["status"], effect_count=0
        ),
    )


def test_aliases_unknown_capacity_and_observed_arrival():
    proc, inv, s = inputs("capacity")
    alias = "same-rack"
    rack = next(r for r in inv.resources if r.id == "RACK")
    inv = inv.model_copy(
        update=dict(
            resources=tuple(
                r if r != rack else r.model_copy(update=dict(aliases=(alias,)))
                for r in inv.resources
            )
        )
    )
    x = s.candidates[0]
    choices = list(x.placements)
    choices[1] = choices[1].model_copy(update=dict(resource_id=alias))
    s = s.model_copy(
        update=dict(candidates=(x.model_copy(update=dict(placements=tuple(choices))),))
    )
    result = engine.plan(proc, inv, s, generate=False)
    assert result["status"] == "no_feasible_schedule_found"
    proc, inv, s = inputs("typed")
    r = inv.resources[0]
    inv = inv.model_copy(
        update=dict(
            resources=(
                r.model_copy(
                    update=dict(capacity=r.capacity.model_copy(update=dict(quantity=None)))
                ),
                *inv.resources[1:],
            )
        )
    )
    assert "capacity:FORM-A" in engine.plan(proc, inv, s, generate=False)["hard_unknowns"]
    proc, inv, s = inputs("supply")
    supply = proc.supplies[0]
    projected = Lead(
        minimum_minutes=240,
        maximum_minutes=360,
        clock="elapsed_minutes",
        source_ref="supply-projection",
        anchor=s.planning_boundary,
        deadline=s.deadline_at,
    )
    proc = proc.model_copy(update=dict(supplies=(supply.model_copy(update=dict(lead=projected)),)))
    result = engine.plan(proc, inv, s, generate=False)
    assert (
        result["status"] == "feasible"
        and result["lead_time_results"][0]["observed_ready_at"]
        == supply.model_dump(mode="json")["ready_at"]
    )


async def test_resource_recurrence_with_phase_c(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.domain import DomainError
    from canvas_bridge.processes import (
        change_service as cs,
    )
    from canvas_bridge.processes import (
        effort_service as es,
    )
    from canvas_bridge.processes import (
        readiness as rd,
    )
    from canvas_bridge.processes import (
        resource_service as service,
    )
    from tests.test_phase_c_reconciliation import authored_rows, target_packet
    from tests.test_phase_c_reconciliation import fixture as case

    request = await seed(bridge, owner)
    rid = request["record_id"]
    await service.save(bridge.processes, owner, service.Save.model_validate(request))
    g = (await service.view(bridge.processes, owner, rid, "TYPED")).data["generation"]
    scenario = case("scenarios")["scenarios"][13]
    target = await target_packet(bridge, owner, scenario)
    observed = (
        await cs.observe(
            bridge.processes,
            owner,
            cs.Observation(
                record_id=rid, expected_revision=1, target=target, idempotency_key="changed"
            ),
        )
    ).data
    applied = (
        await cs.apply_change(
            bridge.processes,
            owner,
            cs.Reassessment(
                record_id=rid,
                expected_revision=observed["revision"],
                change_id=observed["change_id"],
                idempotency_key="reconcile",
                assessments=authored_rows(scenario, target),
                inventory_complete=True,
                material_changes=["PA-R02"],
            ),
        )
    ).data
    current = (await service.view(bridge.processes, owner, rid, "TYPED")).data
    assert not current["current_work_basis"]
    with pytest.raises(DomainError):
        await service.save(
            bridge.processes,
            owner,
            service.Save.model_validate(
                request
                | dict(
                    work_revision=applied["revision"],
                    journal_revision=2,
                    expected_generation=g["generation_id"],
                    idempotency_key="stale-issue",
                )
            ),
        )
    work = rd.view(bridge.processes, owner, rid).data["remaining_work"][0]
    forecast = (
        await es.issue(
            bridge.processes,
            owner,
            es.ForecastRequest(
                record_id=rid,
                work_revision=applied["revision"],
                journal_revision=2,
                idempotency_key="reopened-forecast",
                work_id=work["work_id"],
                scope_id="prototype",
                task_family="studio",
                scope_kind="remaining_episode",
                baseline=dict(low=65, high=65),
            ),
        )
    ).data["forecast"]
    new = deepcopy(request)
    new.update(
        work_revision=applied["revision"],
        journal_revision=3,
        expected_generation=g["generation_id"],
        idempotency_key="new-episode",
        forecast_id=forecast["forecast_id"],
    )
    new["process"]["revision"] = "2"
    new["process"]["active_demand_mapping"]["parent_forecast_ref"] = forecast["forecast_id"]
    for s in new["process"]["steps"]:
        s.update(
            episode_id=forecast["episode_id"],
            work_lineage_id=forecast.get("lineage_id") or forecast["work_id"],
        )
    await service.save(bridge.processes, owner, service.Save.model_validate(new))
    result = (await service.view(bridge.processes, owner, rid, "TYPED")).data["generation"]
    assert (
        result["result"]["active_minutes"] == 65
        and result["work_episode_id"] != g["work_episode_id"]
    )
    assert not {b["id"] for b in result["result"]["blocks"]} & {
        b["id"] for b in g["result"]["blocks"]
    }
    capture(
        "reopened-work",
        dict(
            prior=g["generation_id"],
            before_episode=g["work_episode_id"],
            after_episode=result["work_episode_id"],
            repair=result["result"],
        ),
    )


def test_reservation_residual_load_and_exclusive_expiry():
    proc, inv, schedule = inputs("booking")
    first = proc.steps[0]
    second = first.model_copy(
        update=dict(
            id="other",
            mode="unattended",
            resource_requirement=first.resource_requirement.model_copy(
                update=dict(booking_required=False)
            ),
        )
    )
    proc = proc.model_copy(update=dict(steps=(first, second)))
    from decimal import Decimal

    r = inv.resources[0]
    r = r.model_copy(
        update=dict(
            capacity=r.capacity.model_copy(update=dict(quantity=Decimal(2))),
            reservations=(r.reservations[0].model_copy(update=dict(quantity=Decimal(2))),),
        )
    )
    inv = inv.model_copy(update=dict(resources=(r, *inv.resources[1:])))
    c = schedule.candidates[0]
    c = c.model_copy(
        update=dict(
            placements=(
                *c.placements,
                c.placements[0].model_copy(
                    update=dict(placement_id="other", step_id="other", booking_id=None)
                ),
            )
        )
    )
    result = engine.plan(
        proc, inv, schedule.model_copy(update=dict(candidates=(c,))), generate=False
    )
    assert "resource_capacity" in result["rejected_candidates"][c.id]
    proc, inv, schedule = inputs("max-lag")
    proc = proc.model_copy(
        update=dict(
            dependencies=tuple(
                e.model_copy(update=dict(maximum_inclusive=False)) for e in proc.dependencies
            )
        )
    )
    result = engine.plan(proc, inv, schedule, generate=False)
    assert "maximum_lag" in result["rejected_candidates"]["inclusive-boundary"]


def test_split_and_priority_capacity_controls():
    p, i, s = inputs("stable")
    old = s.candidates[-1].placements[0]
    from datetime import timedelta

    candidate = Candidate(
        id="split",
        placements=[
            old.model_copy(update=dict(placement_id="first", run_minutes=30)),
            old.model_copy(
                update=dict(
                    placement_id="second",
                    run_minutes=30,
                    start_at=old.start_at + timedelta(minutes=30),
                )
            ),
        ],
    )
    s = s.model_copy(update=dict(candidates=(candidate,), base_blocks=()))
    assert (
        "indivisible_split" in engine.plan(p, i, s, generate=False)["rejected_candidates"]["split"]
    )
    divisible = p.model_copy(
        update=dict(steps=(p.steps[0].model_copy(update=dict(divisible=True)),))
    )
    assert engine.plan(divisible, i, s, generate=False)["active_minutes"] == 60
    p, i, s = inputs("capacity-proof")
    result = engine.plan(p, i, s)
    assert result["status"] == "infeasible" and result["partial_service"]["unmet_step_ids"]
    assert sum(result["partial_service"]["prioritized_unmet_vector"]) == 60
    capture("priority-shortfall", result["partial_service"])


def test_versioned_capacity_and_consumable_shortfall():
    from decimal import Decimal

    from canvas_bridge.processes.resource_models import CapacityInterval

    proc, inv, s = inputs("capacity-proof")
    resource = inv.resources[0]
    cap = CapacityInterval(
        start_at=s.planning_boundary,
        end_at=s.deadline_at,
        quantity=Decimal(2),
        revision="2",
        source_ref="second-station",
    )
    inv = inv.model_copy(
        update=dict(
            resources=(
                resource.model_copy(update=dict(capacity_intervals=(cap,))),
                *inv.resources[1:],
            )
        )
    )
    assert engine.plan(proc, inv, s, generate=False)["capacity_certificate"] is None
    proc, inv, s = inputs("supply")
    proc = proc.model_copy(
        update=dict(
            supplies=(
                proc.supplies[0].model_copy(
                    update=dict(
                        required_quantity=Decimal(2), available_quantity=Decimal(1), unit="sample"
                    )
                ),
            )
        )
    )
    assert (
        "supply_quantity_shortfall"
        in engine.plan(proc, inv, s, generate=False)["rejected_candidates"]["after-supply"]
    )
    proc, inv, s = inputs("typed")
    proc = proc.model_copy(
        update=dict(
            steps=(
                proc.steps[0],
                proc.steps[1].model_copy(update=dict(turnaround_minutes=5)),
                proc.steps[2],
            )
        )
    )
    result = engine.plan(proc, inv, s)
    assert result["active_minutes"] == 65 and result["passive_elapsed_minutes"] == 125
    assert result["resource_usage"][0]["quantity_minutes"] == 140
