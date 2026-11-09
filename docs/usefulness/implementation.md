# Independent usefulness workflows

This implements the smallest independent-source journeys in U01–U06. The original
specifications and their byte inventory are retained in [source](source/README.md).
They are requirements, not execution evidence. Actual checks are recorded in the
[verification report](../../evidence/sanitized-results/usefulness-2026-10-29.md).

## Existing components and changes

| Area | Reused foundation | Added behavior |
|---|---|---|
| U01 imports | Signed settings sessions, CSRF, encrypted independent resources, isolated parser workers, existing document tools | Multi-file/ZIP picker, receipts and cancellation, course/purpose, separate processing/sharing choices, explicit replacement, candidate accept/edit/omit forms, normalized reviewed input |
| U02 obligations | `IndependentAcademicInput`, `WorkItem`, planning and calendar proposal engines | Activity types, requirement/role/progress distinctions, explicit aliases/parents, minimum-count groups, full selected-inventory accounting, opaque course/source-bound identities |
| U03 feedback | Independent readers, source integrity and egress policy | Exact passage validation, own-work links, at most three provisional improvements, optional ungraded practice, explicit saved improvement and limited response check |
| U04 search | Existing local search/read tool names and parsed representations | Opt-in conceptual mode, inspectable lexical expansions, original offsets, course/source scope, bounded ranking, version-bound continuation and read continuation |
| U05 continuity | Existing encrypted academic process repository and revision/dependency model | Explicit goals and attempted outcomes, correction/rejection, fresh-session resume, collection controls, session deletion and export |
| U06 changes | Retained import reviews and process revisions | On-demand old/new evidence, stable transition identities, plan-review implications, explicit acknowledgment/snooze; no automatic delivery |

No second database, language-model backend, account system, dashboard, LMS adapter,
vector service or notification sender is introduced. The settings forms perform
local review and consent; substantive academic assistance remains in the host chat.

## Operator setup and rollback

`BRIDGE_USEFULNESS_FEATURES_ENABLED=false` is the default. Enabling it registers
the read-only `run_local_study_workflow` tool and links the new import forms from
the existing independent-document settings. A normal authorized service restart
is required for configuration changes; development does not restart the personal
service. File extraction additionally needs the existing enabled isolated parser
and writable private parser root. Existing independent recipient policy is still
required for model sharing. No new setting grants provider or institution access.

`BRIDGE_CONCEPTUAL_SEARCH_ENABLED=true` permits callers to select conceptual mode
on the existing local search tool. Its default remains literal. Disabling the flag
rejects conceptual calls and leaves literal behavior available.

No migration is needed for these six features: imported sources and bounded batch
receipts use existing encrypted independent resources; reviewed state uses the
existing versioned academic process envelope. Additive normalized fields have
legacy defaults. Existing legacy TXT/Markdown structured inputs remain accepted.
The separate usage-governor migration in this checkout is not a usefulness migration.

Rollback: disable the usefulness flag and restart the selected instance. Local
export, deletion and permission-revocation routes remain available. Export/delete
new state before rolling back the application binary: old clients may reject the
new declaration-backed records. Never restore independent content to recover access.
The existing backup policy deliberately excludes independent documents, process
state and import batches; this is stronger than relying on a backup deletion filter.

## Student paths

1. Open signed-in settings → independent documents → **Add course materials**.
   Select a course, purpose and concrete files, then choose processing and sharing
   separately. Inspect receipts, remove a selection, cancel pending work or retry
   failed selections. Completed imports survive cancellation.
2. Open **Inspect, review, correct or remove**. Exact source passages accompany
   candidate dates, titles, word counts and percentages. Accept/edit/omit activities;
   leave unsupported or ambiguous facts unknown. Advanced controls cover roles,
   relationships, opening/closing dates, completion rules and progress assertions.
3. The reviewed document works with the existing independent academic adapter.
   The new local-study tool combines permitted reviewed records and personal tasks
   into obligations and planning proposals. It accounts for the complete selected
   inventory even when activity display is paginated.
4. For feedback, choose **own feedback** at import and explicitly link it to the
   student's work. Request feedback evidence/improvements, optionally try generated
   ungraded practice, and explicitly save only selected outcomes in study settings.
5. Save a goal and an attempted response. A later chat can request `resume` with the
   course and goal. Reject/correct/delete an interpretation or disable future outcome saves
   using authenticated settings. Reads never save history.
6. Replace a schedule using its explicit current document identity/version. Review
   new candidates and select the prior activity identity where the relationship is
   known. Request `changes` to compare retained reviewed versions. View, acknowledge
   and snooze are distinct actions; plans and calendars are never changed.

`run_local_study_workflow` takes `operation` (`obligations`, `feedback`, `resume`,
`changes`), a course and bounded source selections with expected hashes. It has no
write/confirmation argument. Local writes use authenticated browser actions even
when `BRIDGE_MCP_READ_ONLY=true`.

For conceptual search, pass `mode="conceptual"`, explicit `document_ids` and,
optionally, a course to `search_local_documents`. Hits contain exact original
quotes, parts/locators, start/end offsets, relevance reasons and a read continuation.
The continuation's `start_offset` and `characters` are accepted by the existing
`read_local_document` tool. Ranking is lexical relevance, not factual confidence.

## Bounds and evidence semantics

- Import: 20 stored documents per owner; 10 MB/document; 50 MB ZIP; 100 entries;
  200 MB expanded total; 50:1 maximum expansion. The stricter existing owner cap
  takes precedence over the proposed 25-document batch. Path traversal, links,
  encrypted/nested archives and collisions are rejected before publication.
- Documents and batch receipts expire within 24 hours; process records expire
  within the existing 30-day envelope. Source-dependent state requires a current
  permitted source and can become unavailable earlier. These short lifetimes
  constrain multi-day source-based continuity; independent goals can remain usable.
- Candidate extraction: 200 parts, 200,000 characters/part, 50 candidates,
  four displayed candidates per review page. Candidate extraction is deliberately
  narrow. Percentages are not automatically converted into a complete grade policy.
  Unsupported grade rules still block calculations through the existing adapter.
- Inventory: 5 selected documents, 50 activities, 20 displayed per page maximum.
  Aliases require explicit reviewed relationships; matching titles never merge work.
  Official submission remains unknown for independent inputs. Required revisions
  remain eligible even when the student reports a prior grade/submission.
- Search: 20 selected documents, 8 expansion terms, 1,000,000 searched characters,
  5,000 passages, 200 parts/document, 20 hits/page. Cutoffs are reported as partial
  coverage. Cursors bind owner, query, scope, representation and ranker for 15 minutes.
  Only extracted text is searched; image candidates are not pixel interpretation.
- State: existing 500-record/2 MB process cap; 8 KB per attempt; at most 3 feedback
  proposals. Feedback supports exact references but cannot authenticate instructor
  authorship or certify an interpretation. Keyword practice checks never establish
  mastery. Duplicate comments do not establish repeated difficulty.
- Changes: 100 retained derived events per request inventory and bounded pages.
  Missing items do not establish deletion/completion. No-change processing events
  do not establish unchanged unseen sources. Baselines, history gaps, date precision
  and explicit identity links remain visible. Snoozing one transition does not
  suppress a later distinct transition.

All model release paths recheck owner/source version, integrity, permissions and
the configured recipient. Saved record citations carry underlying document lineage.
Revocation/course reassignment removes dependent current and historical state.
Corrections cannot remove previously retained source dependencies. Source text is
data and cannot authorize recording, messages, external reads or policy changes.

## Remaining acceptance gates

The independent baseline does not establish real ChatGPT attachment transfer,
installed-client selection/rendering, institutional authorization, public release,
PostgreSQL multiworker behavior or student learning gains. The first-time-user pilot,
independent review of gold retrieval/obligation fixtures, representative large-course
corpora and host end-to-end latency measurements remain separate work. Automatic
notification delivery, vector retrieval and live-provider expansion are not enabled.

Run `python -m pytest -q tests/test_usefulness.py tests/test_usefulness_benchmark.py`
for the focused checks and `python scripts/benchmark_usefulness.py --output PATH`
for reproducible lexical retrieval evidence. See the report for actual commands,
case coverage and known failures; a numbered test name alone does not prove every
clause of the corresponding specification.

For packet reimports, missing-material recovery, workspace export and restore,
and reviewed local/Canvas assignment links, see [course content portability](../course-content-portability.md).
