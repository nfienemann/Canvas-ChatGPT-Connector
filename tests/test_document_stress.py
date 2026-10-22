"""Synthetic boundary, generated-input and isolated-worker stress checks."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from xml.sax.saxutils import escape

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from canvas_bridge import parser_worker
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_isolated, validate_result
from tests.test_docx_reading import docx, paragraph, text_of
from tests.test_file_reading import scientific_pdf
from tests.test_spreadsheet_reading import NS, records, workbook


def sheet(rows):
    return f'<worksheet xmlns="{NS}"><sheetData>{rows}</sheetData></worksheet>'


@pytest.mark.parametrize("budget", [10, 21, 250_000])
def test_pdf_exact_budget_discloses_omitted_pages(monkeypatch, budget):
    monkeypatch.setattr(parser_worker, "MAX_TEXT", budget)
    result = parser_worker.extract(scientific_pdf(["x" * budget, "Unread final page"]), "pdf")
    assert result["coverage"] == "partial"
    assert len(result["pages"]) == 1 and result["page_count"] == 2
    assert any("remaining" in warning for warning in result["warnings"])


def test_pdf_exact_budget_with_no_remaining_page_is_complete(monkeypatch):
    monkeypatch.setattr(parser_worker, "MAX_TEXT", 10)
    result = parser_worker.extract(scientific_pdf(["1234567890"]), "pdf")
    assert result["coverage"] == "text_only"


@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_page_and_section_separator_cannot_exceed_text_budget(monkeypatch, kind):
    monkeypatch.setattr(parser_worker, "MAX_TEXT", 8001)
    data = (
        scientific_pdf(["x" * 8000, "end"])
        if kind == "pdf"
        else docx(paragraph("x" * 8000) + paragraph("end"))
    )
    result = parser_worker.extract(data, kind)
    assert len("\n\n".join(page["text"] for page in result["pages"])) <= 8001
    assert result["coverage"] == "partial"


@pytest.mark.parametrize("kind", ["pdf", "docx", "xlsx"])
def test_parent_rejects_worker_claiming_complete_with_missing_pages(kind):
    data = {"pdf": scientific_pdf(), "docx": docx(), "xlsx": workbook()}[kind]
    result = parser_worker.extract(data, kind)
    result["pages"].pop()
    with pytest.raises(ValueError, match="Invalid sandbox"):
        validate_result({"ok": True, "extraction": result}, data)


def test_parent_counts_page_separators_in_text_budget(monkeypatch):
    import canvas_bridge.parser_sandbox as sandbox

    data = scientific_pdf(["a", "b"])
    result = parser_worker.extract(data, "pdf")
    monkeypatch.setattr(sandbox, "MAX_TEXT", 3)
    with pytest.raises(ValueError, match="Invalid sandbox"):
        validate_result({"ok": True, "extraction": result}, data)


@pytest.mark.parametrize(
    "changes",
    [
        {"word/activeX/activeX1.xml": "<active/>"},
        {"word/ActiveX/activeX1.bin": b"synthetic control"},
        {
            "[Content_Types].xml": '<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'
        },
    ],
)
def test_docx_active_packages_are_rejected(changes):
    with pytest.raises(ValueError, match="active_office_content"):
        parser_worker.extract(docx(changes=changes), "docx")


@pytest.mark.parametrize("suffix", ["", "<v/>", "<v>42</v>"])
def test_xlsx_unknown_types_are_never_silently_blank(suffix):
    data = workbook(
        changes={
            "xl/worksheets/sheet2.xml": sheet(
                f'<row r="1"><c r="A1" t="unknown">{suffix}</c></row>'
            )
        }
    )
    with pytest.raises(ValueError, match="unsupported_workbook_cell_type"):
        parser_worker.extract(data, "xlsx")


@pytest.mark.parametrize("contents", ["<v>1</v><v>2</v>", "<f>1</f><f>2</f>", "<is/><is/>"])
def test_xlsx_duplicate_cell_values_and_formulas_are_rejected(contents):
    data = workbook(
        changes={"xl/worksheets/sheet2.xml": sheet(f'<row r="1"><c r="A1">{contents}</c></row>')}
    )
    with pytest.raises(ValueError, match="invalid_workbook_structure"):
        parser_worker.extract(data, "xlsx")


def test_xlsx_omitted_row_index_uses_explicit_cell_references():
    data = workbook(
        changes={
            "xl/worksheets/sheet2.xml": sheet(
                '<row><c r="C5"><v>7</v></c><c><v>8</v></c></row><row><c><v>9</v></c></row>'
            )
        }
    )
    _, cells = records(parser_worker.extract(data, "xlsx")["pages"][0])
    assert list(cells) == ["C5", "D5", "A6"]


@pytest.mark.parametrize(
    "row", ['<row><c r="A5"/><c r="B6"/></row>', '<row r="4"><c r="A5"/></row>']
)
def test_xlsx_conflicting_row_references_still_fail_closed(row):
    with pytest.raises(ValueError, match="invalid_workbook_structure"):
        parser_worker.extract(workbook(changes={"xl/worksheets/sheet2.xml": sheet(row)}), "xlsx")


def test_xlsx_default_style_preserves_date_format_for_cells_and_formula_cache():
    data = workbook(
        changes={
            "xl/styles.xml": f'<styleSheet xmlns="{NS}"><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>',
            "xl/worksheets/sheet2.xml": sheet(
                '<row r="1"><c r="A1"><v>45000</v></c><c r="B1"><f>A1+1</f><v>45001</v></c></row>'
            ),
        }
    )
    _, cells = records(parser_worker.extract(data, "xlsx")["pages"][0])
    assert cells["A1"]["number_format_id"] == 14
    assert cells["A1"]["value"] == "45000"
    assert cells["B1"]["cached_value"]["number_format_id"] == 14


XML_TEXT = st.text(alphabet="abc XYZ012<> &\t\nΔ雪😀", min_size=1, max_size=100)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.lists(XML_TEXT, min_size=1, max_size=20))
def test_generated_docx_runs_preserve_text_once(parts):
    runs = "".join(f'<w:r><w:t xml:space="preserve">{escape(part)}</w:t></w:r>' for part in parts)
    assert text_of(docx(f"<w:p>{runs}</w:p>")) == "".join(parts)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.lists(XML_TEXT, min_size=1, max_size=20))
def test_generated_xlsx_strings_and_cell_spans_round_trip(values):
    rows = "".join(
        f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c></row>'
        for i, value in enumerate(values, 1)
    )
    data = workbook(changes={"xl/worksheets/sheet2.xml": sheet(rows)})
    result = parser_worker.extract(data, "xlsx")
    validate_result({"ok": True, "extraction": result}, data)
    page = result["pages"][0]
    _, cells = records(page)
    assert [cell["value"] for cell in cells.values()] == values
    for span in page["cell_spans"]:
        assert json.loads(page["text"][span["start"] : span["end"]])["cell"] == span["cell"]


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    st.lists(
        st.text(alphabet="abc XYZ012", min_size=1, max_size=50).filter(lambda s: bool(s.strip())),
        min_size=1,
        max_size=5,
    ),
    st.integers(1, 200),
)
def test_generated_pdf_budgets_never_claim_omitted_text_is_complete(texts, budget):
    original = parser_worker.MAX_TEXT
    try:
        parser_worker.MAX_TEXT = budget
        result = parser_worker.extract(scientific_pdf(texts), "pdf")
    finally:
        parser_worker.MAX_TEXT = original
    canonical = "\n\n".join(text.strip() for text in texts)
    actual = "\n\n".join(page["text"] for page in result["pages"])
    assert len(actual) <= budget
    assert canonical.startswith(actual)
    if len(canonical) <= budget:
        assert actual == canonical
    if actual != canonical:
        assert result["coverage"] == "partial"


@pytest.mark.skipif(os.name != "nt", reason="Concurrent Windows AppContainer lifecycle proof")
def test_repeated_concurrent_real_workers_preserve_results_and_clean_jobs(tmp_path):
    runtime = tmp_path / "runtime"
    jobs = tmp_path / "jobs"
    samples = [
        ("docx", docx(paragraph("Synthetic worker canary"))),
        ("xlsx", workbook()),
        ("pdf", scientific_pdf()),
    ]
    expected = {
        kind: extract_isolated(data, kind, jobs, runtime_root=runtime) for kind, data in samples
    }

    def read(sample):
        kind, data = sample
        barrier.wait(timeout=10)
        try:
            return kind, extract_isolated(data, kind, jobs, runtime_root=runtime)
        except DomainError as exc:
            assert exc.reason_code == "DOCUMENT_WORKER_BUSY"
            assert exc.processing_stage == "worker_queue"
            return kind, None

    with ThreadPoolExecutor(max_workers=3) as pool:
        for _ in range(4):
            barrier = Barrier(3)
            results = list(pool.map(read, samples))
            assert any(result is not None for _, result in results)
            assert any(result is None for _, result in results)
            for kind, result in results:
                if result is None:
                    result = extract_isolated(dict(samples)[kind], kind, jobs, runtime_root=runtime)
                assert result == expected[kind]
    with pytest.raises(DomainError, match="active_office_content"):
        extract_isolated(
            docx(changes={"word/activeX/control.bin": b"synthetic"}),
            "docx",
            jobs,
            runtime_root=runtime,
        )
    assert not list((jobs / "jobs").iterdir())
