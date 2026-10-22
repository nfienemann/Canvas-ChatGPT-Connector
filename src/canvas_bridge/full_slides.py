"""Transient whole-slide rendering; source bytes never leave the local sandbox.

The first renderer profile is Windows AppContainer. Other platforms fail closed
until a separately verified Office sandbox is available. Existing text/picture
workers retain their current platform support and restrictions.
"""

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_isolated

RENDERER = "canvas-bridge-pptx-full-slide-v1"
_slot = threading.Lock()


def render_slide(data, settings, slide):
    if type(slide) is not int or not 1 <= slide <= 200:
        raise DomainError("needs_input", "Choose a slide from the presentation overview.")
    office = settings.slide_renderer_root
    if os.name != "nt" or office is None:
        raise DomainError(
            "unsupported_feature",
            "Complete-slide rendering needs the optional Windows LibreOffice sandbox. "
            "This server has not enabled it; slide text, notes and embedded pictures remain available.",
        )
    if not settings.file_reading_enabled or settings.parser_root is None:
        raise DomainError("unsupported_feature", "Isolated file reading is not enabled.")
    if len(data) > 10_000_000:
        raise DomainError("unsupported_feature", "Presentation exceeds the 10 MB limit.")
    if not _slot.acquire(blocking=False):
        raise DomainError("retry_later", "Another slide is rendering. Retry shortly.")
    try:
        # Archive expansion, XML and resource-reference checks are themselves
        # sandboxed. Do not open an unvalidated archive in the service process.
        parsed = extract_isolated(
            data,
            "pptx",
            settings.parser_root,
            runtime_root=settings.parser_runtime_root,
            render_preflight=True,
        )
        count = parsed["metadata"]["render_preflight"]["slide_count"]
        if not 1 <= slide <= count <= 200:
            raise DomainError("needs_input", "Slide is outside this presentation.")
        from canvas_bridge.windows_sandbox import run_office

        # LibreOffice's Windows profile components do not reliably handle long
        # paths. A private, random OS-temp job avoids nesting its profile under
        # an arbitrarily long parser/workspace path. It gets its own SID below.
        with tempfile.TemporaryDirectory(prefix="canvas-slide-") as directory:
            work = Path(directory)
            (work / "input.pptx").write_bytes(data)
            run_office(office.resolve(), work, slide)
            output = work / "input.pdf"
            if (
                output.is_symlink()
                or output.is_junction()
                or output.resolve().parent != work
                or output.stat().st_nlink != 1
            ):
                raise ValueError("Invalid renderer output location")
            with output.open("rb") as stream:
                pdf = stream.read(10_000_001)
            if len(pdf) > 10_000_000 or not pdf.startswith(b"%PDF-"):
                raise ValueError("Invalid rendered PDF")
            image = extract_isolated(
                pdf,
                "pdf",
                settings.parser_root,
                runtime_root=settings.parser_runtime_root,
                visual={"page": 1, "rotation": 0},
            )
            if image["page_count"] != 1:
                raise ValueError("Renderer did not return exactly one slide")
        return {
            **image,
            "renderer": RENDERER,
            "visual_kind": "pptx_slide",
            "content_hash": hashlib.sha256(data).hexdigest(),
            "rendered_pdf_hash": hashlib.sha256(pdf).hexdigest(),
            "page": slide,
            "page_count": count,
            "image_locator": f"Slide {slide}",
            "coverage": "complete_static_slide_render; visual_interpretation_required",
            "hidden": parsed["metadata"]["slides"][slide - 1]["hidden"],
        }
    except DomainError:
        raise
    except TimeoutError as exc:
        raise DomainError(
            "retry_later", "Complete-slide rendering exceeded its time limit."
        ) from exc
    except Exception as exc:
        raise DomainError(
            "unsupported_feature",
            "Complete-slide rendering failed or exceeded isolation limits. "
            "Use the structured slide reader; no complete visual result is available.",
        ) from exc
    finally:
        _slot.release()
