# Scientific document comprehension v3

This local implementation adds a bounded scientific document model and an
evidence-linked explanation contract to the existing read, render and figure
tools. It does not establish deployed ChatGPT visual acceptance or scientific
interpretation accuracy. Those remain separate gates below.

## Source structure and authorization

`read_course_file` now returns `document_model` (`scientific-document-3`) alongside
the existing bounded text. It binds each original unit to the source file ID,
content hash, source version, original locator, extraction state and inherited
source permissions. The model cannot grant access. Existing selected-course,
source authorization, retention, privacy and final recipient egress checks still
apply. Source text, XML attributes and embedded instructions remain untrusted data.

| Format | Stored evidence | Explicit limits |
|---|---|---|
| PDF | Original page, text blocks, caption candidates, page requiring visual discovery | Embedded text does not establish table geometry, equation layout, script roles or image content |
| PPTX | Original slide order and hidden state; paragraph runs, stored tables, captions, OMML, image geometry when present, separate speaker notes | Notes and XML order are not observed pixels; conversion needs the existing renderer and fidelity checks |
| DOCX | Original paragraph/table/equation locators, cell coordinates/spans, source-declared headers, subscript/superscript runs and OMML operator trees | Document-wide structure is attached to the first text section; section numbers are not Word page numbers; no verified visual renderer |
| XLSX | Sheet and cell coordinates, merged ranges, hidden state, lexical numbers, formatting runs, stored formulas and cached values | Formulas are not executed; header semantics, units and missing values are not inferred; no verified visual renderer |

The parser version changes to `canvas-bridge-documents-v11-scientific-structure`,
invalidating older extraction caches through the existing version mechanism.
The isolated Windows and Linux parser runtimes include the same structure helper.
Privacy-redacted units discard their structural aliases; incomplete auxiliary
privacy coverage withholds structure as well as the existing protected fields.

Structure is capped at 80 items per category, 400 cells per table, 80 KB per unit,
120 KB per document and 60 KB in a read response. OMML trees have node/depth limits.
Omitted structures and incomplete equations/tables are explicit. Missing
relationships never become inferred formulas, header meanings or numerical values.
The existing text, archive, memory, process-time and render limits still apply.

## Retrieval and visual evidence

Use the existing overview, file search and text index before rendering selected
original units. `inspect_course_figure` accepts the original `page` argument
(slide number for PPTX), a figure/table/panel label, or an optional literal `query`.
Queries search stored text, including available slide notes; they cannot discover
the meaning of an image-only pathway. An unmatched query or label is explicitly
unresolved. Continuations bind the source version, hash, scope epoch, query and
remaining time/image/attempt budgets.

For “explain slide 22,” render original slide 22. For “compare slides 8 and 14,”
retrieve those two original slides separately and retain both citations. For
“which lecture explains this pathway,” search the selected course files first,
then inspect promising sources. Long decks use the existing overview/text
continuations and selective rendering; this change does not require a full-deck
high-resolution render.

The sequence remains authorized source, privacy/egress check, structure and
candidate discovery, bounded render, supported host delivery, actual pixel
inspection, attributed report and grounded explanation. A PPTX subset rendered
as PDF page 1 retains the original slide in its receipt and citation. PDF and
PPTX reports use format-specific signed receipts, current source metadata,
expiry, scope epoch and hash-bound extracted text.

`auto`, `native`, `reader` and `text` retain the existing delivery policy. An
operator-verified exact client build can use automatic native delivery. Otherwise
the existing authorized reader is the fallback. A successful response, image hash,
dimensions or conversion receipt never changes model visibility to established.
If the host drops the pixels, report unavailable and retry the supported reader;
if neither path exposes pixels, there is no visual answer. Word/Excel requests
return `VISUAL_FORMAT_UNSUPPORTED` and an authorized text read fallback.

## Explanation contract

After actually seeing pixels, `record_course_figure_observation` accepts the
existing panel schema with experimental variables, controls/treatments and panel
relationships, plus `image_quality` and optional `scientific_explanation`.

Each explanation claim has a unique ID and one basis:

- `visual_observation`: indexes into attributed direct observations.
- `source_text`: an exact quotation from the current original page/slide.
- `inference` or `scientific_context`: earlier evidence claim IDs and explicit uncertainty.

The response separates direct explanation, observed evidence, textual evidence,
context, conclusion support, limitations and original source locator. Axes,
units, legends, significance, error-bar meaning and unknown fields remain empty
unless observed. Numerical visual claims require structured readings with region
and precision; estimates retain uncertainty. Exact quote and reference checks
reject mismatched anchors, missing observations and unsupported numeric tokens.
They do not prove that a paraphrase follows from its quotation or that a model
read a graph correctly. Those semantic judgments require independent review.

Unavailable pixels cannot have assessed image quality or visual observations.
Insufficient-resolution or important-details-unreadable reports cannot supply
scientific observations. Partially readable images may support explicitly limited
claims. Explanation requires a confirmed figure and stated adequate readability.
Rendering failure and unsupported conversions remain failures, not reconstructions.

Visibility is an **attributed assistant report**, not independent server proof.
`interpretation_verified` remains false. These results stay in the conversation;
this change neither overwrites extracted source text nor saves new academic records.

## Reproducible scientific fixtures and evaluation

`benchmarks/scientific/v3` contains ten original fictional image-heavy PDF pages
and their PNGs: western blot, flow cytometry, qPCR, mass spectrometry, microscopy,
cell signaling, dose response, confocal imaging, multi-panel figures and complex
table headers. Seeded authoring is in `scripts/build_scientific_fixtures.py`;
runtime/CI use committed bytes and need no authoring dependencies. The manifest
binds every asset and case to SHA-256. The fixture-only license is CC0-1.0.

Existing synthetic vector/EMF decks and tests remain part of the regression suite:
`tests/test_emf_worker.py`, `tests/test_presentation_subset.py`,
`tests/test_presentation_rendering.py`, `tests/test_presentation_derivatives.py`
and `tests/fixtures/synthetic_visual_slides.pptx`. Synthetic converter fixtures
test mapping and failure handling; they are not evidence of native Office fidelity.

```powershell
.venv/Scripts/python.exe -m canvas_bridge.scientific_benchmark
.venv/Scripts/python.exe -m pytest tests/test_scientific_comprehension.py -q
.venv/Scripts/python.exe -m canvas_bridge.scientific_benchmark --responses responses.json --reviews reviews.json --require-reviewed
```

The first command measures exact candidate retrieval by label and literal query.
Interpretation is a separate metric, null when no independently reviewed answers
exist. It never promotes retrieval success to comprehension accuracy. Exit codes
are 0 for requested gates passing, 1 for a failed gate, and 2 for invalid input.
Any reviewed interpretation failure fails the run. `--require-reviewed` also
requires all ten cases, preventing a small reviewed subset from passing release.
The saved JSON records the requested gate and its result, source/corpus hashes,
runtime/dependency information and execution time. DNS and socket connections
are blocked during evaluation. No confidence interval is asserted for this curated census.

External response intake requires exact `corpus_sha256`, a system `id`, `version`
and actual `execution_reference`, and `observations`. Each observation binds
`case_id`, the exact PNG `image_sha256`, and a valid `FigureObservation` including
its structured explanation. Additional unscored response fields are rejected.
Review intake has a `reviews` list. Each review must bind the case, corpus,
observation and rubric hashes (canonical JSON SHA-256 via
`benchmark_lab.dataset.digest`), provide a distinct human `reviewer_id`,
`reviewer_kind: human`, `expertise`, `review_record`, timezone-aware
`reviewed_at`, `rubric_expert_reviewed: true`, and a boolean for every required
rubric dimension. Hash mismatch, future date, missing dimension or model-only
judgment fails. Human identity/expertise are external attestations, not locally
authenticated facts. Unit-test fictional reviewers do not constitute real review.

Every ordinary CI run generates a retrieval report. The larger academic workflow
also runs the scientific tests/report. Its `scientific_interpretation_release`
input requires fully reviewed answers from `benchmarks/scientific/reviews/`.
That input must be enabled before advertising validated scientific interpretation.
The existing academic comparison lab independently guards grade/privacy outcomes
and compares actual previous reports; no competitor or baseline-model execution
is invented here.

## Acceptance status

See the [local execution record](../evidence/sanitized-results/scientific-comprehension-v3-2026-10-26.md).
The implementation and deterministic synthetic checks are locally reviewable.
Expert rubric approval, independently judged interpretation results, current
deployed host visibility/fallback acceptance and native-conversion acceptance
remain outstanding. DOCX/XLSX visual comprehension remains unsupported. These
limits prevent claiming the full end-to-end scientific comprehension definition
of done from extraction, tests or fixture layout inspection alone.
