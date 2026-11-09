# Private library local implementation and verification

Specification archive SHA-256:
`3c24540cf3e174bf90663688386ee95f279bae6d65cb50734f085e07c76a3505`.
Base checkout: `5bd086356e730b01b5a9f1be9de106446ef049c6`; the checkout already
contained unrelated uncommitted work. No commit, deployment, personal database
migration, real academic-record import or LMS request was performed.

## Delivered scope

L0 inventory/contract reconciliation and the local L1 durable foundation/useful
library are implemented. L1 operational acceptance is partial. L2 native host
handoff and L3 audio/video are explicitly absent/disabled. See the
[implementation and configuration guide](../../docs/private-media-library.md).

The local implementation includes owner-qualified encrypted metadata, encrypted
original chunks outside SQL, reservations, resumable authenticated upload,
structural quarantine scanning, durable version publication, separate grants,
queued existing parsers, bounded cited read/search, sanitized images, immutable
replacement history, owner downloads/ranges/export, deletion journals, explicit
legacy-copy migration, and separate encrypted operator backup/restore. Existing
independent readers/study tools use immutable `lib_` identities through the shared
evidence/authorization core. SQLite child constraints and PostgreSQL composite
foreign keys are installed by additive migration `a28e70b915cd`. Destructive
downgrade is refused.

## Executed checks

All fixture files were fictional. Commands used `.venv\Scripts\python` on Windows,
Python 3.14, with disposable SQLite databases, temporary encrypted object stores
and synthetic verified identities. Most fault tests substitute deterministic
scanner/parser functions; the actual-worker test and visible demo use the real
Windows AppContainer runtime. Those are separate evidence classes.

| Check | Actual result |
|---|---|
| Full `pytest -q --disable-warnings --maxfail=8` | 2,086 passed, 30 skipped, 3 failed in 1,010.61 seconds; failures diagnosed below |
| Final library + three corrected contract cases | 46 passed in 54.38 seconds (43 library cases plus three corrected contracts) |
| `ruff check src tests scripts migrations --output-format concise` | Passed |
| `ruff format --check src tests scripts migrations` | Passed, 396 files |
| Repository Bandit gate: `bandit -r src -ll -ii -q` | Passed |
| `canvas-bridge compliance-report --validate-only` | Registry valid; 30 controls; no authorization granted |
| `git diff --check` | Passed (line-ending normalization warnings only) |

The full suite's three failures were compatibility assertions: the feature-gated
MCP inventory expected disabled library tools, and two legacy downgrade checks
expected only the older plaintext-protection error. The new library downgrade
barrier correctly stopped those operations first. Tests now account for the
flag and either protective barrier, retaining the data-preservation assertions.
A fresh full suite was not repeated after these assertion-only changes. Library
refinements made during the longer full run were covered by the final focused run.
No unresolved failing case is represented as a pass. Final review also repaired
a search race: captured snippets retain their original source/representation/grant
fences; revocation cannot convert them into an unreferenced status response. A
regression injects revocation immediately after representation read.

An additional unfiltered Bandit probe reported the trusted schema-generated
SQLite DDL (medium severity, low confidence) and fixed Windows ACL identity utility
(low severity). These were reviewed: identifiers come exclusively from internal
SQLAlchemy models, and the utility is an absolute OS executable invoked without a
shell or user arguments. The repository's medium-severity/medium-confidence gate
passes; the broader probe was not reported as clean.

The 30 skips require PostgreSQL, Linux, explicit native converters or OCR runtimes.
Docker, Podman and psql were not available locally. No hosted result is inferred
from SQLite or thread-concurrency results.

## Visible local browser evidence

The disposable demo's normal settings flow was used in an isolated Webcmd session:
visible synthetic sign-in, select fictional TXT, review storage/processing/sharing,
upload, observe publication receipt and later `ready`, download, rename, revoke,
and delete. No authentication state was injected into the browser.

Downloaded original: **63 bytes**, SHA-256
`4621ec392af36668f1ffbd95352a33c014b8107509be04c86d10df76320c7bce`.
Revocation displayed `not_requested`; deletion reported access disabled and active
store purged, with zero remaining file links. At 390 × 844 CSS pixels there was no
horizontal overflow. The full-page [mobile capture](private-library/library-mobile.png)
was visually inspected. [Sanitized observations](private-library/browser.json)
record the flow and limits. The agent browser session was closed and disposable
demo stopped. The screenshot shows an earlier revision of this same local UI;
final receipt/search/scanner refinements were verified in automated tests.

This is local browser proof, not an installed ChatGPT/Claude client, host file
picker, native attachment transfer, screen-reader study or model observation of
source pixels. HTTP coverage for PDF, DOCX, PPTX, XLSX, TXT, PNG and JPEG uses
ASGI requests through the actual authenticated routes. Only TXT was selected
through the visible browser. Embedded chart XLSX packages are recursively checked;
a hidden macro payload remains rejected. Larger safe originals retain exact bytes
when processing exceeds the existing parser ceiling.

## Acceptance and remaining release work

[Acceptance ledger](private-library/acceptance.csv) maps all 36 cases to actual
probes and explicitly records partial, blocked and unrun clauses. A test name does
not establish every clause of its source case. The [24-requirement ledger](private-library/requirements.csv)
separates delivery from verification; `synthetic_pass` means the listed local
checks passed, not full deployment acceptance. [Source hashes](private-library/source-hashes.json)
bind this historical report to the October implementation and integration files.
Later shared-module changes require their own current-worktree verification.

Required remaining work before broader claims or operational release:

- A hosted private-bucket adapter, real PostgreSQL multiworker acceptance,
  distributed ingress/load and storage-outage/crash rehearsals.
- The 1,000-item reference deployment and p95 targets; deployment-wide derivative,
  export/backup capacity planning and operational alerting/backup lifecycle.
- Full archive/polyglot/adversarial logging and commit-boundary fault matrices;
  complete keyboard/screen-reader acceptance and a second-owner browser pilot.
- Exact supported real-client upload fallback, later-chat retrieval, download and
  image-delivery/observation evidence. L2 requires a verified supported host API;
  arbitrary URL intake is absent. L3 requires separate codec/privacy/processing work.
- Physical backup deletion verification. The thirty-day horizon limits restore
  eligibility; it does not prove deletion from operator storage or external copies.

No gate above is waived by a passing local test. The library remains off by default;
this record does not authorize public release or institutional access.
