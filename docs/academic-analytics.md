# Academic operations analytics

A student can review one or two closed periods for selected courses. The report separates provider-observed timeliness, the student's own progress, saved schedule conflicts, effort measurements and coordination activity. Each family has its own coverage, sources, counts and reasons for missing measurements.

## Request a review

Call `get_academic_analytics` with the current connection ID and a request such as the following. The course ID in this example stands for an already selected course. The two windows cover local Monday through Sunday in New York. The second week has 169 elapsed hours because daylight saving time ends.

```json
{
  "connection_id": "connection-one",
  "request": {
    "course_ids": ["selected-course"],
    "timezone": "America/New_York",
    "windows": [
      {"start": "2026-10-19T00:00:00-04:00", "end": "2026-10-26T00:00:00-04:00"},
      {"start": "2026-10-26T00:00:00-04:00", "end": "2026-11-02T00:00:00-05:00"}
    ],
    "as_of": "2026-11-02T00:00:00-05:00",
    "evidence_cutoff": "2026-11-02T00:00:00-05:00"
  }
}
```

The start is inclusive and the end exclusive. Each window may span up to 31 elapsed days. Two windows must be ordered and disjoint. Give the time zone as an IANA name and provide offsets on all timestamps. The end of the last window must be at or before `as_of`, which must be at or before `evidence_cutoff`. Future cutoffs are rejected. Omit `families` to request all five, or pass any subset of the identifiers below.

`as_of` selects the state being described. `evidence_cutoff` selects which observations may support it. A version learned later can establish an earlier state when it carries evidence of that effective time. A capture timestamp alone only supports state from the observation onward.

## Sources and historical coverage

| Family | Source and calculation | What can be recovered |
| --- | --- | --- |
| `deadline_outcomes` | Scoped workload snapshot parents, applicable due versions and normalized own-submission evidence. Counts on-time, late, missed and unknown outcomes. The missed rate divides missed by known outcomes. | Uses underlying inventory, including parents omitted from the overview. A date lacking enough precision for a partial-day boundary is unplaceable. Missing pages limit the cohort. Pooled rates add counts before division. |
| `personal_completion` | The same due parents, each student's saved progress declarations and separate revision flags. Offline work can be marked done. | Shows progress on the due cohort at the state cutoff. A save without an event timestamp cannot establish when the student finished. An absent declaration is unknown. |
| `schedule_conflicts` | Frozen accepted or proposed study blocks intersected with the union of retained busy intervals. Uses measured overlap, affected blocks, internal clashes and capacity shortfalls. Semester finding samples track acknowledgment and recorded resolution separately. | Window fields `accepted_snapshot` and `proposed_snapshot` can pin the intended saves. Partial busy coverage yields observed overlap only. Full finding counts require a retained sample with matching scope and window. |
| `effort_calibration` | A pre-work forecast and an explicit completed duration for the same parent, work revision, unit and scope. Range coverage includes both endpoints. Budget error uses the recorded planning budget. Point error requires an explicit point estimate. | A saved plan freezes the range, its assumptions and source. A remaining-work forecast can use a measured phase or a cumulative duration with a timed baseline. Preserves recorded zero and lists incomplete or unmatched work. |
| `coordination` | Scoped workflow requests, governor attempts, distinct confirmed delivery effects, recorded manual sessions and separate system elapsed time. A retried request can generate several attempts. | Known effects require authoritative scoped receipts. Legacy receipts without a course binding cannot establish a scoped effect. A calendar proposal supplies no confirmed calendar-write receipt. Manual minutes come from explicit session measurements. Empty history needs collection coverage to establish zero. |

For an owned independent dataset, call `run_independent_academic_workflow` with `capability: "analytics"`, the existing dataset selection, and the same review under `analytics`. Select the dataset's own document ID as the sole course ID. Canonical parents, aliases, child steps and explicitly dated declarations come from the reviewed dataset version. Its timeliness and progress retain student-declared provenance. Unsupported families report missing observations. This route supports on-demand review.

## Save, correct and replay

- `save_study_plan` freezes measurement references alongside the normal local save. Its optional `plan_state` is `accepted` by default. Pass `proposed` to keep a candidate separate. Supply the optional `review_calendar` to establish the reviewed busy window and its coverage. If measurement capture fails, the primary save can still succeed and reports a coverage limitation.
- `record_academic_measurement` accepts one owned actual duration or manual session. For a manual session, pass a stable `measurement_id`, `course_id` and `manual` object with `occurred_at` and the recorded `minutes`. For a work actual, use the matching `work_id`, saved forecast reference, work revision, unit, scope, start and completion information. Use `expected_version: 0` when creating a measurement and the current version for a correction. Replaying the same input is idempotent.
- `save_academic_analytics` takes the same arguments as a fresh review. Use `get_academic_analytics` with `connection_id` and `saved_report_id` to retrieve the saved result. To restate one, send the original request with `restates` set to the saved report ID and a later evidence cutoff. The report identifies changed cohorts and measurements and links to its predecessor.
- Source access is checked using the authenticated owner, current selected courses and underlying parent bindings, including on saved reads and restatements. Scope revocation drops derived local history. The existing local-state expiry is 30 days from observation or explicit save. Legacy records can contribute their retained current version. Overwritten versions predating measurement capture cannot be reconstructed.

## Read the report

Each period exposes counts and source coverage by family. Measures carry units, numerator, denominator and sample count. An undefined rate returns a null value. A comparison reports rate differences in percentage points, duration differences in the original units and the samples on both sides. Inspection is bounded to 64 snapshots, 5,000 parents and 2,000 local records. Coverage flags identify retrieval limits, and detailed references can be abbreviated for transport independently of the calculated counts. Treat results as descriptions of the selected evidence. Report and system runtimes measure machine activity.

The [verification record](../evidence/sanitized-results/stage6-academic-analytics.md) links the reproducible synthetic cases and the evaluated host answers.
