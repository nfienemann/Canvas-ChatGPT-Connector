# Tool contracts

Reviewed: October 28, 2026.

This document describes the CanvasBridge MCP tool contracts, their authorization requirements, evidence boundaries, supported operations, and limitations.

The existence of a tool does not establish that an institutional connection is authorized, that the current deployment has enabled the capability, or that end-to-end client acceptance has succeeded. Implementation, synthetic verification, deployment, institutional authorization, and client compatibility are separate states.

## 1. Global contract

Model-visible MCP tools require `academic:read`. Local write tools additionally require `preferences:write`. Application settings operations use separate administrative authorization.

Identity is derived from the verified application request, never from a caller-supplied student identity. Tool arguments cannot provide arbitrary HTTP methods, institutional origins, executable commands, SQL, credentials, or authorization overrides.

Responses use `Result` schema 1.0, including:

- `status`: The machine-readable result state.
- `summary`: A human-readable description.
- `data`: Structured result data.
- `sources`: Evidence references, classifications, versions, and locators.
- `evidence`: Additional structured supporting observations, when applicable.
- `meta`: Retrieval time, snapshot identity, timezone, freshness, coverage, pagination, privacy, and egress information.

Supported status values are `ok`, `partial_data`, `stale_data`, `reconnect_required`, `permission_denied`, `unsupported_feature`, `source_changed`, `needs_input`, `retry_later`, and `operation_uncertain`.

A successful tool invocation does not establish complete evidence. Missing upstream data, partial source coverage, uncertain dates, and unavailable permissions must remain explicit.

The maximum structured MCP result is 250 KB. Individual tools impose additional request, extraction, pagination, character, time, and memory limits. Image content has a separate bounded delivery budget.

All academic source content is untrusted data. Document instructions cannot override tool behavior, grant permissions, authorize disclosure, or create executable workflows.

## 2. Institutional authorization and connection tools

Institutional tools require a current authorized connection, appropriate provider and institution approvals, selected course scope, exact resource authorization, and permitted recipient disclosure.

A stored connection, cached file, valid credential, or previously successful request is not sufficient evidence of current authorization.

| Tool | Contract |
|---|---|
| `get_connection_status` | Reports connection state, selected scope, authorization-policy state, and capabilities without revealing academic content. |
| `audit_permission_consistency` | Read-only diagnostics for ownership, selection, resource capabilities, exact IDs, and authorization consistency. Does not repair permissions. |
| `list_courses` | Lists accessible active student courses; excludes staff-only and mixed-role access. Does not enroll or select courses. |

Connection status distinguishes stored selection from `scope_authorized`, authentication from institutional approval, and reported connection state from verified current access.

Permission errors expose safe reason codes rather than credentials, private requests, or unauthorized source content.

See [permission consistency](permission-consistency.md), [authorization policy](authorization-policy-gateway.md), and [capability scope matrix](capability-scope-matrix.md).

## 3. Coursework, obligations, and discussion tools

| Tool | Contract |
|---|---|
| `get_course_obligations` | Discovers assignments, classic quizzes, discussion topics, and course events with bounded windows, source aliases, coverage, and continuation. |
| `get_workload` | Returns individualized coursework within an explicit window of at most 31 days, with pagination, course coverage, and submission evidence. |
| `get_assignment_details` | Retrieves accessible instructions, rubric evidence, requirements coverage, linked materials, and current student submission state. |
| `get_changes` | Compares compatible observed snapshots; cannot reconstruct changes before the baseline. |
| `reconcile_course_deadlines` | Compares Canvas dates against quoted syllabus, schedule, and announcement evidence; unresolved date applicability remains explicit. |
| `review_assignment_requirements` | Compares instructions, rubrics, related sources, and optional draft characteristics without predicting grades. |
| `audit_course_consistency` | Returns prioritized supported contradictions, missing information, evidence, possible consequences, and unchecked sources. |
| `list_course_discussions` | Lists selected-course discussion metadata without fetching thread entries or announcements. |
| `read_discussion_topic` | Reads a permitted prompt and optionally the authenticated student's own contributions. Peer bodies are withheld. |
| `get_my_discussion_participation` | Performs a bounded authorized scan of the student's posts and replies, reporting counts, timing, coverage, and uncertainty. |

### Discussion restrictions

Discussion access does not provide general access to classmates' conversations.

The implementation distinguishes metadata discovery, prompt reading, and verified self-participation. Peer identity and message-body disclosure remain unavailable without a separate authorized disclosure path.

A complete authorized scan may establish the absence of a visible student entry. Incomplete coverage, eventual consistency, missing timestamps, unknown deletion states, or restricted replies cannot establish absence.

A posted entry does not automatically establish rubric completion, sufficient participation, earned credit, or an on-time grade.

Discussion reads never post, reply, mark entries read, subscribe, or modify Canvas state.

See [discussion reading](discussion-reading.md) and [course obligations](course-obligations.md).

## 4. Grades and assessment evidence

| Tool | Contract |
|---|---|
| `get_gradebook` | Returns the student's visible reported grades without inventing hidden or unposted scores. |
| `get_course_grading_policy` | Collects Canvas grading configuration, visible scores, and versioned syllabus-rule candidates. |
| `calculate_course_grade` | Performs reproducible grade arithmetic under supported current, syllabus, projected, and required-score modes. |
| `audit_course_grade` | Reconciles reported, reproduced, and syllabus-derived grade calculations without collapsing them into one unsupported value. |
| `simulate_grade_scenario` | Evaluates explicitly hypothetical scores or target requirements against verified assessment identities and applicable rules. |
| `prepare_for_assessment` | Builds a bounded cited evidence package distinguishing explicitly assigned content from inferred relevance. |

Grade calculations preserve unknown, ungraded, hidden, excluded, dropped, and unsupported policy states.

A hypothetical score is not a Canvas What-If write. Estimated outcomes are not official grades or guarantees.

Syllabus policies require actual review tied to their returned versions. Unsupported grading structures, incomplete eligibility, missing scores, or contradictory source evidence prevent exact assertions.

Assessment preparation does not establish that material will appear on an exam. A course document's relevance is not equivalent to instructor-confirmed coverage.

See [grade auditing](grade-auditing.md).

## 5. Course files, extraction, and visual inspection

| Tool | Contract |
|---|---|
| `get_course_outline` | Discovers accessible modules, pages, and files, preserving bounded references and resource visibility. |
| `fetch_course_material` | Retrieves permitted page or document text with source-version-bound continuation. |
| `search_course_materials` | Searches previously fetched page content with current access revalidation. |
| `list_course_files` | Enumerates visible course files, module associations, opaque file IDs, and extraction metadata. |
| `read_course_file` | Reads bounded PDF, DOCX, PPTX, XLSX, text, and Markdown content, with source locators and extraction limitations. |
| `search_course_files` | Searches authorized document passages; optional unread-file extraction remains bounded and version-bound. |
| `get_file_extraction_status` | Reports file accessibility, format support, parser state, extraction coverage, and safe failure reasons without downloading. |
| `render_course_file_page` | Renders a permitted PDF page, or a supported PPTX slide, using the private image-delivery pipeline. |
| `render_course_slide` | Renders an authorized PPTX slide through the presentation derivative pipeline and page reader. |
| `inspect_course_figure` | Finds likely figure locations and optionally renders one candidate page or slide under bounded inspection controls. |
| `record_course_figure_observation` | Records an attributed visual observation from an actual inspected image receipt without changing extracted source text. |
| `interpret_course_schedule` | Structures visually inspected schedule rows and identifies source-based dates; may prepare calendar proposals without writing events. |
| `prepare_course_file_download` | Prepares an unchanged authorized original for private download delivery independently of text extraction. |

### Document extraction boundaries

Text extraction operates through bounded isolated workers. Metadata discovery does not grant permission to read a document's body.

PDF, DOCX, PPTX, XLSX, text, and Markdown readers preserve source version, extraction status, locators, and available coverage.

General text windows are bounded to 16,000 characters; PPTX reading has additional slide and character limits.

XLSX extraction reports stored workbook cells, sheet identities, formula text, cached values, and relevant formatting metadata. It does not calculate formulas, execute macros, refresh external connections, or guarantee that cached values are current.

Sheet positions are not printed Excel page numbers. Numeric dates and formatted identifiers preserve their stored representations rather than becoming assumed localized display values.

Unread-file search is bounded. An empty search result cannot establish that a term is absent from inaccessible, unreadable, truncated, or unsearched content.

### Visual evidence boundaries

A successful renderer establishes image preparation, not necessarily image visibility to the language model.

The visual pipeline distinguishes:

1. Source authorized and retrieved.
2. Page or slide rendered.
3. Image delivered or made available to the host.
4. Image actually visible to the model.
5. Attributed visual interpretation completed.
6. Interpretation independently verified.

The latter stages cannot be inferred from earlier transport success.

Figure candidates found through captions, page text, labels, or layout clues are not visually confirmed figures.

Visual observations must be based on pixels actually exposed to the interpreting model. Missing or unreadable pixels require an explicit unavailable or uncertain outcome.

Graph axes, values, error bars, statistical significance, legends, and table structure must be reported separately as observed, uncertain, or unreadable. Numerical estimates cannot be represented as exact source labels.

Visual observations and proposed extraction corrections do not silently overwrite source documents or become independently verified scientific findings.

See [visual inspection v2](visual-inspection-v2.md), [PPTX visual pipeline](pptx-visual-pipeline.md), [scientific document comprehension](scientific-document-comprehension-v3.md), [file reading](file-reading.md), and [XLSX reading](xlsx-reading.md).

## 6. Planning, studying, and academic orchestration

| Tool | Contract |
|---|---|
| `propose_study_plan` | Produces a bounded deterministic plan from a recent workload snapshot and explicit student constraints. |
| `propose_course_study_plan` | Plans selected assignments, quizzes, discussion participation, and event preparation using current obligation inventories. |
| `propose_calendar_sync` | Builds deduplicated proposed events from verified academic dates and caller-supplied authorized calendar context. |
| `prepare_study_session` | Prepares source-grounded explanations, concepts, and voluntary active-recall practice using permitted course material. |
| `run_academic_workflow` | Executes a fixed registry of reviewed read-only multi-step academic workflows, returning partial and unsupported steps explicitly. |
| `get_semester_overview` | Analyzes selected courses for observed changes, deadlines, grade evidence, workload conflicts, and explainable priorities on demand. |

### Workflow registry

`run_academic_workflow` supports seven fixed workflows:

- Daily Academic Brief
- Weekly Course Priorities
- Exam Preparation Pack
- Grade Outlook
- Course Discrepancy Review
- Lecture Comprehension
- Calendar Preparation

Callers select the workflow and bounded inputs. They cannot supply arbitrary tool names, executable graphs, permission overrides, or background schedules.

Existing underlying tool contracts remain authoritative. The orchestrator does not bypass source authorization, integrity checks, response limits, privacy filtering, or recipient policy.

A partial workflow must describe which operations completed, failed, were denied, or were not attempted.

### Study sessions and evidence of learning

Generated practice questions must be distinguishable from actual instructor assessments.

Practice questions should be presented before answers are revealed. Viewing content does not establish mastery.

Student responses must not be fabricated. Scoring or review depends on the actual response and its source evidence.

Shared terminology across courses does not independently establish a meaningful scientific relationship.

### Planning and calendar restrictions

Timed filters use half-open instants. Date-only records retain local calendar dates rather than manufactured times.

Unknown effort is not inferred from assignment points, titles, or quiz duration.

Planning uses supported effort ranges, availability, breaks, buffer, prerequisites, and explicit conflicts. Unknown timing or prerequisites must remain provisional.

Daylight-saving transitions are handled using elapsed time and applicable source timezones.

Calendar availability must come from actual authorized calendar context or clearly identified student-provided constraints. CanvasBridge does not independently verify free time from a calendar proposal request.

Calendar proposals do not create, update, or delete external events. External calendar writes require separate user confirmation, native provider authorization, and action verification.

See [academic workflows](academic-workflows.md), [activity study planning](activity-study-planning.md), and [planning date boundaries](planning-date-bounds.md).

## 7. Independent academic intelligence

Independent academic intelligence is a separate source-acquisition pathway from institutional LMS access.

It requires verified application identity, permitted independently imported material, current source rights, academic-integrity checks, and recipient authorization. It does not require an active Canvas connection merely because the academic reasoning concerns coursework.

Institutional or derived institutional information retains its original restrictions. Disconnecting Canvas, copying files, changing labels, or reimporting previously restricted material does not automatically make that information independently authorized.

### Independent tool inventory

| Tool | Contract |
|---|---|
| `list_local_documents` | Lists the user's permitted independent imports without contacting an institution. |
| `get_local_document_status` | Reports document identity, current content hash, extraction coverage, and limitations. |
| `read_local_document` | Returns bounded authorized excerpts, provenance, and continuation for an owned independent import. |
| `search_local_documents` | Searches extracted independent document text; missing visual or textual coverage remains explicit. |
| `prepare_local_study_materials` | Collects cited evidence for ChatGPT to produce permitted learning materials; does not claim a separate backend language model. |
| `render_local_document_page` | Renders an imported PDF page only with the required per-document visual-sharing permission. |
| `get_local_study_preferences` | Reads schema-restricted independent study preferences without institutional authentication. |
| `get_saved_study_state` | Reads independent or legacy local-only preferences by default; requesting institutional derived plans/progress requires active authorized source access. |
| `run_independent_academic_workflow` | Performs bounded academic analysis on explicitly selected independent documents using shared deterministic reasoning services. |

ChatGPT conversation attachments are not automatically imported into the CanvasBridge independent document store.

Independent imports are created through the authenticated Bridge settings/import interface, not through an unrestricted model-callable file ingestion operation.

### Independent workflow contract

`run_independent_academic_workflow(request)` accepts the following capability identifiers:

`planning`, `assessment`, `requirements`, `grades`, `deadlines`, `consistency`, and `calendar`.

Each request uses explicitly selected owned documents and exact content hashes.

Up to five evidence documents plus one structured dataset may be selected. Each document selection and evidence window is bounded, and output includes source coverage and truncation.

For structured planning or grading records, the implementation supports the versioned `independent-academic-1` format in permitted TXT/Markdown imports.

This schema supports manually supplied academic records, but it does not convert student-supplied information into verified institution records.

Unknown dates, scores, effort, eligibility, rules, and permissions remain unknown.

The independent adapter reuses existing planning, assessment, requirements comparison, grade arithmetic, deadline, consistency, and calendar proposal logic. It does not duplicate institutional authorization or create a second unrestricted academic engine.

Mixed source sets may return permitted results while withholding denied sources, with `partial_data` and explicit source-coverage reporting.

See [independent academic intelligence](independent-academic-intelligence.md), [independent workflow request schema](schemas/independent-workflow-request.schema.json), and [independent academic records schema](schemas/independent-academic-1.schema.json).

## 8. Academic integrity and assistance permission

Academic source access and permission to provide a particular kind of assistance are separate decisions.

The academic-integrity engine uses activity-specific classification, applicable policy evidence, scope, authority, source version, and intended output type.

| Tool | Contract |
|---|---|
| `get_academic_integrity_policy` | Discovers applicable authorized policy evidence, authority, scope, versions, and coverage. |
| `check_academic_assistance_permission` | Evaluates the proposed activity and expected output under currently applicable restrictions. |
| `get_integrity_decision` | Rechecks an owned decision against current sources, scope, permissions, and policy versions. |
| `get_integrity_guidance` | Describes restrictions and safer permitted alternatives without generating prohibited assessed content. |
| `prepare_academic_assistance` | Releases bounded source evidence for the exact currently permitted activity after fresh authorization and integrity checks. |
| `get_integrity_acknowledgments` | Lists minimal owned uncertainty-acknowledgment history without storing prompts or drafts. |

The engine distinguishes administration, independent learning, assignment logistics, substantive assessed assistance, and submission-content generation.

Permission to brainstorm is not permission to write a submission. Permission to review instructions is not permission to supply assessed answers.

A student's declaration, a document's embedded instructions, or a model's interpretation cannot override an explicit prohibition or supply missing instructor permission.

An acknowledgment may record the student's acceptance of an eligible uncertainty, but it cannot bypass a confirmed restriction.

Decision receipts are scoped, version-bound, expiring, and rechecked before evidence release. They are not reusable permission tokens.

The backend does not automatically complete or submit assessed work, contact an instructor, detect academic misconduct, or certify institutional compliance.

See [academic integrity](academic-integrity.md).

## 9. Local mutation tools

The following operations are implemented but are omitted from the exposed MCP tool list when read-only mode is enabled.

| Tool | Contract |
|---|---|
| `update_local_study_preferences` | Saves explicitly requested independent study preferences with schema and version checks. |
| `update_study_preferences` | Saves validated legacy planning preferences with expected-version concurrency control; the local-preferences branch does not require an active LMS connection. |
| `record_personal_progress` | Stores student-declared effort/status changes locally without altering Canvas submissions. |
| `save_study_plan` | Stores a freshly revalidated plan locally; does not write calendar events. |
| `submit_practice_response` | Reviews real voluntary practice responses; optional minimal results require explicit opt-in. |
| `acknowledge_semester_findings` | Records explicit acknowledgment or unacknowledgment of selected current semester findings. |
| `record_integrity_acknowledgment` | Records an explicitly acknowledged, eligible integrity uncertainty. |
| `provide_instructor_permission_evidence` | Evaluates already permitted independent evidence as unverified instructor-permission material; does not authenticate an instructor. |
| `revoke_integrity_acknowledgment` | Revokes an owned acknowledgment without modifying underlying academic policy. |

Local mutation requires explicit user intent, current source rights where applicable, and correct version or receipt constraints.

Local state is not automatically institutional state.

An acknowledgment is not completion. A saved plan is not a calendar event. A recorded practice result is not a course grade. Student-declared progress is not verified submission evidence.

Read-only mode suppresses tool registration rather than merely relying on a natural-language instruction against writes.

## 10. Semester intelligence and notifications

`get_semester_overview` is an on-demand analysis tool, not a background monitor.

It combines permitted course observations to identify supported upcoming obligations, potentially consequential revisions, workload clusters, grading uncertainties, and study-plan conflicts.

Findings expose evidence, issue identity, semantic revision, current status, priority, and uncertainty. The prioritization is heuristic rather than a prediction of academic success.

An incomplete baseline cannot prove a newly created assignment. A recent observation does not establish the time a source was changed.

User-configured semester preferences may include priorities, planning periods, workload tolerance, and notification preferences.

Saving a notification preference does not schedule a notification.

Background monitoring and delivery require a separately approved host scheduler, explicit opt-in, fresh source authorization, and delivery-receipt handling. No active notification mechanism is provided by these MCP tools.

See [semester intelligence](semester-intelligence.md).

## 11. Conditional academic-process tools

The academic-process layer is controlled by `BRIDGE_PROCESS_FEATURES_ENABLED`, which defaults to `false`.

When enabled, the process tool registry may expose:

| Tool | Contract |
|---|---|
| `evaluate_academic_process` | Evaluates scoped evidence, contradictions, feasibility, lifecycle, identity, concepts, unofficial degree progress, clarification, annotation, and portfolio publication clearance. |
| `preview_academic_process_change` | Produces an expiring preview of an explicitly requested local record creation or correction. |
| `confirm_academic_process_change` | Applies a reviewed exact preview with confirmation, source rechecks, and an idempotency key. |
| `get_academic_process_records` | Inspects owned current process records and their permitted state. |
| `get_academic_process_impacts` | Reports observed changes and dependent repair needs. |
| `preview_academic_process_recovery` | Previews deletion or rollback of selected local records. |
| `export_academic_process_records` | Returns explicitly selected permitted records as versioned JSON or Markdown. |
| `get_academic_support_report` | Previews a minimal diagnostic report without academic payloads, credentials, or raw errors. |

Read-only mode additionally omits the process preview/confirmation mutation tools.

The process registry is not an autonomous task agent. It cannot submit assignments, send messages, make calendar mutations, perform background monitoring, or publish work.

### Portfolio limitation

Portfolio evaluation performs source-, rights-, attribution-, privacy-, and publication-clearance review.

It does not by itself generate or host a public portfolio website, publish an HTML artifact, or establish rights to disclose group projects, copyrighted material, patient information, or confidential research.

The current reviewed-export and portfolio-clearance mechanisms must not be documented as a generally available portfolio-generation or publication product unless separately implemented, enabled, and verified.

See [academic process implementation](process-specifications/implementation.md).

## 12. Source provenance, privacy, and consistency

Every source-backed operation must preserve its applicable provenance and limitations.

The implementation distinguishes:

- Source facts and directly retrieved evidence.
- Deterministic calculations based on supported inputs.
- Student-supplied assertions and preferences.
- Assistant-generated interpretations or hypotheses.
- Unknown or unsupported claims.

Course files, independent imports, visual observations, local state, and inferred conclusions cannot silently become interchangeable evidence.

Source access is rechecked before sensitive output. A cached copy does not provide rights after revocation, withdrawal, source changes, or recipient-policy denial.

Private student and peer data must be minimized under the applicable source, privacy, academic-integrity, and final egress policies.

Unknown rights or classifications cannot be corrected by assigning a more permissive label.

Revocation and deletion must also respect the relevant derived-state and dependency cleanup rules.

See [data egress governance](data-egress-governance.md), [data lifecycle controls](data-lifecycle-controls.md), and [third-party privacy](third-party-privacy.md).

## 13. Original file delivery

`prepare_course_file_download(connection_id, file_id, expected_source_version?, expected_bytes_sha256?)` prepares exact currently authorized source bytes independently of text extraction.

An `ok` result means the original was prepared for delivery. It does not mean the user received, saved, or attached the file.

The companion `get_course_file_download_payload(connection_id, delivery_id)` is an application-visible private operation, not a general model-visible academic reading tool.

Delivery requires renewed ownership, permission, source-version, and expiration checks. The mechanism may provide bytes or a bounded temporary resource depending on supported client capabilities.

Temporary signed URLs and private delivery payloads must not be exposed as ordinary source references.

Actual ChatGPT attachment delivery must be established through client acceptance testing; a successful backend preparation alone is insufficient.

See [original file delivery](original-file-delivery.md).

## 14. Verification and release boundaries

A documented tool may exist at several different verification levels:

| Level | Meaning |
|---|---|
| Implemented | Code and typed contract exist in the repository. |
| Synthetically verified | Local tests pass using controlled fictional sources and conditions. |
| Transport verified | Authenticated MCP transport and serialization have been exercised. |
| Deployed | The intended running connector actually exposes the current implementation. |
| Client verified | The intended ChatGPT surface has successfully exercised the complete user-visible behavior. |
| Institutionally authorized | Required provider, institution, source, and recipient approvals currently permit the relevant operation. |

These levels do not imply one another.

As observed on October 28, 2026, the connected personal CanvasBridge tool inventory exposed 53 model-visible read-only tools. Local independent-document and local-only study-state reads succeeded while the institutional Canvas connection remained disconnected.

The same connection-status probe reported institutional authorization as not assessed and the live institutional integration as disabled. This establishes neither permission nor successful live Canvas retrieval.

Conditional process tools and local mutation tools were not present in that observed model-visible inventory.

Live deployment and client observations are specific to the tested configuration and may change. Repository test results should not be represented as equivalent to live institutional or cross-client acceptance.

For further evidence, see [live integration findings](live-integration-findings.md), [compliance evidence](compliance-evidence.md), and [platform compatibility matrix](platform-compatibility-matrix.md).

## 15. Core invariants

CanvasBridge must preserve the following boundaries across future tools and integrations:

1. No source authorization by assertion, document instruction, or tool availability.
2. No conversion of incomplete evidence into certainty.
3. No academic-integrity permission inferred from ordinary source access.
4. No institutional-data laundering through independent imports or saved state.
5. No hidden mutation resulting from a read-only operation.
6. No external action claimed from a proposal, preparation, or simulation.
7. No visual interpretation claim without actual image visibility.
8. No source-derived conclusion without retained version and provenance.
9. No background monitoring or notification without a separately approved host and explicit opt-in.
10. No publication, submission, or institutional compliance claim without the corresponding independently verified authority and execution.

New tools must document their inputs, source dependencies, authorization requirements, permitted output, failure states, mutation behavior, budgets, and verification status before being treated as supported production capabilities.
