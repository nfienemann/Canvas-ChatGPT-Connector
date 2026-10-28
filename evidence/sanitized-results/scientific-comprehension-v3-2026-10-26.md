# Scientific document comprehension v3 — local verification

Executed October 26, 2026 using fictional fixtures in the existing Windows
checkout. This is backend, parser and synthetic protocol evidence. No real course
record, live Canvas request, deployment, service restart or permission change was
required. Original release gates remain in force.

## Implementation and fixtures

The existing read path now exposes a source/hash/original-locator document model.
OOXML tables, formatting runs, math structure, captions and notes remain distinct.
The existing figure tool supports bounded PDF/PPTX discovery and rendering, and
structured-only Word/workbook fallbacks. Grounded explanation separates visual
reports, exact text anchors, inference, scientific context and limitations.
Unreadable images and unsupported numeric assertions fail explicitly; render
receipts never prove visual inspection.

Ten CC0 fictional figure types have image-heavy PDF/PNG fixtures with exact
manifest hashes. All ten rendered PDF pages were visually inspected for layout.
The review caught and corrected overlapping qPCR labels and a missing table
group-header label; the two corrected pages were re-rendered and re-inspected.
Poppler emitted missing display-font warnings, but the rendered labels and plots
were visible in the inspected pages. This layout check is not independent expert
scoring of an evaluated model's interpretation.

## Executed checks

- `pytest -q --tb=short`: 1,581 passed, 28 environment-dependent skips, three
  failures during implementation. The failures were obsolete expectations for
  existing deployment preflight and personal/offline authorization behavior.
- After correcting those assertions, the complete desktop, personal and MCP
  contract test files passed: **19 passed**. Damaged keys remain intact, failed
  startup releases its lock, owner isolation remains enforced, and fixture-only
  live selection requires explicit enablement. Production authorization was not
  weakened to make tests pass.
- Final scientific-specific run: **31 passed**, including source numbering,
  table/math structure, privacy projection, resource limits, unsupported formats,
  unreadable images, attribution, numeric evidence, network blocking, hash-bound
  human review intake and rejection of an unreviewed release gate.
- A final affected-file run covers scientific, PDF, DOCX, spreadsheet, PPTX,
  figure, privacy, provider, vector/EMF, subset, derivative and renderer tests.
  **330 passed, four native-converter checks skipped.** Exact results are recorded
  in `scientific-comprehension-v3-2026-10-26-checks.json`.
- Ruff check and format check passed across `src`, `tests` and `scripts`.
  Bandit passed for the six scientific/figure modules. `git diff --check` passed.
  `canvas-bridge compliance-report --validate-only` returned a valid registry
  with 23 controls and `authorization_granted: false`.

The broad run occurred during implementation; final affected tests verify the
later scientific hardening. No second full repository run was substituted for
the recorded affected checks. Skipped checks require a trusted native converter,
a Linux kernel, a disposable PostgreSQL database or an installed OCR runtime.
Synthetic converter/mapping tests do not certify native Office/EMF fidelity.

## Benchmark results and evidence boundaries

`scientific-comprehension-v3-2026-10-26.json` records **10/10 deterministic retrieval
cases**, zero network attempts, interpretation accuracy **null**, and **0/10
independently reviewed interpretations**. The `--require-reviewed` run intentionally
exited 1; its separate `-review-gate.json` records that failed gate. Retrieval is
not promoted to scientific accuracy.

`scientific-comprehension-v3-2026-10-26-academic.json` records **81 objective cases
passed**, two interpretive cases still requiring review and **zero regressions**
against the actual preceding evidence-graph report (83 paired tasks). No external
model, alternative repository or unexecuted previous stable version is claimed.
Source/corpus fingerprints were checked against the final checkout and fixtures
before preserving these reports. Timing is not used for a comparative speed claim.

The full end-to-end scientific comprehension definition of done remains gated on
independent expert rubric/answer review and current deployed client pixel-delivery
and fallback acceptance. Word/Excel visual rendering is unavailable. Native
conversion fidelity is not established by this run. An attributed assistant
report of visibility is not independent server proof of scientific correctness.

See [implementation contract](../../docs/scientific-document-comprehension-v3.md)
and [release gates](../release-gates.md).
