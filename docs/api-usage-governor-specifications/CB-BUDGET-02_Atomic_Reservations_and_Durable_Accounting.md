# CB-BUDGET-02 — Atomic Reservations, Ledger & Reconciliation

**Audience:** Codex implementation agent  
**Priority:** P0 before a shared multi-student deployment  
**Depends on:** CB-BUDGET-01 central governor and provider billing adapter

## 1. Objective

Prevent simultaneous MCP tasks, workers, scheduled jobs, and retries from collectively consuming more budget than admission allowed. A Python in-process counter is inadequate for multiworker/host deployments. Implement an **atomic, persistent reservation ledger** with idempotency and conservative settlement under failures. Distinguish locally counted attempts from the actual transactions Instructure later invoices.

## 2. Data model

Design models, with migrations and encrypted/sanitized logging as appropriate:

- `contract_budget`: provider, opaque contract ID, policy version, billing cycle ID/bounds, allowance units, safety holdback, configured reserve, overage permission (default false), effective state.
- `budget_pool`: cycle, workload class, soft target, consumed, reserved, borrowed, reserve eligible.
- `usage_attempt`: unique attempt UUID, parent task, owner pseudonym, tenant pseudonym, normalized operation, provider, idempotency key, reservation amount, settled amount, state, observed upstream status, duration, header-derived throttle cost, creation/expiry timestamps.
- `budget_adjustment`: reconciliation event, verified actor/source, reason, delta, effective cycle, linked vendor statement, recorded timestamp, immutable audit reference.
- `usage_period`: per-contract and per-cycle conservation totals, version, out-of-band adjustment, last vendor reconciliation.

Do not store raw API paths containing student IDs, authorization headers, response bodies, file names, token values, grades, prompts, or other personal course content in the usage ledger.

## 3. Admission algorithm

For each outgoing HTTP attempt, in a single SERIALIZABLE/row-locked transaction or equivalent atomic operation:

1. Verify authorization decision and vetted operation category.
2. Determine current contract cycle using the policy's effective billing calendar, not server-local midnight.
3. Obtain an upper-bound reserved charge from the billing adapter. For an unknown endpoint or unbounded estimate, deny or require bounded chunking.
4. Check global hard usable budget, active reservations, safety margin, category allocation, and per-owner/task/institution limits.
5. Persist one reservation and increment corresponding reserved totals; then release lock and permit the outbound attempt.
6. If any check fails, return a typed denial **before** sending a request.

Atomic invariant: `settled + active_reserved + uncertain_hold + provider_external_estimate <= hard_usable_limit`. This applies across processes. If some terms are unknown or billing cannot be observed in real time, clearly document the guarantee as a *local admission ceiling*, not proof the vendor cannot invoice overages.

Use a single consistent lock ordering to avoid deadlocks; measure critical-section duration; do not hold DB transaction locks during external HTTP calls.

## 4. Settlement state machine

States: `REQUESTED`, `RESERVED`, `SENT`, `SETTLED`, `UNCERTAIN`, `CANCELLED_BEFORE_SEND`, `RECONCILED`. The transport must emit an authoritative `SENT` transition immediately before send when possible. Repeated settle/cancel calls are idempotent by attempt ID.

- Request stopped before network send: refund reservation.
- Confirmed response: settle according to current verified billing model, retaining separate response headers for technical throttling.
- Timeout, network disconnect, HTTP 429/403, 5xx, process crash after send: mark **UNCERTAIN** and conservatively retain charge unless contract evidence or reconciliation proves nonbillable.
- Retry: a **new admitted attempt** with a new attempt ID, linked to original; no free retry assumption.
- Follower in a deduplicated request: no additional upstream charge if no extra request is sent.
- If actual charge exceeds reserved upper bound, quarantine as accounting exception; immediately close the affected pool/contract to new outgoing traffic pending reconciliation. Never let mismatched billing silently create a negative budget.

If contract counts pages, each paginated request must reserve independently. Prefetch may reserve a bounded bundle but must settle/cancel each unsent item deterministically.

## 5. Crash and restart recovery

On startup, identify stale reservations. If no request could have been sent, release it with evidence; if the send state is unknown, retain an uncertain hold. A process restart must not reset consumed budget or turn uncertain attempts into free capacity. Provide operator audit tools to reconcile stale holds from verified logs or vendor statements—no end-user release control.

Design for database outage: **fail closed** for new external calls. Read-only local academic features should still work to the extent they do not depend on the unavailable database. If a secondary Redis queue or cache is used for speed, PostgreSQL or another durable source of truth must survive Redis eviction/restart; any fallback must preserve atomicity and not double-admit.

## 6. Cycle rollover and adjustments

Represent each monthly period as stable `[start, end)` instants derived from a configured contractual local timezone and day-of-month, using timezone-aware dates. Handle February, leap years, DST transitions, annual renewal, midcycle contract changes, and late-arriving reconciliation. Do not merely reset a global integer counter on the first of the month.

Late vendor invoices and corrections remain attributed to the proper historical cycle. A new billing cycle does not delete historical ledgers. Policy changes create new versions; do not retroactively rewrite usage events or silently raise limits.

Distinguish live local estimate vs vendor invoice truth. Display both and their difference. If vendor reporting lags, carry forward a configurable nonnegative uncertainty buffer for external clients or unreported transactions sharing the same contract allowance.

## 7. Audit and security

Budget increases and reconciliation adjustments require authenticated operator roles, explicit reason, source evidence, and immutable append-only events. User tool parameters cannot include `skip_budget`, `free_call`, `set_cost`, `is_staff`, or `approved` switches that override server policy. Protect accounting endpoints against replay and request forgery; encode anonymous owner references and enforce strict retention limits.

Keep monetary amounts decimal if supported; transaction unit amounts should be integers or fixed-precision decimals based on partner terms. Do not conflate billed $ values with Canvas `X-Request-Cost` floating-point throttle units. Provide finance exports using aggregated numbers by default.

## 8. Test matrix

- 100 concurrent calls under an allowance of 25 admit at most 25 unit-charge attempts.
- Two processes racing for the last reservation cannot both succeed.
- Crash after reserve but before send is resolved without inventing usage.
- Crash after send retains uncertain charge; restart cannot refund it blindly.
- Two retries consume up to three separately reserved attempts.
- 429 response consumes a charge unless evidence says otherwise.
- Existing completed request cannot be settled twice.
- Failed vendor-reconciliation input cannot silently alter totals.
- Historical cycle corrections do not mutate a new cycle.
- Revoked institutional source cannot be fetched even with ample budget.

**Definition of done:** the consumption ledger is durable, race-resistant, conservative about uncertain upstream attempts, and reconcilable to actual partner reporting without losing provenance or leaking student records.
