"""Synthetic provider and actual MCP acceptance for process features."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from canvas_bridge.app import create_app
from canvas_bridge.domain import DomainError
from canvas_bridge.processes.requests import EvaluationRequest, SaveRequest
from canvas_bridge.storage import IndependentResource
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally


@pytest.fixture
async def process_document(bridge, owner, parsed_locally):
    bridge.settings.process_features_enabled = True
    return await bridge.independent.ingest(
        owner,
        b"Fictional study notes. Exam is October 10. No real academic records.",
        "fictional-notes.txt",
        "text/plain",
        own_material=True,
        share_text=True,
    )


def evaluation(ident):
    return EvaluationRequest.model_validate(
        {
            "scope": {
                "document_ids": [ident],
                "local_course": "fictional-course",
                "term": "2030-fall",
            },
            "payload": {"operation": "evidence", "decision_class": "policy"},
        }
    )


async def test_process_service_local_offline_evaluation_and_confirmed_record(
    bridge, owner, process_document
):
    bridge.settings.capability_profile = "offline_research"
    request = evaluation(process_document)
    response = await bridge.processes.evaluate(owner, request)
    assert response.data["uncertainty_assessment"]["status"] == "sufficient"
    assert not response.data["uncertainty_assessment"]["permission_established"]
    assert response.sources[0].id == process_document
    proposed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="notes-evidence")
    )
    assert bridge.processes.repository.inventory(owner)["records"] == []
    with pytest.raises(DomainError):
        await bridge.processes.confirm(owner, proposed.data["preview_id"], False, "save")
    first = await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    second = await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    assert first.data == second.data
    assert bridge.processes.repository.read(owner, "notes-evidence").kind == "claim"
    with pytest.raises(DomainError):
        bridge.processes.inspect_records("different-owner", ["notes-evidence"])


async def test_process_source_delete_cascades_current_history_and_pending_preview(
    bridge, owner, process_document
):
    req = SaveRequest(evaluation=evaluation(process_document), record_id="evidence")
    proposed = await bridge.processes.propose(owner, req)
    await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    changed = await bridge.processes.propose(owner, req.model_copy(update={"expected_revision": 1}))
    bridge.independent.delete(owner, process_document)
    assert bridge.processes.repository.inventory(owner)["records"] == []
    with pytest.raises(DomainError):
        await bridge.processes.confirm(owner, changed.data["preview_id"], True, "change")
    with bridge.store.transaction() as session:
        rows = list(
            session.scalars(select(IndependentResource).where(IndependentResource.owner == owner))
        )
        assert all(
            process_document not in json.dumps(row.content)
            for row in rows
            if row.kind.startswith("academic_process")
        )


async def test_process_commit_source_revoked_after_preview_and_account_generation_race(
    bridge, owner, process_document, monkeypatch
):
    proposed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=evaluation(process_document), record_id="evidence")
    )
    original = bridge.processes.compute

    async def changed(*args):
        value = await original(*args)
        with bridge.store.transaction() as session:
            bridge.store.principal(session, owner).generation += 1
        return value

    monkeypatch.setattr(bridge.processes, "compute", changed)
    with pytest.raises(DomainError) as error:
        await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    assert error.value.reason_code == "PROCESS_ACCOUNT_CHANGED"
    assert bridge.processes.repository.inventory(owner)["records"] == []


async def test_process_provider_resource_rechecks_selection_and_source_versions(
    bridge, owner, seeded
):
    bridge.settings.process_features_enabled = True
    now = bridge.retention.clock()
    workload = await bridge.workload(owner, seeded, now, now + timedelta(days=7), "UTC")
    item = workload.data["items"][0]
    req = EvaluationRequest.model_validate(
        {
            "scope": {
                "connection_id": seeded,
                "course_id": item["course_id"],
                "resource_ids": [item["id"]],
            },
            "payload": {"operation": "evidence"},
        }
    )
    result = await bridge.processes.evaluate(owner, req)
    assert result.sources[0].id == item["id"]
    proposed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=req, record_id="course-evidence")
    )
    await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    bridge.store.disconnect(owner, seeded)
    assert bridge.processes.repository.inventory(owner)["records"] == []
    with pytest.raises(DomainError):
        await bridge.processes.evaluate(owner, req)


async def test_process_mcp_catalog_and_real_output_contract(
    settings, bridge, owner, seeded, token_factory, parsed_locally
):
    # Enable before constructing the HTTP app fixture.
    bridge.settings.process_features_enabled = True
    from tests.test_mcp_contract import running as server_fixture

    server = server_fixture.__wrapped__(bridge, settings, seeded)
    base = await anext(server)
    try:
        ident = await bridge.independent.ingest(
            owner,
            b"Fictional notes for an independent process test.",
            "fictional.txt",
            "text/plain",
            own_material=True,
            share_text=True,
        )
        async with client_session(base, token_factory()) as session:
            catalog = await session.list_tools()
            tools = {t.name: t for t in catalog.tools}
            assert tools["confirm_academic_process_change"].annotations.destructiveHint is True
            assert tools["preview_academic_process_change"].annotations.readOnlyHint is False
            request = evaluation(ident).model_dump(mode="json")
            response = await session.call_tool("evaluate_academic_process", {"request": request})
            data = response.structuredContent
            assert data["status"] == "ok", data
            assert data["data"]["uncertainty_assessment"]["status"] == "sufficient", data
            assert data["data"]["document_trust"][0]["authority_granted"] is False
            now = bridge.retention.clock()
            identity = {
                "source_id": ident,
                "provider": "manual",
                "external_id": "course-one",
                "term": "synthetic-term",
                "institution": "synthetic-institution",
                "course_code": "TEST101",
                "section": "A",
                "instructor": "Fictional instructor",
            }
            payloads = [
                {
                    "operation": "feasibility",
                    "work": [
                        {
                            "id": "essay",
                            "minimum_minutes": 30,
                            "maximum_minutes": 60,
                            "deadline": (now + timedelta(days=1)).isoformat(),
                        }
                    ],
                    "availability": [
                        {"start": now.isoformat(), "end": (now + timedelta(hours=3)).isoformat()}
                    ],
                },
                {
                    "operation": "identity",
                    "left": identity,
                    "right": identity | {"provider": "manual-other", "external_id": "course-two"},
                },
                {
                    "operation": "knowledge",
                    "concept_id": "cell",
                    "label": "Cell structure",
                    "related_concept": "chemistry",
                    "relationship_kind": "prerequisite",
                    "source_id": ident,
                    "review_at": (now + timedelta(days=2)).isoformat(),
                },
                {
                    "operation": "degree",
                    "program": "fictional",
                    "concentration": "biology",
                    "catalog_year": 2030,
                    "minimum_credits": 120,
                    "coursework": [{"course": "TEST101", "credits": 3, "completed": True}],
                },
                {
                    "operation": "lifecycle",
                    "assignment_id": "essay",
                    "target": "requirements_reviewed",
                },
                {
                    "operation": "portfolio",
                    "parts": [{"source_id": ident, "origin": "student_authored"}],
                },
                {
                    "operation": "annotation",
                    "source_id": ident,
                    "entity": "essay",
                    "field": "requirements",
                    "note": "Review the fictional rubric.",
                },
            ]
            for payload in payloads:
                evaluated = await session.call_tool(
                    "evaluate_academic_process", {"request": request | {"payload": payload}}
                )
                assert evaluated.structuredContent["status"] == "ok", (
                    payload["operation"],
                    evaluated.structuredContent,
                )
                if payload["operation"] == "knowledge":
                    assert (
                        evaluated.structuredContent["data"]["relationships"][0]["kind"]
                        == "prerequisite"
                    )
                if payload["operation"] == "degree":
                    assert evaluated.structuredContent["data"]["concentration"] == "biology"
            preview = await session.call_tool(
                "preview_academic_process_change",
                {"request": {"evaluation": request, "record_id": "evidence"}},
            )
            assert preview.structuredContent["status"] == "ok", preview.structuredContent
            ident = preview.structuredContent["data"]["preview_id"]
            applied = await session.call_tool(
                "confirm_academic_process_change",
                {"preview_id": ident, "confirmed": True, "idempotency_key": "save"},
            )
            assert applied.structuredContent["status"] == "ok", applied.structuredContent
            records = await session.call_tool(
                "get_academic_process_records", {"record_ids": ["evidence"]}
            )
            assert records.structuredContent["status"] == "ok", records.structuredContent
            assert records.structuredContent["data"]["records"][0]["kind"] == "claim"
            for output_format in ("json", "markdown"):
                exported = await session.call_tool(
                    "export_academic_process_records",
                    {"record_ids": ["evidence"], "output_format": output_format},
                )
                assert exported.structuredContent["status"] == "ok", exported.structuredContent
            impacts = await session.call_tool(
                "get_academic_process_impacts", {"record_id": "evidence"}
            )
            assert impacts.structuredContent["status"] == "ok", impacts.structuredContent
            support = await session.call_tool(
                "get_academic_support_report", {"category": "parsing"}
            )
            assert support.structuredContent["status"] == "ok", support.structuredContent
            assert not support.structuredContent["data"]["sent"]
    finally:
        await server.aclose()


def test_process_tools_disabled_by_default_and_writes_absent_in_read_only_mode(bridge, settings):
    app = create_app(settings, bridge)
    assert "evaluate_academic_process" not in {
        t.name for t in app.state.mcp._tool_manager.list_tools()
    }
    settings.process_features_enabled = settings.mcp_read_only = True
    app = create_app(settings, bridge)
    names = {t.name for t in app.state.mcp._tool_manager.list_tools()}
    assert "evaluate_academic_process" in names and "confirm_academic_process_change" not in names
