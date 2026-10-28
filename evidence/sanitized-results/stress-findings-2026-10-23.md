# October 23 stress findings: local synthetic validation

Scope: workload action semantics, bounded schedule discovery, OCR diagnostics,
and inventory freshness/completeness. No real academic records or credentials
are included. No private service restart, deployment, Canvas write or Calendar
write was performed for this change. Existing pixel delivery, visual UI and
LibreOffice conversion behavior is outside this change.

Implemented behavior is described in
[the response contract](../../docs/october23-stress-findings.md).

## Checks

- `tests/test_october23_findings.py`: **36 passed**. Includes submitted,
  resubmitted, graded, excused, offline, conflicting and unknown submission
  states; historical/future windows and stable pagination; title/filename/module
  discovery; exact version/hash/page provenance; document/time/access/parse
  limits; classroom activities; successful/partial/failed/budget-limited OCR;
  old OCR cache invalidation; independent inventory branch timeouts; retained
  references and fresh access enforcement.
- Authenticated HTTP MCP fixture exercises all four affected tools with
  `academic:read` and verifies their read-only annotations and response fields.
  Synthetic Canvas requests remain GET-only.
- Focused existing suite: **265 passed** across integration findings, course
  files, document search, academic intelligence, spreadsheet reading, service
  security, permission consistency/contract and PDF processing regressions.
- `ruff check src tests`: **passed**.
- Full suite, `.venv\Scripts\python -m pytest -q --tb=short`: **835 passed,
  24 skipped in 248.11 seconds**. Skips: 13 Linux-only checks, 7 requiring a
  disposable PostgreSQL database, 2 requiring an explicitly configured trusted
  native presentation converter, and 2 requiring an installed operator OCR runtime.
  Synthetic OCR success/failure/coverage regressions ran and passed separately
  from those optional real-runtime checks.
- Final `git diff --check`: **passed**. Existing uncommitted presentation and
  visual-delivery work was preserved; this task did not edit those pipelines.

## Evidence boundary

These are local source-code and synthetic transport results. The owner's
reported October 23 live failures motivated the fixtures; no claim is made that
the installed connector has loaded this revision or that the real schedule's
candidate count has been reproduced. Existing release gates remain unchanged.
