"""Synthetic DOCX tables; no real coursework or credentials."""

import io
import json
import random
import string
import zipfile

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.course_files import list_files, read_file, search_files, status
from canvas_bridge.documents import read_docx
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_isolated
from canvas_bridge.parser_worker import extract
from tests.conftest import seed
from tests.test_academic_intelligence import office_manifest
from tests.test_course_files import file_record
from tests.test_mcp_contract import running as running
from tests.test_workbooks import rewrite

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def paragraph(text, style=None):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def cell(text="", properties="", content=None):
    return f"<w:tc><w:tcPr>{properties}</w:tcPr>{paragraph(text) if content is None else content}</w:tc>"


def table(rows, width=3, properties=""):
    return (
        "<w:tbl><w:tblPr>"
        + properties
        + "</w:tblPr><w:tblGrid>"
        + '<w:gridCol w:w="2000"/>' * width
        + "</w:tblGrid>"
        + "".join("<w:tr>" + row + "</w:tr>" for row in rows)
        + "</w:tbl>"
    )


def document_xml():
    rubric = table(
        [
            "<w:trPr><w:tblHeader/></w:trPr>"
            + cell("Criterion", '<w:vMerge w:val="restart"/>')
            + cell("Performance levels", '<w:gridSpan w:val="2"/>'),
            cell("", "<w:vMerge/>") + cell("Excellent") + cell("Developing"),
            cell("Methods") + cell("Reproducible controls") + cell("Missing controls"),
            '<w:trPr><w:gridBefore w:val="1"/></w:trPr>' + cell("10 points") + cell("5 points"),
        ],
        properties='<w:tblCaption w:val="Synthetic rubric"/>',
    )
    nested = table([cell("Inner label") + cell("Nested value")], 2)
    container = table(
        [cell(content=paragraph("Before inner") + nested + paragraph("After inner"))], 1
    )
    return (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + paragraph("Rubric requirements", "Heading1")
        + rubric
        + paragraph("Surrounding policy, not a table caption")
        + container
        + paragraph("Closing note")
        + "</w:body></w:document>"
    )


def document(xml=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        office_manifest(archive, "docx")
        archive.writestr("word/document.xml", document_xml() if xml is None else xml)
    return out.getvalue()


def records(result):
    return [r for page in result["pages"] for r in page["records"]]


def test_body_order_grid_coordinates_merges_headers_and_context():
    data = document()
    result = extract(data, "docx")
    assert result["coverage"] == "text_only"
    assert extract(data, "docx") == result
    all_records = records(result)
    by_id = {r["id"]: r for r in all_records}
    assert result["metadata"]["table_count"] == 3
    body_order = result["metadata"]["body_order"]
    assert body_order[0] == "P1" and body_order[1] == "T1" and body_order[3] == "T2"
    assert by_id["P1"]["style_id"] == "Heading1"
    assert by_id["T1"]["preceding_block"] == "P1"
    assert (
        by_id[by_id["T1"]["following_block"]]["text"] == "Surrounding policy, not a table caption"
    )
    assert by_id["T1"]["rows"][0]["repeating_header"]
    assert by_id["T1:R1C1"]["row_span"] == 2
    assert by_id["T1:R2C1"]["merge_origin"] == "T1:R1C1"
    assert by_id["T1:R2C1"]["text"] == ""  # Never duplicate Criterion.
    assert by_id["T1:R2C1"]["row_span"] is None
    assert by_id["T1:R1C2"]["column_span"] == 2
    assert by_id["T1:R1C2"]["merge_status"] == "horizontal_span"
    assert by_id["T1"]["rows"][3]["grid_before"] == 1
    assert "T1:R4C1" not in by_id
    assert by_id["T1:R4C2"]["text"] == "10 points"
    assert "Reproducible controls" in result["pages"][0]["text"]
    assert "[Paragraph" not in result["pages"][0]["text"]
    assert "not rendered pages" in " ".join(result["warnings"])


def test_nested_tables_remain_linked_to_exact_cell_and_ordered_blocks():
    result = extract(document(), "docx")
    items = {r["id"]: r for r in records(result)}
    blocks = items["T2:R1C1"]["blocks"]
    assert [b["kind"] for b in blocks] == ["paragraph", "table_reference", "paragraph"]
    assert blocks[0]["text"] == "Before inner" and blocks[2]["text"] == "After inner"
    assert blocks[1]["id"] == "T3"
    assert items["T3"]["parent_cell"] == "Table T2, R1C1"
    assert items["T3"]["preceding_block"] == blocks[0]["id"]
    assert items["T3"]["following_block"] == blocks[2]["id"]
    assert "Nested value" not in items["T2:R1C1"]["text"]
    assert "Nested value" == items["T3:R1C2"]["text"]


def test_combined_merge_rectangles_continue_only_across_consecutive_rows():
    rectangle = table(
        [
            cell("Group A", '<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>') + cell("Top"),
            cell("", '<w:gridSpan w:val="2"/><w:vMerge/>') + cell("Middle"),
            cell("", '<w:gridSpan w:val="2"/><w:vMerge/>') + cell("Bottom"),
            cell("Unmerged", '<w:gridSpan w:val="2"/>') + cell("Break"),
            cell("", '<w:gridSpan w:val="2"/><w:vMerge/>') + cell("Orphan"),
        ]
    )
    xml = '<w:document xmlns:w="urn:word"><w:body>' + rectangle + "</w:body></w:document>"
    result = extract(document(xml), "docx")
    items = {r["id"]: r for r in records(result)}
    assert items["T1:R1C1"]["row_span"] == 3 and items["T1:R1C1"]["column_span"] == 2
    assert items["T1:R3C1"]["merge_origin"] == "T1:R1C1"
    assert items["T1:R5C1"]["merge_origin"] is None
    assert items["T1:R5C1"]["merge_status"] == "unresolved"


@pytest.mark.parametrize(
    "case",
    [
        "trailing_omission",
        "empty_cell",
        "empty_table",
        "row_revision",
        "property_revision",
        "field",
        "picture",
    ],
)
def test_empty_omitted_and_uninterpreted_content_are_distinct(case):
    xml = document_xml()
    if case == "trailing_omission":
        xml = xml.replace('<w:gridBefore w:val="1"/>', '<w:gridAfter w:val="1"/>')
    elif case == "empty_cell":
        xml = xml.replace("Missing controls", "")
    elif case == "empty_table":
        xml = xml.replace(paragraph("Closing note"), table([], 1))
    elif case == "row_revision":
        xml = xml.replace("<w:tblHeader/>", '<w:tblHeader/><w:del w:id="1"/>')
    elif case == "property_revision":
        xml = xml.replace(
            "<w:tblHeader/>", '<w:tblHeader/><w:trPrChange w:id="1"><w:trPr/></w:trPrChange>'
        )
    elif case == "field":
        xml = xml.replace(
            "Closing note",
            "</w:t><w:instrText>PRIVATE COMMAND</w:instrText><w:t>Stored field result",
        )
    else:
        xml = xml.replace(paragraph("Closing note"), "<w:p><w:r><w:drawing/></w:r></w:p>")
    result = extract(document(xml), "docx")
    items = {r["id"]: r for r in records(result)}
    if case == "trailing_omission":
        assert items["T1"]["rows"][3]["grid_after"] == 1
        assert "T1:R4C3" not in items and items["T1:R4C1"]["text"] == "10 points"
    elif case == "empty_cell":
        assert items["T1:R3C3"]["text"] == "" and items["T1:R3C3"]["merge_origin"] is None
    elif case == "empty_table":
        assert items["T4"]["row_count"] == 0
    else:
        assert result["coverage"] == "partial"
        if case.endswith("revision"):
            assert result["metadata"]["detected_revision_markers"]
            assert items["T1"]["structure_status"] == "partial"
        if case == "field":
            assert "PRIVATE COMMAND" not in str(result)


@pytest.mark.parametrize(
    "case",
    [
        "orphan",
        "span_mismatch",
        "grid_mismatch",
        "legacy",
        "content_in_continuation",
        "no_grid",
        "revision",
        "row_wrapper",
        "floating",
    ],
)
def test_uncertain_structure_stays_partial(case):
    xml = document_xml()
    if case == "orphan":
        xml = xml.replace('<w:vMerge w:val="restart"/>', "")
    elif case == "span_mismatch":
        xml = xml.replace("<w:vMerge/>", '<w:vMerge/><w:gridSpan w:val="2"/>')
    elif case == "grid_mismatch":
        xml = xml.replace('<w:gridBefore w:val="1"/>', '<w:gridBefore w:val="2"/>')
    elif case == "legacy":
        xml = xml.replace('<w:gridSpan w:val="2"/>', '<w:hMerge w:val="restart"/>')
    elif case == "content_in_continuation":
        xml = xml.replace(
            "<w:vMerge/></w:tcPr>" + paragraph(""),
            "<w:vMerge/></w:tcPr>" + paragraph("Stored ambiguous value"),
        )
    elif case == "no_grid":
        xml = xml.replace('<w:gridCol w:w="2000"/>', "")
    elif case == "revision":
        xml = xml.replace(
            paragraph("Closing note"),
            "<w:ins>" + paragraph("Unconfirmed new deadline") + "</w:ins>",
        )
    elif case == "row_wrapper":
        xml = xml.replace("<w:tr>", "<w:tr><w:ins>" + cell("Changed cell") + "</w:ins>", 1)
    else:
        xml = xml.replace("<w:tblPr>", '<w:tblPr><w:tblpPr w:horzAnchor="page"/>', 1)
    result = extract(document(xml), "docx")
    assert result["coverage"] == "partial"
    if case == "revision":
        assert "ins" in result["metadata"]["omitted_elements"]
        assert "Unconfirmed new deadline" not in " ".join(p["text"] for p in result["pages"])
    else:
        assert result["metadata"]["tables"][0]["structure_status"] == "partial"
    if case in {"orphan", "span_mismatch"}:
        continuation = next(r for r in records(result) if r["id"] == "T1:R2C1")
        assert continuation["merge_status"] == "unresolved" and continuation["merge_origin"] is None


@pytest.mark.parametrize(
    "case", ["dtd", "span_zero", "span_huge", "deep", "row_limit", "long_text", "bad_body"]
)
def test_unsafe_or_excessive_documents_fail_explicitly(case):
    xml = document_xml()
    if case == "dtd":
        xml = '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///private">]>' + xml
    elif case in {"span_zero", "span_huge"}:
        xml = xml.replace('w:val="2"', 'w:val="0"' if case == "span_zero" else 'w:val="999999999"')
    elif case == "row_limit":
        xml = xml.replace(
            "</w:tbl>",
            ("<w:tr>" + cell() + "</w:tr>") * 201 + "</w:tbl>",
            1,
        )
    elif case == "long_text":
        xml = xml.replace("Closing note", "X" * 16001)
    elif case == "bad_body":
        xml = xml.replace("w:body", "w:absent")
    else:
        content = paragraph("Deep")
        for _ in range(10):
            content = table([cell(content=content)], 1)
        xml = xml.replace(paragraph("Closing note"), content)
    with pytest.raises((ValueError, DefusedXmlException)):
        extract(document(xml), "docx")


def test_content_controls_tabs_breaks_and_inert_hyperlinks():
    xml = document_xml().replace(
        paragraph("Closing note"),
        "<w:sdt><w:sdtPr/><w:sdtContent>"
        + paragraph("Controlled text")
        + "</w:sdtContent></w:sdt>",
    )
    xml = xml.replace("Controlled text", "Control</w:t><w:tab/><w:t>A</w:t><w:br/><w:t>B")
    xml = xml.replace(
        "Rubric requirements",
        "Requirements</w:t></w:r><w:hyperlink><w:r><w:t>visible link</w:t></w:r></w:hyperlink><w:r><w:t>suffix",
    )
    result = extract(document(xml), "docx")
    assert result["coverage"] == "text_only"
    assert any(r.get("text") == "Control\tA\nB" for r in records(result))
    assert "visible link" in records(result)[0]["text"]


def test_isolated_worker_preserves_merged_and_nested_tables(tmp_path):
    result = extract_isolated(document(), "docx", tmp_path / "parser")
    assert result["metadata"]["table_count"] == 3
    assert next(r for r in records(result) if r["id"] == "T1:R1C1")["row_span"] == 2
    assert not list((tmp_path / "parser" / "jobs").iterdir())


@pytest.fixture
async def readable_docx(bridge, owner, seeded, monkeypatch, tmp_path):
    data = document()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                filename="fictional.docx",
                display_name="fictional.docx",
                size=len(data),
                updated_at="2026-10-22T12:00:00Z",
                url="https://canvas.synthetic.invalid/files/51/download",
                **{"content-type": MIME},
            )
        ]
    }
    bridge.synthetic.data["file_bodies"], bridge.synthetic.data["file_types"] = (
        {"51": data},
        {"51": MIME},
    )
    bridge.settings.file_reading_enabled = True
    bridge.settings.parser_root = tmp_path / "parser"

    async def parse(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parse)
    _, courses = bridge.selected(owner, seeded)
    files = await list_files(bridge, owner, seeded, courses[0].id)
    return courses[0], files.data["files"][0]["file_id"]


async def test_continuation_search_cells_and_citations(bridge, owner, seeded, readable_docx):
    course, ref = readable_docx
    result = await read_docx(bridge, owner, seeded, ref, table_id="T1", max_records=3)
    items = result.data["records"][:]
    while result.data["continuation"]:
        result = await read_docx(bridge, owner, seeded, **result.data["continuation"])
        items.extend(result.data["records"])
    assert len(items) == len({i["id"] for i in items}) == 11
    assert all(i["table_id"] == "T1" for i in items)
    cell = next(i for i in items if i["id"] == "T1:R3C2")
    assert cell["source_reference"]["locator"] == "Table T1, R3C2"
    assert cell["source_reference"]["content_hash"] == result.data["content_hash"]
    assert cell["source_reference"]["url"].endswith("/files/51")
    assert (await status(bridge, owner, seeded, ref)).data["indexed"]
    assert (await read_file(bridge, owner, seeded, ref)).data["format"] == "docx"
    found = await search_files(bridge, owner, seeded, course.id, "Reproducible controls")
    assert found.data["results"] and "Reproducible controls" in found.data["results"][0]["passage"]
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1


async def test_response_byte_budget_continuation_does_not_skip_cells(
    bridge, owner, seeded, readable_docx
):
    _, ref = readable_docx
    rng = random.Random(19)
    rows = [
        "".join(cell("".join(rng.choices(string.ascii_letters, k=3000))) for _ in range(3))
        for _ in range(4)
    ]
    data = document(
        '<w:document xmlns:w="urn:word"><w:body>' + table(rows) + "</w:body></w:document>"
    )
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    result = await read_docx(bridge, owner, seeded, ref, table_id="T1", max_records=50)
    assert 1 < len(result.data["records"]) < 13
    assert result.data["continuation"]["offset"] == len(result.data["records"])
    seen = [r["id"] for r in result.data["records"]]
    while result.data["continuation"]:
        result = await read_docx(bridge, owner, seeded, **result.data["continuation"])
        assert len(json.dumps(result.data["records"], ensure_ascii=True)) < 61000
        seen.extend(r["id"] for r in result.data["records"])
    assert len(seen) == len(set(seen)) == 13


@pytest.mark.parametrize(
    "args", [{"table_id": "T99"}, {"table_id": "../../secret"}, {"offset": 1}, {"max_records": 0}]
)
async def test_invalid_selection_is_not_empty_success(bridge, owner, seeded, readable_docx, args):
    _, ref = readable_docx
    with pytest.raises(DomainError):
        await read_docx(bridge, owner, seeded, ref, **args)


async def test_existing_owner_version_and_access_boundaries(bridge, owner, seeded, readable_docx):
    _, ref = readable_docx
    first = await read_docx(bridge, owner, seeded, ref, max_records=1)
    other = await seed(bridge, "other-owner", "other-connection")
    with pytest.raises(DomainError):
        await read_docx(bridge, "other-owner", other, ref)
    changed = rewrite(
        bridge.synthetic.data["file_bodies"]["51"],
        "word/document.xml",
        lambda s: s.replace("10 points", "20 points"),
    )
    bridge.synthetic.data["file_bodies"]["51"] = changed
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(changed), updated_at="2026-10-23T12:00:00Z"
    )
    with pytest.raises(DomainError):
        await read_docx(bridge, owner, seeded, **first.data["continuation"])
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError):
        await read_docx(bridge, owner, seeded, ref)
    assert not (await status(bridge, owner, seeded, ref)).data["indexed"]
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_real_mcp_docx_cell_relationships(
    running, bridge, owner, seeded, readable_docx, token_factory, monkeypatch
):
    from canvas_bridge.parser_sandbox import extract_document

    _, ref = readable_docx
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", extract_document)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}, timeout=60
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                response = await session.call_tool(
                    "read_course_docx", {"connection_id": seeded, "file_id": ref, "table_id": "T1"}
                )
                result = response.structuredContent
                assert result["status"] == "ok"
                items = {r["id"]: r for r in result["data"]["records"]}
                assert items["T1:R2C1"]["merge_origin"] == "T1:R1C1"
                assert items["T1:R1C1"]["row_span"] == 2
                assert items["T1:R1C1"]["source_reference"]["locator"] == "Table T1, R1C1"
                assert "download" not in json.dumps(result)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
