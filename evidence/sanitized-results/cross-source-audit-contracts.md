# Cross-source and grade audit contracts

## Deadline audit

The reproduction uses fictional Canvas assignments, a syllabus and an explicitly selected schedule page. Both sources say “11/11 Life extension (Quiz 12)”. The selected assignment is titled “QUIZ #12”. The audit groups the two passages, records the embedded identifier and matched assignment ID, and retains the source IDs, versions, locators and offsets. Its assignment query has three candidates. The two passages establish November 11 as a calendar fragment. Neither establishes a year, clock time, timezone or governing deadline. There are zero comparable deadline pairs in this case.

A separate fixture supplies two explicit, fully timed document deadlines and a Canvas deadline. The audit compares three pairs and detects the one-hour difference in two of them. Changing the source timestamp does not select a winner. Explicit amendment language adds a supersession candidate for review. A shared calendar date establishes agreement only to date precision.

Read each query’s cross-source comparison alongside the graph’s audit coverage. Source retrieval is scoped to the selected and bounded inputs. Graph construction records the evidence that reached the builder. Entity matching counts unmatched occurrences. Actual comparison counts pairs from distinct sources with comparable dates. The existing graph completeness flag describes input coverage and matching; a fully built graph can have zero cross-source comparisons. Findings can identify a source difference while overall coverage is partial. The audit cannot determine which deadline governs from a topic mention.

## Grade timeout investigation

A read-only lookup of the supplied grade request in the local usage ledger found 37 attempts. Their start times spanned 88.84 seconds of the 90-second request budget. All 22 individual assignment-detail reads returned HTTP 200. Their start times spanned 66.7 seconds. Syllabus discovery then read the file and module inventories, including six module-item collections. The last pages-listing attempt had an uncertain settlement and no recorded HTTP status. This places the timeout during automatic discovery after sequential evidence verification consumed most of the shared budget. The ledger does not attribute all elapsed wall time or establish a Canvas pages outage. The historical consumer catalog was unavailable for direct inspection. The checkout’s shared response schema includes unknown freshness.

Automatic syllabus discovery and reading now have at most 30 seconds, bounded by the remaining overall request time with two seconds reserved for returning the outcome. User-selected material IDs skip automatic discovery. The timeout response records the interrupted stage and distinguishes local budget expiry from a raised upstream timeout. It returns an indeterminate classification without numerical grades. Receipt-based freshness and coverage travel with completed grade responses. If receipt freshness cannot be verified, the grade response uses the catalog-compatible not_refreshed value and a warning. The collector retains its underlying uncertainty.

## Changed files

| Area | Files |
| --- | --- |
| Date evidence and candidate matching | `src/canvas_bridge/academic_dates.py`, `src/canvas_bridge/academic_rules.py` |
| Graph observations, comparisons and audit response | `src/canvas_bridge/academic/evidence_adapters.py`, `src/canvas_bridge/academic_evidence.py`, `src/canvas_bridge/academic_intelligence.py` |
| Grade timeout and response contract | `src/canvas_bridge/grade_audit.py` |
| Reviewed output fields and course-scoped benchmark fixture | `src/canvas_bridge/privacy/output.py`, `src/canvas_bridge/benchmark_lab/adapters.py` |
| Tests | `tests/test_academic_dates.py`, `tests/test_academic_intelligence.py`, `tests/test_grade_audit.py` |
| Documentation | `docs/tool-contracts.md` and this report |

The operational investigation used accounting metadata only. Acceptance used synthetic coursework, the existing authorization and output boundaries, and the published MCP tool schemas. The installed service and client catalog require a release and an authorized retest to establish live behavior. Large courses and slow upstreams can still exhaust the budget. The synthetic differences establish no historical course conflict.

## Verification

- Academic dates and intelligence, grade audit, evidence graphs, assessment preparation, independent intelligence, damaged-document corpus, benchmark lab and privacy suites passed 329 tests.
- Refresh timestamps, paged inventory, egress contracts and MCP contracts passed 42 tests.
- The final identifier and grade-schema acceptance rerun passed 46 tests. A subsequent focused rerun passed both the selected-schedule reproduction and the MCP projection check after exposing the per-occurrence comparisons in the audit. These runs overlap the main suite.
- Ruff and scoped Git whitespace checks passed. No full-suite result was run or reused for this patch.
