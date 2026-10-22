"""Known-answer DOCX regressions using fictional documents only."""

import io
import json
import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.course_files import list_files, read_file, search_files, status
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_document, extract_isolated
from canvas_bridge.parser_worker import PARSER, extract
from canvas_bridge.retrieval import fetch_material
from canvas_bridge.storage import Material
from tests.test_academic_intelligence import academic as academic
from tests.test_course_files import file_record
from tests.test_mcp_contract import running as running

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def paragraph(text):
    return '<w:p><w:r><w:t xml:space="preserve">' + escape(text) + "</w:t></w:r></w:p>"


def docx(body=None, *, changes=None):
    """Small OOXML package; no Word installation or real coursework needed."""
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": (
            f'<w:document xmlns:w="{WORD}" xmlns:v="urn:schemas-microsoft-com:vml" '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<w:body>"
            + (body if body is not None else paragraph("Synthetic assignment."))
            + "<w:sectPr/></w:body></w:document>"
        ),
    }
    parts.update(changes or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            if content is not None:
                archive.writestr(name, content)
    return stream.getvalue()


def text_of(data):
    return "\n\n".join(p["text"] for p in extract(data, "docx")["pages"])


def test_docx_run_boundaries_breaks_links_and_table_order():
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Exam </w:t></w:r>'
        "<w:r><w:t>1: November </w:t></w:r><w:r><w:t>12, 2026</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Alpha</w:t><w:cr/><w:t>Beta</w:t><w:br/>"
        "<w:t>Gamma</w:t><w:tab/><w:t>Delta</w:t></w:r>"
        '<w:hyperlink r:id="external"><w:r><w:t> link label</w:t></w:r></w:hyperlink></w:p>'
        "<w:tbl><w:tr><w:tc>"
        + paragraph("First cell")
        + "</w:tc><w:tc>"
        + paragraph("Second cell")
        + "</w:tc></w:tr><w:tr><w:tc>"
        + paragraph("Third cell")
        + "</w:tc></w:tr></w:tbl>"
        + paragraph("Unicode: β-catenin and café.")
    )
    assert text_of(docx(body)) == (
        "Exam 1: November 12, 2026\nAlpha\nBeta\nGamma\tDelta link label\n"
        "First cell\nSecond cell\nThird cell\nUnicode: β-catenin and café."
    )


def test_docx_nested_textbox_is_not_duplicated_or_joined_to_surrounding_words():
    body = (
        "<w:p><w:r><w:t>Before box</w:t><w:pict><v:shape><v:textbox><w:txbxContent>"
        + paragraph("Box line one")
        + paragraph("Box line two")
        + "</w:txbxContent></v:textbox></v:shape></w:pict><w:t>After box</w:t></w:r></w:p>"
    )
    assert text_of(docx(body)) == "Before box\nBox line one\nBox line two\nAfter box"


def test_docx_revision_and_compatibility_policy_does_not_duplicate_content():
    body = (
        "<w:moveFrom>" + paragraph("Old moved deadline") + "</w:moveFrom>"
        "<w:del>" + paragraph("Deleted instruction") + "</w:del>"
        "<w:ins>" + paragraph("Current instruction") + "</w:ins>"
        "<w:moveTo>" + paragraph("Current deadline") + "</w:moveTo>"
        '<mc:AlternateContent><mc:Choice Requires="v">'
        + paragraph("Modern box")
        + "</mc:Choice><mc:Fallback>"
        + paragraph("Compatible box")
        + "</mc:Fallback></mc:AlternateContent>"
    )
    assert text_of(docx(body)) == "Current instruction\nCurrent deadline\nCompatible box"


@pytest.mark.parametrize(
    "changes",
    [
        {"word/document.xml": None},
        {"word/document.xml": f'<w:document xmlns:w="{WORD}"/>'},
        {"word/document.xml": "<unrelated><p><t>not Word</t></p></unrelated>"},
    ],
)
def test_docx_invalid_main_document_has_a_specific_reason(changes):
    with pytest.raises(ValueError, match="invalid_docx_structure"):
        extract(docx(changes=changes), "docx")


def test_docx_empty_body_has_one_readable_section_with_partial_coverage():
    result = extract(docx(""), "docx")
    assert result["page_count"] == 1
    assert result["pages"] == [
        {"page": 1, "text": "", "state": "no_text", "locator_kind": "section"}
    ]
    assert result["coverage"] == "partial"


def reading_body():
    return (
        "<w:p><w:r><w:t>Exam </w:t></w:r><w:r><w:t>1: November </w:t></w:r>"
        "<w:r><w:t>12, 2026</w:t></w:r></w:p>"
        + paragraph("Write 1,000 words. Include a methods section.")
        + paragraph(" ".join(f"sample{i:04d}" for i in range(720)))
        + paragraph("Conclusion: verify the fictional experiment with independent cultures.")
    )


@pytest.fixture
async def word_file(bridge, owner, seeded, monkeypatch):
    data = docx(reading_body())
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                filename="synthetic.docx",
                display_name="synthetic.docx",
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
        "11": [{"title": "synthetic.docx", "type": "File", "content_id": 51}]
    }
    bridge.settings.file_reading_enabled = True

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    course = bridge.selected(owner, seeded)[1][0]
    listed = await list_files(bridge, owner, seeded, course.id)
    return course, listed.data["files"][0]["file_id"]


async def test_docx_reads_search_sections_and_continuations_agree(bridge, owner, seeded, word_file):
    course, ref = word_file
    before = (await status(bridge, owner, seeded, ref)).data
    assert before["format_supported"] and before["extraction_outcome"] == "not_attempted"
    cached = await search_files(bridge, owner, seeded, course.id, "Exam")
    assert cached.status == "partial_data" and not cached.data["results"]
    assert ref in [f["file_id"] for f in cached.data["unindexed_documents"]]
    first = await read_file(bridge, owner, seeded, ref, length=733)
    current, reconstructed = first, first.data["text"]
    while current.data["continuation"]:
        current = await read_file(bridge, owner, seeded, length=733, **current.data["continuation"])
        reconstructed += current.data["text"]
    full = await fetch_material(bridge, owner, seeded, ref, length=16000)
    assert reconstructed == full.data["text"] == text_of(docx(reading_body()))
    assert full.data["page_count"] == 2
    assert "Section 1" not in reconstructed
    assert "Exam 1: November 12, 2026" in reconstructed
    repeated = await read_file(bridge, owner, seeded, ref, length=733)
    assert repeated.data["chunk_id"] == first.data["chunk_id"]
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1
    section = await read_file(bridge, owner, seeded, ref, page_start=2, page_end=2)
    assert section.data["text"].startswith("Conclusion:")
    assert "Exam" not in section.data["text"]
    assert "Section 2 (not a rendered page)" in section.sources[0].locator
    for unread in (False, True):
        found = await search_files(
            bridge, owner, seeded, course.id, "November 12, 2026", include_unread=unread
        )
        assert found.data["results"][0]["page"] == 1
        assert found.data["results"][0]["content_hash"] == first.data["content_hash"]
    after = (await status(bridge, owner, seeded, ref)).data
    assert after["extraction_outcome"] == "parsed" and after["indexed"]
    assert after["reason_code"] is None and after["parser"] == PARSER


async def test_docx_hash_guards_permission_and_version_changes(bridge, owner, seeded, word_file):
    _, ref = word_file
    with pytest.raises(DomainError) as missing:
        await read_file(bridge, owner, seeded, ref, offset=1)
    assert missing.value.reason_code == "CONTINUATION_HASH_REQUIRED"
    assert not any("download" in r.url.path for r in bridge.synthetic.requests)
    first = await read_file(bridge, owner, seeded, ref, length=100)
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, ref, offset=1, expected_hash="0" * 64)
    revised = docx(paragraph("Revised synthetic instructions."))
    bridge.synthetic.data["file_bodies"]["51"] = revised
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(revised), updated_at="2026-10-22T13:00:00Z"
    )
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, **first.data["continuation"])
    with pytest.raises(DomainError):
        await read_file(bridge, "different-owner", seeded, ref)
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    assert (await status(bridge, owner, seeded, ref)).data["state"] == "inaccessible"
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text


@pytest.mark.parametrize("stage", ["parsed", "unsupported", "failed"])
async def test_docx_old_parser_cache_is_invalidated(bridge, owner, seeded, word_file, stage):
    _, ref = word_file
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.text, row.version_hash = "old parser text", "old hash"
        row.file_state = {
            "stage": stage,
            "parser": "canvas-bridge-documents-v5-xlsx",
            "reason": "old failure",
        }
    before = (await status(bridge, owner, seeded, ref)).data
    assert before["extraction_outcome"] == "not_attempted" and before["reason"] is None
    assert (await read_file(bridge, owner, seeded, ref)).data["parser"] == PARSER


@pytest.mark.parametrize(
    "reason,stage,code",
    [
        ("retry_later", "runtime_setup", "DOCUMENT_RUNTIME_SETUP_FAILED"),
        ("retry_later", "worker_execution", "DOCUMENT_WORKER_TIMEOUT"),
        ("unsupported_feature", "text_extraction", "EXTRACTION_CORRUPT_OR_UNREADABLE"),
        ("unsupported_feature", "text_extraction", "EXTRACTION_INVALID_DOCX_STRUCTURE"),
        ("unsupported_feature", "text_extraction", "EXTRACTION_OFFICE_RESOURCE_LIMIT"),
        ("unsupported_feature", "result_read", "DOCUMENT_OUTPUT_LIMIT"),
    ],
)
async def test_docx_processing_failure_status_search_and_retry(
    bridge, owner, seeded, word_file, monkeypatch, reason, stage, code
):
    course, ref = word_file

    async def fail(*args):
        raise DomainError(
            reason, "Synthetic processing failure.", reason_code=code, processing_stage=stage
        )

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", fail)
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref)
    state = (await status(bridge, owner, seeded, ref)).data
    assert state["state"] == state["extraction_outcome"] == "failed"
    assert state["format_supported"] and state["access_state"] == "available"
    assert not state["indexed"] and state["reason_code"] == code
    assert state["processing_stage"] == stage
    found = await search_files(bridge, owner, seeded, course.id, "Exam", include_unread=True)
    assert found.status == "partial_data"
    assert found.data["document_statuses"][0]["state"] == "failed"
    assert found.data["document_statuses"][0]["reason_code"] == code

    async def repaired(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", repaired)
    assert (await read_file(bridge, owner, seeded, ref)).status == "ok"
    assert (await status(bridge, owner, seeded, ref)).data["reason_code"] is None


@pytest.mark.skipif(
    os.name != "nt", reason="Actual Windows AppData and AppContainer DOCX regression"
)
def test_docx_actual_worker_structural_failures_and_cleanup():
    root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    for data, code in [
        (docx(changes={"word/document.xml": None}), "EXTRACTION_INVALID_DOCX_STRUCTURE"),
        (
            docx(changes={"word/document.xml": "<private-synthetic-canary"}),
            "EXTRACTION_CORRUPT_OR_UNREADABLE",
        ),
    ]:
        with pytest.raises(DomainError) as error:
            extract_isolated(data, "docx", root)
        assert error.value.reason_code == code
        assert error.value.processing_stage == "text_extraction"
        assert "canary" not in str(error.value) + json.dumps(error.value.data)


@pytest.mark.contract
@pytest.mark.skipif(os.name != "nt", reason="Real DOCX worker through HTTP MCP on Windows")
async def test_docx_mcp_transport_uses_actual_worker(
    running, token_factory, seeded, word_file, bridge, monkeypatch
):
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", extract_document)
    bridge.settings.parser_root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    bridge.settings.ocr_root = bridge.settings.parser_root / "missing-optional-ocr"
    course, ref = word_file
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                args = {"connection_id": seeded, "file_id": ref}
                before = await session.call_tool("get_file_extraction_status", args)
                assert before.structuredContent["data"]["extraction_outcome"] == "not_attempted"
                for invalid in ({"page_start": 0}, {"offset": -1}):
                    rejected = await session.call_tool("read_course_file", {**args, **invalid})
                    assert rejected.isError
                reversed_range = await session.call_tool(
                    "read_course_file", {**args, "page_start": 2, "page_end": 1}
                )
                assert reversed_range.structuredContent["status"] == "needs_input"
                missing = await session.call_tool("read_course_file", {**args, "offset": 1})
                assert (
                    missing.structuredContent["data"]["reason_code"] == "CONTINUATION_HASH_REQUIRED"
                )
                first = await session.call_tool("read_course_file", {**args, "length": 3000})
                assert not first.isError and first.structuredContent["status"] == "ok"
                mismatch = await session.call_tool(
                    "read_course_file", {**args, "offset": 1, "expected_hash": "0" * 64}
                )
                assert mismatch.structuredContent["status"] == "source_changed"
                data = first.structuredContent["data"]
                reconstructed = data["text"]
                while data["continuation"]:
                    part = await session.call_tool(
                        "read_course_file",
                        {"connection_id": seeded, **data["continuation"], "length": 3000},
                    )
                    assert part.structuredContent["status"] == "ok"
                    data = part.structuredContent["data"]
                    reconstructed += data["text"]
                full = await session.call_tool(
                    "fetch_course_material",
                    {"connection_id": seeded, "material_id": ref, "length": 16000},
                )
                assert (
                    reconstructed
                    == full.structuredContent["data"]["text"]
                    == text_of(docx(reading_body()))
                )
                section = await session.call_tool(
                    "read_course_file", {**args, "page_start": 2, "page_end": 2}
                )
                assert section.structuredContent["data"]["text"].startswith("Conclusion:")
                found = await session.call_tool(
                    "search_course_files",
                    {"connection_id": seeded, "course_id": course.id, "query": "November 12, 2026"},
                )
                assert found.structuredContent["data"]["results"][0]["page"] == 1
                rendered = await session.call_tool("render_course_file_page", {**args, "page": 1})
                assert rendered.structuredContent["status"] == "unsupported_feature"
                assert "PDF only" in rendered.structuredContent["summary"]
                after = await session.call_tool("get_file_extraction_status", args)
                assert after.structuredContent["data"]["extraction_outcome"] == "parsed"
                assert after.structuredContent["data"]["indexed"]

                broken = docx(changes={"word/document.xml": None})
                bridge.synthetic.data["file_bodies"]["51"] = broken
                bridge.synthetic.data["files"]["11"][0].update(
                    size=len(broken), updated_at="2026-10-22T13:00:00Z"
                )
                rejected = await session.call_tool(
                    "fetch_course_material", {"connection_id": seeded, "material_id": ref}
                )
                assert (
                    rejected.structuredContent["data"]["reason_code"]
                    == "EXTRACTION_INVALID_DOCX_STRUCTURE"
                )
                failed = (
                    await session.call_tool("get_file_extraction_status", args)
                ).structuredContent["data"]
                assert failed["extraction_outcome"] == "failed" and failed["format_supported"]
                assert failed["reason_code"] == "EXTRACTION_INVALID_DOCX_STRUCTURE"
                assert not failed["indexed"]


async def test_docx_split_run_deadline_reaches_academic_rules_without_locator_labels(
    bridge, owner, seeded, academic, word_file
):
    from canvas_bridge.academic_intelligence import academic_request

    course, ref = word_file
    compared = await academic_request(bridge, owner, seeded, course.id, material_ids=[ref])
    assert any(f["kind"] == "missing_canvas_deadline" for f in compared.data["findings"])
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        assert row.text.startswith("Exam 1: November 12, 2026\nWrite 1,000 words.")
        assert "Section 1" not in row.text


@pytest.mark.parametrize("characters", [250_000, 250_001])
def test_docx_text_limit_discloses_unread_remainder(characters):
    long_text = " ".join(f"word{i:05d}" for i in range(30_000))[:characters]
    result = extract(docx(paragraph(long_text) + paragraph("Unread final paragraph")), "docx")
    assert result["coverage"] == "partial"
    assert len(result["pages"][0]["text"]) == 250_000
    assert result["page_count"] == 2 and len(result["pages"]) == 1
    assert any("limit" in warning and "remaining" in warning for warning in result["warnings"])


def test_docx_strict_namespace_and_non_word_text():
    body = (
        paragraph("Word text")
        + '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>not ordinary text</m:t></m:r></m:oMath>'
    )
    xml = (f'<w:document xmlns:w="{WORD}"><w:body>{body}</w:body></w:document>').replace(
        WORD, "http://purl.oclc.org/ooxml/wordprocessingml/main"
    )
    assert text_of(docx(changes={"word/document.xml": xml})) == "Word text"


@pytest.mark.parametrize(
    "body",
    [
        f'<!DOCTYPE w:document [<!ENTITY x "unsafe">]><w:document xmlns:w="{WORD}"><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>',
        f'<!DOCTYPE w:document SYSTEM "https://synthetic.invalid/external.dtd"><w:document xmlns:w="{WORD}"><w:body/></w:document>',
    ],
)
def test_docx_xml_dtd_and_entities_are_rejected(body):
    from defusedxml.common import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        extract(docx(changes={"word/document.xml": body}), "docx")
