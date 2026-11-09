# CB-BUDGET-04 — Percentage-Based Pools, Fairness & Task Budgets

**Audience:** Codex implementation agent  
**Priority:** P0 before student-scale usage  
**Depends on:** CB-BUDGET-01 through CB-BUDGET-03

## 1. Objective and design decision

Use **percentage allocations for workload classes**, not rigid percentages for individual API fields, endpoints, or every MCP tool. A field-based scheme is brittle: tool footprints evolve, high-value operations span many endpoints, unused categories strand capacity, and each API call may carry a different contractual charge. A global hard commercial cap is mandatory; workload percentages are primarily **soft scheduling targets**, with controlled borrowing and a protected reserve.

The student need not know contract details. The LLM never selects a cheaper workload class merely by labeling its request `interactive`; server logic maps registered operations to trusted categories and validates task context.

## 2. Configuration and example

Support a flexible, versioned allocation policy where all percentages total exactly 100% of the **usable pool after safety margin**:

| Pool | Default example | Intended use |
|---|---:|---|
| `interactive` | 55% | Student-triggered course queries, reading, immediate study support |
| `scheduled_sync` | 25% | Planned incremental refresh and bounded indexing |
| `exploratory` | 10% | Broad audits, optional discovery, expensive background analysis |
| `reserve` | 10% | Operator-defined high-priority, legitimately authorized continuity work |

For a hypothetical 300,000-transaction allowance and 5% safety margin: hard usable pool = **285,000**; soft targets = interactive **156,750**, sync **71,250**, exploratory **28,500**, reserve **28,500**. The remaining 15,000 is *not* free to spend; it is an uncertainty/safety holdback. These are engineering examples, not Instructure allocations or quoted commercial rules.

Represent percentages as rational/decimal values, validate 0..100 range and sum, and use deterministic integer rounding such that targets sum exactly to the usable total. Updating only the allowance recomputes every target automatically. Keep percentage parameters adjustable by operator config without a migration or core-code change.

## 3. Soft pools and borrowing

Soft pool targets should influence scheduling, not impose needlessly rigid denials. For example, if scheduled sync used 5% of its 25% allocation and interactive demand is high, permit borrowing from unused nonreserve capacity when: (a) global usable budget has headroom; (b) no protected reserve is consumed; (c) borrowing respects per-user/tenant/task limits; (d) a minimum floor for active competing categories remains; and (e) the action is independently authorized.

Record borrower, lender pool, units, cycle, and rules used. Borrowing affects reports but does not create extra global budget. Introduce safe policy choices: `strict_pools`, `borrow_unused_nonreserve`, and `priority_weighted_fair_queue`; default to borrow-unused nonreserve with configurable reserve protection. A producer cannot opportunistically relabel a scheduled job as interactive.

**Reserve eligibility** is a server-maintained allowlist of narrowly defined operations, *not* a user-declared emergency. Reserve is still inside the usable global cap. When a reserve-eligible action is not essential or its source authorization is absent, deny as normal.

## 4. Per-owner fairness

Do not divide global monthly allowance permanently into equal shares of all registered students; inactive users would waste capacity, and new registrations near the end of a cycle would destabilize the allocation. Use configurable per-owner rolling minute/hour/day bursts and per-task caps. Optionally calculate **soft** longer-term fair shares across recently active paid users, bounded by overall remaining budget and controlled by tenant needs.

Suggested policy components:

- Requests per owner in short rolling windows (hard burst limits).
- Daily/monthly owner soft ceilings with fair-share borrowing when excess is available.
- Per-institution concurrent fetch limits and optional contracted caps.
- Total concurrent high-cost tasks per owner.
- Max paginated requests and bytes per task.
- Max retries and wall-clock time.
- Isolation between paying students and synthetic QA traffic.

Avoid using personally identifying email addresses as accounting keys. Use stable opaque pseudonymous owner references, enforce deletion lifecycle, and minimize logs.

## 5. Task budget envelopes

Before a potentially expensive tool invocation, estimate a conservative plan with `max_requests`, `max_units`, `max_pages`, `max_documents`, and `deadline`. Reserve/admit at each actual HTTP attempt, not merely at plan creation. The high-level MCP request returns partial evidence and a continuation cursor if the envelope runs out. Continuations must inherit the same student and task lineage or a server-issued bounded subtask; starting a new prompt cannot reset a global fairness limit.

Example: a `prepare_for_assessment` request gets a configurable upper bound of 40 upstream attempts, while a narrow `get_assignment_details` request gets a smaller envelope. These are illustrative only; calibrate from observed distributions and provider semantics. A task's finite envelope is not a guarantee the full user request can be satisfied.

## 6. Anti-abuse and legitimate access

Users must not manipulate spending classes with prompt injection, fake urgency, course titles, tool arguments, or arbitrary account IDs. Restrict operator override to authenticated administration with an audit event. Rate-limit owner creation and account switching where reasonably possible. Detect bot-like repeated polling and abusive high-fan-out requests without unnecessarily tracking full student messages.

Fairness must not restrict legitimate offline learning or local document analysis merely because the Canvas API budget is exhausted. Never make commercial quotas a substitute for existing Canvas approval or FERPA/privacy checks.

## 7. Acceptance criteria

- 300,000 example / 5% margin yields exactly 285,000 usable units and 55/25/10/10 targets as stated.
- Operator changes allowance to 500,000; percentages recompute without tool code changes.
- An idle sync pool can lend nonreserve units to interactive traffic; global cap never rises.
- An exhausted reserve cannot be reached by a student claiming urgency.
- A runaway AI agent can't reset per-owner throttles by creating many tasks.
- An instructor-prohibited action stays denied even if a workload pool has capacity.
- 100 inactive student accounts do not freeze allocation or reserve unused per-user shares.
- 3 active owners compete fairly without one monopolizing shared concurrency.
- Partial task returns disclose coverage and avoid false completeness claims.
- All category decisions are reproducible from audited server-side rules.

**Definition of done:** percentage knobs are simple for an operator yet economically safe: one immutable global ceiling, flexible class shares, protected reserve, and scoped fairness.
