"""Opt-in execution of the supplied synthetic Stage 4 course and semester packets."""

import io
import json
import os
import platform
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from canvas_bridge.academic.study_steps import source_steps
from canvas_bridge.usefulness.imports import candidates
from canvas_bridge.usefulness.workspace import Workspace
from tests.test_academic_operations_acceptance import build_identity
from tests.test_content_portability import archive
from tests.test_content_portability import paired as paired

pytestmark = pytest.mark.skipif(
    not os.getenv("BRIDGE_TEST_PORT_SUITE"), reason="requires supplied Stage 4 synthetic archive"
)


@pytest.fixture
def rig(paired, owner, tmp_path, monkeypatch):
    bundle = Path(os.environ["BRIDGE_TEST_PORT_SUITE"])
    assert (
        sha256(bundle.read_bytes()).hexdigest()
        == "e91dc8bb1c5c1cf660155d087cab62057702b0bc02622f43815d47614ac0935f"
    )
    inputs = zipfile.ZipFile(bundle)
    root = "stage4_portability/"
    output = Path(os.environ.get("BRIDGE_TEST_PORT_OUTPUT", tmp_path / "receipts"))
    output.mkdir(parents=True, exist_ok=True)
    clock = datetime(2026, 10, 29, 16, tzinfo=UTC)
    for bridge in paired:
        bridge.settings.file_reading_enabled = True
        if os.name == "nt":
            parser = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
            bridge.settings.parser_root = bridge.settings.parser_runtime_root = parser
        monkeypatch.setattr(bridge.retention, "clock", lambda: clock)

    def save(name, value):
        (output / (name + ".json")).write_text(
            json.dumps(value, indent=2, default=str), encoding="utf8"
        )

    build = build_identity()
    save(
        "environment",
        {
            "base_commit": build["base_commit"],
            "source_sha256": build["source_sha256"],
            "runtime": platform.python_version(),
            "clock": clock.isoformat(),
            "profile": "synthetic",
            "principal": owner,
            "recipient": "authenticated_settings_owner",
            "authority": "paired_live_sqlite",
        },
    )

    def fixture(name):
        return inputs.read(root + "fixtures/" + name)

    async def acquire(bridge, name, data, *, course="MKT320", expected=None, decisions=None):
        args = dict(
            course=course,
            purpose="material",
            key=name,
            term="fall26",
            expected=expected,
            decisions=decisions,
            permissions={"own_material": True, "share_text": True, "allow_academic_analysis": True},
            validate_session=lambda: 0,
        )
        service = bridge.usefulness.imports
        pre = await service.run(
            owner, data, "selection.zip", "application/zip", preview_only=True, **args
        )
        result = await service.run(
            owner, data, "selection.zip", "application/zip", confirmation=pre["preview_id"], **args
        )
        save(
            name,
            {
                "request": {
                    "scope": course,
                    "term": "fall26",
                    "hash": sha256(data).hexdigest(),
                    "expected": expected,
                    "decisions": decisions,
                },
                "preview": pre,
                "result": result,
            },
        )
        return result

    yield *paired, fixture, acquire, save
    inputs.close()


async def test_exact_course_sequence(rig, owner, token_factory, monkeypatch):
    source, dest, fixture, acquire, save = rig
    missing = {"course/MKT320-C01.md": None}
    base = await acquire(source, "baseline", fixture("base.zip"), expected=missing)
    by_path = {i["logical_path"]: i for i in base["items"]}
    brief = by_path["course/MKT320-A05.md"]
    assert brief["state"] == "ready", brief
    row = source.independent.require(owner, brief["document_id"])
    paragraphs = row.content["parsed"]["pages"]
    parts = [
        {"text": p["text"], "locator": "Page " + str(i), "kind": "page", "ordinal": i}
        for i, p in enumerate(paragraphs, 1)
    ]
    document = {
        "id": row.id,
        "role": "instructions",
        "parts": parts,
        "content_hash": row.version_hash,
        "title": "MKT320-A05",
        "version": row.version_hash,
        "source_version": row.version_hash,
        "url": "",
        "course_id": "MKT320",
        "source_type": "local_document",
        "retrieved_at": row.provenance["acquired_at"],
        "complete": bool(paragraphs),
    }
    evidence = source_steps([document])
    assert len([s for s in evidence["steps"] if s["kind"] == "deliverable"]) == 3
    save("baseline-evidence", {"steps": evidence, "coverage": base["coverage"]})
    matches = candidates(row)
    assert matches
    selected = next(c for c in matches if "November 2 at 23:59 America/New_York" in c["quote"])
    review = source.usefulness.save_review(
        owner,
        row.id,
        row.version_hash,
        {
            selected["id"]: {
                "action": "edit",
                "work": {
                    "key": "MKT320-A05",
                    "title": "Research Decision Memo",
                    "activity_kind": "assignment",
                    "progress": "in_progress",
                    "due": {"kind": "timestamp", "timestamp": "2026-11-02T23:59:00-05:00"},
                    "requirement": "required",
                },
            }
        },
        key="explicit-personal-progress",
    )
    source.independent.preferences(owner, {"timezone": "America/New_York"})
    save(
        "progress",
        {
            "receipt": review,
            "record": source.processes.repository.read(owner, review["record_id"]).model_dump(
                mode="json"
            ),
        },
    )
    for name in ("moved", "duplicate", "longpaths"):
        result = await acquire(source, name, fixture(name + ".zip"), expected=missing)
        originals = {
            i["content_hash"]: i["binding"] for i in base["items"] if i["state"] == "ready"
        }
        assert all(
            i["binding"] == originals[i["content_hash"]]
            for i in result["items"]
            if i["state"] == "ready" and i["content_hash"] in originals
        )
    with zipfile.ZipFile(io.BytesIO(fixture("base.zip"))) as original:
        reversed_zip = archive([(n, original.read(n)) for n in reversed(original.namelist())])
    reordered = await acquire(source, "reordered", reversed_zip)
    assert {i["binding"] for i in reordered["items"]} == {i["binding"] for i in base["items"]}
    revision = await acquire(source, "revised", fixture("revised.zip"))
    notice = next(i for i in revision["items"] if i["logical_path"].endswith("N01.md"))
    assert notice["state"] == "ready" and notice["disposition"] == "new_version"
    amended = source.independent.require(owner, notice["document_id"])
    save(
        "competing-deadlines",
        {
            "assertions": [
                {
                    "source": r.id,
                    "version": r.version_hash,
                    "passages": [
                        line
                        for p in r.content["parsed"]["pages"]
                        for line in p["text"].splitlines()
                        if "November 2" in line or "November 4" in line
                    ],
                }
                for r in (row, amended)
            ]
        },
    )
    from canvas_bridge.processes.requests import EvaluationRequest

    conflicts = await source.processes.evaluate(
        owner,
        EvaluationRequest.model_validate(
            {
                "scope": {
                    "document_ids": [row.id, amended.id],
                    "local_course": "MKT320",
                    "term": "fall26",
                },
                "payload": {
                    "operation": "evidence",
                    "decision_class": "deadline",
                    "claims": [
                        {
                            "source_id": r.id,
                            "entity": "MKT320-A05",
                            "field": "deadline",
                            "value": date,
                        }
                        for r, date in ((row, "November 2"), (amended, "November 4"))
                    ],
                },
            }
        ),
    )
    assert conflicts.data["resolution"]["status"] == "unresolved"
    assert len(conflicts.data["resolution"]["candidates"]) == 2
    save("unresolved-deadline", conflicts.model_dump(mode="json"))
    done = [i["document_id"] for i in revision["items"] if i["state"] == "ready"]
    raw = Workspace(source).export(
        owner, "MKT320", [review["record_id"]], done, originals=True, preferences=True
    )
    api = Workspace(dest)
    preview = api.restore(owner, raw, generation=0)
    save("clean-restore-preview", preview)
    references = {
        ident
        for ident, item in preview["documents"].items()
        if item.get("reason") == "PORT_REFERENCE_UNRESOLVED"
    }
    if references:
        # A separate authenticated acquisition supplies original fixture bytes for reference-only sources.
        with zipfile.ZipFile(io.BytesIO(fixture("revised.zip"))) as original:
            needed = [
                (i["logical_path"], original.read(i["logical_path"]))
                for i in revision["items"]
                if i["document_id"] in references
            ]
        await acquire(dest, "destination-selected-references", archive(needed))
        preview = api.restore(owner, raw, generation=0)
    save("restore-preview", preview)
    receipt = api.restore(
        owner, raw, generation=0, confirmation=preview["preview_id"], key="roundtrip"
    )
    save("restore-receipt", receipt)
    assert receipt["status"] == "complete", receipt
    restored = dest.independent.require(owner, row.id)
    assert restored.content["reviewed_dataset"]["work"][0]["progress"] == "in_progress"
    assert restored.version_hash == row.version_hash
    for ident in done:
        assert (
            dest.independent.require(owner, preview["source_id_map"][ident]).version_hash
            == source.independent.require(owner, ident).version_hash
        )
    assert (
        api.restore(owner, raw, generation=0, confirmation=preview["preview_id"], key="roundtrip")
        == receipt
    )

    from canvas_bridge.usefulness.service import scoped_work_id

    oldplan = source.usefulness.records.save(
        owner,
        "MKT320",
        "plan",
        {
            "blocks": [
                {
                    "work_id": scoped_work_id(row.id, "MKT320-A05"),
                    "start": "2026-10-29T16:00:00Z",
                    "end": "2026-10-29T16:30:00Z",
                }
            ],
            "calendar_action": False,
        },
        depends_on=[review["record_id"]],
        sources=[source.usefulness.records.document_tag(owner, row)],
        idempotency_key="saved-plan",
    )
    historical = Workspace(source).export(
        owner, "MKT320", [oldplan["record_id"]], [], originals=False
    )
    handoff = api.restore(owner, historical, generation=0)
    assert handoff["records"][oldplan["record_id"]]["action"] == "historical_replan_required"
    save("historical-plan", handoff)

    # Explicitly permit the destination recipient before exercising academic analysis.
    from datetime import timedelta

    import httpx

    from canvas_bridge.academic.independent_engine import work_items
    from canvas_bridge.academic.independent_models import (
        IndependentAcademicInput,
        IndependentRequest,
    )
    from canvas_bridge.app import create_app
    from canvas_bridge.authorization import RequestAuthorization, request_authorization
    from canvas_bridge.calendar_sync import marker
    from canvas_bridge.egress_models import RecipientIdentity
    from canvas_bridge.independent_intelligence import run
    from tests.test_usefulness import browser_session

    browser_session(dest, owner, token_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(dest.settings, dest)),
        base_url=dest.settings.resource_url,
        cookies={"bridge_session": "usefulness-browser"},
        headers={"Origin": dest.settings.resource_url},
    ) as browser:
        saved = await browser.post(
            "/settings/materials/sharing",
            data={
                "csrf": "usefulness-csrf",
                "document_id": row.id,
                "expected_hash": row.version_hash,
                "permission_version": "0",
                "confirm": "reviewed",
                "share": "yes",
                "analysis": "yes",
                "primary_review": dest.independent.profile().review_digest(),
            },
        )
        assert saved.status_code == 303, saved.text
    instant = dest.retention.clock() + timedelta(hours=2)
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: instant)
    dataset = IndependentAcademicInput.model_validate(restored.content["reviewed_dataset"])
    parent = work_items(dataset, dest.independent.evidence(restored))[0]
    event = {
        "id": "fictional-current-event",
        "title": parent.title,
        "bridge_marker": marker(owner, "", parent),
        "start": parent.effective_due.timestamp,
        "end": parent.effective_due.timestamp + timedelta(minutes=15),
        "status": "confirmed",
        "version": "current-calendar-readback",
    }
    calendar = {
        "calendar_id": "fictional-calendar",
        "timezone": "America/New_York",
        "events": [event],
        "retrieved_at": instant,
        "window_start": instant,
        "window_end": instant + timedelta(days=7),
        "pagination_complete": True,
        "mapping_search_complete": True,
    }
    context = request_authorization.set(
        RequestAuthorization(
            "portability-test", recipient="chatgpt", egress_identity=RecipientIdentity("chatgpt")
        )
    )
    try:
        for capability, options in [
            ("calendar", {"calendar": calendar}),
            (
                "planning",
                {"plan": {"windows": [{"start": instant, "end": instant + timedelta(minutes=45)}]}},
            ),
        ]:
            request = IndependentRequest.model_validate(
                {
                    "capability": capability,
                    "dataset": {"document_id": restored.id, "expected_hash": restored.version_hash},
                    **options,
                }
            )
            result = await run(dest, owner, request)
            save(
                "current-" + capability,
                {
                    "request": request.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
            )
            if capability == "calendar":
                assert not result.data["proposals"] and len(result.data["mappings"]) == 1
                assert result.data["provider_writes_executed"] is False
    finally:
        request_authorization.reset(context)


async def test_exact_dropout(rig, owner):
    source, _, fixture, acquire, save = rig
    with zipfile.ZipFile(io.BytesIO(fixture("base.zip"))) as original:
        feedback = original.read("course/MKT320-F01.md")
    expected = {"course/MKT320-F01.md": sha256(feedback).hexdigest(), "course/MKT320-C01.md": None}
    first = await acquire(source, "fresh-dropout", fixture("dropout.zip"), expected=expected)
    assert all(m["retained_version"] is None for m in first["coverage"]["missing"])
    recovery = await acquire(source, "exact-recovery", fixture("recovered.zip"), expected=expected)
    item = next(i for i in recovery["items"] if i["logical_path"].endswith("F01.md"))
    row = source.independent.require(owner, item["document_id"])
    assert row.version_hash == sha256(feedback).hexdigest()
    save(
        "recovered-feedback",
        {"source": row.id, "hash": row.version_hash, "pages": row.content["parsed"]["pages"]},
    )
    again = await acquire(source, "retained-omission", fixture("dropout.zip"), expected=expected)
    assert any(m["retained_version"] == row.version_hash for m in again["coverage"]["missing"])
    source.independent.delete(owner, row.id)
    deleted = await acquire(source, "after-deletion", fixture("recovered.zip"), expected=expected)
    assert (
        next(i for i in deleted["items"] if i["logical_path"].endswith("F01.md"))["state"]
        == "failed"
    )


async def test_bounded_semester(rig, owner):
    source, dest, fixture, acquire, save = rig
    index = json.loads(fixture("full-semester-index.json"))
    by_course = defaultdict(list)
    for entry in index["members"]:
        by_course[entry["course_fixture_key"]].append(entry["archive_entry"])
    counts = Counter()
    with zipfile.ZipFile(io.BytesIO(fixture("full-semester.zip"))) as full:
        for course, paths in sorted(by_course.items()):
            for offset in range(0, len(paths), 19):
                names = paths[offset : offset + 19]
                selected = archive([(n, full.read(n)) for n in names])
                name = f"semester-{course}-{offset}"
                expected = {
                    k: None
                    for k in {"MKT320": ["MKT320-C01"], "OPS330": ["OPS330-N02", "OPS330-R04"]}.get(
                        course, []
                    )
                }
                result = await acquire(source, name, selected, course=course, expected=expected)
                counts["unsupported"] += len(result["excluded"])
                counts.update(i["state"] for i in result["items"])
                assert len(result["items"]) + len(result["excluded"]) == len(names)
                docs = [i["document_id"] for i in result["items"] if i["state"] == "ready"]
                if docs:
                    raw = Workspace(source).export(owner, course, [], docs, originals=True)
                    api = Workspace(dest)
                    preview = api.restore(owner, raw, generation=0)
                    receipt = api.restore(
                        owner, raw, generation=0, confirmation=preview["preview_id"], key=name
                    )
                    save(name + "-restore", {"preview": preview, "receipt": receipt})
                    unresolved = {
                        k for k, v in preview["documents"].items() if v["action"] == "blocked"
                    }
                    assert all(
                        preview["documents"][k].get("reason") == "PORT_REFERENCE_UNRESOLVED"
                        for k in unresolved
                    )
                    assert receipt["status"] == ("partial" if unresolved else "complete")
                    for ident in set(docs) - unresolved:
                        assert (
                            dest.independent.require(owner, ident).version_hash
                            == source.independent.require(owner, ident).version_hash
                        )
                    # Each declared course unit is bounded by the actual 20-document store limit.
                    for ident in docs:
                        if ident not in unresolved:
                            dest.independent.delete(owner, ident)
                        source.independent.delete(owner, ident)
    save(
        "semester-accounting",
        {
            "members": sum(counts.values()),
            "courses": list(by_course),
            "states": counts,
            "strategy": "sequential bounded units with explicit synthetic deletion after verified readback",
        },
    )
    assert sum(counts.values()) == 236


async def test_supplied_shared_reading(rig, owner):
    source, _, fixture, acquire, save = rig
    with zipfile.ZipFile(io.BytesIO(fixture("shared.zip"))) as shared:
        first, second = "course/MKT320-R02.pdf", "finance/shared-reading.pdf"
        mkt = await acquire(
            source, "shared-marketing", archive([(first, shared.read(first))]), course="MKT320"
        )
        fin = await acquire(
            source, "shared-finance", archive([(second, shared.read(second))]), course="FIN310"
        )
    a, b = mkt["items"][0], fin["items"][0]
    assert a["content_hash"] == b["content_hash"] and a["binding"] != b["binding"]
    assert a["document_id"] != b["document_id"]
    source.independent.delete(owner, a["document_id"])
    assert source.independent.require(owner, b["document_id"]).version_hash == a["content_hash"]
    save(
        "shared-isolation",
        {"version": a["content_hash"], "removed": a["binding"], "retained": b["binding"]},
    )
