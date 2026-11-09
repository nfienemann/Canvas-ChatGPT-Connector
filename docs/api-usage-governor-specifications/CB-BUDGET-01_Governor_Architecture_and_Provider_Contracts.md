# CB-BUDGET-01 — Centralized API Governor & Provider Contract

**Project:** Canvas Bridge Personal / future provider-agnostic academic intelligence platform  
**Audience:** Codex implementation agent, Integration + Compliance branches  
**Priority:** P0 before production paid API usage  
**Status:** Implementation specification; not a claim of existing implementation  
**Prerequisites:** Existing upstream authorization and source-provenance enforcement

## 1. Objective

Create a provider-neutral `UpstreamUsageGovernor` that every external provider API attempt must pass through. It must enforce technical rate limits and commercial budgets as **independent dimensions** while preserving existing authorization, student privacy, academic-integrity, and source-revocation gates. An LLM or any MCP tool may *request* a provider operation; neither controls its admission, price, limits, exemption, retry, or usage accounting.

The eventual Instructure agreement has not provided a monthly transaction allowance or billing definition. Implement an **injectable contract adapter** so the operator later configures an allowance (e.g. 300000 transactions) and associated contractual counting rules without rewriting tools or budgeting algorithms. Never invent a fee, allowance, or transaction definition. No live Canvas traffic becomes authorized simply because a budget is configured.

## 2. Required integration boundary

Inventory all outbound institution API paths: HTTP clients, OAuth refresh, pagination helpers, course file fetch/download, background refreshes, grade/assignment retrieval, search, retries, webhooks that cause API reads, admin tools, and future provider SDK extensions. Route them through one provider-specific transport facade and a single final admission point immediately before **each network attempt**. One `prepare_for_assessment` tool call can cause many upstream attempts.

Provide a dependency injection interface, not a hardcoded wrapper around a single Canvas endpoint:

```python
@dataclass(frozen=True)
class UsageContext:
    provider_id: str
    contract_id: str | None
    tenant_id: str | None
    owner_id: str | None
    task_id: str
    operation: str
    workload_class: str
    resource_scope: str | None
    attempt_id: str


class GovernedProviderTransport(Protocol):
    async def request(self, ctx: UsageContext, request: RequestSpec) -> ProviderResponse: ...
```

Keep IDs opaque in telemetry. Preserve authentication, network allowlists, OAuth scope and privacy checks before admission.

## 3. Four distinct controls

1. **Legal/authorization gate:** whether this provider, institution, owner, scope, endpoint, and disclosure are authorized; deny first.
2. **Commercial monthly allocation:** total billable transactions/units admitted this contract period, net of safety margin and reserves; persistent across workers and restarts.
3. **Technical throttling:** adaptive request/concurrency pacing based on Canvas response headers and throttling signals. Its `X-Request-Cost` units are *not* assumed to be billable commercial transactions.
4. **Fair-use/admission:** owner, institution, task, and workload-class soft/hard controls preventing a single runaway agent from monopolizing allocation.

Each denial has an independent reason code and remedy. Logging must distinguish technical throttling from commercial exhaustion, upstream authorization denial, and host failure.

## 4. Provider billing adapter

Create `ProviderBillingPolicy` with immutable version and effective period. Required fields: provider/contract identity; allowance unit name; budget units per attempt rule; method/endpoint exceptions; failed requests treatment; pagination counting; retries counting; redirects; file downloads; out-of-band usage; contract timezone/calendar anchor; included quota; overage treatment; margin; and evidence source. Adapter must support billable units based on `1 per HTTP request`, endpoint-weighted charges, or a later externally reported counter. **Default estimate is conservative, and any unconfigured commercial terms must be identified as unknown.**

The contract terms presently disclose a monthly API transaction allocation and possible overages, but not a public universal rate or exact transaction counting. Therefore no inference that `X-Request-Cost` equals a paid transaction is allowed. Capture both counters in separate fields. Provider-specific adapter can be added without editing core allocation logic.

## 5. Policy configuration sample

Config shape (illustrative, not approved terms):

```yaml
provider: canvas
contract_id: agreement-placeholder
billing:
  status: unconfigured  # unconfigured | configured | reconciled
  unit: commercial_transaction
  monthly_allowance: null
  charge_model: pending_contract_definition
  timezone: UTC
  cycle_day: 1
  safety_margin_pct: 5
  paid_overages: disabled
allocation:
  interactive_pct: 55
  scheduled_sync_pct: 25
  exploratory_pct: 10
  reserve_pct: 10
rate:
  max_concurrency_per_token: 1
  retries_per_attempt: 2
  respect_retry_after: true
```

Configuration must be externalized and typed, validated, versioned, and audited; it must not contain provider credentials. `null` is not infinity. In a paid production deployment with unknown allowance or counting rules, the governor must not quietly assume unlimited API usage. Provide an explicitly documented **synthetic/test mode** that exercises the engine without outbound Canvas requests.

## 6. Operation labels and defaults

Classify operations by business purpose: `interactive`, `scheduled_sync`, `exploratory`, `reserve_eligible`. Category is determined by trusted server-side routing, not caller-provided text. Each operation declares maximum pagination depth, max body size, timeout, retry eligibility, max operation cost, cache eligibility, and read/write risk. Unknown endpoints default to DENY until classified and reviewed. Read-only Canvas Bridge still must govern POSTs used by read APIs if any exist; HTTP verb does not determine risk or billing.

Do not allocate hard individual budgets to every **field** or endpoint. Adding a new rubric field must not require editing the financial allocation model. Costs accrue to the single global contract budget plus configurable workload pools and fair-use gates.

## 7. Diagnostics and public MCP behavior

Return stable errors: `PROVIDER_NOT_AUTHORIZED`, `BILLING_CONTRACT_UNCONFIGURED`, `UPSTREAM_BUDGET_EXHAUSTED`, `WORKLOAD_POOL_DEFERRED`, `OWNER_RATE_LIMITED`, `TASK_BUDGET_EXCEEDED`, `UPSTREAM_THROTTLED`, `GOVERNOR_UNAVAILABLE`. Include whether permitted cached information is available and next plausible retry condition; never promise refresh at a precise time without scheduling it. Do not expose commercial agreement details to students.

Offline, local-document and synthetic workflows must continue when upstream budget is exhausted, subject to independent rights and authorization. Stale institutional caches remain gated by their original source authorization and revocation conditions.

## 8. Acceptance and handoff

- A tool causing 50 HTTP attempts is charged/admitted as attempts, not as one MCP call.
- Every provider access path uses the guarded transport; attempts bypassing it fail CI tests.
- A provider change requires an adapter and config, not edits to all MCP tools.
- A new signed/verified allowance is supplied through operator configuration without redeploying core code.
- Canvas technical cost headers and commercial billed transaction units remain separate.
- Unknown contract terms cannot silently produce unbounded live traffic.
- Existing institutional authorization gates and academic-integrity controls remain effective.

**Deliverables:** interface + adapters, inventory of call sites, typed configuration schema, migration notes, instrumentation hooks, tests, and an ADR documenting the distinction between rate, transaction, and spend budgets.

**Definition of done:** a single auditable admission layer owns all upstream traffic and exposes provider-independent decisions without asserting any as-yet-unquoted Instructure commercial pricing.
