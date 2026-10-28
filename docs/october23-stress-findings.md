# October 23 workload, discovery and inventory response contract

These changes were deployed to the personal connector and exercised through its
installed tools on October 23. See the
[live acceptance record](../evidence/sanitized-results/stress-findings-live-2026-10-23.md)
for results and remaining coverage limits, and the separate
[synthetic validation record](../evidence/sanitized-results/stress-findings-2026-10-23.md)
for failure-path regressions. These results do not establish broader client or
institutional support.

## Workload

`get_workload` preserves the existing independent `submission_state`,
`assessment_state`, and `timeliness_state` fields. It adds:

- `due_date_relationship`: `past_due`, `not_yet_due`, or `undated`, evaluated at
  `status_as_of`. A date without a clock becomes past due after that local date.
- `window_relationship`: `before_window`, `within_window`, or `undated`.
- `work_status`: submission state, or the explicit `graded`/`excused` assessment
  state. The underlying submission evidence remains available independently.
- `outstanding_action` and its evidence basis. `submit` requires an explicit
  unsubmitted record with an online submission requirement. `none_indicated`
  for submitted/resubmitted or excused work is not a general completion claim.
  Grades alone, offline/no-submission work and uncertain evidence remain unknown.

Only a past-due item with explicit outstanding submission evidence enters the
`overdue` section. Submitted, resubmitted, graded and excused work have separate
sections. Other past-due items use `past_due_unknown`. Undated items retain their
own section. `include_overdue` continues to include historical records before
the requested window; it does not turn all such records into overdue work.
Continuation binds the classification time so a deadline crossing during
pagination cannot change sorting and skip records. Availability and revision
fields remain independent constraints on what the student can do.

## Schedule material discovery

Automatic discovery examines authorized course file/page inventory and module
labels. Tokenized title/filename matching handles revision separators such as
`Course_Schedule_rev092926.pdf`. Schedule/timetable hints precede calendars and
syllabi, with PDFs first at equal priority and deterministic tie breaking.
Names are discovery hints only, never evidence of document contents.

At most three selected documents are read, within a 35-second material budget
and a 15-second per-document budget. The existing overall academic request
budget remains in place. `material_discovery.documents` reports each candidate
as reviewed, partially reviewed, unreadable, inaccessible, failed, or skipped,
with machine-readable reasons for count/time/access/parse limits. An explicit
selection continues to use the same authorization checks.

The discovery result distinguishes no candidate discovered, candidate not
reviewed, reviewed with candidates, and reviewed with no matching obligations.
Review applies only to the listed documents; check inventory and extraction
coverage before inferring absence. Source records preserve the fetched metadata
version, content hash, update time and page/section locator. Classroom activities
are returned separately from assessment-date candidates; neither automatically
becomes a confirmed assignment deadline or changes Canvas or Calendar.

## OCR and inventory

Successful OCR removes the document's obsolete zero-text warning, while generic
parser cautions remain. `document_diagnostics` contains document/page outcomes;
`parser_warnings` contains general cautions. `ocr_confidence` reports recognition
scores separately from `ocr_coverage` page counts, failures and budget skips.
OCR remains uncertain transcription even when every page yields text. Old OCR
caches are invalidated by a diagnostic revision, without changing the PDF pixel
delivery or presentation conversion pipeline.

OCR failure with no usable document text preserves its failure reason. Search
reports failures, no usable text, incomplete search, matches, or no match in
fully extracted text separately. A timeout is never a successful zero-match
search.

Inventory branches have bounded time shares within the existing total budget.
Successful branches survive other branch failures. File rows report
`reference_origin`, `inventory_freshness`, `inventory_checked_at`, and
`access_verification`. File-list visibility and course-qualified metadata checks
are distinguishable from retained module references (`not_rechecked`).
`inventory_status` reports completeness, freshness, counts, metadata/module-item
failures and budget limits. Metadata fallback lookups are capped and deduplicated.
Fresh content authorization is still required for every subsequent read/search,
including cached text. Search and academic evidence responses carry the partial
inventory status and coverage forward.

## Restricted-inventory follow-up

See the [diagnosis and live acceptance record](../evidence/sanitized-results/inventory-followup-2026-10-23.md)
for the upstream 403/404 explanation, regression checks and deployed results.

Inventory collection timeouts preserve already received pages. A later
permission denial still discards that collection's earlier records. Module file
metadata checks run in batches of at most three, with individual time limits
inside the unchanged total inventory budget. Successful sibling results survive
a timeout; pending lookups retain explicit budget-failure diagnostics. Results
are ordered deterministically after the bounded requests finish.

`inventory_status.module_file_coverage`, `module_file_reference_count`, and
`unresolved_module_file_count` distinguish resolution of visible module file
references from course-wide listing completeness. Complete module resolution
does not establish access to unlisted files or document content. Upstream
403/404 responses continue to produce partial course inventory.

Search cursors bind to file identity/version and search parameters, not
fluctuating freshness labels or branch availability. Changed files, versions,
scope or queries still require a restart, and each read still requires fresh
authorization. `pass_progress.inventory_incomplete_seen` preserves incomplete
inventory evidence across continuation calls even if a later inventory succeeds.
`coverage_reasons` separates remaining documents, failed documents, partial
extraction, missing versions and incomplete inventory. Existing cursors from
before this deployment require one restart because their binding format changed.
