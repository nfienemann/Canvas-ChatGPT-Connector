# Academic intelligence implementation and evidence

This increment extends the existing native ChatGPT connector. It does not add a
dashboard, paid model, AI subscription or second sign-in flow. The implementation
plan is in [academic-intelligence-plan.md](academic-intelligence-plan.md).

## Acceptance and feature boundaries

The test names below are in `tests/test_academic_intelligence.py`. Existing
file/network/authentication, grade, planning and lifecycle suites remain in force.
Passing a synthetic acceptance case establishes the stated supported behavior;
it does not establish coverage of every natural-language policy or all universities.

| Feature | Implementation / MCP tools | Acceptance test | Limits / dependencies |
|---|---|---|---|
| Evidence and coverage | `domain.py`, `evidence.py`, `normalize.py`, `app.py`, `service.py`; additive `evidence` envelopes across tools and `submission_consistency` in assignment details | `test_evidence_versions_coverage_and_unknown_reconciliation`, `test_current_detail_conflict_preserves_missing_evidence` | Older sources without hashes/coverage are explicitly unknown. Missing evidence is never backfilled as a known submission. Different retrieval times can explain disagreements; neither observation establishes a missing assignment. |
| Documents | `parser_worker.py`, `parser_sandbox.py`, `course_files.py`, `retrieval.py`; existing file readers/search/continuation | `test_authorized_office_read_search_and_isolation`, `test_office_real_appcontainer`; existing actual Paper 3 proof | PDF, DOCX, PPTX, TXT and Markdown text. PDF pages, presentation-order slides, Word text sections. OCR, visual figures, faithful equations/tables, XLSX/CSV and non-Windows isolation remain unsupported. Search only indexes successfully read files. |
| Changes | `change_tracking.py`, `normalize.py`, `service.py`; `get_changes(refresh=False)` | `test_changes_earliest_observation_and_dedupe` | Consecutive complete observations; no pre-baseline reconstruction. Disappearance is not proof of deletion. Stable notification keys prevent duplicate identities; delivery is disabled and consumers must deduplicate keys. Retention limits historical coverage. |
| Deadlines | `academic_rules.py`, `academic_intelligence.py`, `canvas.py`; **reconcile_course_deadlines** | `test_deadline_acceptance_and_exact_source`, Office schedule integration test | Exact unique title matches; similar titles remain ambiguous. Explicit ISO/full English month dates only. No inferred year, 11:59 PM time or source precedence. A date-only versus timed comparison requires known course timezone. |
| Grades | Existing `grade_audit.py`, `grading_engine.py`, `grading_policy.py`; existing four grade tools | `test_grade_84_vs_91_acceptance`; 30 existing grading regressions | Reuses Decimal arithmetic and source/version-bound policy review. Unsupported rules, hidden work, unclear periods, missing scores or incomplete policy prevent precise estimates. See [grade-auditing.md](grade-auditing.md). |
| Requirements | `academic_rules.py`, `academic_intelligence.py`; **review_assignment_requirements** | `test_instruction_conflict_and_draft_acceptance`, `test_optional_ranges_formats_amendments` | Explicit mandatory word counts, submission formats, same-named percentage criteria and dated obligations. Qualitative rubric conflicts need ChatGPT interpretation with quoted passages. Optional suggestions are not mandatory. Draft word count is not an instructor grade. |
| Priorities | `planning.py`; **propose_study_plan** extended with `importance` and `priority_overrides` | `test_prioritization_urgency_importance_effort_and_overrides`; existing dependency/busy-time allocation tests | Student override (0 highest), urgency, stated grade weight, then deadline. Grade impact is student supplied and labeled; assignment points are not silently converted to course weight. Unknown effort stays unknown. Completed/excused work is excluded unless revision evidence exists. |
| Exam preparation | `academic_intelligence.py`, `academic_rules.py`; **prepare_for_assessment** | `test_exam_reads_associated_pdf_without_inventing_coverage` | Finds a reliably dated next assessment or requests a choice. Reads up to three associated/discovered documents; same-module relevance is inferred, not assigned coverage. Returns cited excerpts/objectives/keyword overlap for ChatGPT to create guides and questions. No separate generation service. |
| Calendar composition | `calendar_sync.py`; **propose_calendar_sync**, existing native Google Calendar connection | `test_calendar_three_deadlines_one_existing_acceptance_and_reproducibility`, changed deadline/DST/stale tests | Proposal engine and native-connection read composition. No embedded Google OAuth or automatic writes. Fresh complete event/mapping searches required. Actual writes require confirmation in ChatGPT and independent read-back. No notifications or autonomous synchronization. |
| Integrated audit | `academic_intelligence.py`; **audit_course_consistency** | `test_integrated_five_supported_findings_no_false_error_claim` | Five planted supported findings detected; unchecked grades, qualitative criteria, external/hidden readings and full meeting timetables remain labeled. One selected course per bounded request; no claim of exhaustive course correctness. |

## Evidence and deterministic methods

`Source` remains backward compatible with additive `source_type`, `course_id`,
`resource_id`, `content_hash`, `extraction_status` and `uncertainty` fields. Every
MCP result now also provides evidence envelopes containing the source URL,
retrieval/source timestamps, location, classification, version, collection
coverage and pagination completeness where established. Unknown old fields are
labeled rather than invented. New rule passages retain document/version, locator,
offset, exact passage and interpretation status. Derived calculations, student
input and source facts are distinguished. Source content is always untrusted.

Date extraction and rule comparisons are deterministic; close title matches
never receive the certainty of exact unique matches. A missing Canvas due field
is a confirmed field absence, not a confirmed policy mistake. A new announcement
does not automatically amend an old syllabus. Conflicting versions remain visible.

Change snapshots fingerprint normalized instruction text and compare title,
due/open/close dates, points, submission requirements and observed states.
Consecutive complete pairs establish the first observed timestamp for each
transition. Canvas modification timestamps remain separate. Unchanged snapshot
queries return identical notification keys. Old snapshots without fingerprints
cannot prove instruction changes. No notification sender is installed or enabled.

The grade model, schema and exact arithmetic are documented separately in
[grade-auditing.md](grade-auditing.md). The new acceptance fixture reproduces 84%
with 80/20 category weights and estimates 91% with reviewed 45/55 weights from
the same scores. It explains a seven-point difference without claiming either
source is definitively correct. Missing policy still deliberately prevents a
precise syllabus estimate.

## Native Calendar flow

1. In the same ChatGPT conversation, read events and busy intervals through the
   student's existing Google Calendar connection. Resolve the desired calendar
   explicitly when more than one account/calendar is relevant.
2. Page the requested interval (maximum 31 days). Search prior Canvas source URLs
   and `canvas-bridge:` markers as well, including outside the current date
   interval, because an existing deadline may have moved. Do not claim complete
   mapping searches if the native tool did not provide that coverage.
3. Pass minimal event IDs, title, timing, marker/source URL, status and version;
   omit attendees and private meeting text. `retrieved_at` is the actual read
   time, not a fabricated freshness stamp. Listing and workload snapshots must
   be complete and no more than five minutes old.
4. The proposal tool returns exact creates/updates, possible untagged duplicates,
   ignored undated/past/completed work and optional study blocks around supplied
   busy intervals. Date-only obligations become all-day proposals; no time is
   invented. Timed deadline reminders use a disclosed 15-minute duration, not an
   effort estimate. DST conversion uses IANA timezones and absolute instants.
5. Present the concrete proposal and obtain explicit student confirmation. Only
   then may ChatGPT invoke the separate Google Calendar write tool. Reread Canvas
   and event versions before acting. Preserve the stable marker and source URL in
   the event description, then read back the event to verify it.
6. After an uncertain create result, search the marker before retrying. Event
   descriptions maintain the durable assignment/event mapping. Removed Canvas
   records never automatically trigger Calendar deletions.

Canvas Bridge never receives the native Google OAuth credential and cannot
enforce actions another tool performs. It does not store Calendar events or
attendees. Explicit authorization and mutation remain the responsibility of the
ChatGPT conversation and the existing Calendar tool. Confirmation is not a
Boolean parameter that a model can silently submit to this service.

## Security, retention and operational boundaries

- All academic network requests remain reviewed Canvas **GET** routes. Every new
  workflow checks authenticated ownership, selected student-course scope and an
  ending connection epoch. Foreign course/file IDs are rejected before reading.
- Announcements use a server-constructed `context_codes[]=course_ID` and bounded
  180-day interval, verify returned context and publication times, and exclude
  hidden/future entries. No instructor-only information, grade updates, assignment
  submission or outbound instructor contact is exposed.
- Office files use the existing authenticated downloader and credential-free
  Windows AppContainer. ZIP members/expanded bytes/compression ratio, DTD/entity
  XML, macros and embedded objects are constrained or rejected. External OOXML
  relationships are never followed. Only standard Python, pypdf and defusedxml
  code is copied into the isolated runtime. Existing CPU/memory/time limits apply.
- Raw files remain temporary; extracted file text keeps the existing maximum
  24-hour cache and scope/deletion fences. New comparisons, drafts, Calendar
  evidence and grade calculations are ephemeral, not new persistent tables.
  Assignment snapshots use existing configured retention; notification delivery
  is off. Google event markers persist in the student's independently controlled
  Calendar until edited/deleted there.
- A request inspects at most 30 assignment details, 10 announcements, three
  documents, and 90 seconds. Overflow, incomplete collections and uninspected
  sources are reported. Output remains under the existing MCP response budget.

## Access and remaining work

No MCP identity scopes, database migration, new subscription or student
reinstallation is required for the configured private service. Refresh the
installed connector's tools after restarting its existing launcher.

The Canvas announcement route now needs
`url:GET|/api/v1/announcements` for a future scoped institution developer key;
denial remains a coverage limitation. Other reads reuse existing scopes. This
does not grant institutional approval or change public distribution gates.

Next priorities are reviewed broader date/policy grammars, user-confirmed mapping
of ambiguous obligations, verified Linux/macOS parser isolation, OCR/visual
extraction, qualitative rubric evaluation safeguards, and an explicitly approved
native Calendar create/update/read-back pilot. Automatic notifications remain off.


## Recorded validation

The complete Windows suite passed **309 tests**, with PostgreSQL and actual
AppContainer checks included, at **83% statement coverage**. Five desktop tests
and PNG/ICO/ICNS generation also passed after upgrading the optional packaging
Pillow dependency to resolve the dependency-audit findings. The final dependency
audit reported no known vulnerabilities. No public installer rebuild is claimed.

The restarted private service reread the actual acceptance PDF (15 pages, 74,408
characters in five chunks). The installed ChatGPT connector invoked the new
course-audit and assessment-preparation tools, cited source records, and correctly
refused to identify a next quiz from undated assessments. Actual ChatGPT also combined native Calendar availability/event searches, a
fresh Canvas workload and the new Calendar proposal tool, returning a single
deadline reminder proposal with duplicate checks and an overlap explanation.
No event was created, changed or deleted; write/read-back remains untested.
The detailed run record and any later composition result are in
[evidence](../evidence/sanitized-results/verification.md).
