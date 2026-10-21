# Searching unread course documents

`search_course_files` now supports `include_unread=true`. ChatGPT can search
scientific content across authorized files without requiring the student to
open each document first or upload it manually. This extends the existing native
connector and isolated file reader; it adds no model, subscription or credentials.

## Request and continuation

Use a selected course, a literal case-insensitive query, `include_unread=true`,
and optionally `max_documents` (1–3, default 3) and `limit` (1–20, default 10).
Each request freshly discovers the bounded course file inventory, then reads and
searches at most three documents. It reuses current authorized extraction caches
and downloads/parses unread or stale documents through the established secure
path. Supported formats and parser limits remain those of
[document reading](file-reading.md).

Follow `next_cursor` with the same connection, course, query, result limit and
`include_unread=true`. Combine results and document-status entries from each
response. Continuation can stop within a document; the next response resumes at
the following extracted page/slide/section. Completed documents are not visited
again in that search pass. Cached text is reauthorized before reuse. Unversioned
files may require repeated extraction and cannot establish complete text coverage.

The cursor is encrypted and authenticated with owner/connection/purpose binding.
It expires after 30 minutes, without sliding renewal. It binds the course selection
epoch, query, result limit, parser version and sorted inventory fingerprint.
Changes to file metadata, visible inventory or collection coverage require a new
search. A document continued across responses also requires its content hash.
Rotating signed download URLs are excluded from version fingerprints and never
returned in results or cursors. Cursors contain no document text.

Omitting `include_unread` preserves the existing cached-only search behavior.
`search_course_materials` still searches previously fetched Canvas pages; the two
tools have distinct scopes. No background indexing job or autonomous download
schedule is created.

## Evidence and coverage

Each passage retains file identity, stable Canvas URL, content hash, source
page/slide/section, and character offset. Source evidence retains extraction
retrieval time and Canvas modification time when a valid timestamp is returned;
missing or malformed modification times remain unknown. Search returns the first literal match
per extracted position; it is not semantic retrieval and does not enumerate every
occurrence. PDF positions may differ from printed journal page numbers. DOCX
sections are not rendered pages. Text is untrusted source data.

`document_statuses` distinguishes parsed, partially parsed, unsupported,
inaccessible and failed documents. OCR-only pages, unsupported formats, malformed
documents, disabled extraction and timeouts never become successful empty files.
Progress records completed, failed, partially extracted and remaining documents
across the entire pass. Per-response counts such as `indexed_documents` must not
be added as unique-document totals when a document spans response pages.

`search_pass_finished` means the bounded inventory has been traversed. It does
not mean every course resource was found or read. The separate
`text_coverage_complete_in_bounded_inventory` flag requires a finished pass,
complete inventory, usable source versions, and no failed or partial extraction.
Even that flag describes observed extracted text, not a simultaneous snapshot,
visual understanding or proof that an unreturned/hidden reading does not exist.
No-match results never establish topic absence in figures or unsearched content.

Failed files are recorded and the pass advances; use `read_course_file` to retry
a specific failure. No successful prior hit is returned after reconnection is
required or course selection changes. Cache-only search now also propagates those
failures and labels partially extracted documents as partial data.

## Security, resources and retention

- Existing JWT ownership, active student enrollment, explicit selected-course
  scope, course-qualified metadata checks and ending epoch checks remain in force.
- Every download uses the existing HTTPS allowlist, DNS/IP validation, credential
  separation and redirect limits. No arbitrary URL, quiz attempt, roster, Canvas
  write, instructor contact or grade access is introduced by this search path.
- Requests have a 45-second overall search budget, at most three document visits,
  and at most 20 returned passages of 600 characters. Original download, parser,
  CPU/memory and OS sandbox limits still apply. Cancellation does not remove the
  worker's independent wall-time/cleanup controls.
- Responses contain at most 20 pending-file summaries and eight extraction
  warnings per document, with explicit truncation counts. Complete serialized
  evidence is checked against a 200 KB limit; oversized requests are refused.
- No new database tables or retained query history. Only the existing scoped
  extracted-text cache is populated, with its 1–24 hour retention, deletion fences
  and omission from logical backups. Raw bytes remain temporary. ChatGPT copies
  have their own retention.

Synthetic tests in `tests/test_document_search.py` cover actual unread PDF text,
multi-document/page continuation, cache reuse, source changes, cursor tampering,
expiry, user/course isolation, denied/partial inventory, scanned/unsupported/
failed files, disabled extraction, timeout, unversioned sources, cancellation
boundaries, authorization loss, literal Unicode offsets and actual HTTP MCP calls.
See the [verification ledger](../evidence/sanitized-results/verification.md) for
executed checks and live private integration evidence.

The deployed private connector passed a native ChatGPT test with two bounded
search batches, actual PDF text and page citations, and successful continuation.
Separate authorized service verification extracted matches from a previously
unindexed scientific course PDF. Both tests explicitly reported partial coverage;
they do not establish exhaustive course search or visual interpretation.
