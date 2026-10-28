# Additional regression validation — October 23, 2026

Scope: local implementation and synthetic validation of the supplied additional
regression report. No live academic records or identifiers were used in tests.
Existing unrelated checkout changes were retained.

The dedicated suite covers filtered single-item and paginated planning, busy-time
subtraction, future openings across DST, pinned timing limits, closed and unknown
opening states, per-item accounting, unknown effort versus a real numerical
shortfall, completed-work timing metadata, authorized assignment links and denied
or external references, document priority, parser-restart errors, raw versus
semantic hashes, and fresh submission reconciliation. A real local HTTP/MCP
roundtrip exercises the workload-to-future-plan handoff with synthetic records.
A disposable SQLite migration roundtrip preserves source inventory and requires
fresh scope for legacy snapshots.

Initial focused validation: 23 dedicated regression cases passed. Later checks
cover 27 dedicated cases, including capacity before a future opening, explicitly
selected instruction documents and filtered Calendar composition.

Final focused checks:

- Planning/domain/date/scope/activity and regression suites: 97 passed after the
  allocator was corrected to preserve capacity before a future opening.
- Regression/academic/permission-consistency suites: 94 passed after the linked
  document outcomes were unified for automatic and explicit review.
- `ruff check src tests migrations`: passed.
- `git diff --check`: passed.

Full suite: `.venv\Scripts\python.exe -m pytest -q` — **952 passed, 27 skipped**
in 294.13 seconds. Skips: 13 Linux-kernel cases, 7 disposable-PostgreSQL cases,
5 trusted native-converter cases and 2 optional OCR-runtime cases. This run began
before the final allocator and document-outcome adjustments; the focused checks
above cover those final changes. No second redundant full run was performed.

No deployment or live retest is claimed. Migration `62ab7d391c04`, service restart
and fresh workload acquisition are required when activating the repaired build.
The cause of the historical live hash variation remains unconfirmed; rotating
transport values are a reproduced possible cause, not a claim about unseen logs.
