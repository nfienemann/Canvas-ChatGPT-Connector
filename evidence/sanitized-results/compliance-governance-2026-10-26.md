# Compliance evidence and release governance verification

Evaluated 2026-10-26. This is development evidence, not legal, institutional,
provider or platform approval. No live LMS retrieval or deployment was performed.

## Source and implementation

- Application 0.1.0; base commit `eaa1d9fbed79dbfaae7492753218005bebd529e5`.
- Uncommitted source snapshot `09a77b7ff0abb766e31dc704ec0f04a38c1c21bbb2236303fd277c81cec45fa9`, scope `reviewed-source-v1`, 296 files. The dirty state blocks release; the base commit alone does not reproduce these changes.
- Added the repository-only `canvas-bridge compliance-report` command, strict evidence models, source-bound pytest recorder and fixed security-check receipts. Reports never initialize application settings or load a database or private approval bundle.
- Registry includes 21 controls, six approval entries, seven manual reviews, four published-policy mappings and fifteen review templates. All actual approval entries remain MISSING.
- Seven fictional walkthroughs exercise unauthorized retrieval, identifier withholding, an 85% academic calculation, revoked input, restricted file transfer, cache expiration and an attempted instruction bypass.
- CI records technical checks, generates sanitized readiness evidence on failure, and enforces the independent offline release gate before requested desktop preview publication. CI changes were inspected and YAML parsed locally; a remote CI run is not claimed.

## Executed checks

The full synthetic regression run completed on 2026-10-25 with **1,305 passed,
27 skipped**, zero failures or errors, in 442.36 seconds. Its receipt records
1,332 collected cases, a complete selection, exit code 0 and unchanged source.
On resumption on 2026-10-26, the current source fingerprint still matched that
receipt and all eight security-check receipts. No redundant full run was needed.

Skipped cases: 13 require Linux, seven require an explicitly configured disposable
PostgreSQL database, five require optional trusted native converters and two
require OCR. Skipped execution does not verify a control.

The focused evidence and walkthrough suite passed **34 tests** in 41.16 seconds.
Eight fixed checks passed: Ruff lint, Ruff formatting, Bandit, Python dependency
vulnerabilities, Node dependency vulnerabilities, dependency license screening,
Git-history secret scanning and staged-source secret scanning. Both dependency
audits reported zero known findings within their recorded scope. The unpublished
first-party application still requires source review; dependency results do not
establish application security or project licensing.

Container configuration, image vulnerability and Linux container runtime checks
were NOT_RUN on this Windows host. The report preserves those gaps. The wheel
built, contained all seven compliance modules, and its extracted installed-layout
CLI validated the source registry. Dependency consistency checking passed for
84 installed packages. `git diff --check` passed.

## Generated package and reproducibility

Local output: `.local/compliance-review-package/report.md` and `report.json`.
Inputs: `.local/compliance-evidence-input/tests.json` and its `checks/` directory.
These are explicit local review exports, not tracked student-data caches.

```console
python -m canvas_bridge.cli compliance-report --category synthetic_demo --results .local/compliance-evidence-input/tests.json --checks .local/compliance-evidence-input/checks --output .local/compliance-review-package
```

The command requires a new output directory. Repeating with identical inputs and
evaluation date produced byte-identical Markdown and JSON. Adding
`--enforce-release offline_core` wrote the same report and returned exit code 2.
The generated package also passed a separate redacted Gitleaks scan.

- Markdown SHA-256: `7034e335e69aa5c185a10102af65e6993bad1afcb098b3b4e74d8b46bd2f3a14`.
- JSON SHA-256: `8bb5827c3c0339c6e977407612cdab1d1fcc2a653aeb6627cd15e89afcd4aae4`.
- Observed controls: 17 TESTED, one IMPLEMENTED_UNVERIFIED (`CB-DOCUMENT-01`), three REQUIRES_EXTERNAL_APPROVAL.
- Offline core, institutional pilot and public connected plugin gates: BLOCKED.
- Legal compliance determination: NOT_MADE.

## Remaining boundaries

Missing approvals, adopted project licensing, independent content/security reviews,
deployment/operations reviews, platform-specific document proofs and container
checks remain explicit release blockers. Local receipts are unsigned; an authorized
reviewer must confirm provenance through trusted CI or supervised reproduction.
Policy mappings are technical interpretations and do not broaden runtime grants.
Secret scanning and a synthetic fixture catalog support content review but cannot
prove the absence of every possible confidential datum.

On resumption, migration source was unchanged and installed packages remained
compatible. The default local configuration and database file timestamps predated
this work; their contents were not inspected. No disposable PostgreSQL test URL
was configured, so no database synchronization or PostgreSQL runtime claim is made.
