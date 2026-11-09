import asyncio

import pytest

from canvas_bridge import parser_sandbox as sandbox
from canvas_bridge.course_files import read_file
from canvas_bridge.domain import DomainError
from canvas_bridge.worker_storage import invalidate
from tests.test_file_reading import readable as readable


@pytest.mark.parametrize("revoked", [False, True])
async def test_pdf_read_rechecks_scope_after_contention_without_redownload(
    bridge, owner, seeded, readable, monkeypatch, tmp_path, revoked
):
    _, file_id = readable
    bridge.settings.parser_root = bridge.settings.parser_runtime_root = tmp_path
    monkeypatch.setattr("canvas_bridge.course_files.extract_document", sandbox.extract_document)
    busy = asyncio.Event()
    loop = asyncio.get_running_loop()
    original = sandbox.extract_isolated

    def observe(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except DomainError as exc:
            if exc.reason_code == "DOCUMENT_WORKER_BUSY":
                loop.call_soon_threadsafe(busy.set)
            raise

    monkeypatch.setattr(sandbox, "extract_isolated", observe)
    with sandbox._slot:
        task = asyncio.create_task(read_file(bridge, owner, seeded, file_id, page_start=1))
        await asyncio.wait_for(busy.wait(), timeout=10)
        if revoked:
            invalidate(owner, seeded, namespace=bridge.processing_namespace)
    if revoked:
        with pytest.raises(DomainError) as denied:
            await task
        assert denied.value.status == "permission_denied"
    else:
        result = await task
        assert result.data["passages"][0]["page"] == 1
        assert result.data["text"]
    assert sum(r.url.path.endswith("/download") for r in bridge.synthetic.requests) == 1


async def test_extra_pdf_fails_promptly_and_cancelled_waiter_never_replays(
    settings, tmp_path, monkeypatch
):
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path
    attempts = []
    original = sandbox.extract_isolated

    def observe(data, *args, **kwargs):
        attempts.append(data)
        return original(data, *args, **kwargs)

    monkeypatch.setattr(sandbox, "extract_isolated", observe)
    with sandbox._slot:
        waiting = asyncio.create_task(sandbox.extract_document(b"first", "pdf", settings))
        try:
            async with asyncio.timeout(2):
                while not sandbox._pdf_waiter.locked():  # noqa: ASYNC110 - observe production lock
                    await asyncio.sleep(0.01)
            with pytest.raises(DomainError) as full:
                await asyncio.wait_for(sandbox.extract_document(b"second", "pdf", settings), 1)
            assert full.value.reason_code == "DOCUMENT_WORKER_BUSY"
            assert full.value.processing_stage == "worker_queue"
        finally:
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
    assert not sandbox._pdf_waiter.locked()
    assert attempts == [b"first", b"second"]


async def test_queue_deadline_preserves_busy_without_starting_worker(
    settings, tmp_path, monkeypatch
):
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path / "parser"
    monkeypatch.setattr(sandbox, "PDF_QUEUE_WAIT_SECONDS", 0.05)
    with sandbox._slot, pytest.raises(DomainError) as busy:
        await asyncio.wait_for(sandbox.extract_document(b"fixture", "pdf", settings), 1)
    assert busy.value.status == "retry_later"
    assert busy.value.reason_code == "DOCUMENT_WORKER_BUSY"
    assert busy.value.processing_stage == "worker_queue"
    assert not sandbox._pdf_waiter.locked()
    assert not settings.parser_root.exists()


@pytest.mark.parametrize(
    "kind,reason,stage,expected_calls",
    [
        ("pdf", "DOCUMENT_WORKER_BUSY", "worker_queue", 2),
        ("docx", "DOCUMENT_WORKER_BUSY", "worker_queue", 1),
        ("pdf", "DOCUMENT_WORKER_TIMEOUT", "worker_execution", 1),
        ("pdf", "RESOURCE_PERMISSION_DENIED", "authorization", 1),
    ],
)
async def test_only_pdf_admission_failure_is_replayed_once(
    settings, tmp_path, monkeypatch, kind, reason, stage, expected_calls
):
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path
    calls = []

    def reject(*args, **kwargs):
        calls.append(kind)
        raise DomainError("retry_later", "fixture", reason_code=reason, processing_stage=stage)

    monkeypatch.setattr(sandbox, "extract_isolated", reject)
    with pytest.raises(DomainError) as error:
        await sandbox.extract_document(b"fixture", kind, settings)
    assert error.value.reason_code == reason
    assert len(calls) == expected_calls
