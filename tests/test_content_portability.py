"""Synthetic course packet acceptance through the authenticated settings route."""

import io
import json
import zipfile
from hashlib import sha256
from urllib.parse import quote

import pytest

from tests.test_recovery_independence import parsed_locally as parsed_locally
from tests.test_usefulness import ui as ui


@pytest.fixture(autouse=True)
def enable(bridge):
    bridge.settings.usefulness_features_enabled = True
    bridge.settings.process_features_enabled = True


def archive(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        for name, value in members:
            output.writestr(name, value)
    return stream.getvalue()


async def upload(
    ui,
    members,
    key,
    *,
    term="fall",
    role="material",
    course="MKT",
    expected=None,
    decisions=None,
    commit=True,
):
    payload = archive(members)
    headers = {
        "X-Bridge-CSRF": "usefulness-csrf",
        "X-Bridge-Own": "true",
        "X-Bridge-Key": key,
        "X-Bridge-Filename": "packet.zip",
        "X-Bridge-Term": term,
        "X-Bridge-Purpose": role,
        "X-Bridge-Course": course,
        "X-Bridge-Expected": quote(json.dumps(expected or {})),
        "X-Bridge-Mappings": quote(json.dumps(decisions or {})),
        "Content-Type": "application/zip",
    }

    async def post(extra):
        response = await ui.post(
            "/settings/materials/import", content=payload, headers=headers | extra
        )
        assert response.status_code == 200, response.text
        return response.json()

    review = await post({"X-Bridge-Preview": "true"})
    if not commit:
        return review
    return await post({"X-Bridge-Confirmation": review["preview_id"]})


async def test_packet_move_revision_reorder_and_scopes(ui, bridge, owner, parsed_locally):
    original = [("unit/a.txt", "Memo due Nov 2."), ("unit/b.md", "Feedback.")]
    first = await upload(ui, original, "first")
    assert first["state"] == "ready"
    old, feedback = first["items"]
    longpath = "chapter/" * 50 + "reading.txt"
    moved = await upload(ui, [original[1], (longpath, original[0][1])], "moved")
    assert [i["disposition"] for i in moved["items"]] == ["unchanged", "relocated"]
    assert moved["items"][1]["document_id"] == old["document_id"]
    for field in ("role", "term", "course"):
        other = await upload(ui, original[:1], field, **{field: "reading"})
        assert other["items"][0]["binding"] != old["binding"]
        assert other["items"][0]["document_id"] != old["document_id"]
    rev = await upload(ui, [("unit/a.txt", "Memo due Nov 4.")], "revision")
    item = rev["items"][0]
    assert item["disposition"] == "new_version" and item["binding"] == old["binding"]
    row = bridge.independent.require(owner, item["document_id"])
    assert row.content["version_history"][-1]["hash"] == old["content_hash"]
    assert row.content["version_history"][-1]["logical_path"] == longpath
    assert (
        bridge.independent.require(owner, feedback["document_id"]).version_hash
        == feedback["content_hash"]
    )


async def test_review_ambiguous_exact_bytes(ui, parsed_locally):
    first = await upload(ui, [("left.txt", "same"), ("right.txt", "same")], "first")
    review = await upload(ui, [("moved.txt", "same")], "review", commit=False)
    item = review["items"][0]
    assert item["disposition"] == "ambiguous"
    target = first["items"][0]["document_id"]
    assert target in item["candidates"]
    result = await upload(ui, [("moved.txt", "same")], "chosen", decisions={"moved.txt": target})
    assert result["items"][0]["document_id"] == target


async def test_recover_incremental_selection(ui, bridge, owner, parsed_locally):
    detail = b"Feedback describes the design."
    expected = {"feedback.md": sha256(detail).hexdigest(), "original-case.md": None}
    available = [("brief.md", "Memo due Nov 2.")]
    dropout = await upload(ui, available, "dropout", expected=expected)
    assert all(m["retained_version"] is None for m in dropout["coverage"]["missing"])
    wrong = await upload(ui, [("feedback.md", "unrelated")], "wrong", expected=expected)
    assert wrong["items"][0]["state"] == "failed"
    recovered = await upload(ui, [("feedback.md", detail)], "recovered", expected=expected)
    assert recovered["items"][0]["content_hash"] == expected["feedback.md"]
    partial = await upload(ui, available, "partial", expected=expected)
    assert partial["coverage"]["missing"][0]["retained_version"] == expected["feedback.md"]
    assert bridge.independent.require(owner, recovered["items"][0]["document_id"])


@pytest.fixture
def paired(settings, tmp_path):
    from tests.conftest import bridge as build

    path = tmp_path / "live-authority.sqlite"
    source_settings = settings.model_copy(
        update={
            "database_url": "sqlite:///" + path.as_posix(),
            "usefulness_features_enabled": True,
            "process_features_enabled": True,
        }
    )
    destination_settings = settings.model_copy(
        update={
            "portability_origin_sqlite": path,
            "database_url": "sqlite:///" + (tmp_path / "destination.sqlite").as_posix(),
            "usefulness_features_enabled": True,
            "process_features_enabled": True,
        }
    )
    sources = build.__wrapped__(source_settings)
    destinations = build.__wrapped__(destination_settings)
    try:
        yield next(sources), next(destinations)
    finally:
        sources.close()
        destinations.close()


async def test_paired_workspace_roundtrip_and_revocation(
    paired, owner, parsed_locally, monkeypatch
):
    from canvas_bridge.domain import DomainError
    from canvas_bridge.storage import IndependentResource
    from canvas_bridge.usefulness.workspace import Workspace
    from canvas_bridge.usefulness.workspace_package import unpack
    from tests.test_usefulness import import_text, reviewed

    source, dest = paired
    doc = await import_text(source, owner, "Memo due November 2, 2026.", course="MKT")
    review = reviewed(source, owner, doc)
    source.independent.preferences(owner, {"timezone": "UTC"})
    raw = Workspace(source).export(
        owner, "MKT", [review["record_id"]], [], originals=True, preferences=True
    )
    manifest, docs, recs, payloads = unpack(raw, owner)
    assert payloads[doc.version_hash] == b"Memo due November 2, 2026."
    api = Workspace(dest)
    plan = api.restore(owner, raw, generation=0)
    assert plan["history_authority"] == "paired_live_sqlite"
    assert plan["source_id_map"] == {doc.id: doc.id}
    assert plan["preferences"]["action"] == "create"
    assert plan["records"][recs[0].id]["action"] == "create"
    with pytest.raises(RuntimeError), monkeypatch.context() as scoped:

        def interrupt(*args, **kwargs):
            raise RuntimeError("injected before transaction commit")

        scoped.setattr(api.repo, "_save", interrupt)
        api.restore(owner, raw, generation=0, confirmation=plan["preview_id"], key="same")
    assert dest.independent.list(owner).data["documents"] == []
    done = api.restore(owner, raw, generation=0, confirmation=plan["preview_id"], key="same")
    assert done["status"] == "complete"
    assert done["history_authority"] == plan["history_authority"]
    assert done["outcomes"]["records"] == plan["records"]
    assert (
        api.restore(owner, raw, generation=0, confirmation=plan["preview_id"], key="same") == done
    )
    restored = dest.independent.require(owner, doc.id)
    assert not restored.provenance["share_text"]
    assert (
        restored.content["reviewed_dataset"]
        == source.independent.require(owner, doc.id).content["reviewed_dataset"]
    )
    assert dest.independent.preferences(owner).data["value"]["timezone"] == "UTC"
    with dest.store.transaction() as db:
        container = db.get(IndependentResource, api.repo.identity(owner))
        assert container.expires_at.replace(tzinfo=None) == timestamp_for_test(
            manifest["retention"]["expires_at"]
        )
    source.independent.delete(owner, doc.id)
    assert api.restore(owner, raw, generation=0)["documents"][doc.id]["action"] == "blocked"
    with pytest.raises(DomainError):
        dest.independent.require(owner, doc.id)


def timestamp_for_test(value):
    from datetime import datetime

    return datetime.fromisoformat(value).replace(tzinfo=None)


async def test_reject_malformed_workspace_before_commit(paired, owner):
    from canvas_bridge.domain import DomainError
    from canvas_bridge.usefulness.workspace import Workspace
    from canvas_bridge.usefulness.workspace_package import MANIFEST_LIMIT, pack, unpack
    from tests.test_usefulness import goal

    origin, dest = paired
    ident = goal(origin, owner)
    raw = Workspace(origin).export(owner, "biology", [ident], [])
    manifest, _, _, payloads = unpack(raw, owner)
    process = manifest["process"]
    record = process["records"][0]
    variants = [
        (pack(manifest | {"export_id": []}, payloads), "PORT_PACKAGE_INVALID"),
        (pack(manifest | {"generation": False}, payloads), "PORT_PACKAGE_INVALID"),
        (archive([("/manifest.json", "{}")]), "PORT_PACKAGE_INVALID"),
        (archive([("manifest.json", b"x" * (MANIFEST_LIMIT + 1))]), "PORT_PACKAGE_INVALID"),
        (
            pack(manifest | {"process": process | {"records": [record, record]}}, payloads),
            "PROCESS_SCOPE_MISMATCH",
        ),
        (
            pack(
                manifest | {"process": process | {"records": [record | {"kind": "future_kind"}]}},
                payloads,
            ),
            "PROCESS_EXPORT_SCHEMA_UNSUPPORTED",
        ),
    ]
    for damaged, reason in variants:
        with pytest.raises(DomainError) as error:
            Workspace(dest).restore(owner, damaged, generation=0)
        assert error.value.reason_code == reason
    assert not dest.processes.repository.inventory(owner)["records"]


async def test_original_container_expiry_and_owner_generation(paired, owner, monkeypatch):
    from datetime import timedelta

    from canvas_bridge.domain import DomainError
    from canvas_bridge.storage import IndependentResource, PrincipalState
    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import goal

    origin, dest = paired
    ident = goal(origin, owner)
    now = origin.retention.clock()
    with origin.store.transaction() as session:
        container = session.get(IndependentResource, origin.processes.repository.identity(owner))
        container.created_at = now - timedelta(days=25)
        container.expires_at = now + timedelta(minutes=1)
    raw = Workspace(origin).export(owner, "biology", [ident], [])
    api = Workspace(dest)
    assert api.restore(owner, raw, generation=0)["records"][ident]["action"] == "create"
    with monkeypatch.context() as shifted:
        shifted.setattr(dest.retention, "clock", lambda: now + timedelta(minutes=2))
        assert (
            api.restore(owner, raw, generation=0)["records"][ident]["action"]
            == "blocked_expired_or_deleted"
        )
    with origin.store.transaction() as session:
        session.get(PrincipalState, owner).generation += 1
    with pytest.raises(DomainError) as error:
        api.restore(owner, raw, generation=0)
    assert error.value.reason_code == "PORT_AUTHORITY_UNAVAILABLE"
    assert not dest.processes.repository.inventory(owner)["records"]


async def test_destination_conflicts_and_stale_preview(paired, owner, parsed_locally):
    from canvas_bridge.domain import DomainError
    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import goal

    source, dest = paired
    goal_id = goal(source, owner, course="MKT", share=False)
    raw = Workspace(source).export(owner, "MKT", [goal_id], [])
    api = Workspace(dest)
    preview = api.restore(owner, raw, generation=0)
    api.restore(owner, raw, generation=0, confirmation=preview["preview_id"], key="first")
    dest.usefulness.records.save(
        owner,
        "MKT",
        "goal",
        {"concept": "different"},
        record_id=goal_id,
        expected_revision=1,
        idempotency_key="local-edit",
    )
    assert api.restore(owner, raw, generation=0)["records"][goal_id]["action"] == "conflict"
    replace = api.restore(owner, raw, generation=0, choices=[goal_id])
    assert replace["records"][goal_id]["destination_revision"] == 2
    goal(dest, owner, course="FIN", share=False)
    with pytest.raises(DomainError, match="destination"):
        api.restore(
            owner,
            raw,
            generation=0,
            choices=[goal_id],
            confirmation=replace["preview_id"],
            key="race",
        )
    replace = api.restore(owner, raw, generation=0, choices=[goal_id])
    api.restore(
        owner, raw, generation=0, choices=[goal_id], confirmation=replace["preview_id"], key="final"
    )
    assert dest.processes.repository.read(owner, goal_id).revision == 3


async def test_workspace_browser_and_missing_authority(ui, owner, bridge):
    from canvas_bridge.domain import DomainError
    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import goal

    ident = goal(bridge, owner)
    download = await ui.post(
        "/settings/materials/workspace/export",
        data={"csrf": "usefulness-csrf", "course": "biology", "record": ident},
    )
    assert download.status_code == 200
    review = await ui.post(
        "/settings/materials/workspace/preview",
        data={"csrf": "usefulness-csrf"},
        files={"bundle": ("course.cbworkspace", download.content)},
    )
    assert review.status_code == 200 and "Confirm eligible changes" in review.text
    assert "verified against this installation" in review.text
    with pytest.raises(DomainError):
        Workspace(bridge).restore("foreign", download.content, generation=0)
    for bad in [archive([("../manifest.json", "{}")]), b"invalid"]:
        with pytest.raises(DomainError):
            Workspace(bridge).restore(owner, bad, generation=0)


async def test_reviewed_mixed_assignment_projection(bridge, owner, seeded, parsed_locally, ui):
    from datetime import timedelta

    from canvas_bridge.processes.requests import EvaluationRequest, SaveRequest
    from tests.test_usefulness import import_text, reviewed

    now = bridge.retention.clock()
    workload = await bridge.workload(owner, seeded, now, now + timedelta(days=7), "UTC")
    item = workload.data["items"][0]
    doc = await import_text(bridge, owner, "A separate brief due November 2, 2026.", course="MKT")
    reviewed(bridge, owner, doc)
    scope = {
        "document_ids": [doc.id],
        "local_course": "MKT",
        "connection_id": seeded,
        "course_id": item["course_id"],
        "resource_ids": [item["id"]],
        "term": "fall",
    }
    local = {
        "source_id": doc.id,
        "provider": "manual",
        "external_id": "paper",
        "kind": "assignment",
        "term": "fall",
        "institution": "ignored-caller-label",
        "course_code": "MKT",
    }
    remote = local | {"source_id": item["id"], "provider": "canvas", "external_id": item["id"]}
    request = EvaluationRequest.model_validate(
        {
            "scope": scope,
            "payload": {
                "operation": "identity",
                "associate_local_course": True,
                "left": local,
                "right": remote,
            },
        }
    )
    before = await bridge.processes.evaluate(owner, request)
    assert len(before.data["canonical_inventory"]) == 2
    link = before.data["canonical_link_proposal"]
    assert len({a["scope"]["institution"] for a in link["aliases"]}) == 2
    propose = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="mixed")
    )
    await bridge.processes.confirm(owner, propose.data["preview_id"], True, "confirm-mixed")
    confirmed = await bridge.processes.evaluate(owner, request)
    assert len(confirmed.data["canonical_inventory"]) == 1
    parent = confirmed.data["reviewed_parent"]
    assert len(parent["deadline_assertions"]) == 2 and parent["assignment_id"] == item["id"]
    current = request.model_dump(mode="json")
    current["payload"]["calendar"] = dict(
        calendar_id="synthetic",
        timezone="UTC",
        retrieved_at=now,
        window_start=now,
        window_end=now + timedelta(days=7),
        pagination_complete=True,
        mapping_search_complete=True,
        events=[],
    )
    projected = await bridge.processes.evaluate(owner, EvaluationRequest.model_validate(current))
    assert projected.data["reviewed_parent"]["calendar_projection"]["proposal_count"] <= 1
    from canvas_bridge.usefulness.workspace_package import unpack

    download = await ui.post(
        "/settings/materials/workspace/export",
        data={"csrf": "usefulness-csrf", "course": "MKT", "record": "mixed"},
    )
    assert download.status_code == 200
    manifest, _, exported, _ = unpack(download.content, owner)
    assert exported and exported[0].id == "mixed", manifest["omitted"]
    from canvas_bridge.usefulness.workspace import Workspace

    assert (
        Workspace(bridge).restore(owner, download.content, generation=0)["records"]["mixed"][
            "action"
        ]
        == "reuse"
    )
    remove = bridge.processes.recovery_preview(owner, record_id="mixed")
    await bridge.processes.confirm(owner, remove.data["preview_id"], True, "unlink")
    assert len((await bridge.processes.evaluate(owner, request)).data["canonical_inventory"]) == 2
    bridge.store.disconnect(owner, seeded)
    partial = await bridge.processes.evaluate(owner, request)
    assert partial.status == "partial_data" and [s.id for s in partial.sources] == [doc.id]
    assert bridge.independent.require(owner, doc.id)


async def test_packet_validation_and_historical_progress(ui, bridge, owner, parsed_locally):
    from canvas_bridge.usefulness.imports import candidates

    unsafe = await upload(
        ui, [("café.md", "one"), ("cafe\u0301.md", "two")], "collision", commit=False
    )
    assert unsafe["state"] == "rejected" and len(unsafe["items"]) == 2
    first = await upload(ui, [("assignment.md", "Memo must contain two tables.")], "first")
    doc = first["items"][0]["document_id"]
    source = bridge.independent.require(owner, doc)

    def decide(row, progress, revision):
        item = candidates(row)[0]
        return bridge.usefulness.save_review(
            owner,
            doc,
            row.version_hash,
            {
                item["id"]: {
                    "action": "edit",
                    "work": {
                        "key": "memo",
                        "title": "Memo",
                        "progress": progress,
                        "revision_requested": revision,
                    },
                }
            },
            expected_revision=0 if not revision else stale.revision,
            key="review2" if revision else "review1",
        )

    first_review = decide(source, "student_marked_done", False)
    revised = await upload(ui, [("assignment.md", "Memo must contain three tables.")], "revised")
    assert revised["items"][0]["document_id"] == doc
    stale = bridge.usefulness.records.state(owner).records[first_review["record_id"]]
    assert (
        stale.state == "stale"
        and stale.data["value"]["dataset"]["work"][0]["progress"] == "student_marked_done"
    )
    result = decide(bridge.independent.require(owner, doc), "student_marked_done", True)
    assert result["record_id"] == stale.id
    current = bridge.processes.repository.read(owner, result["record_id"])
    assert current.data["value"]["dataset"]["work"][0]["revision_requested"]


async def test_reference_remap_and_missing_parent(paired, owner, parsed_locally):
    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import reviewed

    source, dest = paired
    data = archive([("brief.md", "Memo due November 2, 2026.")])

    async def acquire_app(app):
        result = await app.usefulness.imports.run(
            owner,
            data,
            "test.zip",
            "application/zip",
            course="MKT",
            purpose="material",
            key="baseline",
            permissions={"own_material": True},
            validate_session=lambda: 0,
        )
        return app.independent.require(owner, result["items"][0]["document_id"])

    src = await acquire_app(source)
    review = reviewed(source, owner, src, key="memo")["record_id"]
    tag = source.usefulness.records.document_tag(owner, src)
    child = source.usefulness.records.save(
        owner,
        "MKT",
        "task",
        {
            "title": "Prepare",
            "minutes": 0,
            "finished": False,
            "grade": None,
            "submission": "unknown",
        },
        sources=[tag],
        depends_on=[review],
        idempotency_key="manual",
    )["record_id"]
    raw = Workspace(source).export(owner, "MKT", [child], [], originals=False)
    api = Workspace(dest)
    missing = api.restore(owner, raw, generation=0)
    assert missing["records"][child]["action"] == "unresolved_dependency"
    assert missing["documents"][src.id]["reason"] == "PORT_REFERENCE_UNRESOLVED"
    dst = await acquire_app(dest)
    assert src.id != dst.id
    mapped = api.restore(owner, raw, generation=0)
    assert mapped["source_id_map"] == {src.id: dst.id}
    assert mapped["records"][review]["action"] == "create"
    api.restore(owner, raw, generation=0, confirmation=mapped["preview_id"], key="mapped")
    read = dest.processes.repository.read(owner, review)
    assert read.sources[0].id == dst.id
    assert read.data["value"]["dataset"]["work"][0]["evidence"][0]["document_id"] == dst.id
    assert (
        dest.independent.require(owner, dst.id).content["reviewed_dataset"]["work"][0]["key"]
        == "memo"
    )
    source.independent.delete(owner, src.id)
    deleted = api.restore(owner, raw, generation=0)
    assert deleted["documents"][src.id]["action"] == "blocked"
    assert src.id not in deleted["source_id_map"]
    assert dest.independent.require(owner, dst.id).id == dst.id


async def test_workspace_tampering_expiry_and_trusted_history(
    paired, owner, parsed_locally, monkeypatch, tmp_path
):
    from datetime import timedelta

    from canvas_bridge.domain import DomainError
    from canvas_bridge.usefulness.workspace import Workspace
    from canvas_bridge.usefulness.workspace_package import pack, unpack
    from tests.test_usefulness import import_text

    source, dest = paired
    doc = await import_text(source, owner, "Sample", course="MKT")
    raw = Workspace(source).export(owner, "MKT", [], [doc.id], originals=True)
    manifest, _, _, payloads = unpack(raw, owner)
    api = Workspace(dest)
    wrong = pack(manifest | {"schema_version": "course-workspace-99"}, payloads)
    with pytest.raises(DomainError) as err:
        api.restore(owner, wrong, generation=0)
    assert err.value.reason_code == "PORT_SCHEMA_UNSUPPORTED"
    forged = pack(manifest | {"course": "different"}, payloads)
    with pytest.raises(DomainError) as err:
        api.restore(owner, forged, generation=0)
    assert err.value.reason_code == "PORT_AUTHORITY_UNAVAILABLE"
    for damaged in [raw[: len(raw) // 2], pack(manifest, {doc.version_hash: b"tampered"})]:
        with pytest.raises(DomainError) as err:
            api.restore(owner, damaged, generation=0)
        assert err.value.reason_code == "PORT_PACKAGE_INVALID"
    with monkeypatch.context() as m:
        m.setattr(dest.settings, "portability_origin_sqlite", tmp_path / "unavailable.sqlite")
        with pytest.raises(DomainError) as err:
            api.restore(owner, raw, generation=0)
        assert err.value.reason_code == "PORT_AUTHORITY_UNAVAILABLE"
    review = api.restore(owner, raw, generation=0)
    with monkeypatch.context() as m:
        clock = dest.retention.clock() + timedelta(minutes=16)
        m.setattr(dest.retention, "clock", lambda: clock)
        with pytest.raises(DomainError) as err:
            api.restore(owner, raw, generation=0, confirmation=review["preview_id"], key="expired")
        assert err.value.reason_code == "PORT_PREVIEW_CHANGED"
    source.independent.delete(owner, doc.id)
    with pytest.raises(DomainError):
        api.restore(owner, raw, generation=0, confirmation=review["preview_id"], key="revoked")
    assert not dest.independent.list(owner).data["documents"]


@pytest.fixture(autouse=True)
def capture_portability_receipts(monkeypatch, request):
    """Optional synthetic execution evidence, excluding session and confirmation credentials."""
    import os
    from pathlib import Path

    from canvas_bridge.processes.service import ProcessService
    from canvas_bridge.usefulness.imports import Imports
    from canvas_bridge.usefulness.workspace import Workspace
    from canvas_bridge.usefulness.workspace_package import unpack

    folder = os.environ.get("BRIDGE_TEST_PORT_OUTPUT")
    if not folder:
        yield
        return
    events = []

    def safe(value):
        if isinstance(value, dict):
            return {
                k: (
                    "digest:" + sha256(str(v).encode()).hexdigest()
                    if k in {"preview_id", "confirmation"}
                    else safe(v)
                )
                for k, v in value.items()
                if k not in {"csrf", "key", "attempt", "validate_session"}
            }
        if isinstance(value, (list, tuple)):
            return [safe(v) for v in value]
        if hasattr(value, "model_dump"):
            return safe(value.model_dump(mode="json"))
        return value

    export, restore, acquire, evaluate = (
        Workspace.export,
        Workspace.restore,
        Imports.run,
        ProcessService.evaluate,
    )

    def capture_export(self, owner, course, ids, docs, **options):
        raw = export(self, owner, course, ids, docs, **options)
        manifest, _, _, _ = unpack(raw, owner)
        events.append(
            {
                "operation": "export",
                "course": course,
                "selection": [ids, docs],
                "manifest": manifest,
                "bundle_sha256": sha256(raw).hexdigest(),
            }
        )
        return raw

    def capture_restore(self, owner, raw, **options):
        event = {
            "operation": "restore",
            "request": options,
            "bundle_sha256": sha256(raw).hexdigest(),
        }
        events.append(event)
        try:
            event["response"] = restore(self, owner, raw, **options)
            return event["response"]
        except Exception as exc:
            event["error"] = getattr(exc, "reason_code", None) or type(exc).__name__
            raise

    async def capture_import(self, owner, data, filename, mime, **options):
        result = await acquire(self, owner, data, filename, mime, **options)
        events.append(
            {
                "operation": "import",
                "archive_sha256": sha256(data).hexdigest(),
                "request": options,
                "response": result,
            }
        )
        return result

    async def capture_evaluate(self, owner, evaluation):
        result = await evaluate(self, owner, evaluation)
        events.append({"operation": "evaluate", "request": evaluation, "response": result})
        return result

    monkeypatch.setattr(Workspace, "export", capture_export)
    monkeypatch.setattr(Workspace, "restore", capture_restore)
    monkeypatch.setattr(Imports, "run", capture_import)
    monkeypatch.setattr(ProcessService, "evaluate", capture_evaluate)
    yield
    output = Path(folder)
    output.mkdir(parents=True, exist_ok=True)
    (output / (request.node.name + ".json")).write_text(
        json.dumps(safe(events), indent=2, default=str), encoding="utf8"
    )


async def test_typed_state_and_dependency_closure(paired, owner, parsed_locally):
    import base64

    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import attempt_value, goal, import_text

    src, dest = paired
    parent = goal(src, owner, "MKT", share=False)
    child = src.usefulness.save_attempt(
        owner, "MKT", attempt_value(parent), key="explicit-attempt", share=False
    )["record_id"]
    typed = {
        "schema_version": "independent-academic-1",
        "complete": False,
        "timezone": None,
        "work": [],
        "grades": {
            "complete": False,
            "assessments": [
                {"key": "entered-zero", "score": 0, "possible": 10},
                {"key": "unknown-score", "score": None},
                {"key": "absent-score"},
            ],
        },
    }
    material = await import_text(src, owner, json.dumps(typed), course="MKT")
    raw = Workspace(src).export(owner, "MKT", [child], [material.id], originals=True)
    api = Workspace(dest)
    plan = api.restore(owner, raw, generation=0)
    assert set(plan["record_id_map"]) == {parent, child}
    api.restore(owner, raw, generation=0, confirmation=plan["preview_id"], key="typed")
    read = dest.processes.repository.read(owner, child)
    original = src.processes.repository.read(owner, child)
    assert read.data["value"] == original.data["value"]
    assert (
        read.depends_on == (parent,)
        and read.sources == original.sources
        and read.updated_at == original.updated_at
    )
    actual = json.loads(
        base64.b64decode(dest.independent.require(owner, material.id).content["bytes"])
    )
    assert actual == typed
    assert actual["complete"] is False and actual["timezone"] is None
    a, b, c = actual["grades"]["assessments"]
    assert type(a["score"]) is int and a["score"] == 0 and b["score"] is None and "score" not in c
    dest.usefulness.records.delete(owner, parent, 1)
    blocked = api.restore(owner, raw, generation=0)
    assert blocked["records"][parent]["action"] == "blocked_deleted_record"
    assert blocked["records"][child]["action"] in {
        "blocked_deleted_record",
        "unresolved_dependency",
    }


def test_concurrent_restore_receipt(paired, owner):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import goal

    source, dest = paired
    ident = goal(source, owner, "MKT", share=False)
    raw = Workspace(source).export(owner, "MKT", [ident], [])
    api = Workspace(dest)
    plan = api.restore(owner, raw, generation=0)
    start = Barrier(2)

    def confirm():
        start.wait(timeout=10)
        return api.restore(
            owner, raw, generation=0, confirmation=plan["preview_id"], key="concurrent"
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        tasks = [workers.submit(confirm) for _ in range(2)]
        receipts = [future.result(timeout=20) for future in tasks]
    assert receipts[0] == receipts[1] and receipts[0]["record_count"] == 1
    assert dest.processes.repository.read(owner, ident).revision == 1


async def test_independent_destination_review_is_preserved(paired, owner, parsed_locally):
    from canvas_bridge.usefulness.workspace import Workspace
    from tests.test_usefulness import reviewed

    source, dest = paired
    data = archive([("brief.md", "Memo due November 2, 2026.")])
    rows = []
    for app in (source, dest):
        receipt = await app.usefulness.imports.run(
            owner,
            data,
            "test.zip",
            "application/zip",
            course="MKT",
            purpose="material",
            key="packet",
            permissions={"own_material": True},
            validate_session=lambda: 0,
        )
        doc = app.independent.require(owner, receipt["items"][0]["document_id"])
        rows.append((doc, reviewed(app, owner, doc, key="memo")["record_id"]))
    (src, origin_review), (dst, destination_review) = rows
    raw = Workspace(source).export(owner, "MKT", [origin_review], [src.id])
    api = Workspace(dest)
    proposed = api.restore(owner, raw, generation=0)
    assert proposed["records"][origin_review]["action"] == "unresolved_destination_review"
    receipt = api.restore(
        owner, raw, generation=0, confirmation=proposed["preview_id"], key="preserve"
    )
    assert receipt["status"] == "partial"
    assert (
        dest.independent.require(owner, dst.id).content["review"]["record_id"] == destination_review
    )
