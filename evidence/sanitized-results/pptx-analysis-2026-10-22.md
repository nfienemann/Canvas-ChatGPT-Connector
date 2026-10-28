# PPTX analysis validation — October 22, 2026

## Status and acceptance boundary

**Partial implementation; definition of done is not met.** Local large-PPTX
extraction and structured slide records are implemented. The optional Windows
whole-slide converter is experimental and disabled. Native rendering did not
produce a slide image within its budget; scientific fidelity and actual host
pixel visibility are not established. No Lecture 2 summary is claimed.

The installed private connector was queried using its existing authorized
connection and exact opaque file references. Inventory again found the acceptance
deck at **14,176,811 bytes**, and the installed `read_course_file` returned
`unsupported_feature / FILE_TOO_LARGE / file_download`, limit **10,000,000**.
No content was returned. Inventory was partial, not complete course coverage.
Connection status still advertised a separate 52,428,800-byte original maximum,
131,072-byte inline maximum, native attachment unimplemented and host support not
negotiated. No settings, selection or credentials were changed, and the service
was not restarted/deployed. IDs, private URLs and course contents are omitted.

Other discovered regression-deck source sizes were 1,622,850, 15,495,687 and
41,189,003 bytes. Their scientific contents and new-code live behavior were not
verified. The last is intentionally above the 32 MiB standard extraction cap.

## Implemented changes

- `document_policy.py`, `file_download.py`, `config.py`, `.env.example`: separate
  32 MiB PPTX source cap / 60 s download budget, bounded streaming with unknown
  size support, source quota diagnostics retaining the legacy error code, and
  one active analysis download per process. Other extraction formats remain 10 MB.
- `presentation_worker.py`, `parser_worker.py`: bounded ZIP/XML validation;
  presentation-order slide text, tables/text boxes, notes and stored chart text;
  provenance spans; blank/image-only records; media gaps and partial failures.
  Parser version is `canvas-bridge-documents-v8-presentation`.
- `course_files.py`, `parser_sandbox.py`, `linux_sandbox.py`: validated structured
  results, eight-slide / 8,000-character windows, hash-bound continuations and
  cache invalidation, resource counters, existing current-access/epoch fences.
- `presentation_render_worker.py`, `presentation_runtime.py`, `windows_sandbox.py`,
  `visual_files.py`: disabled experimental conversion through the existing page
  endpoint, bounded native child, package/media checks, private profile cleanup,
  typed failure and version checks. Native success remains blocked.
- `service.py`, `file_delivery.py`, `app.py`, `visual_ui.py`, `ui/page-reader/reader.js`
  and regenerated `assets/page-reader.js`: capability/budget distinctions and
  existing authenticated image transport adapted to slide labels. No public
  image URL, new overlapping endpoint or native-attachment promise.
- `tests/test_presentation_reading.py`, `tests/test_presentation_rendering.py`,
  synthetic fixture/generator, existing office security expectation, and
  `docs/pptx-reading.md`: regressions, boundaries and operator documentation.

Pre-existing delivery-roadmap/documentation edits and
`scripts/diagnose_download_handshake.mjs` were present before this task and were
preserved. No private records or native renderer binaries were added to Git.

## Checks and measured resource impact

Targeted extraction/transport/security tests exercised below/exact/over cap,
14,176,811 bytes, 25,000,000 bytes, 25 MiB, 32 MiB, unknown Content-Length,
unknown metadata size, abort/close behavior, ZIP traversal including Windows
backslash normalization, member/XML/ratio/slide limits, active content, DTDs,
chart/notes provenance, blank slides, stale/revoked access and false observations.
Existing transport tests cover cancellation, 401/403/404/429/5xx and stale sizes.
The DOCX deadline-matching regression remains in the full regression selection.

Real Windows AppContainer extraction benchmark (synthetic stored-media padding;
two text slides, **not** a scientific image-complexity benchmark):

| Source bytes | Elapsed including setup/cleanup | Worker peak committed bytes | XML bytes read | Worker JSON bytes |
|---|---:|---:|---:|---:|
| 14,176,811 | 5,177 ms | 73,572,352 | 597 | 1,804 |
| 25,000,000 | 1,631 ms | 73,940,992 | 597 | 1,804 |

Both succeeded on the final code; emitted extraction JSON was 1,914 bytes. The
first measurement includes a cold runtime build. Peak aggregate Job memory was
74,776,576 and 75,169,792 bytes respectively. This measures worker
commit, not service-wide RSS. Parent source buffers, filesystem caches and the
native renderer are not included in those peaks. No production latency/failure
rate is inferred from two synthetic samples. Runtime metrics contain numeric
resource facts, not slide contents, tokens, URLs or operator paths.

The focused PPTX/visual/MCP run completed **65 passed, 2 skipped**; the skips
were the unavailable optional OCR installation. An additional source/worker run
completed **38 passed**. Subsequent preflight/Unicode tests were included in the
full run. Final full-suite and static-check results are recorded below;
earlier failing development runs are not release-pass evidence.

Final checks on the completed working tree:

- `.venv/Scripts/python.exe -m pytest -q`: **740 passed, 22 skipped**, 201.39 s.
  Skips: 13 Linux-kernel cases, 7 disposable-PostgreSQL cases and 2 optional OCR
  cases. The DOCX locator/deadline matcher and PDF/XLSX/delivery regressions pass.
- `.venv/Scripts/python.exe -m ruff check .`: passed.
- `.venv/Scripts/python.exe -m ruff format --check .`: 164 files formatted.
- `git diff --check`: passed.
- Native reader JavaScript bundle rebuilt successfully with the bundled Node
  runtime. No package/dependency upgrades were required.

Earlier development failures were an obsolete “PDF only” assertion and a corrupt
image fixture that also contained an external relationship. The assertion and
fixture were corrected; render preflight now uses deterministic part ordering.
The complete rerun above passed after those changes. These test results do not
upgrade the separate failed native-render or pending live-service gates.

A final read-only status check confirmed the connection remained active with the
same four selected courses, including the acceptance course. The new
`file_analysis` capability object was absent from that installed service, which
still advertised the independent 50 MiB original-delivery limit.

## Native rendering investigation: BLOCKED

A public LibreOffice 26.8.1 administrative image was downloaded and verified
against its published SHA-256. The version probe returned 26.8.1.1. The renderer
was extracted locally for testing; it was not configured in the private service.
Windows extended paths were required for deep runtime files and ACL setup.

Multiple synthetic AppContainer attempts ended as
`SLIDE_RENDER_RESOURCE_LIMIT`, stage `slide_rendering`, category `render_timeout`.
A synthetic reference conversion outside the sandbox also failed to finish in
its bounded attempt. A short-path probe returned normal bootstrap restart code
81; its bounded retry also timed out. No real academic file was processed outside
the sandbox. No surviving soffice process was observed after the attempts.
Normal text/PDF workers retain their original process restrictions.

The MCP image contract test supplies a **synthetic substitute rendering**, proving
image-block serialization, slide citations, post-read version fencing and access
revocation only. It does not prove LibreOffice conversion, host-visible pixels,
correct scientific interpretation, or the live lecture acceptance gate.

Automatic approval review rejected deletion of generated runtime caches with
“blocked by policy”; cleanup was not retried through another mechanism. The
temporary public runtime, installer and validation caches remain outside Git.

## Grounded example, synthetic source only

Actual XML extraction of `tests/fixtures/synthetic_visual_slides.pptx` returned:

> This fictional deck concerns fluorescence controls (slide 1 title). Its speaker
> notes warn that spot counts alone cannot establish efficacy (slide 1 notes).
> Slide 2 contains an image without extracted text; slide 3 is hidden and has no
> extracted text. None of the slide images has been visually interpreted.

This is an example of calibrated text grounding, **not** a summary of the real
acceptance lecture. Image-derived claims and a complete deck review remain absent.

## Required next evidence

1. Resolve native startup within the declared sandbox/resource budgets; validate
   complete slide rendering, hidden indices, font substitution, corrupt media,
   cancellation and process-tree cleanup without weakening isolation.
2. Re-run security/fidelity checks before enabling the rendering flag. Review the
   monitored staging limit (not a hard disk quota) and fleet/concurrency controls.
3. Load the reviewed build in the authorized private service, then perform actual
   MCP reads of the regression decks. A local synthetic pass is not deployment.
4. Receive and inspect representative real slide pixels in the client. Compare
   the resulting cited summary with manual slide review; disclose every unread
   slide/visual. Only that can satisfy the Lecture 2 scientific-fidelity gate.
