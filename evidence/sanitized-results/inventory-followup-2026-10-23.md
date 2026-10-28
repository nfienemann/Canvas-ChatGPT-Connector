# Restricted inventory and partial-coverage follow-up

## Diagnosis

The installed permission audit confirmed an owned, selected course with consistent
local scope. Course and module metadata returned HTTP 200; the course file-list
endpoint returned HTTP 403. No credential refresh or state repair occurred.

The installed audit does not expose error bodies or probe Pages. A separate
private operator diagnostic therefore made exactly two bounded, freshly
authorized GETs on the existing allowlisted course Pages/Files routes. It
disabled credential refresh, followed no redirects, read at most 4 KiB of error
data, and retained only recognized error categories:

- Pages: HTTP 404, recognized course-navigation-disabled response.
- Files: HTTP 403, recognized access-denied response.

These are upstream restrictions, not an incorrect course identifier or a
connector-generated HTTP failure. Both paths match the documented
[Pages list route](https://developerdocs.instructure.com/services/canvas/resources/pages#method.wiki_pages_api.index)
and [Files list route](https://developerdocs.instructure.com/services/canvas/resources/files).
Canvas's [Pages API implementation](https://github.com/instructure/canvas-lms/blob/master/app/controllers/wiki_pages_api_controller.rb)
checks tab availability, and its [disabled-tab handler](https://github.com/instructure/canvas-lms/blob/master/app/controllers/application_controller.rb)
returns 404 for JSON requests. The [file-list implementation](https://github.com/instructure/canvas-lms/blob/master/app/controllers/files_controller.rb)
checks folder-content permission separately from an individual file read.
The private diagnostic observed the actual responses; inspecting public source
alone would not establish this institution's configuration. The precise reason
for denied file-list permission was not inferred beyond Canvas's response.

The previously issued live search cursor also reproduced `source_changed` when
its inventory observations changed. Synthetic fixtures isolated the defect:
freshness labels and branch failures were included in the cursor's source
fingerprint even when file membership and versions were identical.

## Connector changes

- Search continuation now binds to the source manifest and existing scope/query
  constraints. Transient freshness and branch-status changes do not invalidate
  it. Actual added/removed/version-changed files still require a restart.
- Incomplete inventory is remembered across the search pass. A later successful
  inventory cannot erase an earlier coverage gap. Explicit coverage reason
  codes separate remaining documents, document failures, partial extraction,
  unversioned sources and inventory gaps.
- Branch timeouts preserve completed collection pages. A subsequent permission
  denial still discards that collection's received records.
- Course-qualified file metadata uses at most three concurrent GETs, with
  individual timeouts and the unchanged overall budget. Successful lookups
  survive slow siblings, pending/failed lookups remain explicit, all tasks are
  joined/cancelled before returning, and output ordering is deterministic.
- Module file-reference resolution has its own coverage and unresolved count.
  Resolving every visible module file never upgrades a denied course-wide list
  to complete inventory or grants permission to read content.

Old search cursors need one restart after deployment because their binding
format changed. Fresh authorization/version checks remain mandatory on every
content read. No new Canvas endpoint, permission, credential, course selection,
or request-budget setting was introduced.

## Remaining partial coverage

Course-wide discovery remains incomplete while the upstream lists are disabled
or denied. Files referenced by accessible modules can still be independently
authorized. External/unlisted resources are not inferred or fetched through
alternate permissions.

OCR's `partial` extraction label is deliberate: recognized text does not verify
table structure, dates, figures or reading order. The schedule's one accepted
OCR page and confidence are reported separately. Other documents can genuinely
have low-confidence pages or reach the four-page OCR limit. Those limits and the
three-document search batch remain in force; they are not successful empty
results. The PDF pixel-delivery and LibreOffice conversion paths are unchanged.

## Validation and deployment

- Initial regression run: **five failures reproduced**, four negative/control
  cases passed. The failures covered volatile cursor binding, discarded partial
  collection pages, lookup starvation and missing module-resolution reporting.
- Final follow-up regressions: **11 passed**, including fresh authorization on
  retained references, real membership/version changes, later collection denial,
  bounded concurrency, overall cancellation and explicit unattempted lookups.
- Focused existing/new checks: **197 passed**.
- Full suite: **846 passed, 24 skipped in 236.17 seconds**. Skips remain the
  platform/disposable-database/optional-runtime cases documented in the earlier
  [synthetic validation record](stress-findings-2026-10-23.md).
- `ruff check src tests` and final `git diff --check`: **passed**.

The personal service restarted at **20:57:46 America/New_York October 23**
(00:57:46 UTC October 24) using its existing configuration and the normal
Windows elevation boundary. The deployment manifest contains 12 module hashes;
all still matched after the live checks. No database or tunnel restart was
performed.

Installed-connector checks after restart:

| Check | Result | Request receipt |
|---|---|---|
| File inventory | 34 fresh module file references; module file coverage complete; zero unresolved lookups, metadata failures or budget exhaustion. Course-wide coverage remains partial with the original 403/404 reasons. | `d9169950a015435590a165e90ea3ae88` |
| Search, first bounded call | One document completed, one matching passage; continuation available. Coverage reasons explicitly identify remaining documents, partial extraction and incomplete inventory. | `e5f66327be474114b47f2fe785ad48c7` |
| Search, using that continuation | Advanced to three completed documents, three additional passages, no duplicated passages and no `source_changed`. Incomplete inventory remains recorded across the pass. There are 31 documents remaining; this was a continuation verification, not an exhaustive course search. | `0fbbd9dc943a48a6bc7deb6244ac4ff1` |
| Automatic deadline reconciliation | Still finds 17 candidates without explicit material IDs. Reports complete module file resolution while preserving incomplete course-wide inventory and OCR uncertainty. | `a408c18bbe514d16adf99ad93c808fdc` |

All four post-deployment calls resolved the 34 module files freshly. Fluctuating
fresh/retained observations were isolated synthetically; this live run did not
induce an outage or change production limits to force that condition.

Before/after protected-state fingerprints match for encrypted credentials and
credential lifecycle, authorization state/epochs/versions, all four selected
courses, saved local records, jobs, and private configuration including vault and
tunnel settings. Only normal retrieval/cache/refresh metadata is outside that
comparison. No Canvas or Calendar writes were invoked; MCP saved-state writes
remain disabled. No permissions or source restrictions were repaired or widened.

Raw coursework responses and private state proofs remain only in the private
operator directory, outside tracked repository content. This report records
aggregate results and receipts, not student records or source passages.
