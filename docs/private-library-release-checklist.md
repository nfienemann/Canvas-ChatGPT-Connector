# Private library: local completion and release blockers

Status: November 3, 2026. This is the canonical follow-up checklist for the October
29 specification package. Implementation stays default-off. Local implementation,
local evidence, installed-service activation and public release are separate states.
The attached specifications supplied requirements; they did not authorize deployment
or changes to personal databases, credentials, institutional settings or retention.

## Completed locally

- Durable encrypted originals, immutable versions, independently encrypted SQL
  metadata, verified owner/session identity, explicit storage/processing/recipient
  choices, zero-LMS use and the existing independent study/read/search adapters.
- Authenticated browser selection, byte progress, durable per-file receipts,
  offset reconciliation, cancellation, replacement, metadata/collection/tag filters,
  original downloads, export, revocation and deletion. Errors and completed actions
  have text status and keyboard focus; failed extraction can be retried with its
  existing permission revision, without granting additional rights.
- Structural validation and bounded OS worker integration; flat ZIP member checks,
  archive expansion limits and symlink/collision/active-carrier rejection. A scanner
  outage keeps bytes quarantined. Original retention does not depend on extraction.
- Shared database admission for quota and operation leases: four ingress requests
  per owner/sixteen per deployment, one export per owner/two per deployment, and
  bounded aggregate export memory. Derivatives have owner and deployment budgets.
  Existing heavy processing leases remain one per owner/two per deployment.
- Optional managed encrypted backups in a separate private directory: aggregate
  capacity admission, authenticated manifest/part verification and physical expiry
  after thirty days. An unavailable directory leaves receipts pending and does not
  get recreated by health checks. Manual backup paths remain operator-managed.
- Content-free daily counters and operator diagnostics for quota drift, processing
  queues/failures, checksum failures, deletion backlog, restore hold and backup
  verification. Lease/metric/orphan/backup cleanup uses the retention worker or
  `library-maintain`; no content-browsing operator/model tool was added.
- Additive SQLite migrations and protective downgrade refusal; isolated restore
  requires the current independent deletion journal and restores neither sessions
  nor recipient/processing grants. Fault tests cover write-before-commit retries,
  duplicate workers, purge failure, corrupt/expired backups and lost recovery keys.
- A reproducible 1,000-item local benchmark meets the specified p95 targets. A
  PostgreSQL acceptance test is checked in and explicitly skips without a disposable
  PostgreSQL database. No skipped test is recorded as a pass.

See the [implementation/operations guide](private-media-library.md),
[local completion evidence](../evidence/sanitized-results/private-library-local-completion-2026-11-03.md),
[acceptance ledger](../evidence/sanitized-results/private-library/acceptance.csv) and
[reference load results](../evidence/sanitized-results/private-library/local-load-2026-11-03.json).
The original specification package and its proposed schemas remain unchanged;
contract extensions are documented in the implementation guide.

## Blockers that need an environment or external access

| Gate | Missing prerequisite | Required evidence before closing |
| --- | --- | --- |
| PostgreSQL multiworker acceptance | A disposable PostgreSQL service; `TEST_DATABASE_URL` must never point at personal/production data. | Run `tests/test_library_postgres.py`, existing PostgreSQL tests and database-upgrade PostgreSQL tests. Exercise independent workers, owner constraints, migrations, rollback refusal, deletion and restore on that service. |
| Hosted object storage | Decide the provider, private bucket/account, encryption/key service, credentials and lifecycle policy. The local adapter and storage interface exist; a vendor-specific bucket adapter is still implementation work after that decision. | Implement conditional publication/private reads/delete/inventory/backup operations; test multiworker races, denied public access, outages, checksum corruption, orphan removal, versioned-object deletion and recovery against the chosen service. Local filesystem results cannot close this gate. |
| Hosted operation and recovery | A reference host, HTTPS/origin/proxy limits, persistent volumes, key custody, worker supervision, backup schedule and alert destination. | Repeat load/isolation/slow-client/retry/crash/deletion tests; rehearse loss and recovery of the actual metadata/object/key/journal set; verify physical backup expiry and failure alerts. No infrastructure, notification destination or scheduled backup was provisioned by this task. |
| Actual ChatGPT/Claude fallback and later-chat use | Access to each exact signed-in client/surface/version with a configured Bridge integration and reachable authorized HTTPS service. | Record visible upload receipt, unsupported-native fallback, disconnect/restart and later-chat retrieval, owner download/save, and model-visible pixels where claimed. Tool schemas, local HTTP/MCP and generated image bytes do not establish host behavior. |
| Human accessibility acceptance | A tester using the supported browser and assistive technology, such as NVDA or VoiceOver. Hosting is not inherently required. | Verify announcements, focus/order, error recovery, cancellation, all file-management actions and small-screen zoom. Automated labels, keyboard actions and mobile screenshots are local evidence only. |
| Supported platform/converter acceptance | The actual Linux/container/Windows deployment configuration and optional converter/OCR dependencies being advertised. | Run OS sandbox and format-specific conversion/visual checks there. Windows structural-worker evidence does not certify every renderer or Linux deployment. |
| Release approvals | Applicable platform distribution, institutional acquisition and independent deployment/privacy approvals. | Close the corresponding project release gates separately. Library implementation and possession of a file do not confer these approvals. |

## Explicit future slices, not hidden L1 blockers

**L2 native host intake remains unimplemented and disabled.** It needs a documented
supported host handoff, exact domain/recipient policy and real-client fixtures before
an adapter can safely accept file references. Then implement and test explicit
selection, preexisting file, expiry, redirects/public-address pinning, credential
isolation, deduplication and new-chat behavior. `submit_library_files` is absent;
there is no arbitrary-URL acquisition fallback. Browser upload is the working L1 path.

**L3 audio/video and broader/nested archives remain unimplemented and disabled.**
They are separately scoped development: codec/duration/size bounds, safe range
streaming, optional transcript/frame extraction, recipient controls, processing/cost
budgets and synthetic acceptance. Hosting alone will not complete them. Nested
course-export import also needs a reviewed manifest/provenance mapping.

## Resuming after the deployment delay

1. Read this checklist and the current ledgers; rehash the build being tested.
2. Keep library writes disabled until the selected environment is configured. Use
   disposable data for migration and rollback/recovery rehearsals first.
3. Select and implement the hosted storage adapter if required. Run the PostgreSQL,
   object-store and actual-host checks separately and record exact versions/results.
4. Configure monitoring and scheduled maintenance/backup verification, then verify
   them under deliberate storage/key/purge failures. `library-health` provides safe
   aggregate JSON; the operator's monitor must inspect its `state` and `alerts`.
5. Complete assistive-technology and exact-client evidence. Enable L1 only when its
   non-compensating gates pass; L2/L3 stay off until their own evidence exists.

Local tests cover named fault/attack cases, not every possible exploit, crash point,
malware family or hardware failure. They are not a public deployment certification.
No personal service was restarted or activated and no private database was migrated
as part of this implementation.
