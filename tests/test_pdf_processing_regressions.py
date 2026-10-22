"""Synthetic regressions for the 2026-10-22 PDF incident; no academic records."""

import base64
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.course_files import read_file, status
from canvas_bridge.domain import DomainError
from canvas_bridge.parser_sandbox import extract_document, extract_isolated
from canvas_bridge.parser_worker import extract
from canvas_bridge.visual_files import render_document, validate_rendering
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


@pytest.fixture
def fake_worker(monkeypatch, tmp_path):
    """Simulate only OS launch for path/error tests, using synthetic bytes."""
    module = (
        "canvas_bridge.linux_sandbox"
        if sys.platform == "linux"
        else "canvas_bridge.windows_sandbox"
    )
    monkeypatch.setattr("canvas_bridge.parser_sandbox.ensure_runtime", lambda *a: tmp_path)

    def run(runtime, work, **kwargs):
        result = {"ok": True, "extraction": extract((work / "input.bin").read_bytes(), "pdf")}
        (work / "result.json").write_text(json.dumps(result))

    monkeypatch.setattr(module + ".run", run)
    return module


def test_redirected_job_parent_uses_directory_identity(tmp_path, monkeypatch, fake_worker):
    root = tmp_path / "parser"
    root.mkdir(mode=0o700)
    logical = root / "jobs"
    physical = root / "redirected-jobs"
    physical.mkdir()
    real_resolve, real_samefile = Path.resolve, Path.samefile

    def resolve(path, *args, **kwargs):
        resolved = real_resolve(path, *args, **kwargs)
        if resolved.parent == logical and resolved.name.startswith("document-"):
            # Model Windows AppData: existing parent resolves logically, newly
            # created child resolves physically, both parents are the same dir.
            destination = physical / resolved.name
            resolved.rename(destination)
            return destination
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(
        Path,
        "samefile",
        lambda left, right: (
            True if left == physical and right == logical else real_samefile(left, right)
        ),
    )
    result = extract_isolated(scientific_pdf(), "pdf", root)
    assert "Conclusions:" in result["pages"][2]["text"]


def test_job_resolved_outside_root_is_rejected_before_writes(tmp_path, monkeypatch, fake_worker):
    root = tmp_path / "parser"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        resolved = real_resolve(path, *args, **kwargs)
        if resolved.parent == root / "jobs" and resolved.name.startswith("document-"):
            return outside / resolved.name
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(DomainError) as error:
        extract_isolated(scientific_pdf(), "pdf", root)
    assert error.value.reason_code == "DOCUMENT_WORKSPACE_INVALID"
    assert not list(outside.iterdir())
    assert not list((root / "jobs").iterdir())


@pytest.mark.parametrize(
    "failure,code,stage",
    [
        ("runtime", "DOCUMENT_RUNTIME_SETUP_FAILED", "runtime_setup"),
        ("timeout", "DOCUMENT_WORKER_TIMEOUT", "worker_execution"),
        ("exit", "DOCUMENT_WORKER_EXITED", "worker_execution"),
        ("missing", "DOCUMENT_RESULT_UNAVAILABLE", "result_read"),
        ("invalid", "DOCUMENT_RESULT_INVALID", "result_validation"),
        ("oversize", "DOCUMENT_OUTPUT_LIMIT", "result_read"),
    ],
)
def test_processing_errors_are_bounded_and_stage_specific(
    tmp_path, monkeypatch, fake_worker, failure, code, stage
):
    secret = "synthetic-private-document-secret"

    def failed_runtime(*args):
        raise OSError(secret)

    def run(runtime, work, **kwargs):
        if failure == "timeout":
            raise TimeoutError(secret)
        if failure == "exit":
            raise DomainError(
                "retry_later",
                "Worker exited.",
                reason_code="DOCUMENT_WORKER_EXITED",
                processing_stage="worker_execution",
                worker_exit_code=1,
            )
        if failure == "invalid":
            (work / "result.json").write_text(secret)
        if failure == "oversize":
            (work / "result.json").write_bytes(b"x" * 2_000_001)

    if failure == "runtime":
        monkeypatch.setattr("canvas_bridge.parser_sandbox.ensure_runtime", failed_runtime)
    monkeypatch.setattr(fake_worker + ".run", run)
    root = tmp_path / "parser"
    root.mkdir(mode=0o700)
    with pytest.raises(DomainError) as error:
        extract_isolated(scientific_pdf(), "pdf", root)
    assert error.value.reason_code == code
    assert error.value.processing_stage == stage
    assert secret not in str(error.value) + json.dumps(error.value.data)
    if failure == "exit":
        assert error.value.data["worker_exit_code"] == 1
    if (root / "jobs").exists():
        assert not list((root / "jobs").iterdir())
    # Failures release the concurrency slot for the next request.
    from canvas_bridge.parser_sandbox import _slot

    assert not _slot.locked()


def test_worker_errors_do_not_echo_untrusted_reasons():
    from canvas_bridge.parser_sandbox import validate_result

    for validate in (
        lambda: validate_result({"ok": False, "reason": "private filename"}, b""),
        lambda: validate_rendering({"ok": False, "reason": "private filename"}, b"", {}),
    ):
        with pytest.raises(DomainError) as error:
            validate()
        assert "private filename" not in str(error.value) + json.dumps(error.value.data)
        assert error.value.reason_code.endswith("FAILED")


def test_changed_worker_version_requires_restart_not_unchecked_results():
    from canvas_bridge.parser_sandbox import validate_result

    data = scientific_pdf()
    parsed = extract(data, "pdf")
    parsed["parser"] = "new-worker-version"
    with pytest.raises(DomainError) as error:
        validate_result({"ok": True, "extraction": parsed}, data)
    assert error.value.reason_code == "DOCUMENT_PARSER_VERSION_CHANGED"
    assert error.value.status == "retry_later"
    assert error.value.processing_stage == "result_validation"


async def test_missing_continuation_hash_rejected_before_download(
    bridge, owner, seeded, readable, monkeypatch
):
    _, ref = readable

    async def unexpected(*args, **kwargs):
        pytest.fail("Missing continuation hash must not trigger download or extraction")

    monkeypatch.setattr("canvas_bridge.course_files.download_file", unexpected)
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", unexpected)
    with pytest.raises(DomainError) as error:
        await read_file(bridge, owner, seeded, ref, offset=10)
    assert error.value.reason_code == "CONTINUATION_HASH_REQUIRED"
    assert (await status(bridge, owner, seeded, ref)).data["state"] == "available"


async def test_changed_ocr_installation_invalidates_partial_cache(
    bridge, owner, seeded, readable, tmp_path, monkeypatch
):
    from canvas_bridge.storage import Material

    _, ref = readable
    bridge.settings.ocr_root = tmp_path / "old-location"
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.file_state = {**row.file_state, "stage": "partially_parsed"}
        old_key = row.file_state["ocr_configuration"]
        assert str(tmp_path) not in json.dumps(row.file_state)
    calls = []

    async def retried(data, kind, settings):
        calls.append(True)
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", retried)
    bridge.settings.ocr_root = tmp_path / "new-location"
    assert "Methods:" in (await read_file(bridge, owner, seeded, ref)).data["text"]
    assert calls == [True]
    with bridge.store.transaction() as session:
        assert session.get(Material, ref).file_state["ocr_configuration"] != old_key


def test_missing_ocr_installation_has_safe_specific_reason(tmp_path):
    from canvas_bridge.ocr_runtime import files

    with pytest.raises(DomainError) as error:
        files(tmp_path / "private-operator-path")
    assert error.value.reason_code == "OCR_INSTALLATION_UNAVAILABLE"
    assert "private-operator-path" not in str(error.value) + json.dumps(error.value.data)


async def test_failure_status_retries_and_search_preserves_reason(
    bridge, owner, seeded, readable, monkeypatch
):
    from canvas_bridge.document_search import search_documents

    course, ref = readable

    async def fail(*args):
        raise DomainError(
            "retry_later",
            "Worker setup failed.",
            reason_code="DOCUMENT_RUNTIME_SETUP_FAILED",
            processing_stage="runtime_setup",
        )

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", fail)
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref)
    state = (await status(bridge, owner, seeded, ref)).data
    assert state["state"] == "failed" and not state["indexed"]
    assert state["processing_stage"] == "runtime_setup"
    assert state["rendering_outcome"] == "not_tracked"
    search = await search_documents(
        bridge, owner, seeded, course.id, "Methods", limit=10, cursor=None, max_documents=1
    )
    failure = search.data["document_statuses"][0]
    assert failure["reason_code"] == "DOCUMENT_RUNTIME_SETUP_FAILED"
    assert failure["processing_stage"] == "runtime_setup"
    assert search.data["pass_progress"]["failed_documents"] == 1

    async def repaired(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", repaired)
    assert "Methods:" in (await read_file(bridge, owner, seeded, ref)).data["text"]


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows AppData and AppContainer regression")
async def test_real_appdata_text_and_render_do_not_require_ocr(settings):
    settings.file_reading_enabled = True
    settings.parser_root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    settings.ocr_root = settings.parser_root / "missing-optional-ocr"
    data = scientific_pdf()
    result = await extract_document(data, "pdf", settings)
    assert "Conclusions:" in result["pages"][2]["text"]
    rendering = await render_document(data, settings)
    assert base64.b64decode(rendering["png"]).startswith(b"\x89PNG")


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows worker startup and exit diagnostics")
def test_real_worker_start_and_exit_failures_are_distinct(tmp_path):
    from canvas_bridge.parser_sandbox import ensure_runtime
    from canvas_bridge.windows_sandbox import run

    work = tmp_path / "job"
    work.mkdir()
    with pytest.raises(DomainError) as start:
        run(tmp_path / "missing-runtime", work)
    assert start.value.reason_code == "DOCUMENT_WORKER_START_FAILED"
    assert start.value.processing_stage == "worker_start"
    runtime = ensure_runtime(Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser")
    with pytest.raises(DomainError) as exited:
        run(runtime, work, script="missing_synthetic_worker.py")
    assert exited.value.reason_code == "DOCUMENT_WORKER_EXITED"
    assert exited.value.data["worker_exit_code"] == 2


@pytest.mark.contract
@pytest.mark.skipif(os.name != "nt", reason="Real PDF worker through HTTP MCP on Windows")
async def test_pdf_read_and_render_first_through_actual_mcp_worker(
    running, token_factory, seeded, readable, bridge, monkeypatch
):
    course, ref = readable
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", extract_document)
    bridge.settings.parser_root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    bridge.settings.ocr_root = bridge.settings.parser_root / "missing-optional-ocr"
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                args = {"connection_id": seeded, "file_id": ref}
                render = await session.call_tool("render_course_file_page", {**args, "page": 1})
                assert render.structuredContent["status"] == "ok"
                assert any(c.type == "image" for c in render.content)
                first = await session.call_tool("read_course_file", {**args, "length": 40})
                assert first.structuredContent["status"] == "ok"
                missing_hash = await session.call_tool("read_course_file", {**args, "offset": 40})
                assert (
                    missing_hash.structuredContent["data"]["reason_code"]
                    == "CONTINUATION_HASH_REQUIRED"
                )
                mismatch = await session.call_tool(
                    "read_course_file", {**args, "offset": 40, "expected_hash": "0" * 64}
                )
                assert mismatch.structuredContent["status"] == "source_changed"
                data = first.structuredContent["data"]
                reconstructed = data["text"]
                while data["continuation"]:
                    next_read = await session.call_tool(
                        "read_course_file",
                        {"connection_id": seeded, **data["continuation"], "length": 40},
                    )
                    assert next_read.structuredContent["status"] == "ok"
                    data = next_read.structuredContent["data"]
                    reconstructed += data["text"]
                full = await session.call_tool(
                    "fetch_course_material",
                    {
                        "connection_id": seeded,
                        "material_id": ref,
                    },
                )
                assert reconstructed == full.structuredContent["data"]["text"]
                found = await session.call_tool(
                    "search_course_files",
                    {
                        "connection_id": seeded,
                        "course_id": course.id,
                        "query": "replication",
                    },
                )
                assert found.structuredContent["data"]["results"][0]["page"] == 3
