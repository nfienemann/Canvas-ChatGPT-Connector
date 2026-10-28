# Semester intelligence and early warnings

`get_semester_overview` reads the selected courses together on demand. It returns
current obligations, bounded course grade evidence, cited findings, ranked next
actions, coverage counts and uncertainties. It does not install a poller, create
a job, send a notification, write Canvas, or change an existing calendar.

## Evidence and scope

The request can narrow the selected course scope, provide aware start/end bounds
(at most 366 days), a display timezone and user-supplied busy times. Without term
bounds, the report explicitly covers the previous 30 and next 120 days; it does
not invent university semester dates. Dates come from the existing normalized
student-effective assignment observations, including supported overrides.

Each finding has a stable issue key, semantic revision, source evidence, applicable
time when known, consequence where supported, evidence status, next action,
acknowledgment and lifecycle. Report timestamps and snapshot IDs do not create a
new semantic revision. Source content remains untrusted data.

Supported findings include:

- Known upcoming deadlines, verified pending overdue/missing work, and unknown
  timing or completion. Unknown submission status never proves missing work.
- Newly observed assessments and consequential deadline, availability or requirement
  revisions. Ordinary title/status edits are not automatically warnings.
- Deadline clusters within 72 hours; a major cluster needs two verified structural
  assessment weights of at least 10%. Closeness alone is not an attendance conflict.
- Explicit saved study blocks overlapping supplied busy times or ending after a
  known deadline, and source revisions affecting saved plans.
- Conditional workload shortfalls from current student/instructor estimates,
  explicit available windows minus busy times, and the user's daily workload cap.
  Assistant estimates never become verified workload. Local-day boundaries account
  for daylight-saving transitions.
- HTML syllabus/assignment deadline differences and recognizable category-weight
  discrepancies, with applicability left for review. Grade position uses the existing
  deterministic grade engine and evidence graph; it never estimates passing probability.
- Visible module prerequisite references whose targets are not visible or locked.
  This is an access uncertainty, not proof of a deleted file or unfinished work.
  Restricted module titles/content are not included or fetched.

Course evidence is bounded to 15 seconds per course and 60 seconds total, after the
existing bounded assignment refresh. HTML syllabi and visible grade/module inputs
are checked; linked documents, announcements, every material prerequisite, and
external calendars are not exhaustively inspected. Partial reads are explicit.
The response returns at most 60 findings and 100 compact obligations, additionally
bounded by byte size; total/returned counts expose truncation. No finding means
only that the available evidence did not establish one.

Structural weights require complete supported points/weighted policy evidence,
known denominators and eligibility, and no drop rules. Unknown or unsupported
rules, extra-credit denominators and missing weights remain unknown. A structural
share is not the grade consequence of missing an assignment.

## Priority and lifecycle

Priorities are reproducible heuristics: current reliable timing (24/72-hour tiers),
then the user's course priority (0 highest, 10 lowest), then verified structural
weight, then stable issue ID. Unknown timing or stale/suspected evidence goes to
clarification. Known plan conflicts, dependency checks and supported workload
shortfalls remain explicit planning factors. No rank guarantees an academic outcome.
Freshness describes the observation time; a recent read does not prove that a syllabus
was recently revised or that its policy applies to a particular assessment.

Complete, same-scope, time-ordered snapshots establish confirmed observations.
Incomplete history can support a suspected change between common records, never
a newly created assessment or resolution. Missing baseline means incomplete history.
Resolution requires comparable, still-accessible source objects and known current
timing/completion; absent records, unknown dates and dates outside the report are
not proof of resolution. Supplemental syllabus/module findings have current evidence
only; they do not claim historical resolution without stored comparable sources.

`acknowledge_semester_findings` saves only an explicit user selection, using a
15-minute owner/connection/scope-bound report receipt and optimistic state version.
It also supports explicit unacknowledgment. A changed semantic finding is visible
again. The transaction checks connection epoch to reject a concurrent scope change.
Acknowledgment is separate from assignment completion and notification authorization.

## Preferences and notifications

Use `update_local_study_preferences` only when asked to remember preferences. Its
optional `semester` object supports course priorities, preferred local study periods,
aware available windows, daily workload tolerance and notification preferences.
Preferences are stored separately from educational records in existing encrypted,
user-owned preference storage. Legacy connection preferences are a fallback only
when no independent preferences were saved. Preferred periods guide next actions;
they are not proof of availability. Unknown fields, including inferred health or
protected characteristics, are rejected.

On-demand analysis is the default. Explicit notification preference requires
course scope, daily/weekly frequency and distinct local quiet hours. Saving that
preference does **not** create a schedule. The native overview always reports
`approved_host_schedule_required` after opt-in because this implementation has no
connected delivery/scheduling adapter.

`semester_notifications.py` supplies a pure, tested adapter contract for a future
approved host. Eligibility requires opt-in, server-owned host approval, fresh
authorized analysis, scoped courses, quiet-hour/frequency checks and unacknowledged
actionable semantic revisions. Repeated unchanged findings are suppressed after a
confirmed provider receipt. Preparation is not delivery; ambiguous sends must be
reconciled with the stable delivery key before retry. No MCP argument can assert
host approval, fabricate delivery or start a worker. The adapter must recheck
authorization on every run and persist its receipt only after confirmed delivery.

Existing 30-day retention applies to preference/state records. Scope withdrawal
clears semester acknowledgment/delivery state. A future host must stop on expired
opt-in or missing delivery history and obtain a fresh explicit schedule decision;
it must not treat an expired ledger as permission to repeat old alerts. No active
notification capability or deployed host acceptance is claimed here.

## Reproducible verification

Run `python -m pytest tests/test_semester_intelligence.py -q`. Its fictional scenarios
cover 12 simultaneous courses, unknown/dropped grade weights, revisions, repeats,
resolved conflicts, incomplete history, timezone transitions, user preferences,
acknowledgment races, revocation, notification deduplication and actual MCP transport.
No real academic records, model judge, or external service is required. Full CI
includes these tests; the periodic/release benchmark workflow also runs them.
The existing academic benchmark compares objective grade/privacy behavior without
compensating for a regression with an improvement elsewhere.
