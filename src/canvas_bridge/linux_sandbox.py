"""Linux Landlock + seccomp launcher. Never fall back to an unrestricted parser."""

import errno
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

import defusedxml
import PIL
import pypdf
import pypdfium2
import pypdfium2_cfg
import pypdfium2_raw

from canvas_bridge import ocr_runtime
from canvas_bridge.domain import DomainError


def private_root(root: Path) -> Path:
    if sys.platform != "linux":
        raise DomainError("unsupported_feature", "Linux kernel isolation is unavailable.")
    if os.geteuid() == 0:
        raise DomainError(
            "unsupported_feature", "Run Linux document extraction as a dedicated unprivileged user."
        )
    root = root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise DomainError(
            "unsupported_feature",
            "The Linux parser requires an owner-only dedicated directory (mode 0700).",
        )
    return root


def ensure_runtime(root: Path, ocr_root: Path | None = None) -> Path:
    root = private_root(root)
    worker = Path(__file__).with_name("parser_worker.py")
    office = Path(__file__).with_name("office_package.py")
    visual = Path(__file__).with_name("visual_worker.py")
    ocr = Path(__file__).with_name("ocr_worker.py")
    bootstrap = Path(__file__).with_name("linux_worker.py")
    library = Path(sysconfig.get_path("stdlib"))
    native = Path(sysconfig.get_config_var("DESTSHARED") or library / "lib-dynload")
    digest = hashlib.sha256(
        worker.read_bytes()
        + office.read_bytes()
        + visual.read_bytes()
        + PIL.__version__.encode()
        + ocr.read_bytes()
        + ocr_runtime.version(ocr_root)
        + b"runtime-with-pdfium-cfg-v1"
        + str(pypdfium2.PYPDFIUM_INFO).encode()
        + str(pypdfium2.PDFIUM_INFO).encode()
        + bootstrap.read_bytes()
        + sys.version.encode()
        + pypdf.__version__.encode()
        + defusedxml.__version__.encode()
    ).hexdigest()[:20]
    runtime = root / ("linux-runtime-" + digest)
    if (runtime / "ready").is_file() and (runtime / "ready").read_text(encoding="ascii") == digest:
        return runtime
    with tempfile.TemporaryDirectory(prefix="preparing-", dir=root) as directory:
        stage = Path(directory)
        excluded = {
            "site-packages",
            "dist-packages",
            "test",
            "tests",
            "__pycache__",
            "idlelib",
            "tkinter",
            "ensurepip",
            "turtledemo",
        }
        with zipfile.ZipFile(stage / "stdlib.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for source in library.rglob("*.py"):
                relative = source.relative_to(library)
                if not excluded.intersection(relative.parts):
                    archive.write(source, relative.as_posix())
        (stage / "dynload").mkdir()
        for source in native.glob("*.so"):
            if not source.name.startswith(("_test", "xx", "_tkinter", "_ctypes_test")):
                shutil.copy2(source, stage / "dynload" / source.name)
        for package in (
            pypdf,
            defusedxml,
            pypdfium2,
            pypdfium2_raw,
            pypdfium2_cfg,
            PIL,
        ):
            shutil.copytree(
                Path(package.__file__).parent,
                stage / "site" / package.__name__,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        pillow_libs = Path(PIL.__file__).parent.parent / "pillow.libs"
        if pillow_libs.is_dir():
            shutil.copytree(pillow_libs, stage / "site/pillow.libs")
        shutil.copy2(worker, stage / "worker.py")
        shutil.copy2(office, stage / "office_package.py")
        shutil.copy2(visual, stage / "visual_worker.py")
        shutil.copy2(ocr, stage / "ocr_worker.py")
        ocr_runtime.copy(ocr_root, stage)
        shutil.copy2(bootstrap, stage / "bootstrap.py")
        (stage / "ready").write_text(digest, encoding="ascii")
        try:
            stage.rename(runtime)
        except OSError as exc:
            if (
                exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}
                or not (runtime / "ready").is_file()
            ):
                raise
    return runtime


def run(runtime: Path, work: Path, *, script="worker.py", timeout=15):
    if sys.platform != "linux" or not re.fullmatch(r"[a-z_]+\.py", script) or not 0 < timeout <= 15:
        raise DomainError("unsupported_feature", "Invalid Linux extraction launch.")
    runtime, work = runtime.resolve(), work.resolve()
    if work == runtime or work.is_relative_to(runtime) or runtime.is_relative_to(work):
        raise DomainError(
            "unsupported_feature", "Parser code and document directories must be separate."
        )
    # The child cannot create files or modify input. Combined with RLIMIT_FSIZE,
    # a single precreated output gives a total writable-document budget of 2 MB.
    with (work / "result.json").open("xb"):
        pass
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(runtime / "bootstrap.py"),
        str(runtime),
        str(work),
        script,
        str(os.getpid()),
    ]
    # No preexec_fn (unsafe in a threaded service), shell, inherited environment,
    # descriptors, output pipe accumulation or document-controlled executable.
    with subprocess.Popen(  # noqa: S603 - trusted executable/runtime and validated local script.
        command,
        cwd=work,
        env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    ) as process:
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise TimeoutError("Isolated extraction exceeded its wall-time limit.") from exc
    if code == 77:
        raise DomainError(
            "unsupported_feature",
            "Linux document isolation could not be established. Landlock ABI 3+ and libseccomp are required; no unrestricted extraction was attempted.",
        )
    if code:
        raise RuntimeError("Isolated extraction failed or exceeded resource limits.")
