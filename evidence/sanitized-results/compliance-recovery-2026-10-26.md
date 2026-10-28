# CB-09–CB-14 recovery implementation — scoped verification

Date: 2026-10-26. All regression documents, identities, approvals and educational
records were fictional. No institutional request, credential refresh, permission grant,
production migration, restart, publication or deployment was performed.

## Implemented

- Independent source contracts and strict local preferences; institutional plans and
  caches remain subject to the existing provider, institution, identity and sharing gates.
- Authenticated browser import and confirmed deletion of independent documents;
  encrypted bounded storage; six local-document MCP operations; per-source text/image
  consent and exact recipient-policy checks; provenance, expiry and final output fencing.
- Startup schema/key/journal preflight; target-bound encrypted pre-upgrade backup;
  explicit fresh bootstrap and lost-journal recovery with historical uncertainty retained.
- Canonical-origin browser sign-in, safe callback/token reason codes and separate
  settings stages for identity, approvals, OAuth configuration and scope.
- Generated inventory of 48 actual MCP registrations and six operational-regression
  entries in the existing JSON/Markdown compliance report.

Implementation and operator procedure: [compliance-recovery.md](../../docs/compliance-recovery.md).

## Actual checks

The scoped integration selection covered recovery, browser OAuth, identity hardening,
OAuth, account deletion, retention, provider approval, egress, privacy, compliance reports,
provider architecture and the extension SDK: **426 passed, 1 skipped** in 153.57 seconds.

A subsequent recovery-only selection passed **44 tests, with 1 skipped**, in 24.31 seconds.
These 44 repeat part of the earlier selection; they are not 44 additional unique tests.
The PostgreSQL recovery fixture was skipped because `TEST_DATABASE_URL` was not set.
CI's disposable PostgreSQL job will collect it. No full repository suite was run.

Scoped Ruff checks passed; 31 affected Python files passed formatting checks.
`git diff --check` passed for those files. Bandit reported no medium/high severity
findings at medium/high confidence in the five new implementation modules scanned.
The existing registry validator accepted all 23 controls.

The fixtures demonstrate:

- Registered local MCP reading, search, status, cited study evidence and preferences
  work with institutional access disabled and an unverified fictional connection.
- Every registered institutional tool's precheck rejects missing approval, offline mode,
  unverified identity, expired credentials, revocation and disconnected references, with
  no provider request during those checks.
- A fictional PDF is extracted and rendered in a real Windows AppContainer and delivered
  as native MCP image content. Actual model visibility remains explicitly unknown.
- DOCX, PPTX, XLSX, TXT and Markdown imports use the existing parsers.
- Known institutional bytes cannot be relabeled by re-import after cache deletion;
  unknown/mixed provenance and revoked sharing are denied; prompt text cannot alter policy.
- Cross-owner access, expired imports, account deletion during processing and deletion
  confirmation are enforced. Detected page-content identifiers prevent visual sharing.
- Both the selected older revision and the later pre-identity revision upgrade in
  disposable SQLite fixtures after encrypted backup verification. Missing or wrong keys,
  wrong database targets, existing backup destinations and damaged/missing journals fail.
- Canonical login redirects precede cookie/state creation, and callback and personal
  owner mismatch fixtures preserve the original identity controls.

## Evidence boundary

Other work changed the shared repository, including benchmark-lab implementation and tests.
The broad receipt reports `source_unchanged=false`. The focused receipt reports
`source_unchanged=true` during its run, but further repository changes preceded report
generation. The generated reports correctly mark these receipts **STALE**, leave operational controls
**IMPLEMENTED_UNVERIFIED**, and keep every release gate blocked. Actual passing execution
counts above do not override that limitation. No registry entry was promoted to TESTED
by hand. Rerun source-bound readiness checks after the checkout is settled.

Local artifacts (ignored, not publication evidence):

- `.local/recovery-input/tests.json`: broad scoped execution receipt.
- `.local/recovery-input/focused-tests.json`: focused execution receipt.
- `.local/recovery-acceptance-2026-10-26/report.md` and `report.json`.
- `.local/recovery-focused-2026-10-26/report.md` and `report.json`.

The current shell's configured database was inspected read-only. It reports revision
`9b2a41e5021c`, while this source expects `d914cb092014`. Missing fields include
`connections.authentication_state`, later material/snapshot fields and the new independent
storage tables. The preflight reports **SCHEMA_UPGRADE_REQUIRED**. Its journal is readable,
but historical deletion assurance is **unknown**. This observation does not identify which
database a separately running service selects. No actual database was upgraded.

## Remaining operational verification

Confirm the deployment environment and exact database target; back up and apply the
controlled upgrade during authorized downtime. Preserve the existing key and journal.
Run the PostgreSQL fixture against a disposable database. Review the exact recipient
configuration, content rights and full visual-page privacy. Installed ChatGPT widget
behavior and historical identity-warning root cause remain unverified. Independent pixel
delivery currently supports PDF; other independent formats provide text. None of these
checks constitutes external integration approval or a legal-compliance determination.
