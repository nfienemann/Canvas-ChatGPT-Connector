# Additional workload and assignment regressions

The October 23 report and its selected response fields are investigation evidence,
not an executable live replay or authorization to change accounts. Regression
tests use fictional assignments, file metadata and credentials. Live course,
work, snapshot and request identifiers are not copied into the repository.

## Behavior and evidence

| Finding | Repair / investigation |
|---|---|
| F1 workload selection | A snapshot retains its full source inventory plus an immutable `workload_scope` describing the requested window, flags, courses, all filtered work IDs and collection completeness. Planning and Calendar proposals consume that selection, including later response pages. Inputs for excluded work are rejected. |
| F2 future openings | Current actionability stays distinct from future planning eligibility. Future-locked work may receive conditional blocks after a known opening and before the applicable deadline/closing bound. Blocks and timing evidence require a future access recheck. Missing openings block allocation; closed/inaccessible/completed work has an explicit omission reason. `work_accounting` covers every selected item even when recommendations are capped. |
| F3 feasibility | `known_capacity_status` and `information_status` separate numerical capacity from uncertainty. Only unallocated minutes caused by capacity count toward `known_shortfall_minutes`. Unknown effort, relevance, prerequisites or timing do not become zero effort or a demonstrated shortage. Existing `timing_unresolved`, `availability_unknown` and partial-workload classifications remain. |
| F4 linked instructions | Assignment details preserve explicit anchors as structured references. At most 20 links and 10 seconds of course-qualified file metadata checks register authorized opaque material IDs; filenames alone never become IDs. No linked bytes are downloaded by details. Automatic requirements review prioritizes these documents over schedule/syllabus hints within the existing document/read budgets, and includes their cited contents even without a title match. External, unsafe, cross-course, denied, unresolved, skipped and parser-blocked links remain explicit. |
| F5 hash observations | The existing hash includes raw description and submission fields, so rotating file authorization or submission-preview URLs can change it. Synthetic tests reproduce that mechanism. Retrieval time itself is not a hash input. The historical live cause remains unconfirmed because the supplied report does not include raw hash inputs. The exact `content_hash` is retained; an additive versioned `semantic_hash` excludes known transport parameters and retains academic fields, rubric, link identity and non-transport query values. No existing change detection or reconciliation is switched to the new hash. |
| F6 provenance | Planning propagates assignment coverage, pagination completeness, source timestamps and display timezone. It does not infer syllabus or whole-course coverage. Timing separates `past_due` from `overdue_recovery`; submitted, graded and excused records do not acquire a recovery obligation. |

`semantic_hash` describes selected assignment fields, not the contents of linked
documents or every Canvas field. It supplements the original source hash and
does not prove that an external document is unchanged. Submission reconciliation
still compares fresh observations of the same reported source update.

## Activation boundary

Migration `62ab7d391c04` adds `snapshots.workload_scope`. Apply the normal database
migration before activating this build. Existing snapshots have unknown scope
and require a fresh workload read before planning; their raw inventory remains
available for history. Internal unfiltered refresh snapshots are explicitly
labeled `source_inventory`.

This change does not restart or migrate the private running service, refresh
credentials, change selected courses, write Canvas or Calendar, save a plan,
fetch quiz questions/attempts, or bypass the document-parser restart guard.
Live installed-connector acceptance remains separate from local synthetic tests.

Validation is recorded in
[the sanitized evidence record](../evidence/sanitized-results/additional-regressions-2026-10-23.md).
