"""Synthetic scientific slides only: structure, pixels, transport and boundaries."""

import base64
import io
import json
import struct
import zipfile
import zlib

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

from canvas_bridge.course_files import list_files, search_files, status
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_isolated
from canvas_bridge.parser_worker import extract
from canvas_bridge.presentation_worker import render_picture
from canvas_bridge.presentations import read_picture, read_presentation
from tests.conftest import seed
from tests.test_academic_intelligence import office_manifest
from tests.test_course_files import file_record
from tests.test_mcp_contract import running as running
from tests.test_workbooks import rewrite

MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def paragraph(text):
    return f'<a:p><a:pPr lvl="1"><a:buChar char="•"/></a:pPr><a:r><a:t>{text}</a:t></a:r></a:p>'


def shape(text, index=1, placeholder="body"):
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{index}" name="Text {index}"/><p:cNvSpPr/><p:nvPr><p:ph type="{placeholder}"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paragraph(text)}</p:txBody></p:sp>'


def picture():
    return '<p:pic><p:nvPicPr><p:cNvPr id="20" name="Synthetic figure" descr="Unverified diagram description"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="img"/><a:srcRect l="1000"/></p:blipFill><p:spPr><a:xfrm rot="5400000"><a:off x="100" y="200"/><a:ext cx="300" cy="400"/></a:xfrm></p:spPr></p:pic>'


def presentation(image_only=False):
    output = io.BytesIO()
    image = io.BytesIO()
    with Image.new("RGB", (120, 80), "#2488aa") as pixels:
        pixels.save(image, format="PNG")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        office_manifest(archive, "pptx")
        # Source filenames deliberately disagree with actual presentation order.
        archive.writestr(
            "ppt/presentation.xml",
            f'<p:presentation {NS}><p:sldIdLst><p:sldId id="2" r:id="s2"/><p:sldId id="1" r:id="s1"/></p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships><Relationship Id="s1" Type="http://example/slide" Target="slides/slide1.xml"/><Relationship Id="s2" Type="http://example/slide" Target="slides/slide2.xml"/></Relationships>',
        )
        table = '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="3" name="Results"/></p:nvGraphicFramePr><a:graphic><a:graphicData><a:tbl><a:tblGrid><a:gridCol w="400"/><a:gridCol w="400"/></a:tblGrid>'
        table += (
            '<a:tr h="200"><a:tc gridSpan="2"><a:txBody>'
            + paragraph("Synthetic measurements")
            + '</a:txBody></a:tc><a:tc hMerge="1"><a:txBody/></a:tc></a:tr>'
        )
        table += (
            '<a:tr h="200"><a:tc><a:txBody>'
            + paragraph("Control")
            + "</a:txBody></a:tc><a:tc><a:txBody>"
            + paragraph("5.3")
            + "</a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
        )
        group = (
            '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="4" name="Group"/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="10" y="20"/><a:chOff x="0" y="0"/></a:xfrm></p:grpSpPr>'
            + shape("Mechanism in controlled cultures", 5)
            + "</p:grpSp>"
        )
        content = (
            picture()
            if image_only
            else shape("Differentiation", placeholder="title") + table + group + picture()
        )
        archive.writestr(
            "ppt/slides/slide2.xml",
            f"<p:sld {NS}><p:cSld><p:spTree>{content}</p:spTree></p:cSld></p:sld>",
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            f'<p:sld {NS} show="0"><p:cSld><p:spTree>{shape("Hidden review", placeholder="title")}</p:spTree></p:cSld></p:sld>',
        )
        archive.writestr(
            "ppt/slides/_rels/slide2.xml.rels",
            '<Relationships><Relationship Id="notes" Type="http://example/notesSlide" Target="../notesSlides/notesSlide1.xml"/><Relationship Id="img" Type="http://example/image" Target="../media/image1.png"/></Relationships>',
        )
        notes = "" if image_only else "Instructor explains experimental controls"
        archive.writestr(
            "ppt/notesSlides/notesSlide1.xml",
            f"<p:notes {NS}><p:cSld><p:spTree>{shape(notes)}{shape('999', 2, 'sldNum')}</p:spTree></p:cSld></p:notes>",
        )
        archive.writestr("ppt/media/image1.png", image.getvalue())
    return output.getvalue()


def test_slide_order_group_structure_notes_tables_and_provenance():
    data = presentation()
    result = extract(data, "pptx")
    assert result["coverage"] == "partial"
    assert result["metadata"]["slides"][0]["title"] == "Differentiation"
    assert result["metadata"]["slides"][1]["hidden"]
    page = result["pages"][0]
    assert [o["kind"] for o in page["objects"]] == ["sp", "table", "grpSp", "sp", "picture"]
    assert page["objects"][3]["group_index"] == 3
    assert page["objects"][4]["transform"]["attributes"]["rot"] == "5400000"
    cells = page["objects"][1]["table"]["cells"]
    assert cells[0]["column_span"] == "2" and cells[1]["horizontal_merge"]
    assert cells[3]["row"] == 2 and cells[3]["column"] == 2 and cells[3]["text"] == "5.3"
    assert page["notes"][0]["text"] == "Instructor explains experimental controls"
    assert "999" not in page["text"]
    assert "speaker notes paragraph 1" in page["text"]
    assert "table R2C2" in page["text"]
    assert page["objects"][0]["paragraphs"][0]["level"] == "1"
    assert extract(data, "pptx") == result


@pytest.mark.parametrize(
    "case",
    [
        "empty_notes",
        "absent_notes",
        "vertical_merge",
        "background",
        "oversize_pixels",
        "corrupt_picture",
        "notes_limit",
    ],
)
def test_partial_coverage_and_resource_edges(case):
    data = presentation()
    if case == "empty_notes":
        data = rewrite(
            data,
            "ppt/notesSlides/notesSlide1.xml",
            lambda s: s.replace("Instructor explains experimental controls", ""),
        )
        assert extract(data, "pptx")["pages"][0]["notes_state"] == "present_empty"
    elif case == "absent_notes":
        data = rewrite(
            data,
            "ppt/slides/_rels/slide2.xml.rels",
            lambda s: s.replace('Type="http://example/notesSlide"', 'Type="http://example/unused"'),
        )
        assert extract(data, "pptx")["pages"][0]["notes_state"] == "absent"
    elif case == "vertical_merge":
        data = rewrite(
            data,
            "ppt/slides/slide2.xml",
            lambda s: s.replace('gridSpan="2"', 'rowSpan="2"').replace('hMerge="1"', 'vMerge="1"'),
        )
        cells = extract(data, "pptx")["pages"][0]["objects"][1]["table"]["cells"]
        assert cells[0]["row_span"] == "2" and cells[1]["vertical_merge"]
    elif case == "background":
        data = rewrite(
            data,
            "ppt/slides/slide1.xml",
            lambda s: s.replace(
                "<p:spTree>", '<p:bg><a:blip r:embed="unread_background"/></p:bg><p:spTree>'
            ),
        )
        assert extract(data, "pptx")["pages"][1]["visual_review_required"]
    elif case == "notes_limit":
        data = rewrite(
            data,
            "ppt/notesSlides/notesSlide1.xml",
            lambda s: s.replace("</p:txBody>", paragraph("extra") * 201 + "</p:txBody>"),
        )
        with pytest.raises(ValueError, match="presentation_resource_limit"):
            extract(data, "pptx")
    else:
        raw = b"not a picture"
        if case == "oversize_pixels":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                raw = archive.read("ppt/media/image1.png")
            header = struct.pack(">II", 4000, 4000) + raw[24:29]
            raw = raw[:16] + header + struct.pack(">I", zlib.crc32(b"IHDR" + header)) + raw[33:]
        data = replace_member(data, "ppt/media/image1.png", raw)
        with pytest.raises((ValueError, OSError)):
            render_picture(data, 1, 5)


@pytest.mark.parametrize(
    "args",
    [
        {"slide": 3},
        {"slide": 1, "offset": 1},
        {"slide": 1, "offset": 100, "expected_hash": "a" * 64},
        {"max_objects": 31},
    ],
)
async def test_invalid_selection_never_becomes_empty_success(
    bridge, owner, seeded, readable_presentation, args
):
    _, ref = readable_presentation
    with pytest.raises(DomainError):
        await read_presentation(bridge, owner, seeded, ref, **args)


def test_image_only_not_empty_complete_and_pixels_decoded_without_slide_claim():
    result = extract(presentation(True), "pptx")
    assert result["coverage"] == "partial" and result["pages"][0]["text"] == ""
    assert result["pages"][0]["notes_state"] == "present_empty"
    image = render_picture(presentation(True), 1, 1)
    assert image["image_locator"] == "Slide 1, object 1"
    assert "not a rendered slide" in image["coverage"]
    with Image.open(io.BytesIO(base64.b64decode(image["png"]))) as pixels:
        assert pixels.getpixel((10, 10)) == (36, 136, 170)
        assert pixels.size == (120, 80) and not pixels.info


@pytest.mark.parametrize(
    "case", ["external_notes", "missing_notes", "dtd", "objects", "long_text", "chart"]
)
def test_malformed_or_unsupported_structures_are_explicit(case):
    data = presentation()
    if case in {"external_notes", "missing_notes"}:
        data = rewrite(
            data,
            "ppt/slides/_rels/slide2.xml.rels",
            lambda s: s.replace(
                'Target="../notesSlides/notesSlide1.xml"',
                'TargetMode="External" Target="https://private.invalid/notes"'
                if case == "external_notes"
                else 'Target="../../missing.xml"',
            ),
        )
    elif case == "dtd":
        data = rewrite(
            data,
            "ppt/notesSlides/notesSlide1.xml",
            lambda s: '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]>' + s,
        )
    elif case == "objects":
        data = rewrite(
            data,
            "ppt/slides/slide2.xml",
            lambda s: s.replace("</p:spTree>", shape("x") * 201 + "</p:spTree>"),
        )
    elif case == "long_text":
        data = rewrite(
            data, "ppt/slides/slide2.xml", lambda s: s.replace("Differentiation", "A" * 16001)
        )
    else:
        data = rewrite(
            data,
            "ppt/slides/slide2.xml",
            lambda s: s.replace(
                "</p:spTree>",
                "<p:graphicFrame><a:graphic><a:chart/></a:graphic></p:graphicFrame></p:spTree>",
            ),
        )
        result = extract(data, "pptx")
        assert (
            result["pages"][0]["objects"][-1]["interpretation_status"]
            == "unsupported_graphic_or_chart"
        )
        return
    with pytest.raises((ValueError, DefusedXmlException)):
        extract(data, "pptx")


@pytest.mark.parametrize(
    "case", ["external", "wrong_type", "missing", "wrong_object", "wrong_slide", "vector"]
)
def test_picture_never_follows_external_or_invalid_references(case):
    data = presentation()
    if case in {"external", "missing", "wrong_type"}:
        replacements = {
            "external": (
                'Target="../media/image1.png"',
                'TargetMode="External" Target="http://127.0.0.1/private"',
            ),
            "missing": ('Target="../media/image1.png"', 'Target="../media/missing.png"'),
            "wrong_type": ("http://example/image", "http://example/hyperlink"),
        }
        old, new = replacements[case]
        data = rewrite(data, "ppt/slides/_rels/slide2.xml.rels", lambda s: s.replace(old, new))
    elif case == "vector":
        data = replace_member(
            data, "ppt/media/image1.png", b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        )
    with pytest.raises((ValueError, OSError)):
        render_picture(data, 99 if case == "wrong_slide" else 1, 1 if case == "wrong_object" else 5)


def replace_member(data, member, content):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as original,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as new,
    ):
        for name in original.namelist():
            new.writestr(name, content if name == member else original.read(name))
    return output.getvalue()


def test_real_sandbox_structure_picture_and_job_cleanup(tmp_path):
    data = presentation()
    root = tmp_path / "parser"
    result = extract_isolated(data, "pptx", root)
    assert result["pages"][0]["notes_state"] == "extracted"
    image = extract_isolated(
        data, "pptx", root, visual={"kind": "pptx", "page": 1, "rotation": 0, "object_index": 5}
    )
    assert image["pixels"] == [120, 80] and image["png"]
    assert not list((root / "jobs").iterdir())


@pytest.fixture
async def readable_presentation(bridge, owner, seeded, monkeypatch, tmp_path):
    data = presentation()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                filename="fictional.pptx",
                display_name="fictional.pptx",
                size=len(data),
                updated_at="2026-10-22T00:00:00Z",
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

    async def parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", parser)
    _, courses = bridge.selected(owner, seeded)
    files = await list_files(bridge, owner, seeded, courses[0].id)
    return courses[0], files.data["files"][0]["file_id"]


async def test_reader_continuation_notes_tables_search_and_cache(
    bridge, owner, seeded, readable_presentation
):
    course, ref = readable_presentation
    overview = await read_presentation(bridge, owner, seeded, ref)
    assert len(overview.data["presentation"]["slides"]) == 2
    result = await read_presentation(bridge, owner, seeded, ref, slide=1, max_objects=2)
    assert (
        result.data["records"][1]["table"]["cells"][3]["locator"] == "Slide 1, object 2, table R2C2"
    )
    records = result.data["records"][:]
    while result.data["continuation"]:
        result = await read_presentation(bridge, owner, seeded, **result.data["continuation"])
        records.extend(result.data["records"])
    assert len(records) == 6 and records[-1]["kind"] == "speaker_note"
    assert records[-1]["source_reference"]["locator"] == "Slide 1, speaker notes paragraph 1"
    assert records[-1]["source_reference"]["content_hash"] == result.data["content_hash"]
    assert (await search_files(bridge, owner, seeded, course.id, "experimental controls")).data[
        "results"
    ]
    assert (await status(bridge, owner, seeded, ref)).data["state"] == "partially_parsed"
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1


async def test_access_and_version_boundaries_reused(bridge, owner, seeded, readable_presentation):
    _, ref = readable_presentation
    result = await read_presentation(bridge, owner, seeded, ref, slide=1, max_objects=1)
    other = await seed(bridge, "other-owner", "other-connection")
    for function, args in [
        (read_presentation, {}),
        (read_picture, {"slide": 1, "object_index": 5}),
    ]:
        with pytest.raises(DomainError):
            await function(bridge, "other-owner", other, ref, **args)
    bridge.synthetic.data["file_bodies"]["51"] = presentation(True)
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(presentation(True)), updated_at="2026-10-23T00:00:00Z"
    )
    with pytest.raises(DomainError, match="changed"):
        await read_presentation(bridge, owner, seeded, **result.data["continuation"])
    with pytest.raises(DomainError, match="changed"):
        await read_picture(bridge, owner, seeded, ref, 1, 1, result.data["content_hash"])
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError):
        await read_picture(bridge, owner, seeded, ref, 1, 1)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_real_mcp_slide_and_image_content(
    running, bridge, owner, seeded, readable_presentation, token_factory, monkeypatch
):
    from canvas_bridge.parser_sandbox import extract_document

    _, ref = readable_presentation
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", extract_document)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}, timeout=60
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "read_course_presentation",
                    {"connection_id": seeded, "file_id": ref, "slide": 1},
                )
                assert result.structuredContent["data"]["notes_state"] == "extracted"
                version = result.structuredContent["data"]["content_hash"]
                image = await session.call_tool(
                    "read_course_slide_image",
                    {
                        "connection_id": seeded,
                        "file_id": ref,
                        "slide": 1,
                        "object_index": 5,
                        "expected_hash": version,
                    },
                )
                assert image.structuredContent["status"] == "ok"
                assert image.structuredContent["sources"][0]["locator"] == "Slide 1, object 5"
                assert any(c.type == "image" for c in image.content)
                assert "png" not in json.dumps(image.structuredContent)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
