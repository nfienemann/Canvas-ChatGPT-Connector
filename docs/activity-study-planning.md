# Study planning from course activities

`propose_course_study_plan` adds a read-only planning path for explicitly selected
assignments, classic quizzes, visible discussion topics and preparation for dated
course calendar events. The existing snapshot-based `propose_study_plan` remains
compatible. This is part of the native ChatGPT connector, with no extra model,
subscription, dashboard, credentials or Canvas writes.

## Workflow and evidence

1. Read `get_course_obligations` for each selected course, using a common calendar
   window (at most 31 days) and IANA display timezone. Follow its hash-bound
   continuation when necessary.
2. Pass each course ID and `inventory_version`, the identical window/timezone,
   and the canonical obligation IDs to `propose_course_study_plan`. Source alias
   IDs and guessed titles cannot select work. Up to ten courses and 50 activities
   share one set of availability windows and busy times.
3. For each activity, distinguish a student's actual request from a
   `suggested_review`. Suggestions produce review entries and no allocated blocks.
   This field records provenance; it is not an authorization mechanism. ChatGPT
   must not manufacture student choices or effort estimates.
4. Use `remaining_work` for assignments, quizzes and discussion participation;
   use `event_preparation` for a dated calendar event. Event starts bound
   preparation but never populate `source_due`, imply mandatory attendance or
   reserve the event itself. Add known commitments separately as busy times.
5. Supply effort and availability only when known. Quiz duration and assignment
   points never become effort. Date-only fields require their applicable
   `date_only_timezones` entry; display timezone alone is insufficient. All-day
   event preparation conservatively finishes before that local day begins, with
   that assumption labeled. A past event cannot become overdue preparation.

The service refreshes course access and all five inventory collections, checks
content/coverage versions, projects only allowlisted facts into the existing
deterministic planning engine, and checks the selection epoch again before
returning. Linked assignment/quiz/calendar aliases share one work ID. Conflicting
dates or unresolved links produce cited review entries, not silent source
precedence. Response sources include retrieval time, content hashes, source
modification time when returned, and per-resource pagination coverage.

The shared engine retains urgency, student priority and importance, effort upper
bounds, prerequisite handling, buffers, breaks, pinned blocks, busy-time exclusion
and elapsed-time DST calculations. Existing assignment progress records can be
read under the same owner/connection/key scope. Nothing is saved by this tool.
Completed, excused, submitted-without-revision and currently closed/locked work
is excluded according to the existing normalized evidence. Unknown participation
or submission never becomes `not_submitted`. A fitting plan remains provisional
because it only covers selected activities, not every academic obligation.

## Bounds and failure behavior

The inventory's collection/page/100-row processing bounds still apply. All course
refreshes share the configured outer refresh timeout, with cancellation on timeout.
A changed version requires another inventory read. Unauthorized courses, foreign
IDs, expired credentials and changed selection fail closed. Unavailable narrower
collections remain explicit; known selected work may still receive a partial plan.
Response size is checked after evidence attachment against a 200 KB limit; an
oversized plan is refused with a request to narrow the scope, never silently
truncated. No raw provider URLs, quiz answers, attempts, peer replies, roster data,
tokens or signed URLs are added to planning output.

## Acceptance and remaining dependencies

`tests/test_activity_planning.py` exercises a mixed-activity acceptance case with
shared nonoverlapping capacity, linked-source deduplication, deterministic repeated
results, optional activity review, unavailable effort, precise conflict evidence,
completed work exclusion, own progress, same titles across courses, later inventory
pages, foreign IDs, scope changes, authorization failure, partial coverage,
timeouts, response bounds, all-day/DST preparation and actual HTTP MCP transport.

This tool does not save plans/progress for new activity types or synchronize them
to Google Calendar. The existing Calendar proposal tool still uses assignment
snapshots. New Quizzes, Canvas Planner items, group-child discussions, automatic
initial-post/reply sub-deadlines and complete meeting timetables remain unsupported.
Visibility alone establishes neither required participation nor remaining work.
Institution-specific endpoint denials remain limitations, not empty-course claims.
No schema migration, new OAuth flow or new Canvas API endpoint is required.

See the [verification ledger](../evidence/sanitized-results/verification.md) for
executed tests and private integration proof; synthetic success is not proof that
every institution exposes standalone activities through the same routes.

The deployed private ChatGPT integration was verified on 2026-10-20: the new tool
returned a review entry and no blocks for an unconfirmed assignment suggestion,
while retaining Rowan's denied quiz access and incomplete discussion coverage.
Mixed standalone activity allocation is covered by synthetic acceptance tests;
no such live resource was established by that private check.
