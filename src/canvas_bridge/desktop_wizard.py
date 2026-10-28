"""Native setup and maintenance UI, not an academic dashboard or chatbot."""

import json
import queue
import tempfile
import threading
import webbrowser
from pathlib import Path

from canvas_bridge.onboarding import (
    EDITIONS,
    OfflineRuntime,
    SetupError,
    authorized_services,
    compatibility,
    diagnostics,
    verify_bundle,
)


class SetupWizard:
    def __init__(self, root, folder, *, remember=True, edition="offline"):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.root = tk, ttk, root
        self.folder, self.base_folder, self.remember = Path(folder), Path(folder), remember
        self.mode = tk.StringVar(value=edition)
        self.consent = tk.BooleanVar(value=False)
        self.runtime, self.result = None, None
        self.events = queue.Queue()
        self.busy = self.closing = False
        self.stage = "welcome"
        root.title("Canvas Bridge · Setup")
        root.geometry("780x700")
        root.minsize(730, 670)
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f3f7f6")
        style.configure("TLabel", background="#f3f7f6", foreground="#182e32", font=("Segoe UI", 11))
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("TButton", padding=(12, 8))
        root.configure(background="#f3f7f6")
        self.frame = ttk.Frame(root, padding=28)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(0, weight=1)
        self.eyebrow = ttk.Label(self.frame, text="CANVAS BRIDGE  /  SETUP")
        self.eyebrow.grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.title = ttk.Label(self.frame, style="Title.TLabel", wraplength=710)
        self.title.grid(row=1, column=0, sticky="w")
        self.body = ttk.Label(self.frame, wraplength=710, justify="left")
        self.body.grid(row=2, column=0, sticky="w", pady=14)
        self.detail = ttk.Label(self.frame, wraplength=710, justify="left")
        self.detail.grid(row=3, column=0, sticky="w", pady=(0, 12))
        self.extra = ttk.Frame(self.frame)
        self.extra.grid(row=4, column=0, sticky="ew")
        self.progress = ttk.Progressbar(self.frame, maximum=5)
        self.progress.grid(row=5, column=0, sticky="ew", pady=(16, 4))
        self.status = ttk.Label(self.frame, wraplength=710, justify="left")
        self.status.grid(row=6, column=0, sticky="sw", pady=12)
        self.frame.rowconfigure(6, weight=1)
        self.buttons = ttk.Frame(self.frame)
        self.buttons.grid(row=7, column=0, sticky="ew")
        self.secondary = ttk.Button(self.buttons, text="Close", command=self.close)
        self.secondary.pack(side="left")
        self.primary = ttk.Button(self.buttons, text="Continue", command=self.setup)
        self.primary.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda _: self.close())
        self.welcome()
        root.after(100, self.poll)

    def clear_extra(self):
        for child in self.extra.winfo_children():
            child.destroy()

    def welcome(self):
        self.stage = "welcome"
        self.title.configure(text="Choose how to begin")
        self.body.configure(
            text="Start with local tools, explore fictional coursework, or check whether an approved institution service is available."
        )
        self.detail.configure(
            text="No terminal, API token or administrator access is needed for the local editions. Installing this app never enables university access."
        )
        self.clear_extra()
        for edition, (label, explanation) in EDITIONS.items():
            self.ttk.Radiobutton(self.extra, text=label, value=edition, variable=self.mode).pack(
                anchor="w", pady=(6, 0)
            )
            self.ttk.Label(self.extra, text=explanation, wraplength=680).pack(
                anchor="w", padx=24, pady=(0, 6)
            )
        self.primary.configure(text="Continue", command=self.setup)
        self.status.configure(
            text="Windows x64 local preview. Other operating systems and ChatGPT client acceptance are not claimed by this installer."
        )
        self.primary.focus_set()

    def setup(self):
        from canvas_bridge.desktop import remembered_directory

        self.clear_extra()
        self.consent.set(False)
        self.stage = "setup"
        if self.mode.get() == "institutional":
            self.title.configure(text="Institution access needs approval")
            self.body.configure(
                text="Your institution's hosted service must verify provider approval, institution approval, authentication and sharing permissions. This installer cannot change any of them."
            )
            services = authorized_services()
            self.detail.configure(
                text="No approved service is included in this release. Ask your institution for its approved sign-in route. Never paste a Canvas API token."
                if not services
                else "Choose your institution's reviewed sign-in route. The host will check current approval before enabling access."
            )
            for service in services:
                self.ttk.Button(
                    self.extra,
                    text=service["name"],
                    command=lambda url=service["settings_url"]: webbrowser.open(url),
                ).pack(anchor="w")
            self.primary.configure(text="Back to local editions", command=self.welcome)
            self.status.configure(
                text="Institution connection: not established. Client integration: not verified."
            )
            return
        if self.remember:
            self.folder = remembered_directory(self.mode.get())
        else:
            self.folder = self.base_folder
        self.title.configure(text="Review your local setup")
        self.body.configure(
            text=EDITIONS[self.mode.get()][1]
            + " No external AI service is connected by setup. Nothing starts automatically when you sign in to your computer."
        )
        self.detail.configure(
            text=f"Application data folder:\n{self.folder}\n\nPreferences stay separate from program files. Local demo sign-in keys are created only for the synthetic edition."
        )
        self.ttk.Checkbutton(
            self.extra,
            variable=self.consent,
            text="I understand this edition's data use and want to set it up locally.",
        ).pack(anchor="w", pady=5)
        self.ttk.Button(self.extra, text="Choose data folder…", command=self.choose_folder).pack(
            anchor="w", pady=5
        )
        self.ttk.Button(self.extra, text="Back", command=self.welcome).pack(anchor="w", pady=5)
        self.status.configure(
            text="Setup checks compatibility, application files, local health, available sources and a fictional academic task. Missing approvals cannot be bypassed."
        )
        self.primary.configure(text="Check and set up", command=self.start)

    def choose_folder(self):
        from tkinter import filedialog

        chosen = filedialog.askdirectory(
            parent=self.root, title="Choose a parent for application data"
        )
        if chosen:
            self.folder = Path(chosen) / (
                "Canvas Bridge Offline" if self.mode.get() == "offline" else "Canvas Bridge Demo"
            )
            self.detail.configure(text=f"Application data folder:\n{self.folder}")

    def background(self, operation, task):
        if self.busy:
            return
        self.busy = True
        self.primary.configure(state="disabled")
        for child in self.extra.winfo_children():
            if child.winfo_class() == "TButton":
                child.configure(state="disabled")

        def execute():
            try:
                self.events.put((operation, task(), None))
            except Exception as exc:
                self.events.put((operation, None, exc))

        threading.Thread(target=execute, name="bridge-setup", daemon=True).start()

    def start(self):
        if not self.consent.get():
            self.status.configure(
                text="Review the data-use explanation and select the confirmation before continuing."
            )
            return
        from canvas_bridge.desktop import DemoRuntime

        self.runtime = (
            OfflineRuntime(self.folder)
            if self.mode.get() == "offline"
            else DemoRuntime(self.folder)
        )

        def task():
            self.events.put(("progress", (1, "Checking system compatibility…"), None))
            if not compatibility()["supported_release"]:
                raise SetupError(
                    "PLATFORM_NOT_SUPPORTED",
                    "This installer is supported on Windows x64. Other platform editions are not yet verified.",
                )
            self.events.put(("progress", (2, "Verifying packaged application components…"), None))
            bundle = verify_bundle()
            self.events.put(("progress", (3, "Starting the selected local edition…"), None))
            self.runtime.start()
            self.events.put(
                ("progress", (4, "Verifying local tools and the fictional academic task…"), None)
            )
            try:
                check = self.runtime.check()
            except Exception:
                self.runtime.stop()
                raise
            return {
                "bundle": bundle,
                "check": check,
                "diagnostics": diagnostics(self.runtime, check),
            }

        self.background("start", task)

    def ready(self):
        self.stage = "ready"
        self.title.configure(text="Your local checks passed")
        offline = self.mode.get() == "offline"
        self.body.configure(
            text="The offline academic engine reproduced the fictional 85% grade. No server or account was needed."
            if offline
            else "The local server authenticated its test client, negotiated study tools, read fictional coursework and produced a study recommendation."
        )
        self.detail.configure(
            text="University access: not enabled. ChatGPT integration: not tested. A prepared document or rendered image never proves delivery or analysis in an AI client."
        )
        self.progress.configure(value=5)
        self.status.configure(
            text="Check passed. You can review diagnostics, test again or safely close the app."
        )
        self.primary.configure(
            text="Test my text document…" if offline else "Open synthetic settings",
            command=self.inspect_file if offline else self.open_settings,
        )
        self.secondary.configure(text="Close" if offline else "Stop and close")
        self.clear_extra()
        self.check_button = self.ttk.Button(self.extra, text="Run checks again", command=self.check)
        self.check_button.grid(row=0, column=0, padx=(0, 8), pady=5, sticky="w")
        for column, (label, callback) in enumerate(
            (
                ("Diagnostics", self.show_diagnostics),
                ("Update…", self.update),
                ("Roll back…", lambda: self.update(True)),
            ),
            1,
        ):
            self.ttk.Button(self.extra, text=label, command=callback).grid(
                row=0, column=column, padx=4, pady=5
            )
        self.ttk.Button(self.extra, text="Remove local data…", command=self.remove_data).grid(
            row=1, column=0, columnspan=2, pady=8, sticky="w"
        )

    def check(self):
        self.status.configure(text="Rechecking the selected edition…")
        self.background("check", self.runtime.check)

    def open_settings(self):
        if not webbrowser.open(self.runtime.url):
            self.status.configure(
                text=f"Your browser did not open. Open this local address in your browser: {self.runtime.url}"
            )

    def show_diagnostics(self):
        window = self.tk.Toplevel(self.root)
        window.title("Canvas Bridge · Local diagnostics")
        text = self.tk.Text(window, width=90, height=28, wrap="word", padx=16, pady=16)
        text.pack(fill="both", expand=True)
        text.insert("1.0", json.dumps(self.result, indent=2))
        text.configure(state="disabled")
        self.ttk.Button(window, text="Close", command=window.destroy).pack(pady=10)

    def inspect_file(self):
        from tkinter import filedialog, messagebox

        if not messagebox.askyesno(
            "Permission to process",
            "Only choose your own permitted material. Do not select restricted exams, confidential research or another person's records. Processing stays local; nothing is shared. Continue?",
            parent=self.root,
        ):
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Test your own permitted text document",
            filetypes=[("Text documents", "*.txt *.md")],
        )
        if path:
            self.background("document", lambda: self.runtime.inspect(path, own_material=True))

    def update(self, rollback=False):
        from tkinter import filedialog

        from canvas_bridge.desktop_updates import prepare_update
        from canvas_bridge.onboarding import trust_configuration

        if not trust_configuration().get("release_keys"):
            self.status.configure(
                text="Signed updates are not configured for this development preview. Obtain a publisher-approved release; unsigned packages cannot be installed through this wizard."
            )
            return
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a signed Canvas Bridge update",
            filetypes=[("Signed update package", "*.cbu")],
        )
        if not chosen:
            return
        revision = None
        if self.mode.get() == "synthetic":
            from canvas_bridge.deployment import preflight

            revision = preflight(self.runtime.settings)["revision"]
        staging = Path(tempfile.mkdtemp(prefix="bridge-verified-update-")) / "verified"
        edition = self.mode.get()
        self.status.configure(
            text="Verifying release signature, compatibility, file integrity and Windows publisher…"
        )

        def task():
            return prepare_update(
                chosen,
                staging,
                edition=edition,
                database_revision=revision,
                rollback=rollback,
            )

        self.background("update_review", task)

    def review_update(self, prepared):
        from tkinter import messagebox

        from canvas_bridge.desktop_updates import launch_update

        if not messagebox.askyesno(
            "Review verified release",
            prepared["release"].release_notes
            + "\n\nKeep preferences and access state. Stop this application and open the verified installer?",
            parent=self.root,
        ):
            prepared["installer"].unlink(missing_ok=True)
            self.status.configure(
                text="Update canceled. The current application and data are unchanged."
            )
            return

        def install():
            self.runtime.stop()
            launch_update(prepared, confirmed=True)
            return {"installer": "launched"}

        self.background("update_install", install)

    def remove_data(self):
        from tkinter import messagebox

        from canvas_bridge.desktop_profiles import remove_profile

        if not messagebox.askyesno(
            "Remove local data",
            f"Permanently remove application records, preferences and local sign-in keys in:\n{self.folder}\n\nExisting ChatGPT conversations, Canvas records, downloads and backups elsewhere are outside this deletion. Continue?",
            parent=self.root,
        ):
            return

        def task():
            self.runtime.stop()
            return remove_profile(self.folder, confirmed=True)

        self.background("remove", task)

    def close(self):
        self.closing = True
        self.secondary.configure(state="disabled")
        self.status.configure(text="Closing local tools. Your data will be kept.")
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
        if operation == "progress":
            self.progress.configure(value=result[0])
            self.status.configure(text=result[1])
            self.root.after(100, self.poll)
            return
        self.busy = False
        self.primary.configure(state="normal")
        for child in self.extra.winfo_children():
            if child.winfo_class() == "TButton":
                child.configure(state="normal")
        if operation in {"stop", "remove", "update_install"} and not error:
            self.root.destroy()
            return
        if self.closing and operation != "stop":
            self.close()
        elif error:
            from canvas_bridge.desktop import friendly_error

            self.closing = False
            self.secondary.configure(state="normal")
            self.status.configure(text=friendly_error(error))
            if self.result is not None and operation in {"check", "update_install", "remove"}:
                self.result["check"] = {"state": "failed"}
                self.result["diagnostics"] = diagnostics(self.runtime)
                self.title.configure(text="Local checks need attention")
                if operation != "check":
                    self.status.configure(
                        text=friendly_error(error)
                        + " Local tools stopped. Close and reopen the application after reviewing this result."
                    )
                    self.primary.configure(state="disabled")
            if operation == "start" and self.mode.get() == "synthetic" and self.runtime.settings:
                from canvas_bridge.deployment import preflight

                if preflight(self.runtime.settings)["findings"] == ["SCHEMA_UPGRADE_REQUIRED"]:
                    self.ttk.Button(
                        self.extra, text="Review data upgrade…", command=self.upgrade_data
                    ).pack(anchor="w")
        elif operation == "start":
            self.result = result
            if self.remember:
                from canvas_bridge.desktop import remember_directory

                try:
                    remember_directory(self.folder, self.mode.get())
                except OSError:
                    pass  # A convenience preference cannot turn a verified setup into failure.
            self.ready()
        elif operation == "check":
            self.title.configure(text="Your local checks passed")
            self.result["check"] = result
            self.result["diagnostics"] = diagnostics(self.runtime, result)
            self.status.configure(
                text="Check passed. Local task completed; external client and university access remain unverified."
            )
        elif operation == "document":
            self.result["document_check"] = result
            self.status.configure(
                text=f"Source retrieved and text extracted ({result['characters_extracted']} characters). Conversion, pixels, delivery and AI analysis were not claimed. No document was saved."
            )
        elif operation == "upgrade":
            self.status.configure(
                text="Local data upgrade verified. Preferences and access state were preserved. Choose Check and set up again."
            )
        elif operation == "update_review":
            self.review_update(result)
        self.root.after(100, self.poll)

    def upgrade_data(self):
        from tkinter import messagebox

        from canvas_bridge.desktop_profiles import migrate_profile

        if not messagebox.askyesno(
            "Verify local data upgrade",
            "The app will test migration on a copy and verify preferences and access state before replacing the local database. The original stays intact if verification fails. Continue?",
            parent=self.root,
        ):
            return

        def task():
            self.runtime.stop()
            return migrate_profile(self.runtime.settings, acknowledged=True)

        self.background("upgrade", task)


def uninstall_data_window():
    import tkinter as tk
    from tkinter import messagebox, ttk

    from canvas_bridge.desktop import default_data_directory, remembered_directory
    from canvas_bridge.desktop_profiles import MARKER, remove_profile

    root = tk.Tk()
    root.title("Canvas Bridge · Local data")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Keep or remove local data", font=("Segoe UI", 18, "bold")).pack(
        anchor="w"
    )
    ttk.Label(
        frame,
        text="Uninstalling program files keeps data unless you select a folder below.\nRemoval includes its local records, preferences and sign-in keys.\nCanvas, ChatGPT conversations, external downloads and backups are unchanged.",
        wraplength=650,
    ).pack(anchor="w", pady=16)
    choices = []
    for folder in sorted(
        {
            remembered_directory(),
            remembered_directory("offline"),
            default_data_directory(),
            default_data_directory().with_name("Canvas Bridge Offline"),
        }
    ):
        if (folder / MARKER).is_file():
            selected = tk.BooleanVar(value=False)
            ttk.Checkbutton(frame, text=str(folder), variable=selected).pack(anchor="w", pady=8)
            choices.append((folder, selected))

    def remove():
        selected = [f for f, v in choices if v.get()]
        if not selected:
            root.destroy()
            return
        if not messagebox.askyesno(
            "Confirm permanent removal",
            "Permanently remove only the selected application data folders?",
            parent=root,
        ):
            return
        try:
            for folder in selected:
                remove_profile(folder, confirmed=True)
        except Exception as exc:
            from canvas_bridge.desktop import friendly_error

            messagebox.showerror("Removal needs review", friendly_error(exc), parent=root)
            return
        root.destroy()

    ttk.Button(frame, text="Keep data and continue", command=root.destroy).pack(
        side="left", pady=20
    )
    ttk.Button(frame, text="Remove selected data", command=remove).pack(side="right", pady=20)
    root.mainloop()
