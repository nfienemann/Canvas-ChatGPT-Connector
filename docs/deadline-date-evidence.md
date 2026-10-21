# Deadline date and time evidence

The existing `reconcile_course_deadlines`, `review_assignment_requirements` and
`audit_course_consistency` workflows share deterministic date extraction and
comparison. `academic_dates.py` normalizes source dates; `academic_rules.py`
retains the assessment match, passage and finding. Authentication, selected-course
retrieval, file parsing and source-version checks remain in their existing paths.

## Supported source statements

The grammar recognizes ISO dates and English full or abbreviated month names,
including day-first forms and ordinal days. Examples include `Nov. 12, 2026`,
`12th November 2026`, and `2026-11-12`. A directly attached 12-hour or 24-hour
clock time may include seconds and an explicit UTC offset, UTC/GMT/Z, or an IANA
timezone such as `America/New_York`. Only the recognized passage is normalized;
there is no model, paid service or external date parser.

Returned obligations retain `raw_date`, `date`, `precision`, `timezone`,
`local_datetime`, `normalization_status`, `uncertainty` and an exact `date_offset`.
`precision` is `date`, `timestamp`, or `local_datetime` when a stated clock time
cannot be resolved to an instant. The source citation retains document version,
course, locator, passage and retrieval time. Source `date` remains null when
normalization would require unsupported assumptions; a local wall time can still
be shown separately.

No year is copied from the current date, document title or course term. Numeric
month/day strings such as `11/12/2026` remain unresolved without an explicit date
order. Timezone abbreviations such as EST are not assigned an IANA zone or fixed
offset. A stated clock time without a zone does not inherit the course or student
zone. Invalid dates, invalid offsets, unknown `-00:00`, and ambiguous/nonexistent
IANA wall times at daylight-saving changes remain unresolved. Date-only statements
remain dates and never become 11:59 PM deadlines.

## Comparison and findings

Unique exact assessment-title matches still identify comparison candidates.
Similar titles, duplicate titles, date ranges and prose relationships need review;
this increment does not infer source precedence, amendment applicability or a
relationship across lines/table cells.

Two explicit timestamps are compared as instants. If either side is date-only,
any timestamp is converted to the verified course timezone before comparing
calendar dates. A missing or invalid course timezone prevents that comparison.
Matching dates return `same_at_available_precision` and
`time_agreement_established=false`; they do not prove agreement on a deadline's
clock time. The additive `comparisons` array records the comparison basis and zone.

An unresolved source date now produces `source_date_unresolved` for an otherwise
matched, dated assignment. A missing course zone produces `timezone_unresolved`.
Actual differences retain `conflicting_deadlines` with both source evidence and
comparison basis. Null Canvas due fields retain `missing_canvas_deadline`, even
when the source date needs clarification: field absence is separate from policy
applicability and never establishes an upcoming or unscheduled assessment.

Obligation IDs now bind course, resource, document version, locator, exact date
offset and original date text. Refreshing an unchanged passage keeps its ID;
changing the version or scope changes it. Retrieval timestamps remain evidence
without causing artificial identity changes. These are candidate IDs, not a
saved mapping, historical comparison baseline or notification subscription.

## Verification and security

`tests/test_academic_dates.py` contains 31 regression cases for supported grammar,
source precision, invalid/unknown inputs, DST, midnight conversion in both
directions, deterministic IDs and offsets, authenticated HTML/PDF/DOCX retrieval,
pagination, denied/partial sources, changed versions, course/user isolation and
the actual HTTP MCP contract. Existing academic and parsing suites remain in
force. Executed platform checks are recorded in the
[verification ledger](../evidence/sanitized-results/verification.md).

There are no new tools, OAuth scopes, network routes, stored student records,
calendar actions or Canvas writes. Source content remains untrusted. No live
course date needs to be changed to test this increment. Broader multilingual and
relative-date grammars, cross-cell schedule interpretation and student-reviewed
ambiguous matches remain development dependencies.
