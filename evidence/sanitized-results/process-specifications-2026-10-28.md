# Academic process specifications — local verification, October 28, 2026

## Scope

Implemented the supplied CB-01 through CB-17 process contracts in the
`canvas_bridge.processes` package and integrated their source authorization,
recipient egress, integrity, encrypted persistence, revocation and retention paths
with the existing Bridge. The source archive is recorded under
`docs/process-specifications/source/manifest.json`. Those Markdown files are
requirements data, not authorization to run document instructions.

See [implementation and operating boundaries](../../docs/process-specifications/implementation.md)
for the per-specification delivery map, tool catalog, storage format and limits.

## Executed checks

All commands used the repository `.venv` Python on Windows with synthetic fixtures.
No real coursework was used in these tests.

| Check | Actual result |
|---|---|
| Initial full pytest run | 1,693 passed, 28 skipped, 1 warning; before this implementation and concurrent additions |
| Broader process/deletion/retention/recovery check | 110 passed |
| Final process/service plus account deletion, retention, service security and recovery check | 104 passed in 34.83 seconds |
| Full regression run during shared-checkout development | 1,828 passed, 3 failed, 28 skipped in 687.47 seconds; source changed during the run |
| Current independent-intelligence file rerun | 18 passed in 17.63 seconds, including the three cases that failed in the full run |
| Final process acceptance selection | 58 passed in 7.25 seconds; all six process test modules, no deselection; unchanged source fingerprint |
| Process evaluation gate | Passed: all 47 test functions (58 parameterized executions), all 17 specifications represented, zero blocking reasons |
| Ruff lint on `src` and `tests` | Passed at verification time |
| Ruff formatting on new process code/tests and PostgreSQL process case | 29 files already formatted |
| Bandit on `src/canvas_bridge/processes` | No findings |
| `git diff --check` | Passed |
| New PostgreSQL revocation/correction race case | Skipped locally: no disposable `TEST_DATABASE_URL`; included in CI's PostgreSQL selection |

The full run's failures were the three parameterizations of
`test_saved_local_preferences_do_not_need_active_lms`, with MCP token validation
errors in a test file being changed concurrently. The current file passes all 18
tests on rerun. The long full run is **not** a clean, immutable-source acceptance
receipt. Process checks were repeated after final edits, and their gate was checked
against the current source fingerprint. Do not combine those facts into a claim
that the final full suite was rerun successfully.

An earlier process receipt passed when created but was subsequently rejected with
`SOURCE_CHANGED` after concurrent edits. The final process receipt was regenerated
and passed. The [aggregate gate report](process-specifications-2026-10-28.json)
records the exact accepted source fingerprint; it contains no captured logs or
academic payloads. Later repository changes invalidate its claim to currentness.

The repository-wide formatting check identified concurrent edits in `app.py` and
`domain.py`; no repository-wide formatting pass is claimed. The process package
and its new tests pass formatting independently.

## Important regression evidence

- Exact sources and current recipient permissions are checked before output and
  before commit; account-generation and source-version races deny stale changes.
- Genuine HTTP MCP calls cover the process catalog, request schemas, evaluations,
  preview/confirm, inventory, impacts, JSON/Markdown export and support preview.
- Dependent plans become stale after material changes and can be repaired from
  fresh evidence. Cosmetic title changes leave unaffected plans usable.
- Deadline corrections remain reviewable without existing dependents. Historical
  values whose source versions cannot be released are withheld.
- Atomic rollback, replay conflicts, concurrent file-backed SQLite commits and a
  saturated history/receipt journal are covered. Full journals do not prevent
  correction or deletion; old preview versions cannot replay mutations.
- Source deletion, disconnect and retention remove dependent payloads/history/
  previews while preserving unrelated imports. Mutating hooks use the existing
  principal-before-connection lock order.
- Client candidates cannot assert instructor authority, verified submission,
  official degree completion or publication clearance. Imported instructions never
  grant tool capabilities. Missing coverage remains missing.

## Not established by this record

No private configuration, credentials, live database or installed service was
changed. No deployment, restart, push, release or installed ChatGPT acceptance was
performed. `BRIDGE_PROCESS_FEATURES_ENABLED` remains false by default.

PostgreSQL execution, Linux sandbox checks, native converter execution and operator
OCR require their own environments. Their skips are not passes. Synthetic tests do
not establish model interpretation accuracy, extraction precision/recall,
institutional approval, distribution approval or production recovery.

Portfolio review returns a hold through the public adapter until a trusted rights
review is configured. Its internal clearance/export contract is tested; no live
review registry or public publishing transport is installed. Degree projections
remain unofficial. No messaging, submission, calendar writing or autonomous
monitoring is activated.
