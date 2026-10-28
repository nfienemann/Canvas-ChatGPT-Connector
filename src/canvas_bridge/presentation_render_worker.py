"""Fixed whole-slide conversion inside the credential-free Windows AppContainer.

Never run this module directly against live course files. LibreOfficeKit runs
inside this worker using an operator-provided public read-only runtime.
"""

import hashlib
import io
import json
import posixpath
import re
import subprocess
import sys
import time
from configparser import ConfigParser
from pathlib import Path

from PIL import Image

if __package__:
    from canvas_bridge.document_policy import PPTX_SOURCE_BYTES, PresentationLimit
    from canvas_bridge.emf_worker import prepare_emf
    from canvas_bridge.presentation_subset import single_slide
    from canvas_bridge.presentation_worker import Package, local
    from canvas_bridge.visual_worker import render
else:
    from document_policy import PPTX_SOURCE_BYTES, PresentationLimit
    from emf_worker import prepare_emf
    from presentation_subset import single_slide
    from presentation_worker import Package, local
    from visual_worker import render

RENDERER = "canvas-bridge-pptx-libreoffice-v1"
CONVERTER = "canvas-bridge-pptx-pdf-v6-bounded-emf"
MAX_PDF = 10_000_000


def convert_native(office_root, profile, source, output, options):
    work = source.parent
    (work / "native-request.json").write_text(
        json.dumps({"office_root": str(office_root), "options": options}), encoding="utf-8"
    )
    child = subprocess.run(  # noqa: S603 - fixed credential-free worker, no shell
        [
            sys.executable,
            "-I",
            "-S",
            str(Path(__file__).with_name("presentation_native.py")),
            str(work),
        ],
        cwd=work,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        creationflags=0x08000000,
        check=False,
    )
    if child.returncode == 124:
        raise TimeoutError()
    if child.returncode in {0xC0000017, 0xC000012D}:
        raise MemoryError()
    if child.returncode or not output.is_file():
        raise ValueError("conversion_failed")


class UnsupportedMedia(ValueError):
    def __init__(self, name):
        super().__init__("unsupported_slide_media")
        extension = Path(name).suffix.lower().lstrip(".")
        self.media_format = (
            extension if extension in {"emf", "wmf", "svg", "wdp", "mp4", "wav"} else "other"
        )


def validate_svg(root):
    """Self-contained static SVG only; no scripts, foreign objects or fetching."""
    allowed = {
        "svg",
        "g",
        "defs",
        "title",
        "desc",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
        "tspan",
        "textPath",
        "use",
        "symbol",
        "clipPath",
        "mask",
        "linearGradient",
        "radialGradient",
        "stop",
        "pattern",
        "marker",
        "style",
        "metadata",
    }
    elements = list(root.iter())
    if len(elements) > 10_000 or local(root) != "svg":
        raise ValueError("image_resource_limit")
    for element in elements:
        if local(element) not in allowed:
            raise ValueError("active_or_external_content")
        for key, value in element.attrib.items():
            attr = key.rsplit("}", 1)[-1].lower()
            if attr.startswith("on") or (
                attr in {"href", "src", "base"} and not value.startswith("#")
            ):
                raise ValueError("active_or_external_content")
        for value in [*element.attrib.values(), element.text or ""]:
            if (
                "@" in value
                or "\\" in value
                or "/*" in value
                or re.search(r"(?:javascript|https?|file|data):", value, re.I)
            ):
                raise ValueError("active_or_external_content")
            if any(
                not target.strip(" \t\n\r\"'").startswith("#")
                for target in re.findall(r"url\s*\((.*?)\)", value, re.I | re.S)
            ):
                raise ValueError("active_or_external_content")


def convert(work, data, page, rotation, office_root, *, derivative=False):
    if type(page) is not int or not 1 <= page <= 200 or rotation not in {0, 90, 180, 270}:
        raise ValueError("invalid_page_or_rotation")
    if len(data) > PPTX_SOURCE_BYTES:
        raise ValueError("file_size_or_signature")
    replacements = {}
    with Package(data) as package:
        paths = package.slide_paths()
        count = len(paths)
        if page > count:
            raise ValueError("page_limit_or_range")
        for name in sorted(package.names):
            if "/embeddings/" in name.lower():
                raise ValueError("active_or_external_content")
            if name.lower().startswith("ppt/media/") and not name.endswith("/"):
                if name.lower().endswith(".emf"):
                    try:
                        extension, raw = prepare_emf(package.read(name, limit=8 * 1024 * 1024))
                    except ValueError as exc:
                        raise UnsupportedMedia(name) from exc
                    if extension == "png":
                        replacements[name] = (name + ".png", raw)
                        if sum(len(item[1]) for item in replacements.values()) > 32 * 1024 * 1024:
                            raise ValueError("image_resource_limit")
                    del raw
                    continue
                if name.lower().endswith(".svg"):
                    validate_svg(package.xml(name))
                    continue
                if not name.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")
                ):
                    raise UnsupportedMedia(name)
                raw = package.read(name, limit=32 * 1024 * 1024)
                with Image.open(io.BytesIO(raw)) as picture:
                    if picture.format not in {"PNG", "JPEG", "GIF", "BMP", "TIFF"}:
                        raise UnsupportedMedia(name)
                    if picture.width * picture.height > 16_000_000:
                        raise ValueError("image_resource_limit")
                    picture.verify()
                del raw
            if name.lower().endswith((".xml", ".rels")):
                root = package.xml(name)
                if name.endswith(".rels"):
                    part = posixpath.join(
                        posixpath.dirname(posixpath.dirname(name)),
                        posixpath.basename(name).removesuffix(".rels"),
                    )
                    package.relations(part)
                if any(
                    local(e) == "Relationship"
                    and e.get("TargetMode") == "External"
                    and not e.get("Type", "").endswith("/hyperlink")
                    for e in root.iter()
                ):
                    raise ValueError("active_or_external_content")
                if any(local(e) in {"oleObj", "control"} for e in root.iter()):
                    raise ValueError("active_or_external_content")
    profile = work / "profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user/registrymodifications.xcu").write_text(
        '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        "</item></oor:items>",
        encoding="utf-8",
    )
    source = work / "input.pptx"
    subset = single_slide(data, page, source, media_replacements=replacements)
    del replacements
    mapping = [{"source_slide": page, "pdf_page": 1, "hidden": subset["hidden"]}]
    options = {
        "PageRange": {"type": "string", "value": "1"},
        "ExportHiddenSlides": {"type": "boolean", "value": "true"},
        "ExportNotesPages": {"type": "boolean", "value": "false"},
        "ExportOnlyNotesPages": {"type": "boolean", "value": "false"},
        "ExportNotes": {"type": "boolean", "value": "false"},
        "ExportBookmarks": {"type": "boolean", "value": "false"},
    }
    started = time.monotonic()
    output = work / "input.pdf"
    convert_native(Path(office_root), profile, source, output, options)
    with output.open("rb") as stream:
        pdf = stream.read(MAX_PDF + 1)
    if len(pdf) > MAX_PDF:
        raise ValueError("image_output_limit")
    if derivative:
        import pypdfium2 as pdfium

        if not pdf.startswith(b"%PDF-"):
            raise ValueError("conversion_invalid_pdf")
        with pdfium.PdfDocument(pdf) as document:
            if len(document) != 1:
                raise ValueError("conversion_page_mismatch")
            # Force every page to load now, not only the requested page later.
            import math
            from contextlib import closing

            for index in range(1):
                with closing(document[index]) as pdf_page:
                    if not all(math.isfinite(n) and 1 <= n <= 20_000 for n in pdf_page.get_size()):
                        raise ValueError("conversion_invalid_pdf")
        version = ConfigParser(interpolation=None)
        version.read(Path(office_root) / "program/version.ini", encoding="utf-8")
        build = version.get("Version", "buildid", fallback="unknown")
        if len(build) > 64 or not all(c.isalnum() or c in ".-" for c in build):
            raise ValueError("conversion_failed")
        return {
            "converter": CONVERTER,
            "engine_build": build,
            "source_content_hash": hashlib.sha256(data).hexdigest(),
            "derivative_content_hash": hashlib.sha256(pdf).hexdigest(),
            "pdf_bytes": len(pdf),
            "pdf_page_count": 1,
            **subset,
            "slide_to_page": mapping,
            "mapping_validation": "single_source_slide_hidden_included_one_pdf_page_and_geometry",
            "conversion_ms": round((time.monotonic() - started) * 1000),
            "warnings": [
                "Static LibreOffice export includes hidden slides, excludes notes and animations, and may substitute fonts. Scientific fidelity requires inspecting pixels.",
                "PDF page 1 maps only to the selected original slide. Dynamic slide numbers are frozen to the original number; custom shows and sections are omitted. Visual fidelity remains unverified until pixels are inspected.",
                "Supported full-frame EMF+ bitmaps are normalized to PNG; optional embedded PDF alternatives are discarded without parsing. Classic EMF is limited to validated static drawing records. Inspect pixels for fidelity.",
            ],
        }
    result = render(pdf, page=1, rotation=rotation)
    if result["page_count"] != 1:
        raise ValueError("conversion_page_mismatch")
    result.update(
        renderer=RENDERER,
        content_hash=hashlib.sha256(data).hexdigest(),
        page=page,
        page_count=count,
        visual_render_status="rendered_not_interpreted",
        visual_observation=None,
        warnings=[
            "Static LibreOffice rendering may substitute fonts or differ from PowerPoint. Animations and notes are excluded; verify scientific labels against pixels."
        ],
    )
    return result


def main():
    work = Path(sys.argv[1])
    try:
        request = json.loads((work / "request.json").read_text(encoding="utf-8"))
        with (work / "input.bin").open("rb") as stream:
            data = stream.read(PPTX_SOURCE_BYTES + 1)
        derivative = request.get("conversion_only", False)
        result = {
            "ok": True,
            "derivative" if derivative else "rendering": convert(
                work,
                data,
                request["page"],
                request["rotation"],
                request["office_root"],
                derivative=derivative,
            ),
        }
    except Exception as exc:
        allowed = {
            "invalid_page_or_rotation",
            "file_size_or_signature",
            "page_limit_or_range",
            "active_or_external_content",
            "conversion_failed",
            "conversion_page_mismatch",
            "conversion_invalid_pdf",
            "image_output_limit",
            "image_resource_limit",
            "unsupported_slide_media",
            "invalid_slide_reference",
            "invalid_pptx_archive",
            "active_office_content",
        }
        reason = (
            "memory_limit"
            if isinstance(exc, MemoryError)
            else "render_timeout"
            if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
            else "pptx_expansion_limit"
            if isinstance(exc, PresentationLimit)
            else str(exc)
            if isinstance(exc, ValueError) and str(exc) in allowed
            else "unreadable_or_rendering_limit"
        )
        result = {"ok": False, "reason": reason}
        if isinstance(exc, UnsupportedMedia):
            result["media_format"] = exc.media_format
    encoded = json.dumps(result).encode()
    if len(encoded) > 2_000_000:
        encoded = b'{"ok":false,"reason":"image_output_limit"}'
    (work / "result.json").write_bytes(encoded)


if __name__ == "__main__":
    main()
