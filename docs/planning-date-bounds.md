# Source dates and study-plan boundaries

This correction applies to `propose_study_plan`, the validation used by
`save_study_plan`, and optional study blocks in `propose_calendar_sync`. The
connector remains a native ChatGPT tool; no calendar write, new login, model,
Canvas route or database migration is introduced.

## Confirmed bugs

The previous allocator only used timestamp deadlines, despite accepting
`FactDate.local_date`. A synthetic date-only obligation was scheduled two days
after its reported date. The previous window arithmetic also used local wall
clock subtraction: on the New York spring DST transition, a 01:30–03:30 window
allocated 120 minutes although only 60 elapsed minutes existed. These failures
were reproduced against the committed baseline before the fix.

Opening timestamps were also omitted from the allocator's earliest-start bound,
and pinned blocks skipped closing constraints already in the past. New timing
rules use the same bounds for automatic blocks and pins. Existing completed,
excused and currently locked/inaccessible filters remain in place.

## Input and interpretation

`PlanRequest.date_only_timezones` is an optional map from an authorized workload
ID to its applicable IANA timezone. It is needed only when that item's due,
opening or closing field is a date without a time. A display timezone or Calendar
account timezone does not establish the course's timezone. Values supplied by
the conversation are labeled as such, never promoted to verified Canvas facts.
Foreign workload IDs and invalid timezone names are rejected.

With a known timezone, the engine conservatively finishes before a date-only
due/closing day starts, and waits until after a date-only opening day ends. These
are explicit planning assumptions. The original date, precision, raw text and
source reference remain unchanged; no midnight or 11:59 PM deadline is invented.
A passed conservative due bound requires clarification instead of automatically
scheduling late work. Unknown timezones and nonexistent local date boundaries
prevent allocation. Repeated midnight uses the earliest start of that date.

Timestamp-based overdue recovery remains conditional and respects a known close;
it is labeled recovery and cannot claim a verified feasible plan. Missing due
dates retain the existing unknown/historical-relevance behavior.

## Outputs and time arithmetic

Recommendations include their timing evidence. `timing_constraints` retains each
work item's source due/open/close values, source ID, calculated `planning_not_before`
and `planning_finish_by` instants, assumption text, timezone basis and blocked
reason. The calculation never overwrites a source date.

If timing alone prevents the requested allocation, `feasibility` is
`timing_unresolved`. Unknown timing does not add invented minutes to
`known_shortfall_minutes`. Capacity shortages are calculated against the stated
bounds; `shortfall_basis` makes the distinction explicit. A fitting plan using
conservative date assumptions remains provisional.

Availability, busy intervals, pins and block arithmetic use UTC instants and
elapsed minutes. Offset-aware output can be rendered in the student's preferred
zone by ChatGPT. Nonexistent local times are rejected; explicit DST fold choices
retain their distinct instants. Overlap, horizon, busy-time, break and buffer
checks therefore use actual elapsed capacity.

Python's primary references describe the relevant [datetime arithmetic](https://docs.python.org/3/library/datetime.html)
and [IANA timezone/fold behavior](https://docs.python.org/3/library/zoneinfo.html).

## Verification and limits

`tests/test_planning_dates.py` includes source-preservation/reproducibility,
unknown timezone, date-only due/open/close, contradictory bounds, pins, skipped
dates, repeated midnight, both DST transitions, elapsed busy-time capacity,
owner/scope/stale/partial snapshots, Calendar composition, and actual HTTP MCP
contract tests using fictional Canvas responses. See the verification ledger for
actual run totals. The complete Windows run passed 365 tests (12 Linux-only
skips). [Linux CI](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39516486216)
passed 373 tests (four Windows-only skips) against source commit `96af218`.
The installed private connector also
returned the new timing evidence from a fresh read of all four selected courses,
kept availability unknown and allocated no blocks. The live window contained no
date-only deadlines; that acceptance case remains synthetic. The ChatGPT tool
catalog was refreshed and the new description visibly verified. No real grades
are needed for automated tests.

Authorization and selected-course checks are unchanged. Request timing inputs
are ephemeral unless the student explicitly saves a plan through the existing
version-checked local write. This does not add quiz/discussion planning, infer
course timezone, repair an instructor's dates or synchronize Calendar events.
