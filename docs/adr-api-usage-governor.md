# ADR — Independent authorization, technical and commercial admission

Status: accepted for synthetic implementation, external activation gated.

Use one provider-neutral durable governor at the existing guarded HTTP boundary.
Keep authorization first. Count each actual attempt, including redirects and retries;
never equate MCP calls or Canvas technical cost headers with commercial transactions.
Missing commercial terms deny live sends. Synthetic fixtures use a separate finite
fictional contract and cannot select a real network transport.

Use a single database lock order for financial and technical ceilings. PostgreSQL
row locking supports multiple workers; SQLite immediate transactions support isolated
local fixtures. This favors inspectable conservation over high-throughput sharding.
Load measurements must precede any move to finer-grained locking. Waiting queues
and cache coalescing are bounded process-local optimizations, never the accounting
source of truth. No transaction lock spans network I/O.

Use soft workload percentages, recorded nonreserve borrowing, protected reserve and
rolling owner/task limits rather than per-field budgets or permanent student shares.
Retain uncertain sent charges and reject duplicate send permits. Quarantine cost
exceptions. Vendor statements remain distinct from local estimates and must account
for reporting cutoffs. Signed operator updates and append-only adjustments do not
change source permissions. Paid overages are unsupported and disabled.

Restore financial history with a global hold and require verified reconciliation
before reopening access. Account deletion removes pseudonymous accounting links but
cannot mint capacity. Raw academic content and credentials never enter the ledger.

Consequences: a ledger outage or unknown billing model blocks upstream refresh;
independently authorized local analysis remains available. The guarantee is a local
admission ceiling, not an invoice guarantee about external clients or unverified
vendor counting. Future production acceptance requires the separate existing gates.
