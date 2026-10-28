"""Private job leases, cancellation and conservative orphan recovery."""

import hashlib
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from canvas_bridge.domain import DomainError
from canvas_bridge.retention_policy import FENCE_LIFETIME, ORPHAN_SECONDS

scope = ContextVar("processing_owner", default=None)
cancellation = ContextVar("processing_cancellation", default=None)
active = {}
versions = {}
guard = threading.RLock()


@contextmanager
def processing(owner, connection, *, namespace=None):
    key = (namespace, owner, connection)
    with guard:
        version = versions.get(key, (0, 0))[0]
    token = scope.set((key, version))
    try:
        yield
    finally:
        scope.reset(token)


def invalidate(owner, connection, *, namespace=None):
    key = (namespace, owner, connection)
    with guard:
        versions[key] = (versions.get(key, (0, 0))[0] + 1, time.monotonic())
        for recorded, event in active.values():
            if recorded and recorded[0] == key:
                event.set()


def pending(owner, connection, *, namespace=None):
    with guard:
        return sum(
            1
            for recorded, _ in active.values()
            if recorded and recorded[0] == (namespace, owner, connection)
        )


def require_running():
    event = cancellation.get()
    if event and event.is_set():
        raise DomainError("permission_denied", "Document processing was cancelled.")


@contextmanager
def lock_file(path):
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def remove_workspace(path, root):
    # Resolve and validate every deletion, including Windows junctions. Never
    # follow a worker-created link or recursively delete outside the job root.
    if path.is_symlink() or path.is_junction() or not path.resolve().parent.samefile(root):
        return False
    for directory, folders, files in os.walk(path, followlinks=False):
        if any(
            (Path(directory) / name).is_symlink() or (Path(directory) / name).is_junction()
            for name in folders + files
        ):
            return False
    if not cleanup_profile(path):
        return False
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def profile_name(work):
    return (
        "CanvasBridge.Parser." + hashlib.sha256(str(Path(work).resolve()).encode()).hexdigest()[:32]
    )


def cleanup_profile(work):
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("userenv", use_last_error=True).DeleteAppContainerProfile
    api.argtypes, api.restype = [wintypes.LPCWSTR], ctypes.c_long
    status = api(profile_name(work)) & 0xFFFFFFFF
    return status in {0, 0x80070002}  # Success or profile already absent.


@contextmanager
def job_directory(jobs):
    work = Path(tempfile.mkdtemp(prefix="document-", dir=jobs))
    recorded, event = scope.get(), threading.Event()
    token = cancellation.set(event)
    try:
        # Resolve Windows AppData redirection before opening a lease handle.
        # Accept directory aliases only when their OS directory identity matches.
        resolved = work.resolve()
        if not resolved.parent.samefile(jobs):
            raise DomainError(
                "retry_later",
                "The document workspace is outside its private root.",
                reason_code="DOCUMENT_WORKSPACE_INVALID",
                processing_stage="job_setup",
            )
        work = resolved
        with lock_file(work / ".lease"):
            with guard:
                if recorded and recorded[1] != versions.get(recorded[0], (0, 0))[0]:
                    event.set()
                active[str(work)] = (recorded, event)
            require_running()
            yield str(work)
            require_running()
    finally:
        cancellation.reset(token)
        if remove_workspace(work, jobs):
            with guard:
                active.pop(str(work), None)
        else:
            event.set()  # Keep a pending receipt until a later sweep removes it.
            with guard:
                active[str(work)] = (recorded, event)


def sweep_orphans(root, *, now=None):
    now = time.time() if now is None else now
    jobs = Path(root) / "jobs"
    removed = pending_count = 0
    if not jobs.is_dir() or jobs.is_symlink() or jobs.is_junction():
        return {"removed": 0, "pending": 0}
    for path in jobs.glob("document-*"):
        if not path.is_dir() or path.is_symlink() or path.is_junction():
            continue
        lease = path / ".lease"
        if lease.is_symlink() or lease.is_junction():
            pending_count += 1
            continue
        try:
            age = now - (lease.stat().st_mtime if lease.exists() else path.stat().st_mtime)
        except FileNotFoundError:
            continue  # Another worker completed between directory enumeration and stat.
        if 0 <= age < ORPHAN_SECONDS:
            continue
        try:
            with lock_file(lease):
                pass
            if remove_workspace(path, jobs):
                removed += 1
                with guard:
                    active.pop(str(path), None)
            else:
                pending_count += 1
        except OSError:
            pending_count += 1  # Active OS lease or cleanup failure; never claim erasure.
    with guard:
        for key, (_, created) in list(versions.items()):
            if time.monotonic() - created > FENCE_LIFETIME.total_seconds() and not any(
                r and r[0] == key for r, _ in active.values()
            ):
                del versions[key]
    return {"removed": removed, "pending": pending_count}
