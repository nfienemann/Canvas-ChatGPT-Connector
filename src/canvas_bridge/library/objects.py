"""Chunk-authenticated private local store. Callers never choose filesystem paths."""

import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from canvas_bridge.library.contracts import CHUNK, fail


class LibraryObjectStore(Protocol):
    def put_chunk(self, owner: str, key: str, offset: int, data: bytes) -> None: ...
    def publish(self, owner: str, key: str, size: int, digest: str) -> None: ...
    def read(self, owner: str, key: str, size: int, digest: str, *, published=True): ...
    def delete(self, owner: str, key: str) -> None: ...
    def inventory(self): ...
    def reconcile(self, known, now): ...
    def sealed_parts(self, owner, key): ...
    def restore_part(self, owner, key, part, raw): ...


class EncryptedDirectory:
    def __init__(self, root: Path, key: bytes, *, synthetic=False, create=True):
        root = root.absolute()
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in [root, *root.parents]
        ):
            fail("STORAGE_UNAVAILABLE", "retry_later")
        if not synthetic:
            # Durable originals must not accidentally inherit a repository/cloud-sync policy.
            folded = {part.casefold() for part in root.parts}
            if (
                any(part.startswith("onedrive") for part in folded)
                or folded
                & {
                    "onedrive",
                    "dropbox",
                    "public",
                    "wwwroot",
                    "static",
                    "google drive",
                }
                or root.is_relative_to(Path.cwd().resolve())
            ):
                fail("STORAGE_UNAVAILABLE", "retry_later")
        if not create:
            if not root.is_dir():
                fail("STORAGE_UNAVAILABLE", "retry_later")
            self.root, self.cipher = root, AESGCM(key)
            self.lock = threading.RLock()
            return
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "nt":
            import subprocess

            from canvas_bridge.windows_sandbox import acl

            who = subprocess.run(  # noqa: S603 - fixed OS utility; no caller arguments.
                [
                    str(Path(os.environ["SystemRoot"]) / "System32/whoami.exe"),
                    "/user",
                    "/fo",
                    "csv",
                    "/nh",
                ],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            match = re.search(rb"S-1-[0-9-]+", who.stdout)
            if who.returncode or not match:
                fail("STORAGE_UNAVAILABLE", "retry_later")
            acl(
                root,
                "/inheritance:r",
                "/grant:r",
                f"*{match[0].decode()}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            )
        else:
            root.chmod(0o700)
        self.root, self.cipher = root, AESGCM(key)
        self.lock = threading.RLock()

    def directory(self, owner, key, *, create=False):
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            fail("RESOURCE_UNAVAILABLE")
        owner_key = hashlib.sha256(owner.encode()).hexdigest()
        path = self.root / owner_key / key
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in [self.root, path.parent, path]
        ):
            fail("STORAGE_UNAVAILABLE", "retry_later")
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def seal(self, owner, key, part, data):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, data, f"library-1:{owner}:{key}:{part}".encode())

    def open(self, owner, key, part, data):
        try:
            return self.cipher.decrypt(
                data[:12], data[12:], f"library-1:{owner}:{key}:{part}".encode()
            )
        except Exception:
            fail("CHECKSUM_MISMATCH")

    def put_chunk(self, owner, key, offset, data):
        if offset < 0 or offset % CHUNK or not 0 < len(data) <= CHUNK:
            fail("SOURCE_CHANGED", "source_changed")
        directory = self.directory(owner, key, create=True)
        part = str(offset // CHUNK)
        target = directory / part
        if target.exists():
            if self.open(owner, key, part, target.read_bytes()) != data:
                fail("CHECKSUM_MISMATCH", "source_changed")
            return
        raw = self.seal(owner, key, part, data)
        # DB owner lock serializes mutations; replace recovers a partial disk write.
        temporary = directory / (part + ".pending")
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def read(self, owner, key, size, digest, *, published=True):
        directory = self.directory(owner, key)
        try:
            if published:
                manifest = json.loads(
                    self.open(owner, key, "manifest", (directory / "manifest").read_bytes())
                )
                if manifest != {"size": size, "sha256": digest}:
                    fail("CHECKSUM_MISMATCH")
            sha, count = hashlib.sha256(), 0
            for offset in range(0, size, CHUNK):
                part = str(offset // CHUNK)
                data = self.open(owner, key, part, (directory / part).read_bytes())
                if len(data) != min(CHUNK, size - offset):
                    fail("CHECKSUM_MISMATCH")
                count += len(data)
                sha.update(data)
                yield data
            if count != size or (digest and sha.hexdigest() != digest):
                fail("CHECKSUM_MISMATCH")
        except OSError:
            fail("STORAGE_UNAVAILABLE", "retry_later", retryable=True)

    def publish(self, owner, key, size, digest):
        for _ in self.read(owner, key, size, digest, published=False):
            pass
        directory = self.directory(owner, key)
        data = self.seal(
            owner, key, "manifest", json.dumps({"size": size, "sha256": digest}).encode()
        )
        with (directory / "manifest.pending").open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(directory / "manifest.pending", directory / "manifest")

    def delete(self, owner, key):
        path = self.directory(owner, key)
        if path.exists():
            shutil.rmtree(path)  # server-validated immediate child of private owner directory

    def sealed_parts(self, owner, key):
        for path in sorted(self.directory(owner, key).iterdir()):
            if path.name != "manifest" and not path.name.isdigit():
                continue
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                fail("STORAGE_UNAVAILABLE", "retry_later")
            yield path.name, path.read_bytes()

    def restore_part(self, owner, key, part, raw):
        if (part != "manifest" and (not re.fullmatch(r"\d{1,2}", part) or int(part) > 12)) or len(
            raw
        ) > CHUNK + 1024:
            fail("RESTORE_ON_HOLD")
        target = self.directory(owner, key, create=True) / part
        # Exclusive creation refuses both existing data and file-level symlinks.
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def inventory(self):
        for owner in self.root.iterdir():
            if owner.is_symlink() or not owner.is_dir():
                continue
            for obj in owner.iterdir():
                if obj.is_dir() and not obj.is_symlink():
                    yield owner.name, obj.name, obj.stat().st_mtime

    def reconcile(self, known, now):
        removed = 0
        for owner_digest, key, modified in self.inventory():
            if (owner_digest, key) in known or modified > now - 86400:
                continue
            if not re.fullmatch(r"[a-f0-9]{64}", owner_digest) or not re.fullmatch(
                r"[a-f0-9]{32}", key
            ):
                continue
            target = self.root / owner_digest / key
            if target.resolve().parent.parent != self.root.resolve() or any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in (target, target.parent)
            ):
                fail("STORAGE_UNAVAILABLE", "retry_later")
            shutil.rmtree(target)
            removed += 1
        return removed
