# Remaining blocked cases: verification record, October 29, 2026

Status: AI-19 and VI-08 passed; OP-07 remains blocked. Broader snapshot suites have failures.
This file is not a release approval.

The frozen test copy was retained in a private local temporary directory.
Its Git base is `5bd086356e730b01b5a9f1be9de106446ef049c6`; the tested working
source includes uncommitted edits. A separate chat continues editing the original
checkout. This record applies to the frozen bytes, not all subsequent shared edits.

Executed so far:

- Focused source, subset, rendering and permission tests: **57 passed, 2 skipped**.
- Explicit trusted native-runtime tests: **2 passed**; the prior skips were executed.
- Frozen-copy visual cases VI-01, VI-02, VI-08: **3 passed** with hash-bound actual
  pixel observations. Corpus source fingerprint:
  `3fffb7122d17593000939a85fe076da197f632809463248435a2e1b68c2120a2`.
- Two genuine user UI submissions succeeded at their respective source revisions.
  The final frozen-copy AI-19 receipt records brainstorming allowed, instructor
  permission false and different-activity reuse denied. It is not reusable consent.
- Disposable recovery preflight: **BLOCKED**, with no installer executed. Actual
  fresh install, upgrade, rollback and uninstall remain NOT_RUN.
- Ruff checks for the new harness, renderer and regression-test files passed;
  `git diff --check` passed before the snapshot.
- Installed personal connector status remained disconnected, authentication revoked,
  live integration disabled and provider approval NOT_ASSESSED. No reconnect,
  personal import, migration, credential refresh, approval or service restart occurred.
  The [final status receipt](stress-blocked-live-2026-10-29.json) rechecks this
  boundary at 01:16 UTC on October 30 (October 29 local time). The new installed
  renderer behavior was not tested or activated by this task.

The complete imported corpus finished in 174.03 seconds: **70 PASS, 2 FAIL,
1 BLOCKED**, with `source_unchanged_during_run=true` and the fingerprint above.
Both previously blocked AI-19 and VI-08 passed; OP-07 is the sole blocked case.
All 47 supplied stress fixture/gold files match the prior accepted hashes.

Two regressions are present in this snapshot of concurrent in-progress work:

- **AI-14:** `get_integrity_guidance` returns a minimized permission-denied error
  (`EGRESS_ERROR_REDACTED`) instead of the expected decision. It does not release
  source content or grant instructor permission.
- **DP-01:** participation returns `partial_data`, `request_unavailable` and zero
  verified entries instead of the fixture's one post and one reply. Coverage says
  incomplete; zero is not treated as proof of nonparticipation.

The separate full suite completed: **1,946 passed, 31 failed, 29 skipped** in
1,154.90 seconds, with `complete_selection=true`, `source_unchanged=true`,
`interrupted=false` and exit code 1. Its `reviewed-source-v1` digest is
`c9733472b0f6a3f634114ad1f3719ac654410fbe5ee86ce2ec2686de81040209`.
All **12 new rendering/UI regression cases passed** within that run. The 31
broader failures cover migration, authorization, discussion pagination, egress,
identity/OAuth and personal-import paths. This snapshot is not a full-suite pass.

A focused diagnostic reproduction
confirmed four failures outside the new rendering/UI tests: a migration downgrade
now stops at the financial-history guard before the expected plaintext guard;
retry authorization sends no request where one is expected; the tool registry
expects `run_local_study_workflow` but it is not exposed; and the download test's
course-access check is incomplete. These are recorded, not bypassed or hidden.

The implementation and boundaries are described in
[the case report](../../docs/stress-blocked-cases-2026-10-29.md).

Retained evidence: [synthetic verification bundle](../../.local/stress-blocked-final-2026-10-29.zip),
[full-suite failure list](../../.local/stress-blocked-final-2026-10-29/full-suite-failures.json),
and [disposable recovery kit](../../.local/CanvasBridge-Disposable-Recovery-Kit-2026-10-29.zip).
The verification bundle includes per-case receipts, original delivered PNGs,
hash-bound observations, the human UI receipt, source manifests, full-suite
outcomes and checksums. It excludes UI launch capabilities, keys and databases.
