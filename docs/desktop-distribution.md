# Desktop distribution

## Audience and first run

Everyday students should use a supported hosted service directly from ChatGPT;
they should not install a server, paste a Canvas token, obtain an API key, or read
a GitHub installation guide. No approved hosted service exists yet. The native
packages are a **local synthetic demonstration** for evaluation and operator
training. They are not a production hosting wizard and cannot enable live access.

The download page presents a short OS-specific download table. Windows uses a
per-user EXE setup wizard with a Start menu shortcut and an optional desktop
shortcut. It does not request administrator access. macOS uses a DMG with the app
and Applications shortcut. Ubuntu/compatible Debian uses a DEB that the system
software installer can open, with an Applications-menu entry. Linux package
installation can require administrator approval. A portable Linux tarball is
also provided; compatibility outside the tested distribution is not established.

The native launcher explains the fictional scope before initializing anything.
The user can change the data directory, start the demo, open browser settings,
and run the authenticated MCP read/planning check using buttons. No terminal is
part of the ordinary path. Errors use plain language and never display tokens or
private connection URLs. The existing settings page remains the only browser UI;
the launcher is not a separate academic dashboard or chatbot.

## Data and lifecycle

Default folders:

| OS | Data |
|---|---|
| Windows | `%LOCALAPPDATA%\Canvas Bridge Demo` |
| macOS | `~/Library/Application Support/Canvas Bridge Demo` |
| Linux | `$XDG_DATA_HOME/Canvas Bridge Demo`, or `~/.local/share/Canvas Bridge Demo` |

`Canvas Bridge Launcher/preferences.json` alongside the default folder remembers
only the chosen directory. Data and keys are separate from application binaries.
An OS lock prevents concurrent access by two launchers, including after a crash.
The server binds a reserved loopback socket and chooses another port if necessary.
Operator environment variables and `.env` files cannot change the demo's profile,
database, network binding or credentials. Resources resolve inside the package;
working-directory changes and spaces/Unicode in the profile path are tested.

Starting again renews the fictional sign-in token, runs migrations and preserves
keys, existing connections and course selections. Closing stops the server and
closes database pools. Nothing installs a background service or enables autostart.
Uninstall removes program files; it deliberately keeps data. Privacy controls
inside the running demo delete account records. After closing, the user can remove
the displayed demo folder through their file manager to remove all demo files.

## Build and verification

Contributor build: `uv sync --frozen --group packaging`, then
`uv run --group packaging python scripts/build_desktop.py`. Windows build machines
also need Inno Setup 6. End users need none of these dependencies. Python, native
libraries, Tk, migration scripts, institution fixtures, project license status and
third-party notices are bundled using explicit resource lists. No entire checkout,
`.env`, local DB, test credential or operator directory is added.

`scripts/smoke_desktop.py` installs/copies the finished package in a disposable
location, launches it from a different directory with Python removed from PATH,
tests the wizard controls and real MCP exchange, then checks preservation of keys.
The Windows check also upgrades in place and uninstalls; the Linux check installs
and removes the DEB. It refuses to replace an existing Windows user installation.
macOS checks copying from a mounted DMG. GUI checks do not open external websites.

The normal CI test job must pass before packaging. A main-branch commit containing
`[desktop-preview]`, or the explicit workflow-dispatch option, builds Windows x64,
macOS ARM64/Intel and Linux x64 on their own runners. All four verified packages
are required for publication. The release job uses a short-lived GitHub token with
contents-write permission only in that job, uploads to a draft and publishes an
immutable commit-tagged prerelease after every upload succeeds. SHA-256 checksums
and platform verification reports accompany downloads. This is source/binary
distribution, not deployment of a live service.

## Remaining public-release gates

Development packages are unsigned (macOS may have PyInstaller's local ad-hoc
signature). These are not verified publisher signatures. Windows Authenticode
and Apple Developer ID signing/notarization require the owner's real signing
identity and protected release configuration. Do not advise users to disable
SmartScreen, Gatekeeper or antivirus. Checksums are not a substitute for signing.

Runner GUI checks do not establish screen-reader accessibility, fresh consumer-OS
trust prompts, every Linux distribution, or compatibility with older OS versions.
Windows ARM64 and Linux ARM64 are not packaged. The owner must select the project
license before claiming an open-source release. Native packaging also cannot
replace institution OAuth approval, live hosting/identity setup, ChatGPT client
verification or distribution eligibility review.

Build references: [PyInstaller](https://pyinstaller.org/en/stable/),
[Inno Setup](https://jrsoftware.org/isinfo.php), and
[GitHub runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
