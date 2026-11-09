"""Synthetic PDF worker progress, privacy and timeout recovery."""

import io
import os
import sys
import time

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf._page import PageObject
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from canvas_bridge import parser_worker
from canvas_bridge.course_files import read_file
from canvas_bridge.domain import DomainError, WorkerDeadline
from canvas_bridge.parser_sandbox import extract_document, extract_isolated
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf


def test_cross_page_annotation_privacy():
    writer = PdfWriter(
        clone_from=PdfReader(io.BytesIO(scientific_pdf(["Hello Cedar Person", "Figure"])))
    )
    writer.pages[1][NameObject("/Annots")] = ArrayObject(
        [writer._add_object(DictionaryObject({NameObject("/T"): TextStringObject("Cedar Person")}))]
    )
    stream = io.BytesIO()
    writer.write(stream)
    parsed = parser_worker.extract(stream.getvalue(), "pdf", (1, 1))
    assert parsed["pages"][0]["text"] and "Cedar Person" not in str(parsed)


@pytest.mark.parametrize("stall,window", [(3, (1, 4)), (1, (1, 4)), (2, (2, 2))])
def test_killed_worker_only_returns_finished_pages(tmp_path, monkeypatch, stall, window):
    data = scientific_pdf(["First", "Second", "Third", "Fourth"])
    from canvas_bridge import parser_sandbox

    class Interrupted(BaseException):
        pass

    original = PageObject.extract_text

    def extract_text(page, *args, **kwargs):
        if page.page_number + 1 == stall:
            raise Interrupted
        return original(page, *args, **kwargs)

    def run(runtime, work, **kwargs):
        monkeypatch.setattr(sys, "argv", ["worker.py", str(work)])
        try:
            parser_worker.main()
        except Interrupted:
            # A stopped child can leave the last progress record half written.
            with (work / "result.json").open("ab") as stream:
                stream.write(b'{"extraction":')
            expired = WorkerDeadline(15)
            expired.stopped = True
            raise expired from None

    # main() normally runs in a child. Keep its process-wide logging policy
    # local to this in-process launcher double.
    monkeypatch.setattr(parser_worker.logging, "disable", lambda level: None)
    monkeypatch.setattr(PageObject, "extract_text", extract_text)
    monkeypatch.setattr(parser_sandbox, "ensure_runtime", lambda *args: tmp_path)
    backend = "windows_sandbox" if os.name == "nt" else "linux_sandbox"
    monkeypatch.setattr("canvas_bridge." + backend + ".run", run)
    if stall == 3:
        parsed = extract_isolated(data, "pdf", tmp_path, page_range=window)
        assert [p["page"] for p in parsed["pages"]] == [1, 2]
        assert parsed["coverage"] == "partial" and "15 seconds" in parsed["warnings"][-1]
    else:
        with pytest.raises(DomainError) as raised:
            extract_isolated(data, "pdf", tmp_path, page_range=window)
        assert raised.value.reason_code == "DOCUMENT_WORKER_TIMEOUT"
        assert raised.value.details["completed_pages"] == []
        assert raised.value.details["page_start"] == window[0]
    assert not list((tmp_path / "jobs").iterdir())
    next_page = stall + 1
    recovered = extract_isolated(data, "pdf", tmp_path, page_range=(next_page, next_page))
    assert recovered["pages"][0]["page"] == next_page


@pytest.mark.skipif(
    os.name != "nt" and sys.platform != "linux", reason="Requires a supported OS sandbox"
)
async def test_real_sandbox_progressive_pdf_timings(
    tmp_path, record_property, monkeypatch, bridge, owner, seeded, readable
):
    data = scientific_pdf([f"Synthetic paper page {number}. " * 15 for number in range(1, 31)])
    root = tmp_path / "parser"
    root.mkdir(mode=0o700)
    for label, window in (("cold", (25, 25)), ("warm", (25, 25)), ("batch", (1, 4))):
        start = time.monotonic()
        result = extract_isolated(data, "pdf", root, page_range=window)
        elapsed = round(time.monotonic() - start, 2)
        record_property(label + "_seconds", elapsed)
        print(label, window, elapsed, "seconds")
        assert result["page_count"] == 30
        assert [p["page"] for p in result["pages"]] == list(range(window[0], window[1] + 1))
        assert not list((root / "jobs").iterdir())

    # Exercise the authorized service path as well. The warm worker timings
    # above still launch a process; a validated cache hit should launch none.
    _, ref = readable
    bridge.settings.parser_root = bridge.settings.parser_runtime_root = root
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    launches = []

    async def observe(*args):
        launches.append(args[-1])
        return await extract_document(*args)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", observe)
    for label in ("cache_miss", "cache_hit"):
        start = time.monotonic()
        reply = await read_file(bridge, owner, seeded, ref, page_start=25)
        elapsed = round(time.monotonic() - start, 2)
        record_property(label + "_seconds", elapsed)
        print(label, elapsed, "seconds")
        assert reply.data["passages"][0]["page"] == 25
    assert launches == [(25, 25)]

    # Inject a trusted test-only stall into the temporary runtime. The normal
    # launcher still enforces its real deadline and cleans up the child.
    from canvas_bridge.parser_sandbox import ensure_runtime

    runtime = ensure_runtime(root)
    probe = runtime / "stall_probe.py"
    probe.write_text(
        "import time, worker\n"
        "from pypdf._page import PageObject\n"
        "original = PageObject.extract_text\n"
        "def extract(page, *args, **kwargs):\n"
        "    if page.page_number == 2: time.sleep(60)\n"
        "    return original(page, *args, **kwargs)\n"
        "PageObject.extract_text = extract\n"
        "worker.main()\n",
        encoding="ascii",
    )
    if os.name == "nt":
        from canvas_bridge import windows_sandbox as backend
    else:
        from canvas_bridge import linux_sandbox as backend
    launch = backend.run

    def stall(runtime, work, **kwargs):
        return launch(runtime, work, **{**kwargs, "script": "stall_probe.py"})

    monkeypatch.setattr(backend, "run", stall)
    result = extract_isolated(data, "pdf", root, page_range=(1, 4))
    assert [p["page"] for p in result["pages"]] == [1, 2]
    assert "15 seconds" in result["warnings"][-1]
    assert not list((root / "jobs").iterdir())
