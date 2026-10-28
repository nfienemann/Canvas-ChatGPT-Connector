# Academic workflow orchestration

`run_academic_workflow` is one read-only entry point for seven reviewed workflows.
The server owns the immutable registry; callers select a name and bounded inputs,
never a tool name, executable graph, URL, permission or scheduler.

| Workflow | Sequence and scope |
| --- | --- |
| Daily Academic Brief | Assignment snapshot, optional observed-change comparison, optional supplied calendar availability, study priorities; up to five selected courses |
| Weekly Course Priorities | Shared assignment snapshot, calendar availability, existing deterministic study planner; up to five courses |
| Exam Preparation Pack | Confirmed assessment and cited scope/materials, supplied availability, suggested review sequence with time blocks where possible; one course |
| Grade Outlook | One grade-evidence collection, current arithmetic, optional explicit scenario using the same evidence; up to three courses |
| Course Discrepancy Review | Existing date/requirements audit and independent grading-rule reconciliation; one course |
| Lecture Comprehension | Explicit material selection or outline discovery, bounded document reads, inspected-pixel report handoff; one course and three materials |
| Calendar Preparation | Shared workload, fresh complete calendar context, existing deduplicated event proposals; up to five courses |

## Contract

`workflow_registry.py` declares required and optional capabilities, ordered
dependencies, authorization requirements, limits, output version and partial-result
behavior. Input validation rejects unknown fields and workflows, empty selection,
invalid timezones, naive dates, windows over 31 days and inputs over 64 KB. Omitted
window bounds mean the next seven days, explicitly disclosed in the result.
Explicit course references must already be selected and accessible; the tool never
changes course selection. An unavailable requested course is counted as missing,
without returning its content. An oversized course scope requires a narrower request.

The original services remain authoritative for provider capabilities, institution
approvals, exact resource authorization, request admission, cooldowns, sandboxing
and egress. Optional capability negotiation cannot grant a permission. Every executed
adapter checks its original tool policy, and request authorization is checked before
and after each step and before release. A source or authorization change withholds
the aggregate. A failed membership refresh that invalidates the lease also withholds
previously gathered findings; a resource budget never overrides authorization.

Within a request, equivalent operations are memoized, the workload snapshot is
shared, and grade scenarios reuse acquired evidence. There is no cross-user result
cache. Steps execute serially; concurrent requests use independent contexts and the
existing admission and file-worker controls. No serial test is presented as evidence
of parallel file processing.

The defaults are 24 steps, 120 HTTP attempts including retries, 4 MB API bytes,
30 MB document bytes, three downloaded files, 30 seconds per step and 90 seconds
including initial negotiation. Existing stricter limits still apply. The 40 KB
workflow output ceiling also supplies a conservative byte-based token upper bound;
the connector does not run a language model or claim a specific tokenizer count.
Oversized outputs drop whole sections with their citations and explicitly report
the omission. The outer MCP layer retains its separate total response limit.

## Partial results and evidence

Results contain a student-readable summary, sections with source IDs and freshness,
assumptions, limitations, next actions, request/definition digests and a bounded
execution trace with timings and resource counters. Unsupported sources, bad
references, timeouts and limits have explicit reason codes. Independent completed
sections survive ordinary dependency failures. A partial dependency cannot produce
an unqualified complete derived section.

Calendar context is supplied through the student's existing authorized client
connection. It is not independently authenticated by this connector. Missing,
stale or incomplete context is unknown availability, never an empty calendar.
Proposals remain subject to the existing exact-event approval, write and provider
receipt workflow. This tool makes no external write and saves no plan.

Lecture text is not visual comprehension. The result names the existing page/slide
render and figure-inspection tools and asks the client to return observations with
current render receipts. Checked receipts establish provenance, not scientific
accuracy. An unreadable figure, missing report, or unverified interpretation remains
partial. Exam review blocks fit supplied time windows after known busy periods;
they do not establish adequate effort, complete scope or probable mastery.

The tests in `tests/test_workflows.py` exercise all seven real service paths,
unavailable courses/capabilities, missing calendar and baseline, grade reuse,
corrupt documents, bad citations, authorization expiry/revocation, concurrency,
timeouts, API budgets, partial sources, output limits and calendar proposals.
The existing CI pytest job runs them on every change. Existing benchmark CI retains
its objective accuracy/privacy gates and prior-version trend reports. No competitor
or model comparison is claimed by these orchestration tests.
