"""Run structural scanning in the same bounded, credential-free OS worker as readers."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from canvas_bridge.domain import DomainError
from canvas_bridge.library.contracts import fail
from canvas_bridge.worker_storage import job_directory


def scan_isolated(data, kind, settings, preview=False):
    from canvas_bridge.parser_sandbox import ensure_runtime

    if not settings.parser_root:
        fail("SCAN_UNAVAILABLE", "retry_later", retryable=True)
    try:
        root = settings.parser_root.resolve()
        runtime = ensure_runtime(root)
        if sys.platform == "linux":
            from canvas_bridge.linux_sandbox import run
        else:
            from canvas_bridge.windows_sandbox import run
        jobs = root / "jobs"
        jobs.mkdir(exist_ok=True)
        with job_directory(jobs) as directory:
            work = Path(directory)
            (work / "input.bin").write_bytes(data)
            (work / "request.json").write_text(json.dumps({"kind": kind, "preview": preview}))
            run(runtime, work, script="library_safety_worker.py", timeout=30, memory_mb=384)
            with (work / "result.json").open("rb") as stream:
                raw = stream.read(3_000_001)
            if len(raw) > 3_000_000:
                fail("SCAN_UNAVAILABLE", "retry_later")
            result = json.loads(raw)
        if not result.get("ok"):
            reason = result.get("reason")
            if reason not in {
                "UNSAFE_CONTENT",
                "UNSAFE_ARCHIVE",
                "UNSUPPORTED_MEDIA",
                "UPLOAD_TOO_LARGE",
                "PROCESSING_UNSUPPORTED",
            }:
                reason = "SCAN_UNAVAILABLE"
            fail(reason, "unsupported_feature")
        inspection = result["inspection"]
        if (
            inspection["sha256"] != hashlib.sha256(data).hexdigest()
            or inspection["bytes"] != len(data)
            or inspection["kind"] != kind
        ):
            fail("CHECKSUM_MISMATCH")
        return inspection
    except DomainError:
        raise
    except Exception:
        fail("SCAN_UNAVAILABLE", "retry_later", retryable=True)


async def scan(data, kind, settings, preview=False):
    return await asyncio.to_thread(scan_isolated, data, kind, settings, preview)
