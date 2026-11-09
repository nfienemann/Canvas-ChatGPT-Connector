# U01–U06 development verification — October 29, 2026

Scope: six independent-source journeys from the supplied specification archive.
Implementation and controls: [implementation notes](../../docs/usefulness/implementation.md).
This is local development evidence, not an installed-client, deployment, provider
approval, public-release or learning-efficacy claim. The shared checkout contained
other work; those changes were preserved. No commit, push, personal-service restart,
production migration or live-provider call was performed for this implementation.

## Execution record

Runtime: Windows, Python 3.14.5, local SQLite fixtures. The checkout started its
recorded runs at `5bd086356e730b01b5a9f1be9de106446ef049c6` with uncommitted changes.
No active institutional connection is needed by these workflows. New integration
fixtures replace the provider client with a failing tripwire.

Recorded checks ([machine-readable summary](usefulness-2026-10-29.json)):

- Initial full run: **2,031 passed, 10 failed, 30 skipped in 1,233.61 seconds**.
  The run overlapped source changes and is not a final-source whole-suite certificate.
  The skipped cases require Linux, disposable PostgreSQL, native conversion or OCR.
- Final targeted run: **79 passed in 68.28 seconds**, with the source unchanged
  throughout. This includes **all 64 usefulness/benchmark checks** and every case
  group that failed in the initial full run. No failures remain in that final
  selection. This does not convert skips into passes or claim a second full run.
  After that receipt, concurrent edits to four private-media-library specification
  documents changed the whole-checkout fingerprint. Their paths and the handoff
  fingerprint are recorded in the JSON summary; this is not a release certificate
  for those subsequent documents.
- The final positive HTTP MCP journey verifies obligations, feedback and change
  events through normal transport output, in addition to the earlier resume test.

- Compatibility run: **132 passed in 83.68 seconds** across usefulness, benchmark,
  independent intelligence, process service and recovery-independence tests.
  The source recorder marked this run changed because the desktop build resource
  list was amended while the run was active; this receipt is not a whole-checkout
  source-bound release certificate.
- Scope/egress compatibility: **113 passed**. Compliance rerun: **27 passed**.
  Earlier focused runs passed 118, 55 and 56 cases
  as functionality was added. One later run completed its test bodies but could
  not write its receipt because the destination already existed; it was rerun
  using a fresh output path, not treated as a successful recorder run.
- Ruff lint and formatting passed for the new package, tests, benchmark script
  and desktop resource-list change.
- Browser: real signed settings UI in a disposable local synthetic instance,
  with the existing isolated parser enabled and provider client set to fail.
  File-picker import of a fictional syllabus completed with 1 completed / 0 failed.
  Candidate edit/requirement/effort survived save and reload. Explicit goal and
  attempt saves worked with MCP read-only; the incomplete control explanation
  displayed **incomplete**, with no mastery claim. Desktop and 390-pixel mobile
  screenshots were visually inspected. Mobile document scroll width was 390.
  [Desktop](usefulness-ui/review-desktop.png) · [Mobile](usefulness-ui/review-mobile.png).
- Packaging: the new import script is explicitly included in the desktop build
  resource list. A wheel build was not executed successfully: this shell lacks
  `uv` and an executable Python `build` installation. No packaged-binary claim.

The broad run overlapped implementation edits. Compliance tests intentionally
reject source fingerprints that change during a test; a separate diagnostic run
reproduced that reason (`STALE` instead of `PASSED`). Final outcomes are listed
in the JSON summary. The initial discussion/usage cases passed against the current
concurrently updated checkout; usefulness work did not alter those tests or weaken
governor rules. No test was relaxed to accept stale source evidence.

Commands (from the repository environment):

```text
python -m pytest -q -p canvas_bridge.compliance.pytest_plugin --compliance-results .local/usefulness-full.json
python -m pytest -q tests/test_usefulness.py tests/test_usefulness_benchmark.py tests/test_independent_intelligence.py tests/test_process_service.py tests/test_recovery_independence.py -p canvas_bridge.compliance.pytest_plugin --compliance-results .local/usefulness-final-focused.json
python -m pytest -q tests/test_usefulness.py tests/test_usefulness_benchmark.py -p canvas_bridge.compliance.pytest_plugin --compliance-results .local/usefulness-final-61.json
python -m pytest -q tests/test_usefulness.py tests/test_usefulness_benchmark.py tests/test_independent_intelligence.py tests/test_egress_contract.py -p canvas_bridge.compliance.pytest_plugin --compliance-results .local/usefulness-final-scope.json
python scripts/benchmark_usefulness.py --output .local/usefulness-search-benchmark.json
```

The final rerun selected all usefulness tests plus every failed base-case ID from
`.local/usefulness-full.json`; its fresh receipt is `.local/usefulness-final-retries.json`.
Full test IDs, counts, source hashes and source-change flags are retained in the
machine-readable summary. Seven supplied Markdown files were rechecked against
their original byte lengths and SHA-256 manifest values.

## Retrieval and obligation fixtures

The retrieval corpus was frozen before its first measured comparison. It contains
20 fictional documents in TXT, Markdown, DOCX, PPTX and PDF, 40 queries, separate
gold answers and checked SHA-256 fingerprints. The same actual parser and ranker
were used for both modes; parser execution here is in-process, with isolated
browser extraction verified separately. No mapping tuning followed a failed query.

| Query class | Count | Literal success | Conceptual success |
|---|---:|---:|---:|
| Exact | 10 | 10 | 10 |
| Paraphrase | 12 | 0 | 12 |
| Acronym | 6 | 0 | 6 |
| Course disambiguation | 6 | 6 | 6 |
| Unanswerable, no match | 6 | 6 | 6 |

Answerable evidence in top five: **34/34 conceptual, 16/34 literal**. The proposed
29/34 threshold passed. Warm 20-document ranker p95 was **0.753 ms**; the separate
100-document ranker-only scaling sample p95 was **2.779 ms**, concurrency one.
These small-corpus timings exclude authentication, egress, extraction and host
latency. The service owner cap remains twenty documents. The hand-authored corpus
has not received independent expert or first-time-student review.

Twelve frozen fictional obligation scenarios check required, optional, unclear,
chosen, submitted, graded, excused, revision-required, student-marked-done,
unassigned group responsibility, unknown submission and two-of-three selection.
They preserve unknown official state and compare the new filters with the earlier
generic actionability logic. This is fixture coverage, not university-wide recall.

## Numbered acceptance coverage

“Covered” below means the stated automated slice was executed, not that every
sentence of the source case or every environment has been accepted. The 47 source
case IDs are preserved in the source manifest. Tests are in `test_usefulness.py`,
with frozen benchmarks in `test_usefulness_benchmark.py`; broader parser, integrity,
egress and lifecycle regressions remain part of the full suite.

| Cases | Executed slice | Remaining boundary |
|---|---|---|
| U01-A1 | Authenticated TXT upload/review → HTTP MCP planning and exact reading locator; real file-picker/parser browser proof | Multi-format first-time-user journey and actual ChatGPT host acceptance |
| U01-A2 | Explicit/TBD dates, conflicting counts, typed percentage/count candidates, review-only normalized dataset | General document understanding and complete grade-policy extraction |
| U01-A3 | All seven no-source workflow calls through HTTP MCP; true sharing denial remains denial | None claimed beyond the tested transport |
| U01-A4 | Dedup without rights escalation, cross-course separation, replacement/current-version CAS | Multiworker PostgreSQL race acceptance |
| U01-A5 | Traversal, absolute path, symlink, collision, nested archive, bomb, false MIME and safe ZIP | Broader active-content/container evidence is inherited from parser regressions |
| U01-A6 | Local preview without sharing, foreign owner, no institution required; final source/egress rechecks | Real institutional provenance/rights approval is outside this baseline |
| U01-A7 | Cancel states, source deletion, actual restart and backup/restore exclusion | Crashed-worker recovery across all deployment topologies |
| U02-A1, A4 | Distinct activity kinds/parents; student assertions stay distinct from official unknown; revision remains actionable | Live provider-specific activity normalization |
| U02-A2, A3 | Two-of-three group, independent grading rule, alias/parent validation; no title merge; long keys retain identity | Cross-document mapping UI beyond explicit reviewed identities |
| U02-A5 | Date-only and ambiguous dates stay non-invented; explicit open/close fields | Full institution-specific precedence and timezone scenarios |
| U02-A6, A7 | Failed selected source retains permitted work; continuation plus entire-inventory accounting; capacity, unknown effort and cycles | Representative large-course end-to-end scale |
| U02-A8 | Foreign/stale checks and one winner under real SQLite concurrent revision writes | PostgreSQL concurrency |
| U03-A1, A2 | Exact own-feedback passage, provisional improvement and separate ungraded task; score stays unknown | Authenticating instructor authorship from a student-provided copy |
| U03-A3, A4 | Duplicate comment is not a trend; distinct works/counterexample; forged quote rejected | Independent quality evaluation of host interpretations |
| U03-A5, A6 | Existing integrity/egress route retained; private feedback withheld from serialized channels | All assignment-specific assessment policies and real-host channels |
| U03-A7, A8 | No profile on read; explicit UI save path; deterministic check distinguishes missing explanation; no mastery | Student learning outcomes |
| U04-A1–A3 | Frozen lexical benchmark, acronym/course scope, literal compatibility, original Unicode offsets and negation | Held-out representative corpus |
| U04-A4 | Caption candidates explicitly do not establish unseen pixel values | Visual interpretation accuracy |
| U04-A5–A8 | Owner/scope/version/delete checks, forged cursor rejection, deterministic bounded ranking, no provider calls | Host end-to-end latency; no vectors or external index are implemented |
| U05-A1–A3 | Goal/attempt save, retry, rejection, versioned correction; actual restart and fresh HTTP MCP resume | Actual ChatGPT-host session behavior |
| U05-A4, A5 | Course/owner separation, dependent source deletion, unrelated goal retained; corrections preserve lineage | Source-dependent continuity beyond source retention |
| U05-A6–A8 | Collection disable vs deletion, real backup restore excludes independent state, bounded five-minute resume, authenticated read-only-deployment UI | Full user pilot and all host-specific UI paths |
| U06-A1, A2 | Earlier deadline old/new citations, affected plan, no writes; repeated read same ID; change-back new ID | Live schedule refresh remains disabled |
| U06-A3, A4 | Baseline-only state, disappeared item not deletion, semantic processing-only changes, precision uncertainty | Arbitrary conflicting-document authority cannot be resolved automatically |
| U06-A5, A6 | Read does not acknowledge; versioned snooze/retry/expiry; revoked data withheld | No pending notification channel exists |
| U06-A7, A8 | Restart reconstructs same transition identity; source deletion and backup exclusion | Delivery receipts, quiet hours/DST and uncertain sends are conditional, not implemented |

## Disposition

The implementation preserves the requested independent baseline and local mutation
boundary. Pilot targets, installed-host behavior, platform packaging, PostgreSQL
and live-provider expansion remain explicitly unverified. New usefulness workflows
default off. No deployment setting, personal credentials or approval state was changed.
The disposable browser server and session were closed after inspection.
