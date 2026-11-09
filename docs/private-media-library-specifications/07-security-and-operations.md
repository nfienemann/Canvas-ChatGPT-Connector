# Security and operations

## Threats and required controls

| Threat | Required control | Acceptance |
|---|---|---|
| Cross-user ID/object/cursor guessing | Owner-qualified lookups and child constraints, private object access, indistinguishable safe denial | AT-02, AT-22 |
| Model-forged upload consent | Authenticated concrete selection receipt; no boolean approval bypass | AT-07, AT-08 |
| Host URL SSRF or credentials leakage | Narrow adapter allowlist, validated/pinned public destinations, redirect checks, isolated ingress transport | AT-09 |
| Oversized/lying uploads and concurrent quota race | Streamed actual-byte limits, atomic reservations and publish accounting | AT-04, AT-10 |
| Parser exploit, archive bomb, traversal | Signature/structure validation, bounded sandbox, no network/credentials, rejection before publication | AT-11, AT-12 |
| Malicious source instructions | Content-data boundary and purpose-specific tools; no source-driven grants or actions | AT-24 |
| Restricted bytes relabeled independent | Retained origin/dependencies/fingerprints; immutable provenance; no name-based permission changes | AT-23 |
| Revocation during search/render/download | Generation/permission checks at commit and release; bounded stream checks | AT-18, AT-19 |
| Restoring deleted content | Independent durable tombstone journal, source/owner/checksum reconciliation, recovery hold on uncertainty | AT-20 |
| Signed URL or private content in logs | Field allowlist, URL/credential redaction and exception-path tests | AT-25 |
| Duplicate callbacks/retries and split-brain workers | Unique idempotency constraints, leases, deterministic commit records | AT-05, AT-31 |
| Inline active content or public preview leak | Sandboxed safe image/attachment delivery, fixed MIME/disposition, private cache headers | AT-12, AT-17 |

## Operational behavior

Ingress and processing have separate queues and budgets. A slow parser must not hold an upload request indefinitely or block metadata reads. Use durable job leases with bounded exponential backoff. Safe transient failures can retry at most three times; stale permission, unsafe file or unsupported type does not auto-retry. After a worker crash, reconcile staging objects, committed metadata and reservations before rerunning work. Retried publication must yield the same receipt.

Define configurable ingress wall-clock and idle deadlines; initial defaults are 15 minutes per intake transfer and 60 seconds without progress. Session/intake expiry must be shown to the client. Processing timeouts preserve the original and report a failed/partial representation when safe, with a retry action that does not broaden permissions. Scanner outages hold publication in quarantine; storage outages do not produce available items.

Reconcile object inventory against metadata at least daily without exposing a general inventory tool to the model. Quarantine orphans expire within 24 hours. Unknown objects are not adopted into a user's library based on filenames. Alert operators on unreconciled quota drift, purge backlog, repeated checksum failures, unavailable keys or failed backup verification; exclude source content from alerts.

Track aggregate upload success/failure, time to receipt, processing completion, queue wait, bytes/quota, denied attempts, purge deadlines and restore verification. Log only opaque correlation/job identifiers, safe reason categories, counts and timings. Restrict operator access and audit any break-glass content access through the deployment's existing controls. A library must not create a hidden browsing interface for operators.

## Performance acceptance targets

For an explicitly documented reference deployment and synthetic dataset of 1,000 items per owner: metadata/list p95 <=2 seconds; indexed text search p95 <=3 seconds; finalization acknowledgement p95 <=2 seconds after validation completes. Upload throughput depends on client network and must report byte progress. Do not advertise an end-to-end parsing time before measurements exist. Record concurrency, corpus sizes, exclusions and sample counts with every result.

Load acceptance includes two users uploading near quota concurrently, a slow client, retry storms, worker crash, object-store failure and deletion while processing. No throughput score can compensate for an isolation or deletion failure. Hosted PostgreSQL and object-store tests are separate from local SQLite/filesystem tests.

## Budget and service ownership

An operator owns storage, egress, backup, scanner, compute and incident costs. No mandatory student LLM API key or separate paid student tier is introduced. Apply deployment-wide admission limits before accepting unfunded work. A full service returns quota/capacity information; it does not discard originals or silently transfer them to a third party. External processing remains optional and disabled until recipient policy, funding and acceptance are established.

Institutional acquisition, downstream privacy, platform distribution and public release remain separate project gates. This specification preserves those boundaries without treating the independent library as dependent on an LMS connection. It does not certify legal rights or platform approval.
