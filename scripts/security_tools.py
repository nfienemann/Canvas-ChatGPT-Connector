"""Run pinned upstream scanners after verifying their release archive SHA-256.

Operator/CI tooling only; never imported by the service or exposed over MCP.
Archive members are read by exact name, never extracted as paths.
"""

import argparse
import hashlib
import io
import platform
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RELEASES = {
    ("gitleaks", "Linux"): (
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    ),
    ("gitleaks", "Windows"): (
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_windows_x64.zip",
        "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
    ),
    ("trivy", "Linux"): (
        "https://github.com/aquasecurity/trivy/releases/download/v0.76.1/trivy_0.76.1_Linux-64bit.tar.gz",
        "c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0",
    ),
}


def checked_binary(data, digest, name, *, zipped=False):
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Scanner archive checksum mismatch; refusing execution.")
    if zipped:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read(name)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        entry = archive.getmember(name)
        if not entry.isfile() or entry.size > 300_000_000:
            raise ValueError("Invalid scanner archive member.")
        return archive.extractfile(entry).read()


def install(name):
    system = platform.system()
    if platform.machine().lower() not in {"amd64", "x86_64"} or (name, system) not in RELEASES:
        raise ValueError("Scanner platform unavailable; run the Linux CI gate.")
    url, digest = RELEASES[name, system]
    root = Path(".tools/security")
    root.mkdir(parents=True, exist_ok=True)
    archive = root / (digest + ".archive")
    if not archive.exists():
        # Fixed public release URL, standard certificate verification, no credentials.
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            data = response.read(150_000_001)
        if len(data) > 150_000_000:
            raise ValueError("Scanner archive exceeds size limit.")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Scanner archive checksum mismatch.")
        archive.write_bytes(data)
    binary_name = name + (".exe" if system == "Windows" else "")
    binary = checked_binary(archive.read_bytes(), digest, binary_name, zipped=system == "Windows")
    target = root / binary_name
    # Replace from the validated archive each invocation, even if a cache was tampered with.
    target.write_bytes(binary)
    target.chmod(0o700)
    return target.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=("gitleaks", "trivy"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    executable = install(args.tool)
    raise SystemExit(subprocess.run([str(executable), *args.arguments], check=False).returncode)  # noqa: S603


if __name__ == "__main__":
    main()
