# Document range and XLSX chunk investigation

## Findings

The text reader used two different rules at the end of a document. A start beyond the count raised a domain error without a reviewed reason code. The public error projection therefore used its fallback. An end beyond the count was silently clipped. The visual path had a separate cause. Its workers knew the count but discarded it on failure, leaving a generic range or conversion diagnosis. A nearby local failure event for the text reader recorded an unclassified failure with content policy unevaluated. The journal omits the arguments, so attribution to the specific slide request remains unconfirmed.

A read-only request-ID lookup in the local usage ledger established two successful file downloads and a separate file-listing 403 in the referenced request context. The ledger records upstream attempts and does not store response text, tool arguments, or the boundary of a specific workbook. The reported 5,000-character split was reproduced using entirely synthetic data. The XLSX extractor emits whole JSON lines within its extraction budget. The reader subsequently slices the joined text at character offsets. Structured cells come from a separate projection of the extracted units.

## Contract

Within the supported 1–200 input domain, both requested endpoints must be inside the identified document. A new `DOCUMENT_RANGE_OUT_OF_BOUNDS` diagnostic has status `needs_input`, the requested `page_start` and `page_end`, and the valid interval 1 through `page_count`. The final MCP response has no sources or image. Numeric bounds are reconstructed from reviewed fields only. Range syntax and unusable lengths have separate `DOCUMENT_RANGE_INVALID` and `DOCUMENT_LENGTH_UNAVAILABLE` codes. The MCP argument schema can also reject malformed input before dispatch. Version mismatches, access checks, actual conversion failures and egress decisions retain their respective paths.

The XLSX response adds the boolean `data.text_truncated`. A true value means the window omits a prefix or suffix of the selected extracted text. The final window can have this flag set and a null continuation. From offset zero, concatenate each window verbatim in continuation order and parse nonblank LF-delimited records after completion. The selection, offsets, hash and parser bindings continue to apply. Structured cells retain their separate output budget. There is no input schema, stored document model, or database migration change.

## Changed files in this task

| Area | Files |
| --- | --- |
| Range validation, reader and tool contract | `src/canvas_bridge/document_ranges.py`, `src/canvas_bridge/course_files.py`, `src/canvas_bridge/app.py` |
| Range-aware internal callers and compact output | `src/canvas_bridge/document_search.py`, `src/canvas_bridge/figure_inspection.py`, `src/canvas_bridge/workflow_operations.py` |
| Worker, renderer and derivative handling | `src/canvas_bridge/visual_worker.py`, `src/canvas_bridge/visual_files.py`, `src/canvas_bridge/presentation_render_worker.py`, `src/canvas_bridge/presentation_pipeline.py`, `src/canvas_bridge/presentation_derivatives.py` |
| Public error reconstruction and diagnostics | `src/canvas_bridge/egress_errors.py`, `src/canvas_bridge/failure_diagnostics.py` |
| Reader documentation | `docs/file-reading.md`, `docs/xlsx-reading.md`, this report |
| Synthetic tests | `tests/test_file_reading.py`, `tests/test_visual_files.py`, `tests/test_presentation_reading.py`, `tests/test_presentation_rendering.py`, `tests/test_spreadsheet_reading.py`, `tests/test_visual_error_projection.py` |

## Verification

- Reader, renderer, progressive PDF, search, spreadsheet and figure-inspection regression run during implementation: 221 passed, four skipped. The two native converter cases subsequently passed with the configured trusted LibreOffice source in an isolated test runtime. Two optional OCR cases skipped in the broad run.
- Public diagnostics, egress, workflow and slide-worker/MCP regression run: 87 passed. Focused bounds, redaction and isolated PDF failure tests: 32 passed. Runs overlap.
- The exact-size workbook test reconstructed windows of 5,000, 5,000 and 4,037 characters, parsed the escaped long value, and verified formula text and cached value. Final focused runs also passed for the structured XLSX result through MCP, first/last PDF pages, the out-of-range MCP envelope and loss of file access during slide counting.
- Additional synthetic PPTX coverage included speaker notes, hidden slides, cached chart text and native hidden-slide mapping to PDF pixels. XLSX coverage included direct structured cells and stored formula caches. These exercise adjacent behavior independently of the reported incidents.
- Scoped Ruff lint, format and diff checks passed. Tests ran on the dirty local checkout based on `5bd0863`. No full suite was run or reused. No service rollout or live document retest was performed.

## Full-suite and installed-client follow-up, November 5, 2026

The frozen release manifest starts with `e03c344f3d57` and includes the assessment-preparation feature. The final Windows run collected 2,665 Python tests. It passed 2,652 and skipped 13 Linux-kernel cases. All 87 Node tests passed. Ruff lint and formatting passed across 680 files. The gate used a disposable PostgreSQL cluster and the configured OCR and native slide runtimes. The stale derivative test now checks the specific bounds diagnostic, requested slide and count while continuing to verify cache invalidation.

The release also includes the planning test fixture's Canvas receipt clock fix, a historical-schema fixture built from real migration revisions, and the SQLite migration transaction and connection-lifetime repair. The accepted snapshot excludes later concurrent workspace edits.

Deployed to Canvas Bridge Personal after verifying 869 manifest files and a ready database preflight at revision `d40ad4c70618`. Both installed text-read and slide-render tools returned the actionable bounds error and zero sources or images. The installed XLSX client followed both continuations, reassembled all 14,037 characters and parsed every nonblank JSON line. The structured projection and reconstructed text each contained 151 records. An initial slide call encountered a busy document worker and succeeded on retry. No workbook cells, source identifiers, credentials or presentation content are included in this report.
