"""Phase C exercises the real independent source adapter and owned readiness journal."""

import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.processes import change_service as cs
from canvas_bridge.processes import readiness as rd
from tests.test_independent_intelligence import independent_recipient as independent_recipient
from tests.test_phase_b_readiness import authored_review, import_case
from tests.test_recovery_independence import parsed_locally as parsed_locally

BUNDLE = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-c/specs.zip"
OUTPUT = os.getenv("BRIDGE_PHASE_C_OUTPUT")


def member(name):
    with ZipFile(BUNDLE) as z:
        return z.read("phase_c_reconciliation/" + name)


def fixture(name):
    return json.loads(member("fixtures/" + name + ".json"))


def write(name, value):
    if OUTPUT:
        path = Path(OUTPUT) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf8")


async def target_packet(bridge, owner, scenario):
    versions = {v["source_version_id"]: v for v in fixture("change_inputs")["source_versions"]}
    roles = {
        "assignment_brief": "brief",
        "reference_packet": "reference",
        "recorded_rehearsal": "measurement",
        "student_artifact": "artifact",
    }
    values = []
    for f in scenario["model_input_files"]:
        role = roles[versions[f["source_version_id"]]["role"]]
        name = (
            scenario.get("alias_name", Path(f["path"]).name)
            if role == "artifact"
            else Path(f["path"]).name
        )
        mime = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }[Path(name).suffix]
        ident = await bridge.independent.ingest(
            owner,
            member(f["path"]),
            name,
            mime,
            course="BenchLink",
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
        )
        assert bridge.independent.require(owner, ident).version_hash == f["sha256"]
        values.append(dict(logical_id=role, role=role, document_id=ident, content_hash=f["sha256"]))
    if not any(b["role"] == "artifact" for b in values):
        values.append(
            dict(logical_id="artifact", role="artifact", document_id=None, content_hash=None)
        )
    return values


def authored_rows(scenario, packet):
    label = scenario["reassessment_input_id"]
    if not label:
        return []
    c = fixture("reassessment_inputs")
    source = json.loads(member("reference/phase_b_fixture/fixtures/readiness_inputs.json"))
    ver = {v["source_version_id"]: v for v in fixture("change_inputs")["source_versions"]}
    roles = {
        "assignment_brief": "brief",
        "reference_packet": "reference",
        "recorded_rehearsal": "measurement",
        "student_artifact": "artifact",
    }
    all_refs = {r["evidence_id"]: r for r in source["evidence_catalog"] + c["new_evidence"]}

    def anchor(ref):
        r = all_refs[ref]
        loc = r.get("locator", {})
        return dict(
            source=roles[ver[r["source_version_id"]]["role"]],
            part=loc.get("slide_number", 1),
            surface={"slide": "slide", "native_notes": "notes"}.get(loc.get("surface"), "text"),
            quote=r["quote"],
        )

    rows = []
    for r in next(a for a in c["assessments"] if a["assessment_id"] == label)["rows"]:
        ident = r["requirement_id"]
        refs = [anchor(i) for i in r["evidence_refs"]]
        governing = next((a for a in refs if a["source"] == "brief"), None) or anchor("EV-" + ident)
        status = r["assessment_status"]
        rule = {"PA-R03": "all_claims", "PA-R04": "recorded_run", "PA-R05": "absence"}.get(
            ident, "passage"
        )
        if ident == "PA-R01" and status == "needs_work":
            rule = "absence"
        rows.append(
            dict(
                requirement_id=ident,
                criterion=governing["quote"],
                governing=governing,
                applicability_basis="Explicit in the governing brief.",
                assessment_status=status,
                rationale=r["rationale"],
                evidence=refs,
                coverage_rule=rule,
                coverage=r["evidence_coverage"],
                reviewed_extent=[dict(source="artifact", parts=list(range(1, 8)))]
                if rule in {"all_claims", "absence"}
                else [],
                followup="matching_rehearsal" if status == "unknown" else None,
                gap_kind=r.get("gap_kind"),
                action="Revise this criterion" if r.get("gap_kind") else None,
                completion_condition=governing["quote"] if r.get("gap_kind") else None,
                measured_artifact_hash=next(
                    b["content_hash"] for b in packet if b["role"] == "artifact"
                )
                if rule == "recorded_run" and status != "unknown"
                else None,
            )
        )
    return rows


@pytest.mark.parametrize("number", range(1, 17))
async def test_transition(number, bridge, owner, parsed_locally, independent_recipient):
    bridge.settings.process_features_enabled = True
    service = bridge.processes
    scenarios = fixture("scenarios")["scenarios"]
    sc = scenarios[number - 1]
    case = sc["id"]
    calls = []

    async def run(name, request):
        result = await getattr(cs, name)(service, owner, request)
        calls.append(
            dict(operation=name, arguments=request.model_dump(mode="json"), response=result.data)
        )
        return result.data

    first = await import_case(bridge, owner, "baseline")
    receipt = rd.save(service, owner, authored_review(first, "BASELINE")).data
    ident = receipt["record_id"]

    def head():
        return service.repository.read(owner, ident)

    def mark(task):
        r = head()
        w = next(
            row["work_item"]["work_id"]
            for row in r.data["requirements"]
            if row["requirement_id"] == task
        )
        rd.update_progress(
            service,
            owner,
            rd.Progress(
                record_id=ident,
                expected_revision=r.revision,
                work_id=w,
                idempotency_key="done-" + task,
                progress_state="student_marked_done",
            ),
        )

    async def change(s, label):
        packet = await target_packet(bridge, owner, s)
        obs = cs.Observation(
            record_id=ident,
            expected_revision=head().revision,
            target=packet,
            idempotency_key=label + "-observe",
            partial_parts={"artifact": [1, 2, 3, 4, 5]} if s["id"] == "PHC-S10" else {},
        )
        staged = await run("observe", obs)
        removed = []
        if s["id"] == "PHC-S07":
            removed = [
                dict(
                    requirement_id="PA-R01",
                    authority=dict(
                        source="brief",
                        part=1,
                        quote="This complete synthetic amendment removes PA-R01 from the required criterion set.",
                    ),
                )
            ]
        args = cs.Reassessment(
            record_id=ident,
            expected_revision=staged["revision"],
            change_id=staged["change_id"],
            idempotency_key=label + "-apply",
            assessments=authored_rows(s, packet),
            removals=removed,
            inventory_complete=True,
            material_changes=s["material_fulfillment_change_ids"],
        )
        return obs, args

    if number in {12, 13}:
        mark("PA-R02")
    if sc["initial_snapshot_id"] in {"C-STATE-CORRECTED", "C-STATE-RESOLVED-WITH-DONE-HISTORY"}:
        _, warm = await change(scenarios[2], "prior")
        await run("apply_change", warm)
    if number == 16:
        mark("PA-R01")
        _, transition = await change(scenarios[2], "before-rollback")
        applied = await run("apply_change", transition)
        # Progress on independent work after the reconciliation is outside its compensation scope.
        other = authored_review(first, "BASELINE").model_copy(
            update=dict(assignment_id="separate-assignment", idempotency_key="other")
        )
        other_id = rd.save(service, owner, other).data["record_id"]
        work = rd.view(service, owner, other_id).data["remaining_work"][0]
        rd.update_progress(
            service,
            owner,
            rd.Progress(
                record_id=other_id,
                expected_revision=1,
                work_id=work["work_id"],
                idempotency_key="unrelated-later",
                progress_state="student_marked_done",
                personal_note="Retain this unrelated later progress.",
            ),
        )
        undo = cs.Compensation(
            record_id=ident,
            expected_revision=head().revision,
            applied_revision=applied["revision"],
            idempotency_key="undo",
        )
        comp = await run("compensate", undo)
        assert await run("compensate", undo) == comp
        assert (
            rd.view(service, owner, ident).data["remaining_work"][0]["progress_state"]
            == "student_marked_done"
        )
        assert (
            rd.view(service, owner, other_id).data["remaining_work"][0]["personal_note"]
            == "Retain this unrelated later progress."
        )
    else:
        obs, args = await change(sc, case)
        if number in {14, 15}:
            duplicate = await run(
                "observe", obs.model_copy(update={"idempotency_key": "another-observer"})
            )
            assert duplicate["revision"] == args.expected_revision
        if number == 15:
            mark("PA-R01")
            with pytest.raises(DomainError):
                await run("apply_change", args)
            args = args.model_copy(
                update=dict(expected_revision=head().revision, idempotency_key="rebased")
            )
        receipt = await run("apply_change", args)
        assert await run("apply_change", args) == receipt
    result = rd.view(service, owner, ident).data
    report = (await cs.report(service, owner, ident)).data
    write(case + ".json", dict(calls=calls, view=result, report=report))
    expected = fixture("expected_transitions")["results"][number - 1]
    assert {
        r["requirement_id"]: r["assessment_status"] for r in result["requirements"]
    } == expected["row_statuses"]
    assert (
        result["summary_status"] == expected["readiness"]
        and len(result["review_followups"]) == expected["review_followup_count"]
    )
    if number != 16:
        assert {
            a["requirement_id"]: a["impact_status"] for a in report["change_report"]["impacts"]
        } == expected["impacts"]
        assert {
            a["requirement_id"]: a["work_action"] for a in report["change_report"]["work_actions"]
        } == {a["requirement_id"]: a["action"] for a in expected["work_actions"]}


@pytest.mark.skipif(
    not os.environ.get("BRIDGE_PHASE_C_HOST"), reason="Opt-in native synthetic host journey"
)
async def test_native_journeys(settings, owner, token_factory, tmp_path):
    import contextlib

    from tests.conftest import bridge as bridge_fixture
    from tests.test_permission_consistency_contract import client_session
    from tests.test_phase_a_benchmark import review_host
    from tests.test_phase_b_readiness import running

    settings.database_url = "sqlite:///" + str(tmp_path / "state.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    settings.parser_root = settings.parser_runtime_root = (
        Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    )
    tools = [
        "get_assignment_readiness",
        "read_local_document",
        "get_local_document_status",
        "observe_assignment_change",
        "get_assignment_change",
        "reconcile_assignment_change",
        "compensate_assignment_change",
    ]
    workdir = tmp_path / "host"
    workdir.mkdir()
    instruction = (
        "Use only the coursework MCP tools. No filesystem, shell or external tools. Retrieve the saved readiness. If the selected context contains a staged change_id, resume it directly using get_assignment_change. Otherwise for a refresh, observe the provided target bindings at the current record revision, get the change, read selected current sources through continuations, then reconcile the staged change using its returned revision and change ID. Use exact source quotes and requested brief IDs. Supply targeted assessments only for affected criteria where supported. Unavailable branches can remain pending. Retrieve both the change report and the readiness after any write. For recovery compensate the specified applied revision. Use an original idempotency key per operation. Tool argument schemas: "
        + json.dumps(
            {
                model.__name__: model.model_json_schema()
                for model in [cs.Observation, cs.Reassessment, cs.Compensation]
            }
        )
    )

    async def host(name, prompt, ctx):
        out = Path(OUTPUT) / "native" / name
        out.mkdir(parents=True)
        ans = await review_host(
            settings.resource_url,
            token_factory(),
            member("prompts/" + prompt + ".md").decode() + "\nSelected context: " + json.dumps(ctx),
            workdir,
            out,
            "host",
            tools=tools,
            instructions=instruction,
        )
        assert ans

    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        first = await import_case(bridge, owner, "baseline")
        # Rebind the real, frozen Phase B host assessment to the same canonical source bytes.
        with ZipFile(
            BUNDLE.parents[3] / "evidence/sanitized-results/phase-b-readiness-receipts.zip"
        ) as z:
            events = [
                json.loads(line)
                for line in z.read("baseline/save/native-events.jsonl").decode().splitlines()
            ]
        review = next(
            e["item"]["arguments"]["review"]
            for e in reversed(events)
            if e["type"] == "item.completed"
            and e["item"].get("tool") == "save_assignment_readiness"
            and e["item"].get("result")
            and json.loads(e["item"]["result"]["content"][0]["text"]).get("status") == "ok"
        )
        assert {x["content_hash"] for x in review["bindings"]} == {x["content_hash"] for x in first}
        key = rd.save(
            bridge.processes,
            owner,
            rd.Review.model_validate(review | dict(bindings=first, course="BenchLink")),
        ).data["record_id"]

        def head():
            return bridge.processes.repository.read(owner, key)

        original = head()
        task = next(
            r["work_item"]["work_id"]
            for r in original.data["requirements"]
            if r["requirement_id"] == "PA-R01"
        )
        rd.update_progress(
            bridge.processes,
            owner,
            rd.Progress(
                record_id=key,
                expected_revision=original.revision,
                idempotency_key="declared",
                work_id=task,
                progress_state="student_marked_done",
                personal_note="Keep the dated review note.",
            ),
        )
        async with running(settings) as pid:
            async with client_session(settings.resource_url, token_factory()) as session:
                write(
                    "native/schemas.json",
                    [
                        t.model_dump(mode="json")
                        for t in (await session.list_tools()).tools
                        if t.name in tools
                    ],
                )
            corrected = await target_packet(bridge, owner, fixture("scenarios")["scenarios"][2])
            await host(
                "corrected",
                "review_changes",
                dict(record_id=key, expected_revision=head().revision, target=corrected),
            )
            assert head().data.get("change_report", {}).get("processing_state") == "applied"
            write("native/corrected-state.json", head().data)
            amended = await target_packet(bridge, owner, fixture("scenarios")["scenarios"][3])
            observation = cs.Observation(
                record_id=key,
                expected_revision=head().revision,
                idempotency_key="stage-amendment",
                target=amended,
            )
            async with client_session(settings.resource_url, token_factory()) as session:
                staged = (
                    await session.call_tool(
                        "observe_assignment_change",
                        {"request": observation.model_dump(mode="json")},
                    )
                ).structuredContent
                assert staged["status"] == "ok"
                write(
                    "native/pre-restart.json",
                    dict(observation=observation.model_dump(mode="json"), result=staged),
                )
        async with running(settings) as pid2:
            write("native/restart.json", dict(before=pid, after=pid2))
            await host(
                "amendment",
                "review_changes",
                dict(
                    record_id=key,
                    expected_revision=head().revision,
                    target=amended,
                    change_id=staged["data"]["change_id"],
                ),
            )
            write("native/amendment-state.json", head().data)
            await host(
                "recurrence",
                "recurring_work",
                dict(record_id=key, expected_revision=head().revision, target=first),
            )
            write("native/recurrence-state.json", head().data)
            assert head().data["change_report"]["applied_revision"] == head().revision
            missing = [
                b if b["role"] != "artifact" else b | dict(document_id=None, content_hash=None)
                for b in first
            ]
            await host(
                "missing",
                "replacement_unavailable",
                dict(record_id=key, expected_revision=head().revision, target=missing),
            )
            write("native/missing-state.json", head().data)
            await host(
                "compensate",
                "restore_reconciliation",
                dict(
                    record_id=key,
                    applied_revision=head().data["change_report"]["applied_revision"],
                    expected_revision=head().revision,
                ),
            )
            write("native/restored-state.json", head().data)
            if head().data["change_report"]["processing_state"] != "compensated":
                events = (Path(OUTPUT) / "native/compensate/host-events.jsonl").read_text("utf8")
                assert (
                    "MCP tool call requires approval" in events
                    and "approval policy is never" in events
                )
                write(
                    "native/compensation-boundary.json",
                    dict(
                        status="blocked_by_native_host",
                        receipt=None,
                        observed_revision=head().revision,
                        evidence="compensate/host-events.jsonl",
                    ),
                )


async def test_controls_and_failed_commit(
    bridge, owner, parsed_locally, independent_recipient, monkeypatch
):
    import io

    from canvas_bridge.processes.change_observation import native_manifest

    bridge.settings.process_features_enabled = True
    service = bridge.processes
    initial = await import_case(bridge, owner, "baseline")
    key = rd.save(service, owner, authored_review(initial, "BASELINE")).data["record_id"]
    base = service.repository.read(owner, key)
    item = base.data["requirements"][0]["work_item"]["work_id"]
    rd.update_progress(
        service,
        owner,
        rd.Progress(
            record_id=key,
            work_id=item,
            expected_revision=1,
            idempotency_key="edit",
            progress_state="student_marked_done",
            personal_note="Check my measurements",
            personal_title="My targeted rehearsal",
            effort=dict(minimum_minutes=10, maximum_minutes=20, origin="student_estimate"),
        ),
    )
    scenarios = fixture("scenarios")["scenarios"]
    packet = await target_packet(bridge, owner, scenarios[11])
    obs = cs.Observation(
        record_id=key, expected_revision=2, idempotency_key="observe", target=packet
    )
    staged = (await cs.observe(service, owner, obs)).data
    apply = cs.Reassessment(
        record_id=key,
        expected_revision=staged["revision"],
        change_id=staged["change_id"],
        idempotency_key="apply",
        inventory_complete=True,
    )

    assert (
        rd.view(service, owner, key).data["pending_observation"]["change_id"] == staged["change_id"]
    )

    def fail_after_flush(*args):
        persist(*args)
        raise RuntimeError("synthetic failure after staging write")

    persist = service.repository._save
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "_save", fail_after_flush)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            await cs.apply_change(service, owner, apply)
    assert service.repository.read(owner, key).revision == staged["revision"]
    receipt = (await cs.apply_change(service, owner, apply)).data
    assert (await cs.apply_change(service, owner, apply)).data == receipt
    with pytest.raises(DomainError) as legacy:
        service.repository.rollback_preview(owner, receipt["revision_id"])
    assert legacy.value.reason_code == "CHANGE_SCOPED_RECOVERY_REQUIRED"
    task = rd.view(service, owner, key).data["remaining_work"][0]
    assert (
        task["personal_note"] == "Check my measurements"
        and task["progress_state"] == "student_marked_done"
    )
    assert task["effort"]["origin"] == "student_estimate" and task["declaration_id"]
    rd.update_progress(
        service,
        owner,
        rd.Progress(
            record_id=key,
            expected_revision=receipt["revision"],
            work_id=task["work_id"],
            idempotency_key="later",
            personal_note="Preserve this later note",
        ),
    )
    rollback = (
        await cs.compensate(
            service,
            owner,
            cs.Compensation(
                record_id=key,
                expected_revision=receipt["revision"] + 1,
                applied_revision=receipt["revision"],
                idempotency_key="undo",
            ),
        )
    ).data
    restored = rd.view(service, owner, key).data
    assert restored["remaining_work"][0]["personal_note"] == "Preserve this later note"
    # A newly arrived historical observation has its own receipt and leaves today's head alone.
    historical = (
        await cs.observe(
            service,
            owner,
            obs.model_copy(
                update=dict(
                    target=tuple(map(rd.Binding.model_validate, initial)), idempotency_key="late"
                )
            ),
        )
    ).data
    assert (
        historical["processing_state"] == "superseded"
        and historical["revision"] == rollback["revision"]
    )
    # An automatic refresh cannot skip an unproved parent; explicit direct comparisons are separate.
    target = await target_packet(bridge, owner, scenarios[2])
    pending = (
        await cs.observe(
            service,
            owner,
            cs.Observation(
                record_id=key,
                expected_revision=rollback["revision"],
                target=target,
                idempotency_key="missing-parent",
                selection_mode="refresh",
                source_parents={"artifact": "0" * 64},
            ),
        )
    ).data
    with pytest.raises(DomainError) as missing:
        await cs.apply_change(
            service,
            owner,
            apply.model_copy(
                update=dict(
                    expected_revision=pending["revision"],
                    change_id=pending["change_id"],
                    idempotency_key="skip-parent",
                )
            ),
        )
    assert missing.value.reason_code == "CHANGE_PARENT_UNRESOLVED"
    # Duplicate native part aliases must never be elevated to a complete payload proof.
    raw = io.BytesIO()
    with ZipFile(raw, "w") as z:
        for name in ("[Content_Types].xml", "ppt/presentation.xml", "PPT/presentation.xml"):
            z.writestr(name, b"x")
    assert native_manifest(raw.getvalue()) is None
    write(
        "transaction-controls.json",
        dict(
            staged=staged,
            recovered=receipt,
            restored=restored,
            rollback=rollback,
            historical=historical,
            parent_block=missing.value.reason_code,
        ),
    )


async def test_live_replaced_alias(bridge, owner, parsed_locally, independent_recipient):
    bridge.settings.process_features_enabled = True
    initial = await import_case(bridge, owner, "baseline")
    service = bridge.processes
    key = rd.save(service, owner, authored_review(initial, "BASELINE")).data["record_id"]
    old = next(b for b in initial if b["role"] == "artifact")
    raw = member("reference/phase_b_fixture/reference/phase_a_fixture/cases/corrected/deck.pptx")
    ident = await bridge.independent.ingest(
        owner,
        raw,
        "deck.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        course="BenchLink",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
        replace_id=old["document_id"],
        expected_hash=old["content_hash"],
    )
    target = [
        b
        if b != old
        else b
        | dict(
            document_id=ident, content_hash=bridge.independent.require(owner, ident).version_hash
        )
        for b in initial
    ]
    receipt = (
        await cs.observe(
            service,
            owner,
            cs.Observation(
                record_id=key, expected_revision=1, target=target, idempotency_key="in-place"
            ),
        )
    ).data
    change = (await cs.report(service, owner, key)).data
    assert (
        next(c for c in change["change_report"]["comparisons"] if c["role"] == "artifact")[
            "change_class"
        ]
        == "incomparable"
    )
    assert rd.view(service, owner, key).data["summary_status"] == "unknown"
    applied = (
        await cs.apply_change(
            service,
            owner,
            cs.Reassessment(
                record_id=key,
                expected_revision=receipt["revision"],
                change_id=receipt["change_id"],
                inventory_complete=True,
                idempotency_key="review-later",
            ),
        )
    ).data
    assert rd.view(service, owner, key).data["counts"]["unknown"] == 4
    write("in-place.json", dict(observation=receipt, pending=change, apply=applied))


async def test_hidden_context_and_order_controls(
    bridge, owner, parsed_locally, independent_recipient
):
    import io

    from canvas_bridge.processes.change_observation import native_manifest

    bridge.settings.process_features_enabled = True
    service = bridge.processes
    packet = await import_case(bridge, owner, "baseline")
    initial = authored_review(packet, "BASELINE")
    key = rd.save(service, owner, initial).data["record_id"]
    other = rd.save(
        service,
        owner,
        initial.model_copy(update=dict(assignment_id="second", idempotency_key="separate")),
    ).data
    first = rd.view(service, owner, key).data
    second = rd.view(service, owner, other["record_id"]).data
    assert key != other["record_id"] and {w["work_id"] for w in first["remaining_work"]}.isdisjoint(
        w["work_id"] for w in second["remaining_work"]
    )
    scenarios = fixture("scenarios")["scenarios"]

    def revision():
        return service.repository.read(owner, key).revision

    async def observe(target, label, **kwargs):
        return (
            await cs.observe(
                service,
                owner,
                cs.Observation(
                    expected_revision=revision(),
                    record_id=key,
                    target=target,
                    idempotency_key=label,
                    **kwargs,
                ),
            )
        ).data

    corrected = await target_packet(bridge, owner, scenarios[2])
    staged = await observe(corrected, "first-corrected")
    args = cs.Reassessment(
        expected_revision=staged["revision"],
        record_id=key,
        change_id=staged["change_id"],
        assessments=authored_rows(scenarios[2], corrected),
        inventory_complete=True,
        idempotency_key="corrected",
    )
    await cs.apply_change(service, owner, args)
    # The prior head is not reselected when an old automatic notification arrives last.
    hashes = {b["role"]: b["content_hash"] for b in packet}
    late = await observe(
        packet, "older", selection_mode="refresh", source_parents={"artifact": "1" * 64}
    )
    assert late["processing_state"] == "superseded" and revision() == late["revision"]
    limited = await target_packet(bridge, owner, scenarios[6])
    st = await observe(limited, "incomplete-inventory")
    removal = cs.Removal(
        requirement_id="PA-R01",
        authority=rd.Anchor(
            source="brief",
            part=1,
            quote="This complete synthetic amendment removes PA-R01 from the required criterion set.",
        ),
    )
    with pytest.raises(DomainError):
        await cs.apply_change(
            service,
            owner,
            cs.Reassessment(
                expected_revision=st["revision"],
                record_id=key,
                change_id=st["change_id"],
                removals=[removal],
                inventory_complete=False,
                idempotency_key="unsafe-retire",
            ),
        )
    # Identical extracted visible slide text is insufficient when an uninspected native part differs.
    raw = member("reference/phase_b_fixture/reference/phase_a_fixture/cases/corrected/deck.pptx")
    changed = io.BytesIO()
    with ZipFile(io.BytesIO(raw)) as src, ZipFile(changed, "w") as dest:
        for part in src.namelist():
            content = src.read(part)
            if part == "ppt/notesSlides/notesSlide7.xml":
                content = content.replace(
                    b"</p:notes>", b"<!-- additional native context --></p:notes>"
                )
                assert content != src.read(part)
            dest.writestr(part, content)
    assert native_manifest(raw) != native_manifest(changed.getvalue())
    changed_id = await bridge.independent.ingest(
        owner,
        changed.getvalue(),
        "changed-notes.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        course="BenchLink",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
    )
    fresh = [
        b
        if b["role"] != "artifact"
        else b
        | dict(
            document_id=changed_id,
            content_hash=bridge.independent.require(owner, changed_id).version_hash,
        )
        for b in corrected
    ]
    pending = await observe(fresh, "hidden-context", partial_parts={"artifact": [1, 2, 3, 4, 5]})
    projected = (await cs.report(service, owner, key)).data
    assert (
        next(c for c in projected["change_report"]["comparisons"] if c["role"] == "artifact")[
            "change_class"
        ]
        == "content_changed"
    )
    assert (
        next(r for r in projected["current_selection"] if r["requirement_id"] == "PA-R03")[
            "assessment_status"
        ]
        == "unknown"
    )
    assert (
        next(r for r in projected["current_selection"] if r["requirement_id"] == "PA-R04")[
            "assessment_status"
        ]
        == "unknown"
    )
    # Summary precedence for known required conflict/work is the very same projection used in pending reports.
    rows = [
        dict(required=True, applicability="applicable", assessment_status=x)
        for x in ("unknown", "needs_work")
    ]
    assert rd.summarize(rows, False)["summary_status"] == "needs_work"
    assert (
        rd.summarize(rows + [rows[0] | {"assessment_status": "conflict"}], False)["summary_status"]
        == "conflict"
    )
    write(
        "dependency-controls.json",
        dict(
            late=late,
            selected=hashes,
            partial_observation=pending,
            pending=projected,
            isolated_record=other,
        ),
    )


async def test_real_concurrent_progress(
    settings, owner, tmp_path, parsed_locally, independent_recipient
):
    import asyncio
    import contextlib
    import threading

    from tests.conftest import bridge as bridge_fixture

    settings.database_url = "sqlite:///" + str(tmp_path / "race.db")
    settings.process_features_enabled = True
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        service = bridge.processes
        packet = await import_case(bridge, owner, "baseline")
        key = rd.save(service, owner, authored_review(packet, "BASELINE")).data["record_id"]
        target = await target_packet(bridge, owner, fixture("scenarios")["scenarios"][11])
        obs = await cs.observe(
            service,
            owner,
            cs.Observation(
                record_id=key, expected_revision=1, idempotency_key="stage", target=target
            ),
        )
        args = cs.Reassessment(
            record_id=key,
            expected_revision=obs.data["revision"],
            change_id=obs.data["change_id"],
            inventory_complete=True,
            idempotency_key="apply",
        )
        work = rd.view(service, owner, key).data["remaining_work"][0]
        progress = rd.Progress(
            record_id=key,
            expected_revision=args.expected_revision,
            work_id=work["work_id"],
            idempotency_key="mark",
            progress_state="student_marked_done",
        )
        wait = threading.Barrier(2)

        def compete(op):
            wait.wait(timeout=10)
            try:
                result = (
                    asyncio.run(cs.apply_change(service, owner, args))
                    if op == "apply"
                    else rd.update_progress(service, owner, progress)
                )
                return result.data
            except DomainError as exc:
                return {"reason_code": exc.reason_code}

        results = await asyncio.gather(
            *(asyncio.to_thread(compete, name) for name in ("apply", "progress"))
        )
        assert sum(r.get("revision") == 3 for r in results) == 1
        assert sum(r.get("reason_code") == "PROCESS_REVISION_MISMATCH" for r in results) == 1
        if "reason_code" in results[0]:
            await cs.apply_change(
                service,
                owner,
                args.model_copy(update=dict(expected_revision=3, idempotency_key="apply-again")),
            )
            assert (
                rd.view(service, owner, key).data["remaining_work"][0]["progress_state"]
                == "student_marked_done"
            )
        write(
            "concurrent-writers.json", dict(results=results, view=rd.view(service, owner, key).data)
        )


async def test_protocol_compensation(settings, bridge, owner, token_factory, parsed_locally):
    from tests.test_mcp_contract import running as serve
    from tests.test_permission_consistency_contract import client_session

    settings.process_features_enabled = True
    packet = await import_case(bridge, owner, "baseline")
    key = rd.save(bridge.processes, owner, authored_review(packet, "BASELINE")).data["record_id"]
    target = await target_packet(bridge, owner, fixture("scenarios")["scenarios"][11])
    receipts = []
    async for url in serve.__wrapped__(bridge, settings, None):
        async with client_session(url, token_factory(), read_timeout=90) as session:

            async def call(name, arguments):
                out = (await session.call_tool(name, arguments)).structuredContent
                receipts.append(dict(tool=name, arguments=arguments, result=out))
                assert out["status"] == "ok", (name, out["summary"])
                return out["data"]

            obs = await call(
                "observe_assignment_change",
                dict(
                    request=dict(
                        record_id=key, target=target, expected_revision=1, idempotency_key="observe"
                    )
                ),
            )
            commit = await call(
                "reconcile_assignment_change",
                dict(
                    request=dict(
                        record_id=key,
                        change_id=obs["change_id"],
                        expected_revision=obs["revision"],
                        inventory_complete=True,
                        idempotency_key="apply",
                    )
                ),
            )
            published = await call("get_assignment_change", dict(record_id=key))
            assert published["change_report"]["action_counts"] == {"keep": 2, "update": 1}
            assert published["change_report"]["impact_counts"] == {"unaffected": 4}
            assert all(a["action_reason"] for a in published["change_report"]["work_actions"])
            state = await call("get_assignment_readiness", dict(record_id=key))
            w = next(w for w in state["remaining_work"] if w["requirement_id"] == "PA-R04")
            update = await call(
                "record_readiness_progress",
                dict(
                    request=dict(
                        record_id=key,
                        work_id=w["work_id"],
                        expected_revision=commit["revision"],
                        progress_state="in_progress",
                        personal_note="Preserve this later progress",
                        idempotency_key="late-edit",
                    )
                ),
            )
            args = dict(
                request=dict(
                    record_id=key,
                    applied_revision=commit["revision"],
                    expected_revision=update["revision"],
                    idempotency_key="compensate",
                )
            )
            restored = await call("compensate_assignment_change", args)
            assert await call("compensate_assignment_change", args) == restored
            current = await call("get_assignment_readiness", dict(record_id=key))
            assert any(
                w.get("personal_note") == "Preserve this later progress"
                for w in current["remaining_work"]
            )
        write("compensation-protocol.json", receipts)


@pytest.mark.skipif(
    not os.environ.get("BRIDGE_PHASE_C_HOST"), reason="Opt-in native synthetic amendment"
)
@pytest.mark.parametrize("number", [5, 6])
async def test_native_scoped_amendments(
    number, settings, owner, token_factory, tmp_path, independent_recipient
):
    import contextlib

    from tests.conftest import bridge as bridge_fixture
    from tests.test_phase_a_benchmark import review_host
    from tests.test_phase_b_readiness import running

    settings.database_url = "sqlite:///" + str(tmp_path / "isolated.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    settings.parser_root = settings.parser_runtime_root = (
        Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    )
    out = Path(OUTPUT) / "native" / ("duration" if number == 5 else "added")
    out.mkdir(parents=True)
    workdir = tmp_path / "empty"
    workdir.mkdir()
    scenarios = fixture("scenarios")["scenarios"]
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        first = await import_case(bridge, owner, "baseline")
        key = rd.save(bridge.processes, owner, authored_review(first, "BASELINE")).data["record_id"]
        corrected = await target_packet(bridge, owner, scenarios[2])
        # Establish a committed previous corrected state. Only the following target review earns host credit.
        obs = await cs.observe(
            bridge.processes,
            owner,
            cs.Observation(
                record_id=key, expected_revision=1, idempotency_key="seed", target=corrected
            ),
        )
        receipt = await cs.apply_change(
            bridge.processes,
            owner,
            cs.Reassessment(
                record_id=key,
                expected_revision=obs.data["revision"],
                change_id=obs.data["change_id"],
                assessments=authored_rows(scenarios[2], corrected),
                inventory_complete=True,
                idempotency_key="seed-review",
            ),
        )
        target = await target_packet(bridge, owner, scenarios[number - 1])
        context = dict(record_id=key, expected_revision=receipt.data["revision"], target=target)
        tools = [
            "get_assignment_readiness",
            "get_assignment_change",
            "observe_assignment_change",
            "reconcile_assignment_change",
            "read_local_document",
            "get_local_document_status",
        ]
        instructions = (
            "Use only the coursework tools. Observe the selected change, inspect the returned change report, read current sources for impacted criteria including continuations and native notes; assess them from the brief and artifact, then reconcile and retrieve the confirmed change and readiness. Use precise source quotes and actual reviewed extent. Leave proven unaffected rows to carry automatically. Tool argument models: "
            + json.dumps([c.model_json_schema() for c in (cs.Observation, cs.Reassessment)])
        )
        async with running(settings):
            answer = await review_host(
                settings.resource_url,
                token_factory(),
                member("prompts/review_changes.md").decode()
                + "\nSelected assignment/target: "
                + json.dumps(context),
                workdir,
                out,
                "host",
                tools=tools,
                instructions=instructions,
            )
            assert answer
        state = bridge.processes.repository.read(owner, key)
        write("native/" + out.name + "-state.json", state.data)
        assert state.data["assessment_revision"] > receipt.data["revision"]
        task = "PA-R04" if number == 5 else "PA-R05"
        assert (
            next(r for r in state.data["requirements"] if r["requirement_id"] == task)[
                "assessment_status"
            ]
            == "needs_work"
        )


async def test_episode_scoped_effort(bridge, owner, parsed_locally, independent_recipient):
    from canvas_bridge.planning import PlanRequest

    bridge.settings.process_features_enabled = True
    service = bridge.processes
    first = await import_case(bridge, owner, "baseline")
    key = rd.save(service, owner, authored_review(first, "BASELINE")).data["record_id"]
    original = next(
        w
        for w in rd.view(service, owner, key).data["remaining_work"]
        if w["requirement_id"] == "PA-R02"
    )
    rd.update_progress(
        service,
        owner,
        rd.Progress(
            record_id=key,
            expected_revision=1,
            idempotency_key="my-estimate",
            work_id=original["work_id"],
            effort=dict(minimum_minutes=12, maximum_minutes=20, origin="student_estimate"),
            progress_state="student_marked_done",
            personal_note="This was the earlier version.",
        ),
    )
    scenario = fixture("scenarios")["scenarios"][13]
    target = await target_packet(bridge, owner, scenario)
    staged = (
        await cs.observe(
            service,
            owner,
            cs.Observation(
                record_id=key,
                expected_revision=2,
                target=target,
                idempotency_key="changed-fulfillment",
            ),
        )
    ).data
    applied = (
        await cs.apply_change(
            service,
            owner,
            cs.Reassessment(
                record_id=key,
                expected_revision=staged["revision"],
                idempotency_key="apply",
                change_id=staged["change_id"],
                inventory_complete=True,
                assessments=authored_rows(scenario, target),
                material_changes=["PA-R02"],
            ),
        )
    ).data
    view = rd.view(service, owner, key, plan=PlanRequest()).data
    task = view["remaining_work"][0]
    assert task["requirement_id"] == "PA-R02" and task["work_id"] != original["work_id"]
    assert (
        task["progress_state"] == "not_started"
        and task["progress_basis"] == "system_default"
        and not task.get("declaration_id")
    )
    assert task["effort_review_needed"] and "effort" not in task
    assert task["work_id"] in view["plan"]["effort_summary"]["unknown_effort_work_ids"]
    before = rd.view(service, owner, key, revision=2).data
    past = next(w for w in before["remaining_work"] if w["requirement_id"] == "PA-R02")
    assert (
        past["effort"]["maximum_minutes"] == 20 and past["declaration_id"] and past["personal_note"]
    )
    write("planner-delta.json", dict(prior=before, applied=applied, current=view))


@pytest.mark.skipif(
    not os.environ.get("BRIDGE_PHASE_C_HOST"), reason="Opt-in host recall of a staged change"
)
async def test_native_pending_recall(
    settings, owner, token_factory, tmp_path, independent_recipient
):
    import contextlib

    from tests.conftest import bridge as bridge_fixture
    from tests.test_phase_a_benchmark import review_host
    from tests.test_phase_b_readiness import running

    settings.database_url = "sqlite:///" + str(tmp_path / "state.db")
    settings.process_features_enabled = settings.file_reading_enabled = True
    settings.parser_root = settings.parser_runtime_root = (
        Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    )
    out = Path(OUTPUT) / "native" / "pending-recall"
    out.mkdir(parents=True)
    workdir = tmp_path / "empty"
    workdir.mkdir()
    with contextlib.contextmanager(bridge_fixture.__wrapped__)(settings) as bridge:
        base = await import_case(bridge, owner, "baseline")
        key = rd.save(bridge.processes, owner, authored_review(base, "BASELINE")).data["record_id"]
        packet = await target_packet(bridge, owner, fixture("scenarios")["scenarios"][2])
        stage = await cs.observe(
            bridge.processes,
            owner,
            cs.Observation(
                record_id=key, target=packet, expected_revision=1, idempotency_key="staged"
            ),
        )
        async with running(settings):
            answer = await review_host(
                settings.resource_url,
                token_factory(),
                f"Recall my saved assignment {key}. Is an updated file selection awaiting review? Tell me what was actually saved and what is pending.",
                workdir,
                out,
                "host",
                tools=["get_assignment_readiness", "get_assignment_change"],
                instructions="Use only the two coursework tools for this synthetic saved review. Retrieve the readiness first and check any pending observation.",
            )
        assert (
            answer
            and bridge.processes.repository.read(owner, key).revision == stage.data["revision"]
        )
        events = [
            json.loads(line) for line in (out / "host-events.jsonl").read_text("utf8").splitlines()
        ]
        completed = [
            e["item"]
            for e in events
            if e["type"] == "item.completed" and e["item"]["type"] == "mcp_tool_call"
        ]
        assert {"get_assignment_readiness", "get_assignment_change"} == {
            i["tool"] for i in completed
        }
        assert any("pending_observation" in json.dumps(i.get("result")) for i in completed)


async def test_dependency_publication_boundary(
    bridge, owner, parsed_locally, independent_recipient
):
    from canvas_bridge.processes.models import AcademicRecord

    bridge.settings.process_features_enabled = True
    svc = bridge.processes
    before = await import_case(bridge, owner, "baseline")
    key = rd.save(svc, owner, authored_review(before, "BASELINE")).data["record_id"]
    base = svc.repository.read(owner, key)
    child = AcademicRecord(
        id="derived-work",
        kind="plan",
        scope=base.scope,
        data={"title": "Dependent plan"},
        sources=base.sources,
        depends_on=(key,),
        updated_at=bridge.retention.clock(),
    )
    preview = svc.repository.propose(owner, child.id, child, "create")
    svc.repository.commit(owner, preview, confirmed=True, idempotency_key="child")
    case = fixture("scenarios")["scenarios"][2]
    target = await target_packet(bridge, owner, case)
    obs = await cs.observe(
        svc,
        owner,
        cs.Observation(record_id=key, target=target, expected_revision=1, idempotency_key="stage"),
    )
    assert svc.repository.read(owner, child.id).state == "valid"
    applied = await cs.apply_change(
        svc,
        owner,
        cs.Reassessment(
            record_id=key,
            expected_revision=obs.data["revision"],
            change_id=obs.data["change_id"],
            idempotency_key="apply",
            inventory_complete=True,
            assessments=authored_rows(case, target),
        ),
    )
    assert applied.data["revision"] > obs.data["revision"]
    with pytest.raises(DomainError) as invalid:
        svc.repository.read(owner, child.id)
    assert invalid.value.reason_code == "PROCESS_RECORD_NOT_VALID"
    write(
        "dependency-publication.json",
        dict(
            parent=key,
            child=child.id,
            pending=obs.data,
            child_state_while_pending="valid",
            applied=applied.data,
            after=invalid.value.reason_code,
        ),
    )
