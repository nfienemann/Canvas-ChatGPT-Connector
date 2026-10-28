"""A bundled, loopback-only demo. Student use of a hosted release needs no app."""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from sqlalchemy import URL

from canvas_bridge.app import create_app
from canvas_bridge.cli import initialize_demo, verify_read
from canvas_bridge.config import Settings
from canvas_bridge.resources import resource_root


class DemoSettings(Settings):
    """Never inherit operator configuration or secrets from the launching shell."""

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, **kwargs):
        return (init_settings,)


def default_data_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        value = os.environ.get("XDG_DATA_HOME", "")
        base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".local/share"
    return base / "Canvas Bridge Demo"


def remembered_directory(edition="synthetic") -> Path:
    default = default_data_directory()
    if edition == "offline":
        default = default.with_name("Canvas Bridge Offline")
    location = default.parent / "Canvas Bridge Launcher" / "preferences.json"
    try:
        if location.stat().st_size > 8192:
            return default
        value = Path(
            json.loads(location.read_text(encoding="utf-8"))[
                "offline_directory" if edition == "offline" else "data_directory"
            ]
        )
        return value if value.is_absolute() else default
    except (OSError, ValueError, KeyError, TypeError):
        return default


def remember_directory(folder: Path, edition="synthetic"):
    location = default_data_directory().parent / "Canvas Bridge Launcher"
    location.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = location / "preferences.tmp"
    values = {}
    for mode, key in (("offline", "offline_directory"), ("synthetic", "data_directory")):
        values[key] = str(folder.resolve() if mode == edition else remembered_directory(mode))
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(location / "preferences.json")


class AlreadyRunning(RuntimeError):
    pass


class ProfileLock:
    """OS lock, released even after a crash. Keep the inode stable across exits."""

    def __init__(self, folder: Path):
        self.file = (folder / "launcher.lock").open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                self.file.seek(0, 2)
                if not self.file.tell():
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise AlreadyRunning(
                "This demo is already open. Switch to its existing window."
            ) from exc

    def close(self):
        self.file.close()


class DemoRuntime:
    def __init__(self, folder: Path, preferred_port: int = 8765):
        self.folder = folder.expanduser().absolute()
        self.preferred_port = preferred_port
        self.lock = None
        self.socket = None
        self.server = None
        self.thread = None
        self.settings = None
        self.failure = None
        self.app = None

    def start(self):
        from canvas_bridge.desktop_profiles import prepare_profile

        prepare_profile(self.folder, "synthetic")
        if self.lock:
            raise AlreadyRunning("This demo is already running.")
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = ProfileLock(self.folder)
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform == "win32":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                self.socket.bind(("127.0.0.1", self.preferred_port))
            except OSError:
                self.socket.bind(("127.0.0.1", 0))
            self.socket.listen(128)
            port = self.socket.getsockname()[1]
            self.settings = DemoSettings(
                database_url=URL.create(
                    "sqlite", database=str(self.folder / "bridge.db")
                ).render_as_string(),
                institutions_file=resource_root() / "institutions.json",
                local_jwks_file=self.folder / "jwks.json",
                vault_key_file=self.folder / "vault.key",
                deletion_journal=self.folder / "deletions.jsonl",
                resource_url=f"http://127.0.0.1:{port}",
                port=port,
            )
            initialize_demo(self.settings, self.folder, verbose=False)
            self.app = create_app(self.settings)
            self.server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host="127.0.0.1",
                    port=port,
                    access_log=False,
                    server_header=False,
                    proxy_headers=False,
                    log_config=None,
                    log_level="error",
                    timeout_graceful_shutdown=3,
                    loop="asyncio",
                    http="h11",
                    ws="none",
                )
            )

            def serve():
                try:
                    asyncio.run(self.server.serve(sockets=[self.socket]))
                except BaseException as exc:
                    self.failure = type(exc).__name__

            self.thread = threading.Thread(target=serve, name="canvas-demo", daemon=True)
            self.thread.start()
            deadline = time.monotonic() + 30
            while not self.server.started:
                if not self.thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError(
                        "The local service could not start. Close the demo and try again."
                    )
                time.sleep(0.05)
        except BaseException:
            self.stop()
            raise

    @property
    def url(self):
        return self.settings.resource_url + "/settings"

    def check(self) -> dict:
        from sqlalchemy import select

        from canvas_bridge.onboarding import SetupError
        from canvas_bridge.storage import Connection

        with self.app.state.bridge.store.transaction() as session:
            if not session.scalar(select(Connection.id).where(Connection.state == "active")):
                raise SetupError(
                    "DEMO_ACCESS_DISABLED",
                    "This demo has no active fictional connection. Updates preserve disabled/deleted access. Choose a new empty demo folder to explicitly start a new demonstration.",
                )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            asyncio.run(verify_read(self.settings))
        return json.loads(output.getvalue())

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                self.server.force_exit = True
                self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError(
                    "The demo is still finishing a request. Please try closing again."
                )
        if self.app:
            self.app.state.bridge.store.close()
            self.app = None
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.lock:
            self.lock.close()
            self.lock = None


def friendly_error(error: Exception) -> str:
    from canvas_bridge.onboarding import SetupError

    if isinstance(error, SetupError):
        return f"{error.code}: {error}"
    if isinstance(error, AlreadyRunning):
        return str(error)
    if isinstance(error, PermissionError):
        return "This folder cannot be used. Choose a folder in your user account and try again."
    return (
        "The application could not finish this step. "
        "Close other copies, then try again. If it still fails, report error type "
        f"{type(error).__name__} to the project owner. Do not attach your data folder."
    )


class SetupWindow:
    def __new__(cls, root, folder, *, remember=True, edition="offline"):
        from canvas_bridge.desktop_wizard import SetupWizard

        return SetupWizard(root, folder, remember=remember, edition=edition)


def smoke_test(folder: Path) -> dict:
    runtime = DemoRuntime(folder, preferred_port=0)
    try:
        runtime.start()
        result = runtime.check()
        result["bundled"] = bool(getattr(sys, "frozen", False))
        result["platform"] = sys.platform
        return result
    finally:
        runtime.stop()


def ui_smoke_test(folder: Path, edition="synthetic") -> dict:
    """Exercise native widgets and the bundled runtime without opening a browser."""
    import tkinter as tk

    root = tk.Tk()
    window = SetupWindow(root, folder, remember=False, edition=edition)
    screens = []

    def assert_layout(stage):
        root.update_idletasks()
        for widget in (
            window.title,
            window.body,
            window.detail,
            window.extra,
            window.status,
            window.buttons,
        ):
            assert (
                widget.winfo_rooty() + widget.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            ), stage + " exceeds window height"
            assert (
                widget.winfo_rootx() + widget.winfo_width()
                <= root.winfo_rootx() + root.winfo_width()
            ), stage + " exceeds window width"
        screens.append(stage)

    try:
        assert_layout("welcome")
        window.mode.set("institutional")
        window.primary.invoke()
        assert "not established" in window.status.cget("text")
        assert_layout("institutional_unconnected")
        window.primary.invoke()
        window.mode.set(edition)
        window.primary.invoke()
        assert window.stage == "setup"
        assert_layout("setup")
        window.primary.invoke()
        assert not window.busy and window.runtime is None
        window.consent.set(True)
        window.primary.invoke()
        deadline = time.monotonic() + 60
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert window.stage == "ready", window.status.cget("text")
        assert_layout("ready")
        window.check_button.invoke()
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert window.status.cget("text").startswith("Check passed"), window.status.cget("text")
        return {
            "native_wizard": "passed",
            "platform": sys.platform,
            "edition": edition,
            "widget_bounds": screens,
            "checks": window.result,
        }
    finally:
        if window.runtime:
            window.runtime.stop()
        root.destroy()


def main():
    logging.disable(logging.INFO)
    parser = argparse.ArgumentParser(description="Canvas Bridge local demo")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--edition", choices=["offline", "synthetic"], default="offline")
    parser.add_argument("--uninstall-data", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--ui-smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.uninstall_data:
        from canvas_bridge.desktop_wizard import uninstall_data_window

        uninstall_data_window()
        return
    if args.smoke_test or args.ui_smoke_test:
        with tempfile.TemporaryDirectory(prefix="Canvas Bridge test ") as temporary:
            try:
                run = ui_smoke_test if args.ui_smoke_test else smoke_test
                result = (
                    run(args.data_dir or Path(temporary), edition=args.edition)
                    if args.ui_smoke_test
                    else run(args.data_dir or Path(temporary))
                )
            except Exception as exc:
                if args.report:
                    args.report.write_text(
                        json.dumps(
                            {"error_type": type(exc).__name__, "detail": friendly_error(exc)}
                        ),
                        encoding="utf-8",
                    )
                raise SystemExit(1) from None
            if args.report:
                args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
            if sys.stdout:
                print(json.dumps(result))
        return
    import tkinter as tk

    root = tk.Tk()
    SetupWindow(
        root,
        args.data_dir or remembered_directory(),
        remember=args.data_dir is None,
        edition=args.edition,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
