# Canvas Bridge: tool contracts and capability overview

**Reviewed October 28, 2026 against implementation commit `5bd0863`.**
This document combines a project overview with the implemented MCP tool catalog.
It describes repository capabilities, not a claim that every tool is enabled in a
deployed client or approved for public distribution.

## Project in one paragraph

Canvas Bridge brings authorized coursework and permitted student-owned documents
into ordinary ChatGPT conversations. It helps students understand obligations,
reconcile conflicting instructions, calculate grade scenarios, prepare for
assessments, and plan study time using cited evidence. The connector retrieves and
normalizes facts, performs deterministic calculations, and enforces access and
sharing rules; ChatGPT supplies conversational explanation and tutoring. Students
keep their existing conversational interface instead of maintaining another
academic dashboard.

The core design is **evidence before advice**: preserve source identity, dates,
versions, coverage and uncertainty; distinguish official records from student input
and model interpretation; and withhold unsupported conclusions. Canvas coursework
is read-only. Explicitly requested local preferences, plans and acknowledgments
are separate from institutional records.

## Registrar final-time lookup

`reconcile_course_deadlines`, `audit_course_consistency` and `propose_calendar_sync`
accept optional bounded `registrar_lookup` term/course identifiers. Final timing
gaps return a host lookup procedure, five result rules and existing Calendar
mapping identity where applicable. Inspect registrar email with the host's
already-authorized institutional email connector; email evidence remains in the
host conversation. No mailbox transport, email import, monitoring or provider
write is introduced. See [the contract and limits](registrar-final-times.md).
The same optional request field and handoff are supported by
`run_independent_academic_workflow` for deadlines, consistency and calendar work,
under the existing independent-source authorization path.

## What a student can do

| Student goal | Implemented support | Result boundary |
|---|---|---|
| Understand what needs attention | Workload, discussion participation, observed changes, semester overview and daily/weekly workflows | Missing coverage and uncertain completion stay visible; a past deadline alone does not mean unfinished work. |
| Resolve conflicting course information | Quoted deadline comparisons, requirements/rubric review and course consistency audits | A discrepancy is an investigation item, not proof of instructor error or automatic authority for a replacement deadline. |
| Understand grade options | Visible grade evidence, reproducible arithmetic, reconciliation and explicit hypothetical scenarios | Unknown scores, unsupported rules and unreviewed syllabus interpretations prevent exact claims. |
| Study from actual materials | Bounded document reading, assessment evidence packs, voluntary practice and page/slide rendering | Retrieved text is not visual comprehension; generated practice is not an instructor exam. |
| Work without an LMS connection | Permitted independent imports, local study preferences and seven independent analysis capabilities | Import, ownership, provenance and recipient permissions still apply; a ChatGPT attachment is not automatically a Bridge import. |
| Keep assistance within course rules | Activity-specific academic-integrity checks and controlled evidence release | Document access, sharing permission and permission to use AI for an activity are separate decisions. |
| Review changes to saved academic records | Optional reconciliation, impact analysis, preview/confirm, recovery and export tools | Disabled by default; degree projections remain unofficial and portfolio review cannot grant publication rights. |

## Availability and release status

The source registers **63 tools by default**, including one app-only download
helper. Enabling `BRIDGE_PROCESS_FEATURES_ENABLED` adds eight process tools, for
**71 total**. These are catalog counts, not claims of 71 independently approved
features. `BRIDGE_MCP_READ_ONLY=true` omits tools registered with local write scope:
54 tools remain without process features, or 59 with them.

| Surface | Current implementation boundary |
|---|---|
| Synthetic development | Fictional fixtures and local regression coverage support development and demonstrations. Synthetic results are labeled. |
| Institutional coursework | Requires verified identity, an owned connection, selected resources, current access and separately reviewed provider/institution/recipient permissions. `live_access_enabled` defaults to false. Credentials alone do not enable access. |
| Independent documents | Existing signed-in settings import flow supplies owned, permitted sources. No active LMS connection is required for independent workflows or local-only preferences. |
| File extraction and visuals | Institutional file reading defaults off. Isolated parser/runtime configuration is required; experimental PPTX rendering defaults off. Local visual sharing additionally requires document permission. |
| Academic process tools | Opt-in implementation of the 17 process specifications; registered only when the process feature flag is enabled. |
| Public release | Institutional onboarding, distribution eligibility, security/operational review and advertised-client acceptance retain separate gates. This document does not establish approval or production readiness. |

The [release gates](../evidence/release-gates.md) govern acceptance claims. The
[product specification](../Codex_Spec.md) governs product constraints. Neither a
catalog entry nor a passing synthetic test grants permission to disclose real coursework.

## Shared tool contract

### Identity, access and side effects

- Every MCP tool requires `academic:read`. Tools marked **Write** below also
  require `preferences:write` and are omitted in MCP read-only mode.
- Identity comes from the verified request. Connection, course, work, material,
  file and document references come from the corresponding authorized discovery
  response; never guess identifiers or pass another student's identity.
- Inputs use bounded typed schemas. There is no arbitrary HTTP/SQL/command tool,
  generic URL fetcher, model-callable credential importer or approval override.
- Institutional access, resource ownership, source versions, academic-integrity
  rules and recipient permissions are checked at their applicable boundaries,
  including before protected output is released. Cached data does not bypass
  revocation. Documents and imported instructions cannot grant authority.
- **Read** denotes the registered read-only analysis/retrieval contract. Reads can
  maintain bounded caches or short-lived processing receipts; it does not mean
  zero internal bookkeeping. **Write** denotes local state/review operations,
  never permission to write Canvas records.
- Saving a plan, preference, practice outcome or acknowledgment requires the
  applicable explicit user choice. A general request for help is not consent to
  save state, acknowledge a restriction or confirm a consequential change.

### Results, evidence and limits

Structured results use [`Result` schema `1.0`](../src/canvas_bridge/domain.py):

| Field | Meaning |
|---|---|
| `status`, `summary` | Machine-readable outcome and student-readable explanation. |
| `data` | Tool-specific facts, calculations, proposals and limitations; safe `reason_code` values where applicable. |
| `sources`, `evidence` | Source references and evidence records. Metadata can include locators, retrieval/update times, hashes, extraction state and uncertainty. |
| `meta` | Request/snapshot identity, retrieval time, display timezone, freshness, per-resource coverage, continuation, warnings and privacy/egress metadata. |

Statuses are `ok`, `partial_data`, `stale_data`, `reconnect_required`,
`permission_denied`, `unsupported_feature`, `source_changed`, `needs_input`,
`retry_later` and `operation_uncertain`. Missing, denied, unrefreshed and unsupported
sources are distinct from a verified empty result. Inspect coverage even when an
individual operation succeeds.

The ordinary serialized `Result` budget is 250,000 bytes; image and private
payload responses have separate transport checks. Page images have a separate
bounded PNG budget. Course-file text windows are at most 16,000 characters.
Workflow and source-specific limits can be stricter. Continue with the returned
cursor/part reference and required hash/version; narrow excessive requests rather
than claiming complete coverage.

Sources distinguish `source_fact`, `deterministic_calculation`, `student_input`,
`assistant_inference` and `unknown`. A passage establishes what a source says, not
independent verification of its scientific or policy claims. Model observations
and interpretations remain attributed and unverified unless separately verified.

## Implemented tool catalog

These tables cover every registered tool in
[`app.py`](../src/canvas_bridge/app.py),
[`integrity/tools.py`](../src/canvas_bridge/integrity/tools.py) and
[`processes/tools.py`](../src/canvas_bridge/processes/tools.py). Runtime MCP
`tools/list` supplies exact input schemas for the configured deployment; this
catalog explains purpose, side effects and result boundaries.

### Connection, obligations and workload

| Tool | Access | Result boundary |
|---|---|---|
| `get_connection_status` | Read | Owned connection, selected scope, authentication evidence and capability/approval state. Stored selection or an `active` label does not prove live authorization. |
| `audit_permission_consistency` | Read | Exact-ID, ownership, selection, authorization-lease and capability diagnostics. Optional bounded upstream metadata probes do not read bodies, refresh credentials, change selection or repair permissions. |
| `list_courses` | Read | Authorized active student courses; staff/mixed roles excluded. Does not select courses or enroll the student. |
| `get_course_obligations` | Read | Assignment, classic quiz instruction, discussion and event inventory with aliases, versions and continuation. Candidates do not establish required, upcoming or unfinished work; no quiz questions or attempts. |
| `get_workload` | Read | Individualized assignment dates/statuses within an explicit window of at most 31 days, up to 100 items per page. After membership verification, assignment retrieval gets three times the configured refresh duration (36 seconds by default, 45 maximum). Each remaining course gets a share of the remaining time, one course at a time. The filter-bound cursor pages the observed snapshot. For a timed-out course, request that course ID separately with the same window and no cursor. A fresh request starts at the first upstream page. Outstanding action is distinct from deadline history. |
| `get_assignment_details` | Read | Fresh accessible requirements, rubric, current-user status and checked linked-material references. A linked filename is not evidence its document was read. |
| `get_changes` | Read | Comparison of complete matching-scope observations with actual interval and baseline limitations. First observed does not mean newly published. |

The workload audit can spend its entire time allowance and still return partial coverage. Each assignment source has a 20-page ceiling. A scoped retry can help with a timeout after any reported cooldown expires. The page ceiling still applies on a retry. A genuine Canvas assignment denial stops the audit and invalidates affected cached records. The 403 response identifies the course by its one-based position in the requested IDs, or in the sorted selected IDs when the request omitted them.

### Course materials, document reading and visual evidence

| Tool | Access | Result boundary |
|---|---|---|
| `get_course_outline` | Read | Bounded modules, items, pages and files, with usable material references where access is established. Listing does not read a resource or establish that it is assigned. |
| `fetch_course_material` | Read | Authorized page/file text with fresh access checks and content-hash-bound continuation. No arbitrary external URL retrieval. |
| `search_course_materials` | Read | Previously fetched page index only, with fresh permission checks and explicit incomplete index coverage. |
| `list_course_files` | Read | Selected-course metadata and opaque file references. Default bounded mode remains compatible. `inventory_mode="resumable"` follows Files, folders/subfolders, modules/items and assignment links one operation at a time; follow `meta.next_cursor` until absent. Cursors are encrypted and owner/connection/course/epoch-bound, and every request reauthorizes. Denied linked-file metadata yields an explicitly unverified reference, never a grant. Complete coverage requires every branch to finish without gaps. |
| `read_course_file` | Read | PDF, DOCX, PPTX, XLSX, TXT and Markdown text windows with locators, hashes and extraction limits. XLSX preserves stored cells and distinguishes formulas from caches; formulas are not executed. |
| `search_course_files` | Read | Literal extracted-text search, cached-only by default. `include_unread=true` allows bounded extraction of at most three files per request; continuations retain scope/version and processing outcomes. |
| `get_file_extraction_status` | Read | Authorization and text-extraction state without downloading. Separates access, format support, extraction outcome, parser version and safe processing diagnostics; does not report rendering history. |
| `render_course_file_page` | Read | Bounded PDF page image, or configured experimental PPTX slide, with provenance and render receipt. Rendering does not prove host delivery or model-visible pixels. |
| `render_course_slide` | Read | Authorized PPTX slide through an isolated private PDF derivative. Citations stay tied to the original slide/hash; native runtime and feature configuration are required. |
| `inspect_course_figure` | Read | Bounded figure-candidate lookup and native/reader/text delivery, with cumulative budgets and explicit visual-pipeline states. Text labels cannot establish a figure's meaning. |
| `record_course_figure_observation` | Read | Attributed observation tied to an owned render receipt and current access. Preserves observed/unreadable/uncertain elements without claiming independent scientific verification. |
| `interpret_course_schedule` | Read | Ephemeral visual rows tied to a rendered-page receipt, with date basis, coordinates, uncertainty and optional calendar proposals. Does not establish authoritative deadlines or write events. |

See [file reading](file-reading.md), [PPTX reading](pptx-reading.md),
[visual inspection](visual-inspection-v2.md) and
[scientific document evidence](scientific-document-comprehension-v3.md).

### Original-file delivery

| Tool | Access | Result boundary |
|---|---|---|
| `prepare_course_file_download` | Read | Prepare unchanged authorized original bytes independently of extraction. `delivery_state=prepared` means prepared, not saved, downloaded or attached in ChatGPT. |
| `get_course_file_download_payload` | Read; app-only | Reauthorize an owned delivery and return a private payload to the download UI. Delivery IDs grant no access; original-byte and temporary-link release remain separately governed. |

The default original-file ceiling is 50 MiB, with a five-minute prepared-delivery
lifetime and a separate bounded inline payload. Live bearer-link release is
disabled by current egress policy; transport support alone does not authorize
disclosure. Native attachments and successful saves require actual client evidence.
See the [delivery contract](original-file-delivery.md) and
[current egress rules](data-egress-governance.md).

### Discussions

| Tool | Access | Result boundary |
|---|---|---|
| `list_course_discussions` | Read | Topic metadata without thread entries; announcements excluded. Closed-for-comments does not mean completed participation. |
| `read_discussion_topic` | Read | Authorized prompt/date evidence and optional authenticated-student entries. Peer thread disclosure is disabled; attachments use the authorized file path. |
| `get_my_discussion_participation` | Read | Fresh bounded verification of the student's own posts/replies, partial/restricted/ambiguous states and observed timing. Counts do not establish rubric satisfaction or grades. |

Verified absence requires exhausted authorized coverage. Partial scans can supply
lower-bound counts, never invented zero participation. Discussion reads do not
publish, reply, edit or delete. See [discussion contracts](discussion-reading.md).

### Grades

| Tool | Access | Result boundary |
|---|---|---|
| `get_gradebook` | Read | The authenticated student's visible reported fields; no hidden/unposted-score inference or assumed exact policy. |
| `get_course_grading_policy` | Read | Visible configuration, assessment evidence and exact versioned syllabus-rule candidates. Candidate interpretation needs student review. |
| `calculate_course_grade` | Read | Deterministic current, syllabus-derived, projected or required-score calculations for supported complete inputs. Missing/unsupported policy prevents exact claims. |
| `audit_course_grade` | Read | Reported, reproduced and syllabus-derived values with source coverage and missing evidence. A timed-out audit returns an indeterminate result, the interrupted stage, and a local-budget or upstream timeout reason. Automatic syllabus discovery and reading have a 30-second budget within the 90-second request. Explicit syllabus IDs skip discovery. |
| `simulate_grade_scenario` | Read | Explicit hypothetical scores and supported target-score scenarios. No inferred future marks, official final-grade claim or Canvas What-If write. |

For `calculate_course_grade`, the `grade_assignments`, `grade_groups` and
`own_grade_enrollments` rows of `meta.coverage` report collection pagination.
`grade_configuration` covers retrieval of the single course object.
`grade_assignment_details` covers retrieval of the selected detail objects.
The gradebook citation covers those Canvas input rows. The calculation row
describes the derived result and stays separate. Syllabus citations
remain independent. An empty source coverage array means the producer supplied
no matching collection evidence for that source.

The legacy `data.coverage.visible_assignment_collection_complete` flag also
requires the entitlement and grading-group checks and the local comparison
budget. Use the assignment row for assignment pagination alone.
`grade_calculation_inputs` is complete when the normalized input evidence is
complete and the chosen calculation reports no missing information. Page fields
on this row and the detail-object row have no collection-pagination meaning.
Calculation coverage applies to the chosen mode and visible work.

Grade freshness describes accepted Canvas configuration, assignment, group,
detail and enrollment reads. It excludes entitlement probes, syllabus discovery
and document reads. All upstream receipts yield `live`. Verified reuse yields
`cached` when every receipt is accounted for. Zero consumed inputs yields
`not_refreshed`. Unverified origin or an overall timeout with discarded
progress yields `unknown`. The oldest verified input time supplies
`meta.retrieved_at`. When timing is unknown the required envelope timestamp is
informational. Privacy filtering may withhold individual transport receipts.

Syllabus review must refer to the returned version/rules and the student's actual
review; the assistant cannot manufacture it. Unknown scores are not zero.
Eligibility, coverage and supported drop rules remain explicit. See
[grade auditing](grade-auditing.md) and the independent workflow below.

### Academic analysis, planning and study

| Tool | Access | Result boundary |
|---|---|---|
| `reconcile_course_deadlines` | Read | Compares cited date candidates using exact titles or unique embedded assessment identifiers. Duplicate passages retain their citations and versions. The graph reports retrieval, entity matching and cross-source comparison coverage separately. A single source cannot establish cross-source consistency. Missing years, clocks, zones and deadline applicability remain explicit. |
| `review_assignment_requirements` | Read | Instructions, rubric, related passages, supported numeric/format conflicts and ephemeral draft word count. Qualitative review stays with ChatGPT; no instructor-grade prediction. |
| `prepare_for_assessment` | Read | Cited assessment evidence with standard (6-document) and thorough (12-document) passes. Follow the returned deferred-ID, missing-page or excerpt arguments. See [budgets and continuation](../evidence/sanitized-results/assessment-preparation-budgets.md). |
| `audit_course_consistency` | Read | One-course prioritized supported findings, evidence, impact and unchecked resources; optional grades and self-only discussion checks. Not a guarantee of a problem-free course. |
| `propose_study_plan` | Read | Stateless priorities/blocks from a recent workload and explicit constraints, with work accounting, capacity limits and unresolved information. Saves nothing. |
| `propose_course_study_plan` | Read | Fresh inventory/version-bound planning for selected assignments, quizzes, discussions and event preparation. Suggested activities require review; saves nothing. |
| `propose_calendar_sync` | Read | Deduplicated create/update proposals using fresh complete context from an existing authorized calendar client. No event write, deletion or independent calendar-access claim. |
| `run_academic_workflow` | Read | One of seven server-defined workflows with bounded execution, evidence, resource accounting and partial results. No caller-supplied executable graph or autonomous action. |
| `get_semester_overview` | Read | On-demand selected-course obligations, grade position, observed changes, conflicts, uncertainty and heuristic priorities. Starts no monitoring or notifications. |
| `acknowledge_semester_findings` | Write | Save/remove acknowledgment of explicitly selected current findings. Does not alter source facts or authorize notification delivery. |
| `prepare_study_session` | Read | Source-grounded concepts or voluntary generated practice from explicit permitted materials. Course meanings stay distinct; figure practice needs actual pixel evidence. |
| `submit_practice_response` | Write | Check actual student responses. Optional outcome retention needs opt-in; raw responses are not retained. Open-ended/unmatched answers need review; no inferred mastery. |

`run_academic_workflow` offers Daily Academic Brief, Weekly Course Priorities,
Exam Preparation Pack, Grade Outlook, Course Discrepancy Review, Lecture
Comprehension and Calendar Preparation. These reuse existing permissioned
collectors and deterministic services. Defaults include 24 steps, three downloaded
files, 90 seconds total and a 40,000-byte workflow output ceiling; narrower
operation limits still apply. Execution is serial within a request, not evidence
of parallel file-processing capacity. See [workflow contracts](academic-workflows.md).

Planning preserves date-only precision, explicit effort ranges, pinned blocks,
dependencies, breaks/buffer and known busy intervals. Timed windows are half-open;
an end exactly at local midnight excludes that date. No 11:59 PM deadline or effort
estimate is invented from points. Date-only planning needs the applicable per-work
timezone; conservative planning bounds are not source deadlines. Durations use
elapsed UTC time across DST. Supplied calendar context is not independently
authenticated by Bridge.

Read `effort_summary` when presenting a plan. Its upper-estimate work minutes
balance as allocated plus total known unallocated. The latter includes direct
capacity, dependencies, and other constraints such as unavailable sources or
unknown availability. Extra reserved pin minutes and work with unknown duration
are reported separately. The time required on a calendar also includes breaks.
`pin_conflicts` retains the original pin, its blocking prerequisites and a
decision for the student. Only executable allocations appear in `blocks`.

Unknown submission is not cached certainty; `not_submitted` describes the online
record, not offline completion. Undated work is not automatically upcoming.
Practice is labeled as generated, with answers withheld until the student responds.
Preferred study periods and notification preferences do not create a schedule.
See [planning dates](planning-date-bounds.md), [cross-course study](cross-course-study.md)
and [semester analysis](semester-intelligence.md).

### Independent documents and local state

For a decomposed assignment, supply the parent record with its deadline and a
row per work step with `activity_kind: "study_step"` and `parent_key`. Leave the
step's due date unset. Changing the parent date updates its children's planning
cutoffs. Planning counts the steps once and Calendar uses the parent for the
reminder. Child activities with their own deadlines, such as discussion replies,
keep their own reminders. Legacy rows that name the same qualified assignment
in a numbered step key and title can supply a provisional shared cutoff. Confirm
that date against the assignment before using the reminder.

For supported assignment briefs, select them as `instructions` in a
`requirements` request to obtain cited work and deliverable candidates. When
passing a reviewed decomposition to `planning`, select the source documents and
record each step's `evidence` as document ID (`document_id`), `content_hash`,
part `locator` and exact `quote`. Use `start` and `end` for a repeated quote.
`study_step_review` reports which citations were located in the current
selection. The host and student review the interpretation and estimated time.
Explicit personal completion can satisfy a step dependency. LMS receipt status
requires separate evidence, and a revision request reopens the step.
Use `completion_rule: "verify_submission_receipt"` on an outstanding receipt
check to name it in the effort summary. Its minutes are counted once.

| Tool | Access | Result boundary |
|---|---|---|
| `list_local_documents` | Read | Owned permitted imports. Import uses signed-in settings, not a model-callable upload or automatic ChatGPT attachment transfer. |
| `read_local_document` | Read | Bounded cited parts with coverage and continuation. Ownership, retained provenance and permitted use remain required. |
| `search_local_documents` | Read | Literal extracted-text search within one document; no match is not complete visual inspection. |
| `get_local_document_status` | Read | Independent source identity/hash, extraction coverage and limitations for version-bound follow-up requests. |
| `prepare_local_study_materials` | Read | Cited independent-source study evidence; no backend language-model reasoning claim. |
| `render_local_document_page` | Read | Imported PDF page only, after explicit per-document visual-sharing permission. Does not imply local DOCX/XLSX/PPTX visual support. |
| `run_independent_academic_workflow` | Read | Selected permitted sources support `planning`, `assessment`, `requirements`, `grades`, `deadlines`, `consistency` and `calendar` without an LMS connection. Saves no plan and writes no calendar. |
| `get_local_study_preferences` | Read | Schema-restricted owner-scoped preferences without an institutional connection. |
| `update_local_study_preferences` | Write | Explicitly requested local study/timezone/semester preferences with expected-version checks. Notification preferences alone do not activate delivery. |
| `get_saved_study_state` | Read | Local-only preferences by default; optional connection ID selects the owned legacy namespace even after disconnect. `include_institutional=true` adds saved progress and plans from that connection and requires active authorization on every page. Institutional pages contain up to 25 matching records. While `meta.next_cursor` is present, pass it as `cursor` with the same arguments. A cursor expires after one hour or a scope epoch change. Pages read current storage. An empty `records` list means no matching state in the requested namespace. Operational checkpoints and internal preference provenance are excluded. Existing clients reading larger results must follow the cursor. No database migration is required. |
| `update_study_preferences` | Write | Explicitly requested version-checked preferences, including the legacy owned namespace; this preference-only path does not require an active LMS connection. |
| `record_personal_progress` | Write | Explicit personal progress/effort corrections under source/connection controls. Never Canvas submission or official completion evidence. |
| `save_study_plan` | Write | Freshly validated proposal saved locally with a version receipt. Not a calendar action or institutional update. |

Independent workflows select exact IDs and expected hashes; they do not relabel
institutional content as independent. Structured work/grades can use the imported
[`independent-academic-1` schema](schemas/independent-academic-1.schema.json).
User-supplied dates, grades and completion remain user-supplied. Text, visual,
grade/planning and schedule permissions apply separately; an import is not blanket
sharing consent. See [independent academic intelligence](independent-academic-intelligence.md).

### Academic-integrity permissions

| Tool | Access | Result boundary |
|---|---|---|
| `get_academic_integrity_policy` | Read | Authorized policy passages, scope, authority, versions and coverage. Discovery grants neither access nor instructor permission. |
| `check_academic_assistance_permission` | Read | Activity/output-specific decision: brainstorming, substantive outlines, mechanical edits and assessed drafting are different permissions. |
| `get_integrity_decision` | Read | Recheck an owned decision against current access, scope and versions. An earlier allow is not a reusable credential. |
| `get_integrity_guidance` | Read | Restrictions and permitted alternatives without producing assessed submissions or contacting an instructor. |
| `prepare_academic_assistance` | Read | Bounded evidence release for a permitted activity after fresh integrity, source and recipient checks. The backend does not write submissions. |
| `record_integrity_acknowledgment` | Write | Record actual affirmative acknowledgment of an exact eligible uncertainty. Cannot override prohibitions or unmet instructor-permission requirements. |
| `provide_instructor_permission_evidence` | Write | Evaluate an authorized import as student-supplied, unverified permission evidence. Does not authenticate an instructor or supersede a confirmed prohibition. |
| `get_integrity_acknowledgments` | Read | Minimal owned history; no retained prompts, drafts or institutional misconduct reports. |
| `revoke_integrity_acknowledgment` | Write | Delete an owned uncertainty acknowledgment; policy restrictions remain. |

Interpretation is bounded and requires source applicability/authority; this is not
a general dishonesty detector or misconduct determination. Known restrictions
follow relevant reader, search, visual and study paths. Source instructions and
model assertions cannot grant permission. See [academic integrity](academic-integrity.md).

### Optional academic process tools

These eight tools require `BRIDGE_PROCESS_FEATURES_ENABLED=true`. All three Write
tools are omitted in MCP read-only mode. They implement the
[17 process specifications](process-specifications/implementation.md) through
existing identity, source, integrity, privacy and recipient controls.

| Tool | Access | Result boundary |
|---|---|---|
| `evaluate_academic_process` | Read | Evidence/conflict, feasibility, lifecycle, identity, concept, unofficial degree and portfolio evaluation. Caller claims stay unverified; evaluation saves nothing. |
| `preview_academic_process_change` | Write | Expiring preview of a requested local create/correction using the expected revision; shows evidence, changes and dependent impacts before confirmation. |
| `confirm_academic_process_change` | Write; destructive-capable | Apply the exact confirmed preview, including deletion, with an idempotency key and fresh source/policy checks. No external service is changed. |
| `get_academic_process_records` | Read | Current authorized records/inventory; revoked, expired or invalidated records disclose no academic contents. |
| `get_academic_process_impacts` | Read | Deduplicated observed changes and repair needs. Unauthorized historical versions are withheld; sends no alerts. |
| `preview_academic_process_recovery` | Write | Preview deletion with dependent copies or rollback of one revision. Cannot restore revoked source rights. |
| `export_academic_process_records` | Read | Selected records as versioned JSON/Markdown with provenance and current permission checks. Returns content; does not publish or send it. |
| `get_academic_support_report` | Read | Minimal diagnostic preview with opaque references and fixed guidance; no coursework, credentials, raw exceptions or automatic support transmission. |

Local changes follow **evaluate → preview → review → confirm**. Creation uses
`expected_revision=0`; correction uses the current revision. Retry an uncertain
confirmation with the same idempotency key. Explicit dependencies and source
lineage permit invalidation when evidence changes. A confirmation Boolean is a
client contract, not proof that a human reviewed the preview.

Feasibility is a bounded heuristic, not an optimal-timetable guarantee. Concept
exposure is not mastery; degree projections do not certify graduation.
Clarification workflows draft questions and track confirmed events without an
email transport. The public portfolio adapter returns a review hold/checklist
until a trusted rights-review mechanism is configured. AI-assistance permission
does not grant publication rights.

## Example conversation flows

| Request | Typical sequence | Expected output |
|---|---|---|
| "Help me decide what to study this week." | Check scope → discover workload/obligations → run weekly priorities or propose a plan with real constraints | Cited priorities, proposed blocks, uncertainty and unmet capacity; no saved plan unless requested. |
| "These assignment instructions disagree." | Read assignment → resolve linked documents → review requirements/deadlines | Exact conflicting passages, versions, scope and a clarification need; no invented authoritative answer. |
| "Explain this figure in my lecture." | Discover file → read context → render original page/slide → inspect actual pixels → attribute observations | Grounded explanation with unreadable elements and inference labeled; no visual claims if pixels are unavailable. |
| "Use my imported syllabus to prepare an assessment review." | List local documents → obtain hashes → run independent assessment/requirements analysis | Bounded cited evidence from permitted imports without an LMS connection; coverage remains explicit. |

These are illustrative compositions, not a promise of perfect model tool selection
or support for every image/download path in an untested client.

## Evidence and pitch-safe claims

The [October 28 stress follow-up record](../evidence/sanitized-results/stress-followup-2026-10-28.md)
reports a source-bound full regression run of **1,924 passed, 29 skipped**, and a
separate **73-case corpus with 70 PASS, 0 FAIL and 3 BLOCKED**. These are dated
development results, not proof of production deployment or general model accuracy.
Environment-dependent skips and blocked UI, PPTX-observation and deployment-recovery
cases retain their own acceptance requirements. Later edits do not retroactively
refresh those receipts.

Implemented differentiators include evidence/provenance, explicit uncertainty,
selected-source authorization, deterministic arithmetic and planning, bounded
document processing, independent-source support and reviewed local state changes.
Pitch them as implemented controls with scoped evidence. Do not describe them as
universal institutional access, certified compliance, guaranteed academic accuracy,
fully verified visual comprehension or approved public distribution.

There are no Canvas submissions/edits, roster access, quiz attempts/question-bank
extraction, automatic email/discussion posting, calendar-write tools, active
notification delivery, arbitrary external operations, student token-paste
onboarding or a second chatbot/dashboard. Generic standard `search`/`fetch`
research-surface compatibility is not advertised; named material-search tools have
narrower contracts.

For a pitch or technical review, pair this resource with the
[architecture](provider-architecture.md), [authorization gateway](authorization-policy-gateway.md),
[data egress governance](data-egress-governance.md),
[privacy boundaries](third-party-privacy.md),
[reproducible compliance evidence](compliance-evidence.md), and
[release gates](../evidence/release-gates.md).

## Opt-in independent usefulness workflows

The [U01–U06 implementation](usefulness/implementation.md) adds authenticated
multi-file/ZIP import and evidence review, richer independent obligations,
own-feedback improvements, lexical conceptual search, selected study continuity
and on-demand reviewed change digests. `run_local_study_workflow` is read-only
and opt-in; concrete local saves use signed settings forms. Existing literal
search remains the default. Source text and saved interpretations cannot grant
permissions or produce official submission/mastery claims. See the
[executed evidence](../evidence/sanitized-results/usefulness-2026-10-29.md) for
synthetic, browser and host-client boundaries; this does not activate the personal service.


## Optional private library

When `BRIDGE_LIBRARY_ENABLED=true`, `get_library_status`, `list_library_items`,
`get_library_item`, `read_library_item`, `search_library` and `render_library_item`
use the standard `Result` envelope, current independent-source authorization and
final privacy projection. Exact versions map to `lib_<version-id>` for compatible
independent readers. Metadata disclosure is a recipient permission; owner browser
inventory remains a distinct channel.

`prepare_library_download` creates an expiring owner-session delivery receipt and
has `readOnlyHint=false`; it is absent when MCP read-only mode is enabled. No
`submit_library_files`, arbitrary-URL intake, grant mutation or deletion tool is
registered. Authenticated settings provide the upload/privacy controls. See the
[reconciled library contracts](private-media-library.md#host-gates-and-contract-reconciliation)
and [verification boundaries](../evidence/sanitized-results/private-library-2026-10-29.md).

The [academic operations analytics guide](academic-analytics.md) describes dated reviews, explicit measurement saves, report restatements and coverage for each supported source.
