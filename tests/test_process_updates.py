"""Process updates through the Bridge adapter, with version and event fences."""

import json
from datetime import timedelta

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.processes.requests import EvaluationRequest, SaveRequest
from tests.test_process_service import process_document as process_document
from tests.test_recovery_independence import parsed_locally as parsed_locally


async def test_changed_provider_version_can_be_corrected_without_releasing_old_contents(
    bridge, owner, seeded
):
    from canvas_bridge.evidence import fingerprint
    from canvas_bridge.storage import Work

    bridge.settings.process_features_enabled = True
    now = bridge.retention.clock()
    workload = await bridge.workload(owner, seeded, now, now + timedelta(days=7), "UTC")
    item = next(i for i in workload.data["items"] if i["effective_due"]["kind"] == "timestamp")
    request = EvaluationRequest.model_validate(
        {
            "scope": {
                "connection_id": seeded,
                "course_id": item["course_id"],
                "resource_ids": [item["id"]],
            },
            "payload": {"operation": "evidence"},
        }
    )
    saved = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="exam-date")
    )
    await bridge.processes.confirm(owner, saved.data["preview_id"], True, "save")
    with bridge.store.transaction() as session:
        row = session.get(Work, item["id"])
        payload = json.loads(json.dumps(row.payload))
        payload["effective_due"]["timestamp"] = (now + timedelta(days=1)).isoformat()
        payload["source"]["content_hash"] = fingerprint(payload)
        row.payload = payload
        row.observed_at = now
    changed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="exam-date", expected_revision=1)
    )
    assert (
        changed.data["change"]["before"]["historical_content"] == "withheld_pending_version_review"
    )
    assert "data" not in changed.data["change"]["before"]
    await bridge.processes.confirm(owner, changed.data["preview_id"], True, "change")
    current = bridge.processes.repository.read(owner, "exam-date")
    assert current.revision == 2
    assert current.data["canonical_fields"]["deadline"] == (now + timedelta(days=1)).isoformat()
    impacts = bridge.processes.change_impacts(owner, "exam-date")
    assert impacts.data["external_writes"] is False
    assert impacts.data["impacts"]
    assert all(
        proposal["diff"]["deadline"]["before"] == "withheld_historical_version"
        for proposal in impacts.data["impacts"]
    )


async def test_annotation_export_roundtrips_and_markdown_fences_user_text(
    bridge, owner, process_document
):
    from canvas_bridge.processes.state import read_portable_export

    request = EvaluationRequest.model_validate(
        {
            "scope": {"document_ids": [process_document]},
            "payload": {
                "operation": "annotation",
                "source_id": process_document,
                "entity": "exam",
                "field": "deadline",
                "note": "Check `date` before planning.",
            },
        }
    )
    proposed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="annotation")
    )
    await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    exported = bridge.processes.export(owner, ["annotation"])
    restored = read_portable_export(exported.data, owner=owner)
    assert restored[0].kind == "annotation" and restored[0].data["source_edited"] is False
    markdown = bridge.processes.export(owner, ["annotation"], "markdown").data["markdown"]
    assert "```json" in markdown and markdown.endswith("```\n")


@pytest.mark.parametrize("records", [[None], [{"scope": []}], [{"scope": {}, "sources": [0]}]])
def test_malformed_portable_export_is_rejected_without_import(records):
    from canvas_bridge.processes.state import read_portable_export

    with pytest.raises(DomainError) as error:
        read_portable_export(
            {
                "schema_version": "academic-process-export-1",
                "records": records,
                "authority": "portable_evidence_only",
                "external_transfer": False,
            },
            owner="owner",
        )
    assert error.value.reason_code == "PROCESS_EXPORT_SCHEMA_UNSUPPORTED"


async def test_clarification_status_requires_confirmed_event_and_narrow_response(
    bridge, owner, process_document
):
    scope = {"document_ids": [process_document]}
    claims = [
        {"source_id": process_document, "entity": "exam", "field": "deadline", "value": value}
        for value in ("2030-10-10", "2030-10-11")
    ]
    request = EvaluationRequest.model_validate(
        {"scope": scope, "payload": {"operation": "clarification", "claims": claims}}
    )
    proposed = await bridge.processes.propose(
        owner, SaveRequest(evaluation=request, record_id="question")
    )
    await bridge.processes.confirm(owner, proposed.data["preview_id"], True, "save")
    update = EvaluationRequest.model_validate(
        {
            "scope": scope,
            "payload": {
                "operation": "clarification_update",
                "record_id": "question",
                "event": "sent",
            },
        }
    )
    with pytest.raises(DomainError):
        await bridge.processes.evaluate(owner, update)
    update = update.model_copy(
        update={"payload": update.payload.model_copy(update={"confirmed_event": True})}
    )
    next_preview = await bridge.processes.propose(
        owner, SaveRequest(evaluation=update, record_id="question", expected_revision=1)
    )
    await bridge.processes.confirm(owner, next_preview.data["preview_id"], True, "sent")
    assert (
        bridge.processes.repository.read(owner, "question").data["clarification"]["request"][
            "status"
        ]
        == "sent"
    )
