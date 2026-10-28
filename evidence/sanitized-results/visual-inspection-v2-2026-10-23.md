# Visual inspection v2 validation — October 23, 2026

Overall: local implementation and available checks are ready for review. **The automatic
ordinary ChatGPT pipeline is not accepted as complete.** New tools have not
been deployed. Current Codex observations exercise the previously deployed
renderer, not the newly implemented inspection tools. No credentials, private
source content, original files, rendered academic images, or receipts are stored
in this record. Reusable fixtures are wholly synthetic.

## Checks executed

- Existing rendering and reader suite: **39 passed, 2 skipped** (48.39 seconds).
  The two skips require an optional OCR runtime not installed in the test environment.
- Initial new inspection suite: **29 passed** (40.84 seconds).
- Initial full suite: **786 passed, 23 skipped, 1 failed** (275.40 seconds).
  The failure was the existing fixed catalog count (32 versus 34 after adding two
  read-only tools). The assertion was updated to include both tools explicitly;
  its focused rerun passed.
- Final transport/reader/MCP follow-up: **54 passed** (52.04 seconds).
- After adding the configurable lower-only memory ceiling, all affected
  inspection, PDF, text-reading, sandbox, UI, MCP and read-only catalog checks:
  **106 passed, 15 skipped** (107.93 seconds). This includes an actual Windows
  PDF render at 256 MiB and rejection of values outside the 128-384 MiB range.
  Linux execution remains skipped on Windows; no Linux runtime proof is claimed.
- Full-suite rerun after the catalog correction: **798 passed, 24 skipped**
  (279.35 seconds). Skips require Linux, a disposable PostgreSQL database,
  the optional native presentation converter, or OCR. This shared checkout also
  contains pre-existing/ongoing presentation work; those tests are included.
  The full-suite process began before the final lower-only memory setting was
  added; the subsequent 106-test affected-component run validates that change.
- `ruff check .`, `ruff format --check .`, and `git diff --check`: passed.

Commands used the existing `.venv/Scripts/python.exe` and Ruff installation.
The full suite was `python -m pytest -q`. The final affected-component selection
was `tests/test_figure_inspection.py`, `tests/test_visual_files.py`,
`tests/test_file_reading.py`, `tests/test_file_reading_contract.py`,
`tests/test_linux_sandbox.py`, `tests/test_visual_ui.py`, `tests/test_mcp_contract.py`,
and the read-only catalog assertion in `tests/test_personal.py`.
- Reader bundle rebuilt with the existing pinned local dependencies; no system
  conversion dependency was installed.
- Synthetic table, prose control, and two-panel graph rendered with the existing
  isolated PDF worker and inspected as images in this Codex session.

## Acceptance matrix

`PASS` applies only to the listed evidence boundary. `BLOCKED`/`NOT RUN` is not
a pass and does not establish platform incompatibility.

| Test | Result | Evidence and boundary |
|---|---|---|
| A PDF rendering | PASS local and existing deployed renderer | PNG MIME, hashes, dimensions, isolated cleanup, authorization and resource limits; no new conversion backend |
| B direct image delivery | PASS current Codex route; BLOCKED ordinary ChatGPT | Actual tool results contained image blocks. This model saw pixels including table shading and geometry absent from render metadata. No claim about the previously failing ordinary ChatGPT surface |
| C unsupported host | PASS synthetic; live retest pending | Unknown/unsupported/expired client evidence selects reader; text-only path emits no image; existing UI helper/messaging failures remain isolated |
| D known graph | PASS local visual review and Codex live observation; target client pending | Independently drawn synthetic two-panel graph, known labels/units/legend/trend/statistic and unlabeled shape; actual fixture B graph visually confirmed on page 4 |
| E figure discovery | PASS synthetic and bounded live investigation; target client pending | Synthetic reference page 1, actual figure page 4; ranked caption then image confirmation. Live fixture B references on page 2, caption candidate and actual figure on page 4 |
| F no-graph control | PASS current Codex visual check and synthetic contract; target client pending | User-specified fixture A page 3 visibly contains prose columns, no graph. Synthetic prose report has no axes/panels; schema rejects invented graph panels with negative status |
| G table layout | PASS current Codex visual check and synthetic contract; target client pending | Fixture A page 2 note supports the user-specified combined total of 122. Synthetic equivalent preserves spatial ambiguity, records correction with confidence, checks text anchor, leaves extracted text unchanged; column interleaving also covered |
| H permission revocation | PASS synthetic | Hidden/revoked source blocks a new render, continuation and old-receipt observation. Wrong owner/hash, expiry and source-version changes rejected. No live permission was revoked |
| I failure isolation | PASS synthetic | Renderer crash, timeout, memory and malformed-source outcomes yield bounded errors/fallback; same MCP session and ordinary course/text tools remain usable; existing worker tests cover actual malformed PDFs |
| J cross-client | PARTIAL | Codex route observed. Ordinary ChatGPT web/desktop/mobile not retested in this implementation session. Reader prior success is user-reported, separately from mocked bridge tests |

## Visual checks and their limits

For the synthetic graph, this model saw panel A's blue line rising and the red
line staying nearly flat, Dose [mg/L], Response [%], the two-color legend,
`p = 0.03`, and one error bar. The error-bar type and statistical comparison
remain unspecified. Panel B has three increasing gray bars with Time [h] and
Count; no tick values or legend were invented. An orange diamond appears below
panel B and has no corresponding text object. A small tick/axis-label overlap
was corrected in the synthetic fixture before final rendering.

The live checks used connection status, ordinary course-file inventory, exact
opaque file identifiers, source-hash-bound reads and the existing render tool.
No access-control bypass, selected-course changes, credential changes, Canvas
writes, calendar actions, service restart or publishing was performed. Existing
normal retrieval refreshes still apply. Source figures were never inferred from
filenames or treated as instructions.

Model observations above are not independent scientific validation. Tests of
submitted observation objects verify schema/provenance/reconciliation behavior;
they do not test whether an unattended model independently reaches the same
interpretation. The target client must complete the visible-feature challenge
and negative controls before that workflow can be advertised.

## Remaining acceptance work

The owner selected web, desktop and mobile where possible and offered to return
a new stress report. The [prepared test request](../../docs/visual-inspection-stress-test.txt)
separates current renderer checks from v2 deployment and includes one report
template per surface. No new client result has yet been received.

Deploy the reviewed changes through the established operator process, then
recheck the catalog and run the synthetic visual challenge in the actual ordinary
ChatGPT surface. Record its exact client/build and whether native delivery,
reader handoff or text-only mode works. Keep capability unknown if initialization
does not distinguish that surface. Run each other advertised client independently.
Do not infer target-client success from this Codex session or the Python tests.
