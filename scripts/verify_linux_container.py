"""Synthetic container proof; no credentials or actual coursework."""

import asyncio
import sys
import tempfile
from pathlib import Path


def prepare(root):
    from tests.test_academic_intelligence import ooxml
    from tests.test_file_reading import scientific_pdf
    from tests.test_visual_files import scanned_pdf

    root.mkdir(parents=True, exist_ok=True)
    (root / "scan.pdf").write_bytes(scanned_pdf(mixed=True))
    for kind in ("pdf", "txt", "md", "docx", "pptx"):
        data = (
            scientific_pdf()
            if kind == "pdf"
            else ooxml(kind)
            if kind in {"docx", "pptx"}
            else b"Methods: controlled synthetic cultures."
        )
        (root / ("synthetic." + kind)).write_bytes(data)


async def verify(root):
    from canvas_bridge.config import Settings
    from canvas_bridge.parser_sandbox import extract_document

    with tempfile.TemporaryDirectory(prefix="canvas-parser-") as jobs:
        settings = Settings(_env_file=None, file_reading_enabled=True, parser_root=Path(jobs))
        assert settings.parser_runtime_root == Path("/opt/canvas-parser")
        for kind in ("pdf", "txt", "md", "docx", "pptx"):
            result = await extract_document(
                (root / ("synthetic." + kind)).read_bytes(), kind, settings
            )
            assert result["coverage"] == "text_only"
            assert any("controlled" in page["text"] for page in result["pages"])
            if kind == "pdf":
                assert result["page_count"] == 3
                assert "Conclusions" in result["pages"][2]["text"]
            assert not list((settings.parser_root / "jobs").iterdir())
            print(f"Verified {kind} extraction and cleanup in restricted Linux image")
        from canvas_bridge.visual_files import render_document

        image = await render_document((root / "synthetic.pdf").read_bytes(), settings)
        assert image["png"] and image["page_count"] == 3
        scan = await extract_document((root / "scan.pdf").read_bytes(), "pdf", settings)
        assert scan["pages"][1]["extraction_method"] == "tesseract_english_ocr"
        assert "October" in scan["pages"][1]["text"]
        print("Verified page-image rendering and scanned-PDF OCR in restricted Linux image")


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "prepare":
        prepare(Path(directory))
    elif mode == "verify":
        asyncio.run(verify(Path(directory)))
    else:
        raise SystemExit("Expected prepare or verify")
