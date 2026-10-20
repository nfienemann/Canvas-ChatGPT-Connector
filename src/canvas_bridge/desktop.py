"""A bundled, loopback-only demo. Student use of a hosted release needs no app."""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import webbrowser
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


def remembered_directory() -> Path:
    default = default_data_directory()
    location = default.parent / "Canvas Bridge Launcher" / "preferences.json"
    try:
        if location.stat().st_size > 8192:
            return default
        value = Path(json.loads(location.read_text(encoding="utf-8"))["data_directory"])
        return value if value.is_absolute() else default
    except (OSError, ValueError, KeyError, TypeError):
        return default


def remember_directory(folder: Path):
    location = default_data_directory().parent / "Canvas Bridge Launcher"
    location.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = location / "preferences.tmp"
    temporary.write_text(json.dumps({"data_directory": str(folder.resolve())}), encoding="utf-8")
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
        self.folder = folder.expanduser().resolve()
        self.preferred_port = preferred_port
        self.lock = None
        self.socket = None
        self.server = None
        self.thread = None
        self.settings = None
        self.failure = None
        self.app = None

    def start(self):
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
    if isinstance(error, AlreadyRunning):
        return str(error)
    if isinstance(error, PermissionError):
        return "This folder cannot be used. Choose a folder in your user account and try again."
    return (
        "The demo could not finish this step. Your existing files were kept. "
        "Close other copies, then try again. If it still fails, report error type "
        f"{type(error).__name__} to the project owner. Do not attach your data folder."
    )


class SetupWindow:
    def __init__(self, root, folder: Path, *, remember=True):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root, self.folder = root, folder
        self.remember = remember
        self.runtime = None
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.stage = "welcome"
        root.title("Canvas Bridge · Local demo")
        root.geometry("660x530")
        root.minsize(590, 490)
        root.configure(background="#f3f7f6")
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f3f7f6")
        style.configure("TLabel", background="#f3f7f6", foreground="#182e32", font=("", 11))
        style.configure("Title.TLabel", font=("", 23, "bold"))
        style.configure("Accent.TButton", font=("", 11, "bold"), padding=(18, 11))
        style.configure("TButton", padding=(10, 7))
        self.frame = ttk.Frame(root, padding=28)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(0, weight=1)
        self.eyebrow = ttk.Label(self.frame, text="CANVAS BRIDGE  /  LOCAL DEMO")
        self.eyebrow.grid(row=0, column=0, sticky="w", pady=(0, 18))
        self.title = ttk.Label(self.frame, style="Title.TLabel", wraplength=570)
        self.title.grid(row=1, column=0, sticky="w")
        self.body = ttk.Label(self.frame, wraplength=570, justify="left")
        self.body.grid(row=2, column=0, sticky="nw", pady=18)
        self.detail = ttk.Label(self.frame, wraplength=570, justify="left")
        self.detail.grid(row=3, column=0, sticky="nw", pady=(0, 15))
        self.extra = ttk.Frame(self.frame)
        self.extra.grid(row=4, column=0, sticky="ew")
        self.status = ttk.Label(self.frame, wraplength=570, justify="left")
        self.status.grid(row=5, column=0, sticky="sw", pady=14)
        self.frame.rowconfigure(5, weight=1)
        self.buttons = ttk.Frame(self.frame)
        self.buttons.grid(row=6, column=0, sticky="ew")
        self.secondary = ttk.Button(self.buttons, text="Close", command=self.close)
        self.secondary.pack(side="left")
        self.primary = ttk.Button(self.buttons, style="Accent.TButton", command=self.setup)
        self.primary.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda _: self.close())
        self.welcome()
        root.after(100, self.poll)

    def clear_extra(self):
        for widget in self.extra.winfo_children():
            widget.destroy()

    def welcome(self):
        self.stage = "welcome"
        self.title.configure(text="Try it on your computer")
        self.body.configure(
            text="Explore connection settings and test the study tools with fictional courses. Setup takes about a minute. No Python, terminal commands or API keys are needed."
        )
        self.detail.configure(
            text="This preview does not connect to your university or ChatGPT. A future hosted release is intended to let students connect directly in ChatGPT without installing anything."
        )
        self.primary.configure(text="Set up local demo", command=self.setup)
        self.primary.focus_set()

    def setup(self):
        from tkinter import filedialog

        self.stage = "setup"
        self.title.configure(text="A private place for your demo")
        self.body.configure(
            text="Fictional records and local sign-in keys stay in your user account. The demo is accessible only from this computer. Nothing starts automatically when you sign in to your computer."
        )
        self.detail.configure(text=f"Demo data folder:\n{self.folder}")
        self.clear_extra()

        def choose():
            picked = filedialog.askdirectory(
                parent=self.root, title="Choose where to keep demo data"
            )
            if picked:
                self.folder = Path(picked) / "Canvas Bridge Demo"
                self.detail.configure(text=f"Demo data folder:\n{self.folder}")

        self.ttk.Button(self.extra, text="Choose another folder…", command=choose).pack(anchor="w")
        self.status.configure(
            text="Upgrades keep this folder. Uninstalling the application also keeps it."
        )
        self.primary.configure(text="Start local demo", command=self.start)

    def background(self, operation, task):
        self.busy = True
        self.primary.configure(state="disabled")

        def run():
            try:
                result = task()
                self.events.put((operation, result, None))
            except Exception as exc:
                self.events.put((operation, None, exc))

        threading.Thread(target=run, daemon=True).start()

    def start(self):
        self.clear_extra()
        self.status.configure(text="Preparing your local demo…")
        self.runtime = DemoRuntime(self.folder)
        self.background("start", self.runtime.start)

    def ready(self):
        self.stage = "ready"
        self.title.configure(text="Your local demo is ready")
        self.body.configure(
            text="Open connection settings, choose “Open synthetic settings,” and explore the fictional course and privacy controls. Keep this window open while using the demo."
        )
        self.detail.configure(
            text=f"Only on this computer:\n{self.runtime.url}\n\nNo real university or ChatGPT account is connected."
        )
        self.status.configure(
            text="You can also run a quick connection and study-tool check below."
        )
        self.primary.configure(text="Open demo settings", command=self.open_settings)
        self.secondary.configure(text="Stop and close")
        self.clear_extra()
        self.check_button = self.ttk.Button(
            self.extra, text="Check study tools", command=self.check
        )
        self.check_button.pack(anchor="w")

    def open_settings(self):
        if not webbrowser.open(self.runtime.url):
            self.status.configure(
                text="Your browser did not open. Copy the local address shown above into your browser."
            )

    def check(self):
        self.check_button.configure(state="disabled")
        self.status.configure(text="Checking the connection and fictional study tools…")
        self.background("check", self.runtime.check)

    def close(self):
        self.closing = True
        self.secondary.configure(state="disabled")
        self.status.configure(text="Stopping the local demo… Your data will be kept.")
        if not self.busy:
            if self.runtime:
                self.background("stop", self.runtime.stop)
            else:
                self.root.destroy()

    def poll(self):
        try:
            operation, result, error = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll)
            return
        self.busy = False
        self.primary.configure(state="normal")
        if operation == "stop" and not error:
            self.root.destroy()
            return
        if self.closing and operation != "stop":
            self.close()
        elif error:
            self.closing = False
            self.secondary.configure(state="normal")
            if operation == "start":
                self.setup()
            self.status.configure(text=friendly_error(error))
        elif operation == "start":
            if self.remember:
                try:
                    remember_directory(self.folder)
                except OSError:
                    pass  # The running demo is usable even if this convenience cannot be saved.
            self.ready()
        elif operation == "check":
            self.status.configure(
                text=f"Check passed: {result['tool_count']} study tools, {result['observed_obligations']} fictional assignments, and a study recommendation. Live Canvas and ChatGPT have not been tested."
            )
        if operation == "check":
            self.check_button.configure(state="normal")
        self.root.after(100, self.poll)


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


def ui_smoke_test(folder: Path) -> dict:
    """Exercise native widgets and the bundled runtime without opening a browser."""
    import tkinter as tk

    root = tk.Tk()
    window = SetupWindow(root, folder, remember=False)
    try:
        window.primary.invoke()
        assert window.stage == "setup"
        window.primary.invoke()
        deadline = time.monotonic() + 60
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert window.stage == "ready", window.status.cget("text")
        window.check_button.invoke()
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert window.status.cget("text").startswith("Check passed"), window.status.cget("text")
        return {"native_wizard": "passed", "platform": sys.platform}
    finally:
        if window.runtime:
            window.runtime.stop()
        root.destroy()


def main():
    logging.disable(logging.INFO)
    parser = argparse.ArgumentParser(description="Canvas Bridge local demo")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--ui-smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.smoke_test or args.ui_smoke_test:
        with tempfile.TemporaryDirectory(prefix="Canvas Bridge test ") as temporary:
            try:
                run = ui_smoke_test if args.ui_smoke_test else smoke_test
                result = run(args.data_dir or Path(temporary))
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
    SetupWindow(root, args.data_dir or remembered_directory(), remember=args.data_dir is None)
    root.mainloop()


if __name__ == "__main__":
    main()
