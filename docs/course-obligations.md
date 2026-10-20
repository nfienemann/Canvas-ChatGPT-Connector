# Course obligation inventory

`get_course_obligations` extends discovery beyond the assignment-only workload.
It remains a native, read-only MCP tool. No separate interface, model, subscription,
Canvas mutation, Calendar write or additional student login is introduced.

## Scope and behavior

Supply a selected course, aware start/end timestamps (at most 31 days), and an IANA
timezone. The tool retrieves assignments, classic quiz metadata, discussion topic
instructions, and two course-scoped Canvas calendar collections (events and
assignment representations). The calendar window does not filter the assignment,
quiz or discussion inventories: these include historical and undated records.

Explicit assignment `quiz_id`, `discussion_topic.id`, topic/quiz `assignment_id`
when returned, and calendar `assignment_<id>` identities associate sources.
Matching titles alone never merge records. Ambiguous links remain separate.
An assignment's canonical identity matches the existing workload identity; call
`get_workload` for its snapshot/detail workflow, or use the inventory version with
[`propose_course_study_plan`](activity-study-planning.md) for selected activities. This inventory does
not persist new Work rows, synthesize snapshots or automatically schedule newly
discovered activities. Ungraded activities are candidates, with required status
and completion unknown until additional evidence supports them.

The assignment-effective due field is preserved even when null. Other dates are
attributed to their source, and differences are unresolved evidence. Calendar
event starts are not assignment due dates. Date-only all-day events retain their
precision; timestamp values retain the original offset in `raw`. A missing date
never implies upcoming work. Submission semantics reuse `normalize_assignment`.

Descriptions are independently labeled present, empty, not returned, invalid,
nonextractable or truncated. A quiz description can therefore supply instructions
without misrepresenting an empty assignment description. Quiz duration is a time
limit, not an estimated study effort. Questions, attempts and restricted answers
are never requested. Discussion initial-post and reply instructions remain text;
the engine does not invent separate deadlines or infer participation completion.

## Evidence, pagination and bounds

Each alias has a stable owner/connection/course/resource identity, generated Canvas
reference URL, retrieval timestamp, optional source update timestamp, content hash,
extraction state and shared coverage evidence. Provider URLs are not trusted.
Five collection requests run concurrently within the configured refresh budget
(12 seconds by default, maximum 15), after existing course authorization and
credential refresh. This is not a measured end-to-end latency guarantee.

At most 100 source rows per collection are processed; upstream pagination uses the
existing adapter budget. Responses contain at most 20 obligations, six aliases
per obligation, 4,000 characters per description and 24,000 total description
characters. Serialized results are reduced to 220 KB before the shared 250 KB
guard. Restrictions, malformed identities, conflicting duplicate rows, processing
caps and missing pages remain explicit coverage limitations.

Follow `next_offset` with the same filters and `expected_version`. Reads are fresh;
a changed content/coverage/window fingerprint requires restarting at offset zero.
This avoids silently skipping shifted records without retaining a new private
document cache. `obligation_id` focuses one authorized result. Partial content is
not presented as an empty or complete course inventory.

## Security and retention

- Existing JWT, connection ownership, active student enrollment and explicit
  course selection apply before reads; selection epoch is checked again afterward.
- Only the three new reviewed GET routes are enabled. Calendar queries fix the
  selected course context and exclude nested assignments and child reservations.
  Pagination cannot change route, context, dates or query type.
- Allowlisted projection omits quiz access codes, answer/attempt/preview fields,
  overrides, participant identities, peer posts, feed URLs and embedded submissions.
  Appointment groups/reservations and unrelated calendar contexts are omitted.
- Locked, unpublished, unverified-visible quiz/topic content and topics lacking a
  posting timestamp are withheld. Denied assignment access or expired credentials
  abort the result; narrower denied resources are reported independently.
- No new database tables, caches, credentials or logs of academic contents. Existing
  access/credential lifecycle metadata may refresh normally. Request data is
  transient; independent copies in ChatGPT remain controlled by ChatGPT.

## Verified scope and remaining limits

The synthetic acceptance fixture resolves one assignment, classic quiz and
calendar assignment to one obligation, reads visible quiz instructions despite an
empty assignment description, and preserves conflicting dates without guessing.
Regression tests cover permissions, isolation, stale authorization refresh,
continuation changes, pagination confinement, same-title duplicates, calendar
scope/precision, malformed and restricted records, bounded output and actual HTTP
MCP transport. See `tests/test_obligations.py` and the verification ledger for runs.

An authorized private Rowan integration read on 2026-10-20 returned 11 assignments,
completed both calendar queries, received a permission denial for classic quizzes,
and withheld one discussion whose posting date was unavailable. No readable quiz
description was established in that course. This is a verified graceful limitation,
not a claim that the student's Quiz 3 requirements were successfully read.

Planner items, undated calendar events, New Quizzes/external instructions,
group-child discussions, automatic participation sub-deadlines, persistent alias
history and new-activity saved progress/Calendar integration are remaining dependencies. The complete R03/R21
course-breadth requirements remain partial. Institution developer-key scopes must
be approved independently; there is no new OAuth flow or change to token handling.

Reviewed primary references: [classic quizzes](https://developerdocs.instructure.com/services/canvas/resources/quizzes),
[discussion topics](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics),
[Canvas calendar events](https://developerdocs.instructure.com/services/canvas/resources/calendar_events).
