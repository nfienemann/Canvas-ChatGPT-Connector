# Windows local onboarding acceptance — 2026-10-26

Status: implemented local development preview; **general student release is blocked**.
No real academic records, live credentials, institutional approval changes or
background monitoring were used. No release was published. Existing workspace
changes from earlier specifications were preserved.

## Implemented and exercised

- Separate offline, synthetic and institutional pathways. The shipped institutional
  catalog is empty. It cannot grant approvals or request a student's Canvas API token.
- Per-user Windows x64 installer with bundled runtime and native setup wizard.
  Compatibility, installed-file integrity and a completed fictional academic task
  precede success. Python/terminal setup is not part of the student flow.
- Offline 85% arithmetic, bounded permitted TXT/Markdown inspection without external
  sharing, and explicit refusal of unverified offline document formats.
- Synthetic local authenticated MCP negotiation, coursework reads and planning.
  Actual ChatGPT and institutional connections remain independently unverified.
- Evidence-specific progress and privacy-safe diagnostics. Failed rechecks clear
  prior success, and successful recovery restores current status.
- Ed25519 release verification, installer hash/size checking, Windows publisher
  verification, release notes and explicit update confirmation. Tampered, expired,
  incompatible, unsigned and untrusted updates fail closed. Product trust anchors
  are intentionally empty. Test signing identities are ephemeral fixtures only.
- Compatible signed binary rollback preserves the current database and refuses legacy releases below the 0.2.0 access-preservation floor. Copy-first
  local migration verifies integrity, credentials, preferences and disabled access
  before replacement; an injected migration failure leaves the original intact.
- Restart cannot recreate disabled or deleted demo connections. Explicit local
  deletion refuses active profiles, unknown files and linked paths. Uninstall
  defaults to keeping data and describes external copies outside its control.

## Verification record

Full suite: **1,653 passed, 28 skipped** in 560.24 seconds. Skips concern unsupported
host/platform dependencies, disposable PostgreSQL, trusted converters and OCR.
The final onboarding/desktop run after UI refinements: **29 passed**. It includes
actual Windows rejection of an unsigned executable and native failed-recheck
recovery. The full suite predates those final narrow onboarding refinements; it was not
redundantly repeated after the focused run.

Repository lint and formatting passed. The configured Bandit medium/high severity
and confidence gate passed; this does not mean all low-severity scanner advisories
or external release gates are resolved. Governance registry validation passed with
23 controls and no authorization granted. `git diff --check` passed.

The full synthetic academic benchmark has **81 objective passes, 2 interpretation
cases requiring expert review, and no paired regressions** against the prior
semester report. No competitive-model accuracy or human interpretation claim follows
from that backend regression check. Correlated curated fixtures do not justify a
population confidence interval.

The packaged Windows receipt and artifact hash are recorded in
[onboarding-2026-10-26.json](onboarding-2026-10-26.json). The receipt covers installed
startup from an unrelated directory with Python removed from PATH, both native
wizard paths, blocked unapproved institutional setup, consent gating, widget bounds,
local MCP tasks, in-place reinstall, preserved keys and silent uninstall preserving
data. Hashes bind the tested installer and installed file manifest. Automated
widget checks do not constitute visual accessibility or human usability evidence.

## Remaining external gates

| Requirement | Evidence boundary |
|---|---|
| Trusted initial install and signed update/rollback rehearsal | No real signing identity is configured. The built artifact is unsigned; signed release mode rejects missing trust rather than falling back. Checksums establish integrity, not publisher identity. |
| Approved institution connection | No approved hosted service is packaged; host-side approval and identity checks remain mandatory. |
| Advertised AI clients | Local MCP SDK client tested; current installer integration with ChatGPT and other real clients not tested. |
| Nontechnical usability | Zero participants; completion rate, assistance, permission decisions, comprehension and human timing unmeasured. |
| Visual/accessibility QA | Windows desktop was locked. Screenshots could not establish wizard appearance. Widget bounds passed; unlocked-desktop, keyboard, screen-reader and scaling trials remain. |
| Standard-user consumer machines | Per-user/lowest-privilege installer configured and exercised on this host; a fresh independent standard-user machine trial remains. |
| Other platforms / optional converters | macOS/Linux scaffolding is experimental. Frozen offline format support is TXT/Markdown only; optional conversion is detected but never silently enabled or installed. |

The complete zero-friction definition of done is **not yet met** because the
signing, independent-client and human study gates require external evidence.
See [setup and recovery documentation](../../docs/desktop-distribution.md) and
[usability study protocol](../../docs/review-templates/onboarding-usability.md).
