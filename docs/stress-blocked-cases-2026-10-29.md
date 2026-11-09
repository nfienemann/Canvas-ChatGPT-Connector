# Remaining stress cases: rendering, acknowledgment and recovery

This follows the October 28 result of 70 PASS, 0 FAIL and 3 BLOCKED.
Institutional access remains disabled. Synthetic tests and local changes do not
establish institutional permission, activate the installed service, or satisfy
release approval gates.

## AI-19: actual fictional acknowledgment

`scripts/run_integrity_acknowledgment_demo.py` provides a disposable loopback form
backed by an in-memory synthetic database. The user reads the exact activity and
uncertainty notice, checks an initially unchecked box and submits the form. A GET
does not acknowledge. Host, Origin, HttpOnly/SameSite cookie and CSRF checks remain
mandatory. It imports a separate silent-policy variant; it does not reinterpret
the original C08 fixture's higher-level permission requirement as absent.

The first form's `no-referrer` policy caused a browser POST to use `Origin: null`.
The fix uses `Referrer-Policy: same-origin`, preserving the exact loopback origin
check. This follows the [Fetch Origin-header algorithm](https://fetch.spec.whatwg.org/#origin-header).
No `null`, wildcard, external origin or unchecked form was permitted as a workaround.

The user completed the real form. The service permitted only the displayed fictional
brainstorming scope, rejected reuse for drafting with
`INTEGRITY_ACKNOWLEDGMENT_SCOPE_MISMATCH`, and retained
`permission_established=false`. The disposable acknowledgment was then revoked.
The receipt contains source/implementation hashes and no acknowledgment capability.

A separate chat changed integrity code after the first successful run. That receipt
is preserved as historical evidence. A frozen local test copy was made, and the
user completed its form too. Final verification refers to that stable copy; later
edits in the shared checkout are not silently covered by its results.

## VI-08: original slide pixels

Independent documents now support explicitly permitted PPTX slides through the
configured isolated native converter and existing PDF page renderer. Original
source hash, selected slide number, source slide count, derivative hash and mapping
remain distinct. Source identity and visual-sharing permission are checked again
before releasing pixels; deletion, replacement and sharing withdrawal deny release.

The original ten-slide fixture has a workbook used by its chart slide. A strict
preflight validates that workbook as bounded inert XML, without evaluating cells.
The one-slide dependency subset excludes it when rendering the image-only slide 10.
Any selected slide that needs an embedded workbook remains blocked, and a second
check ensures no embedded package reaches native Office. Macro, external-link,
nested-package and malformed-workbook cases still reject. Original bytes and gold
fixtures are unchanged. Converter identity is versioned to invalidate old caches.

Slide 10 was rendered inside the Windows AppContainer, delivered through synthetic
HTTP MCP, saved and inspected as actual pixels. The image shows Control 50% and
Treatment 75%: a 1.5 ratio and a 25 percentage-point difference. Its prose claim of
twice the control conflicts with those values. Replicate count, error bars and
statistical significance are not established. Observations bind both original PPTX
and delivered PNG hashes. This is not automatic backend interpretation or proof of
pixel visibility through the installed personal connector.

The HTTP test client now allows 120 seconds for the native path instead of cancelling
it after five seconds. Native worker CPU, memory, filesystem and execution deadlines
are unchanged.

## OP-07: prepared, still blocked

The [disposable recovery protocol](disposable-recovery-test.md) and
`scripts/Test-DisposableRecovery.ps1` cover fresh install, a persisted fictional task,
real version upgrade, compatible rollback and uninstall. The local kit contains
the protocol, read-only preflight, synthetic canary, blank stage ledger and executed
preflight receipt. It contains no installer or private state.

Preflight explicitly rejects the personal preparation host, missing disposable-OS
attestation, personal Bridge data, empty reviewed release trust and missing release
artifacts. It never installs, uninstalls, migrates, enables a provider or changes
approval. Passing preflight would only mean ready for official UI verification.

Actual OS recovery remains blocked: this Windows Home PC has no available Sandbox
or hardware virtualization, and the user has no separate test machine. The available
development installer is unsigned, with no configured release trust or suitable
verified upgrade/rollback pair. These prerequisites cannot be replaced by running
an uninstaller against the personal app or fabricating signed-release approval.

See the [verification record](../evidence/sanitized-results/stress-blocked-cases-2026-10-29.md)
for executed results and their source boundaries.
