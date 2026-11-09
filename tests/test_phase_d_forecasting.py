"""Executed Phase D product kernels with the frozen independent synthetic expectations."""

import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.analytics.effort_history import HistoryScope, Interval
from canvas_bridge.analytics.personal_forecast import Target, forecast
from canvas_bridge.processes.plan_repair import Block, Constraints, Task, repair
from tests.test_independent_intelligence import independent_recipient as independent_recipient
from tests.test_recovery_independence import parsed_locally as parsed_locally

BUNDLE = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-d/specs.zip"


def fixture(name):
    with ZipFile(BUNDLE) as z:
        return json.loads(z.read("phase_d_forecasting/fixtures/" + name + ".json"))


def capture(name, data):
    if output := os.environ.get("BRIDGE_PHASE_D_SCENARIOS"):
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps(data, indent=2), "utf8")


def history(row):
    return HistoryScope.model_validate(
        {k: v for k, v in row.items() if k in HistoryScope.model_fields}
    )


@pytest.mark.parametrize("index", range(16), ids=lambda i: f"PHD-S{i + 1:02}")
def test_phase_d_scenario(index):
    scenario = fixture("scenarios")["scenarios"][index]
    expected = fixture("expected")["results"][index]["expected"]
    generated = None
    if index < 8:
        current = scenario["current"]
        target = Target.model_validate(
            {k: v for k, v in current.items() if k in Target.model_fields}
        )
        histories = [
            history(h)
            for h in fixture("history")["histories"]
            if h["history_id"] in scenario["history_ids"]
        ]
        actual = forecast(histories, target)
        for k in (
            "factor",
            "ratio_median",
            "raw",
            "published",
            "planning_budget_minutes",
            "training_count",
            "training_history_ids",
            "matched_pair_count",
            "actual_minutes",
            "support",
            "override_state",
        ):
            assert actual[k] == expected[k], k
        assert sorted(actual["excluded"], key=lambda r: r["history_id"]) == sorted(
            expected.get("excluded", []), key=lambda r: r["history_id"]
        )
    else:
        s = fixture("schedules")["schedules"][index - 8]
        policy = Constraints(
            **{
                k: v
                for k, v in s.items()
                if k in Constraints.model_fields and k not in {"availability", "busy"}
            },
            availability=[Interval(start=r["start"], end=r["end"]) for r in s["availability"]],
            busy=[Interval(start=r["start"], end=r["end"]) for r in s["busy"]],
        )
        tasks = [
            Task.model_validate({k: v for k, v in t.items() if k in Task.model_fields})
            for t in s["tasks"]
        ]
        base = [Block.model_validate(b) for b in s["existing_blocks"]]
        candidates = [
            (c["candidate_id"], [Block.model_validate(b) for b in c["blocks"]])
            for c in s["candidates"]
        ]
        actual = repair(
            s["plan_id"], tasks, base, policy, alternatives=candidates, generate_candidates=False
        )
        for k in (
            "status",
            "free_minutes",
            "required_minutes",
            "unscheduled_minutes",
            "selected_candidate_id",
        ):
            assert actual[k] == expected[k], k
        for k, v in expected["selection"].items():
            assert actual["selection"][k] == v, k
        generated = repair(s["plan_id"], tasks, base, policy)
        assert generated["status"] == expected["status"]
        assert generated["selection"]["unmet_minutes"] == expected["selection"]["unmet_minutes"]

    capture(scenario["id"], dict(id=scenario["id"], actual=actual, generated=generated))


@pytest.mark.asyncio
async def test_signed_journal_and_calendar_recovery(
    bridge, settings, owner, token_factory, parsed_locally, tmp_path
):
    from datetime import UTC, datetime, timedelta

    from tests.test_mcp_contract import running
    from tests.test_phase_b_readiness import authored_review, client_session, import_case

    settings.process_features_enabled = True
    packet = await import_case(bridge, owner, "baseline")
    review = authored_review(packet, "BASELINE").model_dump(mode="json")
    async for url in running.__wrapped__(bridge, settings, None):
        async with client_session(url, token_factory(), read_timeout=120) as client:
            if os.environ.get("BRIDGE_PHASE_D_SCENARIOS"):
                from canvas_bridge.processes.surfaces import TOOLS

                catalog = await client.list_tools()
                capture(
                    "tools",
                    [
                        t.model_dump(mode="json", exclude_none=True)
                        for t in catalog.tools
                        if t.name in TOOLS
                    ],
                )
            transcript = []

            async def call(name, *, transcript=transcript, **args):
                r = (await client.call_tool(name, args)).structuredContent
                assert r and r["status"] == "ok", (name, r and r["summary"], r and r["data"])
                transcript.append(dict(tool=name, arguments=args, data=r["data"]))
                return r["data"]

            key = (await call("save_assignment_readiness", review=review))["record_id"]
            work = (await call("get_assignment_readiness", record_id=key))["remaining_work"]
            common = dict(record_id=key, work_revision=1)
            now = datetime.now(UTC)

            def at(hrs, now=now):
                return (now + timedelta(hours=hrs)).isoformat()

            log = dict(
                **common,
                work_id=work[0]["work_id"],
                scope_id="technical",
                observation_id="session",
                expected_observation_revision=0,
                scope_start=at(-2),
                through=at(-1),
                minutes=45,
                completed=True,
                complete_coverage=True,
                journal_revision=0,
                idempotency_key="log45",
            )
            assert (await call("record_scoped_effort", request=log))["revision"] == 1
            assert (await call("record_scoped_effort", request=log))["revision"] == 1
            await call(
                "record_scoped_effort",
                request=log
                | dict(
                    minutes=35,
                    journal_revision=1,
                    expected_observation_revision=1,
                    idempotency_key="correct35",
                ),
            )
            req = dict(
                **common,
                work_id=work[1]["work_id"],
                scope_id="current",
                task_family="presentation",
                scope_kind="remaining_episode",
                baseline=dict(low=40, point=50, high=60),
                journal_revision=2,
                idempotency_key="issue",
            )
            f = (await call("forecast_remaining_work", request=req))["forecast"]
            assert f["planning_budget_minutes"] == 60 and f["training_count"] == 0
            policy = dict(
                as_of=at(0),
                availability_coverage="complete",
                availability=[dict(start=at(1), end=at(4))],
            )
            await call(
                "save_study_replan",
                request=dict(
                    **common,
                    demands=[dict(forecast_id=f["forecast_id"])],
                    constraints=policy,
                    journal_revision=3,
                    idempotency_key="accept",
                ),
            )

            async def read(key=key):
                return await call("get_study_forecast_plan", record_id=key)

            journal = await read()
            assert [m["minutes"] for m in journal["measurements"]] == [45, 35]
            plan = journal["plan"]
            op = plan["operations"][0]
            assert op["action"] == "create"
            ctx = dict(
                calendar_id="synthetic-calendar",
                timezone="UTC",
                window_start=at(0),
                window_end=at(5),
                pagination_complete=True,
                mapping_search_complete=True,
                availability_complete=True,
                events=[],
            )

            def checked(
                rev, key, events, dispatch=False, *, common=common, plan=plan, op=op, ctx=ctx
            ):
                return dict(
                    **common,
                    generation_id=plan["generation_id"],
                    journal_revision=rev,
                    idempotency_key=key,
                    operation_id=op["operation_id"] if dispatch else None,
                    calendar=ctx | dict(events=events, retrieved_at=datetime.now(UTC).isoformat()),
                )

            await call("check_study_calendar", request=checked(4, "preflight", [], True))
            op = (await read())["plan"]["operations"][0]
            assert op["status"] == "issued"
            event = dict(
                id="host-event",
                title="Study",
                version="r1",
                start=op["after"]["start"],
                end=op["after"]["end"],
                bridge_marker=op["marker"],
                status="confirmed",
            )
            await call("check_study_calendar", request=checked(5, "uncertain", []))
            assert (await read())["plan"]["operations"][0]["attempts"] == 1
            await call("check_study_calendar", request=checked(6, "found", [event]))
            assert (await read())["plan"]["operations"][0]["status"] == "observed"
            await call(
                "compensate_study_replan",
                request=dict(
                    **common,
                    generation_id=plan["generation_id"],
                    journal_revision=7,
                    idempotency_key="undo",
                ),
            )
            inverse = (await read())["plan"]
            assert inverse["operations"][0]["action"] == "remove"
            later = checked(
                8, "protect-later", [event | dict(title="My later edit", version="r2")], True
            )
            later.update(
                generation_id=inverse["generation_id"],
                operation_id=inverse["operations"][0]["operation_id"],
            )
            await call("check_study_calendar", request=later)
            assert (await read())["plan"]["operations"][0]["status"] == "conflict"

            bad = log | dict(
                idempotency_key="stale-log", journal_revision=8, expected_observation_revision=2
            )
            denied = (
                await client.call_tool("record_scoped_effort", dict(request=bad))
            ).structuredContent
            assert denied["data"]["reason_code"] == "PROCESS_REVISION_MISMATCH"
            assert (await read())["journal_revision"] == 9
            from canvas_bridge.storage import IndependentResource

            with bridge.store.transaction() as db:
                item = db.get(IndependentResource, packet[1]["document_id"])
                item.provenance = item.provenance | dict(share_text=False)
            denied = (
                await client.call_tool("get_study_forecast_plan", dict(record_id=key))
            ).structuredContent
            assert denied["status"] != "ok" and "measurements" not in denied["data"]
            capture(
                "signed-journal",
                transcript
                + [dict(tool="get_study_forecast_plan", after_revocation=denied["status"])],
            )


@pytest.mark.skipif(
    not os.environ.get("BRIDGE_PHASE_D_HOST"), reason="Opt-in native synthetic host"
)
async def test_native_restarted_journey(settings, owner, token_factory, tmp_path, parsed_locally):
    import contextlib
    import os
    from datetime import UTC, datetime, timedelta

    from canvas_bridge.processes import effort_service as effort
    from canvas_bridge.processes import readiness, study_plan
    from tests.conftest import bridge as bridge_fixture
    from tests.test_phase_b_readiness import (
        authored_review,
        client_session,
        import_case,
        review_host,
        running,
    )

    settings.database_url = "sqlite:///" + str(tmp_path / "study.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    import asyncio

    output = await asyncio.to_thread(Path(os.environ["BRIDGE_PHASE_D_HOST"]).resolve)
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    empty = tmp_path / "host"
    empty.mkdir()
    tools = [
        "get_assignment_readiness",
        "record_scoped_effort",
        "get_study_forecast_plan",
        "forecast_remaining_work",
        "save_study_replan",
        "check_study_calendar",
        "compensate_study_replan",
    ]
    now = datetime.now(UTC)
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        packet = await import_case(bridge, owner, "baseline")
        from canvas_bridge.storage import IndependentResource

        with bridge.store.transaction() as session:
            for b in packet:
                session.get(IndependentResource, b["document_id"]).created_at = now - timedelta(
                    days=1
                )
        receipt = readiness.save(bridge.processes, owner, authored_review(packet, "BASELINE")).data
        rid = receipt["record_id"]
        rec = readiness.snapshot(bridge.processes.repository, owner, rid)
        works = list(effort.eligible(rec))
        repo = bridge.processes.repository
        clock = repo.clock
        repo.clock = lambda: now - timedelta(hours=3)
        start = (now - timedelta(hours=2)).isoformat()
        try:
            seed = effort.ForecastRequest(
                record_id=rid,
                work_revision=1,
                work_id=works[0],
                scope_id="technical",
                task_family="presentation",
                scope_kind="remaining_episode",
                scope_start=start,
                baseline=dict(low=30, point=40, high=50),
                journal_revision=0,
                idempotency_key="first-estimate",
            )
            from tests.test_mcp_contract import running as inprocess

            async for url in inprocess.__wrapped__(bridge, settings, None):
                async with client_session(url, token_factory()) as session:
                    seeded = (
                        await session.call_tool(
                            "forecast_remaining_work", dict(request=seed.model_dump(mode="json"))
                        )
                    ).structuredContent
                    assert seeded["status"] == "ok", seeded["summary"]
        finally:
            repo.clock = clock
        context = dict(
            record_id=rid,
            work_revision=1,
            technical_section=dict(
                work_id=works[0],
                scope_id="technical",
                scope_start=start,
                through=(now - timedelta(hours=1)).isoformat(),
            ),
            remaining_presentation=dict(
                work_id=works[1],
                scope_id="slides",
                scope_kind="remaining_episode",
                task_family="presentation",
                baseline=dict(low=40, point=50, high=60),
            ),
            available_window=dict(
                start=(now + timedelta(hours=2)).isoformat(),
                end=(now + timedelta(hours=5)).isoformat(),
            ),
            timezone="UTC",
            availability_coverage="complete",
        )
        # Use isolated host sessions across actual service restarts.
        schemas = {
            m.__name__: m.model_json_schema()
            for m in (
                effort.ForecastRequest,
                effort.WorkLog,
                study_plan.SavePlan,
                study_plan.CalendarCheck,
            )
        }
        with ZipFile(BUNDLE) as z:
            prompts = {
                p.split("/")[-1]: z.read(p).decode()
                for p in z.namelist()
                if "/prompts/" in p and p.endswith(".md")
            }
        for i, phrase in enumerate(
            (
                "Record scoped",
                "Forecast current",
                "Repair the accepted",
                "Check an interrupted",
                "Restore a previous",
            )
        ):
            prompt = next(p for p in prompts.values() if phrase in p)
            if i >= 3:
                prompt = next(
                    section for section in prompt.split("# ") if section.startswith(phrase)
                )
            async with running(settings) as pid:
                if i >= 3:
                    async with client_session(settings.resource_url, token_factory()) as setup:

                        async def wire(name, **arguments):
                            r = (await setup.call_tool(name, arguments)).structuredContent
                            assert r["status"] == "ok", r["summary"]
                            return r["data"]

                        journal = await wire("get_study_forecast_plan", record_id=rid)
                        plan = journal["plan"]
                        op = plan["operations"][0]
                        c = dict(
                            calendar_id="bench-calendar",
                            timezone="UTC",
                            window_start=now.isoformat(),
                            window_end=(now + timedelta(days=1)).isoformat(),
                            availability_complete=True,
                            mapping_search_complete=True,
                            pagination_complete=True,
                            retrieved_at=datetime.now(UTC).isoformat(),
                            events=[],
                        )
                        if i == 3:
                            await wire(
                                "check_study_calendar",
                                request=dict(
                                    record_id=rid,
                                    work_revision=1,
                                    journal_revision=journal["journal_revision"],
                                    idempotency_key="host-apply",
                                    generation_id=plan["generation_id"],
                                    operation_id=op["operation_id"],
                                    calendar=c,
                                ),
                            )
                        c["retrieved_at"] = datetime.now(UTC).isoformat()
                        c["events"] = [
                            dict(
                                id="syn-study-1",
                                title="Study" if i == 3 else "Later manual edit",
                                start=op["after"]["start"],
                                end=op["after"]["end"],
                                bridge_marker=op["marker"],
                                version="r1" if i == 3 else "r2",
                                status="confirmed",
                            )
                        ]
                        context["complete_synthetic_calendar_readback"] = c
                answer = await review_host(
                    settings.resource_url,
                    token_factory(),
                    prompt
                    + "\nSelected synthetic assignment and personal constraints: "
                    + json.dumps(context),
                    empty,
                    output,
                    f"turn-{i + 1}",
                    tools=tools,
                    instructions="Use only the coursework MCP tools, without files, shell, external services or other tools. Read the saved journal before changes and after any save. Treat the supplied current readiness version as already reconciled. Use exact measured scope boundaries. For replans, use current forecast IDs and omit accepted_blocks when a generation is already saved. Use the supplied synthetic calendar readback only when present. It is the host calendar snapshot for check_study_calendar. Never invent provider observations. For a new forecast omit scope_start to use the server clock. Apply an explicit override via user_override and leave its point null if only endpoints were given. Where applicable report the retrieved forecast version, cutoff, work episode, policy, support, effective budget and calendar status. Backend request schemas: "
                    + json.dumps(schemas),
                )
                assert answer
                async with client_session(settings.resource_url, token_factory()) as session:
                    result = (
                        await session.call_tool("get_study_forecast_plan", dict(record_id=rid))
                    ).structuredContent
                    assert result["status"] == "ok"
                    data = result["data"]
                    (output / f"turn-{i + 1}-readback.json").write_text(
                        json.dumps(dict(pid=pid, data=data), indent=2), "utf8"
                    )
                    if i == 0:
                        assert [m["minutes"] for m in data["measurements"]] == [45, 35]
                    if i == 1:
                        assert data["forecasts"][-1]["training_count"] == 1
                        assert (
                            data["forecasts"][-1]["planning_budget_minutes"] == 60
                            and data["forecasts"][-1]["override_state"] == "applied"
                        )
                    if i == 2:
                        assert data["plan"]["forecast_ids"] == [
                            data["forecasts"][-1]["forecast_id"]
                        ]
                        assert data["plan"]["selected_blocks"]
                    if i == 3:
                        assert data["plan"]["operations"][0]["status"] == "observed"
                    if i == 4:
                        assert (
                            data["plan"].get("compensates")
                            and data["measurements"][-1]["minutes"] == 35
                        )


def test_future_holdout_scores_original_and_corrected_baseline_separately():
    from datetime import datetime

    from canvas_bridge.analytics.personal_forecast import evaluate_frozen

    s = fixture("scenarios")["scenarios"][6]
    target = Target.model_validate(
        {k: v for k, v in s["current"].items() if k in Target.model_fields}
    )
    rows = [
        history(h) for h in fixture("history")["histories"] if h["history_id"] in s["history_ids"]
    ]
    issue = forecast(rows, target)
    end = s["holdout"]["completion_at"]
    learned = s["holdout"]["known_at"]
    scope = HistoryScope(
        history_id="holdout",
        user_id=target.user_id,
        scope_id=target.scope_id,
        episode_id=target.episode_id,
        scope_kind=target.scope_kind,
        task_family=target.task_family,
        baseline_policy=target.baseline_policy,
        scope_start_at=target.cutoff,
        scope_end_at=end,
        coverage=dict(state="complete", known_at=learned, basis="measured"),
        completion=dict(complete=True, completed_at=end, known_at=learned, basis="student"),
        forecasts=[
            dict(
                forecast_id=target.forecast_id,
                scope_id=target.scope_id,
                frozen_at=target.cutoff,
                known_at=target.cutoff,
                baseline=issue["baseline"],
                published=issue["published"],
                budget=issue["planning_budget_minutes"],
                baseline_policy=target.baseline_policy,
                baseline_origin=target.baseline_origin,
            )
        ],
        observations=[
            dict(
                observation_id="holdout-actual",
                scope_id=target.scope_id,
                revision=1,
                known_at=learned,
                minutes=s["holdout"]["actual_minutes"],
                kind="duration_total",
                basis="measured",
            )
        ],
    )
    assert not evaluate_frozen(scope, target.cutoff)
    evaluated = evaluate_frozen(scope, datetime.fromisoformat(s["holdout"]["evaluation_cutoff"]))[0]
    assert evaluated["published"]["absolute_point_error_minutes"] == 17
    assert evaluated["baseline"]["absolute_point_error_minutes"] == 20
    assert evaluated["published"]["inside_range"] is False
    assert forecast(rows + [scope], target)["training_snapshot_id"] == issue["training_snapshot_id"]


def test_s16_provider_double_lost_response_readback(tmp_path):
    import sqlite3
    from datetime import datetime, timedelta

    from canvas_bridge.calendar_sync import CalendarContext, CalendarEvent
    from canvas_bridge.processes.study_plan import ops, reconcile_one

    scenario = fixture("schedules")["schedules"][-1]
    now = datetime.fromisoformat(scenario["as_of"])
    base = scenario["existing_blocks"]
    desired = scenario["candidates"][0]["blocks"]
    operations = ops("synthetic", scenario["plan_id"], base, desired)
    assert [o["action"] for o in operations] == ["update", "create"]
    db = tmp_path / "provider.db"

    def store(event, update):
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            if update:
                assert (
                    conn.execute(
                        "UPDATE events SET payload=? WHERE id=? AND payload=?",
                        (event.model_dump_json(), event.id, update.model_dump_json()),
                    ).rowcount
                    == 1
                )
            else:
                conn.execute("INSERT INTO events VALUES(?,?)", (event.id, event.model_dump_json()))

    def snapshot():
        with sqlite3.connect(db) as conn:
            events = [
                CalendarEvent.model_validate_json(r[0])
                for r in conn.execute("SELECT payload FROM events")
            ]
        return CalendarContext(
            calendar_id="fixture",
            timezone="America/New_York",
            retrieved_at=now,
            window_start=now,
            window_end=now + timedelta(days=1),
            events=events,
            pagination_complete=True,
            mapping_search_complete=True,
            availability_complete=True,
        )

    def event(o, b, version):
        return CalendarEvent(
            id=b["provider_event_id"],
            title=b.get("manual_title") or "Study",
            start=b["start"],
            end=b["end"],
            version=version,
            bridge_marker=o["marker"],
            status="confirmed",
        )

    store(event(operations[0], base[0], "r1"), None)
    store(event({"marker": "other-retained"}, base[1], "r1"), None)

    def provider_apply(op, lost):
        original = next((e for e in snapshot().events if e.bridge_marker == op["marker"]), None)
        assert (original.model_dump(mode="json") if original else None) == op["expected_event"]
        store(event(op, op["after"], "r2" if original else "r1"), original)
        if lost:
            raise TimeoutError("Synthetic response lost after commit")

    for o in operations:
        reconcile_one(o, snapshot(), now, stale=False, dispatch=True)
        assert o["status"] == "issued"
        if o["action"] == "create":
            with pytest.raises(TimeoutError):
                provider_apply(o, True)
        else:
            provider_apply(o, False)
        now += timedelta(seconds=1)
        # Recover from serialized local intent and a reopened provider database.
        persisted = json.loads(json.dumps(o))
        reconcile_one(persisted, snapshot(), now, stale=False, dispatch=False)
        assert persisted["status"] == "observed" and persisted["attempts"] == 1
        o.update(persisted)
    capture(
        "provider-recovery",
        dict(
            operations=operations,
            events=[e.model_dump(mode="json") for e in snapshot().events],
            durable_effects=2,
            recovered_operations=2,
        ),
    )
    assert len(snapshot().events) == 3
    assert snapshot().events[1].title == base[1]["manual_title"]


def test_restore_keeps_later_user_state_and_localizes_conflicts():
    from canvas_bridge.processes.study_plan import restore_blocks

    a = dict(block_id="a", start="09:00", end="09:30", manual_note=None)
    b = dict(block_id="b", start="10:00", end="10:30", manual_note=None)
    later = dict(block_id="later", start="11:00", end="11:30")
    moved = dict(start="14:00", end="14:30")
    plan = dict(before=[a, b], selected_blocks=[a | moved, b | moved])
    current = [a | moved | dict(manual_note="my later note"), b | moved | dict(end="14:45"), later]
    restored, conflicts = restore_blocks(plan, current)
    assert restored == [a | dict(manual_note="my later note"), current[1], later]
    assert conflicts == ["b"]


@pytest.mark.parametrize(
    "wall", ["2026-11-01T01:30:00", "2027-03-14T02:30:00-05:00", "2026-11-09T09:00:00-04:00"]
)
def test_invalid_scheduling_wall_time(wall):
    with pytest.raises(ValueError):
        Constraints(timezone="America/New_York", availability=[], as_of=wall)


def test_remaining_session_boundary_refuses_unallocated_total():
    from datetime import datetime

    from canvas_bridge.analytics.personal_forecast import evaluate_frozen
    from canvas_bridge.processes.effort_service import histories

    def at(h):
        return f"2026-11-01T{h}:00:00+00:00"

    f = dict(
        forecast_id="f",
        scope_id="section",
        episode_id="e",
        scope_start=at("10"),
        scope_kind="remaining_episode",
        task_family="reading",
        baseline_policy="v",
        baseline_origin="student_estimate",
        baseline=dict(low=40, point=50, high=70),
        published=dict(low=40, point=50, high=70),
        planning_budget_minutes=70,
        cutoff=at("09"),
    )
    m = dict(
        observation_id="o",
        scope_id="section",
        episode_id="e",
        scope_start=at("09"),
        through=at("11"),
        known_at=at("12"),
        completed=True,
        complete_coverage=True,
        revision=1,
        retracted=False,
        owner_key="student",
        basis="timed",
        minutes=None,
        sessions=[dict(start=at("09"), end=at("11"))],
        pauses=[dict(start=at("10"), end="2026-11-01T10:10:00+00:00")],
    )
    cutoff = datetime.fromisoformat(at("13"))
    scope = histories(dict(forecasts=[f], measurements=[m]), cutoff)[0]
    assert evaluate_frozen(scope, cutoff)[0]["actual_minutes"] == 50
    assert (
        histories(
            dict(forecasts=[f], measurements=[m | dict(sessions=[], pauses=[], minutes=110)]),
            cutoff,
        )
        == []
    )


def test_twenty_distinct_units_and_zero_observation():
    from datetime import timedelta

    row = history(fixture("history")["histories"][0])
    t = Target.model_validate(
        {
            k: v
            for k, v in fixture("scenarios")["scenarios"][0]["current"].items()
            if k in Target.model_fields
        }
    )
    rows = []
    for i in range(21):
        completion = row.completion.model_copy(
            update=dict(completed_at=row.completion.completed_at + timedelta(seconds=i))
        )
        rows.append(
            row.model_copy(
                update=dict(
                    history_id=str(i),
                    episode_id=str(i),
                    completion=completion,
                    observations=(row.observations[0].model_copy(update=dict(minutes=0)),),
                )
            )
        )
    result = forecast(rows, t)
    assert (
        result["training_count"] == 20
        and result["factor"] == "3/23"
        and "0" not in result["training_history_ids"]
    )


async def test_reconciled_work_forecast_keeps_old_measurement(
    bridge, owner, parsed_locally, independent_recipient
):
    from datetime import timedelta

    from canvas_bridge.processes import change_service as cs
    from canvas_bridge.processes import effort_service as es
    from canvas_bridge.processes import readiness as rd
    from canvas_bridge.processes import study_plan
    from tests.test_phase_b_readiness import authored_review, import_case
    from tests.test_phase_c_reconciliation import authored_rows, target_packet
    from tests.test_phase_c_reconciliation import fixture as cf

    bridge.settings.process_features_enabled = True
    service = bridge.processes
    packet = await import_case(bridge, owner, "baseline")
    rid = rd.save(service, owner, authored_review(packet, "BASELINE")).data["record_id"]
    prior = next(
        w
        for w in rd.view(service, owner, rid).data["remaining_work"]
        if w["requirement_id"] == "PA-R02"
    )
    now = service.repository.clock()
    base = dict(
        record_id=rid,
        work_revision=1,
        idempotency_key="old-log",
        journal_revision=0,
        work_id=prior["work_id"],
        scope_id="slides",
    )
    await es.log_work(
        service,
        owner,
        es.WorkLog(
            **base,
            expected_observation_revision=0,
            observation_id="old-actual",
            scope_start=now - timedelta(hours=1),
            through=now,
            minutes=30,
            complete_coverage=True,
            completed=True,
        ),
    )
    f = es.ForecastRequest(
        **(base | dict(journal_revision=1, idempotency_key="old-issue")),
        scope_kind="remaining_episode",
        task_family="presentation",
        baseline=dict(low=40, high=60, point=50),
    )
    old = (await es.issue(service, owner, f)).data["forecast"]
    assert old["planning_budget_minutes"] == 0
    scenario = cf("scenarios")["scenarios"][13]
    target = await target_packet(bridge, owner, scenario)
    staged = (
        await cs.observe(
            service,
            owner,
            cs.Observation(
                record_id=rid, expected_revision=1, target=target, idempotency_key="amend"
            ),
        )
    ).data
    applied = (
        await cs.apply_change(
            service,
            owner,
            cs.Reassessment(
                record_id=rid,
                expected_revision=staged["revision"],
                idempotency_key="apply-amend",
                change_id=staged["change_id"],
                inventory_complete=True,
                assessments=authored_rows(scenario, target),
                material_changes=["PA-R02"],
            ),
        )
    ).data
    current = rd.view(service, owner, rid).data["remaining_work"][0]
    result = (
        await es.issue(
            service,
            owner,
            f.model_copy(
                update=dict(
                    work_id=current["work_id"],
                    work_revision=applied["revision"],
                    journal_revision=2,
                    idempotency_key="reopen",
                )
            ),
        )
    ).data["forecast"]
    assert result["planning_budget_minutes"] == 60 and result["episode_id"] != old["episode_id"]
    state = (await study_plan.view(service, owner, rid)).data
    assert (
        state["measurements"][0]["episode_id"] == old["episode_id"]
        and result["current_observation_refs"] == []
    )
    capture(
        "reconciled-episode",
        dict(old=old, new=result, applied=applied, measurements=state["measurements"]),
    )


async def test_grounded_date_and_explicit_compaction(
    bridge, owner, parsed_locally, independent_recipient
):
    import hashlib
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from canvas_bridge.domain import DomainError
    from canvas_bridge.processes import effort_service as es
    from canvas_bridge.processes import readiness as rd
    from canvas_bridge.processes import study_plan as sp
    from tests.test_phase_b_readiness import authored_review, import_case

    bridge.settings.process_features_enabled = True
    service = bridge.processes
    now = datetime.now(UTC)
    day = (now + timedelta(days=4)).date()
    quote = f"The presentation is due on {day.isoformat()}."
    raw = quote.encode()
    packet = await import_case(bridge, owner, "baseline")
    document = await bridge.independent.ingest(
        owner,
        raw,
        "timing.txt",
        "text/plain",
        course="BenchLink",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
    )
    packet.append(
        dict(
            logical_id="timing",
            role="reference",
            document_id=document,
            content_hash=hashlib.sha256(raw).hexdigest(),
        )
    )
    rid = rd.save(service, owner, authored_review(packet, "BASELINE")).data["record_id"]
    work = rd.view(service, owner, rid).data["remaining_work"][0]
    common = dict(record_id=rid, work_revision=1)
    forecast = (
        await es.issue(
            service,
            owner,
            es.ForecastRequest(
                **common,
                work_id=work["work_id"],
                scope_id="current",
                task_family="slides",
                scope_kind="remaining_episode",
                baseline=dict(low=30, high=40),
                idempotency_key="f",
                journal_revision=0,
            ),
        )
    ).data["forecast"]
    start = now + timedelta(hours=2)
    block = Block(
        block_id="accepted",
        task_id=work["work_id"],
        episode_id=forecast["episode_id"],
        start=start,
        end=start + timedelta(minutes=60),
    )
    date = dict(
        local_date=day.isoformat(),
        course_timezone="America/New_York",
        evidence=dict(source="timing", part=1, surface="text", quote=quote),
    )
    request = sp.SavePlan(
        **common,
        journal_revision=1,
        idempotency_key="stable",
        demands=[dict(forecast_id=forecast["forecast_id"], source_date=date)],
        constraints=dict(
            as_of=now,
            availability_coverage="complete",
            availability=[dict(start=start, end=start + timedelta(hours=3))],
        ),
        accepted_blocks=[block],
    )
    await sp.save(service, owner, request)
    before = (await sp.view(service, owner, rid)).data["plan"]
    assert before["repair"]["retained_reserve_minutes"] == 20
    compact = request.model_copy(
        update=dict(
            journal_revision=2,
            idempotency_key="compact",
            constraints=request.constraints.model_copy(update=dict(compact_reservations=True)),
        )
    )
    await sp.save(service, owner, compact)
    after = (await sp.view(service, owner, rid)).data["plan"]
    assert after["repair"]["retained_reserve_minutes"] == 0
    assert after["selected_blocks"][0]["block_id"] == block.block_id
    assert datetime.fromisoformat(
        after["repair"]["work_allocations"][0]["deadline"]
    ) == datetime.combine(day, datetime.min.time(), ZoneInfo("America/New_York"))
    invalid = request.model_dump(mode="json") | dict(
        idempotency_key="invalid-date", journal_revision=3
    )
    invalid["demands"][0]["source_date"]["local_date"] = (day + timedelta(days=1)).isoformat()
    with pytest.raises(DomainError, match="Refresh") as exc:
        await sp.save(service, owner, sp.SavePlan.model_validate(invalid))
    assert exc.value.reason_code == "PLAN_DEADLINE_SOURCE_MISMATCH"
    capture(
        "source-date-and-compaction",
        dict(before=before, after=after, rejected=exc.value.reason_code),
    )


async def test_selected_canvas_deadline_replan(
    bridge, settings, owner, seeded, token_factory, parsed_locally
):
    """A signed host selects the live deadline, observes a conflict, then releases one future pin."""
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta

    from tests.test_mcp_contract import running
    from tests.test_phase_b_readiness import authored_review, client_session, import_case

    settings.process_features_enabled = True
    review = authored_review(await import_case(bridge, owner, "baseline"), "BASELINE")
    now = datetime.now(UTC).replace(microsecond=0)
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw.update(due_at=(now + timedelta(hours=6)).isoformat(), updated_at=now.isoformat())
    transcript = []
    async with (
        asynccontextmanager(running.__wrapped__)(bridge, settings, None) as url,
        client_session(url, token_factory(), read_timeout=120) as client,
    ):

        async def call(name, args, *, failure=None):
            r = (await client.call_tool(name, args)).structuredContent
            transcript.append(dict(tool=name, args=args, status=r["status"], data=r["data"]))
            if failure:
                assert r["data"].get("reason_code") == failure, r
            else:
                assert r["status"] in {"ok", "partial_data"}, (name, r)
            return r["data"]

        loaded = await call(
            "get_workload",
            dict(
                connection_id=seeded,
                start=now.isoformat(),
                end=(now + timedelta(days=2)).isoformat(),
                timezone="America/New_York",
            ),
        )
        selected = next(i["id"] for i in loaded["items"] if i["source_id"] == str(raw["id"]))
        selection = dict(connection_id=seeded, work_id=selected)
        first = (await call("get_assignment_details", selection))["item"]
        rid = (
            await call("save_assignment_readiness", dict(review=review.model_dump(mode="json")))
        )["record_id"]
        work = (await call("get_assignment_readiness", dict(record_id=rid)))["remaining_work"][0]
        common = dict(record_id=rid, work_revision=1)
        f = (
            await call(
                "forecast_remaining_work",
                dict(
                    request=common
                    | dict(
                        journal_revision=0,
                        idempotency_key="estimate",
                        work_id=work["work_id"],
                        scope_id="test",
                        task_family="presentation",
                        scope_kind="remaining_episode",
                        baseline=dict(low=30, high=30),
                    )
                ),
            )
        )["forecast"]

        def stamp(hours):
            return (now + timedelta(hours=hours)).isoformat()

        pinned = dict(
            block_id="review",
            task_id=work["work_id"],
            episode_id=f["episode_id"],
            start=stamp(4),
            end=stamp(4.5),
            locked=True,
        )
        req = common | dict(
            journal_revision=1,
            idempotency_key="original",
            accepted_blocks=[pinned],
            constraints=dict(
                as_of=stamp(0),
                timezone="America/New_York",
                availability_coverage="complete",
                availability=[dict(start=stamp(1), end=stamp(6))],
            ),
            demands=[
                dict(forecast_id=f["forecast_id"], deadline=first["effective_due"]["timestamp"])
            ],
        )
        await call("save_study_replan", dict(request=req))

        async def saved():
            return (await call("get_study_forecast_plan", dict(record_id=rid)))["plan"]

        old = await saved()
        assert old["selected_blocks"][0]["locked"]
        raw.update(due_at=stamp(3), updated_at=stamp(0.01))
        changed = (await call("get_assignment_details", selection))["item"]
        assert (
            first["id"] == changed["id"]
            and first["source"]["content_hash"] != changed["source"]["content_hash"]
        )
        assert changed["effective_due"]["timestamp"] != first["effective_due"]["timestamp"]
        req.update(
            journal_revision=2,
            idempotency_key="earlier",
            accepted_blocks=[],
            demands=[
                dict(forecast_id=f["forecast_id"], deadline=changed["effective_due"]["timestamp"])
            ],
        )
        await call("save_study_replan", dict(request=req), failure="PLAN_PROTECTED_CONFLICT")
        assert (await saved())["generation_id"] == old["generation_id"]
        for ids in (["other"], ["review", "review"]):
            await call(
                "save_study_replan",
                dict(request=req | dict(release_block_ids=ids)),
                failure="PLAN_PROTECTED_CONFLICT",
            )
        await call(
            "save_study_replan",
            dict(
                request=req
                | dict(
                    release_block_ids=["review"],
                    constraints=req["constraints"] | dict(as_of=stamp(4.1)),
                )
            ),
            failure="PLAN_PROTECTED_CONFLICT",
        )
        req.update(idempotency_key="release-future-pin", release_block_ids=["review"])
        receipt = await call("save_study_replan", dict(request=req))
        assert await call("save_study_replan", dict(request=req)) == receipt
        repaired = await saved()
        assert repaired["before"] == old["selected_blocks"]
        assert repaired["released_block_ids"] == ["review"]
        assert repaired["repair"]["unscheduled_minutes"] == 0
        assert max(
            datetime.fromisoformat(b["end"]) for b in repaired["selected_blocks"]
        ) <= now + timedelta(hours=3)
        assert all(not b["locked"] for b in repaired["selected_blocks"])
        capture("connected-deadline-repair", transcript)
        if folder := os.getenv("BRIDGE_PHASE_D_CONNECTED_HOST"):
            import asyncio

            from tests.test_phase_a_benchmark import review_host

            out = await asyncio.to_thread(Path(folder).resolve)
            out.mkdir(parents=True, exist_ok=True)
            empty = out / "empty"
            empty.mkdir(exist_ok=True)
            raw.update(due_at=stamp(2.75), updated_at=stamp(0.02))
            prompt = f"""For this synthetic exercise I select Canvas assignment {selected} on connection {seeded} as the deadline for saved study record {rid}, forecast {f["forecast_id"]}. Read the assignment details now. Apply its current effective timestamp to the local study plan with the existing availability and timezone, and retrieve the result. Report the source version, deadline, protected-block outcome and remaining minutes. Local study-plan updates only."""
            names = ["get_assignment_details", "get_study_forecast_plan", "save_study_replan"]
            answer = await review_host(
                url,
                token_factory(),
                prompt,
                empty,
                out,
                "deadline",
                tools=names,
                instructions="Use only the three supplied coursework MCP tools. Read current assignment details and the current journal, then use their returned effective_due timestamp, forecast ID, work_revision, journal_revision and constraints to save the plan. Use a new idempotency key. Retrieve the new generation. No other tools or external writes.",
            )
            assert answer
            native = await saved()
            assert native["generation_id"] != repaired["generation_id"]
            assert datetime.fromisoformat(
                native["demands"][0]["deadline"]
            ) == datetime.fromisoformat(raw["due_at"])
            events = [
                json.loads(line)
                for line in (out / "deadline-events.jsonl").read_text("utf8").splitlines()
            ]
            calls = [
                e["item"]["tool"].removeprefix("mcp__coursework__")
                for e in events
                if e.get("type") == "item.completed"
                and e.get("item", {}).get("type") == "mcp_tool_call"
            ]
            assert (
                calls.index("get_assignment_details")
                < calls.index("save_study_replan")
                < len(calls) - 1
            )
            assert calls[-1] == "get_study_forecast_plan"
            capture("connected-deadline-native-readback", native)


def test_releasing_local_pin_alone_requires_no_confirmed_calendar_update():
    from canvas_bridge.processes.study_plan import ops

    confirmed = dict(
        block_id="confirmed",
        locked=True,
        user_edited=True,
        start="2026-11-07T09:00:00Z",
        end="2026-11-07T10:00:00Z",
    )
    released = confirmed | dict(locked=False, user_edited=False)
    assert ops("owner", "generation", [confirmed], [released]) == []
    moved = released | dict(start="2026-11-07T08:00:00Z", end="2026-11-07T09:00:00Z")
    assert [op["action"] for op in ops("owner", "generation", [confirmed], [moved])] == ["update"]
