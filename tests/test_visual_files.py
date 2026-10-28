import base64
import copy
import hashlib
import io
import os
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import httpx
import pypdfium2 as pdfium
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from canvas_bridge.calendar_sync import CalendarContext, CalendarEvent
from canvas_bridge.course_files import read_file, status
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.file_download import download_file
from canvas_bridge.parser_sandbox import extract_document, extract_isolated
from canvas_bridge.storage import Material
from canvas_bridge.visual_files import render_file, validate_rendering
from canvas_bridge.visual_schedule import ScheduleRow, interpret_schedule
from canvas_bridge.visual_worker import RENDERER
from tests.test_course_files import file_client as file_client
from tests.test_course_files import response
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


def scanned_pdf(rotation=0, mixed=False, source=None):
    # Rasterize fictional text, then embed only pixels: no source text layer.
    data = source or scientific_pdf(["October 27, 2026 Exam 1. Project Presentations TBD."])
    with pdfium.PdfDocument(data) as doc, closing(doc[0]) as page:
        with closing(
            page.render(scale=2, rev_byteorder=True, force_bitmap_format=pdfium.raw.FPDFBitmap_BGR)
        ) as b:
            pixels = bytes(b.buffer)
            rgb = b"".join(
                pixels[y * b.stride : y * b.stride + b.width * 3] for y in range(b.height)
            )
            width, height = b.width, b.height
    writer = PdfWriter()
    if mixed:
        writer.append(io.BytesIO(data))
    page = writer.add_blank_page(612, 792)
    obj = DecodedStreamObject()
    obj.set_data(rgb)
    for key, value in {
        "/Type": "/XObject",
        "/Subtype": "/Image",
        "/ColorSpace": "/DeviceRGB",
    }.items():
        obj[NameObject(key)] = NameObject(value)
    for key, value in {"/Width": width, "/Height": height, "/BitsPerComponent": 8}.items():
        obj[NameObject(key)] = NumberObject(value)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/I"): writer._add_object(obj.flate_encode())}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /I Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotation:
        page.rotate(rotation)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def ocr_root():
    roots = [
        Path(os.environ.get("BRIDGE_TEST_OCR_ROOT", "/unconfigured")),
        Path("/usr/share/tesseract-ocr/5"),
    ]
    for root in roots:
        if (root / "tessdata/eng.traineddata").is_file():
            return root
    pytest.skip("Operator OCR runtime not installed")


@pytest.mark.parametrize(
    "kind,rotation", [("searchable", 0), ("scan", 0), ("scan", 90), ("mixed", 0)]
)
def test_T11_T12_isolated_pdf_images(kind, rotation, tmp_path):
    data = scientific_pdf() if kind == "searchable" else scanned_pdf(rotation, kind == "mixed")
    page = 2 if kind == "mixed" else 1
    r = extract_isolated(
        data, "pdf", tmp_path / "parser", visual={"page": page, "rotation": rotation}
    )
    assert base64.b64decode(r["png"]).startswith(b"\x89PNG")
    assert (
        r["text_layer_characters"] > 0 if kind == "searchable" else r["text_layer_characters"] == 0
    )
    assert r["page"] == page
    assert max(r["pixels"]) <= 2401
    assert not list((tmp_path / "parser/jobs").iterdir())


async def test_T11_T25_image_only_ocr_and_mixed_provenance(settings, tmp_path, ocr_root):
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path / "parser"
    settings.ocr_root = ocr_root
    r = await extract_document(scanned_pdf(mixed=True), "pdf", settings)
    assert r["pages"][0]["extraction_method"] == "embedded_text"
    scan = r["pages"][1]
    assert scan["extraction_method"] == "tesseract_english_ocr"
    assert "October" in scan["text"] and "Project" in scan["text"]
    assert scan["words"] and r["coverage"] == "partial"


def test_T11_colored_table_with_merged_header_and_word_geometry(tmp_path, ocr_root):
    from PIL import Image

    writer = PdfWriter()
    writer.append(io.BytesIO(scientific_pdf(["Synthetic timetable"])))
    content = DecodedStreamObject()
    # One merged heading over two columns; colored rows and explicit dates.
    content.set_data(b"""
q 0.9 0.8 0.4 rg 40 500 532 180 re f Q
0 0 0 RG 40 500 532 180 re S
40 560 m 572 560 l S 40 620 m 572 620 l S
300 500 m 300 620 l S
BT /F1 16 Tf 180 645 Td (Course Schedule) Tj ET
BT /F1 16 Tf 55 585 Td (November 19, 2026) Tj ET
BT /F1 16 Tf 320 585 Td (Quiz Three) Tj ET
BT /F1 16 Tf 55 525 Td (December 3, 2026) Tj ET
BT /F1 16 Tf 320 525 Td (Quiz Four) Tj ET
""")
    writer.pages[0][NameObject("/Contents")] = writer._add_object(content)
    pdf = io.BytesIO()
    writer.write(pdf)
    data = scanned_pdf(source=pdf.getvalue())
    rendering = extract_isolated(
        data, "pdf", tmp_path / "parser", ocr_root=ocr_root, visual={"page": 1, "rotation": 0}
    )
    image = Image.open(io.BytesIO(base64.b64decode(rendering["png"])))
    assert any(r > b + 30 and g > b + 30 for r, g, b in image.get_flattened_data())
    ocr = extract_isolated(
        data,
        "pdf",
        tmp_path / "parser",
        ocr_root=ocr_root,
        visual={"page": 1, "rotation": 0, "ocr": True},
    )["ocr"]
    assert "November" in ocr["text"] and "Quiz" in ocr["text"]
    assert ocr["words"] and not ocr["table_structure_verified"]


@pytest.mark.parametrize(
    "data,page",
    [(b"%PDF-corrupt", 1), (b"x" * 10_000_001, 1), (scientific_pdf(), 4)],
    ids=["corrupt", "oversized", "out_of_range"],
)
def test_T11_render_failures_are_explicit(data, page, tmp_path):
    with pytest.raises(DomainError):
        extract_isolated(data, "pdf", tmp_path / "parser", visual={"page": page, "rotation": 0})


async def test_T13_render_authorization_hash_and_receipt(bridge, owner, seeded, readable, tmp_path):
    course, ref = readable
    bridge.settings.parser_root = tmp_path / "parser"
    r, png = await render_file(bridge, owner, seeded, ref)
    assert png and r.data["binary_retrieved"] and r.sources[0].locator == "PDF page 1"
    assert "verifier=" not in r.model_dump_json()
    for arguments in [
        ("other-owner", seeded, ref, None),
        (owner, seeded, ref, "0" * 64),
        (owner, seeded, "unknown-file", None),
    ]:
        with pytest.raises(DomainError):
            await render_file(bridge, *arguments[:3], expected_hash=arguments[3])
    bridge.select_courses(owner, seeded, [], "UTC")
    with pytest.raises(DomainError):
        await render_file(bridge, owner, seeded, ref)


async def test_T11_whitespace_cache_not_indexed(bridge, owner, seeded, readable):
    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.text = " \n"
        row.locators = [{"page": 1, "text": " \n", "state": "no_text"}]
        row.file_state = {**row.file_state, "coverage": "partial", "stage": "partially_parsed"}
    assert not (await status(bridge, owner, seeded, ref)).data["indexed"]
    assert not (await read_file(bridge, owner, seeded, ref)).data["indexed"]


def sample_row(**overrides):
    return ScheduleRow(
        row_key="class17",
        title="Exam 1",
        original_date="October 27, 2026",
        kind="exam",
        passage="October 27, 2026 Exam 1",
        bbox=[0.1, 0.2, 0.9, 0.3],
        **{"date": "2026-10-27", "date_basis": "explicit", **overrides},
    )


async def test_T13_T25_schedule_scope_version_and_tbd(bridge, owner, seeded, readable, tmp_path):
    _, ref = readable
    bridge.settings.parser_root = tmp_path / "parser"
    r, _ = await render_file(bridge, owner, seeded, ref)
    receipt = r.data["render_receipt"]
    result = await interpret_schedule(
        bridge, owner, seeded, receipt, [sample_row(date=None, date_basis="tbd")]
    )
    assert result.data["entries"][0]["date"] is None
    assert result.sources[0].classification == "assistant_inference"
    assert not result.data["entries"][0]["verified"]
    with pytest.raises(ValidationError):
        sample_row(date_basis="tbd")
    with pytest.raises(DomainError):
        await interpret_schedule(bridge, "other-owner", seeded, receipt, [sample_row()])
    proof = bridge.vault.open(receipt, owner, seeded)
    for changes in [
        {"expires": (utcnow() - timedelta(seconds=1)).isoformat()},
        {"version": "changed"},
    ]:
        bad = bridge.vault.seal({**proof, **changes}, owner, seeded)
        with pytest.raises(DomainError):
            await interpret_schedule(bridge, owner, seeded, bad, [sample_row()])


@pytest.mark.contract
async def test_T12_T21_native_mcp_image_content(
    running, bridge, token_factory, seeded, readable, tmp_path
):
    _, ref = readable
    bridge.settings.parser_root = tmp_path / "parser"
    async with httpx.AsyncClient(
        timeout=45, headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as client:
                await client.initialize()
                r = await client.call_tool(
                    "render_course_file_page", {"connection_id": seeded, "file_id": ref}
                )
                assert not r.isError
                assert any(c.type == "image" and c.mimeType == "image/png" for c in r.content)
                assert r.structuredContent["data"]["binary_retrieved"]
                denied = await client.call_tool(
                    "render_course_file_page", {"connection_id": seeded, "file_id": "other-file"}
                )
                assert denied.structuredContent["status"] == "permission_denied"
                assert not any(c.type == "image" for c in denied.content)


async def test_T13_expired_download_link_is_refreshed_once(file_client):
    client, provider = file_client
    calls = []

    async def transfer(request):
        calls.append(request)
        if len(calls) == 1:
            provider.data["files"]["11"][0]["url"] = (
                "https://storage.fixture.invalid/renewed?signature=private"
            )
            return httpx.Response(403)
        assert "authorization" not in request.headers
        return response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(transfer)) as http:
        result = await download_file(client, "11", "51", http=http)
    assert result.kind == "pdf" and len(calls) == 2


async def test_T13_denied_download_does_not_retry_forever(file_client):
    client, _ = file_client
    calls = []

    async def transfer(request):
        calls.append(request)
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transfer)) as http:
        with pytest.raises(DomainError, match="unavailable"):
            await download_file(client, "11", "51", http=http)
    assert len(calls) == 2


async def test_T25_parser_upgrade_invalidates_empty_cache(bridge, owner, seeded, readable):
    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.text = " \n"
        row.file_state = {**row.file_state, "parser": "canvas-bridge-documents-v3"}
    assert not (await status(bridge, owner, seeded, ref)).data["indexed"]
    result = await read_file(bridge, owner, seeded, ref)
    assert "Methods" in result.data["text"] and result.data["indexed"]


async def test_T11_ocr_unavailable_preserves_text_and_explicit_failure(
    settings, monkeypatch, tmp_path
):
    from canvas_bridge.parser_worker import extract

    data = scanned_pdf(mixed=True)

    def parser(data, kind, root, **kwargs):
        if kwargs.get("visual"):
            raise DomainError("retry_later", "Timed out")
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_isolated", parser)
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path
    settings.ocr_root = tmp_path
    r = await extract_document(data, "pdf", settings)
    assert "October" in r["pages"][0]["text"]
    assert not r["pages"][1]["text"].strip()
    assert any("failed" in w for w in r["warnings"])


async def test_T11_ocr_batch_and_low_confidence_are_partial(settings, monkeypatch, tmp_path):
    from canvas_bridge.parser_worker import extract

    writer = PdfWriter()
    for _ in range(6):
        writer.add_blank_page(612, 792)
    data = io.BytesIO()
    writer.write(data)
    attempts = []

    def parser(data, kind, root, **kwargs):
        if kwargs.get("visual"):
            attempts.append(kwargs["visual"]["page"])
            return {"ocr": {"text": "unreliable date", "mean_confidence": 20}}
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.parser_sandbox.extract_isolated", parser)
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path
    settings.ocr_root = tmp_path
    r = await extract_document(data.getvalue(), "pdf", settings)
    assert attempts == [1, 2, 3, 4]
    assert not any(p["text"].strip() for p in r["pages"])
    assert r["coverage"] == "partial"
    assert any("batch limit" in w for w in r["warnings"])


@pytest.mark.parametrize("defect", ["hash", "page", "size", "confidence", "geometry", "verified"])
def test_T13_reject_invalid_ocr_worker_evidence(defect):
    rendering = {
        "renderer": RENDERER,
        "content_hash": hashlib.sha256(b"pdf").hexdigest(),
        "page": 1,
        "page_count": 1,
        "rotation": 0,
        "pixels": [100, 100],
        "ocr": {
            "text": "Exam",
            "method": "tesseract_english_ocr",
            "mean_confidence": 90,
            "table_structure_verified": False,
            "words": [{"text": "Exam", "bbox": [0, 0, 10, 10], "confidence": 90}],
        },
    }
    bad = copy.deepcopy(rendering)
    if defect == "hash":
        bad["content_hash"] = "wrong"
    elif defect == "page":
        bad["page"] = 2
    elif defect == "size":
        bad["pixels"] = [9999, 100]
    elif defect == "confidence":
        bad["ocr"]["mean_confidence"] = float("nan")
    elif defect == "geometry":
        bad["ocr"]["words"][0]["bbox"] = [99, 99, 100, 100]
    else:
        bad["ocr"]["table_structure_verified"] = True
    request = {"page": 1, "rotation": 0, "ocr": True}
    assert validate_rendering({"ok": True, "rendering": rendering}, b"pdf", request)
    with pytest.raises(ValueError):
        validate_rendering({"ok": True, "rendering": bad}, b"pdf", request)


async def test_T19_T25_visual_schedule_calendar_dedup_updates_and_uncertainty(
    bridge, owner, seeded, readable, tmp_path
):
    _, ref = readable
    bridge.settings.parser_root = tmp_path / "parser"
    r, _ = await render_file(bridge, owner, seeded, ref)
    receipt = r.data["render_receipt"]
    now = utcnow()
    day = (now + timedelta(days=2)).date()
    row = sample_row(date=day)
    context = CalendarContext(
        calendar_id="fictional",
        timezone="UTC",
        retrieved_at=now,
        window_start=now,
        window_end=now + timedelta(days=10),
        pagination_complete=True,
        mapping_search_complete=True,
        events=[],
    )
    first = await interpret_schedule(bridge, owner, seeded, receipt, [row], context)
    proposal = first.data["calendar"]["proposals"][0]
    assert proposal["action"] == "create" and proposal["requires_explicit_confirmation"]
    assert not first.data["calendar"]["provider_writes_executed"]
    context.events = [
        CalendarEvent(
            id="existing",
            title="Exam 1",
            all_day_date=day,
            bridge_marker=proposal["bridge_marker"],
            status="confirmed",
            version="v1",
        )
    ]
    same = await interpret_schedule(bridge, owner, seeded, receipt, [row], context)
    assert same.data["calendar"]["proposals"] == []
    row.date += timedelta(days=1)
    changed = await interpret_schedule(bridge, owner, seeded, receipt, [row], context)
    assert changed.data["calendar"]["proposals"][0]["action"] == "update"
    assert (
        changed.data["calendar"]["proposals"][0]["previous_timing"]["all_day_date"]
        == day.isoformat()
    )
    row.uncertainties = ["Merged cell inheritance is unclear"]
    uncertain = await interpret_schedule(bridge, owner, seeded, receipt, [row], context)
    assert not uncertain.data["calendar"]["proposals"]
    with pytest.raises(DomainError, match="Duplicate"):
        await interpret_schedule(
            bridge, owner, seeded, receipt, [row, row.model_copy(update={"row_key": "another"})]
        )
