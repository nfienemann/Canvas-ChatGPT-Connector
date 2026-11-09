# Bounded five-course reading tests — November 3, 2026

Owner authorized read-only tests across five selected courses. Tested representative
local file/page and assignment-description samples; not exhaustive course/document
coverage. Detailed results/source text remain encrypted in the operator directory.
No credentials, academic titles, source references or content are included here.

Local results by selected-course ordinal:
1. A PNG candidate is outside existing document text formats; sampled assignment
   description retrieved. Inventory remains partial.
2. Representative PDF and substantive assignment-description text retrieved.
3. No uploaded files discovered; a nonempty Canvas page and description retrieved.
   An initially empty page was not treated as all course content.
4. PDF and sampled description retrieved. The latter only names a linked DOCX;
   course-scoped metadata confirmed hidden_for_user=true and hidden=true. No hidden
   content was downloaded.
5. Representative PDF text retrieved partially; sampled assignment explicitly
   returned no description. This is not proof of no requirements.

Repairs and checks:
- Sparse raster PDFs with 40+ footer characters now reach bounded OCR. A formerly
  footer-only five-page sample yielded about 29,000 characters, four accepted OCR
  pages and one explicitly budget-skipped page.
- Valid indirect annotation arrays no longer cause TypeError/corrupt output. An
  actual formerly failing PDF yielded about 10,000 characters after the repair.
- OCR structures are refreshed; unrecognized sparse text is not complete body text.
- Private reviews bind extracted text as well as source bytes/version. Newly
  recovered body text cannot borrow old footer-only consent.
- Added explicit minimized private file-inventory permission with content/URL
  stripping and selected-course/resource/owner/client checks.
- 132 focused parser/document/privacy/release tests passed; a later refined
  private-binding/privacy run passed 78 tests. Ruff checks passed.
- Nine-source new/changed encrypted review packet round-trip validated. One
  unchanged approved assignment is reused. No additional real reviews fabricated.
- Batch helper now refuses success if every source is skipped, reports source
  changes individually, writes a distinct receipt and passes a synthetic no-signing
  all-skipped rejection check.

Initial native inventories remained withheld with the active inventory flag false
and old two-source receipt unchanged, despite a reported restart. This is not
installed content acceptance. Native cross-course retest awaits confirmed saved
batch reviews and restart. PNG transcription, hidden files, complete OCR and
unreviewed visual/original content are not advertised as delivered.

## Installed retests after the saved batch receipt

The batch saved two new exact-source approvals, not nine. The native connector
returned approved assignment text for course 1 and approved page text for course 3.
All five native file inventories were released under the minimized inventory
permission; four retained partial coverage, and course 3 reported no uploaded files.
Seven packet entries remain unapproved; recovered text must not inherit the old
footer-only approval. One pending assignment version changed despite the sampled
preview remaining equal and requires packet refresh before review.

A subsequent standard PowerShell restart completed with explicit owner authorization.
Live assignment refreshes then returned UPSTREAM_THROTTLED. Local read-only usage
inspection found one active file request and no active cooldown (zero failures);
this is consistent with the configured one-request-per-token concurrency ceiling
and another session doing work, rather than proof of a Canvas 429. No active
request, ledger entry, or source approval was cleared to force acceptance.
The minimized permission audit transmitted successfully (EGRESS_RELEASE_PERMITTED),
but correctly reported stale authorization after incomplete membership refresh.

Added fixed-category stale lease/scope and incomplete-membership logging without
record contents. Nested incomplete refreshes preserve their actual reason codes
instead of continuing into a misleading stale-scope failure. Targeted authorization
and consistency checks passed 35 tests; private review/parser/development-policy
checks passed 42 tests; the extended preflight suite passed 6 tests. These are
focused runs, not a fresh full-suite claim.

### Final recovery and concurrency limit

After normal reservation expiry, the native approved course-4 assignment read
succeeded. A subsequent minimized audit returned status ok, scope_consistency
consistent, and all 35 checks AUTHORIZED_LOCAL_SCOPE with matching snapshots.
The final sequential assignment pass returned course 1 ok; course 2 withheld
with EGRESS_CLASSIFICATION_UNKNOWN; courses 3 and 5 withheld with
EGRESS_GOVERNANCE_MISSING. Those samples have no saved exact-source review.

A later read of the approved course-3 page again returned STALE_SCOPE_SNAPSHOT.
Fixed diagnostics identify a missing membership lease, not a mismatched scope
hash; logs also show an incomplete throttled file-reader refresh. Concurrent
activity continues to invalidate the shared lease. Therefore durable resolution
of concurrent-session stale scope is NOT established. The authorization check
remains intact, and no failed refresh was treated as an authorized success.
The service remains running; no further restart or credential action is needed
from the sleeping owner. Pending source attestations require the owner's review.

### Superseding concurrency repair

The later [concurrent-session repair and acceptance](concurrent-session-authorization-2026-11-03.md)
adds process-coordinated guards rather than retaining a failed authorization lease.
Simultaneous approved assignment/page reads succeeded, the final approved course-4
assignment succeeded, and the final native audit passed all 35 checks. This
supersedes the earlier unresolved concurrency observation for these bounded tests;
pending exact-source reviews and extraction limitations remain unchanged.
