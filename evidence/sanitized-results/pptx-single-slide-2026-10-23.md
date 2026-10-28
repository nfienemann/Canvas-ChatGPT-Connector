# Single-slide PPTX conversion — October 23, 2026

## Scope and root cause

The user authorized one-slide conversion using LibreOffice, unchanged safeguards,
targeted tests only, and exactly one real acceptance-slide attempt. No whole-deck
conversion was repeated. No Canvas writes, credential changes, selection changes,
server restart, saved feature-flag change or deployment occurred.

Native startup had been repaired through nested public runtime packaging and
LibreOfficeKit VCL-thread dispatch. Synthetic conversion worked. Whole-deck import
continued to fail near the process-memory ceiling, without a proven native OOM
diagnosis. Limiting native input to the selected slide resolved the tested case.

## Implemented changes

- `presentation_subset.py`: dependency closure, bounded temporary package,
  original slide order/hidden flag, namespace preservation, dynamic slide-number
  freezing, ambiguous cross-slide dependency rejection. Original source untouched.
- `presentation_render_worker.py`: full-source preflight remains; native input is
  one slide, PDF must contain one page; source count and mapping remain explicit.
- `presentation_derivatives.py`: selection-aware manifest validation and cache;
  source/PDF hashes remain distinct; version/epoch/backend changes evict old entries.
- `presentation_pipeline.py`: selection passed into conversion; original source
  count drives reader navigation; authorization and source fences retained.
- `parser_sandbox.py`: package the subset module in the isolated runtime and
  validate returned mapping against the requested slide.
- Targeted subset, rendering and derivative tests and operator documentation.

No new public tool: existing `render_course_slide` and the page-tool compatibility
route reuse the existing PDF renderer, native reader and image-response helper.
Text extraction, sandbox controls and response size limits were not changed.

## Actual authorized local acceptance — one attempt

| Measurement | Observed |
|---|---:|
| Original source | 14,176,811 bytes; 25 slides |
| Requested original slide | 14 |
| Internal PPTX | 773,842 bytes; 44 members |
| Original slide image references | 6 |
| PDF | 542,809 bytes; 1 page |
| Mapping | Original slide 14 -> PDF page 1 |
| Authorization | 526 ms |
| Authenticated source fetch | 1,936 ms |
| Conversion stage | 13,064 ms |
| Peak process committed memory | 280,686,592 bytes |
| Peak aggregate Job commitment | 323,297,280 bytes |
| PDF rasterization | 1,504 ms |
| Rendered pixels | 2,400 x 1,350 |
| PNG response estimate | 1,060,194 bytes |
| Authorization-state fingerprint | Unchanged before/after |

The normal image-response helper prepared an MCP ImageContent block and original
Slide 14 citation. The PNG was then supplied to Codex through its native local
image-viewing tool; the model actually inspected it and produced a content-grounded
description. This verifies local conversion/rasterization/model-visible pixels,
not the installed ChatGPT plugin or its reader-button flow. Server events correctly
leave host delivery/model interpretation unconfirmed, rather than inventing receipts.

Six image references were preserved as dependencies. Visible material overlaps in
the upper-right region; six references do not establish six separate fully readable
panels. Without an independent PowerPoint rendering, overlap cannot be classified
as original layout versus conversion loss. No claim of complete fidelity is made.

The first rendered image showed a renumbered footer of 1 while provenance correctly
identified original slide 14. Dynamic slide fields are now frozen to their original
number. The correction passes a synthetic hidden-slide native PDF text assertion;
the real slide was deliberately not rerun. Private PNG and metadata remain outside
Git. No source content, screenshots, identifiers, tokens or personal records appear
in this repository evidence record.

## Targeted checks

- First focused run: 32 passed, 2 opt-in native skips.
- Explicit native image-heavy and hidden-slide cases: 2 passed in 30.80 s.
- Final focused run: 42 passed, 2 opt-in native skips in 7.75 s. Includes subset,
  mappings, source mutation/manifest tampering, cache isolation/expiry/revocation,
  real synthetic MCP image transport, corrupt/unsafe media, staging limits,
  PPTX substantial-source/text/notes/chart regressions, DOCX locator/deadline,
  PDF reading and XLSX types/formula/date/hidden-sheet regressions.
- After footer correction: explicit native hidden-slide/number-field case passed
  in 16.70 s. No real conversion repeated.
- Targeted Ruff lint/format and scoped whitespace checks passed. A repository-wide
  whitespace check also reported an unrelated concurrent edit in
  `docs/visual-pdf-reading.md`; that file was left untouched.
- Full suite intentionally not run per budget/scope. Historical full-suite results
  are not presented as validation of this change.

## Remaining gates and operator steps

Source 32 MiB, expansion 64 MiB, 384 MiB process / 512 MiB Job, CPU/process-count,
no-network AppContainer, timeout, output, staging and TTL limits remain unchanged.
Stored temporary ZIP members avoid creating new extreme compression ratios; an
expanded selected subset over the source ceiling is rejected. Cross-slide links
that introduce another slide fail closed. Unsupported objects remain unsupported.

For installed-client validation, configure the trusted public runtime and reviewed
rendering flag, restart the existing private server, refresh the connector tool
catalog and obtain a fresh reader. No database migration is required. These steps
were not performed in this run. The ordinary ChatGPT end-to-end release gate,
remaining representative slides, full-deck visual coverage and a portable converter
backend remain pending. Do not repeat the real fixture without further user scope.
