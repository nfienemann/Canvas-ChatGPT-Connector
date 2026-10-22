"""Build on each target OS; never cross-compile or include operator files."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
NAME = "CanvasBridgeDemo"


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)  # noqa: S603


def icons():
    folder = ROOT / "build/icons"
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((32, 32, 992, 992), radius=224, fill="#174e49")
    pen.rounded_rectangle((224, 240, 800, 784), radius=65, fill="#f3f7f6")
    pen.rectangle((477, 240, 547, 784), fill="#174e49")
    pen.rounded_rectangle((288, 332, 412, 374), radius=18, fill="#174e49")
    pen.rounded_rectangle((612, 332, 736, 374), radius=18, fill="#174e49")
    pen.rounded_rectangle((288, 432, 412, 474), radius=18, fill="#174e49")
    pen.rounded_rectangle((612, 432, 736, 474), radius=18, fill="#174e49")
    image.save(folder / "canvas-bridge.png")
    image.save(folder / "canvas-bridge.ico", sizes=[(n, n) for n in (16, 32, 48, 64, 128, 256)])
    image.save(folder / "canvas-bridge.icns")
    return folder


def notices():
    folder = ROOT / "build/notices"
    folder.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        entry = {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License", "unspecified"),
        }
        inventory.append(entry)
        for file in dist.files or []:
            if ".dist-info" in str(file) and any(
                part.lower().startswith(("license", "copying", "notice")) for part in file.parts
            ):
                source = dist.locate_file(file)
                if source.is_file():
                    # Preserve vendored license paths; basename-only copies overwrite
                    # distinct LICENSE files within a single distribution.
                    relative = Path(*[part for part in file.parts if part not in {".", ".."}])
                    target = folder / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    (folder / "build-dependencies.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )
    shutil.copyfile(ROOT / "LICENSE-STATUS.md", folder / "PROJECT-LICENSE-STATUS.md")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, folder / "PYTHON-LICENSE.txt")
    else:
        shutil.copyfile(
            ROOT / "packaging/licenses/PYTHON-LICENSE.txt", folder / "PYTHON-LICENSE.txt"
        )
    shutil.copyfile(ROOT / "packaging/licenses/TCL-LICENSE.txt", folder / "TCL-LICENSE.txt")
    return folder


def build_bundle():
    icon_folder = icons()
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        NAME,
        "--specpath",
        "build",
        "--paths",
        "src",
        "--noupx",
        "--copy-metadata",
        "canvas-bridge",
        "--copy-metadata",
        "mcp",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "sqlalchemy.dialects.postgresql.psycopg",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
    ]
    # Explicit resources only. Never add the working directory, .env, .local or keys.
    args += ["--add-data", f"{ROOT / 'institutions.json'}:canvas_bridge/resources"]
    args += [
        "--add-data",
        f"{ROOT / 'src/canvas_bridge/assets/page-reader.js'}:canvas_bridge/assets",
    ]
    args += [
        "--add-data",
        f"{ROOT / 'src/canvas_bridge/assets/original-download.js'}:canvas_bridge/assets",
    ]
    args += [
        "--add-data",
        f"{ROOT / 'src/canvas_bridge/assets/page-reader-NOTICES.txt'}:canvas_bridge/assets",
    ]
    for file in sorted((ROOT / "migrations").rglob("*")):
        if file.is_file() and file.suffix in {".py", ".mako"} and "__pycache__" not in file.parts:
            destination = (
                Path("canvas_bridge/resources/migrations")
                / file.relative_to(ROOT / "migrations").parent
            )
            args += ["--add-data", f"{file}:{destination.as_posix()}"]
    args += ["--add-data", f"{notices()}:THIRD-PARTY-NOTICES"]
    if sys.platform == "win32":
        args += ["--icon", str(icon_folder / "canvas-bridge.ico")]
    elif sys.platform == "darwin":
        args += [
            "--icon",
            str(icon_folder / "canvas-bridge.icns"),
            "--osx-bundle-identifier",
            "org.canvasbridge.demo",
        ]
    args += [str(ROOT / "packaging/desktop_entry.py")]
    run(*args)


def package():
    output = ROOT / "dist/installers"
    output.mkdir(parents=True, exist_ok=True)
    architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    if sys.platform == "win32":
        candidates = [
            os.environ.get("ISCC", ""),
            shutil.which("iscc"),
            str(ROOT / ".tools/innosetup/ISCC.exe"),
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        ]
        compiler = next((p for p in candidates if p and Path(p).is_file()), None)
        if not compiler:
            raise RuntimeError("The build machine needs Inno Setup 6. End users do not.")
        run(
            compiler,
            f"/DSourceRoot={ROOT}",
            f"/DAppVersion={VERSION}",
            ROOT / "packaging/windows.iss",
        )
    elif sys.platform == "darwin":
        stage = ROOT / "build/dmg"
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            ROOT / f"dist/{NAME}.app",
            stage / "Canvas Bridge Demo.app",
            dirs_exist_ok=True,
            symlinks=True,
        )
        if not (stage / "Applications").exists():
            (stage / "Applications").symlink_to("/Applications")
        run(
            "hdiutil",
            "create",
            "-volname",
            "Canvas Bridge Demo",
            "-srcfolder",
            stage,
            "-ov",
            "-format",
            "UDZO",
            output / f"CanvasBridgeDemo-macOS-{architecture}.dmg",
        )
    else:
        stage = ROOT / "build/deb"
        app = stage / "opt/canvas-bridge-demo"
        shutil.copytree(ROOT / f"dist/{NAME}", app, dirs_exist_ok=True, symlinks=True)
        control = stage / "DEBIAN"
        control.mkdir(parents=True, exist_ok=True)
        (control / "control").write_text(
            f"Package: canvas-bridge-demo\nVersion: {VERSION}\nSection: education\nPriority: optional\nArchitecture: {'arm64' if architecture == 'arm64' else 'amd64'}\nMaintainer: Canvas Bridge project <345425861+nfienemann@users.noreply.github.com>\nDepends: libc6 (>= 2.35), libx11-6, libxext6, libxrender1, libfontconfig1, libfreetype6, libxft2\nDescription: Local Canvas Bridge demo with fictional courses\n Self-contained launcher; no Python or terminal setup required.\n",
            encoding="utf-8",
        )
        applications = stage / "usr/share/applications"
        applications.mkdir(parents=True, exist_ok=True)
        (applications / "canvas-bridge-demo.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Canvas Bridge Demo\nComment=Explore fictional courses on this computer\nExec=/opt/canvas-bridge-demo/CanvasBridgeDemo\nIcon=canvas-bridge-demo\nTerminal=false\nCategories=Education;\nStartupNotify=true\n",
            encoding="utf-8",
        )
        icon = stage / "usr/share/icons/hicolor/256x256/apps"
        icon.mkdir(parents=True, exist_ok=True)
        with Image.open(ROOT / "build/icons/canvas-bridge.png") as image:
            image.resize((256, 256)).save(icon / "canvas-bridge-demo.png")
        run(
            "dpkg-deb",
            "--root-owner-group",
            "--build",
            stage,
            output / f"CanvasBridgeDemo-Linux-{architecture}.deb",
        )
        # Portable fallback for other glibc distributions: extract and double-click executable.
        shutil.make_archive(
            str(output / f"CanvasBridgeDemo-Linux-{architecture}"), "gztar", ROOT / "dist", NAME
        )
    files = sorted(p for p in output.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    hashes = []
    for file in files:
        with file.open("rb") as stream:
            hashes.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {file.name}\n")
    (output / "SHA256SUMS.txt").write_text("".join(hashes), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-only", action="store_true")
    arguments = parser.parse_args()
    if not arguments.package_only:
        build_bundle()
    package()
