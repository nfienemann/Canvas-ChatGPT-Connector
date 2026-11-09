# Contributor guide

Read README, AGENTS.md and architectural decisions. Use `uv sync --frozen`.
All committed fixtures must be synthetic.

Run focused tests while changing code, then the full suite and Ruff checks before
release. PostgreSQL tests are explicitly skipped without a disposable test
database. Never relabel a skip as a pass. Avoid repeating an unchanged full suite
solely because a new prompt starts.

Maintain the official MCP transport, typed envelope, owner/connection filters,
student-only routes, explicit missing states, date-only semantics, partial
coverage and deletion fencing. Course text cannot grant scope or authorize exports.

Do not add a model API dependency, student billing, academic dashboard, generic
proxy, roster access or Canvas academic writes. Calendar tools remain absent
until independent provider authorization and a tested approval mechanism exist.

Update evidence with precise scope. Fixtures do not prove a university, ChatGPT
client, mobile surface or public listing works. Public claims need observations.

Dependency changes must update `uv.lock`, pass security/contract checks and
`pip-audit`, and consult current vendor documentation for auth/transport changes.
Use SECURITY.md for vulnerability reporting.

The owner has not selected a project license. Do not announce an approved
open-source release as if that decision were already made.

## Where to start when…

Run these commands in PowerShell from the repository root with the project's frozen virtual environment installed. The widget diagnostic also needs Node.js and the locked dependencies in `ui/page-reader` (install with `npm ci --prefix ui/page-reader`). For native slide rendering, follow the [trusted converter setup](pptx-visual-pipeline.md) and set `BRIDGE_TEST_OFFICE_ROOT` in the test process. Without that prerequisite, pytest reports the native cases as skipped.

| Observable symptom | First code entry point | Focused command | What a pass establishes |
| --- | --- | --- | --- |
| A course file is missing from discovery | [paged_inventory.py](../src/canvas_bridge/paged_inventory.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_paged_inventory.py::test_resumable_inventory_follows_all_branches_without_filename_dedup` | All four fixture branches finish. Five distinct file IDs survive even though their filenames match. |
| The list stops after the first page | [course_files.py](../src/canvas_bridge/course_files.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_inventory_followup.py::test_branch_timeout_retains_already_received_inventory_page` | A timeout on page two keeps the first page and marks file coverage partial. Check branch coverage before concluding a file is absent. |
| A known file returns 403 during download | [file_download.py](../src/canvas_bridge/file_download.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_visual_files.py::test_T13_denied_download_does_not_retry_forever` | The provider’s 403 surfaces as `RESOURCE_PERMISSION_DENIED`. The bridge avoids replaying the same denied URL. |
| PDF text disappears between chunks | [course_files.py](../src/canvas_bridge/course_files.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_file_reading.py::test_T11_T12_T25_pdf_read_pages_chunks_and_cache` | Following the continuation retrieves text across the three-page fixture with one source download. |
| The PDF page count exceeds the extracted pages | [parser_worker.py](../src/canvas_bridge/parser_worker.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_document_stress.py::test_pdf_exact_budget_discloses_omitted_pages` | Reaching the text budget before the last page returns partial coverage, the source page count, and a warning. |
| A slide has missing text or looks blank in extraction | [presentation_worker.py](../src/canvas_bridge/presentation_worker.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_presentation_reading.py::test_slide_text_notes_chart_caches_and_empty_image_slide_have_provenance` | The parser distinguishes slide text, chart values and notes. An image-only slide reports media and an empty text layer. |
| A PDF diagram or scanned page is missing | [visual_worker.py](../src/canvas_bridge/visual_worker.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_visual_files.py::test_T11_T12_isolated_pdf_images` | The isolated renderer produces PNG pixels for the requested fixture page, including scanned and rotated inputs. |
| A slide image is missing or comes from the wrong slide | [presentation_render_worker.py](../src/canvas_bridge/presentation_render_worker.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_presentation_rendering.py::test_native_single_slide_hidden_mapping_and_pdf_pixels` | With the trusted Windows converter configured, the selected slide maps to a single PDF page and renders to PNG, including the hidden-slide case. |
| The downloaded file seems incomplete | [file_delivery.py](../src/canvas_bridge/file_delivery.py) | `.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_file_delivery.py::test_workbook_complete_routes_are_original_bytes` | The fixture workbook’s embedded payload and authorized HTTP responses match its original bytes. |
| The download button fails in ChatGPT | [download.js](../ui/page-reader/download.js) | `node scripts/diagnose_download_handshake.mjs` | The shipped widget matches the build. A synthetic host exercises embedded, linked, rejected and external-fallback paths. |

**Visual inspection.** If a render times out, record the failing page or fixture variant and the processing stage reported by the [isolated parser](../src/canvas_bridge/parser_sandbox.py). When a question depends on a diagram, chart legend, label, or slide layout, open the rendered page or slide. Check its source number and read the relevant detail at a legible scale. A successful PNG check establishes that the renderer returned pixels.

**ChatGPT download acceptance.** For a task that calls for host verification, open the original-file widget in the target ChatGPT client, click download, save the synthetic fixture, open it in its normal application, and compare its SHA-256 with the original. Record the client, whether the in-chat or external route was used, and the observed outcome. A host acknowledgment alone only records receipt of the request.

## Private session handoff

When pausing or handing over work, copy this template into `.local/dev-handoff.md` and fill it in. On resume, compare the recorded commit and relevant tracked and untracked changes with the current checkout. Reuse an earlier full-suite result only when its tested revision and relevant working-tree state still match. Record the exact checks you ran, including skips.

```text
Task:
Commit tested (git rev-parse HEAD):
Relevant uncommitted changes at verification:
Last verification command and result (include failures/skips):
Last full suite, if relevant (command, result, commit and relevant changes):
Blocker or remaining check:
Next action:
Existing private audit checkpoint (optional path only):
```

Keep credentials, signed URLs, and course content out of the handoff. For resumable audits, point to the current private checkpoint so the next session can pick up from its recorded position.
