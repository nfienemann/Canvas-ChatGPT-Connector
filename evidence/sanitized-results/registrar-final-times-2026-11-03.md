# Registrar final-time lookup — local evidence

Date: November 3, 2026. Source: user-supplied
`Canvas_Bridge_Registrar_Final_Times_Spec.zip`, `registrar-final-times.md`.
All exercised records are synthetic. Existing uncommitted work was preserved.

## Implemented boundary

- Optional term/section/CRN/campus input on existing deadline, consistency and
  Calendar tools; unknown identifiers stay unknown and foreign course references
  are rejected.
- The independent-document adapter uses the same handoff and Calendar hold,
  without treating a document reference as a verified course identity.
- Bounded final gap discovery, including undated finals-week source passages and
  presentation activity labels. Reported due timestamps are not exam start times.
- Host-owned original-message/attachment inspection and reconciliation procedure,
  explicit five-status behavior, source citations and sender-verification rules.
- Existing assessment Calendar markers retained; uncertain final-slot proposals
  held without writing, deleting, monitoring or creating duplicate events.
- No email ingestion permission path. Host-inspected results stay in the host
  conversation, with existing institutional and recipient gates unchanged.

## Executed

- `.venv/Scripts/python.exe -m pytest tests/test_registrar.py -q`:
  **9 passed**, including loopback authenticated HTTP MCP serialization.
- Initial Ruff check and format check of the six affected Python files: **passed**.
- Final `.venv/Scripts/python.exe -m pytest tests/test_registrar.py
  tests/test_independent_intelligence.py tests/test_academic_intelligence.py -q
  --tb=short`: **86 passed in 70.12 seconds**. Includes all 12 registrar cases
  and the final independent-document/Calendar integration.
- Final Ruff check and format check of all eight affected Python files: **passed**.
- `.venv/Scripts/python.exe -m pytest tests/test_registrar_fixture_assets.py -q`:
  **2 passed**. Confirms the synthetic original `.eml` contains the exact PDF
  bytes, the intended CRN/page/row is present, the other course's CRN is absent,
  and the inconsistent-year grid actually retains both year headings.
- Fixture builder and fixture tests: Ruff check/format **passed**. Generated two
  PDFs with the bundled reportlab runtime; rendered all three pages with
  pypdfium2 and visually checked legibility, labels, rows and year headings.
- `.venv/Scripts/python.exe -m pytest -q`: **2,207 passed, 31 skipped,
  3 failed in 1,381.70 seconds**. This run began before the final independent
  adapter extension and fixture additions; the final code was covered by the
  focused checks above. No fresh full-suite pass is claimed.
- The three full-run failures were:
  - `test_full_run_separates_visual_review_from_text_extraction` in
    `tests/test_benchmark_lab.py`: reproduced in isolation. The
    `parse-image-heavy-pdf` scenario reports `visual_reading_claimed=True`,
    contrary to its expected answer. Its adapter derives this from parser
    coverage, not registrar code. Source stability was true on the isolated run.
    This benchmark mismatch was unresolved at that run; it was subsequently
    [resolved and verified](pdf-benchmark-mismatch-2026-11-03.md) without weakening
    benchmark assertions.
  - `test_report_is_reproducible_and_does_not_load_settings` in
    `tests/test_compliance.py`: initial run observed different source digests.
  - `test_failed_or_stale_security_check_stays_release_blocking` in
    `tests/test_compliance.py`: initial run did not find the expected failed-check
    blocker while source/evidence state was changing.
- A first targeted compliance rerun caught the new standalone fixtures missing
  from `governance/fixtures.json`. Added their exact hashes after inspecting the
  generated source, email payload and rendered pages. This is byte registration,
  not a claim of human provenance review or public approval.
- With edits paused and that registration in place, the two compliance tests
  above were rerun together: **2 passed in 21.96 seconds**. The PDF benchmark
  mismatch was the remaining failure at that point; see the subsequent
  [114-test follow-up](pdf-benchmark-mismatch-2026-11-03.md) for its resolution.
- Skips require unavailable native converter/OCR, Linux kernel, or disposable
  PostgreSQL environments. They are not passes.

`uv` was unavailable on PATH; checks used the existing repository virtualenv.

## Not established

No live mailbox was searched, no original registrar PDF was inspected by a real
host, and no service was deployed or restarted. Host acceptance scenarios for
multi-section PDF/CRN matching, inconsistent year headings, explicit correction
versus unexplained conflict, cancellation, search completeness, unavailable mail,
and Ethics versus Stem Cell are supplied in `docs/registrar-host-acceptance.json`.
Their status is **NOT RUN in a real host**, not passed from unit-test evidence.
This change does not certify sender authenticity, interpretation accuracy,
institutional permission, release approval or actual Calendar delivery.
