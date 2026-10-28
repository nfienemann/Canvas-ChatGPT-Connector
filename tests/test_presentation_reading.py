"""Synthetic large decks and hostile OOXML, never real academic records."""

import io
import os
import zipfile

import httpx
import pytest

from canvas_bridge.course_files import list_files, read_file
from canvas_bridge.document_policy import PPTX_SOURCE_BYTES, PresentationLimit
from canvas_bridge.domain import DomainError
from canvas_bridge.file_download import download_file
from canvas_bridge.parser_sandbox import extract_isolated, validate_result
from canvas_bridge.parser_worker import extract
from canvas_bridge.visual_files import render_file
from tests.test_academic_intelligence import ooxml
from tests.test_course_files import Body, file_record
from tests.test_course_files import file_client as file_client

MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def deck(texts=None, changes=None, target_size=None, compression=zipfile.ZIP_STORED):
    with zipfile.ZipFile(io.BytesIO(ooxml("pptx", texts))) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    parts.update(changes or {})
    if target_size:
        parts["ppt/media/padding.dat"] = b""

    def build():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        return stream.getvalue()

    if target_size:
        parts["ppt/media/padding.dat"] = b"z" * (target_size - len(build()))
    return build()


def rich_deck():
    return deck(
        ["", "Synthetic fluorescence experiment"],
        {
            "ppt/slides/_rels/slide2.xml.rels": '<Relationships><Relationship Id="img" Type="a/image" Target="../media/image.png"/>'
            '<Relationship Id="notes" Type="a/notesSlide" Target="../notesSlides/notesSlide1.xml"/>'
            '<Relationship Id="chart" Type="a/chart" Target="../charts/chart1.xml"/>'
            '<Relationship Id="external" Type="a/image" TargetMode="External" Target="https://private.invalid/secret"/></Relationships>',
            "ppt/media/image.png": b"fixture only: not decoded during text extraction",
            "ppt/notesSlides/notesSlide1.xml": '<notes><sp><ph type="body"/><p><t>Repeat controls before drawing conclusions.</t></p></sp>'
            '<sp><ph type="sldNum"/><p><t>999</t></p></sp></notes>',
            "ppt/charts/chart1.xml": "<chart><title><p><t>Control versus treatment</t></p></title><strCache><v>Control</v></strCache><numCache><v>2.5</v></numCache></chart>",
            "ppt/slides/_rels/slide1.xml.rels": '<Relationships><Relationship Id="img" Type="a/image" Target="../media/image.png"/></Relationships>',
        },
    )


@pytest.mark.parametrize("size", [14_176_811, 25_000_000, 25 * 1024 * 1024, PPTX_SOURCE_BYTES])
def test_substantial_deck_text_does_not_inflate_media(size):
    data = deck(target_size=size)
    result = extract(data, "pptx")
    assert len(data) == size
    assert result["resource_usage"]["zip_read_bytes"] < 5000
    assert result["page_count"] == 2 and "Methods" in result["pages"][0]["text"]
    validate_result({"ok": True, "extraction": result}, data)


@pytest.mark.parametrize("size", [PPTX_SOURCE_BYTES + 1, 41_189_003])
def test_higher_tier_is_explicitly_rejected(size):
    with pytest.raises(ValueError, match="file_too_large"):
        extract(deck(target_size=size), "pptx")


def test_slide_text_notes_chart_caches_and_empty_image_slide_have_provenance():
    data = rich_deck()
    result = extract(data, "pptx")
    first, blank = result["pages"]
    assert first["slide_number"] == 1 and "fluorescence" in first["text"]
    assert "2.5" in first["text"] and "Repeat controls" in first["text"]
    assert "999" not in first["text"]
    assert {s["source_kind"] for s in first["text_spans"]} == {
        "slide_shapes_and_tables",
        "chart_cached_text_and_values",
        "speaker_notes",
    }
    assert first["media_presence"]["images"] == 1
    assert first["media_presence"]["external_relationships"] == 1
    assert "private.invalid" not in str(result)
    assert blank["text"] == "" and blank["state"] == "no_text"
    assert blank["media_presence"]["images"] == 1
    assert result["coverage"] == "partial"
    for page in result["pages"]:
        assert page["visual_observation"] is None
        assert page["visual_render_status"] == "not_rendered"
        assert not page["media_presence"]["graphics_inspected"]
    validate_result({"ok": True, "extraction": result}, data)


@pytest.mark.parametrize(
    "name",
    ["../escape.xml", "/root.xml", "ppt\\bad.xml", "C:/bad.xml", "ppt/../bad.xml", "ppt/./bad.xml"],
)
def test_zip_paths_are_rejected(name):
    data = deck(changes={name: "<xml/>"})
    if "\\" in name:
        # Windows ZipInfo normalizes paths on write; forge the actual ZIP name.
        data = data.replace(name.replace("\\", "/").encode(), name.encode())
    with pytest.raises(ValueError, match="invalid_pptx_archive"):
        extract(data, "pptx")


@pytest.mark.parametrize(
    "change",
    [
        {"ppt/vbaProject.bin": b"macro"},
        {"ppt/embeddings/oleObject1.bin": b"OLE"},
        {"ppt/activeX/activeX1.xml": "<active/>"},
        {
            "[Content_Types].xml": '<Types><Override ContentType="application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"/></Types>'
        },
    ],
)
def test_active_content_never_executes(change):
    with pytest.raises(ValueError, match="active_office_content"):
        extract(deck(changes=change), "pptx")


def test_safe_embedded_chart_workbook_is_not_opened():
    parsed = extract(deck(changes={"ppt/embeddings/data.xlsx": b"not parsed"}), "pptx")
    assert parsed["coverage"] == "text_only"


@pytest.mark.parametrize(
    "changes,compression,budget",
    [
        ({"ppt/media/bomb.dat": b"z" * 200_000}, zipfile.ZIP_DEFLATED, "zip_compression_ratio"),
        ({"ppt/big.xml": b"z" * (4 * 1024 * 1024 + 1)}, zipfile.ZIP_STORED, "xml_member_bytes"),
        ({f"empty/{i}": b"" for i in range(4097)}, zipfile.ZIP_STORED, "zip_members"),
    ],
)
def test_zip_limits_report_numeric_budget(changes, compression, budget):
    with pytest.raises(PresentationLimit) as caught:
        extract(deck(changes=changes, compression=compression), "pptx")
    assert caught.value.details["budget"] == budget
    assert caught.value.details["observed"] > caught.value.details["limit"]
    with pytest.raises(DomainError) as public:
        validate_result(
            {"ok": False, "reason": "pptx_expansion_limit", "details": caught.value.details}, b""
        )
    assert public.value.reason_code == "PPTX_EXPANSION_LIMIT"
    assert public.value.processing_stage == "zip_expansion"


def test_slide_count_corruption_entities_and_truncation_are_honest(monkeypatch):
    with pytest.raises(PresentationLimit) as caught:
        extract(deck(["x"] * 201), "pptx")
    assert caught.value.details["budget"] == "slide_count"
    data = deck(
        changes={
            "ppt/slides/slide1.xml": '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///private">]><s>&x;</s>'
        }
    )
    result = extract(data, "pptx")
    assert result["pages"][1]["state"] == "unreadable" and result["pages"][0]["text"]
    assert result["coverage"] == "partial"
    monkeypatch.setattr("canvas_bridge.parser_worker.MAX_TEXT", 10)
    result = extract(deck(["must be omitted", "0123456789"]), "pptx")
    assert len(result["pages"]) == 1 and result["coverage"] == "partial"
    assert len(result["pages"][0]["text"]) == 10


@pytest.mark.parametrize("mutation", ["observation", "inspected", "spans"])
def test_parent_rejects_fabricated_worker_observation_or_provenance(mutation):
    data = rich_deck()
    result = extract(data, "pptx")
    if mutation == "observation":
        result["pages"][0]["visual_observation"] = "invented microscopy result"
    elif mutation == "inspected":
        result["pages"][0]["media_presence"]["graphics_inspected"] = True
    else:
        result["pages"][0]["text_spans"][0]["end"] = 900_000
    with pytest.raises(ValueError):
        validate_result({"ok": True, "extraction": result}, data)


@pytest.mark.parametrize("size", [14_176_811, 25_000_000, PPTX_SOURCE_BYTES])
@pytest.mark.parametrize("known_size", [False, True])
async def test_bounded_stream_accepts_large_pptx_without_content_length(
    file_client, size, known_size
):
    client, provider = file_client
    data = deck(target_size=size)
    provider.data["files"]["11"][0].update(
        filename="synthetic.pptx", size=size if known_size else None, **{"content-type": MIME}
    )
    body = Body(*(data[i : i + 65536] for i in range(0, len(data), 65536)))
    response = httpx.Response(200, stream=body, headers={"Content-Type": MIME})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as http:
        result = await download_file(client, "11", "51", http=http)
    assert result.byte_size == size and result.data == data and body.closed


@pytest.mark.parametrize("declared", [None, str(PPTX_SOURCE_BYTES + 1)])
async def test_oversized_unknown_stream_closes_and_preserves_legacy_code(file_client, declared):
    client, provider = file_client
    provider.data["files"]["11"][0].update(
        filename="synthetic.pptx", size=None, **{"content-type": MIME}
    )
    body = Body(b"z" * (PPTX_SOURCE_BYTES + 1))
    response = httpx.Response(
        200,
        stream=body,
        headers={"Content-Type": MIME, **({"Content-Length": declared} if declared else {})},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as http:
        with pytest.raises(DomainError) as caught:
            await download_file(client, "11", "51", http=http)
    assert caught.value.reason_code == "FILE_TOO_LARGE"
    assert caught.value.data["budget_code"] == "SOURCE_FILE_TOO_LARGE"
    assert caught.value.data["observed"] > caught.value.data["limit"]
    assert body.closed


@pytest.fixture
async def presentation(bridge, owner, seeded, monkeypatch):
    body = deck([""] * 17)
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                size=len(body),
                filename="test.pptx",
                updated_at="2026-10-22T12:00:00Z",
                url="https://canvas.synthetic.invalid/files/51/download",
                **{"content-type": MIME},
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": body}
    bridge.synthetic.data["file_types"] = {"51": MIME}
    bridge.settings.file_reading_enabled = True

    async def fixture_parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", fixture_parser)
    _, courses = bridge.selected(owner, seeded)
    listing = await list_files(bridge, owner, seeded, courses[0].id)
    return listing.data["files"][0]["file_id"]


async def test_blank_slides_are_paginated_and_cited_without_fake_text(
    bridge, owner, seeded, presentation
):
    result = await read_file(bridge, owner, seeded, presentation)
    seen = []
    while True:
        assert result.status == "partial_data"
        assert len(result.data["slides"]) <= 8
        assert all(s["visual_observation"] is None for s in result.data["slides"])
        seen.extend(s["slide_number"] for s in result.data["slides"])
        assert all(s.locator.startswith("Slide") for s in result.sources)
        c = result.data["continuation"]
        if not c:
            break
        result = await read_file(bridge, owner, seeded, **c)
    assert seen == list(range(1, 18))
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1


async def test_renderer_gap_is_typed_before_download_and_permission_is_rechecked(
    bridge, owner, seeded, presentation
):
    with pytest.raises(DomainError) as unavailable:
        await render_file(bridge, owner, seeded, presentation)
    assert unavailable.value.reason_code == "PPTX_RENDERER_UNAVAILABLE"
    assert not any("download" in r.url.path for r in bridge.synthetic.requests)
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError) as denied:
        await render_file(bridge, owner, seeded, presentation)
    assert denied.value.status == "permission_denied"


async def test_unicode_batches_fit_mcp_and_continuation_version_is_enforced(
    bridge, owner, seeded, presentation
):
    data = deck(["漢𐐀" * 1000] * 17)
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(data), updated_at="2026-10-23T00:00:00Z"
    )
    first = await read_file(bridge, owner, seeded, presentation, length=16000)
    assert len(first.data["text"]) == 8000
    assert len(first.model_dump_json().encode()) < 250000
    assert first.data["continuation"]
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError) as denied:
        await read_file(bridge, owner, seeded, **first.data["continuation"])
    assert denied.value.status == "permission_denied"


@pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer proof")
@pytest.mark.parametrize("size", [14_176_811, 25_000_000])
def test_large_presentation_in_real_appcontainer(size, tmp_path):
    result = extract_isolated(deck(target_size=size), "pptx", tmp_path / "parser")
    assert result["page_count"] == 2
    assert result["resource_usage"]["source_bytes"] == size
    assert all(p["visual_observation"] is None for p in result["pages"])
