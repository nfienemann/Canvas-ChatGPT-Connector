# CB-BUDGET-05 — Contract Configuration, Operator UX & Budget Observability

**Audience:** Codex implementation agent  
**Priority:** P1, with P0 configuration validation and shutoff  
**Depends on:** CB-BUDGET-01, -02, -04

## 1. Objective

Enable a future conversation of the form **“Our signed contract allows ###,### monthly API transactions”** to become a validated configuration change, not a refactor. The operator must also configure any non-obvious billing terms disclosed by the agreement (scope, billable actions, period, overage schedule, external usage). Show enough operational visibility to manage spending without exposing confidential contracts, student records, or tokens.

## 2. Contract data source and precedence

Maintain a versioned, encrypted-or-access-controlled `PartnerBudgetContract` object. Separate contract facts from operational preferences:

**Contract facts:** provider ID, signed agreement ID (opaque), included units, transaction counting policy, billing period start/timezone, effective/renewal dates, external traffic scope, purchase tier, agreed overage rate (optional), vendor report location and reporting delay, evidence hash/reference.

**Operator controls:** safety margin percentage, workload pool shares, per-user limits, task caps, optional financial spend ceiling, caution thresholds, reserve eligibility, circuit-breaker and technical rate-limit parameters.

A new operator setting cannot change external legal permissions. Existing approval registry remains authoritative for whether live provider access is permitted. Avoid treating `PartnerBudgetContract.status=configured` as proof that the Instructure partnership has been approved.

If commercial terms are incomplete, label the model as provisional. The exact API transactions counted under contract may differ from local HTTP request attempts and dynamic Canvas `X-Request-Cost` values. Do not claim invoice-grade accuracy before vendor reconciliation validates the adapter.

## 3. Operator commands and change workflow

Implement restricted CLI or secured admin UI commands, for example:

```text
canvas-bridge budget status --provider canvas
canvas-bridge budget propose --provider canvas --allowance 300000
canvas-bridge budget simulate --provider canvas --policy proposed.yaml
canvas-bridge budget apply --provider canvas --policy approved.yaml
canvas-bridge budget reconcile --provider canvas --statement vendor-summary.json
canvas-bridge budget report --provider canvas --cycle 2026-11
```

`propose` and `simulate` are read-only. `apply` must validate approval state, current contract, schema, amount, effective cycle, authorization, and policy version. Preview changes and require a distinct explicit operator action to apply; maintain audit history and rollback *configuration* to last known safe policy without rolling back a financial ledger.

A simple allowance update to a validated, compatible existing contract should be a one-field change followed by regeneration of derived targets. A different transaction-counting definition must trigger adapter review and acceptance tests before deployment.

## 4. Dashboard design

Provide a privacy-preserving admin dashboard with:

- Contract period with timezone and time remaining.
- Included transaction allowance and configured safety margin.
- Locally settled units, in-flight reservations, uncertain holds, and vendor-reconciled totals.
- Available usable units and reserve remaining.
- Pool usage and borrowing by workload class.
- Top operation classes by units, cost/transaction uncertainty, and upstream throttling.
- Requests prevented by owner/task cap, policy denial, technical throttling, budget exhaustion, and provider outages.
- Cache hit rate and deduplicated request savings.
- Allowed vs denied percentage of requests at each security gate.
- Estimated runway at recent 7-day/30-day usage rate; clear that forecasts are estimates.
- Real vendor spend when available, otherwise **N/A**, not `$0`.

Per-student UI shows only their own relevant cooldown/remaining task capacity, not complete business accounting or other students' usage. Avoid storing precise course titles or external IDs in dashboards.

## 5. Reconciliation and uncertainty

Build a pluggable vendor-statement importer rather than scraping undocumented billing portals. Use a validated schema with cycle, unit, provider, usage total, status, and evidence reference. Require a protected input path and administrator review of discrepancies. Duplicate statements and updates must not double-book usage.

When locally counted usage differs from the vendor total: record adjustment, investigate potential external clients, duplicate attempts, out-of-band traffic, counting differences, and dropped logs. Until reconciled, preserve sufficient reserve/uncertainty holdback or stop upstream traffic if the discrepancy threatens the hard cap. A vendor invoice, not local speculation, is the authority for actual charges.

## 6. Alerting and budget actions

Configurable thresholds (examples): 50%, 70%, 85%, 95% of **usable** monthly allocation. Alert fatigue controls: deduplicate per-cycle threshold notifications and severity; support optional daily/weekly summary. At higher thresholds: pause exploratory work, throttle background sync, strengthen request coalescing, and warn operators. At hard stop, fail closed for billable requests; preserve independently permitted cached/local study workflows.

Allow an explicit operator kill switch disabling provider network access independently from quotas. Operator attempts to set a higher budget than the signed allowance must be rejected unless a separately documented contractual allowance change is provided. Paid overages must remain disabled by default; enabling them requires a verified written contract, spend ceiling, and separately acknowledged operator action.

## 7. Demonstration: adding a known allowance

Initial state: `monthly_allowance: null`, `status: unconfigured`, and blocked unmetered paid production traffic. After the operator receives a contract specifying **300,000** monthly billable transactions and confirms billing semantics: propose config, simulate 100,000 synthetic task requests, review safety margin and class targets, apply with audit evidence, then verify no tool schema changes, no database stamp/reset, and no change to institutional authorization state.

Changing to 500,000 later must update only signed contract inputs/effective version and recompute pools. Do not backdate the change silently, and do not reset consumption in the current period unless the contract explicitly provides a revised period/cap and reconciliation logic validates it.

## 8. Tests and acceptance

- `propose` changes nothing and outputs differences.
- `apply` rejects malformed %, negative limits, invalid cycle/timezone, and unknown billing unit.
- A new allowance recomputes targets deterministically without code modifications.
- Client token cannot call operator commands or view exact partner terms.
- Alert emits once per threshold crossing and accurately identifies percentage denominator.
- Late vendor adjustment appears as historical adjustment without silently altering current cycle.
- Reconciliation cannot be performed twice for the same statement.
- Dashboard distinguishes estimated billable units, technical throttle cost, and confirmed invoice charges.
- Zero upstream authorization never becomes approved because admin configured a budget.

**Definition of done:** an administrator can safely operate the system after receiving a partner allowance and reporting details, with clearly bounded financial exposure and honest usage evidence.
