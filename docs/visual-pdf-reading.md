# Scanned PDF reading and OCR

The existing authenticated file reader now falls back to isolated English OCR
for PDF pages containing fewer than 40 non-whitespace text characters. The parser
version is `canvas-bridge-documents-v4`. Old v3 cache entries and entries created
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
- The native page reader completes the MCP Apps handshake and receives either
  image content or private metadata. Click **Read page in ChatGPT** to recheck
  access/version, validate the PNG hash, and supply pixels to the next turn.
  It negotiates image context support, with the documented ChatGPT file/imageIds
  bridge as a fallback. There is no manual download/upload, external conversion
  service or separate AI account. The view declares no external network origins.
  A later visual question may require pressing the button again.
- Sending a page into ChatGPT subjects that copy to ChatGPT chat/file retention,
  separate from the connector's temporary-file cleanup. The view does not request
  saving it to the user's file library. A sent image does not establish a correct
  interpretation; the assistant must still examine it and disclose uncertainty.
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
| Native ChatGPT visual delivery | Passed through the native page-reader control; model inspected actual pixels |
| Structured visual schedule in native ChatGPT | Seven entries were visually read correctly; submission to interpret_course_schedule was blocked by an expired/declined connector sign-in |
| Source citations | Passed for page, stable Canvas URL, original-byte hash and version |

The OCR misread a presenter name and the comprehensive exam's day. In a blind
native ChatGPT test (no expected dates supplied), the page reader delivered the
actual image and ChatGPT resolved both errors. All seven requested acceptance
entries matched the page, including the presenter column and undated TBD row.
PDF page citations were returned. This establishes visual reading, not automatic
or independently verified schedule reconstruction.

The follow-up structured endpoint call returned `Session terminated`; after
reloading, ChatGPT displayed an expired-connection notice and then an
approval/login decline. No successful live structured validation is claimed.
Local receipt/version/proposal tests pass. Sign-in renewal is needed to repeat
that final live stage; no permissions or authorization code were changed here.

The original gap had two layers: no server OCR, and a text-only model adapter
that did not expose standard MCP image blocks. The native view now performs the
initialization handshake and tolerates initial results without hidden image
metadata, then obtains a fresh authorized image before model-context transfer.
Outbound HTTP library wire logs are disabled to prevent signed URLs or headers
from being recorded under MCP's INFO logging configuration. Safe application
failure-type logging remains enabled.

XLSX support is a separate increment and is not included in this patch.
