# PPTX visual pipeline follow-up — 2026-10-22

Release state: **BLOCKED, not operational end to end.** This record supersedes
the earlier observation that the installed connector still enforced 10 MB. It
does not supersede the broader institutional/public release gates.

## Root cause and implemented changes

Before edits, live connection status reported PPTX rendering disabled, and a
slide-14 render returned `PPTX_RENDERER_UNAVAILABLE` before conversion. The code
had a single-slide converter prototype, no retained PDF derivative, no named
slide tool and a null extraction visual fallback. The original PDF reader and
MCP image response already existed.

The local integration now provides `render_course_slide`, a PPTX compatibility
path from `render_course_file_page`, a private bounded PDF derivative cache,
source/derivative hash separation, source version and epoch fencing, hidden-slide
metadata, whole-deck export validation, standard/high PDFium rasterization,
sanitized stage diagnostics and a v4 native reader. Text extraction is preserved.
See [the pipeline document](../../docs/pptx-visual-pipeline.md) for contracts,
limits, exact restart steps and unresolved mapping/fidelity gates.

Real-deck preflight then identified SVG media as an additional blocker. Static
self-contained SVGs are now validated and accepted. Active content and external
references remain denied. The actual file now passes preflight and reaches
LibreOffice, where isolated conversion times out. Native startup cause is still
unresolved. No safety limit or authorization boundary was bypassed to obtain a
real render.

## Changed files in this follow-up

- `src/canvas_bridge/presentation_pipeline.py`: orchestration and stage events.
- `src/canvas_bridge/presentation_derivatives.py`: manifest validation, typed
  conversion errors, private scoped TTL/capacity cache.
- `src/canvas_bridge/presentation_render_worker.py`: full-deck PDF export,
  count/geometry validation, hidden flags, static SVG checks, bounded startup.
- `src/canvas_bridge/parser_sandbox.py`: bounded PDF result transfer and sanitized
  resource diagnostics on success/failure.
- `src/canvas_bridge/visual_files.py`, `visual_worker.py`: compatibility dispatch
  and reuse of PDFium at bounded 1600/2400-pixel edges.
- `src/canvas_bridge/app.py`, `course_files.py`, `service.py`, `linking.py`: new
  read-only tool/fallback, truthful budgets, cache expiry and revocation cleanup.
- `src/canvas_bridge/visual_ui.py`, `ui/page-reader/reader.js`, generated
  `assets/page-reader.js`: v4 reader, fresh slide/source validation, original
  slide provenance and explicit missing-client-support message.
- `tests/test_presentation_derivatives.py`, `test_presentation_rendering.py`,
  `test_visual_ui.py`, `test_personal.py`: lifecycle/security/transport/UI/catalog
  and opt-in real native-converter checks.
- Pipeline, reading and release documentation, including this record.

Pre-existing original-download documentation/worktree changes were preserved.
No commit, upload, server restart, saved renderer enablement, credential change,
course-selection change, Canvas write or public deployment was performed.

## Actual acceptance evidence

| Gate | Actual observation | State |
|---|---|---|
| A: text extraction | Installed plugin v8 reports 25 extracted slides; bounded reads address slides 1–8, 9–16, 17–24 and 25 with a consistent source hash | PASS for text records |
| Slide 14 text/media | Live read returns only `14` as text, six embedded-image references, no visually inspected slides | Confirmed text/media metadata only |
| Authorized real acquisition | Local integration probe downloads exactly 14,176,811 bytes through existing authorization/download functions | PASS in-process; not a newly deployed MCP call |
| B: complete PDF | Real source passes static-SVG preflight, then returns `PPTX_CONVERSION_TIMEOUT` | BLOCKED |
| C: image-heavy slide 14 | No PDF or PNG generated from the actual source | NOT PASSED |
| D: slides 3, 12, 14, 22, 25 | Text records accessible; scientific visuals and fidelity not inspected | NOT PASSED for visuals |
| E: all 25 slides | Text addresses exist; complete visual addressability/cache reuse only has synthetic contract evidence | NOT PASSED for real visual deck |
| F: security/failure contracts | Fresh access, cache isolation/expiry/epoch/version fencing, revocation after rendering, static SVG denial, corrupt manifests, bounded errors and missing UI support tested synthetically | Automated results below |
| G: actual ChatGPT explanation | Live existing tool remains disabled; no actual model-visible pixels or scientific interpretation | BLOCKED |

The private local probe hashes credential/epoch/state/selected-course fields
before and after; it reports `authorization_state_unchanged=true`. It does not
print those values. No real source bytes, images or scientific slide text were
added to repository fixtures. Successful download or an image count is never
reported as visual understanding.

## Native investigation and resource evidence

- Trusted public LibreOffice 26.8.1 runtime from the earlier verified download.
- Fictional deck outside isolation: conversion completed in **29.17 seconds**,
  two pages under default hidden-slide exclusion. This was a diagnostic baseline,
  never a production path or real-course fallback.
- Isolated synthetic converter: 60-second timeout; observed peak process
  committed memory approximately **201 MB**, aggregate Job approximately **229 MB**.
- Final actual source after SVG support: authorization **481 ms**, authenticated
  fetch **2,292 ms**, conversion/setup failure **63,959 ms**. Peak process committed
  memory **201,359,360 bytes**, aggregate Job **242,438,144 bytes**. Conversion returned
  `PPTX_CONVERSION_TIMEOUT`; registration/render/delivery/interpretation remained
  `not_attempted`. Credential/epoch/state/course-selection fingerprint unchanged.
- Existing protections remain: 32 MiB PPTX source, 64 MiB expansion, XML/member
  caps, 384 MiB per process / 512 MiB aggregate, 10 s CPU per process / 20 s
  aggregate, two processes, 75 s outer deadline, 128 MiB monitored staging.
- PDFs are capped at 10 MB to reuse the existing PDF pipeline; four / 40 MB total
  may be retained in private memory for ten minutes. Native images remain 1.3 MB.
- No surviving diagnostic renderer processes or real worker job files remained
  at the final process/workspace check. Public runtime and synthetic diagnostic
  caches remain outside Git. The prior cleanup approval rejection was not retried.

The LibreOfficeKit API was investigated with fictional content only; initialization
succeeded but document loading did not complete. That probe was terminated and
was not added as a production fallback. IPC/bootstrap incompatibility remains a
hypothesis; no invasive runtime patch or relaxed sandbox was introduced.

## Automated checks

- Targeted cross-format run: **163 passed, 2 skipped** (optional OCR).
- Follow-up PPTX/cache/reader run: **79 passed** before adding the opt-in native test.
- The native test requires explicitly supplied trusted runtime paths. Its default
  skip is not a passing conversion or fidelity result.
- Initial full-suite run: **756 passed, 23 skipped, 1 failed** in 196.21 seconds.
  The failure was the old 31-tool assertion after adding the 32nd read-only tool;
  it was corrected. A follow-up personal/cache/UI run passed **42 tests**.
- Final full-suite run: **757 passed, 23 skipped** in **194.66 seconds**
  (`.venv\Scripts\python.exe -m pytest -q`, exit code 0). Skips cover 13 Linux
  sandbox checks on Windows, seven disposable-PostgreSQL checks, the opt-in
  native converter check, and two optional OCR checks. These skips are not live
  conversion or cross-platform acceptance evidence. The suite was not repeated.
- Ruff lint passed; formatting check reported **169 files already formatted**;
  `git diff --check` passed. The native reader bundle rebuilt successfully.

## Remaining work

Resolve the native conversion startup failure without weakening isolation; prove
hidden/blank/reordered-slide mapping and native fidelity; qualify a portable
backend for other supported hosts; then perform the private server restart/catalog
refresh and actual ChatGPT slide-14 pixel/interpretation test. Only after that can
the representative slides and all-slide coverage be accepted. There is no
source-grounded visual summary example to report yet.
