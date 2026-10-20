"""Standalone trusted bootstrap. Never read document bytes before both OS gates.

Executed with isolated Python (-I -S), no service environment or inherited handles.
Only public parser code and the current job are readable after Landlock. Seccomp
denies everything except the small set needed for in-process text extraction.
"""

import ctypes as C
import errno
import os
import resource
import signal
import sys
from pathlib import Path

# No socket, connect, execve, clone, fork, ptrace, process_vm_*, io_uring,
# mount, chmod, chown, link, symlink, kill or privilege-changing calls.
SYSCALLS = (
    "read",
    "write",
    "readv",
    "writev",
    "close",
    "close_range",
    "fstat",
    "newfstatat",
    "statx",
    "stat",
    "lstat",
    "lseek",
    "pread64",
    "getdents64",
    "open",
    "openat",
    "readlink",
    "readlinkat",
    "access",
    "faccessat",
    "faccessat2",
    "fcntl",
    "dup",
    "dup2",
    "dup3",
    "mmap",
    "munmap",
    "mremap",
    "mprotect",
    "madvise",
    "brk",
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "sigaltstack",
    "clock_gettime",
    "clock_nanosleep",
    "nanosleep",
    "gettimeofday",
    "time",
    "poll",
    "ppoll",
    "select",
    "pselect6",
    "futex",
    "futex_waitv",
    "getpid",
    "getppid",
    "gettid",
    "getuid",
    "geteuid",
    "getgid",
    "getegid",
    "getrandom",
    "getcwd",
    "getrusage",
    "uname",
    "sysinfo",
    "sched_getaffinity",
    "exit",
    "exit_group",
)


class Beneath(C.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", C.c_uint64), ("parent_fd", C.c_int32)]


def check(value):
    if value < 0:
        raise RuntimeError("Kernel isolation failed.")
    return value


def install(runtime, work):
    libc = C.CDLL(None, use_errno=True)
    libc.syscall.restype = C.c_long
    sec = C.CDLL("libseccomp.so.2", use_errno=True)
    sec.seccomp_syscall_resolve_name.argtypes = [C.c_char_p]
    sec.seccomp_syscall_resolve_name.restype = C.c_int
    sec.seccomp_init.argtypes = [C.c_uint32]
    sec.seccomp_init.restype = C.c_void_p
    sec.seccomp_rule_add.argtypes = [C.c_void_p, C.c_uint32, C.c_int, C.c_uint]
    sec.seccomp_load.argtypes = [C.c_void_p]
    sec.seccomp_release.argtypes = [C.c_void_p]
    # Landlock applies to the calling thread. Reject a runtime with pre-existing
    # library threads before any untrusted input; seccomp then forbids new ones.
    if len(list(Path("/proc/self/task").iterdir())) != 1:
        raise RuntimeError("Single-threaded bootstrap required.")
    create, add, restrict = [
        check(sec.seccomp_syscall_resolve_name(name.encode()))
        for name in ("landlock_create_ruleset", "landlock_add_rule", "landlock_restrict_self")
    ]
    abi = check(libc.syscall(create, C.c_void_p(), C.c_size_t(0), C.c_uint(1)))
    if abi < 3:
        raise RuntimeError("Landlock ABI 3 is required, including truncate protection.")
    # Handle every filesystem access through ABI 3, denying all except the
    # leaf grants below. Newer network/device operations are denied by seccomp.
    handled = C.c_uint64((1 << 15) - 1)
    rules = check(libc.syscall(create, C.byref(handled), C.c_size_t(8), C.c_uint(0)))
    read = (1 << 2) | (1 << 3)
    write = (1 << 1) | (1 << 8) | (1 << 14)  # write file, create regular file, truncate
    try:
        for path, rights in ((runtime, read), (work, read | write)):
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Beneath(rights, fd)
                check(libc.syscall(add, C.c_int(rules), C.c_int(1), C.byref(rule), C.c_uint(0)))
            finally:
                os.close(fd)
        check(libc.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
        check(libc.syscall(restrict, C.c_int(rules), C.c_uint(0)))
    finally:
        os.close(rules)
    context = sec.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("Seccomp initialization failed.")
    try:
        for name in SYSCALLS:
            number = sec.seccomp_syscall_resolve_name(name.encode())
            if number >= 0:
                check(sec.seccomp_rule_add(context, 0x7FFF0000, number, 0))
        check(sec.seccomp_load(context))
    finally:
        sec.seccomp_release(context)


def main():
    runtime = Path(sys.argv[1]).resolve()
    work = Path(sys.argv[2]).resolve()
    script, parent = sys.argv[3], int(sys.argv[4])
    try:
        libc = C.CDLL(None, use_errno=True)
        check(libc.prctl(1, signal.SIGKILL, 0, 0, 0))  # PR_SET_PDEATHSIG
        if os.getppid() != parent:
            raise RuntimeError("Launcher exited before isolation.")
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2_000_000,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        # Preload trusted standard-library native dependencies while host library
        # resolution is available. Keep handles alive; no host library tree is
        # granted to the document process. Failed optional modules stay unavailable.
        libraries = []
        for path in sorted((runtime / "dynload").glob("*.so")):
            try:
                libraries.append(C.CDLL(str(path)))
            except OSError:
                pass
        original_stdlib = str(Path(os.__file__).parent)
        archive = str(runtime / "stdlib.zip")
        for module in tuple(sys.modules.values()):
            paths = getattr(module, "__path__", None)
            if paths:
                module.__path__ = [
                    archive + p[len(original_stdlib) :]
                    if p.startswith(original_stdlib + "/")
                    else p
                    for p in paths
                ]
        sys.path[:] = [archive, str(runtime / "dynload"), str(runtime / "site"), str(runtime)]
        sys.dont_write_bytecode = True
        os.chdir(work)
        install(runtime, work)
    except Exception:
        # No raw error, paths, document data or service environment are emitted.
        return 77
    sys.argv[:] = [str(runtime / script), str(work)]
    code = compile((runtime / script).read_bytes(), str(runtime / script), "exec")
    exec(code, {"__name__": "__main__", "__file__": str(runtime / script)})  # noqa: S102 - fixed trusted runtime script, after OS restrictions.
    return 0


if __name__ == "__main__":
    sys.exit(main())
