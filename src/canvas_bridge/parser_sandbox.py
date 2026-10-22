"""Credential-free OS extraction boundary; unsupported platforms fail closed."""

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import defusedxml
import et_xmlfile
import openpyxl
import PIL
import pypdf
import pypdfium2
import pypdfium2_cfg
import pypdfium2_raw

from canvas_bridge import ocr_runtime
from canvas_bridge.document_worker import DOCUMENT_ERRORS
from canvas_bridge.domain import DomainError
from canvas_bridge.office_package import OFFICE_ERRORS
from canvas_bridge.parser_worker import MAX_TEXT, PARSER
from canvas_bridge.presentation_worker import PRESENTATION_ERRORS
from canvas_bridge.workbook_worker import WORKBOOK_ERRORS

_slot = threading.Lock()


def ensure_runtime(root: Path, ocr_root: Path | None = None) -> Path:
    if sys.platform == "linux":
        from canvas_bridge.linux_sandbox import ensure_runtime as linux_runtime

        return linux_runtime(root, ocr_root)
    if os.name != "nt":
        raise DomainError(
            "unsupported_feature",
            "Isolated file extraction requires a supported Windows or Linux sandbox.",
        )
    from canvas_bridge.windows_sandbox import acl

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name("parser_worker.py")
    office = Path(__file__).with_name("office_package.py")
    document = Path(__file__).with_name("document_worker.py")
    workbook = Path(__file__).with_name("workbook_worker.py")
    presentation = Path(__file__).with_name("presentation_worker.py")
    visual = Path(__file__).with_name("visual_worker.py")
    ocr = Path(__file__).with_name("ocr_worker.py")
    digest = hashlib.sha256(
        worker.read_bytes()
        + office.read_bytes()
        + document.read_bytes()
        + workbook.read_bytes()
        + presentation.read_bytes()
        + openpyxl.__version__.encode()
        + et_xmlfile.__version__.encode()
        + visual.read_bytes()
        + PIL.__version__.encode()
        + ocr.read_bytes()
        + ocr_runtime.version(ocr_root)
        + b"runtime-with-pdfium-cfg-v1"
        + str(pypdfium2.PYPDFIUM_INFO).encode()
        + str(pypdfium2.PDFIUM_INFO).encode()
        + sys.version.encode()
        + pypdf.__version__.encode()
        + defusedxml.__version__.encode()
    ).hexdigest()[:16]
    runtime = root / ("runtime-" + digest)
    if (runtime / "ready").is_file():
        return runtime
    runtime.mkdir(exist_ok=True)
    base = Path(sys.base_prefix)
    for pattern in ("python.exe", "python*.dll", "vcruntime*.dll"):
        for source in base.glob(pattern):
            shutil.copy2(source, runtime / source.name)
    shutil.copytree(base / "DLLs", runtime / "DLLs", dirs_exist_ok=True)
    # Only the standard library is included; no service, sitecustomize, database
    # packages, .env, user packages, or credential-bearing workspace is mounted.
    library = base / "Lib"
    excluded = {
        "site-packages",
        "test",
        "tests",
        "__pycache__",
        "idlelib",
        "tkinter",
        "ensurepip",
        "turtledemo",
    }
    with zipfile.ZipFile(runtime / "stdlib.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in library.rglob("*.py"):
            relative = source.relative_to(library)
            if not excluded.intersection(relative.parts):
                archive.write(source, relative.as_posix())
    shutil.copytree(
        Path(pypdf.__file__).parent,
        runtime / "site/pypdf",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(worker, runtime / "worker.py")
    shutil.copy2(office, runtime / "office_package.py")
    shutil.copy2(document, runtime / "document_worker.py")
    shutil.copy2(workbook, runtime / "workbook_worker.py")
    shutil.copy2(presentation, runtime / "presentation_worker.py")
    shutil.copy2(visual, runtime / "visual_worker.py")
    shutil.copy2(ocr, runtime / "ocr_worker.py")
    ocr_runtime.copy(ocr_root, runtime)
    for package in (pypdfium2, pypdfium2_raw, pypdfium2_cfg, PIL, openpyxl, et_xmlfile):
        shutil.copytree(
            Path(package.__file__).parent,
            runtime / "site" / package.__name__,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copytree(
        Path(defusedxml.__file__).parent,
        runtime / "site/defusedxml",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    (runtime / f"python{version}._pth").write_text("stdlib.zip\nDLLs\nsite\n.\n", encoding="ascii")
    # Public interpreter/parser code only. Each job has its own separate SID.
    acl(runtime, "/grant:r", "*S-1-15-2-1:(OI)(CI)(RX)", "/T", "/Q")
    (runtime / "ready").write_text(PARSER, encoding="ascii")
    return runtime


def validate_result(result: dict, data: bytes) -> dict:
    if not result.get("ok"):
        reason = result.get("reason", "extraction_failed")
        allowed = (
            {
                "file_too_large",
                "encrypted_pdf",
                "too_many_pages",
                "active_pdf_content",
                "unsupported_format",
                "corrupt_or_unreadable",
                "output_limit",
                "invalid_slide_reference",
            }
            | DOCUMENT_ERRORS
            | OFFICE_ERRORS
            | WORKBOOK_ERRORS
            | PRESENTATION_ERRORS
        )
        raise DomainError(
            "unsupported_feature",
            "File extraction could not finish: "
            + (reason if reason in allowed else "extraction_failed")
            + ".",
        )
    parsed = result["extraction"]
    if (
        parsed["content_hash"] != hashlib.sha256(data).hexdigest()
        or parsed["parser"] != PARSER
        or parsed["coverage"] not in {"text_only", "partial"}
        or not 0 <= parsed["page_count"] <= 200
        or len(parsed["pages"]) > 200
        or sum(len(p["text"]) for p in parsed["pages"]) > MAX_TEXT
    ):
        raise ValueError("Invalid sandbox extraction result.")
    previous = 0
    for page in parsed["pages"]:
        if not isinstance(page["text"], str) or not previous < page["page"] <= parsed["page_count"]:
            raise ValueError("Invalid sandbox page attribution.")
        previous = page["page"]
    return parsed


def extract_isolated(
    data: bytes,
    kind: str,
    root: Path,
    *,
    runtime_root: Path | None = None,
    visual: dict | None = None,
    ocr_root: Path | None = None,
    render_preflight: bool = False,
) -> dict:
    if len(data) > 10_000_000:
        raise DomainError("unsupported_feature", "File exceeds the extraction size limit.")
    if not _slot.acquire(blocking=False):
        raise DomainError("retry_later", "Another document is being extracted. Retry shortly.")
    try:
        if sys.platform == "linux":
            from canvas_bridge.linux_sandbox import private_root, run

            private_root(root)
            runtime = ensure_runtime(runtime_root or root, ocr_root)
        else:
            from canvas_bridge.windows_sandbox import run

            runtime = ensure_runtime(root, ocr_root)

        jobs = root.resolve() / "jobs"
        jobs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="document-", dir=jobs) as directory:
            work = Path(directory).resolve()
            if not work.is_relative_to(jobs.resolve()):
                raise RuntimeError("Invalid temporary extraction location.")
            (work / "input.bin").write_bytes(data)
            (work / "request.json").write_text(
                json.dumps(
                    visual
                    if visual is not None
                    else {"kind": kind, "render_preflight": render_preflight}
                ),
                encoding="utf-8",
            )
            run(runtime, work, script="visual_worker.py" if visual is not None else "worker.py")
            path = work / "result.json"
            with path.open("rb") as stream:
                output = stream.read(2_000_001)
            if len(output) > 2_000_000:
                raise ValueError("Extraction output exceeded its budget.")
            if visual is not None:
                from canvas_bridge.visual_files import validate_rendering

                return validate_rendering(json.loads(output), data, visual)
            return validate_result(json.loads(output), data)
    except DomainError:
        raise
    except TimeoutError as exc:
        raise DomainError(
            "retry_later", "Document extraction timed out; no complete text was cached."
        ) from exc
    except Exception as exc:
        raise DomainError(
            "unsupported_feature", "Document extraction failed or exceeded sandbox resource limits."
        ) from exc
    finally:
        _slot.release()


async def extract_document(data: bytes, kind: str, settings) -> dict:
    if not settings.file_reading_enabled or settings.parser_root is None:
        raise DomainError(
            "unsupported_feature", "Isolated file extraction is not enabled on this server."
        )
    # Each OS worker always has its own wall/CPU limit, even if this awaiting
    # task is cancelled. It cannot survive the bounded job cleanup.
    parsed = await asyncio.to_thread(
        extract_isolated,
        data,
        kind,
        settings.parser_root,
        runtime_root=settings.parser_runtime_root,
        ocr_root=settings.ocr_root,
    )

    if kind != "pdf" or settings.ocr_root is None:
        return parsed
    attempted = 0
    for page in parsed["pages"]:
        if len(page["text"].strip()) >= 40 or page["state"] in {"truncated", "resource_limit"}:
            continue
        if attempted >= 4:
            parsed["warnings"].append(
                f"Page {page['page']}: OCR batch limit (4 pages); use visual page reading."
            )
            parsed["coverage"] = "partial"
            continue
        attempted += 1
        try:
            visual = await asyncio.to_thread(
                extract_isolated,
                data,
                "pdf",
                settings.parser_root,
                runtime_root=settings.parser_runtime_root,
                ocr_root=settings.ocr_root,
                visual={"page": page["page"], "rotation": 0, "ocr": True},
            )
            recognition = visual["ocr"]
            text = recognition["text"].strip()
            budget = MAX_TEXT - sum(len(p["text"]) + 2 for p in parsed["pages"])
            if text and len(text) <= budget and recognition["mean_confidence"] >= 50:
                page.update(
                    text=text,
                    state="ocr_extracted",
                    extraction_method=recognition["method"],
                    ocr_confidence=recognition["mean_confidence"],
                    words=recognition["words"],
                    image_pixels=visual["pixels"],
                )
                parsed["warnings"] = [
                    w
                    for w in parsed["warnings"]
                    if not w.startswith(f"Page {page['page']}: no text layer")
                    and w != "No readable text was extracted."
                ]
            else:
                parsed["warnings"].append(
                    f"Page {page['page']}: OCR returned no usable text, low-confidence text or exceeded the text budget."
                )
        except DomainError:
            parsed["warnings"].append(
                f"Page {page['page']}: OCR unavailable, failed or exceeded isolation limits. Visual reading may still work."
            )
        parsed["coverage"] = "partial"
    if attempted:
        parsed["warnings"].append(
            "OCR is an uncertain English transcription, not a verified table. Check dates, numbers, names and merged cells against render_course_file_page; colors are not interpreted."
        )
    return parsed
