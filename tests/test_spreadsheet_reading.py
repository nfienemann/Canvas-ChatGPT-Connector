"""Synthetic XLSX semantics, adversarial inputs, authorization and OS/MCP gates."""

import asyncio
import io
import json
import os
import zipfile
from pathlib import Path

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.canvas import CanvasClient, Collection
from canvas_bridge.course_files import list_files, read_file, search_files, status
from canvas_bridge.domain import DomainError
from canvas_bridge.file_download import file_format
from canvas_bridge.parser_sandbox import extract_isolated, validate_result
from canvas_bridge.parser_worker import PARSER, extract
from canvas_bridge.policy import Endpoint
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material
from tests.test_course_files import file_record
from tests.test_mcp_contract import running as running

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def workbook(*, changes=None, date1904=False):
    parts = {
        "[Content_Types].xml": '<Types><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": f'<workbook xmlns="{NS}" xmlns:r="{REL}"><workbookPr date1904="{int(date1904)}"/><sheets><sheet name="PCR &amp; Δ" sheetId="9" r:id="r2"/><sheet name="Hidden values" sheetId="1" state="veryHidden" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships><Relationship Id="r1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="{REL}/worksheet" Target="/xl/worksheets/sheet2.xml"/><Relationship Id="s" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/><Relationship Id="fmt" Type="{REL}/styles" Target="styles.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst xmlns="{NS}"><si><r><t>00</t></r><r><t>123</t></r><rPh><t>not value</t></rPh></si></sst>',
        "xl/styles.xml": f'<styleSheet xmlns="{NS}"><numFmts><numFmt numFmtId="164" formatCode="00000"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>hidden canary</t></is></c></row></sheetData></worksheet>',
        "xl/worksheets/sheet2.xml": f'''<worksheet xmlns="{NS}"><dimension ref="A1:XFD1048576"/>
<cols><col min="2" max="2" hidden="1"/></cols><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>0</v></c><c r="C1"/><c r="E1" t="inlineStr"><is><t>雪\nquoted "value"</t></is></c></row>
<row r="2" hidden="1"><c r="A2"><f>SUM(B1,1)</f><v>1</v></c><c r="B2"><f>2+2</f></c><c r="C2" s="1"><v>45000</v></c><c r="D2" s="2"><v>123</v></c><c r="E2" t="b"><v>0</v></c><c r="F2" t="e"><v>#DIV/0!</v></c><c r="G2" t="d"><v>2026-10-22T12:30:00</v></c></row>
<row r="3"><c r="A3"><f t="shared" si="0" ref="A3:B3">A1+1</f><v>2</v></c><c r="B3"><f t="shared" si="0"/><v>0</v></c><c r="C3"><v>12345678901234567890.1234</v></c></row>
</sheetData><mergeCells><mergeCell ref="A4:C4"/></mergeCells></worksheet>''',
    }
    parts.update(changes or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return stream.getvalue()


def records(page):
    values = [json.loads(line) for line in page["text"].splitlines()]
    return values[0], {v["cell"]: v for v in values[1:]}


@pytest.mark.parametrize("epoch", [False, True])
def test_xlsx_types_formulas_cache_dates_hidden_merged_and_order(epoch):
    data = workbook(date1904=epoch)
    result = extract(data, "xlsx")
    assert validate_result({"ok": True, "extraction": result}, data) == result
    assert result["coverage"] == "text_only" and result["page_count"] == 2
    page = result["pages"][0]
    head, cells = records(page)
    assert head["sheet"] == "PCR & Δ" and head["date_system"] == ("1904" if epoch else "1900")
    assert head["merged_ranges"] == ["A4:C4"]
    assert cells["A1"]["value"] == "00123"
    assert cells["B1"]["value"] == "0" and cells["B1"]["hidden_column"]
    assert cells["C1"]["type"] == "blank" and cells["C1"]["value"] is None
    assert "D1" not in cells and "A4" not in cells
    assert cells["E1"]["value"] == '雪\nquoted "value"'
    assert cells["A2"]["formula"] == "SUM(B1,1)"
    assert cells["A2"]["cached_value"] == {"type": "number", "value": "1"}
    assert cells["A2"]["cached_value_present"] and cells["A2"]["hidden_row"]
    assert not cells["B2"]["cached_value_present"]
    assert cells["B3"]["cached_value_present"] and cells["B3"]["cached_value"]["value"] == "0"
    assert cells["B3"]["formula"] is None and cells["B3"]["formula_attributes"]["si"] == "0"
    assert cells["C2"]["value"] == "45000" and cells["C2"]["number_format_id"] == 14
    assert cells["D2"]["number_format"] == "00000" and cells["D2"]["value"] == "123"
    assert cells["E2"]["value"] is False and cells["F2"]["type"] == "error"
    assert cells["G2"]["type"] == "iso_date"
    assert cells["C3"]["value"] == "12345678901234567890.1234"
    assert result["pages"][1]["sheet_state"] == "veryHidden"
    for span in page["cell_spans"]:
        assert json.loads(page["text"][span["start"] : span["end"]])["cell"] == span["cell"]
    assert extract(data, "xlsx") == result


@pytest.mark.parametrize(
    "mime,name,supported",
    [
        (MIME, "READING.XLSX", "xlsx"),
        ("application/octet-stream", "reading.xlsx", "xlsx"),
        (MIME, "reading.xlsm", None),
        ("text/plain", "reading.xlsx", None),
        ("application/vnd.ms-excel", "reading.xls", None),
        ("text/csv", "reading.csv", None),
    ],
)
def test_xlsx_metadata_dispatch(mime, name, supported):
    assert file_format({"content-type": mime, "filename": name}) == supported


@pytest.mark.parametrize(
    "changes",
    [
        {"xl/vbaProject.bin": b"macro"},
        {"xl/embeddings/object.bin": b"object"},
        {"xl/macrosheets/sheet.xml": "<sheet/>"},
        {
            "xl/sharedStrings.xml": '<!DOCTYPE s [<!ENTITY e SYSTEM "file:///secret">]><sst><si><t>&e;</t></si></sst>'
        },
        {
            "xl/_rels/workbook.xml.rels": f'<Relationships><Relationship Id="r2" Type="{REL}/worksheet" Target="https://example.invalid/private" TargetMode="External"/></Relationships>'
        },
        {
            "xl/_rels/workbook.xml.rels": f'<Relationships><Relationship Id="r2" Type="{REL}/worksheet" Target="../../secret"/></Relationships>'
        },
        {
            "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>-1</v></c></row></sheetData></worksheet>'
        },
        {
            "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row r="1"><c r="XFE1"><v>1</v></c></row></sheetData></worksheet>'
        },
        {
            "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row r="1"><c r="A1"/><c r="A1"/></row></sheetData></worksheet>'
        },
        {
            "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row r="1"><c r="A1" s="999"/></row></sheetData></worksheet>'
        },
    ],
)
def test_xlsx_rejects_unsafe_or_ambiguous_workbooks(changes):
    with pytest.raises((ValueError, DefusedXmlException)):
        extract(workbook(changes=changes), "xlsx")


def test_xlsx_sparse_dimensions_do_not_expand_and_budget_is_honest(monkeypatch):
    import canvas_bridge.parser_worker as worker

    monkeypatch.setattr(worker, "MAX_TEXT", 600)
    result = worker.extract(workbook(), "xlsx")
    assert result["coverage"] == "partial" and result["page_count"] == 2
    assert sum(len(p["text"]) for p in result["pages"]) <= 600
    for page in result["pages"]:
        records(page)  # Budget never emits a half-cell or broken JSON record.
    assert any("remaining cells" in w for w in result["warnings"])


def test_xlsx_compression_bomb_duplicate_entries_and_corruption():
    with pytest.raises(ValueError, match="office_resource_limit"):
        extract(workbook(changes={"padding": "a" * 1_000_000}), "xlsx")
    stream = io.BytesIO(workbook())
    with zipfile.ZipFile(stream, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(ValueError, match="office_resource_limit"):
        extract(stream.getvalue(), "xlsx")
    with pytest.raises(zipfile.BadZipFile):
        extract(b"PK\x03\x04bad", "xlsx")


def test_xlsx_empty_string_escapes_and_external_formula_are_inert():
    sheet = """<worksheet><sheetData><row r="1">
<c r="A1" t="inlineStr"><is><t>_x005F_x0041_ _x000D_ _xD83D__xDE00_</t></is></c>
<c r="B1" t="str"><f>IF(1,"","")</f><v/></c>
<c r="C1"><f>WEBSERVICE("https://example.invalid/private")</f><v/></c>
<c r="D1" t="inlineStr"><is><t/></is></c></row></sheetData></worksheet>"""
    result = extract(workbook(changes={"xl/worksheets/sheet2.xml": sheet}), "xlsx")
    _, cells = records(result["pages"][0])
    assert cells["A1"]["value"] == "_x0041_ \r 😀"
    assert cells["B1"]["cached_value_present"] and cells["B1"]["cached_value"] == {
        "type": "string",
        "value": "",
    }
    assert cells["C1"]["formula"].startswith("WEBSERVICE")
    assert not cells["C1"]["cached_value_present"]
    assert cells["D1"]["value"] == "" and cells["D1"]["type"] == "string"


async def test_xlsx_changed_bytes_invalidate_continuation(bridge, owner, seeded, spreadsheet):
    _, ref = spreadsheet
    first = await read_file(bridge, owner, seeded, ref, length=100)
    data = workbook(date1904=True)
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(data), updated_at="2026-10-22T13:00:00Z"
    )
    bridge.synthetic.data["file_bodies"]["51"] = data
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, length=100, **first.data["continuation"])


async def test_xlsx_generic_canvas_mime_with_specific_response(bridge, owner, seeded, spreadsheet):
    _, ref = spreadsheet
    bridge.synthetic.data["files"]["11"][0]["content-type"] = "application/octet-stream"
    assert (await read_file(bridge, owner, seeded, ref)).data["format"] == "xlsx"


@pytest.fixture
async def spreadsheet(bridge, owner, seeded, monkeypatch):
    data = workbook()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                filename="synthetic.xlsx",
                display_name="synthetic.xlsx",
                **{"content-type": MIME},
                size=len(data),
                updated_at="2026-10-22T12:00:00Z",
                url="https://canvas.synthetic.invalid/files/51/download",
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": data}
    bridge.synthetic.data["file_types"] = {"51": MIME}
    bridge.synthetic.data["module_items"] = {
        "11": [{"title": "synthetic.xlsx", "type": "File", "content_id": 51}]
    }
    bridge.settings.file_reading_enabled = True

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    course = bridge.selected(owner, seeded)[1][0]
    listed = await list_files(bridge, owner, seeded, course.id)
    return course, listed.data["files"][0]["file_id"]


async def test_xlsx_read_reconstruction_hash_repeat_citations_search_fetch(
    bridge, owner, seeded, spreadsheet
):
    course, ref = spreadsheet
    before = await status(bridge, owner, seeded, ref)
    assert before.data["format_supported"] and before.data["access_state"] == "available"
    assert before.data["extraction_outcome"] == "not_attempted"
    result = await read_file(bridge, owner, seeded, ref, length=333)
    first = result
    text = result.data["text"]
    while result.data["continuation"]:
        result = await read_file(bridge, owner, seeded, length=333, **result.data["continuation"])
        text += result.data["text"]
    assert text == "\n\n".join(p["text"] for p in extract(workbook(), "xlsx")["pages"])
    assert (
        first.data["chunk_id"]
        == (await read_file(bridge, owner, seeded, ref, length=333)).data["chunk_id"]
    )
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1
    second = await read_file(bridge, owner, seeded, ref, page_start=2)
    assert second.data["passages"][0]["sheet_name"] == "Hidden values"
    assert "A1" in second.data["passages"][0]["cell_references"]
    assert "Sheet 2 'Hidden values', cell A1" in second.sources[0].locator
    assert "hidden canary" in (await fetch_material(bridge, owner, seeded, ref)).data["text"]
    for unread in (False, True):
        found = await search_files(
            bridge, owner, seeded, course.id, "hidden canary", include_unread=unread
        )
        hit = found.data["results"][0]
        assert hit["page"] == 2 and hit["cell_references"] == ["A1"]
        assert "Sheet 2" in hit["locator"] and hit["content_hash"] == first.data["content_hash"]
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, ref, offset=1)
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, ref, expected_hash="0" * 64)
    with pytest.raises(DomainError):
        await read_file(bridge, "different-owner", seeded, ref)
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    assert (await status(bridge, owner, seeded, ref)).data["access_state"] == "inaccessible"
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text


@pytest.mark.parametrize("old_parser", [None, "canvas-bridge-documents-v4"])
async def test_xlsx_old_unsupported_cache_is_invalidated(
    bridge, owner, seeded, spreadsheet, old_parser
):
    _, ref = spreadsheet
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.file_state = {"stage": "unsupported", "parser": old_parser, "reason": "old rejection"}
        row.limitations = ["The course file format is unsupported."]
    state = await status(bridge, owner, seeded, ref)
    assert state.data["state"] == "available" and state.data["reason"] is None
    assert "unsupported" not in " ".join(state.data["limitations"])
    assert (await read_file(bridge, owner, seeded, ref)).data["parser"] == PARSER


async def test_xlsx_reference_survives_partial_inventory_but_not_access_denial(
    bridge, owner, seeded, spreadsheet, monkeypatch
):
    course, ref = spreadsheet
    original = CanvasClient.collection
    original_one = CanvasClient.one

    async def partial(client, endpoint, **ids):
        if endpoint == Endpoint.FILES:
            return Collection(failure="request_budget")
        return await original(client, endpoint, **ids)

    async def slow(client, endpoint, **ids):
        if endpoint == Endpoint.FILE:
            await asyncio.sleep(1)
        return await original_one(client, endpoint, **ids)

    monkeypatch.setattr(CanvasClient, "collection", partial)
    monkeypatch.setattr(CanvasClient, "one", slow)
    bridge.settings.refresh_budget_seconds = 0.15
    result = await outline(bridge, owner, seeded, course.id)
    item = result.data["modules"][0]["items"][0]
    assert result.status == "partial_data" and item["material_ref"] == ref
    assert item["material_availability"] == "previously_discovered_access_not_rechecked"
    assert result.data["file_reading"]["parser"] == PARSER
    assert "xlsx" in result.data["file_reading"]["formats"]
    monkeypatch.setattr(CanvasClient, "one", original_one)
    bridge.settings.refresh_budget_seconds = 10
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    result = await outline(bridge, owner, seeded, course.id)
    item = result.data["modules"][0]["items"][0]
    assert "material_ref" not in item and item["material_availability"] == "inaccessible"
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref)


async def test_xlsx_known_denial_survives_later_module_timeout(
    bridge, owner, seeded, spreadsheet, monkeypatch
):
    course, _ = spreadsheet
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    original = CanvasClient.collection

    async def timeout_after_module(client, endpoint, **ids):
        result = await original(client, endpoint, **ids)
        if endpoint == Endpoint.MODULES:
            result.items += [{"id": 999, "name": "Later module"}]
        if endpoint == Endpoint.MODULE_ITEMS and ids.get("module") == "999":
            await asyncio.sleep(1)
        return result

    monkeypatch.setattr(CanvasClient, "collection", timeout_after_module)
    bridge.settings.refresh_budget_seconds = 0.15
    result = await outline(bridge, owner, seeded, course.id)
    item = result.data["modules"][0]["items"][0]
    assert "material_ref" not in item and item["material_availability"] == "inaccessible"


@pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer workbook acceptance")
def test_xlsx_actual_os_sandbox():
    root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    result = extract_isolated(workbook(), "xlsx", root)
    assert records(result["pages"][0])[1]["A1"]["value"] == "00123"
    assert result["pages"][1]["sheet_state"] == "veryHidden"
    with pytest.raises(DomainError, match="active_office_content"):
        extract_isolated(workbook(changes={"xl/vbaProject.bin": "macro"}), "xlsx", root)


@pytest.mark.contract
@pytest.mark.skipif(os.name != "nt", reason="MCP through the actual Windows XLSX worker")
async def test_xlsx_mcp_transport_uses_actual_sandbox(
    running, token_factory, seeded, spreadsheet, bridge, monkeypatch
):
    from canvas_bridge.parser_sandbox import extract_document

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", extract_document)
    bridge.settings.parser_root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    # An unavailable optional PDF OCR installation must not break workbook reads.
    bridge.settings.ocr_root = bridge.settings.parser_root / "missing-ocr-installation"
    _, ref = spreadsheet
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert "XLSX" in next(
                    t.description for t in catalog.tools if t.name == "read_course_file"
                )
                result = await session.call_tool(
                    "read_course_file", {"connection_id": seeded, "file_id": ref, "length": 1500}
                )
                assert not result.isError
                assert result.structuredContent["status"] == "ok"
                assert result.structuredContent["data"]["format"] == "xlsx"
                assert "00123" in result.structuredContent["data"]["text"]
                assert result.structuredContent["data"]["passages"][0]["cell_references"]
