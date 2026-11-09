# Searching unread course documents

`search_course_files` now supports `include_unread=true`. ChatGPT can search
scientific content across authorized files without requiring the student to
open each document first or upload it manually. This extends the existing native
connector and isolated file reader; it adds no model, subscription or credentials.

## Request and continuation

Use a selected course, a literal case-insensitive query, `include_unread=true`,
and optionally `max_documents` (1Ã¢â‚¬â€œ3, default 3) and `limit` (1Ã¢â‚¬â€œ20, default 10).
Each request freshly discovers the bounded course file inventory, then reads and
searches at most three documents. It reuses current authorized extraction caches
and downloads/parses unread or stale documents through the established secure
path. Supported formats and parser limits remain those of
[document reading](file-reading.md).

Follow `next_cursor` with the same connection, course, query, match mode, result limit and
`include_unread=true`. Combine results and document-status entries from each
response. Continuation can stop within a document; the next response resumes at
the following extracted page/slide/section. Completed documents are not visited
again in that search pass. Cached text is reauthorized before reuse. Unversioned
files may require repeated extraction and cannot establish complete text coverage.

The cursor is encrypted and authenticated with owner/connection/purpose binding.
It expires after 30 minutes, without sliding renewal. It binds the course selection
epoch, query, match mode, result limit, parser version and sorted inventory fingerprint.
Changes to file metadata, visible inventory or collection coverage require a new
search. A document continued across responses also requires its content hash.
Rotating signed download URLs are excluded from version fingerprints and never
returned in results or cursors. Cursors contain no document text.

Omitting `include_unread` preserves the existing cached-only search behavior.
`search_course_materials` still searches previously fetched Canvas pages; the two
tools have distinct scopes. No background indexing job or autonomous download
schedule is created.

## Searching OCR text

Both cached and unread search default to case-insensitive literal substring matching.
Set `match_mode="approximate"` for a single English word of 7â€“32 letters. Each
position still returns its first exact match when present. Otherwise, on accepted
OCR text only, search compares whole words and pairs split by up to four spaces
or tabs on the same line. It accepts at most one substitution per five letters,
up to two, from a small set of confusable glyph pairs. The closest candidate wins,
with the earliest hit breaking ties. The original transcription stays in the cache.

`matched_text` preserves the source span. `similarity` is the fraction of equal
letters after joining the split, while `ocr_confidence` is the OCR engine's page
estimate on a 0â€“100 scale. Check `ocr_status` to see whether the page used that
transcription. A literal hit can occur in incorrect OCR. Search sets
`visually_verified=false`. To inspect the pixels, call `render_course_file_page`
with the returned file ID, PDF page and `expected_hash` set to `content_hash`.

Cached-only `document_statuses` reports attempted, searched, total and uncertain
positions per indexed document. Uncertain counts include failed, skipped, unusable
and accepted OCR below 80 or with missing confidence. For bounded reads, use
`include_unread=true` and follow the cursor. Use `get_file_extraction_status` for
the page breakdown and `read_course_file` for a specific missing range.
If inventory discovery itself is partial, follow the inventory continuation
through `list_course_files` in resumable mode.

For PDF pages with little embedded text or a sparse text layer over a scan,
the isolated reader can render up to four OCR candidates per batch. The first
pass uses grayscale, a 15-pixel median background and a difference threshold of
30. English Tesseract runs in sparse-text mode (PSM 11, configured 220 DPI).
It returns TSV word boxes and confidence. The reader clusters word centers
into lines and joins words with two spaces, preserving OCR spellings. It uses
accepted page text and its original page number as the searchable cache entry.
Ordinary embedded text continues directly through extraction.

The parser retries a low-confidence single-band page once with the original
grayscale bitmap. The trigger is below 75 and replacement requires at least 80
and a ten-point gain. Table-band processing, pixel limits and worker deadlines
still apply. The parser version change invalidates older extraction caches.
This uses the existing configured English OCR installation.

## Evidence and coverage

Each passage retains file identity, stable Canvas URL, content hash, source
page/slide/section, and character offset. Source evidence retains extraction
retrieval time and Canvas modification time when a valid timestamp is returned;
missing or malformed modification times remain unknown. Exact search returns the first literal match
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
  extracted-text cache is populated, with its 1Ã¢â‚¬â€œ24 hour retention, deletion fences
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
## Synthetic title-search measurements (2026-11-05)

Two comparisons separate recognition from retrieval. For retrieval, six of
26 synthetic PDF pages were indexed. Page 5 carried the reported transcription
`COGRNTINE. OF FLORDIMG` with a **fixture** confidence of 61. Page 6 contained
literal `offloading`. Cached exact search returned page 6. Approximate search
added page 5 with matched text `OF FLORDIMG` and similarity 0.80. The source
span, page numbers, parser and hash survived a one-result cursor boundary.
The other 20 pages had no chance to match the initial cached-only request.

| Labeled page/query pairs | Exact | Approximate enabled |
| --- | ---: | ---: |
| Retrieved among 5 relevant transcriptions | 1 | 4 |
| Retrieved among 11 distractors | 1 | 2 |

Both modes missed `0F7L04DING`. Both matched the literal substring in
`offloadings`, labeled negative for a whole-word intent. The additional false
positive was `comical` for `conical`. On a separate 93,612-character OCR passage
with a split title at the end, median matching time over nine local calls was
0.66 ms exact and 11.43 ms approximate. This measures matching alone.

For recognition, the fixture draws upright and sideways titles, saves scanned
PDFs and rasterizes the pages with PDFium. Visually inspecting the generated
bold title confirmed both words. With the installed English Tesseract 5.5.3
runtime, the original pass recovered the literal word on 1 of 7 images, and the
conditional grayscale pass recovered it on 6 of 7. The readable control stayed
at confidence 95. The bold title went from 36 to 95, the faint title from 0 to
94. The sideways title stayed unreadable at 32. In one local run, the six
retry-eligible pages together took 2.68 s before and 2.92 s after, excluding
PDF rendering, sandbox startup and network time. Individual timings vary.

Run `python -m pytest -q -s tests/test_ocr_search.py` for the generated fixtures.
The raster comparison uses Windows Arial fonts and the existing
`BRIDGE_TEST_OCR_ROOT` test setting. The private PDF and live client were outside
this synthetic evaluation.

### Files involved in this change

- [MCP request](../src/canvas_bridge/app.py) and [response field projection](../src/canvas_bridge/privacy/output_fields.json)
- [Shared matcher](../src/canvas_bridge/passage_search.py), [cached search and file status](../src/canvas_bridge/course_files.py), and [bounded unread search](../src/canvas_bridge/document_search.py)
- [OCR preprocessing](../src/canvas_bridge/ocr_worker.py), [page diagnostics](../src/canvas_bridge/document_diagnostics.py), and [parser version](../src/canvas_bridge/parser_worker.py)
- [Labeled fixtures and OCR comparison](../tests/test_ocr_search.py), [HTTP search contract](../tests/test_document_search.py), and this search guide
