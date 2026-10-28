"""Credential-free OS extraction boundary; unsupported platforms fail closed."""

import asyncio
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from contextlib import nullcontext
from pathlib import Path

import defusedxml
import PIL
import pypdf
import pypdfium2
import pypdfium2_cfg
import pypdfium2_raw

from canvas_bridge import ocr_runtime
from canvas_bridge.document_policy import source_limit
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_worker import MAX_TEXT, PARSER
from canvas_bridge.worker_storage import job_directory, sweep_orphans

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
    spreadsheet = Path(__file__).with_name("spreadsheet_worker.py")
    scientific = Path(__file__).with_name("scientific_structure.py")
    presentation = Path(__file__).with_name("presentation_worker.py")
    presentation_render = Path(__file__).with_name("presentation_render_worker.py")
    presentation_native = Path(__file__).with_name("presentation_native.py")
    presentation_subset = Path(__file__).with_name("presentation_subset.py")
    emf_worker = Path(__file__).with_name("emf_worker.py")
    policy = Path(__file__).with_name("document_policy.py")
    privacy = Path(__file__).with_name("privacy_text.py")
    visual = Path(__file__).with_name("visual_worker.py")
    ocr = Path(__file__).with_name("ocr_worker.py")
    digest = hashlib.sha256(
        worker.read_bytes()
        + spreadsheet.read_bytes()
        + scientific.read_bytes()
        + presentation.read_bytes()
        + presentation_render.read_bytes()
        + presentation_native.read_bytes()
        + presentation_subset.read_bytes()
        + emf_worker.read_bytes()
        + policy.read_bytes()
        + privacy.read_bytes()
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
    shutil.copy2(privacy, runtime / "privacy_text.py")
    shutil.copy2(spreadsheet, runtime / "spreadsheet_worker.py")
    shutil.copy2(scientific, runtime / "scientific_structure.py")
    shutil.copy2(presentation, runtime / "presentation_worker.py")
    shutil.copy2(presentation_render, runtime / "presentation_render_worker.py")
    shutil.copy2(presentation_native, runtime / "presentation_native.py")
    shutil.copy2(presentation_subset, runtime / "presentation_subset.py")
    shutil.copy2(emf_worker, runtime / "emf_worker.py")
    shutil.copy2(policy, runtime / "document_policy.py")
    shutil.copy2(visual, runtime / "visual_worker.py")
    shutil.copy2(ocr, runtime / "ocr_worker.py")
    ocr_runtime.copy(ocr_root, runtime)
    for package in (pypdfium2, pypdfium2_raw, pypdfium2_cfg, PIL):
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
        allowed = {
            "file_too_large",
            "encrypted_pdf",
            "too_many_pages",
            "active_pdf_content",
            "unsupported_format",
            "corrupt_or_unreadable",
            "output_limit",
            "office_resource_limit",
            "active_office_content",
            "invalid_slide_reference",
            "invalid_docx_structure",
            "invalid_workbook_structure",
            "invalid_workbook_reference",
            "unsupported_workbook_cell_type",
            "workbook_resource_limit",
            "memory_limit",
            "dependency_unavailable",
            "pptx_expansion_limit",
            "invalid_pptx_archive",
        }
        details = {}
        if reason == "pptx_expansion_limit":
            supplied = result.get("details", {})
            if supplied.get("budget") not in {
                "zip_members",
                "zip_expanded_bytes",
                "zip_member_bytes",
                "zip_compression_ratio",
                "xml_member_bytes",
                "zip_read_bytes",
                "slide_count",
            } or any(
                type(supplied.get(k)) is not int or supplied[k] < 0 for k in ("observed", "limit")
            ):
                raise ValueError("Invalid presentation budget diagnostic")
            details = {k: supplied[k] for k in ("budget", "observed", "limit")}
            details["retryable"] = False
        raise DomainError(
            "retry_later"
            if reason in {"memory_limit", "dependency_unavailable"}
            else "unsupported_feature",
            "File extraction could not finish: "
            + (reason if reason in allowed else "extraction_failed")
            + ".",
            reason_code="PPTX_EXPANSION_LIMIT"
            if reason == "pptx_expansion_limit"
            else "EXTRACTION_" + (reason.upper() if reason in allowed else "FAILED"),
            processing_stage="zip_expansion"
            if reason == "pptx_expansion_limit"
            else "text_extraction",
            details=details,
        )
    parsed = result["extraction"]
    if parsed["parser"] != PARSER:
        raise DomainError(
            "retry_later",
            "The parser changed while this service was running. Restart the service before retrying.",
            reason_code="DOCUMENT_PARSER_VERSION_CHANGED",
            processing_stage="result_validation",
        )
    if (
        parsed["content_hash"] != hashlib.sha256(data).hexdigest()
        or parsed["coverage"] not in {"text_only", "partial"}
        or not 0 <= parsed["page_count"] <= 200
        or len(parsed["pages"]) > 200
        or sum(len(p["text"]) for p in parsed["pages"]) + 2 * max(0, len(parsed["pages"]) - 1)
        > MAX_TEXT
        or (parsed["coverage"] == "text_only" and len(parsed["pages"]) != parsed["page_count"])
    ):
        raise ValueError("Invalid sandbox extraction result.")
    previous = 0
    structure_bytes = 0
    for page in parsed["pages"]:
        if not isinstance(page["text"], str) or not previous < page["page"] <= parsed["page_count"]:
            raise ValueError("Invalid sandbox page attribution.")
        previous = page["page"]
        structure = page.get("structure")
        if structure is not None:
            size = len(json.dumps(structure, ensure_ascii=True).encode())
            structure_bytes += size
            if (
                size > 80_000
                or structure_bytes > 160_000
                or structure.get("schema_version") != "scientific-structure-3"
                or structure.get("visual_inspection_status") != "not_performed"
                or any(
                    not isinstance(structure.get(k), list) or len(structure[k]) > 80
                    for k in (
                        "text_blocks",
                        "tables",
                        "equations",
                        "figures",
                        "captions",
                        "speaker_notes",
                    )
                )
            ):
                raise ValueError("Invalid scientific structure attribution or budget.")
        if parsed.get("format") == "pptx":
            if (
                page.get("slide_number") != page["page"]
                or page.get("locator_kind") != "slide"
                or page.get("visual_render_status") != "not_rendered"
                or page.get("visual_observation") is not None
                or page.get("media_presence", {}).get("graphics_inspected") is not False
                or page.get("state") not in {"extracted", "no_text", "truncated", "unreadable"}
            ):
                raise ValueError("Invalid presentation attribution")
            end = 0
            for span in page.get("text_spans", []):
                if span.get("source_kind") not in {
                    "slide_shapes_and_tables",
                    "chart_cached_text_and_values",
                    "speaker_notes",
                } or not end <= span["start"] < span["end"] <= len(page["text"]):
                    raise ValueError("Invalid slide text attribution")
                end = span["end"]
        if parsed.get("format") == "xlsx":
            if (
                page.get("locator_kind") != "sheet"
                or not isinstance(page.get("sheet_name"), str)
                or len(page["sheet_name"]) > 128
                or page.get("sheet_state") not in {"visible", "hidden", "veryHidden"}
            ):
                raise ValueError("Invalid workbook attribution.")
            end = 0
            for span in page.get("cell_spans", []):
                if not isinstance(span.get("cell"), str) or not end <= span["start"] < span[
                    "end"
                ] <= len(page["text"]):
                    raise ValueError("Invalid workbook cell attribution.")
                end = span["end"]
    from canvas_bridge.privacy_text import document_privacy

    return document_privacy(parsed)


def extract_isolated(
    data: bytes,
    kind: str,
    root: Path,
    *,
    runtime_root: Path | None = None,
    visual: dict | None = None,
    ocr_root: Path | None = None,
    presentation_root: Path | None = None,
) -> dict:
    if (
        visual is not None
        and kind == "pdf"
        and (
            type(visual.get("memory_mb", 384)) is not int
            or not 128 <= visual.get("memory_mb", 384) <= 384
        )
    ):
        raise DomainError(
            "needs_input",
            "Invalid visual worker memory limit.",
            reason_code="VISUAL_MEMORY_LIMIT_INVALID",
        )
    if len(data) > source_limit(kind):
        raise DomainError(
            "unsupported_feature",
            "File exceeds the extraction size limit.",
            reason_code="EXTRACTION_FILE_TOO_LARGE",
            processing_stage="input_validation",
            details={
                "budget_code": "SOURCE_FILE_TOO_LARGE",
                "observed": len(data),
                "limit": source_limit(kind),
                "retryable": False,
            },
        )
    if not _slot.acquire(blocking=False):
        raise DomainError(
            "retry_later",
            "Another document is being extracted. Retry shortly.",
            reason_code="DOCUMENT_WORKER_BUSY",
            processing_stage="worker_queue",
        )
    stage = "runtime_setup"
    worker_usage = {}
    started = time.perf_counter()
    try:
        if sys.platform == "linux":
            from canvas_bridge.linux_sandbox import private_root, run

            private_root(root)
            runtime = ensure_runtime(runtime_root or root, ocr_root)
        else:
            from canvas_bridge.windows_sandbox import run

            runtime = ensure_runtime(root, ocr_root)

        if visual is not None and kind == "pptx":
            if presentation_root is None or os.name != "nt":
                raise DomainError(
                    "unsupported_feature",
                    "A supported PPTX renderer is not configured.",
                    reason_code="PPTX_RENDERER_UNAVAILABLE",
                    processing_stage="slide_rendering",
                )
            from canvas_bridge.presentation_runtime import prepare

            office_runtime = prepare(runtime, presentation_root)
            visual = {**visual, "office_root": str(office_runtime)}

        stage = "job_setup"
        jobs = root.resolve() / "jobs"
        jobs.mkdir(exist_ok=True)
        sweep_orphans(root)
        with job_directory(jobs) as directory:
            work = Path(directory).resolve()
            # Packaged Windows hosts can redirect AppData for a newly created
            # child while resolving the existing parent to its logical path.
            # Compare directory identity, not those two different path strings.
            # Require an immediate child; links escaping the job root still fail.
            if not work.parent.samefile(jobs):
                raise DomainError(
                    "retry_later",
                    "The isolated document workspace could not be validated.",
                    reason_code="DOCUMENT_WORKSPACE_INVALID",
                    processing_stage=stage,
                )
            (work / "input.bin").write_bytes(data)
            (work / "request.json").write_text(
                json.dumps(visual if visual is not None else {"kind": kind}), encoding="utf-8"
            )
            stage = "worker_execution"
            worker_usage = (
                run(
                    runtime,
                    work,
                    script="presentation_render_worker.py",
                    timeout=75,
                    presentation=True,
                )
                if visual is not None and kind == "pptx"
                else run(
                    runtime,
                    work,
                    script="visual_worker.py" if visual is not None else "worker.py",
                    **(
                        {"memory_mb": visual.get("memory_mb", 384)}
                        if visual is not None and kind == "pdf"
                        else {}
                    ),
                )
                or {}
            )
            stage = "result_read"
            path = work / "result.json"
            with path.open("rb") as stream:
                output = stream.read(2_000_001)
            if len(output) > 2_000_000:
                raise DomainError(
                    "unsupported_feature",
                    "Document worker output exceeded its budget.",
                    reason_code="DOCUMENT_OUTPUT_LIMIT",
                    processing_stage=stage,
                )
            stage = "result_validation"
            if visual is not None and visual.get("conversion_only"):
                from canvas_bridge.presentation_derivatives import validate_derivative

                with (
                    (work / "input.pdf").open("rb")
                    if json.loads(output).get("ok")
                    else nullcontext(None) as stream
                ):
                    pdf = stream.read(10_000_001) if stream else b""
                converted = validate_derivative(json.loads(output), data, pdf, visual["page"])
                converted["resource_usage"] = {
                    **worker_usage,
                    "source_bytes": len(data),
                    "processing_ms": round((time.perf_counter() - started) * 1000),
                    "worker_output_bytes": len(output),
                }
                return converted, pdf
            if visual is not None:
                from canvas_bridge.visual_files import validate_rendering

                rendered = validate_rendering(json.loads(output), data, {**visual, "kind": kind})
                if kind == "pptx":
                    rendered["resource_usage"] = {
                        **worker_usage,
                        "source_bytes": len(data),
                        "processing_ms": round((time.perf_counter() - started) * 1000),
                        "worker_output_bytes": len(output),
                    }
                return rendered
            parsed = validate_result(json.loads(output), data)
            if kind == "pptx":
                parsed["resource_usage"] = {
                    **parsed.get("resource_usage", {}),
                    **worker_usage,
                    "processing_ms": round((time.perf_counter() - started) * 1000),
                    "worker_output_bytes": len(output),
                }
            return parsed
    except DomainError as exc:
        if exc.processing_stage is None:
            exc.processing_stage = stage
        if kind == "pptx" and visual is not None:
            exc.details["resource_usage"] = {
                **worker_usage,
                "source_bytes": len(data),
                "processing_ms": round((time.perf_counter() - started) * 1000),
            }
        raise
    except TimeoutError as exc:
        raise DomainError(
            "retry_later",
            "Document processing timed out; no complete result was returned.",
            reason_code="DOCUMENT_WORKER_TIMEOUT",
            processing_stage=stage,
        ) from exc
    except Exception as exc:
        raise DomainError(
            "retry_later",
            "Document processing could not complete safely.",
            reason_code={
                "runtime_setup": "DOCUMENT_RUNTIME_SETUP_FAILED",
                "job_setup": "DOCUMENT_WORKSPACE_SETUP_FAILED",
                "worker_execution": "DOCUMENT_WORKER_FAILED",
                "result_read": "DOCUMENT_RESULT_UNAVAILABLE",
                "result_validation": "DOCUMENT_RESULT_INVALID",
            }[stage],
            processing_stage=stage,
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
        # Embedded text never needs OCR. Optional OCR setup must not break it.
        ocr_root=None,
    )

    if kind != "pdf" or settings.ocr_root is None:
        return parsed
    attempted = 0
    for page in parsed["pages"]:
        if len(page["text"].strip()) >= 40 or page["state"] in {"truncated", "resource_limit"}:
            continue
        if attempted >= 4:
            page["ocr_status"] = "skipped_budget"
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
            page["ocr_confidence"] = recognition["mean_confidence"]
            text = recognition["text"].strip()
            budget = MAX_TEXT - sum(len(p["text"]) + 2 for p in parsed["pages"])
            if text and len(text) <= budget and recognition["mean_confidence"] >= 50:
                page.update(
                    text=text,
                    state="ocr_extracted",
                    ocr_status="extracted",
                    extraction_method=recognition["method"],
                    ocr_confidence=recognition["mean_confidence"],
                    words=recognition["words"],
                    image_pixels=visual["pixels"],
                )
                parsed["warnings"] = [
                    w
                    for w in parsed["warnings"]
                    if not w.startswith(f"Page {page['page']}: no text layer")
                    and not w.startswith("No readable text was extracted.")
                ]
            else:
                page["ocr_status"] = "unusable"
                parsed["warnings"].append(
                    f"Page {page['page']}: OCR returned no usable text, low-confidence text or exceeded the text budget."
                )
        except DomainError as exc:
            page["ocr_status"] = "failed"
            page["ocr_failure"] = {"status": exc.status, **exc.data}
            parsed["warnings"].append(
                f"Page {page['page']}: OCR unavailable, failed or exceeded isolation limits. Visual reading may still work."
            )
        parsed["coverage"] = "partial"
    if attempted:
        parsed["warnings"].append(
            "OCR is an uncertain English transcription, not a verified table. Check dates, numbers, names and merged cells against render_course_file_page; colors are not interpreted."
        )
    if not any(p["text"].strip() for p in parsed["pages"]):
        failures = [p["ocr_failure"] for p in parsed["pages"] if p.get("ocr_failure")]
        if failures:
            failure = failures[0]
            raise DomainError(
                failure.get("status", "retry_later"),
                "OCR failed and no usable document text is available; this is not a zero-match result.",
                reason_code=failure.get("reason_code") or "OCR_EXTRACTION_FAILED",
                processing_stage=failure.get("processing_stage") or "ocr",
            )
    from canvas_bridge.privacy_text import document_privacy

    return document_privacy(parsed)
