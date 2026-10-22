# Cross-format document stress checks — 22 October 2026

Scope: DOCX, XLSX and PDF. The owner confirmed that all current project changes
should be staged and pushed to `codex/visual-pdf-reading`, and that the repeated
DOCX in the request meant PDF. The initial upload is commit `6ed0f36`.
All newly generated documents and data are synthetic. No private course files,
operator configuration, credentials or databases are included in this record.

## Reproduced gaps and corrections

| Finding | Correction and proof |
|---|---|
| PDF exactly reaching the character cap silently omitted later pages while reporting `text_only` | Report partial coverage and an unread-content warning, including at the real 250,000-character cap; an exact-cap final page remains complete |
| PDF and DOCX could exceed the canonical text cap by a page/section separator | Count separators before adding another page/section; generated PDF inputs exercise small boundary budgets |
| Parent accepted a complete-coverage claim with omitted pages, or a combined text overrun caused by separators | Validate declared versus returned page counts and the complete canonical text budget |
| DOCX accepted ActiveX parts and macro-enabled content types under a `.docx` filename | Reject these packages with the existing `active_office_content` result; a real Windows worker verifies rejection and cleanup |
| XLSX treated unknown cell types with no value as blank | Check the type before blank handling; unknown types remain explicitly unsupported |
| XLSX silently selected the first of duplicate values/formulas/inline strings | Reject ambiguous duplicate elements as invalid workbook structure |
| XLSX rejected omitted row indices despite explicit, consistent cell references | Recover the row from explicit cell references; reject contradictions and preserve sparse coordinates |
| XLSX dropped the default style's number format | Preserve style index zero when a styles table exists, including formula-cache formats; retain raw numeric values |

Parser `canvas-bridge-documents-v7-stress` invalidates earlier extraction caches
on the next authorized read. No permission, download origin, sandbox capability,
memory/CPU budget or maximum response size was broadened. Active Office content
was never executed by the prior parser; the change closes a rejection-policy gap.

## Executed checks

- Existing document suites before fixes: **210 passed** in 98.55 seconds, with
  English OCR configured. This includes reader, search, hash/continuation,
  authorization, rendering, real Windows-worker and local HTTP MCP regressions.
- New regression probes before fixes: **14 failed, 6 passed**; six additional
  separator/parent-validation cases also failed. These are 20 failing test cases,
  not 20 independent defects.
- New stress suite after fixes: **27 passed** in 29.58 seconds. Three generated
  tests each exercise 100 deterministic examples: DOCX run boundaries/Unicode,
  XLSX strings/cell spans, and PDF text budgets.
- First full Windows run: **692 passed, 20 skipped, 3 failed** in 203.76 seconds.
  The three XLSX assertions expected formula caches without the newly preserved
  default number-format metadata. Those assertions now check the new metadata
  as well as the original values. The skips were 13 Linux-kernel tests and seven
  tests needing an explicitly configured disposable PostgreSQL database.
- After correcting the XLSX and Linux fixture assertions, focused workbook,
  PDF-diagnostic and Linux tests: **48 passed, 13 Linux-only skipped** in 15.27
  seconds on Windows. The parser implementation was unchanged by these assertion
  corrections.
- Final full Windows run with English OCR enabled: **695 passed, 20 skipped**
  in 214.30 seconds. All runtime Python changes were committed in `3247adc`;
  the subsequent container changes affect Docker preparation and its proof
  script, not the Windows runtime. Skips are the 13 Linux-kernel and seven
  disposable-PostgreSQL tests covered by the successful Linux test run below.
- Real-worker pressure test: repeated DOCX/XLSX/PDF reads, bounded busy rejection
  under simultaneous calls, successful sequential retries, identical results,
  active-content failure and empty job directories afterward.
- UI bundle rebuild reproduced committed assets. NPM production dependency
  audit found zero vulnerabilities. Python dependency audit found no known
  vulnerabilities; the local unpublished `canvas-bridge` package is not audited
  by PyPI. Ruff lint and formatting checks passed.

## Linux CI follow-up

The initial push's [Linux run](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39850815075)
failed nine tests. Eight path/error fixtures created a parser directory without
the existing required mode `0700`; the ninth CPU-limit test still expected the
old `RuntimeError` rather than the bounded `DomainError` diagnostics. These are
test-contract issues, not evidence that unrestricted extraction is needed.
The fixtures now create mode-0700 directories. The CPU probe requires the safe
exit status/stage and observed termination signal; SIGKILL is not mislabeled as
a proven CPU-specific event. Actual kernel enforcement remains tested in Linux CI.

The [next Linux run](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39851995931)
passed **703 tests, 12 Windows-only skipped** in 77.89 seconds, including
PostgreSQL and real kernel checks. Its later read-only container proof found a
packaging gap: the image prebuilt only the OCR-enabled runtime, but ordinary
text reads now deliberately choose the runtime without OCR. Creating that
missing runtime on a read-only image correctly failed. The Docker build now
prepares both variants without weakening runtime filesystem restrictions.
The container proof also now includes XLSX alongside PDF/TXT/Markdown/DOCX/PPTX,
rendering and scanned-PDF OCR. All six synthetic fixture preparations were
checked locally; actual container execution is validated by Linux CI.

**Final Linux gate: PASS.** [Run 39852501702](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39852501702)
on code commit `51fe012` completed successfully: **703 passed, 12 skipped** in
76.13 seconds. Lint, formatting, dependency audits, reproducible UI assets and
Docker build passed. The image then verified all six document formats and job
cleanup, PDF page-image rendering and actual scanned-PDF OCR while running as
an unprivileged user with no network, a read-only filesystem, dropped capabilities
and `no-new-privileges`. The final evidence-only commit does not change tested
code and skips a redundant CI run.

## Remaining boundaries

This work does not establish deployment of parser v7 in the installed connector.
The serving process must load the matching parser before fresh offset-zero live
reads; old-process version mismatches remain fail-closed. No service restart,
credential refresh, course-selection change or Canvas/Calendar write occurred.

DOCX visual pagination, complete table layout, headers/footnotes/equations;
XLSX formula recalculation, shared-formula expansion and chart interpretation;
and universal PDF OCR accuracy/reading order remain outside the implemented
text-extraction contract. These limits are retained explicitly rather than
reported as recovered content. This finite stress corpus is not exhaustive
malicious-file assurance or public-release acceptance.
