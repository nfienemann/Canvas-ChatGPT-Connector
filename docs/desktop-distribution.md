# Desktop installation and onboarding

## Supported editions

The local 0.2.0 preview targets Windows 10/11 x64. Python, Tk, native libraries and
application components are bundled. Installation is per user, requires no terminal,
and requests no administrator privileges. This is a setup/maintenance window;
the existing settings page remains the only browser UI. macOS and Linux build
scaffolding is experimental, explicitly opt-in and excluded from release CI.

| Edition | Available task and source | Connection boundary |
|---|---|---|
| Offline academic intelligence | Verified fictional 85% calculation; explicit inspection of the user's permitted TXT/Markdown material | No server, database, account, token or network connection; no external sharing |
| Synthetic demonstration | Fictional courses, authenticated local MCP reads and planning | Loopback only; no institution contacted; local MCP test client is not ChatGPT |
| Authorized institutional integration | Navigation to a reviewed approved hosted service, if included | Default catalog is empty. Host must recheck current authorization, identity, course selection and sharing; no token-paste fallback |

The institutional pathway is deliberately unavailable until its independently
approved service exists. Adding a catalog entry is not an approval or live access
grant. Offline and synthetic data directories cannot be mixed or silently adopt
institutional databases. Shell variables and `.env` cannot enable live access.

## First run

Open the Windows installer, then **Canvas Bridge Demo**. Choose the edition,
continue, review the privacy explanation and data location, and select **Check
and set up**. The wizard checks system compatibility, the installed file manifest,
local health, available sources and the fictional task before success. It never
reports a university or AI-client connection from a local test alone.

The offline grade task computes `(80 + 90) / (100 + 100) * 100 = 85%`. Its text
inspection requires explicit ownership/permission acknowledgment, uses bounded
hash-authorized local reads and retains no copy. It reports extraction, not AI
analysis. PDF/PPTX conversion and delivery are not advertised as supported in the
frozen offline edition. Optional LibreOffice metadata detection never installs or
executes a converter; a verified sandboxed conversion component is still required.

Diagnostics distinguish server, authentication, authorization, upstream, converter,
file limits, test-client negotiation, token expiry and clock validation. They omit
credentials, identifiers and raw exception text. No clock-sync claim is made
without an independent trusted time source. Synthetic local tokens last one hour;
restart is explicit. No service, autostart, polling or notification is installed.

| Setup result | Recovery |
|---|---|
| `BUNDLE_INTEGRITY_FAILED` | Reinstall a verified application package; keep the separate profile |
| `EDITION_MISMATCH` / `UNRECOGNIZED_DATA_FOLDER` | Select the matching edition or an empty dedicated folder |
| Profile already open | Close its existing window before retrying; do not remove its lock file |
| `DEMO_ACCESS_DISABLED` | Preserve disabled/deleted access; explicitly choose a new empty fictional profile if a new demonstration is desired |
| Schema upgrade required | Review the copy-first upgrade; missing keys/journal require approved recovery, never replacement credentials |
| Converter missing / not verified | Continue with local grade/TXT/Markdown tasks; optional conversion is unavailable |
| `UPDATE_EXPIRED_OR_CLOCK_INCORRECT` | Check normal automatic system date/time and obtain a current approved package |
| `INSTALLER_PUBLISHER_UNVERIFIED` / `UPDATE_SIGNATURE_INVALID` | Obtain the publisher-approved release; do not bypass verification |
| `ROLLBACK_SCHEMA_INCOMPATIBLE` | Keep the current app or obtain a compatible signed release; no database downgrade |
| `DATA_REMOVAL_REQUIRES_REVIEW` / `DATA_REMOVAL_INCOMPLETE` | Inspect the remaining folder; unknown files are preserved, and an I/O failure may leave a partially removed profile |

## Updates, rollback and recovery

The wizard accepts only `.cbu` packages containing exactly a signed release manifest,
signature and installer. Ed25519 trust anchors and expected Windows publisher
thumbprints are packaged public configuration. Verification checks validity dates,
product/platform/edition, version direction, database compatibility, bounded sizes,
SHA-256 and Windows Authenticode before installation. Release notes and explicit
installation confirmation follow verification. The installer is checked again
before launch. There is no unsigned update fallback or automatic download.

Trust anchors are empty in the development checkout: signed updates are blocked
with recovery guidance. Checksums detect corruption; they do not authenticate a
publisher. No production identity was created or claimed. Publisher signing uses
Windows SDK SignTool and Inno Setup's signed installer/uninstaller support. The
operator must protect the real signing key and configure reviewed public anchors.

Binary rollback needs an explicitly selected, signed older release that supports
the current schema and the 0.2.0 minimum version for access-preservation controls.
Legacy releases below that floor are refused even if signed. It never restores an old database, reconnects a disabled
connection, restores deleted records or widens course selection. Restoring used data
from an old backup is not a desktop rollback mechanism. Start-up refuses outdated
schema until the user approves a local copy-first migration. Migration holds the
profile lock, checks keys/journal and database integrity, verifies preferences,
credentials and access state on the migrated copy, then atomically replaces the
original. Failure keeps the original. Temporary migration copies are removed; no
new persistent backup is retained. This is validation of migration behavior, not a
claim that every future schema change is compatible. Older incompatible releases
require operator assistance, without bypassing recovery controls.

## Local retention and uninstall

Defaults are `%LOCALAPPDATA%\Canvas Bridge Offline` and
`%LOCALAPPDATA%\Canvas Bridge Demo`. Launcher preferences remember only each edition's
chosen folder, separately from academic records. Keys and records are separate
from installed binaries. Closing stops local tools; disabled/deleted connections
and course choices remain disabled/deleted on restart.

Windows uninstall opens a dialog with removal checkboxes **unchecked**. **Keep data
and continue** is the default. The running wizard also has **Remove local data**.
Explicit removal deletes the verified selected application's records, preferences,
keys and owned delivery cache. Unknown files, symlinks/junctions or an active
profile cause refusal for manual review. Silent uninstall and upgrades keep data.
Custom folders remembered by the launcher are listed. An unremembered older folder
can be reviewed and removed separately in a file manager after closing the app.
The launcher directory stores paths only; these can also be removed separately.

Canvas records, ChatGPT conversations, copied downloads, synchronized/OS backups
and institutional service retention are outside this deletion. Deleting local files
is not guaranteed forensic erasure. No credentials or records enter reports.

## Contributor packaging and evidence

Run `uv sync --locked --group packaging`, then `python scripts/build_desktop.py`
in that environment. Inno Setup 6 is a build-machine dependency already installed
by the operator. No executable downloader is included. Locked dependency versions,
explicit resource lists, bundled notices and a per-file SHA-256 manifest support
repeatable inputs; timestamped installers are not claimed byte-for-byte reproducible.

`--release --certificate-thumbprint <approved-thumbprint> --sign-tool <SDK-path>`
requires matching packaged trust and a real protected publisher identity; it fails
instead of producing an unsigned release. `scripts/package_desktop_update.py`
creates signed packages from that installer and an external protected Ed25519
signing key. It verifies the publisher and configured public key before packaging;
keys are never included. Contributor commands are not part of student onboarding.

`scripts/smoke_desktop.py` uses disposable profiles, an unrelated working directory
and PATH without Python, tests actual installed startup, both native wizard paths,
authenticated MCP reads/planning, an in-place reinstall, preserved keys and uninstall.
It refuses to replace an existing Windows user installation. Regular CI runs
onboarding negative/regression tests. Explicit preview CI builds Windows only,
requires both edition receipts and retains checksums. Public preview jobs retain
the independent compliance gate; none was run or published for this implementation.

See [acceptance evidence](../evidence/sanitized-results/onboarding-2026-10-26.md)
and the [nontechnical usability protocol](review-templates/onboarding-usability.md).
Human study results, accessibility/visual inspection on an unlocked consumer desktop,
protected publisher signing, approved institution service and independently tested
AI clients remain external release gates. No general student release is claimed.

References: [Inno per-user privileges](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[signed uninstallers](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm),
[Windows SignTool](https://learn.microsoft.com/en-us/windows/desktop/seccrypto/signtool).
