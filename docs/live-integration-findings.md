# Live integration findings and hardening

The findings were reproduced or checked against the current private connector
on 2026-10-20. Automated regressions use fictional records only. The earlier
PDF-reading increment remains enabled; this change does not alter Canvas content
or grades, add write tools, or extend the selected-course boundary.

| Finding | Classification and root cause | Resolution / honest remaining boundary |
|---|---|---|
| Scientific search misses unread PDFs | Expected index limitation; legacy `search_course_materials` covers pages. Dedicated file search covers previously extracted file text. | Both tools explicitly identify scope and unread exclusions. Discover files, read likely papers, then search the indexed text. No match never proves an unread document lacks the topic. Automatic whole-course/background indexing is not implemented. |
| Parent module ID cannot read one PDF | Expected identifier boundary; modules can contain multiple resources and their IDs are not file identities. Authenticated PDF reading was added in the preceding increment. | Outline File items return `material_ref`; pass it as `file_id` to `read_course_file`. Invalid references now explain this flow without leaking another owner's data. A narrow module query also resolves files outside the first 100 general inventory entries. |
| Outline lists filenames without text | Expected metadata-only discovery behavior; listing is not extraction. | Explicit `document_content_included=false`, reader/search tool names, enabled state, format scope and per-collection failures. The existing authenticated reader returns actual PDF contents with pages and continuation. |
| No history without complete baseline | Expected observation limit; Canvas assignment reads are current snapshots, not a historical event log. | Return precise missing-baseline reason, earliest complete observation, comparison interval, incomplete-observation count and freshness. A later partial observation cannot make an older complete comparison look current. Exact change times and pre-baseline history remain unknown. |
| Undated assessments can appear to be upcoming obligations | Output/planning ambiguity confirmed. Null due dates were preserved internally, but broad workload wording and automatic allocation could imply relevance. | Distinguish `no_canvas_due_date` from unavailable/not-returned dates. Undated records have `schedule_status=unknown`, remain in the undated section, and may be historical or externally scheduled. Unconfirmed undated work is not automatically allocated unless current student input establishes relevance. |
| Workload says `not_submitted`, details says `unknown` | Confirmed query-contract bug. The assignment list requested `include[]=submission`; single-assignment retrieval omitted it. The mock previously returned submission data regardless, hiding the discrepancy. | Both routes now explicitly request the same current-user submission inclusion and use one normalizer. The mock enforces this distinction. No stale workload fallback manufactures certainty when the detail response genuinely lacks evidence. |
| Empty requirements text is ambiguous | Confirmed response-contract bug plus genuine empty source field. The reader collapsed missing, null and empty descriptions into an empty string and reported no field coverage. | Preserve `requirements_text` and add `requirements_coverage`: present, empty_in_canvas, not_returned, invalid, no_extractable_text or truncated. Failed HTTP retrieval remains an error, never empty success. Scope is only the assignment description, not quiz questions or all requirements elsewhere. |

## Submission semantics

`submission_state`, `submission_evidence` and `submission_state_basis` are shared
by workload and assignment details. Only an explicitly returned, verified own
`unsubmitted` workflow becomes `not_submitted`. That is the Canvas online record;
it does not prove that an assessment is upcoming, unfinished offline or missing.
Absent, malformed or wrong-user evidence remains unknown. Conflicting workflow
and timestamp evidence remains unknown. A posted grade without submission proof
does not establish an online submission. Assessment state, timeliness, availability
and personal progress remain separate dimensions.

The authenticated live comparison confirmed that the source list contained the
owner's unsubmitted record; the original detail response omitted submission; the
corrected request returned the same own record. It also confirmed that all 11
undated records had explicit null due dates and that the examined assignment's
description field was an empty string. None of those observations establish
whether the assessments were completed outside Canvas or scheduled in class.

The upstream inclusion and due-date semantics are documented in the primary
[Canvas Assignments API](https://developerdocs.instructure.com/services/canvas/resources/assignments).

## Regression coverage and deployment

`tests/test_integration_findings.py` covers every finding: list/detail parity,
missing/foreign/malformed/conflicting evidence, empty versus omitted/failed
requirements, eleven undated records, conservative planning, baseline intervals
and incomplete snapshots, unread PDF search, module/file reference separation,
module discovery beyond the general inventory cap, and the actual HTTP MCP contract.

Existing authenticated file transport, OAuth refresh, sandbox, access isolation,
cache, deletion and continuation suites remain in place. Only GET requests reach
Canvas. There is no database schema migration for this increment. Added response
fields preserve existing fields and current code derives date coverage for older
stored snapshots. Restart the private source service to load the updated adapter.

OCR, visual interpretation, complete pre-connection history,
and automatic unread-file indexing remain unsupported. See `file-reading.md`
and the release gates for platform and distribution boundaries.


A subsequent synthetic planning audit confirmed date-only deadline and DST
capacity bugs. Their root causes, corrections and verification boundaries are
recorded in [planning date boundaries](planning-date-bounds.md).
