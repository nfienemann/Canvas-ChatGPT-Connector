from copy import deepcopy
from types import SimpleNamespace

import pytest
from pypdf.generic import DictionaryObject, NameObject, NumberObject

from canvas_bridge import parser_sandbox
from canvas_bridge.parser_worker import sparse_image_text


def raster_page(nested=False):
    image = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1000),
            NameObject("/Height"): NumberObject(1000),
        }
    )
    resources = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image})}
    )
    if nested:
        form = DictionaryObject(
            {NameObject("/Subtype"): NameObject("/Form"), NameObject("/Resources"): resources}
        )
        resources = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Form"): form})}
        )
    return DictionaryObject({NameObject("/Resources"): resources})


@pytest.mark.parametrize("nested", [False, True])
def test_sparse_footer_and_raster_is_ocr_candidate(nested):
    assert sparse_image_text(raster_page(nested), "Publisher footer " * 10)
    assert not sparse_image_text(raster_page(nested), "Substantial text " * 40)
    assert not sparse_image_text(DictionaryObject(), "Short legitimate paragraph")


@pytest.mark.parametrize(
    "ocr_text,accepted", [("Fictional body paragraph " * 30, True), ("Short poor OCR", False)]
)
async def test_sparse_scan_ocr_recovers_body_without_replacing_better_text(
    monkeypatch, tmp_path, ocr_text, accepted
):
    footer = "Publisher footer " * 10
    baseline = {
        "format": "pdf",
        "content_hash": "a" * 64,
        "parser": "fixture",
        "metadata": {},
        "page_count": 1,
        "coverage": "partial",
        "warnings": [],
        "pages": [{"page": 1, "text": footer, "state": "extracted", "sparse_image_text": True}],
    }
    calls = []

    def fake(data, kind, root, **kwargs):
        calls.append(kwargs)
        if kwargs.get("visual"):
            return {
                "pixels": 1000000,
                "ocr": {
                    "text": ocr_text,
                    "mean_confidence": 90,
                    "method": "fictional_ocr",
                    "words": [],
                },
            }
        return deepcopy(baseline)

    monkeypatch.setattr(parser_sandbox, "extract_isolated", fake)
    settings = SimpleNamespace(
        file_reading_enabled=True,
        parser_root=tmp_path,
        parser_runtime_root=tmp_path,
        ocr_root=tmp_path,
    )
    result = await parser_sandbox.extract_document(b"fictional", "pdf", settings)
    assert len(calls) == 2
    page = result["pages"][0]
    assert page["text"].strip() == (ocr_text if accepted else footer).strip()
    assert (page.get("state") == "ocr_extracted") == accepted
    if accepted:
        assert any("Fictional body" in x["text"] for x in page["structure"]["text_blocks"])


def test_footer_only_sparse_page_is_not_complete_body_text():
    from canvas_bridge.document_diagnostics import diagnostics

    result = diagnostics(
        [{"page": 1, "text": "Footer only", "state": "extracted", "sparse_image_text": True}], [], 1
    )
    assert result["unit_coverage"]["unit_outcomes"] == [{"position": 1, "state": "sparse"}]
    assert result["ocr_coverage"]["pages_with_usable_text"] == 0
    assert result["ocr_coverage"]["text_positions_complete"] is False


def test_old_ocr_failure_cannot_inject_fields_or_replace_the_page_locator():
    from canvas_bridge.document_diagnostics import diagnostics

    failure = {
        "reason_code": "OCR_INSTALLATION_UNAVAILABLE",
        "status": "unsupported_feature",
        "processing_stage": "ocr",
        "page": 99,
        "message": "PRIVATE exception",
        "title": "PRIVATE path",
        "nested": {"url": "PRIVATE URL"},
    }
    out = diagnostics([{"page": 1, "text": "", "ocr_failure": failure}], [], 1, "pdf")
    assert "PRIVATE" not in str(out)
    assert out["document_diagnostics"][0]["page"] == 1
    assert out["document_diagnostics"][0]["reason_code"] == "OCR_INSTALLATION_UNAVAILABLE"


def test_parser_diagnostic_category_does_not_echo_exception_payload():
    from canvas_bridge.domain import DomainError
    from canvas_bridge.parser_sandbox import validate_result

    with pytest.raises(DomainError) as error:
        validate_result(
            {
                "ok": False,
                "reason": "corrupt_or_unreadable",
                "details": {"parser_error_type": "PRIVATE SOURCE TEXT"},
            },
            b"fictional",
        )
    assert "PRIVATE" not in str(error.value.data)
    with pytest.raises(DomainError) as error:
        validate_result(
            {
                "ok": False,
                "reason": "corrupt_or_unreadable",
                "details": {"parser_error_type": "PdfReadError"},
            },
            b"fictional",
        )
    assert error.value.data["parser_error_type"] == "PdfReadError"


def test_valid_indirect_annotation_array_is_not_corrupt():
    import io

    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, TextStringObject

    from canvas_bridge.parser_worker import extract
    from tests.test_file_reading import scientific_pdf

    writer = PdfWriter(clone_from=io.BytesIO(scientific_pdf(["Fictional course instructions"])))
    annotations = ArrayObject(
        [
            writer._add_object(
                DictionaryObject(
                    {
                        NameObject("/Subtype"): NameObject("/Text"),
                        NameObject("/T"): TextStringObject("Fictional Reviewer"),
                    }
                )
            )
        ]
    )
    writer.pages[0][NameObject("/Annots")] = writer._add_object(annotations)
    stream = io.BytesIO()
    writer.write(stream)
    result = extract(stream.getvalue(), "pdf")
    assert "Fictional course instructions" in result["pages"][0]["text"]
    assert "Fictional Reviewer" not in str(result)
