# Tool contracts

All tools require `academic:read`; local writes additionally require
`preferences:write`. Identity comes from the verified request, never a tool
argument. Inputs have bounded typed schemas; no arbitrary URL, student identity,
HTTP method, SQL or command parameter exists.

Responses use `Result` schema 1.0: status, readable summary, data, sources and
metadata (snapshot, retrieval time, timezone, freshness, coverage, continuation).
Missing upstream data is not success with an empty list. Maximum serialized
response size is 250 KB; callers must narrow excessive requests.

| Tool | Result boundary |
|---|---|
| get_connection_status | Owned identity/scope/capability state; fictional profile visibly labeled |
| list_courses | Active student courses; staff/mixed roles excluded; does not select courses |
| get_workload | Explicit <=31-day window; max 100 items/page; course coverage and encrypted bound cursor |
| get_assignment_details | Fresh accessible requirements/rubric; no locked material |
| get_changes | Complete matching-scope baselines only; first observed is not newly published |
| get_gradebook | Own visible Canvas fields; no unposted fields or exact-policy assumptions |
| get_course_grading_policy | Own visible grade evidence and configuration; exact syllabus quotes/versions and conservative candidate rules |
| calculate_course_grade | Deterministic current/syllabus/projected/required-score modes; refuses unsupported or incomplete policy inputs |
| audit_course_grade | Reported/reproduced/syllabus estimates remain distinct; neutral reconciliation and explicit insufficient evidence |
| simulate_grade_scenario | Conditional visible-work simulations only; no Canvas What-If writes or inferred future scores |
| reconcile_course_deadlines | Quoted dated obligations and exact-title matches; ambiguous matches, precision, timezone and source precedence remain explicit |
| review_assignment_requirements | Instructions/rubric/related passages; deterministic numeric conflicts and ephemeral draft word count, no grade prediction |
| prepare_for_assessment | Cited bounded reading pack; explicitly assigned versus inferred relevance; no invented next quiz or coverage |
| propose_calendar_sync | Fresh conversation-supplied native Calendar context; deduplicated confirmation-only create/update proposals; provider-held mapping markers |
| audit_course_consistency | One-course prioritized supported findings, impact, evidence, next action and unchecked resources |
| get_course_outline | Bounded modules/items/pages/files with one overall time budget; course-bound material references join visible module items; listing never proves a reading was accessed |
| fetch_course_material | Backward-compatible page or file text; fresh access checks, content-hash-bound continuation; files require enabled OS isolation |
| list_course_files | Selected-course metadata with module associations, opaque file IDs, stable Canvas links and indexed state; resolves visible module files even when the Files collection is denied |
| read_course_file | PDF/DOCX/PPTX/TXT/Markdown text windows, PDF page ranges/locators, metadata, hashes and explicit extraction limits; max 16,000 characters per window |
| search_course_files | Previously extracted authorized file text only; page passages, indexed count, unindexed documents and incomplete-coverage flags |
| get_file_extraction_status | Fresh authorization without downloading; available/downloaded/parsed/partially_parsed/unsupported/failed/inaccessible state and reason |
| search_course_materials | Previously fetched page index only; fresh access recheck before returned hits |
| propose_study_plan | Stateless priorities/allocation; no calendar access or saved side effect |
| get_saved_study_state | Local record versions for explicit later changes |
| update_study_preferences | Persistent scoped preference write with expected version |
| record_personal_progress | Persistent personal status/effort; never Canvas submission evidence |
| save_study_plan | Fresh proposal validation and local version receipt; not a calendar action |

Timed filters use half-open instants. Date-only items stay dates and are included
when their local calendar date intersects the requested window; an exactly
midnight end excludes that end date. No 11:59 PM time is manufactured.

Effort is not inferred from points. Unknown effort produces a bounded requirements
review. Plans use upper effort bounds, reserve breaks/buffer and report unmet
minutes. Unknown prerequisites keep otherwise fitting plans provisional.
Replanning accepts explicit busy intervals and pinned study blocks. Pins are
preserved; conflicts with busy time, source deadlines or availability require a
correction. Dependency completion must precede dependent sessions. Supplied
calendar constraints are conversation input, not verified Calendar access.

Saved preference values are returned for conversation reuse. Callers should pass
the student's saved preferences into explicit plan constraints; a read never
silently saves a correction.

No Calendar mutation/notification or generic standard `search`/`fetch` compatibility
tool is advertised. Calendar proposals use the native connection composition described
in [academic intelligence](academic-intelligence.md). Standard research-surface adapters require separate actual
client verification before being added.

Workload and assignment details request the same current-user submission
inclusion and return `submission_evidence` and `submission_state_basis`. An
unknown submission is never replaced with stale cached certainty. `not_submitted`
means Canvas's online record, not proof of offline completion or future relevance.
Undated records expose `due_date_status` and `schedule_status`; null Canvas dates
do not establish unscheduled or upcoming assessments. Unconfirmed undated work
does not become an automatic study allocation without current student input.

Assignment details preserve `requirements_text` and add `requirements_coverage`
with explicit empty/missing/invalid/non-text/truncated states and description-only
scope. A successfully fetched empty description does not mean no requirements
exist. Retrieval failures remain errors. `get_changes` exposes its actual stored
comparison interval, missing-baseline reason and incomplete-observation coverage;
it cannot reconstruct pre-baseline history or exact change times.

See [live findings and root causes](live-integration-findings.md).

Grade tools add no new identity scope or persistence. Syllabus candidates require
actual student review tied to the returned policy version; the assistant cannot
manufacture that review. Unsupported rules, missing eligibility, hidden scores,
period uncertainty or contradictory detail/list evidence prevent exact claims.
See [grade auditing](grade-auditing.md) for schemas, formulas, limits and examples.

The file inventory requires explicit current-user visibility and excludes hidden
or locked files. A module label can remain visible without a usable material
reference when its resource is absent from the accessible bounded inventory.
Module inclusion does not establish whether a reading is assigned or optional.
Only previously extracted file bodies are searched by `search_course_files`;
`search_course_materials` retains its page-only behavior. Signed download URLs
are never returned or persisted as sources. See [file reading](file-reading.md).
