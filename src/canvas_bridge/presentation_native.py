"""Windows LibreOfficeKit host, used only inside the credential-free worker.

Kit avoids the desktop executable's instance-sharing pipe. Windows document
operations must run on Kit's own VCL thread, not the Python calling thread.
No permissions, process limits, or network capabilities are changed here.
"""

import ctypes as C
import json
import os
import sys
import threading
import time
from ctypes import wintypes as W
from pathlib import Path

# The worker converts exactly one deck and then exits. Keep callbacks and the
# native module alive through callback return and interpreter shutdown.
_lifetimes = []


class OfficeAPI(C.Structure):
    _fields_ = [
        ("size", C.c_size_t),
        ("destroy", C.CFUNCTYPE(None, C.c_void_p)),
        ("load", C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_char_p)),
        ("error", C.CFUNCTYPE(C.c_void_p, C.c_void_p)),
    ]


class Office(C.Structure):
    _fields_ = [("api", C.POINTER(OfficeAPI))]


class DocumentAPI(C.Structure):
    _fields_ = [
        ("size", C.c_size_t),
        ("destroy", C.CFUNCTYPE(None, C.c_void_p)),
        ("save", C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p)),
    ]


class Document(C.Structure):
    _fields_ = [("api", C.POINTER(DocumentAPI))]


def convert_native(office_root, profile, source, output, options, *, timeout=60):
    if os.name != "nt":
        raise ValueError("conversion_failed")
    deadline = time.monotonic() + timeout
    os.environ.update(SAL_DISABLE_OPENCL="1", SAL_DISABLESKIA="1")
    os.environ.pop("SAL_LOK_OPTIONS", None)
    registry = (office_root / "share/registry").as_uri()
    os.environ["CONFIGURATION_LAYERS"] = (
        f"xcsxcu:{registry} res:{registry} user:!"
        + (profile / "user/registrymodifications.xcu").as_uri()
    )
    program = office_root / "program"
    with os.add_dll_directory(str(program)):
        library = C.CDLL(str(program / "mergedlo.dll"))
        hook = library.libreofficekit_hook_2
        hook.restype = C.POINTER(Office)
        hook.argtypes = [C.c_char_p, C.c_char_p]
        office = hook(str(program).encode("utf-8"), profile.as_uri().encode("utf-8"))
        if not office or office.contents.api.contents.size < C.sizeof(OfficeAPI):
            raise ValueError("conversion_failed")

        user = C.WinDLL("user32", use_last_error=True)
        enum = C.WINFUNCTYPE(W.BOOL, W.HWND, C.c_void_p)
        timer_callback = C.WINFUNCTYPE(None, W.HWND, W.UINT, C.c_size_t, W.DWORD)
        user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        user.EnumWindows.argtypes = [enum, C.c_void_p]
        user.SetTimer.argtypes = [W.HWND, C.c_size_t, W.UINT, timer_callback]
        user.SetTimer.restype = C.c_size_t
        user.KillTimer.argtypes = [W.HWND, C.c_size_t]
        windows = []

        @enum
        def find(hwnd, _):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            name = C.create_unicode_buffer(64)
            user.GetClassNameW(hwnd, name, len(name))
            # Never send messages to a window in another process. Fail closed
            # if a future Windows VCL backend changes its dispatch window.
            if pid.value == os.getpid() and name.value == "SALCOMWND":
                windows.append(hwnd)
            return True

        if not user.EnumWindows(find, None) or len(windows) != 1:
            raise ValueError("conversion_failed")
        done = threading.Event()
        failures = []

        @timer_callback
        def perform(hwnd, _message, timer, _ticks):
            user.KillTimer(hwnd, timer)
            document = None
            try:
                pointer = office.contents.api.contents.load(office, source.as_uri().encode("utf-8"))
                if not pointer:
                    raise ValueError("conversion_failed")
                document = C.cast(pointer, C.POINTER(Document))
                api = document.contents.api.contents
                if api.size < C.sizeof(DocumentAPI):
                    document = None
                    raise ValueError("conversion_failed")
                if not api.save(
                    document,
                    output.as_uri().encode("utf-8"),
                    b"pdf",
                    json.dumps(options, separators=(",", ":")).encode(),
                ):
                    raise ValueError("conversion_failed")
            except Exception:
                failures.append(True)  # Never export native error text or source paths.
            finally:
                try:
                    if document:
                        document.contents.api.contents.destroy(document)
                except Exception:
                    failures.append(True)
                done.set()

        timer = user.SetTimer(windows[0], 0, 50, perform)
        _lifetimes.append((library, office, find, perform))
        if not timer:
            raise ValueError("conversion_failed")
        if not done.wait(max(0, deadline - time.monotonic())):
            # A native callback can still be in progress. Do not unwind ctypes
            # callbacks/DLLs underneath it; the outer Job kills the entire worker.
            os._exit(124)
        if failures or not output.is_file():
            raise ValueError("conversion_failed")


if __name__ == "__main__":
    # Fixed child of the preflight worker; same AppContainer and non-breakaway
    # Job. Do not import Pillow/PDFium or retain source/archive bytes here.
    work = Path(sys.argv[1])
    try:
        request = json.loads((work / "native-request.json").read_text(encoding="utf-8"))
        convert_native(
            Path(request["office_root"]),
            work / "profile",
            work / "input.pptx",
            work / "input.pdf",
            request["options"],
        )
    except Exception:
        sys.exit(1)
