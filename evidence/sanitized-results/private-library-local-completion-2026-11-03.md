# Private library local completion - November 3, 2026

This record covers the remaining locally implementable L1 work requested after the
earlier November 3 compatibility retest. Default-off behavior is preserved. All
fixtures are synthetic; no personal database/service, institution connection or
public deployment was changed. The checkout includes unrelated concurrent work.

## Changes verified

Shared database ingress/export/backup leases, aggregate export-memory admission,
deployment derivative capacity, bounded export construction and disconnect cleanup;
managed encrypted backups with authenticated part verification and physical expiry;
content-free metrics/health and maintenance commands; safe missing-volume handling;
failed-extraction retry with unchanged grants; title/tag/collection filtering,
keyboard/error focus, disabled-input restoration and live storage totals. Backup
copy/restore use the object-store interface, leaving vendor-specific implementation
explicitly deferred. Flat-archive and image-carrier rejection were strengthened.

Migration head for these operations is `b39f81ca26de`, after `a28e70b915cd` and
`f17a6b204c31`. It adds operation leases, aggregate counters and managed backup
records. Downgrade cannot discard durable originals. Configuration/operations and
external prerequisites are in [the implementation guide](../../docs/private-media-library.md)
and [the canonical release checklist](../../docs/private-library-release-checklist.md).

## Executed focused checks

Windows, Python 3.14, disposable SQLite and local encrypted objects:

```text
python -m pytest -q tests/test_private_library.py tests/test_private_library_boundaries.py tests/test_library_operations.py tests/test_library_postgres.py --disable-warnings --maxfail=3
```

66 passed, 1 skipped in 82.77 seconds at the intermediate checkpoint. The skipped
case requires `TEST_DATABASE_URL` naming a disposable PostgreSQL database.
Neither Docker nor PostgreSQL executables were found on the current command path.

After backup health/integrity and extraction-retry additions:

```text
python -m pytest -q tests/test_library_operations.py --disable-warnings --maxfail=2
```

26 passed in 17.28 seconds. These include eight quota admissions across four
separate SQLite processes, shared ingress leases, export close/expiry, derivative
capacity, private diagnostics, purge outage/reconciliation, managed backup capacity
and expiry, ciphertext alteration with valid ZIP CRC, wrong recovery key, duplicate
workers, storage-before-commit faults, hostile archive/image carriers, untrusted
source instructions, authenticated second-owner HTTP denial and filtered cursors.

```text
python -m pytest -q tests/test_library_crash.py --disable-warnings --maxfail=1
```

2 passed in 10.37 seconds. Each real child process exits abruptly with code 91 after
the durable chunk or publication write and before SQL commit. Recovery rolls back
metadata, expires the crashed publication lease when necessary, returns the same
receipt on retry and retains exactly one exact original with zero accounting drift.
The structural scanner is deterministic inside these persistence-fault children;
these tests do not certify the OS sandbox.

After final UI edits, all seven parameterized authenticated upload/download format
checks passed in 10.57 seconds:

```text
python -m pytest -q tests/test_private_library.py::test_http_browser_upload_csrf_and_original --disable-warnings --maxfail=1
```

## Browser and load evidence

The disposable loopback demo used visible synthetic sign-in and real Windows
structural validation. Keyboard submission, one aborted chunk request, same-receipt
retry, cancellation of two unfinished files while preserving an existing original,
metadata editing, title/tag/collection filtering, focus/error status, exact original
download and deletion passed. The final UI updates quota from 0 to 33 bytes after
upload and back to 0 after deletion, with per-file purpose controls enabled. At
390 x 844 the document has no horizontal overflow. The screenshot was inspected.

The downloaded 44-byte fixture matched SHA-256
`bcc15151ca4c2dc3168d97a89abdb4152c1b99db829a1c92d13a26b255658866`.
See [browser evidence](private-library/browser-completion-2026-11-03.json) and
[mobile screenshot](private-library/library-completion-mobile.png). Some combined
Webcmd actions timed out; the actual resulting state was inspected before any
retry, and the final download was captured separately and compared byte-for-byte.
The named browser session and disposable demo were stopped afterward. This is not
screen-reader or ChatGPT/Claude host acceptance.

```text
python scripts/benchmark_library.py --output evidence/sanitized-results/private-library/local-load-2026-11-03.json
```

The [reference benchmark](private-library/local-load-2026-11-03.json) uses 1,000
encrypted originals and parsed text representations, concurrency 1 and 20 samples
per operation. p95 listing: 0.278288 s (target 2); bounded search: 1.053561 s
(target 3); finalization after validation: 0.102739 s (target 2). All stored hashes
verified, zero accounting drift, zero upstream requests. OS scanner startup,
end-to-end extraction and network/host throughput are excluded explicitly.

## Verification boundaries

The source specification package is unchanged. The implementation ledger contains
all 24 requirements and 36 acceptance cases, with existing test names validated.
The full-suite results below include a shared-checkout run; the two abrupt-crash
tests were added after its collection and ran separately. Final UI changes also
received the separate seven-format HTTP run and real-browser confirmation.

Local passes do not close PostgreSQL, hosted object-store/recovery, exact-client,
assistive-technology, deployment-platform or public approval gates. L2 native host
intake and L3 audio/video/broader archives are explicit unimplemented future slices.
Manual backup files outside the managed root retain an operator physical-lifecycle
gate. No result is attributed to another running test process.


## Supporting checks and cleanup

- Ruff check passed for `src tests scripts migrations`; formatting passed for 411
  files after the final changes (the shared checkout also contains other work).
- `python -m canvas_bridge.compliance.checks bandit --output .local/private-library-bandit.json`:
  project-configured security check PASSED. An earlier bare Bandit invocation
  omitted the project's configuration and returned its default findings; that
  invocation is not represented as a clean pass.
- `python -m canvas_bridge.cli compliance-report --validate-only`: valid registry,
  30 controls, no authorization granted. An earlier guessed process-registry module
  name did not exist; this is the actual supported validation command.
- `git diff --check`: passed, with existing line-ending normalization warnings.
- Both implementation ledgers parse with unique IDs and existing test references;
  links in the new guide/checklist/evidence record resolve.
- The new retry endpoint was added to the authenticated second-owner HTTP matrix:
  one focused test passed in 2.83 seconds, returning the same safe 404 denial.
- [Source hashes](private-library/source-hashes-local-completion-2026-11-03.json)
  cover 49 implementation, integration, migration, benchmark and test files. This
  is a dirty-worktree snapshot, not a commit or deployed-build attestation.

The local browser session and both demo servers are stopped; port 8769 is no
longer listening. The final demo cleaned up on shutdown. Automatic approval review
rejected recursive cleanup of the earlier disposable synthetic directory
`%TEMP%/bridge-library-demo-yz1hrg4r` with "blocked by policy". That fixture folder
remains outside the repository; no cleanup bypass or private-data deletion was
attempted. An older unrelated demo directory was left untouched.


## Full regression result

```text
python -m pytest -q --disable-warnings --maxfail=5 --junitxml=.local/private-library-local-completion-tests.xml
```

**2,187 passed, 31 skipped, zero failures/errors in 1,278.31 seconds (21:18).**
The skips are 11 disposable PostgreSQL cases, 13 Linux-kernel cases, five trusted
native-converter cases and two operator OCR cases. They remain unverified in this
environment. The raw JUnit output stays in ignored `.local`; the
[sanitized aggregate](private-library/full-suite-local-completion-2026-11-03.json)
records counts, commands, supplemental runs and boundaries.

The two abrupt-process-exit tests were collected and passed separately, as were
the final seven-format HTTP checks and added second-owner retry-route denial.
Final browser checks verified both UI fixes. A concurrent change to the shared
`egress_sources.py` appeared during the final audit. It was preserved, with the
original snapshot retained and a separate final source snapshot and integration
run recorded below. The full-suite result is not attributed to that later revision.


## Final shared-module integration check

```text
python -m pytest -q tests/test_egress_contract.py tests/test_private_library.py::test_real_mcp_serialized_metadata_text_and_legacy_adapter tests/test_private_library_boundaries.py::test_study_adapter_and_exact_image_preview --disable-warnings --maxfail=2 --junitxml=.local/private-library-final-egress-tests.xml
```

**13 passed in 61.56 seconds**, including actual MCP serialization, legacy/study
adapter, image preview and egress contract checks against the preserved concurrent
shared-module edit. [Final source hashes](private-library/source-hashes-local-completion-final-2026-11-03.json)
cover the same 49 files and record `egress_sources.py` as the sole change since the
previous completion snapshot. All 49 hashes remained unchanged through this final
integration run. The final UI changes are covered by the separately recorded HTTP and browser
checks above. No second redundant full-suite run was made.
