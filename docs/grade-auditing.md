# Grade auditing in the native connector

Canvas reports a grade. Canvas Bridge evaluates its consistency with available
evidence. This increment adds four read-only MCP tools to the existing service;
there is no new application, account, subscription, dashboard or database table.

## Architecture and files

- `grade_audit.py` acquires freshly authorized course configuration, assignment
  groups, own enrollment grades and own posted assignment scores. It compares each
  assignment-list record with its detail response before using it. It reuses the
  material reader for syllabus PDFs, text, Markdown and HTML pages.
- `grading_policy.py` extracts conservative, deterministic rule candidates and
  binds student review to exact source and configuration versions.
- `grading_engine.py` contains typed policies, evidence and scenario inputs,
  pure Decimal calculations, stable calculation hashes and neutral reconciliation.
- `app.py`, `canvas.py`, `policy.py` and `synthetic.py` register tools, fixed GET
  routes/query parameters and faithful synthetic provider responses.
- `tests/test_grade_audit.py` covers the requested grading edge cases and native
  MCP calls; `test_personal.py` checks the expanded read-only catalog. Existing
  `grades.py` simple-points helper and `get_gradebook` remain backward compatible.

## Tools and result layers

| Tool | Purpose |
|---|---|
| `get_course_grading_policy` | Canvas configuration and score evidence; discovered or explicitly selected syllabus sources; rule candidates, passages and limitations |
| `calculate_course_grade` | `current_graded`, `syllabus_current`, `projected_final` or `required_score`; defaults to Canvas current arithmetic without needing a syllabus |
| `audit_course_grade` | Side-by-side reported, reproduced and syllabus-derived values, differences, explanations and missing evidence |
| `simulate_grade_scenario` | Pure calculations using explicit hypothetical scores or a target; never calls Canvas's write-based What-If API |

All retain `Result` schema 1.0. Layer A is `canvas.reported` and is never replaced
by a calculated value. Own visible override fields remain separate. Available
period information, grade visibility, field presence, missing/late/excused flags
and list/detail conflicts are explicit. Enrollment APIs do not provide a reliable
possible-points total; that value is unavailable, not reverse-engineered from a
rounded percentage.

Layer B contains source-backed syllabus candidates and a conditional calculation.
Layer C classifies `consistent`, `explainable_difference`, `potential_discrepancy`
or `insufficient_evidence`. `confirmed_configuration_mismatch` is deliberately
reserved: this release has no independent instructor-policy verification channel,
so neither a student's confirmation nor a numerical gap can produce that label.
Consistency within 0.01 percentage point is a display-tolerance comparison, not
proof that a particular rounding policy was used.

## Policy schema and interpretation

The returned syllabus policy uses `schema_version: "1.0"`:

```json
{
  "policy_version": "SHA256 of documents, rules and Canvas category configuration",
  "documents": [{"id": "opaque material reference", "title": "Syllabus", "url": "stable Canvas URL", "version": "content hash", "complete": true}],
  "rules": [{
    "id": "stable rule hash",
    "rule_type": "category_weight",
    "value": {"category": "Exams", "weight": "60", "group_id": "opaque group reference"},
    "source_document": "opaque material reference",
    "source_url": "stable Canvas URL",
    "source_location": {"locator": "PDF/text page 2", "offset": 0},
    "document_version": "content hash",
    "source_passage": "Exams: 60%",
    "passage_truncated": false,
    "interpretation_status": "deterministic_candidate",
    "student_confirmation_needed": true,
    "supported": true
  }],
  "interpretation": "unverified_candidates",
  "missing_information": ["Student review is required"],
  "coverage": {"announcements": "not_retrieved", "version_precedence": "not_assumed", "instructor_verification": "not_available"}
}
```

Supported candidate grammar is intentionally narrow: category-name/percentage
lines that map uniquely to Canvas categories, an explicit earned/possible points
statement, and simple category drop-lowest count statements. Rules also identify
extra credit, attendance/participation, late penalties, curves/adjustments,
replacement exams, thresholds, other drop rules and special conditions as
unsupported/ambiguous when their semantics cannot safely be applied. Such passages
block a precise syllabus estimate. Individual assessment weights and category
remapping are not inferred. Exact-name mapping failures remain visible.

A `PolicyReview` input contains `policy_version`, `confirmed_rule_ids`,
`complete_policy_confirmed`, `applicability_confirmed` and an explicit
`empty_categories` choice (`refuse` by default; `renormalize` only when justified).
ChatGPT must obtain the student's actual review; a request to calculate a grade
does not supply it. Every supported candidate must be reviewed. Changed documents
or category configuration invalidate the review. Confirmation records an explicit
student assumption, not an institution-verified fact. Unsupported or conflicting
rules cannot be bypassed through confirmation. The engine never assumes that the
newest document supersedes another. Announcements are not automatically retrieved;
unresolved amendments prevent a defensible completeness confirmation.

## Deterministic methodology

Scores use Python Decimal arithmetic; displayed results round half-up to four
decimal places. All exact inputs, policy, mode, assumptions and engine version
are returned in the calculation basis and hashed for reproducibility. No LLM
performs arithmetic. Posted scores are used as returned; deductions are not
applied again. A zero is a grade only when actually posted or explicitly supplied
as a hypothetical score.

- Points mode: `100 * sum(eligible earned points) / sum(eligible possible points)`.
- Weighted mode: points aggregation within each category, then percentage times
  category weight. Supported configured weights must total 100%. Canvas current
  arithmetic explicitly normalizes over categories with usable denominators.
  Syllabus current estimates refuse empty categories unless the reviewed policy
  explicitly allows normalization. The active weight is returned.
- Excused/omitted/not-graded work is excluded. Unsubmitted, missing and submitted
  but ungraded work stays ungraded, never zero. Unknown score availability,
  eligibility or inconsistent list/detail evidence blocks precision.
- Equal-point drop-lowest rules sort by score and then opaque ID for deterministic
  ties, preserve never-drop entries and leave at least one eligible non-protected
  score. Unequal-point optimization and drop-highest rules are refused. Canvas's
  actual drop semantics optimize group impact; sorting percentages in the general
  case would be incorrect. [Canvas rule documentation](https://community.instructure.com/en/kb/articles/660670-how-do-i-create-rules-for-an-assignment-group).
- Zero-possible-point extra credit adds to a points numerator or an otherwise
  usable weighted-category numerator. A positive-weight category consisting only
  of extra credit has no denominator and is indeterminate.
- Projection requires explicit hypothetical scores for all visible unfinished
  work. It cannot overwrite posted/excused scores or introduce other assessment
  IDs. Required-score analysis solves the affine function between uniform 0% and
  100% outcomes on remaining work, returning the uniform percentage needed and
  conditional/already-met/infeasible status. Nonlinear drop policies are refused.
  These solver endpoints are scenarios, never assumed student scores.

Final modes require `acknowledge_visible_scope`. Even then, results are conditional
on the returned visible inventory: unseen/unpublished future work can invalidate
them. They are never official final grades. A visible restricted assessment blocks
a final scenario. An unavailable instructor adjustment or grading-period policy
cannot be reverse-engineered from the reported total.

## Security, retention and resource limits

The existing verified principal, personal subject boundary, selected course,
institution allowlist and token refresh are reused. Academic operations are GET
only. There is no roster, student ID, URL, credential, SQL or execution argument.
Posted score use requires the current student's identity, matching assignment,
and a valid posting timestamp. Unposted fields and foreign-user scores are
discarded. Hidden course totals are not reconstructed. Final scope/epoch checks
prevent returning an audit after deselection or disconnect. No new grade tables,
audit histories, raw-record logs or notification jobs are created.

Syllabus files reuse existing HTTPS/redirect restrictions and isolated parsing.
Sources use stable Canvas links, never signed download URLs. Existing extracted
file caching expires within 24 hours and is purged on withdrawal/disconnect; no
separate grading cache is created. Returned results can remain in the student's
ChatGPT conversation under its own retention controls.

Limits: 60 groups, 60 assessment detail comparisons, three explicit/discovered
syllabus materials plus the course HTML, 100 candidate rules, 1,000 characters per
parsed rule line, 90 seconds total acquisition, existing parser and 250 KB MCP
response limits. Exceeding a limit produces partial/indeterminate evidence.

## OAuth and deployment

No WorkOS scope or ChatGPT identity change is required: all four tools use
`academic:read`. Refresh the installed connector's tool catalog after restarting
the existing server. No database migration or installer is needed for this
server-side increment.

For scoped Canvas developer keys, enable the read routes
`url:GET|/api/v1/courses/:id` and
`url:GET|/api/v1/courses/:course_id/assignment_groups` in addition to the existing
own enrollment, assignment and material routes. Course GET includes syllabus,
total-score and grading-period fields; own enrollment GET requests current points.
No write scopes or instructor-only syllabus-history APIs are requested. A denied
scope becomes an explicit limitation. See the updated scope inventory and
[Canvas assignment groups](https://developerdocs.instructure.com/services/canvas/resources/assignment_groups),
[courses](https://developerdocs.instructure.com/services/canvas/resources/courses),
[enrollments](https://developerdocs.instructure.com/services/canvas/resources/enrollments)
and [submission visibility](https://developerdocs.instructure.com/services/canvas/resources/submissions).

## Verification and remaining priorities

The regression suite covers all 17 requested edge cases, authenticated PDF
syllabus extraction/page provenance, explicit refusal without policy evidence,
cross-user/course access, stale reviews, scope withdrawal, limits and timeouts.
Actual run totals and owner-only live evidence are in
`evidence/sanitized-results/verification.md`; real academic records are not committed.

Next priorities are an evidence-backed review path for category remapping and
individual assessment weights; instructor amendments/announcement provenance;
mixed-point drop optimization; period-specific and special-condition policies;
and independently verified policy applicability. Office/OCR syllabus extraction
retains the underlying reader's existing limits. False-positive rule candidates
may conservatively block calculations; this is preferable to accepting an
unmodeled condition silently. Optional discrepancy notifications remain deferred
behind the existing delivery/consent gates and are disabled. No professor contact
or notification delivery was added.
