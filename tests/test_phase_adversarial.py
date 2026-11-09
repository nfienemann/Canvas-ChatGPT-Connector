"""Adversarial controls across the A-F benchmark and production boundaries."""

import base64
import hashlib
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from canvas_bridge.analytics.effort_history import Estimate
from canvas_bridge.analytics.personal_forecast import Override, Target, forecast
from canvas_bridge.domain import DomainError
from canvas_bridge.processes import (
    change_observation as changes,
)
from canvas_bridge.processes import (
    handoff_projection as handoffs,
)
from canvas_bridge.processes import (
    readiness as rd,
)
from canvas_bridge.processes import (
    resource_engine,
)
from scripts import audit_phase_a
from tests.test_independent_intelligence import independent_recipient as independent_recipient
from tests.test_phase_d_forecasting import fixture as d_fixture
from tests.test_phase_e_resources import inputs
from tests.test_recovery_independence import parsed_locally as parsed_locally


def test_a_empty_capture_cannot_certify_benchmark(tmp_path):
    def write(name, value):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf8")

    with ZipFile(audit_phase_a.BUNDLE) as archive:
        run = json.loads(archive.read("phase_a_baseline/run_matrix.json"))["runs"][0]
        write("capture.json", run)
        write("imports.json", [])
        for name in ("before.json", "after.json"):
            write(name, {"data": {"documents": []}})
        write("calls.json", [])
        write("review-status.json", {"elapsed_ms": 1})
        write(
            "review-events.jsonl",
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Finished"}},
        )
        (tmp_path / "review-answer.txt").write_text("Finished", encoding="utf8")
        (tmp_path / "review-prompt.txt").write_bytes(
            archive.read("phase_a_baseline/" + run["prompt_ref"])
        )
        with pytest.raises((AssertionError, ValueError)):
            audit_phase_a.audit(tmp_path, archive)


@pytest.mark.parametrize("quote", [" ", "\t\n", "\u00a0"])
def test_b_empty_normalized_quote_cannot_prove_evidence(quote):
    binding = rd.Binding(logical_id="brief", role="brief", document_id="doc", content_hash="a" * 64)
    with pytest.raises((ValueError, DomainError)):
        rd.check_anchor(
            rd.Anchor(source="brief", part=1, surface="text", quote=quote),
            {"brief": binding},
            {"doc": {"pages": [{"text": "No match."}]}},
        )


def test_c_markdown_heading_is_not_equivalent_to_horizontal_rule():
    records = {}

    def version(ident, text):
        raw = text.encode()
        digest = hashlib.sha256(raw).hexdigest()
        records[ident] = SimpleNamespace(
            version_hash=digest, content={"bytes": base64.b64encode(raw).decode(), "format": "md"}
        )
        return rd.Binding(
            logical_id="artifact", role="artifact", document_id=ident, content_hash=digest
        )

    left = version("old", "Results\n---\n")
    right = version("new", "Results\n\n---\n")
    service = SimpleNamespace(
        bridge=SimpleNamespace(independent=SimpleNamespace(require=lambda owner, i: records[i]))
    )
    result = changes.compare(service, "owner", left, right)
    assert result["change_class"] == "content_changed"
    assert result["changed_sections"] == [""]


def test_d_zero_remaining_estimate_is_not_scheduled():
    current = d_fixture("scenarios")["scenarios"][0]["current"]
    target = Target.model_validate({k: v for k, v in current.items() if k in Target.model_fields})
    result = forecast([], target.model_copy(update=dict(baseline=Estimate(low=0, point=0, high=0))))
    assert result["planning_budget_minutes"] == 0
    override = Override(
        override_id="explicit",
        scope_id=target.scope_id,
        episode_id=target.episode_id,
        known_at=target.cutoff,
        values=Estimate(low=5, high=8),
        basis="reported",
    )
    target = target.model_copy(
        update=dict(baseline=Estimate(low=0, high=0), manual_override=override)
    )
    assert forecast([], target)["planning_budget_minutes"] == 8
    assert (
        forecast([], target.model_copy(update=dict(completed=True)))["planning_budget_minutes"] == 0
    )


def test_e_zero_run_still_requires_setup_and_cleanup():
    proc, inv, schedule = inputs("stable")
    step = proc.steps[0]
    step = step.model_copy(
        update=dict(
            run_duration=step.run_duration.model_copy(
                update=dict(minimum_minutes=0, maximum_minutes=0)
            ),
            setup_minutes=10,
            cleanup_minutes=5,
        )
    )
    proc = proc.model_copy(update=dict(steps=(step,)))
    empty = schedule.candidates[0].model_copy(update=dict(id="omit", placements=()))
    schedule = schedule.model_copy(update=dict(candidates=(empty,), base_blocks=()))
    result = resource_engine.plan(proc, inv, schedule, generate=False)
    assert result["status"] != "feasible"


def test_f_grade_letters_cannot_establish_member_assignment():
    role = dict(
        members=[dict(member_id="A", label="Member A"), dict(member_id="B", label="Member B")],
        responsible_actor="A",
        recipient_ids=["B"],
        identity_basis="source_assignment",
        evidence=dict(quote="A written report must earn a B or higher."),
    )
    assert not handoffs.identity_supported(role)


def test_a_notes_must_be_returned_on_the_notes_surface(tmp_path):
    from io import BytesIO

    def write(name, value):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf8")

    with ZipFile(audit_phase_a.BUNDLE) as bundle:
        run = json.loads(bundle.read("phase_a_baseline/run_matrix.json"))["runs"][0]
        case = next(
            c
            for c in json.loads(bundle.read("phase_a_baseline/fixtures/index.json"))["cases"]
            if c["case_id"] == run["case_id"]
        )
        rows = [
            dict(document_id=str(i), filename=f["path"].split("/")[-1], source=f)
            for i, f in enumerate(case["model_input_files"])
        ]
        deck = next(r for r in rows if r["filename"] == "deck.pptx")
        with ZipFile(
            BytesIO(bundle.read("phase_a_baseline/fixtures/" + deck["source"]["path"]))
        ) as ppt:
            combined = " ".join(
                audit_phase_a.native_lines(ppt, "ppt/slides/slide1.xml")
                + audit_phase_a.native_lines(ppt, "ppt/notesSlides/notesSlide1.xml")
            )
        write("imports.json", rows)
        write("before.json", dict(data=dict(documents=[])))
        write(
            "after.json",
            dict(
                data=dict(
                    documents=[
                        dict(document_id=r["document_id"], content_hash=r["source"]["sha256"])
                        for r in rows
                    ]
                )
            ),
        )
        write("capture.json", run)
        write("calls.json", [])
        write("review-status.json", dict(elapsed_ms=1))
        (tmp_path / "review-prompt.txt").write_bytes(
            bundle.read("phase_a_baseline/" + run["prompt_ref"])
        )
        (tmp_path / "review-answer.txt").write_text("Answer", encoding="utf8")
        part = dict(
            part=1,
            text=combined,
            text_spans=[dict(start=0, end=len(combined), source_kind="slide_shapes_and_tables")],
        )
        event = dict(
            type="item.completed",
            item=dict(
                type="mcp_tool_call",
                id="call",
                tool="read_local_document",
                server="coursework",
                arguments=dict(document_id=deck["document_id"]),
                result=dict(
                    content=[
                        dict(
                            text=json.dumps(
                                dict(
                                    status="ok",
                                    data=dict(parts=[part], content_hash=deck["source"]["sha256"]),
                                )
                            )
                        )
                    ]
                ),
            ),
        )
        (tmp_path / "review-events.jsonl").write_text(
            json.dumps(event)
            + "\n"
            + json.dumps(
                dict(type="item.completed", item=dict(type="agent_message", text="Answer"))
            ),
            encoding="utf8",
        )
        surfaces = audit_phase_a.audit(tmp_path, bundle)["source_surfaces"]
        slide = next(s for s in surfaces if s["name"] == "deck.pptx" and s["part"] == 1)
        assert slide["body"] and not slide["notes"]


def test_reordered_readiness_and_corrected_effort_populations():
    import random
    from datetime import UTC, datetime, timedelta

    from canvas_bridge.analytics.effort_history import Reading, selected_actual
    from canvas_bridge.processes.handoff_service import responses

    rng = random.Random(780514)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def at(minute):
        return start + timedelta(minutes=minute)

    for _ in range(180):
        criteria = []
        for _row in range(rng.randint(1, 40)):
            criteria.append(
                dict(
                    required=rng.choice([True, False]),
                    applicability=rng.choice(["applicable", "unknown", "not_applicable"]),
                    assessment_status=rng.choice(
                        ["satisfied", "unknown", "conflict", "needs_work"]
                    ),
                )
            )
        required = [c for c in criteria if c["required"]]
        active = {c["assessment_status"] for c in required if c["applicability"] == "applicable"}
        if any(c["applicability"] == "unknown" for c in required):
            active.add("unknown")
        complete = rng.choice([True, False])
        if not complete:
            active.add("unknown")
        expected = next((v for v in ["conflict", "needs_work", "unknown"] if v in active), "ready")
        rng.shuffle(criteria)
        assert rd.summarize(criteria, complete)["summary_status"] == expected

        readings = []
        minutes = set()
        for i in range(rng.randint(2, 36)):
            lo = rng.randrange(90)
            hi = rng.randint(lo + 1, 100)
            pause_start = rng.randrange(lo, hi)
            pause_end = rng.randint(pause_start + 1, hi)
            reading = Reading(
                observation_id=str(i),
                revision=1,
                scope_id="s",
                known_at=at(100),
                kind="active_interval",
                basis="test",
                start=at(lo),
                end=at(hi),
                pauses=[dict(start=at(pause_start), end=at(pause_end))],
            )
            readings.extend([reading, reading])
            retracted = rng.choice([True, False])
            readings.append(
                reading.model_copy(update=dict(revision=2, retracted=retracted, known_at=at(101)))
            )
            if not retracted:
                minutes.update(set(range(lo, hi)) - set(range(pause_start, pause_end)))
        rng.shuffle(readings)
        scope = SimpleNamespace(
            observations=readings, scope_id="s", scope_start_at=start, scope_end_at=at(100)
        )
        actual, refs, _, reason = selected_actual(scope, at(101))
        assert (
            (actual == len(minutes) and reason is None)
            if refs
            else (not minutes and actual is None)
        )

        ledger = []
        expected_members = {}
        cutoff = rng.randrange(4)
        for m in ("a", "b", "c"):
            for rev in range(1, 5):
                state = rng.choice(["received", "changes_requested", "accepted_for_next_step"])
                row = dict(
                    assignment_id="a",
                    handoff_id="h",
                    known_at=at(rev).isoformat(),
                    observation_id=m,
                    revision=rev,
                    retracted=rng.choice([True, False]),
                    actor_supported=True,
                    original_semantic_basis_id="basis",
                    acknowledged_by=m,
                    state=state,
                )
                ledger.extend([row, row])
                if rev <= cutoff:
                    expected_members[m] = "none" if row["retracted"] else state
        rng.shuffle(ledger)
        view = responses(
            dict(handoff_responses=ledger),
            dict(
                assignment_id="a",
                handoff_id="h",
                semantic_basis_id="basis",
                responsibility=dict(recipient_ids=["a", "b", "c"]),
            ),
            at(cutoff),
        )
        assert all(
            m["state"] == expected_members.get(m["member_id"], "none")
            for m in view["ack_by_member"]
        )


def test_e_seeded_capacity_sweep_matches_minute_oracle():
    import random
    from datetime import timedelta
    from decimal import Decimal

    from canvas_bridge.processes.resource_models import Candidate, CapacityInterval, Placement

    rng = random.Random(911274)
    proc, inventory, schedule = inputs("capacity")
    start = schedule.planning_boundary
    template = proc.steps[0]
    rack = next(r for r in inventory.resources if r.id == "RACK")
    for _ in range(160):
        jobs = []
        slots = []
        load = [0] * 90
        capacity = rng.randint(1, 8)
        reduced = rng.randint(0, capacity)
        cut = rng.randrange(1, 65)
        resume = rng.randrange(cut + 1, 85)
        for n in range(rng.randint(1, 12)):
            lo = rng.randrange(60)
            duration = rng.randrange(1, 30)
            units = rng.randrange(1, 5)
            jobs.append(
                template.model_copy(
                    update=dict(
                        id=str(n),
                        setup_minutes=0,
                        cleanup_minutes=0,
                        run_duration=template.run_duration.model_copy(
                            update=dict(minimum_minutes=duration, maximum_minutes=duration)
                        ),
                        resource_requirement=template.resource_requirement.model_copy(
                            update=dict(quantity=Decimal(units) / 4)
                        ),
                    )
                )
            )
            for t in range(lo, lo + duration):
                load[t] += units
            slots.append(
                Placement(
                    placement_id=str(n),
                    step_id=str(n),
                    episode_id=template.episode_id,
                    start_at=start + timedelta(minutes=lo),
                    resource_id=rack.id,
                )
            )
        r = rack.model_copy(
            update=dict(
                capacity=rack.capacity.model_copy(update=dict(quantity=Decimal(capacity) / 4)),
                capacity_intervals=(
                    CapacityInterval(
                        start_at=start + timedelta(minutes=cut),
                        end_at=start + timedelta(minutes=resume),
                        quantity=Decimal(reduced) / 4,
                        revision="2",
                        source_ref="synthetic-profile",
                    ),
                ),
            )
        )
        s = schedule.model_copy(
            update=dict(candidates=(Candidate(id="candidate", placements=slots),))
        )
        result = resource_engine.plan(
            proc.model_copy(update=dict(steps=tuple(jobs))),
            inventory.model_copy(update=dict(resources=(r,))),
            s,
            generate=False,
        )
        expected = all(
            amount <= (reduced if cut <= t < resume else capacity) for t, amount in enumerate(load)
        )
        assert (result["status"] == "feasible") == expected
        if expected:
            assert (
                result["active_minutes"] == 0
                and result["resource_usage"][0]["quantity_minutes"] == sum(load) / 4
            )
        else:
            assert "resource_capacity" in result["rejected_candidates"]["candidate"]


async def test_b_eight_contending_writers_and_replays(settings, owner, tmp_path, parsed_locally):
    import asyncio
    import contextlib
    import threading

    from tests.conftest import bridge as bridge_fixture
    from tests.test_phase_b_readiness import authored_review, import_case

    settings.database_url = "sqlite:///" + str(tmp_path / "race.db")
    settings.process_features_enabled = True
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        packet = await import_case(bridge, owner, "baseline")
        service = bridge.processes
        key = rd.save(service, owner, authored_review(packet, "BASELINE")).data["record_id"]
        work = rd.view(service, owner, key).data["remaining_work"][0]
        for revision in range(1, 7):
            barrier = threading.Barrier(8)
            requests = [
                rd.Progress(
                    record_id=key,
                    expected_revision=revision,
                    work_id=work["work_id"],
                    idempotency_key=f"race-{revision}-{n}",
                    personal_note=f"round-{revision}-writer-{n}",
                )
                for n in range(8)
            ]

            def write(req, gate=barrier):
                gate.wait(timeout=30)
                try:
                    return rd.update_progress(service, owner, req).data
                except DomainError as exc:
                    return exc.reason_code

            outputs = await asyncio.gather(*(asyncio.to_thread(write, req) for req in requests))
            assert outputs.count("PROCESS_REVISION_MISMATCH") == 7, outputs
            winner = next(i for i, o in enumerate(outputs) if isinstance(o, dict))
            assert outputs[winner]["revision"] == revision + 1
            assert rd.update_progress(service, owner, requests[winner]).data == outputs[winner]
            head = rd.view(service, owner, key).data
            assert head["revision"] == revision + 1
            assert (
                next(r for r in head["remaining_work"] if r["work_id"] == work["work_id"])[
                    "personal_note"
                ]
                == requests[winner].personal_note
            )


def test_b_all_claims_requires_all_selected_artifacts():
    bindings = {
        key: rd.Binding(
            logical_id=key,
            role="brief" if key == "brief" else "artifact",
            document_id=key,
            content_hash="a" * 64,
        )
        for key in ["brief", "slides", "appendix"]
    }
    entries = {
        key: dict(
            pages=[{"text": "Example evidence"}], coverage=SimpleNamespace(seen={1}, complete=True)
        )
        for key in bindings
    }
    row = rd.Criterion(
        requirement_id="claims",
        criterion="Every claim cites a source",
        governing=dict(source="brief", part=1, quote="Example evidence"),
        applicability_basis="Supplied brief",
        assessment_status="satisfied",
        rationale="Slide examined",
        evidence=[dict(source="slides", part=1, quote="Example evidence")],
        coverage="complete",
        coverage_rule="all_claims",
        reviewed_extent=[dict(source="slides", parts=[1])],
    )
    assert rd.assess(row, bindings, entries)["assessment_status"] == "unknown"
    row = row.model_copy(
        update=dict(reviewed_extent=(*row.reviewed_extent, rd.Extent(source="appendix", parts=[1])))
    )
    saved = rd.assess(row, bindings, entries)
    assert rd.validated_snapshot_row(saved, 2)["assessment_status"] == "satisfied"
    del saved["all_artifact_extents_verified"]
    assert rd.validated_snapshot_row(saved, 2)["assessment_status"] == "unknown"
    saved["coverage_rule"] = "passage"
    saved["governing"]["quote"] = "   "
    assert rd.validated_snapshot_row(saved, 1)["assessment_status"] == "unknown"


@pytest.mark.parametrize("actor_label", ["Member A", "Member B"])
def test_f_qualified_explicit_member_mentions_survive(actor_label):
    role = dict(
        members=[dict(member_id="A", label="Member A"), dict(member_id="B", label="Member B")],
        responsible_actor="A",
        recipient_ids=["B"],
        identity_basis="source_assignment",
        evidence=dict(quote="Member A contributes and Member B reviews."),
    )
    assert actor_label in role["evidence"]["quote"]
    assert handoffs.identity_supported(role)


def test_e_unrelated_calendars_cannot_starve_feasible_partial_plan():
    from datetime import timedelta

    from canvas_bridge.processes.resource_models import OperatingCalendar, Span

    p, i, s = inputs("capacity-proof")
    reference = resource_engine.plan(p, i, s)["partial_service"]
    assert sum(reference["prioritized_unmet_vector"]) == 60
    calendars = tuple(
        OperatingCalendar(
            id=f"unrelated-{n}",
            revision="1",
            timezone="UTC",
            windows=[
                Span(
                    start_at=s.planning_boundary + timedelta(minutes=j, seconds=n),
                    end_at=s.planning_boundary + timedelta(minutes=j, seconds=n + 1),
                )
                for j in range(160)
            ],
        )
        for n in range(26)
    )
    stressed = resource_engine.plan(
        p, i.model_copy(update=dict(calendars=(*i.calendars, *calendars))), s
    )
    assert stressed["partial_service"] == reference


@pytest.mark.parametrize("different_receipt", [False, True])
async def test_f_concurrent_send_and_receipt_lookup_return_same_effect(
    bridge, owner, tmp_path, parsed_locally, independent_recipient, different_receipt
):
    import asyncio
    import sqlite3

    from canvas_bridge.processes import (
        handoff_models as models,
    )
    from canvas_bridge.processes import (
        handoff_outputs as operations,
    )
    from canvas_bridge.processes import (
        handoff_service as service,
    )
    from tests.test_phase_f_handoffs import FixtureOutput, seed

    created = asyncio.Event()
    release = asyncio.Event()

    class DelayedConfirmation(FixtureOutput):
        async def create_if_absent(self, owner, op, payload):
            try:
                await super().create_if_absent(owner, op, payload)
            except TimeoutError:
                pass
            created.set()
            await asyncio.wait_for(release.wait(), 15)
            receipt = await self.lookup(owner, op["operation_id"])
            return (
                receipt.model_copy(update={"revision": "different"})
                if different_receipt
                else receipt
            )

    proc = bridge.processes
    proc.handoff_output_adapter = DelayedConfirmation(tmp_path / "out")
    req = await seed(bridge, owner)
    packet = (await service.prepare(proc, owner, models.Prepare.model_validate(req))).data
    subject = dict(
        record_id=req["record_id"],
        work_revision=1,
        handoff_id=req["handoff_id"],
        packet_id=packet["packet_id"],
    )
    output = (
        await service.export(
            proc, owner, models.Export(**subject, journal_revision=1, idempotency_key="export")
        )
    ).data
    op = models.OutputOperation(
        **subject,
        journal_revision=2,
        idempotency_key="send",
        output_id=output["output_id"],
        kind="delivery",
        destination_ref="fixture-inbox",
        recipient_ids=["B"],
        confirmed=True,
    )
    sending = asyncio.create_task(operations.operate(proc, owner, op))
    try:
        await asyncio.wait_for(created.wait(), 15)
        replay = await operations.operate(proc, owner, op)
    finally:
        release.set()
    if different_receipt:
        with pytest.raises(DomainError):
            await sending
    else:
        sent = await sending
        assert sent.data["receipt"] == replay.data["receipt"]
    with sqlite3.connect(proc.handoff_output_adapter.db) as db:
        assert db.execute("select count(*) from effects").fetchone()[0] == 1


@pytest.mark.parametrize("different_receipt", [False, True])
async def test_e_concurrent_apply_and_lookup_confirm_one_effect(
    bridge, owner, tmp_path, parsed_locally, independent_recipient, different_receipt
):
    import asyncio
    import sqlite3

    from canvas_bridge.processes import (
        effort_service,
    )
    from canvas_bridge.processes import (
        resource_effects as effects,
    )
    from canvas_bridge.processes import (
        resource_service as service,
    )
    from tests.test_phase_e_resources import FixtureProvider, seed

    created, release = asyncio.Event(), asyncio.Event()

    class DelayedConfirmation(FixtureProvider):
        async def apply(self, owner, operation):
            receipt = await super().apply(owner, operation)
            created.set()
            await asyncio.wait_for(release.wait(), 15)
            return (
                receipt.model_copy(update={"provider_revision": "different"})
                if different_receipt
                else receipt
            )

    proc = bridge.processes
    proc.resource_provider = DelayedConfirmation(tmp_path / "calendar.db")
    request = await seed(bridge, owner)
    await service.save(proc, owner, service.Save.model_validate(request))
    rid = request["record_id"]
    _, journal = await effort_service.authorize(proc, owner, rid)
    g = service.previous(journal.data, rid, "TYPED")
    op = next(
        o
        for o in g["operations"]
        if o["kind"] == "calendar" and not o["dependencies"] and o["status"] == "pending"
    )
    req = effects.Apply(
        record_id=rid,
        work_revision=1,
        journal_revision=journal.revision,
        idempotency_key="race",
        process_id="TYPED",
        generation_id=g["generation_id"],
        operation_id=op["operation_id"],
        confirmed=True,
    )
    applying = asyncio.create_task(effects.apply(proc, owner, req))
    try:
        await asyncio.wait_for(created.wait(), 15)
        replay = await effects.apply(proc, owner, req)
    finally:
        release.set()
    if different_receipt:
        with pytest.raises(DomainError):
            await applying
    else:
        result = await applying
        assert replay.data["status"] == result.data["status"] == "confirmed"
    with sqlite3.connect(proc.resource_provider.path) as db:
        assert db.execute("SELECT count(*) FROM effects").fetchone()[0] == 1


def test_c_repackaging_preserves_every_native_part_and_rejects_ambiguous_members():
    import random
    from io import BytesIO

    rng = random.Random(1837)
    parts = [("[Content_Types].xml", b"types"), ("ppt/presentation.xml", b"presentation")]
    parts += [(f"ppt/notesSlides/notesSlide{n}.xml", str(n).encode()) for n in range(16)]

    def manifest(entries):
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
        return changes.native_manifest(stream.getvalue())

    expected = manifest(parts)
    assert expected and len(expected) == len(parts)
    for _ in range(80):
        rng.shuffle(parts)
        assert manifest(parts) == expected
        i = rng.randrange(len(parts))
        assert manifest(parts[:i] + [(parts[i][0], b"changed")] + parts[i + 1 :]) != expected
    for invalid in (
        "ppt/Presentation.xml",
        "../slide",
        "ppt/../slide",
        "/slide",
        "ppt//slide",
        "ppt/%2fslide",
    ):
        assert manifest(parts + [(invalid, b"extra")]) is None
    assert manifest(parts + [(f"extra/{n}", b"") for n in range(4097)]) is None


def test_d_cross_episode_sweep_matches_pairwise_intersections():
    import random
    from datetime import timedelta

    from canvas_bridge.analytics.effort_history import HistoryScope, Reading
    from tests.test_phase_d_forecasting import history

    rng = random.Random(192867)
    base = history(d_fixture("history")["histories"][0])
    current = d_fixture("scenarios")["scenarios"][0]["current"]
    target = Target.model_validate({k: v for k, v in current.items() if k in Target.model_fields})
    for _ in range(100):
        rows, spans = [], []
        for i in range(16):
            lo = rng.randrange(38)
            hi = rng.randint(lo + 1, min(lo + 6, 40))
            read = Reading(
                observation_id="r",
                revision=1,
                scope_id=base.scope_id,
                known_at=base.completion.known_at,
                kind="active_interval",
                basis="timer",
                start=base.scope_start_at + timedelta(minutes=lo),
                end=base.scope_start_at + timedelta(minutes=hi),
            )
            episode = str(rng.randrange(7))
            row = HistoryScope.model_validate(
                base.model_dump() | dict(history_id=str(i), episode_id=episode, observations=[read])
            )
            rows.append(row)
            spans.append((str(i), episode, lo, hi))
        expected = {
            ident
            for ident, e, lo, hi in spans
            if any(other != e and left < hi and lo < right for _, other, left, right in spans)
        }
        rng.shuffle(rows)
        actual = {
            r["history_id"]
            for r in forecast(rows, target)["excluded"]
            if r["reason"] == "cross_episode_overlap"
        }
        assert actual == expected


def test_c_repeated_criterion_heading_cannot_hide_a_changed_clause():
    from canvas_bridge.processes.change_impact import governing_sections

    old = "## R1 Support\nGive one example.\n## R1 Format\nUse prose."
    new = old.replace("one example", "three examples")
    assert governing_sections(old)["R1"] != governing_sections(new)["R1"]


async def test_a_structured_planning_followup(
    bridge, owner, token_factory, parsed_locally, monkeypatch
):
    """Replay the host's four explicitly estimated BenchLink steps outside the frozen benchmark."""
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime

    from tests.test_independent_intelligence import imported
    from tests.test_mcp_contract import running
    from tests.test_phase_b_readiness import client_session

    clock = datetime(2026, 11, 5, 12, tzinfo=UTC)
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: clock)
    steps = [
        ("evidence", 10, []),
        ("limitations", 20, ["evidence"]),
        ("shorten", 15, ["limitations"]),
        ("rehearse", 15, ["shorten"]),
    ]
    work = [
        dict(
            key=key,
            title=key,
            activity_kind="study_step",
            parent_key="benchlink",
            progress="not_started",
            prerequisites=prereqs,
            effort=dict(
                minimum_minutes=mins,
                maximum_minutes=mins,
                origin="assistant_estimate",
                as_of=clock.isoformat(),
                assumptions="Unvalidated synthetic session budget.",
            ),
        )
        for key, mins, prereqs in steps
    ]
    work.insert(0, dict(key="benchlink", title="BenchLink presentation revision"))
    dataset = await imported(
        bridge,
        owner,
        json.dumps(
            dict(schema_version="independent-academic-1", complete=True, timezone="UTC", work=work)
        ),
    )
    request = dict(
        capability="planning",
        dataset=dataset,
        plan=dict(
            windows=[dict(start="2026-11-05T14:00:00Z", end="2026-11-05T15:00:00Z")],
            effort_overrides={row["key"]: row["effort"] for row in work if "effort" in row},
            buffer_minutes=0,
            break_minutes=0,
            minimum_block_minutes=5,
        ),
    )
    async with (
        asynccontextmanager(running.__wrapped__)(bridge, bridge.settings, None) as url,
        client_session(url, token_factory()) as client,
    ):
        result = (
            await client.call_tool("run_independent_academic_workflow", dict(request=request))
        ).structuredContent
    d = result["data"]
    from tests.test_phase_d_forecasting import capture

    capture("phase-a-structured-planning", d)
    assert result["status"] in {"ok", "partial_data"}, result
    assert d["effort_summary"]["allocated_work_minutes"] == 60
    assert d["effort_summary"]["total_known_unallocated_minutes"] == 0
    assert len(d["blocks"]) == 4
