# DOCX processing investigation — 22 October 2026

The owner supplied a private DOCX stress-test report. It observed four failed
ordinary extractions across two files and two reader routes, despite DOCX being
advertised as supported. Errors did not establish whether download, worker
startup, isolation or text parsing failed. The report and its private IDs,
academic records and request details are not copied into the repository.

## Findings and changes

The checkout already contained the shared worker fixes documented in
[the PDF investigation](pdf-processing-2026-10-22.md): Windows AppData directory
identity checks, OCR-independent text startup, bounded error stages and early
continuation guards. Existing DOCX/PPTX AppContainer controls passed locally
before the DOCX-specific changes (2 passed). This is consistent with a shared
worker issue in the report, but does not prove the historical failure's cause.

New synthetic known-answer fixtures reproduced these separate DOCX defects:

- `w:cr` disappeared, joining adjacent lines.
- Nested text-box paragraphs appeared both inside the enclosing paragraph and
  again on their own, duplicating and joining text.
- Moved-from/deleted paragraph content and mutually exclusive compatibility
  branches could enter the same canonical text.
- Missing/invalid main-document structure lacked a specific diagnostic; some
  invalid documents returned empty success instead of a bounded rejection.
- An empty body produced zero sections, making the normal section-1 read fail.
- An exact 250,000-character boundary could omit later content without marking
  coverage partial; over-budget extraction also lacked a specific warning.

Nine failing parser assertions were recorded before their fixes: seven initial
cases and two text-budget cases. The traversal now visits Word text once,
preserves line/tab boundaries and follows the documented revision/fallback
policy. Empty documents return a usable empty section with partial coverage.
Structural failures have `EXTRACTION_INVALID_DOCX_STRUCTURE`; omitted text at
the character cap is disclosed. See [DOCX semantics](../../docs/docx-reading.md)
for unsupported features and reading-order limits.

Status and unread-search failures now share one classification: corrupt,
invalid, resource-limited or invalid-output processing is `failed`, separately
from access and format support. Explicit unsupported capabilities remain
`unsupported`. Existing public top-level status enums are preserved. Unknown
failures never assert that a timeout or memory event occurred.

Parser `canvas-bridge-documents-v6-docx` invalidates prior success/failure caches
on the next authorized access. No sandbox capability, process/resource limit,
permission, course selection or download origin was broadened.

## Validation

- Focused DOCX, academic intelligence, file reading, PDF regressions, XLSX and
  document search: **161 passed** before the final extra DOCX output-limit and
  MCP validation/status assertions.
- Full suite with the installed English OCR runtime enabled: **604 passed,
  20 skipped, 4 failed** in 153.60 seconds. Skips were 13 Linux-only checks and
  seven checks requiring a disposable PostgreSQL database. The four failures
  were the invalid-size cases in `test_T23_download_requires_supported_current_metadata`:
  concurrently edited download code passed `details` to an already-imported
  older `DomainError` constructor. The matching constructor was present on disk
  when investigated. This task did not modify either of those files.
- Fresh-process retest of **all 26 DOCX cases and the download/file suite:
  84 passed** in 13.10 seconds, including all four preceding failures. No second
  full run was performed; this record does not claim a clean full-suite run
  against a frozen snapshot of the concurrently edited checkout.
- Targeted Ruff lint/format checks pass for all six changed Python files.
- Repository-wide Ruff lint passed. The repository-wide format check identified
  pre-existing/concurrent formatting in `scripts/build_desktop.py`, outside this
  change; it was not rewritten by this task.
- `git diff --check` passed after the final code edits.

The DOCX tests cover split runs and Unicode, paragraph/table order, text boxes,
revision/fallback policy, strict namespace, malformed main XML, DTD/entity
rejection, empty documents, exact/over-budget truncation, status transitions,
failure recovery, old cache invalidation, source hash/version guards, owner and
visibility denial, literal search, section isolation and canonical text passed
to academic deadline checks. Synthetic bytes are the only documents parsed.

Authenticated local HTTP MCP acceptance uses the actual Windows AppContainer
worker in the redirected AppData parser root with optional OCR deliberately
unavailable. It exercises both reader routes, chunk reconstruction, section
selection, invalid arguments, hash guards, cached search, the PDF-only renderer
boundary and malformed-document error/status propagation. Local MCP success is
not evidence of the installed connector's deployed version or live file recovery.

## Installed service and remaining acceptance

One bounded installed-connector status call for a report reference returned
`format=docx`, `format_supported=true`, `extraction_outcome=not_attempted`, and
parser label `canvas-bridge-documents-v5-xlsx`. No download or text read was
performed by that status probe. The label identifies the reported runtime,
not an independently verified source revision.

No service restart was performed by this task. Coordinated restart/deployment
and fresh offset-zero reads of the original two DOCX references through both
reader routes remain necessary before claiming live recovery. No real document
bytes were downloaded or committed; no credentials, selected courses, Canvas
records, Calendar events or messages were changed.
