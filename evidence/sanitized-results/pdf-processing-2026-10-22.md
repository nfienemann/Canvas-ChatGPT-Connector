# PDF processing incident — 22 October 2026

The owner supplied a private diagnostic reporting PDF text/read/render failures
across three selected courses. The original report, academic records, file IDs,
download links, private configuration and image pixels are not copied here.
This record separates local reproduction from installed-connector verification.

## Reproduction and fix

A synthetic three-page PDF failed with the private service's configured parser
and OCR paths, before any worker launch. The chained local cause was
`Invalid temporary extraction location`. On this packaged Windows host, the new
job directory resolved into redirected AppData while the jobs parent retained
its logical spelling. The resolved job parent and intended jobs directory were
the same filesystem object, verified with `samefile`, despite failing the old
lexical `is_relative_to` check. This is a reproduced local cause consistent with
the report; the report's generic errors alone do not prove its internal stage.

The corrected check requires the resolved job's immediate parent to be the same
directory object as the intended jobs directory. An escaping directory is still
rejected before document bytes are written. No sandbox capability, permission,
resource limit, network rule or selection rule was relaxed.

Embedded-text reads and page rendering now run without optional OCR dependencies.
Only OCR jobs require those libraries/models. Missing OCR does not block existing
text or pixels; low-text pages retain explicit partial coverage and safe errors.

Processing failures carry bounded reason/stage fields. Observed worker exits
carry a numeric code; unknown exit causes remain unknown. The MCP request ID
correlates safe server diagnostics without raw stderr, document text, paths,
signed URLs or credentials. Status and unread search preserve these fields.
The status tool explicitly tracks text extraction, not rendering history.

Missing-hash continuation is rejected after authorization and before downloading
or parsing. Failed reads remain retryable on a later authorized request.

The first installed-service retest uncovered a second deployment issue: the OCR
setting used a logical AppData path whose installation was actually in the
packaged host's physical cache. The physical model and native library were
verified, and only the private OCR-root setting was changed to that location.
No credential or selection setting changed. OCR-location changes now invalidate
cached partial results, and missing installations have a specific safe reason.

## Validation

- Initial Windows worker controls: **5 passed** (text extraction, render variants,
  private file/environment/network/process/runtime-write denial, memory limits).
- Focused regression/reading/rendering/download/search checks: **148 passed,
  2 skipped** because OCR was not enabled in that test invocation.
- Full suite with the installed English OCR runtime enabled: **579 passed,
  20 skipped** in 148.40 seconds. Skips were 13 Linux-kernel checks and seven
  checks requiring an explicitly configured disposable PostgreSQL database.
  The OCR tests passed in this run.
- After the live OCR finding, cache-invalidation and missing-installation
  regressions plus reading/workbook checks: **72 passed**.
- A subsequent full run was affected by another worker changing the shared
  parser from v5 to v6 during execution: **576 passed, 5 failed, 20 skipped**.
  All five failures were parent/worker parser-version mismatches; they were not
  accepted as successful parsing. This condition now has the explicit safe code
  `DOCUMENT_PARSER_VERSION_CHANGED` and requests a service restart. A fresh
  process is used for the follow-up checks against the current shared sources.
- Final fresh-process regression/workbook/visual run with English OCR enabled:
  **72 passed** in 73.59 seconds, including all five previously affected tests,
  the new explicit parser-version rejection and both real OCR tests. No further
  code changes followed this run. Ruff and `git diff --check` also passed.
- Separate synthetic verification with the private service's configured parser
  and OCR roots: embedded text passed for three pages; a scan produced actual
  English OCR with partial coverage; PNG rendering returned bounded pixels.
- Regression coverage includes AppData directory aliasing, escaping paths,
  runtime/worker/output failures, cleanup and lock release, safe reason filtering,
  continuation guards, failure status/search propagation, and recovery on retry.
- An authenticated local HTTP MCP test uses the real Windows worker, renders
  before text extraction, reconstructs short text chunks, checks hash guards,
  exercises the alternate material reader and finds an indexed page passage.
- Ruff and `git diff --check` passed.

No claim is made about complete reading order, table/equation fidelity, universal
OCR accuracy, arbitrary malicious-PDF resistance, Linux runtime validation from
this Windows run, or live connector image visibility from local MCP success.

## Installed service

The owner handled the first restart. The installed connector then exposed the
updated diagnostics and completed bounded reads for the two embedded-text
documents, a render-first request with an actual MCP image block, the alternate
material reader, and two sequential one-document search batches. Search advanced
from one to two completed documents with zero failed documents and retained
partial coverage for the first document and the unsearched inventory.

The scanned schedule initially returned explicit partial data with an OCR
runtime-setup failure, leading to the separate path correction above. After the
owner confirmed the next restart, the installed connector returned OCR text
using the current v6 parser: 1,500 characters in the initial bounded response,
English OCR method, mean confidence 79/100, and explicit partial coverage.
A subsequent 500-character continuation retained the same original-byte hash.
Rendering that same scanned page returned a standard MCP image block at
1,855 by 2,400 pixels with the matching original-byte hash. A missing-hash
continuation returned `CONTINUATION_HASH_REQUIRED` without returning text.

| Report finding | Resolution / evidence boundary |
|---|---|
| PDF-F1 text reads | Two embedded-text originals and the scanned original now return text through the installed connector |
| PDF-F2 rendering | Both render-first and scanned-page requests return actual MCP image blocks; visual interpretation accuracy is not claimed |
| PDF-F3 alternate reader | Original material reference returns text through the installed connector |
| PDF-F4 diagnostics | Safe stage/reason/observed-exit fields; live OCR setup failure was distinguishable and corrected |
| PDF-F5 argument validation | Existing negative checks retained; hash guards tested in real local MCP and installed calls |
| PDF-F6 bounded search | Two one-document live batches advanced with zero failed documents; coverage stayed explicitly partial |
| PDF-F7 hash guard | Installed missing-hash guard and valid continuation verified; mismatch and full reconstruction verified with synthetic real-worker MCP |
| PDF-F8 status scope | Status explicitly describes text extraction and reports rendering history as not tracked |

Before/after installed connection-status checks confirmed the same selected
courses, connection identity and active state. No credentials, Canvas records
or Calendar data were changed by this work. The sole private configuration
change was the OCR installation path; read tools maintained their usual
authorized inventory/text caches. No private report, academic text, image,
receipt, file ID or operator configuration was added to the repository.
