# PDF benchmark coverage mismatch — November 3, 2026

The extraction benchmark previously inferred visual reading whenever parser
coverage was outside a small list of text-only labels. The PDF parser's valid
`partial` coverage therefore produced `visual_reading_claimed=True` for the
synthetic image-heavy PDF, despite executing only text extraction.

The workspace already contained the adapter correction when this follow-up
started; it was preserved. The adapter now reports no visual reading for this
text-extraction operation, independently of the coverage label, and retains
`pixels_require_visual_review`. No parser coverage, benchmark gold, scoring
criterion or independent visual-review gate was weakened.

Added six regressions that execute the image-heavy PDF benchmark using its real
extractor while varying coverage: `text_only`, `partial`, `partial_text`,
`scanned_or_empty`, an unfamiliar future label, and a missing coverage field.
Each must preserve the visual-review limitation and pass the independent gold.

Executed with the repository virtualenv on Windows:

- `python -m pytest tests/test_benchmark_lab.py tests/test_sparse_pdf_ocr.py
  tests/test_file_reading.py -q --tb=short`: **114 passed in 24.07 seconds**.
  Includes `test_full_run_separates_visual_review_from_text_extraction`, the
  previously failing benchmark test. Its full benchmark run is not a full
  repository test-suite run.
- Ruff check and format check of the adapter and benchmark test file: **passed**.
- `git diff --check` for those files: **passed**.

The repository-wide suite was not repeated, as requested. This resolves the PDF
benchmark mismatch recorded during the registrar implementation; it does not
claim a new repository-wide pass, live-client visual interpretation, deployment,
or institutional approval.
