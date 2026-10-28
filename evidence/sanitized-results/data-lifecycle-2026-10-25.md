# Data lifecycle controls — local synthetic validation

Date: October 25, 2026. Windows source checkout. This record covers the P1
Data Lifecycle, Retention & Deletion Controls specification following the
authorization, egress and identity work in this session.

No real Canvas call, approval, credential, course selection or academic record
was changed. No private service/database migration, restart, deployment, commit
or publication was performed. Fixtures and migration/backup canaries are synthetic.

## Implemented boundaries

* Central class descriptions and expiry budgets, authenticated local storage
  inventory, expired-analysis read exclusion, startup/periodic/worker/CLI cleanup.
* Existing-vault AES-GCM field encryption plus populated-data migration; plaintext
  downgrade blocked. New Windows vault keys use DPAPI; legacy keys are supported.
* Authenticated Settings confirmation, CSRF/same-origin/settings-scope checks and
  owner/generation/connection locks for cache and academic-record deletion. No
  deletion MCP tool. Deleted row counts and pending cleanup are reported.
* Per-download memory-only encryption keys, authenticated chunk integrity,
  cancellation of in-flight preparation, active-transfer revocation and bounded
  download grants. Original plaintext bytes and client hashes are preserved.
* Leased worker workspaces, namespace-bound cancellation, safe directory-identity
  handling on Windows, pending-cleanup reporting, AppContainer profile disposal
  and deterministic orphan recovery. Untrusted paths are not deletion targets.
* Backups exclude credentials, sessions, jobs, raw document text and rolled-back
  DB fence copies. Restore requires a current authenticated independent journal,
  an empty migrated target and an unexpired format-2 backup, preserves record
  expiry, and leaves restored connections inactive/unverified without credentials.
* Seven-day process-local receipts, 31-day obsolete restoration-fence cleanup,
  accurate upstream-revocation uncertainty and downstream/backup limitations.

## Actual checks

The preceding identity validation supplied the baseline; a redundant opening
full-suite run was not performed.

| Check | Result |
|---|---|
| Final focused lifecycle + PDF regression checks | **44 passed**, 24.29 seconds |
| Original delivery + lifecycle/account checks before final worker isolation adjustment | **84 passed**, 32.22 seconds |
| Complete regression suite after final changes | **1,149 passed, 27 skipped**, 429.91 seconds; no failures |
| Ruff over source, tests and migrations | Passed |
| Formatting check for 34 affected source/test/migration files | Passed |
| `git diff --check` | Passed; existing Windows line-ending normalization notices are not whitespace failures |

An earlier complete run found five failures: a journal test double missing the
new clock keyword, two Windows workspace alias/invalid-path cases, and two
pending-cleanup assertions affected by shared worker accounting between separate
service instances. The implementation/test-double fixes passed focused checks;
the final complete run is recorded above separately. Failed initial checks are
not represented as passed evidence.

The lifecycle fixtures exercise encrypted SQLite migration including JSON
roundtrips; cross-key denial; credential-field rejection in academic caches;
expired analysis and raw documents; operator-shortened file retention; connection
expiry; owner/generation/confirmation boundaries; DB row deletion; failed and
interrupted processing; orphan leases and cleanup retry; concurrent deletion and
file access; active and in-flight download invalidation; encrypted chunk integrity;
OS key protection; backup expiry/legacy rejection; restoration fences; retained
record expiry after restore; and inactive credential-free restoration.
There are 27 new lifecycle cases in `tests/test_retention.py`; none were skipped.

Existing file-delivery tests cover exact original-byte delivery, source/hash
changes, redirects, disabled access, TTL/clock changes, failure cleanup, concurrent
quotas and HTTP/embedded-resource boundaries. Existing approval, egress, identity,
offline academic, PDF, PPTX and MCP tests remain part of the complete suite.

## Limits of the evidence

The actual PostgreSQL migration/locking job, Linux kernel isolation, optional
native conversion/OCR configurations and deployed browser/service behavior need
their environment-specific checks. Local synthetic HTTP tests do not establish
installed ChatGPT connector acceptance.

Raw native-worker files require an encrypted protected host volume. Field-level
encryption and logical deletion do not certify physical erasure from old DB
pages, WAL, swap, crash dumps, immutable backups or user downloads. External log
retention, physical backup expiry, independent journal recovery and administrator
approval-evidence disposal remain operator release gates. No service or evidence
custodian's real storage policy was changed by this local implementation.

Activation requires migration `c7d9130b42ae` with the existing vault key and stopped
service/workers; it was tested only on disposable synthetic databases. Format-1
backups cannot be restored by the new restore command. Review
[Data lifecycle controls](../../docs/data-lifecycle-controls.md) and
[release gates](../release-gates.md) before activation.
