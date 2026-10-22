"""Real kernel isolation tests on Linux. Never replace them with mocked success."""

import json
import os
import socket
import subprocess
import sys

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.linux_sandbox import ensure_runtime, run
from canvas_bridge.parser_sandbox import extract_isolated
from tests.test_academic_intelligence import ooxml
from tests.test_file_reading import scientific_pdf

linux = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Requires a real Linux kernel; Windows has separate AppContainer proofs.",
)


@pytest.fixture(scope="module")
def linux_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("landlock-parser")
    ensure_runtime(root)
    return root


@linux
@pytest.mark.parametrize("kind", ["pdf", "txt", "md", "docx", "pptx"])
def test_T23_T25_linux_real_format_extraction(linux_root, kind):
    data = (
        scientific_pdf()
        if kind == "pdf"
        else ooxml(kind)
        if kind in {"docx", "pptx"}
        else "Methods: synthetic controlled cultures, μM units.".encode()
    )
    result = extract_isolated(data, kind, linux_root)
    assert result["coverage"] == "text_only"
    assert any("controlled" in p["text"] for p in result["pages"])
    if kind == "pdf":
        assert result["page_count"] == 3
        assert "Conclusions" in result["pages"][2]["text"]
    assert not list((linux_root / "jobs").iterdir())


@linux
def test_T23_linux_private_file_env_network_process_and_resource_denial(
    linux_root, tmp_path, monkeypatch
):
    runtime = ensure_runtime(linux_root)
    secret = tmp_path / "private.env"
    secret.write_text("synthetic-private-canary", encoding="utf-8")
    assert secret.read_text(encoding="utf-8") == "synthetic-private-canary"
    control = runtime / "parent_control.txt"
    control.write_text("parent can write", encoding="utf-8")
    control.unlink()
    work = tmp_path / "probe"
    work.mkdir()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    with socket.create_connection(listener.getsockname(), 2):
        peer, _ = listener.accept()
        peer.close()
    fd = os.open(secret, os.O_RDONLY)
    os.set_inheritable(fd, True)
    monkeypatch.setenv("CANVAS_SECRET_CANARY", "synthetic-private-canary")
    probe = runtime / "probe.py"
    probe.write_text(
        """import json, os, socket, subprocess, sys
from pathlib import Path
work=Path(sys.argv[1]); request=json.loads((work/'probe-request.json').read_text())
result={'secret_env_absent':'CANVAS_SECRET_CANARY' not in os.environ}
actions=[('private_file',lambda:Path(request['secret']).read_bytes()),
 ('private_write',lambda:Path(request['secret']).write_text('bad')),
 ('host_config',lambda:Path('/etc/passwd').read_text()),
 ('parent_job_listing',lambda:list(work.parent.iterdir())),
 ('loopback',lambda:socket.create_connection(('127.0.0.1',request['port']),1)),
 ('internet_socket',lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM)),
 ('udp_socket',lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM)),
 ('unix_socket',lambda:socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)),
 ('child_process',lambda:subprocess.run([sys.executable,'-c','pass'],check=True)),
 ('fork',lambda:os.fork()),
 ('runtime_write',lambda:Path(__file__).with_name('bad.txt').write_text('bad')),
 ('memory_limit',lambda:bytearray(512*1024*1024)),
 ('output_limit',lambda:(work/'result.json').write_bytes(b'x'*3_000_000)),
 ('file_creation',lambda:(work/'unexpected').write_bytes(b'bad')),
 ('input_write',lambda:(work/'probe-request.json').write_text('bad')),
 ('descriptor_closed',lambda:os.read(request['fd'],100)),
 ('service_import',lambda:__import__('canvas_bridge'))]
for name, action in actions:
 try:
  action(); result[name]=False
 except (OSError,MemoryError,ImportError): result[name]=True
result['bounded_output']=(work/'result.json').stat().st_size <= 2_000_000
(work/'result.json').write_text(json.dumps(result))
""",
        encoding="utf-8",
    )
    (work / "probe-request.json").write_text(
        json.dumps({"secret": str(secret), "port": listener.getsockname()[1], "fd": fd}),
        encoding="utf-8",
    )
    try:
        run(runtime, work, script="probe.py")
        proof = json.loads((work / "result.json").read_text(encoding="utf-8"))
        assert all(proof.values()), proof
        assert not (work / "unexpected").exists()
        assert json.loads((work / "probe-request.json").read_text(encoding="utf-8"))["fd"] == fd
        assert secret.read_text(encoding="utf-8") == "synthetic-private-canary"
        listener.settimeout(0.1)
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        os.close(fd)
        listener.close()
        probe.unlink(missing_ok=True)


@linux
def test_T23_linux_timeout_reaps_worker(linux_root, tmp_path, monkeypatch):
    runtime = ensure_runtime(linux_root)
    probe = runtime / "timeout_probe.py"
    probe.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    processes, popen = [], subprocess.Popen

    def capture(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("canvas_bridge.linux_sandbox.subprocess.Popen", capture)
    try:
        with pytest.raises(TimeoutError):
            run(runtime, tmp_path, script="timeout_probe.py", timeout=1)
        assert len(processes) == 1 and processes[0].poll() is not None
    finally:
        probe.unlink(missing_ok=True)


@linux
def test_T23_linux_cpu_limit_and_corrupt_input(linux_root, tmp_path):
    runtime = ensure_runtime(linux_root)
    probe = runtime / "cpu_probe.py"
    probe.write_text("while True: pass\n", encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="resource limits"):
            run(runtime, tmp_path, script="cpu_probe.py")
    finally:
        probe.unlink(missing_ok=True)
    with pytest.raises(DomainError, match="corrupt_or_unreadable"):
        extract_isolated(b"%PDF-corrupted synthetic contents", "pdf", linux_root)
    assert not list((linux_root / "jobs").iterdir())


@linux
def test_T23_linux_runtime_contains_only_public_parser_code(linux_root):
    runtime = ensure_runtime(linux_root)
    assert {p.name for p in (runtime / "site").iterdir()} == {
        "pypdf",
        "defusedxml",
        "pypdfium2",
        "pypdfium2_raw",
        "pypdfium2_cfg",
        "PIL",
        "pillow.libs",
        "openpyxl",
        "et_xmlfile",
    }
    assert not (runtime / "site/canvas_bridge").exists()
    assert (runtime / "stdlib.zip").is_file()
    assert list((runtime / "dynload").glob("*.so"))
    assert ensure_runtime(linux_root) == runtime


@linux
def test_T23_linux_rejects_public_root_and_script_escape(tmp_path, linux_root):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(DomainError, match="owner-only"):
        ensure_runtime(public)
    runtime = ensure_runtime(linux_root)
    with pytest.raises(DomainError, match="launch"):
        run(runtime, tmp_path, script="../outside.py")
    with pytest.raises(DomainError, match="separate"):
        run(runtime, runtime)


def test_T23_linux_no_unrestricted_fallback(tmp_path, monkeypatch):
    import canvas_bridge.parser_sandbox as sandbox

    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox, "ensure_runtime", lambda root, ocr_root=None: tmp_path)
    monkeypatch.setattr("canvas_bridge.linux_sandbox.private_root", lambda root: root)

    def unavailable(*args, **kwargs):
        raise DomainError("unsupported_feature", "Kernel isolation unavailable.")

    monkeypatch.setattr("canvas_bridge.linux_sandbox.run", unavailable)
    with pytest.raises(DomainError, match="Kernel isolation unavailable"):
        sandbox.extract_isolated(b"private document canary", "txt", tmp_path)
    assert not list((tmp_path / "jobs").iterdir())


@linux
def test_T23_linux_readonly_runtime_separate_from_document_jobs(linux_root, tmp_path):
    runtime = ensure_runtime(linux_root)
    runtime.chmod(0o500)
    linux_root.chmod(0o500)
    try:
        for n in range(2):
            root = tmp_path / str(n)
            result = extract_isolated(b"Separate private job", "txt", root, runtime_root=linux_root)
            assert result["pages"][0]["text"] == "Separate private job"
            assert not list((root / "jobs").iterdir())
    finally:
        linux_root.chmod(0o700)
        runtime.chmod(0o700)


@linux
def test_T23_linux_rejects_root_execution(tmp_path, monkeypatch):
    monkeypatch.setattr("canvas_bridge.linux_sandbox.os.geteuid", lambda: 0)
    with pytest.raises(DomainError, match="unprivileged"):
        ensure_runtime(tmp_path / "never-created")
    assert not (tmp_path / "never-created").exists()
