# Canvas Bridge — Commercial API Transaction Governor

**Audience:** Codex / Compliance and Integrations branches  
**Package:** six modular implementation specifications + sample configuration  
**State:** design handoff; not proof of implementation or Instructure approval

## One-sentence design

The operator sets a **negotiated monthly billable-unit allowance** and verified accounting rules in external configuration. Canvas Bridge then automatically derives category allocations and enforces a single shared hard admission ceiling with safe technical throttling, atomic accounting, task limits, and graceful offline fallbacks.

## The answer to “a percentage of budget for each field?”

**Use percentage shares for _workload classes_, not each API field/endpoint.** Rigid per-field slices are brittle because different features call the same endpoints, new fields are added, and idle allocation is wasted. A single global hard ceiling is mandatory. Workload targets should be soft, with tracked nonreserve borrowing and a protected reserve. Per-owner, per-task and per-institution constraints are enforced separately.

Example categories: **55% interactive / 25% scheduled synchronization / 10% exploratory / 10% reserve**, applied **after** an illustrative 5% safety holdback. These are design defaults, not prices, quotas, or terms from Instructure.

If a future contract says **300,000 billable transactions/month**, usable under 5% margin is **285,000**. Pool targets: interactive **156,750**, sync **71,250**, exploratory **28,500**, reserve **28,500**. Even with pool borrowing, **no task can spend beyond the global hard usable allowance**. If the contract later says 500,000, change the single allowance value and derived targets recalculate. A change to billing *semantics* may require changing the provider adapter and tests, not the budget model.

## Specifications, in implementation order

1. `CB-BUDGET-01_Governor_Architecture_and_Provider_Contracts.md` — central request gateway, contract adapter, separate authorization/technical/commercial controls.
2. `CB-BUDGET-02_Atomic_Reservations_and_Durable_Accounting.md` — race-proof durable usage ledger, reservations, uncertain charges, billing cycles and reconciliation.
3. `CB-BUDGET-03_Technical_Throttling_Retry_Cache_and_Backpressure.md` — Canvas technical pacing, retry safety, bounded pagination, caching, and honest partial results.
4. `CB-BUDGET-04_Percentage_Pools_Fairness_and_Task_Budgets.md` — adjustable workload shares, reserve, borrowing, per-user and per-agent fairness.
5. `CB-BUDGET-05_Billing_Config_Admin_Dashboard_and_Alerts.md` — operator CLI/UI, contract ingestion, reports, warnings and usage reconciliations.
6. `CB-BUDGET-06_Testing_Rollout_Security_and_Release_Gates.md` — reproducible concurrency/security tests, mock providers, launch gates, and compliance report integration.

The `examples/canvas_budget_policy.example.yaml` file demonstrates a **disabled/unconfigured** commercial contract. It is a template only; do not assume any commercial allowance, approved Canvas API access, or Instructure partner pricing.

## Non-negotiable invariants

- Live Canvas API access remains blocked without independent institutional/provider approval, regardless of available budget.
- Every actual upstream network attempt, including pages, retries, background jobs and file downloads, goes through the governor.
- *Commercial transactions* and Canvas's dynamic `X-Request-Cost` throttling units are not the same metric.
- A configured allowance limits local network admission; it cannot guarantee an invoice contains zero overages if provider counting rules or usage by other applications are unknown.
- No LLM-controlled budget overrides, exemptions, reset counters, or workload labels.
- Failed or indeterminate sent requests may be chargeable; conservatively hold units pending vendor reconciliation.
- Offline, independently supplied documents remain available where their own privacy and academic-integrity rules permit.
- All changes are versioned and tested; only real test results may be marked `TESTED`.

## Later: the smallest safe update

After an approved commercial arrangement and signed contractual counting semantics exist, the operator should be able to say to Codex:

> Set the Canvas partner allowance to 300,000 commercial transactions per contractual month. Leave the existing source authorization controls, safety margin, pool percentages, ledger, and individual task limits intact. Preview the policy diff, run a synthetic simulation and quota tests, then apply through the authenticated operator workflow. Do not enable paid overages.

If the contract uses endpoint weights, counts 429s differently, includes external consumers, or has non-calendar billing cycles, these inputs **also** need to be configured first; the numerical allowance alone cannot define actual billable cost.

## Public technical references

- Instructure API policy (rate-limit and access restrictions): https://www.instructure.com/policies/canvas-api-policy
- Canvas throttling documentation and `X-Request-Cost`: https://github.com/instructure/canvas-lms/blob/master/doc/api/throttling.md
- Instructure Partner Terms (paid API usage, order-form limits and overage fees): https://www.instructure.com/policies/partners/terms-and-conditions
- Instructure 2026 commercial API announcement: https://community.instructure.com/en/discussion/666822/strengthening-the-future-of-the-canvas-open-ecosystem-an-update-on-api-integrations

## Codex completion instruction

Implement in phases, preserving central institutional authorization, academic-integrity enforcement, and data egress/revocation controls. Include an ADR on commercial versus technical quotas; list all upstream call sites; generate migrations for accounting tables; and produce green synthetic acceptance tests before marking this package complete. No mock or successful local test constitutes permission for live Rowan Canvas access.
