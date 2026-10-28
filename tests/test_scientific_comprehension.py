"""Scientific v3 regression fixtures: fictional OOXML, images and source facts."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from canvas_bridge.course_files import read_file
from canvas_bridge.domain import DomainError
from canvas_bridge.figure_inspection import inspect_figure
from canvas_bridge.figure_observations import FigureObservation, record_observation
from canvas_bridge.parser_sandbox import validate_result
from canvas_bridge.parser_worker import extract
from canvas_bridge.scientific_benchmark import ROOT, corpus, evaluate
from canvas_bridge.scientific_documents import document_model
from canvas_bridge.scientific_explanations import ScientificExplanation, grounded_explanation
from tests.test_docx_reading import docx, paragraph
from tests.test_docx_reading import word_file as word_file
from tests.test_figure_inspection import visual_source as visual_source
from tests.test_file_reading import readable as readable
from tests.test_presentation_reading import presentation as presentation
from tests.test_presentation_reading import rich_deck
from tests.test_presentation_rendering import (
    synthetic_render_transport as synthetic_render_transport,
)
from tests.test_spreadsheet_reading import NS, workbook


def scientific_word():
    math = '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:f><m:num><m:r><m:t>x</m:t></m:r></m:num><m:den><m:r><m:t>y</m:t></m:r></m:den></m:f></m:oMath>'
    return docx(
        paragraph("Figure 3. Fictional dose response")
        + '<w:p><w:r><w:t>H</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="subscript"/></w:rPr><w:t>2</w:t></w:r><w:r><w:t>O</w:t></w:r></w:p>'
        + '<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        + paragraph("Concentration (uM)")
        + "</w:tc></w:tr><w:tr><w:tc>"
        + paragraph("1e-3")
        + "</w:tc><w:tc>"
        + paragraph("ND")
        + "</w:tc></w:tr></w:tbl>"
        + math
    )


def visible(**changes):
    fields = dict(
        visibility="visible",
        delivery_mode="native_mcp_image",
        figure_status="figure_confirmed",
        visible_feature="Two labeled curves on separate axes.",
        region=[0, 0, 1, 1],
        image_quality="sufficient_for_claims",
        direct_visual_observations=["The treatment curve increases."],
        limitations=["No significance test or error-bar meaning is supplied."],
    )
    return FigureObservation(**(fields | changes))


def explanation(**changes):
    fields = dict(
        claims=[
            {
                "claim_id": "observation",
                "statement": "The treatment curve increases.",
                "basis": "visual_observation",
                "visual_observation_indexes": [0],
            },
            {
                "claim_id": "inference",
                "statement": "The displayed response is consistent with an increase under treatment.",
                "basis": "inference",
                "based_on": ["observation"],
                "uncertainty": "Causality and significance are not established.",
            },
        ],
        limitations=["A fictional example, not a real experiment."],
    )
    return ScientificExplanation(**(fields | changes))


def test_word_preserves_cells_spans_headers_subscripts_and_equation_tree():
    data = scientific_word()
    result = extract(data, "docx")
    structure = result["pages"][0]["structure"]
    assert structure["scope"] == "original_document"
    table = structure["tables"][0]
    assert table["cells"][0]["column_span"] == 2
    assert table["cells"][0]["header_declared"]
    assert [(c["row"], c["column"], c["text"]) for c in table["cells"][1:]] == [
        (2, 1, "1e-3"),
        (2, 2, "ND"),
    ]
    assert any(
        r["text"] == "2" and r["vertical_alignment"] == "subscript"
        for b in structure["text_blocks"]
        for r in b["runs"]
    )
    tree = structure["equations"][0]["tree"]
    assert tree["children"][0]["operator"] == "f"
    assert [n["operator"] for n in tree["children"][0]["children"]] == ["num", "den"]
    assert structure["visual_inspection_status"] == "not_performed"
    validate_result({"ok": True, "extraction": result}, data)


def test_workbook_preserves_coordinates_merges_notation_and_superscripts():
    data = workbook(
        changes={
            "xl/sharedStrings.xml": f'<sst xmlns="{NS}"><si><r><t>10</t></r><r><rPr><vertAlign val="superscript"/></rPr><t>-3</t></r></si></sst>'
        }
    )
    page = extract(data, "xlsx")["pages"][0]
    table = page["structure"]["tables"][0]
    records = table["stored_records"]
    assert records[0]["merged_ranges"] == ["A4:C4"]
    cell = next(r for r in records if r.get("cell") == "A1")
    assert cell["rich_runs"][1]["vertical_alignment"] == "superscript"
    assert cell["rich_runs"][1]["text"] == "-3"
    assert any(
        e["notation"] == "spreadsheet_formula" and e["interpretation"] == "not_evaluated"
        for e in page["structure"]["equations"]
    )
    assert next(r for r in records if r.get("cell") == "C3")["value"] == "12345678901234567890.1234"


def test_notes_and_original_presentation_order_remain_separate():
    result = extract(rich_deck(), "pptx")
    first = result["pages"][0]
    assert first["page"] == first["slide_number"] == 1
    assert (
        first["structure"]["speaker_notes"][0]["text"]
        == "Repeat controls before drawing conclusions."
    )
    assert "999" not in str(first["structure"])
    assert first["structure"]["visual_inspection_status"] == "not_performed"


def test_pdf_extraction_and_hash_never_count_as_visual_inspection():
    source = (ROOT / "scientific-fixtures.pdf").read_bytes()
    result = extract(source, "pdf")
    assert result["content_hash"] == hashlib.sha256(source).hexdigest()
    assert len(result["pages"]) == 10
    assert all(
        p["structure"]["visual_inspection_status"] == "not_performed" for p in result["pages"]
    )
    assert all(not p["structure"]["equations"] for p in result["pages"])
    assert "not established" in result["pages"][0]["structure"]["limitations"][-1]


def test_parser_boundary_rejects_forged_visual_confirmation():
    data = scientific_word()
    parsed = extract(data, "docx")
    parsed["pages"][0]["structure"]["visual_inspection_status"] = "confirmed"
    with pytest.raises(ValueError, match="scientific structure"):
        validate_result({"ok": True, "extraction": parsed}, data)


def test_privacy_redaction_discards_structural_aliases():
    data = docx(
        paragraph("student_email: synthetic.peer@fixture.invalid") + paragraph("Safe academic text")
    )
    result = extract(data, "docx")
    assert "synthetic.peer@fixture.invalid" not in json.dumps(result)
    assert "structure" not in result["pages"][0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("visibility", "unavailable"),
        ("delivery_mode", "unknown"),
        ("image_quality", "insufficient_resolution"),
        ("image_quality", "important_details_unreadable"),
    ],
)
def test_unseen_or_unreadable_figures_cannot_receive_scientific_explanation(field, value):
    with pytest.raises(ValidationError):
        visible(**{field: value}, scientific_explanation=explanation())


def test_scientific_explanation_is_attributed_not_independently_verified():
    observation = visible(scientific_explanation=explanation())
    result = grounded_explanation(observation.scientific_explanation, observation, None, "Slide 22")
    assert result["source_locator"] == "Slide 22"
    assert "not_independently_verified" in result["verification"]
    assert result["model_visibility_confirmation"] == "attributed_assistant_report_not_server_proof"


def test_text_claims_must_match_current_source_and_numbers():
    report = explanation(
        claims=[
            {
                "claim_id": "text",
                "statement": "The response was 8 units.",
                "basis": "source_text",
                "source_quote": "The response was 8 units.",
            }
        ]
    )
    assert grounded_explanation(report, visible(), "The response was 8 units.", "PDF page 1")
    with pytest.raises(DomainError, match="not anchored"):
        grounded_explanation(report, visible(), "The response was 9 units.", "PDF page 1")
    bad = report.model_copy(
        update={
            "claims": [
                report.claims[0].model_copy(update={"statement": "The response was 99 units."})
            ]
        }
    )
    with pytest.raises(DomainError, match="Numerical claims"):
        grounded_explanation(bad, visible(), "The response was 8 units.", "PDF page 1")


def test_visual_numbers_require_structured_readings_and_estimate_uncertainty():
    report = explanation(
        claims=[
            {
                "claim_id": "visual",
                "statement": "The response is 8 units.",
                "basis": "visual_observation",
                "visual_observation_indexes": [0],
            }
        ]
    )
    with pytest.raises(DomainError, match="Numerical claims"):
        grounded_explanation(report, visible(), None, "Slide 1")
    number = {
        "value": "8",
        "precision": "visual_estimate",
        "evidence": "Point near axis tick",
        "region": [0.2, 0.2, 0.3, 0.3],
    }
    observation = visible(panels=[{"region": [0, 0, 1, 1], "numerical_readings": [number]}])
    with pytest.raises(DomainError, match="estimate"):
        grounded_explanation(report, observation, None, "Slide 1")
    report.claims[0].uncertainty = "Approximate visual estimate, not an exact label."
    assert grounded_explanation(report, observation, None, "Slide 1")


def test_unknown_claim_reference_and_unreadable_fields_are_rejected():
    with pytest.raises(ValidationError):
        explanation(
            claims=[
                {
                    "claim_id": "inference",
                    "statement": "A causal result.",
                    "basis": "inference",
                    "based_on": ["missing"],
                    "uncertainty": "Unknown",
                }
            ]
        )
    report = explanation(
        claims=[
            {
                "claim_id": "v",
                "statement": "The curve increases.",
                "basis": "visual_observation",
                "visual_observation_indexes": [99],
            }
        ]
    )
    with pytest.raises(DomainError):
        grounded_explanation(report, visible(), None, "Slide 1")


async def test_pptx_figure_discovery_and_report_keep_original_slide(
    bridge, owner, seeded, presentation, synthetic_render_transport
):
    result, png = await inspect_figure(
        bridge, owner, seeded, presentation, page=3, delivery_mode="native"
    )
    assert png and result.data["source_slide"] == 3 and result.data["rendered_page"] == 1
    assert result.data["native_reader_fallback"]["arguments"]["slide"] == 3
    recorded = await record_observation(
        bridge,
        owner,
        seeded,
        result.data["render_receipt"],
        visible(scientific_explanation=explanation()),
    )
    assert recorded.data["source_locator"] == "Slide 3"
    assert recorded.data["scientific_explanation"]["source_locator"] == "Slide 3"
    assert recorded.data["interpretation_verified"] is False
    assert recorded.data["visual_pipeline"]["image_visible_to_model"]["status"] == "reported"


async def test_structure_projection_preserves_source_permissions_and_output_budget(
    bridge, owner, seeded, visual_source
):
    result = await read_file(bridge, owner, seeded, visual_source)
    model = result.data["document_model"]
    assert model["source_file_id"] == visual_source
    assert model["source_permissions"]["grants_access"] is False
    assert model["comprehension_status"] == "not_established"
    assert len(json.dumps(model).encode()) < 65_000


def test_scientific_corpus_retrieval_passes_without_claiming_interpretation_accuracy():
    result = evaluate()
    assert result["retrieval_accuracy"] == 1
    assert result["interpretation_accuracy"] is None
    assert result["interpretation_reviewed_count"] == 0
    assert result["source_stable"]


def test_scientific_corpus_tamper_is_detected(tmp_path):
    import shutil

    shutil.copytree(ROOT, tmp_path / "corpus")
    (tmp_path / "corpus/qpcr.png").write_bytes(b"altered")
    with pytest.raises(ValueError, match="hash"):
        corpus(tmp_path / "corpus")


def test_model_cannot_be_sole_judge_of_its_interpretation():
    from canvas_bridge.benchmark_lab.dataset import digest

    manifest, cases = corpus()
    attempt = {
        "case_id": cases[0]["id"],
        "image_sha256": manifest["files"][cases[0]["id"] + ".png"],
        "observation": visible(scientific_explanation=explanation()).model_dump(mode="json"),
    }
    responses = {
        "corpus_sha256": digest(manifest),
        "system": {
            "id": "evaluated-model",
            "version": "fixture",
            "execution_reference": "synthetic-test",
        },
        "observations": [attempt],
    }
    review = {
        "case_id": attempt["case_id"],
        "reviewer_kind": "model",
        "reviewer_id": "evaluated-model",
        "reviewed_at": "2026-10-26T00:00:00Z",
    }
    with pytest.raises(ValueError, match="independently"):
        evaluate(responses=responses, reviews={"reviews": [review]})


def test_large_structural_response_reports_omitted_units():
    row = SimpleNamespace(
        id="fictional",
        course_id="course",
        version_hash="a" * 64,
        file_state={"format": "pdf", "page_count": 2},
    )
    pages = [
        {"page": i, "state": "extracted", "structure": {"text_blocks": ["x" * 40_000]}}
        for i in (1, 2)
    ]
    model = document_model(row, pages)
    assert model["structure_units_omitted"] == [2]


def test_final_privacy_projection_preserves_reviewed_scientific_schema():
    from canvas_bridge.privacy.output import filter_output

    for kind, data in [("docx", scientific_word()), ("xlsx", workbook()), ("pptx", rich_deck())]:
        parsed = extract(data, kind)
        row = SimpleNamespace(
            id="fictional",
            course_id="course",
            version_hash=parsed["content_hash"],
            file_state={"format": kind, "page_count": parsed["page_count"]},
        )
        payload = {"document_model": document_model(row, parsed["pages"])}
        filtered, redacted, third_party, hidden = filter_output(payload)
        assert not redacted and not third_party and not hidden, (kind, filtered)
        assert filtered == payload
    observed = visible(scientific_explanation=explanation())
    payload = {
        "observation": observed.model_dump(mode="json"),
        "scientific_explanation": grounded_explanation(
            observed.scientific_explanation, observed, None, "Slide 3"
        ),
    }
    filtered, redacted, third_party, hidden = filter_output(payload)
    assert filtered == payload and not redacted and not third_party and not hidden


def test_unavailable_pixels_cannot_claim_assessed_image_quality():
    with pytest.raises(ValidationError):
        FigureObservation(
            visibility="unavailable",
            delivery_mode="unknown",
            figure_status="visual_inspection_unavailable",
            image_quality="sufficient_for_claims",
        )


async def test_word_visual_request_reports_unsupported_renderer(bridge, owner, seeded, word_file):
    _, file_id = word_file
    result, png = await inspect_figure(
        bridge, owner, seeded, file_id, page=1, delivery_mode="native"
    )
    assert png is None and result.data["fallback_reason"] == "VISUAL_FORMAT_UNSUPPORTED"
    assert result.data["native_reader_fallback"]["tool"] == "read_course_file"
    assert result.data["observations"] is None


async def test_literal_query_unresolved_and_continuation_binding(
    bridge, owner, seeded, visual_source
):
    missing, png = await inspect_figure(
        bridge,
        owner,
        seeded,
        visual_source,
        query="absent fictional molecule",
        delivery_mode="text",
    )
    assert png is None and missing.data["fallback_reason"] == "FIGURE_LOCATOR_UNRESOLVED"
    found, png = await inspect_figure(
        bridge, owner, seeded, visual_source, figure_label="Figure 2", delivery_mode="native"
    )
    token = found.data["continuation"]
    assert token and png
    with pytest.raises(DomainError, match="same search"):
        await inspect_figure(
            bridge, owner, seeded, visual_source, continuation=token, query="changed"
        )


def test_invalid_table_spans_do_not_invent_relationships():
    data = scientific_word()
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode()
    for span in ("-1", "oops", "10000000"):
        parsed = extract(
            docx(changes={"word/document.xml": xml.replace('w:val="2"', f'w:val="{span}"')}), "docx"
        )
        table = parsed["pages"][0]["structure"]["tables"][0]
        assert not table["structure_complete"] and table["cells"] == []


def test_equation_and_document_budgets_disclose_incomplete_structure():
    from canvas_bridge.scientific_structure import enrich

    math = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        + "<m:e>" * 14
        + "<m:r><m:t>x</m:t></m:r>"
        + "</m:e>" * 14
        + "</m:oMath>"
    )
    equation = extract(docx(math), "docx")["pages"][0]["structure"]["equations"][0]
    assert equation["tree"] is None and equation["structure_complete"] is False
    parsed = {
        "format": "pdf",
        "pages": [{"page": i, "text": "x" * 4000, "state": "extracted"} for i in range(1, 201)],
        "warnings": [],
    }
    enrich(parsed)
    assert sum(len(json.dumps(p.get("structure", {})).encode()) for p in parsed["pages"]) <= 121000
    assert any("structure" not in p for p in parsed["pages"])
    assert "omitted structures" in parsed["warnings"][0]


def review_fixture():
    # Tests exercise attestation validation; these are NOT benchmark judgments.
    from canvas_bridge.benchmark_lab.dataset import digest

    manifest, cases = corpus()
    case = cases[0]
    attempt = {
        "case_id": case["id"],
        "image_sha256": manifest["files"][case["id"] + ".png"],
        "observation": visible(scientific_explanation=explanation()).model_dump(mode="json"),
    }
    responses = {
        "corpus_sha256": digest(manifest),
        "system": {
            "id": "fixture-model",
            "version": "test",
            "execution_reference": "unit-test-only",
        },
        "observations": [attempt],
    }
    review = {
        "case_id": case["id"],
        "reviewer_kind": "human",
        "reviewer_id": "fictional-reviewer",
        "expertise": "Fictional testing role",
        "review_record": "unit-test-only",
        "reviewed_at": "2020-01-01T00:00:00Z",
        "corpus_sha256": digest(manifest),
        "observation_sha256": digest(attempt),
        "rubric_sha256": digest(case),
        "rubric_expert_reviewed": True,
        "dimensions": dict.fromkeys(case["required_dimensions"], True),
    }
    return responses, review


def test_external_review_requires_exact_answer_rubric_and_corpus():
    responses, review = review_fixture()
    result = evaluate(responses=responses, reviews={"reviews": [review]})
    assert result["interpretation_reviewed_count"] == 1 and result["interpretation_accuracy"] == 1
    for key in ("corpus_sha256", "observation_sha256", "rubric_sha256"):
        with pytest.raises(ValueError, match="source-bound"):
            evaluate(responses=responses, reviews={"reviews": [review | {key: "wrong"}]})
    review["dimensions"]["numerical_grounding"] = False
    result = evaluate(responses=responses, reviews={"reviews": [review]})
    assert result["interpretation_accuracy"] == 0


def test_required_review_gate_fails_unreviewed_corpus(tmp_path, monkeypatch):
    from canvas_bridge.scientific_benchmark import main

    monkeypatch.setattr(
        "sys.argv",
        ["scientific-benchmark", "--require-reviewed", "--output", str(tmp_path / "report.json")],
    )
    assert main() == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["interpretation_accuracy"] is None
    assert not report["gate"]["passed"] and report["gate"]["require_reviewed"]


def test_scientific_benchmark_blocks_network_attempts(monkeypatch):
    import socket

    def malicious_parser(*args):
        socket.getaddrinfo("synthetic.invalid", 443)

    monkeypatch.setattr("canvas_bridge.scientific_benchmark.extract", malicious_parser)
    with pytest.raises(ValueError, match="forbid network"):
        evaluate()


def test_foreign_xml_and_deleted_text_do_not_become_scientific_facts():
    body = (
        paragraph("Current source text")
        + '<x:p xmlns:x="urn:fictional"><x:r><x:t>Foreign fake fact</x:t></x:r></x:p>'
        + "<w:del>"
        + paragraph("Deleted fake fact")
        + "</w:del>"
    )
    structure = extract(docx(body), "docx")["pages"][0]["structure"]
    assert "fake fact" not in json.dumps(structure)
    assert structure["text_blocks"][0]["text"] == "Current source text"


async def test_unreadable_report_returns_clear_failure_without_completed_interpretation(
    bridge, owner, seeded, visual_source
):
    result, _ = await inspect_figure(
        bridge, owner, seeded, visual_source, page=4, delivery_mode="native"
    )
    observation = visible(
        image_quality="insufficient_resolution",
        direct_visual_observations=[],
        visible_feature="A blurred image whose labels cannot be read.",
    )
    report = await record_observation(
        bridge, owner, seeded, result.data["render_receipt"], observation
    )
    assert report.data["fallback_reason"] == "IMAGE_RESOLUTION_INSUFFICIENT"
    assert report.data["comprehension_status"] == "unavailable"
    assert (
        report.data["visual_pipeline"]["visual_interpretation_completed"]["status"]
        == "reported_unavailable"
    )
    assert report.data["scientific_explanation"] is None
