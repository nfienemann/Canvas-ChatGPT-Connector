"""Test installed packages from an unrelated directory without Python on PATH."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None, env=None):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, timeout=180, check=True)  # noqa: S603


def check(executable: Path, temporary: Path, *, ui=False):
    report = temporary / ("ui-report.json" if ui else "mcp-report.json")
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "BRIDGE_DATABASE_URL"):
        environment.pop(name, None)
    environment["PATH"] = (
        str(Path(os.environ["SystemRoot"]) / "System32")
        if sys.platform == "win32"
        else "/usr/bin:/bin"
    )
    # Freeze must not depend on the Python executable that built it.
    run(
        executable,
        "--ui-smoke-test" if ui else "--smoke-test",
        "--report",
        report,
        "--data-dir",
        temporary / "Student's démo data",
        cwd=temporary,
        env=environment,
    )
    result = json.loads(report.read_text(encoding="utf-8"))
    if ui:
        assert result["native_wizard"] == "passed", result
    else:
        assert result["bundled"] and result["tool_count"] == 14, result
        assert result["planning"] == "verified" and result["actual_chatgpt"] == "not_tested", result
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-only", action="store_true")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "dist/installers/package-verification.json"
    )
    args = parser.parse_args()
    results = {"platform": sys.platform, "signing": "unsigned_development_preview"}
    with tempfile.TemporaryDirectory(prefix="Canvas Bridge installation ") as directory:
        temporary = Path(directory)
        installed = temporary / "Application folder"
        cleanup = None
        key = temporary / "Student's démo data/vault.key"
        if sys.platform == "win32" and not args.bundle_only:
            import winreg

            try:
                existing = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{CC5239F2-80A3-4616-84EC-67C2A8AA384A}_is1",
                )
            except FileNotFoundError:
                pass
            else:
                existing.Close()
                raise RuntimeError(
                    "An existing user installation must not be replaced by a package test. Use --bundle-only."
                )
            installer = ROOT / "dist/installers/CanvasBridgeDemo-Windows-x64-Setup.exe"
            run(
                installer,
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOICONS",
                f"/DIR={installed}",
                cwd=temporary,
            )
            executable = installed / "CanvasBridgeDemo.exe"
            cleanup = installed / "unins000.exe"
            results["installer"] = "passed"
        elif sys.platform == "darwin" and not args.bundle_only:
            image = next((ROOT / "dist/installers").glob("*.dmg"))
            mount = temporary / "mounted"
            run("hdiutil", "attach", image, "-mountpoint", mount, "-nobrowse")
            try:
                app = installed / "Canvas Bridge Demo.app"
                shutil.copytree(mount / "Canvas Bridge Demo.app", app, symlinks=True)
            finally:
                run("hdiutil", "detach", mount)
            executable = app / "Contents/MacOS/CanvasBridgeDemo"
            results["disk_image_install"] = "passed"
        elif sys.platform == "linux" and not args.bundle_only:
            package = next((ROOT / "dist/installers").glob("*.deb"))
            run("sudo", "dpkg", "-i", package)
            executable = Path("/opt/canvas-bridge-demo/CanvasBridgeDemo")
            results["deb_install"] = "passed"
        elif sys.platform == "darwin":
            executable = ROOT / "dist/CanvasBridgeDemo.app/Contents/MacOS/CanvasBridgeDemo"
        else:
            executable = (
                ROOT
                / "dist/CanvasBridgeDemo"
                / ("CanvasBridgeDemo.exe" if sys.platform == "win32" else "CanvasBridgeDemo")
            )
        try:
            results["mcp"] = check(executable, temporary)
            before = key.read_bytes()
            if sys.platform == "win32" and not args.bundle_only:
                run(
                    installer,
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/NOICONS",
                    f"/DIR={installed}",
                    cwd=temporary,
                )
                results["in_place_upgrade"] = "passed"
            results["wizard"] = check(executable, temporary, ui=True)
            assert before == key.read_bytes()
            results["restart_preserves_keys"] = "passed"
        finally:
            if cleanup:
                run(cleanup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", cwd=temporary)
                assert not executable.exists()
                assert key.exists()
                results["uninstall_preserves_data"] = "passed"
            elif sys.platform == "linux" and not args.bundle_only:
                run("sudo", "dpkg", "-r", "canvas-bridge-demo")
                assert key.exists()
                results["uninstall_preserves_data"] = "passed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
