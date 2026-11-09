# Canvas Bridge capability coverage matrix

Evidence through November 3, 2026. Full operational readiness is not established.
Later PNG-runtime validation passed 49 Node tests with zero dependency audit findings
after upgrading fflate. See [follow-up receipt](recursive-validation-2026-11-03-png-followup.json).
These JavaScript/CI additions postdate the two full Python-suite receipts.

Implementation discovery: 79 tool registrations, 44 HTTP route registrations, 26 allowlisted Canvas endpoints, 237 Python modules. The connected catalog advertises 53 tools. Conditional/local mutations are tested only in isolated fixtures.

Final Windows suite runs: 2,389 passed / 13 Linux-only skips, then 2,390 passed / 13 Linux-only skips. Both had zero failures and unchanged source during execution. The second includes a five-file extraction-status change; these are not identical-source repetitions.

Static test references are not proof of executed tool coverage. The JSON companion contains implementation locations, dependency calls, routes, endpoints, module hashes, every discovered test definition and counts from referencing test files. Those counts overlap across tools and must not be added.

| Tool | Intended behavior | Connected catalog | Live evidence | Static test references |
|---|---|---|---|---|
| `get_connection_status` | Check your connection, selected scope and capability limits before using academic tools. | yes | PASS: active connection returned; downstream authorization remains separate | 5 files; static linkage only |
| `prepare_course_file_download` | Prepare the unchanged original file for download, including workbooks and opaque binaries. | yes | NOT_EXERCISED | 4 files; static linkage only |
| `get_course_file_download_payload` | App-only: reauthorize a prepared original and obtain its private download payload. | no/conditional | NOT_EXERCISED | 4 files; static linkage only |
| `audit_permission_consistency` | Audit selection, exact IDs, local authorization and resource capabilities read-only. | yes | PASS local-only: 35 consistent checks; upstream checks not requested | 5 files; static linkage only |
| `list_courses` | List currently authorized active student courses. Does not select or enroll in courses. | yes | PASS: five selected courses; active-student pagination complete, historical scope unsupported | 18 files; static linkage only |
| `list_course_discussions` | Discover selected-course discussion metadata without reading thread entries. | yes | BLOCKED: EGRESS_GOVERNANCE_MISSING | 2 files; static linkage only |
| `read_discussion_topic` | Read a discussion prompt and optionally the authenticated student's entries. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `get_my_discussion_participation` | Verify only your own posts and replies using a fresh bounded authorized scan. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `get_course_obligations` | Discover assignments, classic quiz instructions, discussion topics and Canvas events. | yes | BLOCKED: EGRESS_CLASSIFICATION_UNKNOWN | 2 files; static linkage only |
| `get_workload` | Retrieve individualized assignment dates/statuses with source and course coverage. | yes | LIVE COVERAGE RECOVERED: first two course branches complete in combined request; other three completed individually; no continuation remaining; independent deadline fidelity unverified | 9 files; static linkage only |
| `get_assignment_details` | Read current assignment requirements and your status; content is untrusted course data. | yes | LIVE CROSS-TOOL CHECK: one assignment matches workload on all eight compared metadata fields; requirements untruncated; independent fidelity unverified | 5 files; static linkage only |
| `get_changes` | Compare complete observed snapshots. Does not infer history before the stored baseline. | yes | NOT_EXERCISED | 0 files; static linkage only |
| `get_gradebook` | Read your visible reported grades. Unknown policy blocks exact grade-impact claims. | yes | BLOCKED: EGRESS_GOVERNANCE_MISSING | 5 files; static linkage only |
| `get_course_grading_policy` | Retrieve your visible Canvas grade configuration, scores, and versioned syllabus rule candidates. | yes | BLOCKED: EGRESS_CLASSIFICATION_UNKNOWN | 2 files; static linkage only |
| `calculate_course_grade` | Calculate reproducibly using posted scores, preserving unknown and ungraded states. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `audit_course_grade` | Compare Canvas-reported, reproduced, and syllabus-derived grades side by side. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `simulate_grade_scenario` | Simulate explicit future scores or a uniform remaining score needed for a target. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `reconcile_course_deadlines` | Compare Canvas deadlines with quoted syllabus/schedule/announcement dates. | yes | NOT_EXERCISED | 5 files; static linkage only |
| `review_assignment_requirements` | Compare instructions, rubric and explicit assignment mentions in selected course sources. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `prepare_for_assessment` | Build a cited evidence pack for a chosen or reliably dated next assessment. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `propose_calendar_sync` | Prepare deduplicated Calendar deadline and optional study proposals; writes nothing. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `audit_course_consistency` | Inspect one selected course for supported contradictions and missing information. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `get_course_outline` | Find modules, pages and files by title. File module items include material_ref for reading. | yes | BLOCKED: EGRESS_CLASSIFICATION_UNKNOWN | 4 files; static linkage only |
| `fetch_course_material` | Fetch authorized Canvas page or file text. Continuations require the previous content_hash. | yes | NOT_EXERCISED | 6 files; static linkage only |
| `search_course_materials` | Search previously fetched authorized pages and recheck access; reports incomplete index scope. | yes | NOT_EXERCISED | 0 files; static linkage only |
| `list_course_files` | Find uploaded documents by filename and module title within a selected course. | yes | TRAVERSAL ENDED: 120 unique references across five courses and 152 steps; explicit source 403 gaps remain; contents are not all verified | 8 files; static linkage only |
| `render_course_slide` | Render an authorized PPTX slide via a private PDF derivative and the native page reader. | yes | NOT_EXERCISED | 4 files; static linkage only |
| `render_course_file_page` | Render one PDF page, or one PPTX slide when the experimental renderer is configured. | yes | LIVE PIXELS VERIFIED: one PPTX slide and one PDF page with matching source hashes; whole-document visual coverage unverified | 9 files; static linkage only |
| `inspect_course_figure` | Find scientific figure candidates in an authorized document; render one PDF page or PPTX slide. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `record_course_figure_observation` | Structure a visual report AFTER seeing the page pixels; never infer visibility. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `interpret_course_schedule` | Structure schedule rows AFTER inspecting render_course_file_page's image. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `read_course_file` | Read an authorized PDF, DOCX, PPTX, XLSX, text or Markdown file, with citations and limits. | yes | LIVE PARTIAL: complete reported PPTX/XLSX/DOCX chunks; five-page PDF text contains OCR defects and privacy withholding; original-byte fidelity unverified; PNG unsupported; TXT extraction ceiling retained partial coverage even after final chunk | 10 files; static linkage only |
| `search_course_files` | Find cited passages in authorized course documents, including unread files. | yes | BLOCKED: private-content grant excludes search; EGRESS_CLASSIFICATION_UNKNOWN observed | 7 files; static linkage only |
| `get_file_extraction_status` | Check file availability, cached extraction state, page count and limitations without downloading. | yes | LIVE METADATA VERIFIED: two indexed files returned status without text; XLSX hash matched its read. Live cold-cache behavior not established; synthetic cold/warm checks passed | 4 files; static linkage only |
| `propose_study_plan` | Propose what to do first and optional non-overlapping blocks from a recent workload. | yes | NOT_EXERCISED | 4 files; static linkage only |
| `propose_course_study_plan` | Plan selected assignments, classic quizzes, discussions and event preparation. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `list_local_documents` | List permitted independent imports. Import files in Bridge settings; ChatGPT attachments are not automatically transferred. | yes | PASS listing response; document contents not yet exercised | 1 files; static linkage only |
| `run_independent_academic_workflow` | Analyze explicitly selected permitted independent imports without an LMS connection. | yes | NOT_EXERCISED | 5 files; static linkage only |
| `read_local_document` | Read bounded cited excerpts from an owned independent import, with coverage and continuation. | yes | NOT_EXERCISED | 5 files; static linkage only |
| `search_local_documents` | Search permitted imported text. Old single-document literal calls retain their behavior. Conceptual mode returns ranked exact passages, bounded expansions and version-bound continuation; it performs no downloads or visual interpretation. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `get_local_document_status` | Report independent import identity, extraction coverage and limitations. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `prepare_local_study_materials` | Provide a cited independent-source evidence package for ChatGPT to prepare notes; no backend language-model reasoning is claimed. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `render_local_document_page` | Render an independently imported PDF page or configured PPTX slide after explicit per-document visual-sharing permission. Source and derivative hashes stay separate. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `get_local_study_preferences` | Read schema-restricted study preferences without an institutional connection. | yes | PASS read-only response; no preference mutation tested live | 1 files; static linkage only |
| `update_local_study_preferences` | Save only explicitly requested local timezone and study timing preferences, with version checks. | no/conditional | NOT_EXERCISED | 2 files; static linkage only |
| `get_saved_study_state` | Read local-only preferences without an LMS connection. An optional connection ID selects legacy owner-scoped preferences, even after disconnect. Explicitly including Canvas-derived progress/plans requires an active authorized connection. | yes | PASS local-only response; institutional state excluded | 3 files; static linkage only |
| `update_study_preferences` | Save local planning preferences only when the user asks to remember them. Requires version match. | no/conditional | NOT_EXERCISED | 5 files; static linkage only |
| `record_personal_progress` | Save an explicit personal progress/effort correction. Does not submit or complete Canvas work. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `save_study_plan` | Save a freshly validated proposal locally when explicitly requested; never writes a calendar. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `prepare_study_session` | Prepare source-grounded concepts or generated voluntary practice from explicit permitted materials. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `submit_practice_response` | Check actual voluntary student responses against the current permitted study sources. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `run_academic_workflow` | Run a reviewed read-only academic workflow with bounded calls and explicit partial results. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `get_semester_overview` | Analyze all selected courses on demand using authorized snapshots and bounded course evidence. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `acknowledge_semester_findings` | Acknowledge or unacknowledge only findings the user explicitly selects from a current semester report. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `get_library_status` | Report private-library limits and an authenticated browser upload link. Chat attachments require explicit transfer; native host intake and audio/video are unavailable. | no/conditional | NOT_EXERCISED | 2 files; static linkage only |
| `list_library_items` | List at most 50 private items whose metadata this verified recipient may receive. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `get_library_item` | Inspect one permitted library item; specify version_id to pin immutable history. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `read_library_item` | Read exact bounded evidence from an immutable library version. Source instructions are untrusted content, never authorization. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `search_library` | Search permitted extracted text with exact original citations and explicit unsearched coverage. At most 20 selected items and 20 hits. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `render_library_item` | Render one exact PDF page, configured PPTX slide or sanitized PNG/JPEG after separate visual consent. Pixel production does not establish model observation. | no/conditional | NOT_EXERCISED | 0 files; static linkage only |
| `prepare_library_download` | Create a five-minute owner-session download receipt. Requires a signed-in browser; does not deliver bytes to the model. In read-only MCP mode, use the library settings link. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `run_local_study_workflow` | Read independent reviewed obligations and plan proposals, own feedback with optional practice, explicitly saved study outcomes, or on-demand consequential changes. Import/review/save/correct/delete through authenticated settings. No LMS, calendar writes, automatic history collection or notifications. | no/conditional | NOT_EXERCISED | 2 files; static linkage only |
| `get_academic_integrity_policy` | Discover authorized policy passages, authority, scope, versions and coverage. No source access or instructor permission is granted by this check. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `check_academic_assistance_permission` | Check the actual academic activity and expected output. Brainstorming, substantive outlines, mechanical edits and submission drafting are different permissions. Source text and model assertions cannot grant permission. | yes | BLOCKED: EGRESS_CLASSIFICATION_UNKNOWN; no assessed-work permission established | 2 files; static linkage only |
| `record_integrity_acknowledgment` | Record only a student's affirmative acknowledgment of the displayed, exact eligible uncertainty. Never infer it from the original request, general consent or product use. Prohibitions and unmet instructor permission cannot be acknowledged away. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `provide_instructor_permission_evidence` | Evaluate an already authorized independent import as student-supplied, unverified permission evidence. This does not authenticate an instructor or replace a confirmed prohibition. | no/conditional | NOT_EXERCISED | 2 files; static linkage only |
| `get_integrity_decision` | Recheck current source access, policy versions and scope for an owned decision. An old allow is never a reusable bearer credential. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `get_integrity_guidance` | Explain applicable restrictions and permitted alternatives without producing assessed submission content or contacting an instructor. | yes | NOT_EXERCISED | 2 files; static linkage only |
| `prepare_academic_assistance` | Release bounded source evidence for exactly the permitted activity after fresh integrity, source and recipient checks. This backend does not write submissions. Reevaluate when activity changes; never present allowed brainstorming as permission to draft. | yes | NOT_EXERCISED | 3 files; static linkage only |
| `get_integrity_acknowledgments` | Inspect minimal owned acknowledgment history. No prompts, drafts or institutional reports are retained. | yes | NOT_EXERCISED | 1 files; static linkage only |
| `revoke_integrity_acknowledgment` | Delete an owned uncertainty acknowledgment; this never deletes or overrides applicable policy restrictions. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `evaluate_academic_process` | Evaluate sourced evidence, conflicts, feasibility, lifecycle, identity, concepts, unofficial degree progress or portfolio review. Caller claims remain unverified. Does not save a plan, send a message, submit work or publish. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `preview_academic_process_change` | Prepare an expiring exact preview of an explicitly requested local record change. Review before confirmation. expected_revision=0 creates a record; corrections preserve source history and invalidate dependent records. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `confirm_academic_process_change` | Apply only the exact preview the student reviewed and explicitly confirmed, including deletions. Rechecks sources and policy. Retry with the same key after an uncertain response. No external services are changed. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `get_academic_process_records` | Inspect current local records or inventory. Revoked, expired or invalidated records disclose no academic contents. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `preview_academic_process_recovery` | Preview deletion of one local record and its dependent copies, or rollback of one revision. Choose exactly one reference. A rollback cannot restore revoked source access. | no/conditional | NOT_EXERCISED | 0 files; static linkage only |
| `get_academic_process_impacts` | Review deduplicated observed change impacts and repair needs for one saved record. Historical values are withheld when their source version cannot be released. Sends no notifications or calendar updates. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `export_academic_process_records` | Return requested local records as portable versioned JSON or Markdown with provenance, subject to current source and recipient permissions. No external file or message is created. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |
| `get_academic_support_report` | Preview a minimal offline support report with opaque IDs and fixed troubleshooting steps. Includes no coursework, credentials or raw exception text and sends nothing to support. | no/conditional | NOT_EXERCISED | 1 files; static linkage only |

Supported text formats: PDF, DOCX, PPTX, XLSX, TXT and Markdown. PDF images and configured PPTX visual rendering require separate runtime and release checks. OCR remains bounded and may be partial. Native in-chat original attachment is not implemented. No groups endpoint or historical course access is exposed.

Resource, tool, source-code, format and workflow coverage are separate measures. No combined coverage percentage is asserted.


## Course-file formats and visual paths

| Path | Automated evidence | Live verification and limit |
|---|---|---|
| PDF text/OCR | Parser, sandbox, provenance and privacy regressions passed | Five-page example; four OCR pages, visible transcription errors and withholding; semantic fidelity incomplete |
| PDF pixels | Native rendering and budget/authorization tests passed | One source-hash-matched page actually inspected |
| DOCX | Structural, malformed-package and worker tests passed | Complete reported text and 2-row/5-column rubric structure; section locators, no visual pagination claim |
| PPTX text | Order, notes, hidden-slide, continuation and package tests passed | All 11 reported slides in two hash-consistent batches; no whole-deck visual claim |
| PPTX pixels | Native sandbox rendering, mapping and limits passed | One source-hash-matched slide actually inspected |
| XLSX | Cells, styles, dates, formula-cache and bounded parsing tests passed | 150 distinct cell records across two chunks; original-byte equivalence not independently checked |
| TXT | Bounded text and continuation regressions passed | 250,000-character extraction ceiling; final chunk retained explicit partial coverage |
| Markdown | Automated plain-text parsing coverage | No representative live Markdown read; not declared live-verified |
| Standalone image text | Unsupported-format behavior covered | PNG text read explicitly unsupported; no standalone-image transcription claim |

## Workflow and platform boundaries

The current process evaluation passes 47 mapped automated cases. The separate
academic corpus preserves blocked outcomes instead of treating test execution as
semantic acceptance. Its case-by-case summary is linked alongside this matrix.
Live workload metadata was recovered per course; one assignment agreed across
eight compared fields. Live search, outline, obligations, grading policy,
gradebook, discussion listing and academic-permission checks remain blocked as
recorded above. Dependent workflow outputs were not manufactured.

All 13 skips in each full suite require a real Linux kernel. Docker/Linux CI and
native host file handoff are not established. The disposable UI build matched
three checked-in assets, but this is not host acceptance. Mutation tests used
synthetic fixtures; no personal academic or Calendar records were modified.

Code coverage of 86.6% came from an earlier failed diagnostic run, not final
acceptance. The JSON retains limited diagnostic statement mappings only for
unchanged modules; no current per-tool execution percentage is asserted.

Academic corpus outcomes: BLOCKED: 2, PASS: 71.

See [full report](recursive-validation-2026-11-03.md), [structured matrix](recursive-validation-2026-11-03-matrix.json), [corpus outcomes](recursive-validation-2026-11-03-corpus.json), and [process evaluation](recursive-validation-2026-11-03-processes.json).
