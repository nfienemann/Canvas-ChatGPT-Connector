# Recursive validation â€” November 3, 2026

Status: **AUTOMATED VALIDATION COMPLETE; FULL LIVE ACCEPTANCE BLOCKED.** This report separates
source-level tests, synthetic native execution and installed-connector evidence.
After the full Python runs, concurrent work added a JavaScript PNG audit runtime.
Follow-up validation passed 49 Node tests. Its `fflate` dependency was upgraded
from 0.8.2 to 0.8.3 after an audit finding; the final runtime audit reports zero
vulnerabilities. The advisory concerns `unzipSync`, which this PNG path does not
invoke; no exploitability claim is made. CI now installs and audits the runtime,
runs its tests and emits its own SBOM. See the [source-bound follow-up receipt](recursive-validation-2026-11-03-png-followup.json)
and [upstream advisory](https://github.com/advisories/GHSA-px8p-9vwx-vf98).
The earlier full-suite receipts predate these JavaScript/CI changes; no fresh full
Python run was needed for this isolated follow-up, and none is claimed.
This validation performed no Canvas/calendar writes, stored-permission expansion
or approval fabrication. Real resource identifiers and traversal checkpoints are stored outside
the repository under the operator's local CanvasBridge validation directory.

The [capability matrix](recursive-validation-2026-11-03-matrix.md) and its
[JSON companion](recursive-validation-2026-11-03-matrix.json) cover 79 tool
registrations, 53 connected-catalog tools, 44 HTTP routes, 26 allowlisted Canvas
endpoints, 237 Python modules and 1,369 discovered test definitions. Static
references, code execution, live outcomes and semantic verification are distinct.

## Repairs and regression evidence

| Defect | Correction | Regression evidence |
|---|---|---|
| Audit could accept rendered pages from a different source after successful text extraction | Reuse the image/hash/page validation path | Node audit suite: 39 passed |
| Endless unique inventory cursors and empty-folder cycles | Bounded per-run request budget, resumable checkpoint, whole-folder graph cycle detection | Node audit suite: 39 passed |
| Raw MCP transport errors misclassified as malformed application responses | Preserve transport-failure classification without private messages | Node audit suite: 39 passed |
| Local contention looked like provider throttling | Separate local admission and recovery-probe reason codes | Governor and MCP diagnostic regressions |
| Recovery instructions and retry timing were stripped from final responses | Reviewed static guidance plus safe privacy projection | Actual HTTP MCP regressions; live classification and contention responses observed |
| Unexpected exceptions lacked matching client/operator identifiers | Log exception class with the same request ID returned to the client | Request-ID correlation regression; no exception text logged |
| Vulnerable PDF dependency | Pin pypdf 6.21.4 and update lockfile | PDF suite 119 passed, 2 OCR-dependent skips; dependency audit reports no known vulnerabilities |
| Two PostgreSQL fixture defects prevented exercising intended behavior | Use valid preference update and correct source identifier argument | Disposable PostgreSQL: 11 passed |
| Windows path aliases broke acknowledgment-demo source hashing | Resolve the script path before relativizing | Path and guidance regression group: 36 passed |
| Large renderer installation exceeded generic 15-second ACL setup budget | Bounded 90-second allowance only for public Office runtime setup; distinct safe timeout reason | Setup regressions and actual installation completed |
| Renderer disk monitor aborted when LibreOffice removed temporary directories | Tolerate vanished child directories; retain root, link, depth, entry and byte checks | Red/green race regression; native PPTX conversion and tool delivery passed |
| DOCX/XLSX integration clients timed out after five seconds while OS worker remained active | Bounded client read allowance and isolated cold test runtime | Both focused cold-runtime tests passed |
| Final Git metadata timeout replaced the pytest failure summary | Translate subprocess failures into a safe evidence code and retain outcomes with source verification false | Compliance group: 29 passed; verification failure cannot certify a run |

## Executed validation

- First clean comprehensive pass: **2,389 passed, 13 skipped, zero failures** in
  3,081.03 seconds. All skips require a real Linux kernel. The sanitized receipt
  confirms complete selection, exit code zero and unchanged source during the run.
  Raw source fingerprint: `ca0cc16d83e6722c9a956fdf49e1929823bfedcc814c6ff9796b5bd39e1120f0`.
  The tested source is archived privately with its hash manifest.
- Five files changed concurrently after that frozen source was captured: the
  extraction-status MCP boundary, status service, private-content policy, associated
  tests and policy documentation. The second comprehensive pass includes these
  changes, with fingerprint `347c4d526990725e7ad61397ee14fd9d9ca913eb2950d6a60b4a5196f270988e`.
  These are separate source versions; repeatability on identical source must not
  be inferred by combining them. A process evaluation using the first receipt
  against the newer source correctly rejected it as `SOURCE_CHANGED`, despite all
  47 mapped process tests passing in that first run.
- Second clean comprehensive Windows pass: **2,390 passed, 13 Linux-only skips,
  zero failures** in 1,471.72 seconds. Its receipt also confirms complete selection,
  unchanged source and exit code zero. The current process evaluation passes all
  47 mapped cases. There were no newly discovered implementation failures in
  these two consecutive full runs. At that checkpoint, the workspace differed only in
  `docs/course-file-audit.md`; its added text documents the already-tested
  `read(..., {render: false})` option and honest cache-observation boundaries.
- Initial full source suite: **2,288 passed, 31 skipped, 1 failed**. The failure
  was a reproducibility check during concurrent checkout edits; its isolated
  rerun passed. This was not a clean comprehensive pass.
- A detached, unchanged source snapshot completed diagnostic coverage with
  disposable PostgreSQL and OCR: **2,321 passed, 18 skipped, 10 failed**. Statement
  coverage was **86.6%**, separate from resource or semantic coverage. Five failures
  were HTTP client read timeouts; others involved a path alias, a stale assertion,
  a test-only environment variable rejected by the upgrade CLI, and missing
  synthetic benchmark files in the validation snapshot. Repairs were targeted.
- The next snapshot run stopped after **1,127 passed and 1 failed**: a fixture
  assumed the per-file deadline must win over the overall deadline. Freshness,
  retention and bounded concurrency assertions passed. The test now accepts
  either truthful timeout cause while preserving those behavior assertions.
  This failed attempt preceded the two clean Windows runs recorded above.
- Imported synthetic academic corpus: **68 passed, 5 blocked** initially. The
  checkout changed during that run, so it is not stable release evidence.
- Final imported academic corpus: **71 passed, 2 blocked, zero failures** across
  73 cases, with unchanged source during execution. AI-19 requires an actual
  human acknowledgment through the isolated UI; OP-07 requires a disposable OS,
  trusted previous release and controlled interrupted upgrade/rollback evidence.
  Neither was fabricated. The three visual cases passed using actual pixel
  observations bound to the source and image hashes.
- Actual pixel inspection closed the two synthetic PDF visual cases. A separate
  native PPTX case passed after a source/image-hash-bound visual observation.
  The visible values were 50 and 75; the fixture's claim of twice the control is
  contradicted. Variability, sample size and statistical significance are unknown.
- Fast academic benchmark passed its gates. Scientific retrieval benchmark
  accuracy was 1.0; interpretation accuracy was **null**, not a semantic pass.
- Bandit reported no issues at its configured reporting thresholds. Compliance
  validation accepted 30 control records; that does not grant approval.
- Final frozen-source lint and format checks passed. Later JavaScript/CI changes
  received the separate follow-up validation described at the top of this report.

## Live integration boundary

Five selected active-student courses were returned. Historical courses and groups
are not exposed by the implemented policy/API surface and were not silently added.
The local permission audit reported 35 consistent checks; upstream verification
and downstream source release are separate.

| Course ordinal | Inventory state | Discovered references | Qualification |
|---|---|---:|---|
| 1 | Traversal ended | 1 | Access gaps remain |
| 2 | All four branches complete | 43 | 41 PDFs and 2 SVGs; contents not verified |
| 3 | All four branches complete | 0 | No files discovered through exposed branches |
| 4 | Traversal ended; modules complete | 40 | Files/folders/assignment links partial with source-access denials |
| 5 | Traversal ended; modules and assignments complete | 36 | Files and folders partial with explicit Canvas 403 |

All five file-inventory continuations terminated: 120 unique references across
152 resumable steps. This is completion of the permitted traversal, not proof
that inaccessible branches contain no additional resources. The private manifest
is outside the repository and retains opaque identifiers and coverage outcomes.
Eleven retained references in course 4 lack current format/version metadata.
Listing entries generally omit a per-file access state; the manifest records
unknown fields explicitly. Successful listing is not classified as a successful
content read. Only the representative reads described below were verified here.

A PNG text read returned unsupported format. A PDF read, course outline,
obligation discovery and grading-policy request were withheld with
`EGRESS_CLASSIFICATION_UNKNOWN`. The live client received the specific review
requirement and recovery guidance. These are observed failures of content
availability, not passes for parsing, grades, deadlines or academic interpretation.
No review record was invented to bypass them.

Subsequent direct reads under the current owner-authorized private-course grant
succeeded for representative PPTX, XLSX and DOCX inputs. The PPTX returned all 11
slides in two hash-consistent batches; one native rendered slide was actually
inspected and matched its source hash and slide mapping. The XLSX reassembled to
14,037 characters and 150 distinct cell records without duplicate cells. The DOCX
returned all 1,899 text characters, explicitly section-based locators, and a
separate complete 2-row/5-column rubric structure. These checks do not establish
independent original-byte fidelity, scientific comprehension or whole-deck visual
coverage. No assessment answers were generated.

Search and the academic-permission check remained withheld. The current private
content policy explicitly permits direct file reading, rendering and assignment
details; the subsequent extraction-status change adds metadata-only status. It
does not permit search. A live workload request returned 24 items but
only two course assignment branches were complete. Refresh-budget warnings were
being replaced with generic notices; new tests verify safe, actionable coverage
warnings survive repeated minimization and the final MCP privacy boundary.
Separate requests subsequently completed assignment workload coverage for courses
3, 4 and 5 with no continuation remaining. Deadline semantics against independent
source documents remain unverified. Gradebook and discussion listing returned
`EGRESS_GOVERNANCE_MISSING`; those live paths remain blocked.

A subsequent five-page live PDF read returned all reported text characters but
required OCR on four pages. Visible OCR errors and privacy-withholding markers
prevent a full semantic-fidelity claim. A hash-matched rendering of page 5 was
actually inspected and was legible where extracted text was damaged. This proves
one visual fallback, not accurate OCR of the entire document.

The live TXT example reached the 250,000-character extraction ceiling. Reading
the final 10 extracted characters with the expected source hash returned no next
chunk while retaining `partial_data`, partial coverage and the explicit extraction
limit warning. End of continuation therefore did not falsely certify the original
document as fully read. A representative assignment-detail response agreed with
its workload entry on all eight compared metadata fields; this is cross-tool
consistency, not independent source verification.

After the concurrent extraction-status fix, live status calls for a previously
read XLSX and a PDF returned indexed metadata without document text. The XLSX
hash matched the earlier read. Both files were already indexed; these calls do
not establish live cold-cache behavior or independently prove no download occurred.

On the current frozen source, Node dependency audit reported zero vulnerabilities,
license metadata checks covered 127 packages with zero blocked entries, and the
source and complete-Git-history secret checks passed with unchanged-source receipts.
Lint and format checks passed. Bandit reported no issues meeting both configured
severity and confidence thresholds; lower-threshold findings still exist.

The reader UI rebuilt in a disposable directory and matched all three checked-in
assets byte for byte. Final Node audit regressions passed 39/39; lockfile and installed-package compatibility checks passed. The latest
diagnostic group passed 20 tests; the inventory and egress-contract neighboring
rerun passed 15 tests. Another comprehensive attempt stopped at 22% when a
synthetic authorization lease expired during a stalled run. The source-verification
hook then timed out in Git and obscured the summary. All 28 document-search tests
passed on focused rerun without weakening authorization or extending its lease.
The reporting fix passed 29 compliance tests and both subsequent full Windows runs.

## Remaining acceptance work

- Retain explicit gaps for blocked live content and unexercised dependent workflows.
- Establish independent source fidelity and complete permitted non-file traversal
  after the relevant source/recipient gates can legitimately be satisfied.
- Run the Linux/container CI gates; all 13 platform skips remain unverified here.
- Genuine UI acknowledgment and disposable-OS signed upgrade/rollback acceptance
  require their own external evidence; synthetic substitutes do not close them.
- The connected tool catalog omits resumable inventory parameters exposed by the
  current server. The server accepts them, but normal client discoverability is
  not established by that fact.

Operational readiness is **not established**. Successful synthetic tests and
clearer errors do not prove usable, complete access to the authorized coursework.
The evidence supports bounded direct reads, inspected visual fallbacks and workload
metadata recovery within existing permission. It does not support relying on every
academic workflow as a dependable comprehensive interface yet.

Exact sanitized outcomes are retained in the [first full-run receipt](recursive-validation-2026-11-03-pass-1.json),
[second full-run receipt](recursive-validation-2026-11-03-pass-2.json),
[process evaluation](recursive-validation-2026-11-03-processes.json) and
[academic corpus outcomes](recursive-validation-2026-11-03-corpus.json).

## Permanent regression coverage

Permanent regression coverage is retained in:

- `tests/course_file_audit.test.mjs`: source/image mismatch, traversal limits,
  empty-folder cycles, shared admission holds and raw transport failures.
- `tests/test_actionable_error_diagnostics.py`: reviewed guidance, hostile
  diagnostic fields, repeated minimization, retry metadata, final MCP privacy
  projection, coverage warnings and correlated request IDs.
- `tests/test_renderer_setup_diagnostics.py`: permission-setup timeout,
  setup denial, disappearing child directories and missing-root rejection.
- `tests/test_compliance.py`: metadata-tool timeout classification and retaining
  failed outcomes when final source verification is unavailable.
- `tests/test_blocked_case_acceptance.py`: Windows path-alias source hashing.
  Existing PostgreSQL, connection-guard, inventory, DOCX, XLSX and study tests
  were repaired or strengthened without weakening production authorization.

## Prioritized remaining work

1. Resolve legitimate source/recipient evidence for the specifically blocked
   academic workflows. Existing sign-in, selected-course access and permission
   to read a file do not establish permission for every downstream use.
2. Run the Linux CI/container gates and obtain genuine human acknowledgment and
   signed installer recovery evidence in the required disposable environment.
   These cannot be supplied by relabeling Windows or synthetic unit-test results.
3. Expand source-grounded OCR and document-fidelity evaluation. Live OCR errors
   need labeled comparisons and visual review before claiming reliable automated
   interpretation of grades, schedules, equations or scientific figures.
4. Refresh the connected tool catalog so resumable inventory parameters are
   discoverable. Profile long live requests and repeated authorization work;
   retain request budgets and accurate partial-coverage reporting while tuning.
