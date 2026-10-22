# Scanned PDF reading and OCR

The existing authenticated file reader now falls back to isolated English OCR
for PDF pages containing fewer than 40 non-whitespace text characters. The parser
version is returned by the reader and status tools. Older parser cache entries and entries created
with a different OCR-enabled setting are reprocessed on the next authorized read.
Whitespace-only output is never reported as indexed. The former scan failure
was an absent OCR implementation, compounded by that incorrect indexed flag;
an old cached result could preserve the symptom but was not its underlying cause.

## Tools and evidence

- `read_course_file` and `fetch_course_material` preserve existing parameters.
  OCR text uses the same page attribution, hashes, text windows and continuation.
  `page_extraction` and passages identify embedded text versus OCR and confidence.
- `search_course_files` searches accepted OCR text, with method/confidence on
  matches. The default still searches indexed files only; `include_unread=true`
  provides the existing bounded on-demand search workflow.
- `get_file_extraction_status` reports partial coverage and `indexed=false` when
  no usable text exists. OCR never implies a verified table or visual reading.
- `render_course_file_page(connection_id, file_id, page=1, rotation=0,
  expected_hash=None)` returns one PNG as standard MCP `ImageContent`, plus a
  structured Result with stable Canvas citation, source hash/version, dimensions,
  next page and an encrypted one-hour review receipt. It does not return a public
  download URL or put arbitrary PDF bytes inside a text response.
- `interpret_course_schedule(connection_id, render_receipt, rows, calendar=None)`
  validates ephemeral, model-supplied interpretations against the authorized
  rendered source version. Rows retain exact passage, normalized image bounding
  box, date basis, paper/presenter/Q&A fields and uncertainty. They remain
  `assistant_inference`, unverified and subject to student review. The receipt
  proves the rendered source, not that the interpretation is correct.

Never submit visual interpretations if the client has not exposed the image.
TBD remains undated. Assumed or ambiguous dates, unresolved times and uncertain
entries are excluded from Calendar proposals. Optional fresh Calendar context
uses the existing proposal-only workflow with stable row keys, duplicate matching
and proposed updates for changed dates. No Calendar calls or writes occur here.

## Deployment and limits

No additional Canvas endpoint privileges or OAuth scopes are required. The
same selected-course authorization, fresh file metadata, token refresh, exact
approved storage origins, public DNS checks and pinned TLS connections apply.
An expired download denial refreshes metadata and retries once within the same
total download time budget. Storage never receives the Canvas bearer token.

The operator enables OCR with `BRIDGE_OCR_ROOT`, pointing to a trusted Tesseract 5
installation containing `tessdata/eng.traineddata`. Windows additionally needs
the installed Tesseract DLLs. Install from the upstream project's documented
distribution, not a course attachment. Restart the existing service after
configuration. The Linux image includes libtesseract5 and the English model;
file reading still requires its existing explicit enablement and OS isolation.
No extra student setup or token is needed on the configured personal service.

Ordinary embedded-text extraction and page-image rendering use a runtime without
OCR dependencies. Only low-text pages selected for OCR require that installation.
If OCR setup fails, the text reader returns available embedded text with explicit
partial coverage and `page_extraction[].ocr_failure`; rendering remains available.
Rendering failures now report a safe stage/reason code independently of the text
cache. The extraction-status tool explicitly says that render history is not tracked.

For a service launched outside a packaged Windows host, configure the actual
physical OCR installation path. A logical AppData path visible through package
redirection may not exist for the service process. Verify both the English model
and native library at that location; do not download or install course-supplied
executables. A missing installation reports `OCR_INSTALLATION_UNAVAILABLE`.
Correcting the OCR location and restarting invalidates cached partial OCR results.

PDFium renders without forms, annotations, JavaScript, actions or attachments.
Tesseract runs through its C API inside the same Windows AppContainer or Linux
Landlock/seccomp worker; it cannot spawn another process or fetch external data.
Only trusted parser libraries/models are copied into the isolated runtime.

Limits: 10 MB original file, 200 PDF pages, 2,400 pixels on the rendered long
edge, 1.3 MB PNG, 2 MB worker output, 384 MiB worker memory, 10 CPU seconds and
15 wall seconds per worker. OCR attempts at most four low-text pages per
extraction and accepts text only when mean confidence is at least 50/100.
The existing 250,000-character extraction and 16,000-character response limits
remain. Timeouts, unavailable OCR and low-confidence output stay explicit partial
results; they never become fabricated text. Larger scan collections need a
future resumable OCR workflow. Rotations can be requested for page rendering;
automatic OCR orientation correction is not implemented.

OCR preserves word coordinates and attempts horizontal table bands, but does
not verify merged-cell inheritance, colors, equations, scientific figures or
column meanings. Names, numbers and dates can be wrong even at high confidence.
Color page images are preserved independently of grayscale OCR preprocessing.

Raw bytes and PNGs are temporary per-request worker files, removed on cleanup;
no public raw-file endpoint or persistent image cache exists. Extracted text and
word coordinates follow the existing scoped 1–24 hour cache and deletion rules.
Receipts are encrypted, owner/connection/scope/version-bound and expire in one
hour. Abrupt OS failure and host backups retain the existing documented caveats.

## Authorized live verification, 2026-10-21

The owner's previously authorized one-page Rowan schedule was retrieved from
Canvas as its original 99,127 bytes without manual upload, rendered at
1,855 × 2,400 pixels, and read through the existing private connector. No original
document, image, private receipt or coursework transcription is committed here.

| Stage | Observed result |
|---|---|
| Authenticated original binary retrieval | Passed; hash/version-bound original PDF, zero embedded text characters |
| Restricted page rendering | Passed; local visual inspection confirmed the acceptance entries |
| OCR text and indexing/search | Passed with partial coverage; roughly 3,000 characters, mean confidence 79/100, searchable content |
| Native ChatGPT text delivery | Passed; ordinary conversation received OCR with page citation |
| Standard MCP image transport | Passed in real HTTP MCP contract test with `ImageContent` |
| Native ChatGPT visual delivery | Blocked in the tested connector surface: model received metadata but reported no inspectable pixels |
| Structured visual schedule in native ChatGPT | Not completed; model correctly declined to invent image coordinates |
| Source citations | Passed for page, stable Canvas URL, original-byte hash and version |

The OCR misread a presenter name and the comprehensive exam's day. Local image
inspection could resolve them, but this does not establish that the native
ChatGPT model saw the image. The complete visual-schedule acceptance test remains
partial. Future work must verify a supported image-delivery path on that surface;
do not substitute public signed URLs or claim visual understanding from metadata.
XLSX support is a separate increment and is not included in this patch.
