"""Synthetic OCR transcription/search labels and optional installed-engine comparison."""

import io
import os
from contextlib import closing
from pathlib import Path
from time import perf_counter

import pytest

from canvas_bridge import course_files, ocr_worker
from canvas_bridge.course_files import read_file, search_files
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_worker import PARSER, extract
from canvas_bridge.passage_search import PassageMatcher
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_visual_files import ocr_root as ocr_root


def test_labeled_search_recall_and_false_positives():
    positives = ["OFFLOADING", "OF FLORDIMG", "OFFLOADlNG", "OFF LOADlNG", "0F7L04DING"]
    negatives = [
        "overloading",
        "unloading",
        "uploading",
        "offloaded",
        "offset loading",
        "of\nflordimg",
        "offloadings",
        "onboarding",
        "flooding",
        "offline",
    ]
    for mode, expected in [("exact", 1), ("approximate", 4)]:
        matcher = PassageMatcher("offloading", mode)

        def hit(text, matcher=matcher):
            return matcher.find({"text": text, "state": "ocr_extracted"})

        assert sum(bool(hit(text)) for text in positives) == expected
        assert [text for text in negatives if hit(text)] == ["offloadings"]
        # Both modes preserve the established literal substring semantics.
        assert hit("OF FLORDIMG and OFFLOADING")[2] == "exact"
        assert not matcher.find({"text": "OF FLORDIMG", "state": "extracted"})
        # Real words can be visually confusable and have different meanings.
        distractor = PassageMatcher("conical", mode).find(
            {"text": "comical", "state": "ocr_extracted"}
        )
        assert bool(distractor) == (mode == "approximate")


async def test_page_five_cache_unread_cursor_and_coverage(
    bridge, owner, seeded, readable, monkeypatch
):
    course, file_id = readable
    body = scientific_pdf(
        ["Embedded synthetic paragraph."] * 5 + ["literal offloading"] + ["Other page"] * 20
    )
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["files"]["11"][0]["size"] = len(body)

    async def transcriptions(data, kind, settings, page_range=None):
        doc = extract(data, kind, page_range)
        for page in doc["pages"]:
            if page["page"] in (4, 5):
                page.update(
                    state="ocr_extracted",
                    text="COGRNTINE. OF FLORDIMG" if page["page"] == 5 else "other text",
                    ocr_confidence=61 if page["page"] == 5 else 93,
                    ocr_status="extracted",
                    extraction_method="tesseract_english_ocr",
                )
        return doc

    monkeypatch.setattr(course_files, "extract_document", transcriptions)
    await read_file(bridge, owner, seeded, file_id, page_start=1, page_end=3)
    await read_file(bridge, owner, seeded, file_id, page_start=4, page_end=6)

    async def search(query="offloading", **kwargs):
        return await search_files(bridge, owner, seeded, course.id, query, **kwargs)

    exact = await search()
    assert [h["page"] for h in exact.data["results"]] == [6]
    approx = await search(match_mode="approximate")
    five, six = approx.data["results"]
    assert (five["page"], five["locator"], five["matched_text"]) == (5, "PDF page 5", "OF FLORDIMG")
    assert (five["match_type"], five["similarity"], five["ocr_confidence"]) == (
        "approximate",
        0.8,
        61,
    )
    assert five["parser"] == PARSER and five["source_version"] and not five["visually_verified"]
    assert six["match_type"] == "exact" and six["content_hash"] == five["content_hash"]
    empty = await search("absent term")
    status = empty.data["document_statuses"][0]
    assert status["searched_positions"] == list(range(1, 7))
    assert not empty.data["results"] and empty.status == "partial_data"
    assert (status["uncertain_pages"], status["attempted_units"], status["page_count"]) == (
        1,
        6,
        26,
    )
    details = await course_files.status(bridge, owner, seeded, file_id)
    assert [(p["page"], p["mean_confidence"]) for p in details.data["ocr_confidence"]["pages"]] == [
        (4, 93),
        (5, 61),
    ]
    first = await search(match_mode="approximate", include_unread=True, limit=1)
    assert first.data["results"] == [five]
    assert first.data["document_statuses"][0]["searched_positions"] == list(range(1, 6))
    assert "UNCERTAIN_OCR" in first.data["coverage_reasons"]
    with pytest.raises(DomainError, match="changed"):
        await search(include_unread=True, limit=1, cursor=first.data["next_cursor"])
    second = await search(
        match_mode="approximate", include_unread=True, limit=1, cursor=first.data["next_cursor"]
    )
    assert second.data["results"] == [six]
    # Even after reaching the final page, the uncertain OCR limits this pass.
    while second.data["next_cursor"]:
        second = await search(
            match_mode="approximate",
            include_unread=True,
            limit=1,
            cursor=second.data["next_cursor"],
        )
        assert not second.data["results"]
    assert second.data["search_pass_finished"] and second.status == "partial_data"
    assert "UNCERTAIN_OCR" in second.data["coverage_reasons"]
    bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-21T12:00:00Z"
    stale = await search(match_mode="approximate")
    assert not stale.data["results"] and stale.data["unindexed_documents"]


@pytest.mark.parametrize(
    "style,size,ink,angle",
    [
        ("readable", 28, 0, 0),
        ("small", 9, 0, 0),
        ("thin", 13, 0, 0),
        ("ordinary", 24, 20, 0),
        ("heavy", 60, 10, 0),
        ("faint", 40, 233, 0),
        ("sideways", 40, 40, 90),
    ],
)
def test_installed_ocr_title_comparison(style, size, ink, angle, ocr_root, monkeypatch):
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFont

    # Fixed font for repeatable stroke widths. Only generated pixels enter this test.
    font = "arial.ttf" if style == "readable" else "arialbd.ttf"
    font_path = Path(os.environ.get("WINDIR", "")) / "Fonts" / font
    if not font_path.is_file():
        pytest.skip("Windows Arial Bold comparison fixture")
    width = 2400 if style == "readable" else 810
    image = Image.new("RGB", (width, 110), "white")
    ImageDraw.Draw(image).text(
        (10, 12),
        "COGNITIVE OFFLOADING",
        fill=(ink,) * 3,
        font=ImageFont.truetype(str(font_path), size),
    )
    buf = io.BytesIO()
    image.rotate(angle, expand=True).save(buf, format="PDF", resolution=72)
    monkeypatch.setattr(ocr_worker, "OCR_ROOT", ocr_root)
    scores = []
    with (
        pdfium.PdfDocument(buf.getvalue()) as pdf,
        closing(pdf[0]) as page,
        closing(
            page.render(scale=min(2400 / max(page.get_size()), 4), rev_byteorder=True)
        ) as bitmap,
    ):
        for cutoff in (0, ocr_worker.GRAYSCALE_RETRY_BELOW):
            monkeypatch.setattr(ocr_worker, "GRAYSCALE_RETRY_BELOW", cutoff)
            start = perf_counter()
            result = ocr_worker.recognize(bitmap)
            scores.append(
                (
                    "OFFLOADING" in result["text"].upper(),
                    result["mean_confidence"],
                    round(1000 * (perf_counter() - start)),
                )
            )
    print(style, scores)
    if style == "readable":
        assert scores[0][:2] == scores[1][:2] and scores[0][0]
    if scores[0][0] or style in {"ordinary", "heavy", "faint"}:
        assert scores[1][0]
    if style in {"heavy", "faint"}:
        assert not scores[0][0]
