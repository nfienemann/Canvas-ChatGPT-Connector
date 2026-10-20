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
import pypdf

from canvas_bridge.domain import DomainError
from canvas_bridge.parser_worker import MAX_TEXT, PARSER

_slot = threading.Lock()


def ensure_runtime(root: Path) -> Path:
    if sys.platform == "linux":
        from canvas_bridge.linux_sandbox import ensure_runtime as linux_runtime

        return linux_runtime(root)
    if os.name != "nt":
        raise DomainError(
            "unsupported_feature",
            "Isolated file extraction requires a supported Windows or Linux sandbox.",
        )
    from canvas_bridge.windows_sandbox import acl

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name("parser_worker.py")
    digest = hashlib.sha256(
        worker.read_bytes()
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
        }
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
    data: bytes, kind: str, root: Path, *, runtime_root: Path | None = None
) -> dict:
    if len(data) > 10_000_000:
        raise DomainError("unsupported_feature", "File exceeds the extraction size limit.")
    if not _slot.acquire(blocking=False):
        raise DomainError("retry_later", "Another document is being extracted. Retry shortly.")
    try:
        if sys.platform == "linux":
            from canvas_bridge.linux_sandbox import private_root, run

            private_root(root)
            runtime = ensure_runtime(runtime_root or root)
        else:
            from canvas_bridge.windows_sandbox import run

            runtime = ensure_runtime(root)

        jobs = root.resolve() / "jobs"
        jobs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="document-", dir=jobs) as directory:
            work = Path(directory).resolve()
            if not work.is_relative_to(jobs.resolve()):
                raise RuntimeError("Invalid temporary extraction location.")
            (work / "input.bin").write_bytes(data)
            (work / "request.json").write_text(json.dumps({"kind": kind}), encoding="utf-8")
            run(runtime, work)
            path = work / "result.json"
            with path.open("rb") as stream:
                output = stream.read(2_000_001)
            if len(output) > 2_000_000:
                raise ValueError("Extraction output exceeded its budget.")
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
    return await asyncio.to_thread(
        extract_isolated,
        data,
        kind,
        settings.parser_root,
        runtime_root=settings.parser_runtime_root,
    )
