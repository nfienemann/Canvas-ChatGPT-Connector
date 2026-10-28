"""Optional trusted LibreOffice runtime packaging; Windows only, fail closed."""

import hashlib
import os
import shutil
from pathlib import Path

from canvas_bridge.domain import DomainError


def prepare(runtime: Path, office_root: Path) -> Path:
    if os.name != "nt":
        raise DomainError(
            "unsupported_feature",
            "The PPTX renderer has no verified sandbox on this platform.",
            reason_code="PPTX_RENDERER_UNAVAILABLE",
            processing_stage="slide_rendering",
        )
    office_root = office_root.resolve(strict=True)
    program = office_root / "program"
    required = [program / "soffice.bin", program / "mergedlo.dll", program / "version.ini"]
    if not all(p.is_file() and p.resolve().is_relative_to(office_root) for p in required):
        raise DomainError(
            "unsupported_feature",
            "A complete trusted PPTX renderer runtime is required.",
            reason_code="PPTX_RENDERER_UNAVAILABLE",
            processing_stage="runtime_setup",
        )
    digest = hashlib.sha256(b"canvas-bridge-public-office-v2-nested")
    for path in required:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    target = runtime.parent / ("office-runtime-" + digest.hexdigest()[:20])
    # LibreOffice validates its installation with FindFirstFileW, which needs
    # enumeration rights on the installation's parent. Keep that parent public
    # and dedicated; never grant enumeration of the private parser/cache root.
    payload = target / "install"
    if (target / "presentation-ready").is_file():
        return payload
    target.mkdir(exist_ok=True)
    payload.mkdir(exist_ok=True)
    for name in ("program", "share", "presets"):
        source = office_root / name
        if not source.is_dir():
            continue
        # Operator-owned public runtime only, never an existing user profile.
        if any(p.is_symlink() or p.is_junction() for p in source.rglob("*")):
            raise ValueError("Renderer runtime must not contain links")
        # Administrative Windows images include deep optional language/runtime
        # trees; use the native extended path spelling for public code copies.
        shutil.copytree(
            "\\\\?\\" + str(source), "\\\\?\\" + str(payload / name), dirs_exist_ok=True
        )
    from canvas_bridge.windows_sandbox import acl

    acl(Path("\\\\?\\" + str(target)), "/grant:r", "*S-1-15-2-1:(OI)(CI)(RX)", "/T", "/Q")
    (target / "presentation-ready").write_text(digest.hexdigest(), encoding="ascii")
    return payload
