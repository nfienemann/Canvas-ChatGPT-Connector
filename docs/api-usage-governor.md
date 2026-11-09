# API transaction governor

Implements the six [CB-BUDGET specifications](api-usage-governor-specifications/README.md)
with synthetic-first enforcement. Installing this code grants no upstream access,
commercial allowance, institutional approval, or permission to publish records.

## Contract, rate and authorization are separate

Existing approval, identity, selected-source, privacy and integrity checks execute
before admission and again before send. `GuardedHTTP` requires a server-owned usage
binding for institutional traffic. Every page, retry, OAuth request, identity probe
and download hop receives a distinct attempt ID and reservation. A tool invocation
does not count as one transaction. Unknown routes and missing bindings fail closed.

`ProviderBillingPolicy` is injectable. The built-in contract adapter supports integer
per-request charges, reviewed operation weights and conservative upper bounds for
externally reported counting. A later provider needs a transport/operation adapter;
core ledger arithmetic does not depend on Canvas fields. Failed-response exceptions
require verified terms. Otherwise 403, 429, 5xx, interrupted streams and unknown sends
retain an uncertain charge. Conditional requests are attempts too.

Canvas `X-Request-Cost` and `X-Rate-Limit-Remaining` are technical signals, separate
from the contractual unit counter. The [primary throttling documentation](https://github.com/instructure/canvas-lms/blob/master/doc/api/throttling.md)
describes per-token quotas and pre-flight concurrency costs. No commercial price or
monthly allowance is inferred from those headers. This code permits no paid overages.

## Atomicity and lifecycle

Migration `f17a6b204c31` adds `contract_budget`, `usage_period`, `budget_pool`,
`usage_attempt`, `budget_adjustment`, `usage_throttle`, `usage_event` and a governor
lock. PostgreSQL acquires one `FOR UPDATE` lock; isolated SQLite uses
`BEGIN IMMEDIATE`. The same ordering protects admission, pools, reservations,
technical concurrency and settlement. No network call runs while holding that lock.

The local invariant is:

```
settled + reserved + uncertain + external estimate <= usable allowance
```

Each admitted request starts RESERVED. A committed SENT transition immediately
precedes the network operation. Duplicate send permits are rejected. Proven unsent
reservations cancel/refund; stale SENT attempts become UNCERTAIN. Settlement is
idempotent. Over-bound reported costs quarantine the period before further traffic.
Database failure denies new sends. An externally discovered discrepancy can exceed
an old ceiling; it is recorded and quarantined, never hidden by negative capacity.

Cycles are stable UTC intervals derived from the contractual timezone and anchor
day (clamped at month end). Midcycle policy versions preserve all usage and pool
bookings. Contract/calendar changes cannot reset a current cycle. Historical
statements affect their original period. Statements compare their **coverage cutoff**
to confirmed local settlements at that cutoff; later calls and uncertain sends
cannot mask external consumption. Only explicit verified per-attempt evidence can
release uncertain charges. Final closed-cycle evidence can reduce external buffers.

Encrypted logical backups now include the ledger. Restore requires an empty target,
removes accounting identity links, recovers stale reservations and places a global
financial hold. Each restored cycle needs a final signed vendor checkpoint with a
coverage cutoff after restoration and no unresolved holds before an explicit
`release_restore_hold` reconciliation can reopen admission. Restoring old academic
data must never restore free capacity. Destructive schema downgrade is forbidden.

Accounting identifiers are HMAC pseudonyms. The ledger has no raw URLs, tokens,
prompts, course titles or content. Account deletion removes identity links without
erasing totals; the worker anonymizes details after 30 days and deletes resolved
attempt detail 90 days after its cycle ends. Unresolved, de-identified holds and
aggregate financial/audit history remain for reconciliation. Operator database,
trust-file and report access must be protected by deployment OS/database roles.

## Pools, tasks and backpressure

Deterministic largest-remainder allocation preserves every usable unit. The example
300,000 allowance with a 5% holdback gives 285,000 usable units and
156,750 / 71,250 / 28,500 / 28,500 targets. Percentages total exactly 100.

Modes are strict pools, nonreserve borrowing (default), and bounded weighted fair
dispatch. Borrowing records the lender allocations and borrower total and preserves
configured lender floors. Only signed server operation allowlists reach reserve.
Workload labels come from trusted MCP routing and scheduled jobs, never tool input.
Optional weighted dispatch rotates owners, weights interactive/sync/exploratory
5/2/1, admits at most one active request per queued owner, and caps queue depth and
waiting time. Its queue is process-local; durable fleet ceilings still govern every
dispatch. Interactive concurrency headroom protects immediate work across workers.

Durable rolling owner minute/hour/day limits, tenant daily units, task attempts,
units, deadlines, body-byte reservations and download-attempt limits bound fan-out.
Job retries inherit the durable job ID; MCP tasks inherit the server request ID.
New prompts do not reset owner limits. Existing workflows retain their additional
document, pagination, byte and output envelopes. Pagination exhaustion retains
partial coverage and its reason code; it does not imply a complete inventory or
promise a scheduled refresh. A remote continuation is offered only by existing
authorized cursor mechanisms; the governor never exposes a raw signed URL.

Technical limits persist token cooldowns, failure counters and active reservations
across processes. A bounded single probe follows an open circuit. Unparseable
headers fall back to conservative pacing. Retry-After is never shortened to fit a
tool deadline. Ordinary permission 403s are never retried; only the explicitly
recognized `Rate Limit Exceeded` error shape is treated as a legacy throttle.
Sequential calls may wait for an existing cooldown of at most three seconds;
they hold no reservation while waiting and recheck authorization and admission
afterward. Longer cooldowns defer the call without shortening the provider delay.
All safe retries require new reservations. Local/offline analysis is not gated by
upstream capacity.

## Cache and source revocation

The bounded in-memory cache supports single-flight reads, explicit TTL and
ETag/Last-Modified revalidation. Keys bind owner, tenant, token, source epoch,
query and recipient. Every waiter, hit and returned value rechecks authorization.
Course withdrawal/invalidation clears entries. Identity, entitlement, permission
probes, metadata downloads and credential operations are never cached.

The initial cache allowlist is assignment details and individual pages. Default TTL
is zero (concurrent single-flight only); a reviewed operator policy can allow up to
60 seconds. TTL reuse is limited to the MCP provenance path. Reused results record
retrieval time, cache origin, response-only coverage and current authorization in
`meta.upstream_cache`; they are not reported as a new live fetch. Existing persisted
academic caches keep their independent authorization, egress and retention gates.

## Restricted operator workflow

Use the executable [JSON template](api-usage-governor.example.json) and
[JSON Schema](api-usage-governor.schema.json). The supplied handoff YAML remains a
conceptual example; the CLI accepts the normalized JSON schema. Unconfigured/null
allowance denies paid production traffic. Mode is operator-owned, not a tool input:

- `offline_synthetic`: finite fictional policy, `.invalid` MockTransport only.
- `authorized_mock_provider`: explicit controlled MockTransport adapter tests only.
- `production_approved`: real guarded transport, configured signed contract and
  independently passing existing approval/source gates.

The shared application database stores activated immutable policy versions.
`BRIDGE_BUDGET_TRUST_FILE` points to an ACL-protected public-key trust file:

```json
{"keys":{"operator-key-id":{"role":"budget_operator","public_key":"BASE64_ED25519_PUBLIC_KEY","expires_at":"2027-01-01T00:00:00Z"}}}
```

Private signing keys are provisioned outside this service. Mutating commands accept
an Ed25519 envelope with `key_id`, `command`, `signature`. Sign canonical JSON
(sorted keys, compact separators, ASCII escaping) of `command`. The command contains
`action` (`apply` or `reconcile`), aware `issued_at`/`expires_at` (at most 24 hours),
`expected_policy` (current policy SHA-256, or null for initial activation), and
`payload` (the policy or `VendorStatement`). Replay, stale expected versions,
modified payloads, expired keys and untrusted roles fail closed. There is no MCP or
browser administration endpoint and no client override argument.

```text
canvas-bridge budget propose --policy candidate.json --allowance 300000
canvas-bridge budget simulate --policy candidate.json --requests 100000
canvas-bridge budget apply --approved-command signed-apply.json
canvas-bridge budget status --provider canvas
canvas-bridge budget reconcile --approved-command signed-statement.json
canvas-bridge budget report --cycle PERIOD_DIGEST --html protected-report.html
```

Propose/simulate never mutate the ledger or contact providers. Simulation is a pure
allocation planner; concurrency assurance comes from executed database tests.
Applying is a separate explicit action and requires signed, complete counting facts,
effective dates, evidence digest, and allowance no greater than signed allowance.
Raising signed allowance requires new evidence. Counting changes require adapter
review; configuration rollback is a **new signed version**, never a ledger reset.
A signed `kill_switch: true` policy disables network admission independently of
capacity. No budget update grants institutional access.

Status/report provide aggregate periods, usable capacity, settled/reserved/uncertain
units, protected pools, lending, operation classes, denials, technical cost, eligible
cache hit rate, deduplicated savings, 7/30-day runway estimates, bounded process-local
admission latency and vendor totals/difference. Unreported spend is **N/A**. Durable
per-cycle threshold events deduplicate alerts. The CLI/report is the local alert
sink; no email, external messaging, monitoring service or schedule is activated.

## Integration inventory and release evidence

`usage/evidence.py` inventories every institutional path and the separately bounded
identity-provider infrastructure exemptions. CI rejects new unreviewed HTTP imports,
unguarded wrappers and unexpected infrastructure exemptions. This supplements the
existing DNS-pinned transport and extension isolation; static analysis alone is not
a hostile-native-code sandbox.

| Specification | Implementation | Synthetic acceptance |
|---|---|---|
| CB-BUDGET-01 | policy, transport, route inventory | unknown terms, authorization order, bound sends |
| CB-BUDGET-02 | ledger, migration, backup/restore | threaded/process races, recovery, idempotence, reconciliation |
| CB-BUDGET-03 | governed transport, technical state, cache | retries/403, coalescing, revocation, conditional requests |
| CB-BUDGET-04 | pools, durable owner/task controls, fair queue | percentage properties, borrowing, reserve denial, owner rotation |
| CB-BUDGET-05 | signed admin workflow, status/report, threshold events | signed updates, replay rejection, simulation, historical invoices |
| CB-BUDGET-06 | evidence inventory and compliance section | source-bound tests; separate PostgreSQL environment gate |

See [executed validation](../evidence/sanitized-results/api-usage-governor-2026-10-29.md).
`compliance-report.api_usage_governance` only reports TESTED with current, passing
source-bound receipts for all governor cases, including PostgreSQL. Missing approvals
remain REQUIRES_EXTERNAL_APPROVAL. Live contract reconciliation, hosted load,
deployment recovery rehearsal and ordinary ChatGPT acceptance retain independent
release gates. No deployment, migration of the private database, real coursework
access, operator key provisioning or commercial activation was performed here.

## Private development accounting — November 3, 2026

The owner explicitly deferred commercial allowance enforcement for private development.
`BRIDGE_PERSONAL_DEVELOPMENT_USAGE=true` selects local request accounting only for an
owner-restricted `personal` profile bound to `127.0.0.1` with MCP read-only enabled.
Hosted, public and synthetic profiles cannot enable this setting. Default remains false.
`BRIDGE_PERSONAL_DEVELOPMENT_MONTHLY_REQUESTS` defaults to 3,000, with a supported maximum
of 2,147,483,647. These are operator limits, not vendor allowances, commercial units, or a
claim of free API access. Local policy records carry `local_request` units and no
signed vendor allowance or fabricated contract evidence.

Technical throttling, per-owner/task limits, durable reservations, uncertain attempts,
monthly ceilings, restore holds, guarded transports, source authorization, external
approval and content/recipient checks remain mandatory. Consumption retains the same
period identity across restarts and local ceiling changes. Existing commercial policies
are not overwritten. Turning the flag off denies stored development policies; returning
to commercial service requires separately configured signed commercial terms.
The setting does not enable Canvas writes, credential recovery, other users, training,
content sharing, or public release. No schema migration is required.


Private operator override (November 3):
`BRIDGE_PERSONAL_DEVELOPMENT_OWNER_REQUEST_LIMIT` optionally sets the same local
minute/hour/day ceiling (1 through 2,147,483,647); absent means the original owner
limits. This owner's private deployment explicitly selects that maximum and the
same nominal monthly development ceiling. Existing accounting, monthly safety
holdback, task/fan-out, concurrency and provider throttling remain. Public/hosted
commercial admission is unchanged. Updating local ceilings never resets attempts.

Personal development permits two concurrent requests per token by default, so
one active chat need not block another. Set
`BRIDGE_PERSONAL_DEVELOPMENT_MAX_CONCURRENCY` from 1 through 4 to tune this private
testing limit. The owner cap accommodates the chosen value; tenant/global caps,
provider Retry-After, request accounting and every authorization check still apply.
This setting is used only with personal development accounting. Hosted/production
defaults are unchanged. Restart the private service to load a changed setting;
existing usage and outstanding reservations are retained.

Personal development allows 24 file-download HTTP attempts per tool call: up to
six transfers with the initial GET and three redirects each. Policy-document
preflight shares this allowance with the requested reading. Every redirect still
counts toward accounting and the overall 40-request, byte, unit and 120-second
task limits. The production default remains six download attempts. A task-limit
error is not a daily usage limit or necessarily a timeout. Restart the private
service to load this policy change; usage history is preserved.

Reader integrity preflight now refreshes membership before policy discovery and
preserves an incomplete refresh's explicit reason (such as OWNER_RATE_LIMITED)
instead of proceeding into a stale-lease error. Integrity-specific collection
fetches detailed instructions only for the requested assessment, and discovers
policy-title documents rather than unrelated scheduled readings. Policy coverage
limits remain explicit; this confers no academic-assistance permission.
