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

from canvas_bridge.domain import DomainError


def presentation_disk_usage(work):
    """Bound traversal and reject links; the monitor never follows worker paths."""
    pending, count, total = [(work, 0)], 0, 0
    while pending:
        directory, depth = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if (
                    count > 2048
                    or depth > 16
                    or entry.is_symlink()
                    or Path(entry.path).is_junction()
                ):
                    raise DomainError(
                        "unsupported_feature",
                        "Slide rendering exceeded its workspace limit.",
                        reason_code="SLIDE_RENDER_RESOURCE_LIMIT",
                        processing_stage="slide_rendering",
                        details={
                            "budget": "workspace_entries",
                            "observed": count,
                            "limit": 2048,
                            "retryable": False,
                        },
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append((entry.path, depth + 1))
                else:
                    try:
                        total += entry.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        pass  # native renderer may remove its own temporary file
                if total > 128 * 1024 * 1024:
                    raise DomainError(
                        "unsupported_feature",
                        "Slide rendering exceeded its staging-byte limit.",
                        reason_code="SLIDE_RENDER_RESOURCE_LIMIT",
                        processing_stage="slide_rendering",
                        details={
                            "budget": "staging_bytes",
                            "observed": total,
                            "limit": 128 * 1024 * 1024,
                            "retryable": False,
                        },
                    )
    return total


def acl(path: Path, *arguments: str):
    result = subprocess.run(  # noqa: S603 - fixed system utility, structured trusted paths.
        [str(Path(os.environ["SystemRoot"]) / "System32/icacls.exe"), str(path), *arguments],
        capture_output=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise DomainError(
            "retry_later",
            "Sandbox permissions could not be established.",
            reason_code="DOCUMENT_SANDBOX_SETUP_FAILED",
            processing_stage="sandbox_setup",
        )


def run(
    runtime: Path,
    work: Path,
    *,
    script: str = "worker.py",
    timeout: float = 15,
    memory_mb: int = 384,
    presentation: bool = False,
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
        (
            kernel,
            "QueryInformationJobObject",
            W.BOOL,
            [W.HANDLE, C.c_int, pointer, W.DWORD, pointer],
        ),
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

    stage = "sandbox_setup"

    def failure(message, reason):
        return DomainError("retry_later", message, reason_code=reason, processing_stage=stage)

    def checked(value):
        if not value:
            raise failure(
                "The isolated document worker could not complete an OS operation.",
                "DOCUMENT_WORKER_START_FAILED"
                if stage == "worker_start"
                else "DOCUMENT_SANDBOX_SETUP_FAILED"
                if stage == "sandbox_setup"
                else "DOCUMENT_WORKER_FAILED",
            )
        return value

    from canvas_bridge.worker_storage import profile_name

    profile = profile_name(work)
    sid, process, job, attributes = pointer(), Process(), None, None
    initialized, created_profile = False, False
    try:
        result = userenv.CreateAppContainerProfile(
            profile, "Canvas Bridge parser", "Isolated course file parser", None, 0, C.byref(sid)
        )
        if result < 0:
            raise failure("AppContainer creation failed.", "DOCUMENT_SANDBOX_SETUP_FAILED")
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
        limits.basic.process_time = 10 * 10_000_000
        limits.basic.processes = 1
        limits.process_memory = memory_mb * 1024 * 1024
        if presentation:
            # Preflight and the fixed Kit child share this non-breakaway Job and
            # AppContainer. Separate processes avoid retaining parser memory in Kit.
            if script != "presentation_render_worker.py":
                raise ValueError("Invalid presentation worker")
            limits.basic.flags |= 0x4 | 0x200  # aggregate CPU and committed memory
            limits.basic.job_time = 20 * 10_000_000
            limits.basic.processes = 2
            limits.job_memory = 512 * 1024 * 1024
        checked(kernel.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
        ui_limits = W.DWORD(0xFF)
        checked(kernel.SetInformationJobObject(job, 4, C.byref(ui_limits), C.sizeof(ui_limits)))
        startup = StartupEx()
        startup.startup.cb = C.sizeof(startup)
        startup.attributes = C.cast(attributes, pointer)
        executable = runtime / "python.exe"
        command = C.create_unicode_buffer(
            subprocess.list2cmdline([str(executable), "-I", "-S", str(runtime / script), str(work)])
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
        environment = C.create_unicode_buffer(
            "\0".join(f"{k}={v}" for k, v in sorted(env.items())) + "\0\0"
        )
        stage = "worker_start"
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
            raise failure("Sandbox could not resume.", "DOCUMENT_WORKER_START_FAILED")
        stage = "worker_execution"
        deadline = time.monotonic() + timeout
        while True:
            from canvas_bridge.worker_storage import require_running

            require_running()
            waited = kernel.WaitForSingleObject(process.process, 100)
            if presentation:
                presentation_disk_usage(work)
            if waited != 0x102 or time.monotonic() >= deadline:
                break
        if waited == 0x102:
            raise TimeoutError("Document extraction exceeded its time budget.")
        checked(waited != 0xFFFFFFFF)
        code = W.DWORD()
        checked(kernel.GetExitCodeProcess(process.process, C.byref(code)))
        if code.value:
            if presentation and code.value == 124:
                raise DomainError(
                    "retry_later",
                    "The isolated presentation converter exceeded its deadline.",
                    reason_code="PPTX_CONVERSION_TIMEOUT",
                    processing_stage="pptx_conversion",
                    details={"retryable": True, "limit_seconds": 60},
                )
            # Only numeric OS status is exposed, never stderr or document text.
            reason = {
                0xC0000017: "DOCUMENT_WORKER_MEMORY_LIMIT",
                0xC000012D: "DOCUMENT_WORKER_MEMORY_LIMIT",
                0xC0000135: "DOCUMENT_WORKER_DEPENDENCY_UNAVAILABLE",
                0xC000007B: "DOCUMENT_WORKER_DEPENDENCY_UNAVAILABLE",
            }.get(code.value, "DOCUMENT_WORKER_EXITED")
            raise DomainError(
                "retry_later",
                "The isolated document worker exited without a complete result.",
                reason_code=reason,
                processing_stage=stage,
                worker_exit_code=code.value,
            )
        observed = ExtendedLimit()
        if kernel.QueryInformationJobObject(job, 9, C.byref(observed), C.sizeof(observed), None):
            # Peak committed process memory, not RSS. Never collect document,
            # command-line, environment, path or credential data for telemetry.
            return {
                "worker_peak_committed_bytes": int(observed.peak_process),
                "worker_peak_job_committed_bytes": int(observed.peak_job),
            }
        return {}
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
