# Discussion reading and participation

Local implementation, October 26, 2026. This implements the owner's Discussion
Post Read Spec v1.0 with synthetic evidence. It grants no institutional, vendor,
privacy, OAuth, hosting, or deployment approval.

## Tools and interpretation

- `list_course_discussions(connection_id, course_id, include_archived=false,
  include_undated=true, limit=50)` retrieves topic metadata. It excludes
  announcements and requests no thread entries. “Archived” means Canvas's
  `locked` (closed for comments), not completed work. Dates absent from metadata
  remain unknown until a topic read.
- `read_discussion_topic(connection_id, course_id, topic_id,
  include_entries=false, entry_scope=self_only, limit=100)` retrieves a sanitized
  prompt, date evidence and safe course-file references. Optional entries contain
  only the authenticated student's contributions. Numeric topic IDs come from
  discovery; course IDs use the existing exact opaque identifier contract.
- `get_my_discussion_participation(connection_id, course_id, topic_id,
  refresh=false)` performs a fresh bounded scan. `refresh=true` also makes a fresh
  request: this implementation intentionally has **no discussion-result cache**.
  No raw peer thread data is persisted or made available to a model.
- `get_course_obligations(..., include_discussion_participation=true)` adds fresh
  evidence to the returned inventory page. It does not change canonical IDs or
  the inventory version. Ordinary inventory requests do not read threads.
- `audit_course_consistency(..., include_discussions=true)` adds a bounded
  per-topic report, date conflicts, distinct reply deadlines, missing assignment
  representations and completion claims requiring investigation.
- `propose_course_study_plan` refreshes participation only for explicitly
  student-requested discussion activities. Partial evidence goes to `needs_review`.
  Verified outstanding reply counts use the reply deadline within the existing
  canonical activity. Observed count matches do not mark an assignment completed.

`verified_absent` requires exhausted authorized coverage, verified identity,
handled cached-view freshness and no unresolved omissions. An overall partial
scan can still report a verified initial post and lower-bound counts. Creation
time, never edit time, determines `observed_on_time`/`observed_late`. Missing
timestamps or deadlines retain their explicit unknown states. All results are
time-bounded observations; they do not establish rubric satisfaction or grades.

## Implementation sequence and reuse

1. Inspect the existing client, selected-course identity/lease checks, signed
   approval gateway, endpoint schemas, privacy and egress boundaries.
2. Add typed discussion evidence and individually reviewed GET routes.
3. Filter peer identities and bodies at the client boundary; scan nested entries,
   reconcile fresh entries and use bounded paginated fallback.
4. Extend the existing inventory/audit/planning flows without storing threads or
   creating duplicate obligations.
5. Execute synthetic DP acceptance, MCP transport and regression tests; preserve
   the independent external release gates.

## Endpoint-permission matrix

All paths below are under `/api/v1`. Every request reuses connection ownership,
verified identity, selected accessible course, authorization lease, capability,
signed external approval, and final-response checks. A credential is not approval.
No scope is automatically added to institution configuration or credentials.

| GET path | Use | Required endpoint scope / additional boundary |
|---|---|---|
| `/courses/:course_id/discussion_topics` | Metadata discovery | Existing discussion list scope; no thread download |
| `/courses/:course_id/discussion_topics/:topic_id` | Prompt/ownership/visibility | Exact topic scope; requested ID and returned course/context/URL must agree |
| `/courses/:course_id/discussion_topics/:topic_id/view` | Full thread | Exact view scope; `include_new_entries=1`; visibility and post-before-view checks |
| `/courses/:course_id/discussion_topics/:topic_id/entries` | Fallback top-level pages | Exact entries scope; complete pagination required for absence |
| `/courses/:course_id/discussion_topics/:topic_id/entries/:entry_id/replies` | Full reply pages | Exact reply scope; entry ID must come from the authorized topic scan |
| `/courses/:course_id/discussion_topics/:discussion_topic_id/date_details` | Checkpoint date evidence | Exact date-details scope; overrides/pagination make applicability uncertain |
| `/courses/:course_id/assignments/:id` | Existing assignment-effective date path | Existing assignment scope; `include[]=checkpoints`, no submission or grade request |

`entry_list` is unnecessary and remains unallowlisted. Group routes, roster/profile
reads for classmates, masquerading, generic HTTP and all mutation routes remain
unavailable. The authenticated identity comes from the existing validated
connection; no student ID argument or new self-user request is needed.

Pagination reuses the existing origin/path/query validator and resource bounds.
It does not synthesize page numbers. Provider links with new opaque query keys
that the existing validator cannot prove equivalent are rejected; this is an
explicit compatibility limit, never a reason to loosen the authorization fence.

## Privacy, freshness and limits

The client discards the participants collection, peer user IDs, names, profile
metadata and peer message bodies before returning structural records to the
scanner. Only verified self messages enter results. Peer structural entry IDs
are used in memory to follow replies; parent entry IDs are content references,
not person identifiers. Known aliases in self-authored quotations are inspected
with the existing local text policy. Automated redaction is not an anonymity
guarantee; the existing content/privacy and recipient egress reviews still apply.

Thread instructions are untrusted text. HTML scripts/styles/embedded objects are
removed; images and other external resources are never fetched. Attachment
references are accepted only for exact current-course Canvas file paths without
query credentials. Reading them requires the existing authorized file pipeline.
Ambiguous/global/signed attachment URLs are omitted, not fetched.

Defaults: 20 thread page requests (also capped by the shared page ceiling),
2,000 processed entries including duplicates, 10 topics per audit/page enrichment,
one concurrent topic scan, two attempts per thread request, a 12-second topic
budget and 16,000 returned text characters each for prompt/combined contributions.
The entire multi-topic scan also has a 12-second budget. These are configurable
as `BRIDGE_DISCUSSION_MAX_PAGES`, `...MAX_ENTRIES`, `...MAX_TOPICS`,
`...CONCURRENCY`, `...RETRY_ATTEMPTS`, `...BUDGET_SECONDS`, and `...TEXT_LIMIT`
using the existing settings prefix (see `config.py`). Shared response-byte,
request-rate, transport timeout and final MCP size limits still apply.

Coverage counts successful thread pages; metadata/date reads are outside that
count but inside the topic duration budget. Entry delivery truncation is separate
from scan coverage; counts can be complete while returned text is truncated.
429/5xx retry delays use the existing cancellable retry/cooldown infrastructure.
401 invalidates the existing identity lease and can suppress the whole result.
403/404 never trigger a route bypass or imply that the student has not posted.

There is no persistent discussion cache to mix users, scopes or revoked access.
Every call revalidates authority. A fresh call still cannot eliminate upstream
eventual consistency. Unreconciled duplicates, missing authors, stale count/view
disagreements and unknown deletion states prevent a complete absence claim.

## Feature status

Status vocabulary: `planned`, `implemented`, `verified`, `failed`,
`externally_blocked`. “Verified” below means executed **synthetic local tests**,
not live Canvas or deployed-client acceptance.

| Feature | Status | Evidence or limitation |
|---|---|---|
| Three read tools, typed topic/self-entry/participation/coverage | verified | `tests/test_discussions.py`; actual local MCP serialization |
| Separate post/reply counts, nested relationships, deletion, deduplication | verified | DP-01–DP-08 |
| Full view + fresh entries, fallback, full replies, pagination, bounds | verified | DP-09–DP-16, count/conflict/fresh-version regressions |
| Course checks, post-before-view, no roster or mutation routes | verified | DP-17–DP-27 and shared regression tests |
| Signed approval rejection/revocation during retrieval | verified | Missing, pending, expired, revoked and mid-response signed fixtures |
| Distinct dates and unknowns; no grade/rubric assertions | verified | DP-28–DP-31, override/conflict regressions |
| Existing obligations, audits and study plans preserve uncertainty | verified | DP-32–DP-34 and existing activity-planning regressions |
| Sanitized text and reference-only attachments | verified | DP-24/DP-35, privacy and MCP fixtures |
| Combined checkout full regression | failed | Final focused feature checks pass (76); separate concurrent migration/local-preferences contract failures remain. See validation record. |
| Group participation | planned | Fail-closed `group_access_uncertain`; no membership verifier or group route added |
| Peer contextual reading | externally_blocked | `authorized_thread` is rejected before network access; no separately authorized disclosure lane implemented |
| Optional prompt/self-content search indexing | planned | Existing file search remains file-scoped |
| Live Biomedical Ethics validation / installed connector deployment | externally_blocked | No live approvals established or production requests/restart performed |

## API discrepancies and acceptance boundary

The rendered Discussion Topics reference does not currently expose all full-view
details; the official controller documents `include_new_entries`, nested views,
eventual consistency and 503 behavior. The entries API documents the ten-reply
preview. Assignment serialization supports `include[]=checkpoints` and applies
student overrides; the date-details API can instead expose paginated override
sets. This implementation never infers section/group membership from those sets.

Required reply counts stay null when the authorized response lacks an explicit
numeric `reply_to_entry_required_count`. That field is covered by a synthetic
compatibility fixture; its availability on the target Canvas deployment is not
verified. Anonymous topics may be rejected by Canvas's API and remain unknown.
Canvas can log GET access internally; the connector makes no read-state, posting,
subscription, rating or other mutation requests.

Primary sources reviewed October 26, 2026:

- [Discussion Topics API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics)
- [Official discussion API controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_topics_api_controller.rb)
- [Learning Object Dates](https://developerdocs.instructure.com/services/canvas/resources/learning_object_dates)
- [Assignment serialization and effective checkpoint dates](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/assignment.rb)
- [Checkpoint serialization](https://github.com/instructure/canvas-lms/blob/master/lib/checkpoint.rb)
- [Canvas pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)

Executed checks and remaining environment gaps are recorded in
[the validation record](../evidence/sanitized-results/discussion-reading-2026-10-26.md).
