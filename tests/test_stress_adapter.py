"""Adapter/import checks; not the external 73-case acceptance benchmark."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from canvas_bridge.academic.independent_models import IndependentAcademicInput, IndependentRequest
from tests.stress_support import ROOT, NeutralRecords, adapt, course_sources
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally


@pytest.mark.parametrize("course", [f"C{i:02}" for i in range(1, 13)])
async def test_twelve_courses_import_through_normal_store_with_no_lms(
    course, bridge, owner, no_lms_running, token_factory, parsed_locally, monkeypatch
):
    monkeypatch.setattr(bridge, "client", lambda *a, **k: pytest.fail("LMS access attempted"))
    documents = []
    async with client_session(no_lms_running, token_factory()) as session:
        for path in course_sources(course):
            ident = await bridge.independent.ingest(
                owner,
                path.read_bytes(),
                path.name,
                "text/markdown",
                own_material=True,
                share_text=True,
                allow_academic_analysis=True,
            )
            status = (
                await session.call_tool("get_local_document_status", {"document_id": ident})
            ).structuredContent
            assert status["status"] == "ok", status
            documents.append(
                {"document_id": ident, "expected_hash": status["data"]["content_hash"]}
            )
        result = (
            await session.call_tool(
                "run_independent_academic_workflow",
                {
                    "request": {
                        "capability": "requirements",
                        "documents": documents,
                    }
                },
            )
        ).structuredContent
    assert result["status"] in {"ok", "partial_data"}, result
    assert result["data"]["diagnostics"]["institutional_network_attempted"] is False
    assert len(result["data"]["source_versions"]) == 3


def test_adapter_keeps_unknowns_locators_course_scope_and_partial_coverage():
    points, provenance = adapt("C01")
    assert points["grades"]["assessments"][-1]["score"] is None
    assert points["grades"]["assessments"][-1]["score_state"] == "ungraded"
    assert points["complete"] is False
    assert provenance["course"] == "C01" and provenance["locators"]["F"].endswith("/2")
    weighted, provenance2 = adapt("C02")
    assert provenance2["course"] != provenance["course"]
    assert {g["weight"] for g in weighted["grades"]["groups"]} == {"20.00", "30.00", "50.00"}
    planning, _ = adapt("C10")
    assert planning["work"][0]["due"]["kind"] == "local_date"
    assert planning["work"][0]["due"]["timestamp"] is None
    assert "discussion" in provenance["unmapped_sections"]


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("synthetic", False)])
def test_adapter_rejects_unrecognized_or_nonfictional_package(field, value):
    data = json.loads((ROOT / "schema_neutral_records.json").read_text())
    data[field] = value
    with pytest.raises(ValidationError):
        NeutralRecords.model_validate(data)


@pytest.mark.parametrize(
    "filename,model",
    [
        ("independent-academic-1.schema.json", IndependentAcademicInput),
        ("independent-workflow-request.schema.json", IndependentRequest),
    ],
)
def test_published_schema_matches_current_models(filename, model):
    schema = Path(__file__).parents[1] / "docs" / "schemas" / filename
    assert json.loads(schema.read_text()) == model.model_json_schema()
