"""Windows AppContainer launcher with no capabilities and a bounded Job Object.

The child starts suspended, receives no inherited handles or service environment,
and enters a one-process, memory/CPU-limited job before any Python executes.
"""

import ctypes as C
import os
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path
from uuid import uuid4


def acl(path: Path, *arguments: str):
    result = subprocess.run(  # noqa: S603 - fixed system utility, structured trusted paths.
        [str(Path(os.environ["SystemRoot"]) / "System32/icacls.exe"), str(path), *arguments],
        capture_output=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("Sandbox permissions could not be established.")


def run(
    runtime: Path,
    work: Path,
    *,
    script: str = "worker.py",
    timeout: float = 15,
    memory_mb: int = 384,
):
    return _run(runtime, work, script=script, timeout=timeout, memory_mb=memory_mb)


def run_office(runtime: Path, work: Path, slide: int):
    """Trusted operator-installed LibreOffice only; no source-controlled commands.

    Uses the same capability-free AppContainer and one-process Job Object. This
    separate profile grants no additional access to the Python parser workers.
    """
    import shutil

    if type(slide) is not int or not 1 <= slide <= 200:
        raise ValueError("Invalid slide")
    interpreters = list((runtime / "program").glob("python-core-*/bin/python.exe"))
    if len(interpreters) != 1 or not (runtime / "program/mergedlo.dll").is_file():
        raise RuntimeError("LibreOffice renderer is unavailable.")
    worker = work / "slide_worker.py"
    shutil.copy2(Path(__file__).with_name("slide_worker.py"), worker)
    arguments = [str(interpreters[0]), "-I", "-S", str(worker), str(work), str(runtime), str(slide)]
    return _run(runtime, work, timeout=45, memory_mb=768, office_arguments=arguments)


def _run(
    runtime: Path,
    work: Path,
    *,
    script="worker.py",
    timeout=15,
    memory_mb=384,
    office_arguments=None,
):
    if os.name != "nt":
        raise RuntimeError("Windows AppContainer is unavailable.")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    userenv = C.WinDLL("userenv", use_last_error=True)
    advapi = C.WinDLL("advapi32", use_last_error=True)
    pointer, size = C.c_void_p, C.c_size_t

    class Startup(C.Structure):
        _fields_ = [
            ("cb", W.DWORD),
            ("reserved", W.LPWSTR),
            ("desktop", W.LPWSTR),
            ("title", W.LPWSTR),
            ("x", W.DWORD),
            ("y", W.DWORD),
            ("cx", W.DWORD),
            ("cy", W.DWORD),
            ("charsx", W.DWORD),
            ("charsy", W.DWORD),
            ("fill", W.DWORD),
            ("flags", W.DWORD),
            ("show", W.WORD),
            ("reserved2size", W.WORD),
            ("reserved2", pointer),
            ("stdin", W.HANDLE),
            ("stdout", W.HANDLE),
            ("stderr", W.HANDLE),
        ]

    class StartupEx(C.Structure):
        _fields_ = [("startup", Startup), ("attributes", pointer)]

    class Process(C.Structure):
        _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]

    class Capabilities(C.Structure):
        _fields_ = [
            ("sid", pointer),
            ("capabilities", pointer),
            ("count", W.DWORD),
            ("reserved", W.DWORD),
        ]

    class BasicLimit(C.Structure):
        _fields_ = [
            ("process_time", C.c_int64),
            ("job_time", C.c_int64),
            ("flags", W.DWORD),
            ("min_working", size),
            ("max_working", size),
            ("processes", W.DWORD),
            ("affinity", size),
            ("priority", W.DWORD),
            ("scheduling", W.DWORD),
        ]

    class IO(C.Structure):
        _fields_ = [
            (name, C.c_uint64)
            for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")
        ]

    class ExtendedLimit(C.Structure):
        _fields_ = [
            ("basic", BasicLimit),
            ("io", IO),
            ("process_memory", size),
            ("job_memory", size),
            ("peak_process", size),
            ("peak_job", size),
        ]

    declarations = [
        (
            userenv,
            "CreateAppContainerProfile",
            C.c_long,
            [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, pointer, W.DWORD, C.POINTER(pointer)],
        ),
        (userenv, "DeleteAppContainerProfile", C.c_long, [W.LPCWSTR]),
        (advapi, "ConvertSidToStringSidW", W.BOOL, [pointer, C.POINTER(W.LPWSTR)]),
        (advapi, "FreeSid", pointer, [pointer]),
        (kernel, "LocalFree", pointer, [pointer]),
        (
            kernel,
            "InitializeProcThreadAttributeList",
            W.BOOL,
            [pointer, W.DWORD, W.DWORD, C.POINTER(size)],
        ),
        (
            kernel,
            "UpdateProcThreadAttribute",
            W.BOOL,
            [pointer, W.DWORD, size, pointer, size, pointer, pointer],
        ),
        (kernel, "DeleteProcThreadAttributeList", None, [pointer]),
        (kernel, "CreateJobObjectW", W.HANDLE, [pointer, W.LPCWSTR]),
        (kernel, "SetInformationJobObject", W.BOOL, [W.HANDLE, C.c_int, pointer, W.DWORD]),
        (kernel, "AssignProcessToJobObject", W.BOOL, [W.HANDLE, W.HANDLE]),
        (
            kernel,
            "CreateProcessW",
            W.BOOL,
            [
                W.LPCWSTR,
                W.LPWSTR,
                pointer,
                pointer,
                W.BOOL,
                W.DWORD,
                pointer,
                W.LPCWSTR,
                C.POINTER(StartupEx),
                C.POINTER(Process),
            ],
        ),
        (kernel, "ResumeThread", W.DWORD, [W.HANDLE]),
        (kernel, "WaitForSingleObject", W.DWORD, [W.HANDLE, W.DWORD]),
        (kernel, "GetExitCodeProcess", W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
        (kernel, "TerminateProcess", W.BOOL, [W.HANDLE, W.UINT]),
        (kernel, "CloseHandle", W.BOOL, [W.HANDLE]),
    ]
    for dll, name, result, args in declarations:
        function = getattr(dll, name)
        function.restype, function.argtypes = result, args

    def checked(value):
        if not value:
            raise OSError(C.get_last_error(), "Sandbox operation failed.")
        return value

    profile = "CanvasBridge.Parser." + uuid4().hex
    sid, process, job, attributes = pointer(), Process(), None, None
    initialized, created_profile = False, False
    try:
        result = userenv.CreateAppContainerProfile(
            profile, "Canvas Bridge parser", "Isolated course file parser", None, 0, C.byref(sid)
        )
        if result < 0:
            raise RuntimeError("AppContainer creation failed.")
        created_profile = True
        sid_string = W.LPWSTR()
        checked(advapi.ConvertSidToStringSidW(sid, C.byref(sid_string)))
        try:
            acl(work, "/grant:r", f"*{sid_string.value}:(OI)(CI)(M)")
            acl(work, "/setintegritylevel", "(OI)(CI)L")
        finally:
            kernel.LocalFree(C.cast(sid_string, pointer))
        capabilities = Capabilities(sid, None, 0, 0)
        needed = size()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, C.byref(needed))
        attributes = C.create_string_buffer(needed.value)
        checked(kernel.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(needed)))
        initialized = True
        checked(
            kernel.UpdateProcThreadAttribute(
                attributes, 0, 0x00020009, C.byref(capabilities), C.sizeof(capabilities), None, None
            )
        )
        job = checked(kernel.CreateJobObjectW(None, None))
        limits = ExtendedLimit()
        # PROCESS_TIME, ACTIVE_PROCESS, PROCESS_MEMORY, KILL_ON_JOB_CLOSE,
        # DIE_ON_UNHANDLED_EXCEPTION. No breakaway is granted.
        limits.basic.flags = 0x2 | 0x8 | 0x100 | 0x2000 | 0x400
        limits.basic.process_time = (30 if office_arguments else 10) * 10_000_000
        limits.basic.processes = 1
        limits.process_memory = memory_mb * 1024 * 1024
        checked(kernel.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
        ui_limits = W.DWORD(0xFF)
        checked(kernel.SetInformationJobObject(job, 4, C.byref(ui_limits), C.sizeof(ui_limits)))
        startup = StartupEx()
        startup.startup.cb = C.sizeof(startup)
        startup.attributes = C.cast(attributes, pointer)
        executable = Path(office_arguments[0]) if office_arguments else runtime / "python.exe"
        command = C.create_unicode_buffer(
            subprocess.list2cmdline(
                office_arguments or [str(executable), "-I", "-S", str(runtime / script), str(work)]
            )
        )
        # Windows needs profile-location variables to construct the AppContainer
        # environment. They grant no file rights; the OS token still denies access.
        env = {
            key: os.environ[key]
            for key in (
                "SystemRoot",
                "SystemDrive",
                "WINDIR",
                "LOCALAPPDATA",
                "USERPROFILE",
                "APPDATA",
                "ProgramData",
            )
            if key in os.environ
        }
        env.update({"TEMP": str(work), "TMP": str(work)})
        if office_arguments:
            env["PATH"] = (
                str(runtime / "program") + os.pathsep + str(Path(env["SystemRoot"]) / "System32")
            )
        environment = C.create_unicode_buffer(
            "\0".join(f"{k}={v}" for k, v in sorted(env.items())) + "\0\0"
        )
        checked(
            kernel.CreateProcessW(
                str(executable),
                command,
                None,
                None,
                False,
                0x00080000 | 0x00000004 | 0x00000400 | 0x08000000,
                environment,
                str(work),
                C.byref(startup),
                C.byref(process),
            )
        )
        checked(kernel.AssignProcessToJobObject(job, process.process))
        if kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise RuntimeError("Sandbox could not resume.")
        deadline = time.monotonic() + timeout
        while True:
            waited = kernel.WaitForSingleObject(process.process, 200)
            if waited != 0x102:
                break
            if (
                office_arguments
                and sum(p.stat().st_size for p in work.rglob("*") if p.is_file()) > 50_000_000
            ):
                raise RuntimeError("Slide rendering exceeded temporary storage budget.")
            if time.monotonic() >= deadline:
                break
        if waited == 0x102:
            raise TimeoutError("Document extraction exceeded its time budget.")
        checked(waited != 0xFFFFFFFF)
        code = W.DWORD()
        checked(kernel.GetExitCodeProcess(process.process, C.byref(code)))
        if code.value:
            raise RuntimeError(f"Parser sandbox terminated ({code.value}).")
    finally:
        # Kill even a suspended process if job assignment/any later step failed.
        if process.process:
            kernel.TerminateProcess(process.process, 1)
            kernel.WaitForSingleObject(process.process, 5000)
        for handle in (process.thread, process.process, job):
            if handle:
                kernel.CloseHandle(handle)
        if initialized:
            kernel.DeleteProcThreadAttributeList(attributes)
        if sid:
            advapi.FreeSid(sid)
        if created_profile:
            userenv.DeleteAppContainerProfile(profile)
