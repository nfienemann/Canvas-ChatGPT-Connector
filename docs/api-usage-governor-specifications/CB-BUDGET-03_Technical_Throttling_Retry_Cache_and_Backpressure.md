# CB-BUDGET-03 — Technical Throttling, Backpressure & Efficient Retrieval

**Audience:** Codex implementation agent  
**Priority:** P0 for stable upstream use; P1 for optimization  
**Depends on:** CB-BUDGET-01 and CB-BUDGET-02

## 1. Objective

Respect Canvas API's dynamic rate limiting independently from monthly financial allocations. Keep agents from causing accidental storms through pagination, repeated sync, document downloads, or recursive tool calls. Preserve truthful freshness and permissions while caching reusable results. Never bypass existing institutional authorization or data-privacy checks to save transactions.

## 2. Evidence-based Canvas behavior

Canvas documentation describes dynamic, per-access-token throttling; responses may include `X-Request-Cost` (floating-point technical cost) and `X-Rate-Limit-Remaining`. Concurrent requests can incur pre-flight penalties. Throttling responses have been documented as `429` and in some historical implementations `403`; inspect status/body rather than treating every 403 as rate limiting. The partner transaction allotment is separately determined by contract and must not be derived from either throttle header.

Reference: https://github.com/instructure/canvas-lms/blob/master/doc/api/throttling.md and https://www.instructure.com/policies/canvas-api-policy . Capture observed behavior in integration tests; do not hardcode old numerical token-bucket capacities from community posts.

## 3. Adaptive technical limiter

Implement provider adapter with a conservative default per-token concurrency cap. Maintain separately scoped technical budgets for individual OAuth tokens where applicable, plus a global service transport ceiling and a tenant fairness queue. Implement smooth token bucket or leaky bucket pacing if supported, but adapt to actual observed headers and server throttle signals. Use monotonic clocks for short-lived pacing and wall-clock billing periods.

`X-Rate-Limit-Remaining` is a signal about server-imposed remaining technical quota, not about how many billable commercial transactions remain. If header absent or unparsable, fall back to fixed conservative pacing with telemetry. Validate bounds for hostile or malformed headers; ignore attempted header injection into logs or UI.

## 4. Retry and circuit breaker rules

- `429` or identifiable throttling: honor valid `Retry-After` where present; back off with jitter and hard cap; do not spin or immediately retry in loops.
- `403` authorization/policy denial: **never retry as throttling** unless an unambiguous provider error payload identifies a throttle response.
- `401` invalid access: use only the pre-existing permitted credential-refresh mechanism; never recursively refresh forever.
- `5xx`/network failures: only bounded retries for safe/idempotent operations, with per-task cumulative time and cost limits.
- Every retried attempt passes through a *new* financial reservation and rate admission.
- Consecutive upstream failures open a circuit breaker scoped by provider/tenant/token/endpoint as appropriate; probes are guarded and charged too.

Default limits are configuration, not product promises. Backpressure responses tell the LLM/client the request was deferred, not that the data are fresh. Do not queue unbounded work for later without supported scheduling, capacity limits, and valid source authorization at execution time.

## 5. Pagination and fan-out controls

Every high-level MCP operation must declare a maximum page count, document count, total bytes, fan-out, duration, and estimated maximum API attempts. Each pagination continuation is a fresh governed network attempt. An agent cannot evade limits by changing query text, running parallel continuations, or splitting equivalent searches into many tasks. Batch when the provider supports it and batching is permitted, and deduplicate overlapping requests per owner/course/source/version.

For large tasks, return a partial result with explicit `coverage`, `next_cursor` when permitted, `estimated_remaining_calls`, and `reason_code`. A partial result must not be represented as comprehensive. Avoid unnecessary repeated polling of progress endpoints; use bounded exponential intervals.

## 6. Caching strategy

Introduce server-owned caching for authenticated GETs and read-only compatible endpoints, keyed by provider + authorized owner + institution + resource ID + relevant query shape + source version/authorization epoch. Support cache hits, request coalescing (single-flight), ETags/If-Modified-Since where supported, explicit TTL, and incremental synchronization.

- Cache use must validate *current* access, privacy, egress, retention, deletion, and source epoch before release.
- Cross-user caching is forbidden absent independently verified sharing authorization and safe classification.
- Mark response source retrieval time, freshness, coverage, version and cache provenance.
- Conditional GETs still count as an upstream attempt under financial rules unless contract specifies otherwise.
- A content hash match is not institutional authorization.
- A changed authorization epoch invalidates relevant caches and derivatives.
- Never cache credential or full response bodies in usage telemetry.

## 7. Priority queue and graceful degradation

Prioritize **authorized interactive user tasks** ahead of bulk sync and exploratory scans, subject to fairness. At a financial soft threshold, progressively disable background refresh, increase cache reuse, shorten search fan-out, and offer permitted local analysis rather than consuming reserve. At a hard threshold, deny all further billable upstream attempts without operator action and provide transparent fallback. Never silently present old data as freshly retrieved.

Distinguish timeout from exhaustion and throttling. Report whether a request may be retried later, whether a partial result remains usable, and whether local processing can continue. Interface messaging must not leak global partner allowance to untrusted students.

## 8. Verification scenarios

- 10 MCP calls requesting the same unchanged assignment yield a single upstream request while source access remains valid.
- 100 concurrent requests spread across 10 OAuth tokens respect each token's technical limit and the global financial cap.
- An API 403 permission_denied is not retried.
- An explicit throttle response triggers a bounded retry respecting `Retry-After` and a new reservation.
- Agent pagination cannot silently continue beyond a declared cap.
- Removed course access blocks cached material and invalidates derivatives.
- Search coverage reports partial when budget halts retrieval.
- Cache invalidation does not cause an unbounded re-fetch storm.
- Scheduled sync does not starve interactive study operations.
- Offline imported documents remain usable when upstream Canvas budget is exhausted.

**Deliverables:** transport middleware, adaptive pacing policy, bounded retry handler, quota-aware page walker, request coalescing, cache-auth tests, provider mocks and monitoring metrics.

**Definition of done:** Canvas Bridge is both respectful of provider performance and parsimonious with commercial API transactions, without compromising data access controls or misrepresenting freshness.
