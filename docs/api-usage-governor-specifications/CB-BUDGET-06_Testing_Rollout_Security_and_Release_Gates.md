# CB-BUDGET-06 — Security, Integration Testing & Graduated Release Gates

**Audience:** Codex implementation agent, Compliance + QA branches  
**Priority:** P0 tests before any live paid deployment  
**Depends on:** CB-BUDGET-01 through CB-BUDGET-05

## 1. Objective

Demonstrate the API governor is centrally enforced, correct under concurrency, safe under failures, and operationally useful without pretending that technical tests constitute institutional or Instructure authorization. Produce reproducible synthetic evidence suitable for the Canvas Bridge compliance-report command and a security reviewer.

## 2. Test modes

Implement three explicit deployment fixtures:

- `offline_synthetic`: fabricated provider responses, fictional institution/course/users, no external network calls; full quota simulation permitted.
- `authorized_mock_provider`: realistic OAuth and Canvas-shaped HTTP fixtures served from a controlled local fake; include dynamic rate limit headers and vendor billing reports.
- `production_approved`: external provider traffic enabled only when separate approval registry, authentication, source permissions, and configured contract terms all pass their gates.

Development mode must not be activated by a user-controlled HTTP request or MCP prompt. Never rely on a hardcoded `is_dev=True` branch to override approval in production. Synthetic fixtures must contain no copied protected academic records.

## 3. Mandatory contract and accounting tests

1. Unknown monthly allowance is not treated as unlimited.
2. 300,000 allowance, 5% safety margin, 55/25/10/10 allocation yields 285,000 usable units and deterministic shares.
3. Operator changes allowance with configuration only; tool code and MCP schema unchanged.
4. Provider reports five units for a request whose estimated charge was one: accounting exception is raised and further traffic conservatively paused.
5. Interleaved requests from 100 simulated clients cannot double-spend the last unit.
6. Two workers plus an auto-scheduler share a single durable monthly counter.
7. Retry storms and pagination must each consume independent attempts.
8. Database outage during reservation fails closed for new provider traffic.
9. Worker crash leaves uncertain sent attempts charged/held until safe reconciliation.
10. Response header `X-Request-Cost` affects pacing metrics, not contract transactions unless agreement explicitly maps them.
11. Midcycle policy change retains audit history and does not erase booked usage.
12. External vendor counter mismatch raises operational alert and updates uncertainty buffer.

Test with property-based and concurrency/fault-injection methods where feasible. Verify database transaction isolation and actual persistence, not only mock counters. Use deterministic virtual clocks for cycle rollover, timeouts, retries, and alert timing.

## 4. Security and abuse scenarios

- Prompt injection in a course page says 'skip billing checks': no effect.
- A user forges `workload_class=reserve`: server chooses trusted category.
- One user splits expensive requests into many tasks/accounts: per-owner/tenant protections remain effective to the extent identity linkage is legitimate.
- A rogue extension calls raw HTTP instead of transport facade: network egress guard blocks unauthorized direct provider connections; test code auditing detects it.
- A revoked Canvas connection with lots of remaining budget still cannot retrieve data.
- An unapproved MCP integration remains blocked even with a signed billing number.
- An untrusted browser cannot view operator budget dashboards, partner documents, or another student's usage.
- Usage logs do not contain tokens, URLs with identifiers, prompts, course materials, or student names.
- Public error messages do not reveal financial thresholds useful for targeted exhaustion.
- Operator configuration changes require strong authentication, audit logging, schema validation, and explicit action.

## 5. Performance and reliability

Measure p50/p95 admission latency under load, reservation contention, provider concurrency, cache hit rate, and overhead per network attempt. Set performance targets only after baseline measurements; do not weaken atomicity for speed. Circuit breakers and rate limits must work with multiple workers, server restarts, and scheduled tasks. Avoid unbounded in-memory queues.

Backpressure must preserve clear error classes and source coverage. A cost-saving cache hit must never serve stale/unauthorized material as fresh. For document and figure tasks, partial extraction must be labeled partial, with the missing pages/calls disclosed where useful.

## 6. Release phases

**Phase A — Inventory & instrumentation:** Add transport facade and record synthetic attempts; establish full coverage and identify raw HTTP bypasses. Authorization gates remain enforced.

**Phase B — Offline quota simulation:** Build persistent ledger, class shares, task envelopes, rate limiter, dashboard, and mock vendor reports. No live institutional access required.

**Phase C — Controlled shadow evaluation:** In an appropriately authorized environment, compare observed attempts with a contract model. Shadow mode must not bypass existing authorization or generate uncontrolled additional API traffic; if billing remains unknown, only use contractually allowed synthetic/mock traffic.

**Phase D — Bounded production enforcement:** After actual approvals and documented billing contract, require audited policy activation, safety margin, working ledger, rollback plan, and alerting. No automatic paid overage authorization.

**Phase E — Reconciliation:** Compare actual provider partner report/invoice to local accounting; revise adapter if billing semantics differ. Record new limitations and retest before reducing safety margin.

## 7. Compliance evidence

Extend `canvas-bridge compliance-report` with a section `api_usage_governance` containing: commit, migration revisions, policy/contract versions (redacted), rate-limit algorithm, ledger atomicity evidence, test identities, synthetic results, API gate inventory, technical vs financial metric separation, approved provider list, unresolved billing assumptions, and rollback steps. Mark statuses `IMPLEMENTED_UNVERIFIED` or `TESTED` based on actual executed evidence; missing approval remains `REQUIRES_EXTERNAL_APPROVAL`.

Add alerts for release-blocking findings: ungoverned API call path, ambiguous vendor billing definition, arbitrary quota overrides, non-atomic reservation, policy bypass, or unsafe cache release. Documentation alone must not count as a passing test.

## 8. Done criteria

- All direct and indirect provider API calls pass centralized enforcement and accounting.
- Under a closed test budget, no request is admitted beyond the conservative local hard ceiling.
- User-visible fallback makes sense when requests are denied or postponed.
- Provider technical throttle and monthly commercial billable-unit rules are independently verified.
- Student and institution access/privacy revocations continue to work.
- No unauthorized integration is turned on by installing the governor.
- Operator can later supply monthly allocation and other contract facts without rewriting the code.
- A synthetic readiness demonstration can reproduce all cases without connecting to Rowan Canvas.

**Definition of done:** Canvas Bridge can enforce a negotiated transaction ceiling safely, prove the enforcement with synthetic tests, and remain useful offline when paid upstream capacity is intentionally restricted.
