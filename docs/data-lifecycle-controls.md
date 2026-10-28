# Data lifecycle, retention and deletion

Implemented controls apply to the local service and its supported logical backup
format. They do not establish provider/institution approval or certify a host's
disk, logging, backup or downstream service configuration. All validation uses
fictional records. No private database or credentials were migrated during this work.

## Central policies

`src/canvas_bridge/retention_policy.py` defines enforcement budgets.
`Retention.RULES` supplies the purpose, expiry and deletion descriptions displayed
in authenticated Settings. These are deliberately different lifetimes:

| Class | Purpose | Default / expiration condition | Deletion strategy |
|---|---|---|---|
| Authentication credentials | Identity-bound provider/application access | Provider token expiry/revocation; browser/JWT at most one hour; OAuth transaction expiry; connection hard maximum 90 days | Remove encrypted credentials and expired sessions; local disable precedes remote revocation; remote failure remains `not_confirmed` |
| Active connection configuration | Institution mapping, source inventory and explicit course selection | 90 days from connection creation, without automatic extension; disconnect earlier | Purge course/material inventory, academic records, jobs and secrets; retain disabled connection metadata only for the 31-day restoration fence |
| Temporary processing artifacts | Isolated parsing/rendering and exact original delivery | Completion/failure; orphan cleanup after 600 seconds; original delivery 300 seconds by default (configured maximum 900); converted PDFs 600 seconds | Kill bounded workers, delete leased job directories and AppContainer profiles, invalidate grants, destroy per-download memory keys, drop memory caches |
| Sanitized analysis results | Continuations, comparisons and saved preferences/plans/progress | 30 days from observation or explicit save | Read exclusion before periodic deletion; no access-based extension |
| Restricted raw records | Current own-course facts and document analysis | Normalized own-work facts 30 days; extracted file text at most 24 hours (operator can shorten); page text one hour; source metadata limited by connection lifetime | Delete expired facts; clear text/locators/derived file state; exclude all document text from backups; no raw upstream JSON archive |
| Operational diagnostics | Fixed reason codes and deletion verification | Process-local deletion receipts seven days; external log sinks must enforce at most seven days | Expire receipts; no source payload, credential, owner or connection identifier in completion log events; host/operator controls log disposal |
| Authorization evidence / restoration fences | Enforce actual approvals and prevent deleted data returning | Signed approval expiry bounds use. Evidence custodian must record a disposal date or a documented continuing obligation at expiry; default disposal is within 31 days of expiry absent that obligation. Restoration fences: 31 days, exceeding the maximum backup window | Service cannot edit administrator evidence; custodian disposes encrypted correspondence and records under its recorded schedule. Service authenticates and compacts its own obsolete deletion journal and removes obsolete DB fences |

Approval evidence is outside the student's deletion authority and outside service
write access. Its custodian's disposal procedure is a release gate, not a promise
of automatic removal by this service. A documented continuing obligation must
have an explicit review/expiration date; indefinite storage is not the default.

An expired connection cannot retrieve data even before cleanup. Renewing it
requires a new explicit connection and independent approval/identity checks.
The 30-day analysis window supports recent workload comparisons and saved study
state; the 90-day connection ceiling bounds abandoned credentials/configuration.
Minute-scale file lifetimes cover transfer/conversion retries, while the shorter
page and file-text windows support immediate analysis. These are implementation
defaults with distinct operational purposes, not statutory retention claims.
Cleanup occurs at API startup and every 60 seconds while running, in the job
worker, and through `canvas-bridge purge`. Failed periodic cleanup emits a fixed
error type and is retried; it is not reported as completed. No process can unlink
files while the machine/service is stopped: startup recovers expired artifacts.

## Storage inventory, including dependencies

| Location / content | Protection and scope | Lifetime / disposal |
|---|---|---|
| Application DB: connection identity/timezone, course names/provider IDs, work payloads, snapshots, local study records, material titles/URLs/text/locators/state, job payloads, browser CSRF | AES-GCM field envelopes using the existing vault; engine-local key; table/column authentication context; owner/connection/course predicates remain mandatory | Policies above; encrypted values are not plaintext SQL search keys |
| DB lookup metadata: opaque IDs, owner hashes, institution keys, relationships, state, versions, counts and timestamps | Pseudonymous metadata remains queryable; restricted DB account and encrypted host volume still required | Parent lifetime, or bounded restoration-fence lifetime |
| Token store: connection credential, pending OAuth payload, browser credential | Existing AES-GCM with principal/connection binding; no second identity or token store | Expiry, disconnection, session termination; never included in logical backup |
| Vault key / private operator credentials | New Windows vault keys use current-account DPAPI; existing 32-byte keys remain supported without rewriting them. Linux/container keys remain separately mounted private secrets | Operator-managed rotation/recovery lifecycle; never placed in DB, academic cache, MCP output or backup. Removing one account does not destroy the shared service key |
| Original download staging: configured root or vault-parent/original-delivery | Private directory and exclusive process lock; authenticated chunks; per-object key only in process memory; quota includes encryption overhead | TTL/revocation/close/startup orphan removal. A crash loses the decryption keys. A held Windows file handle can delay unlink; report cleanup pending |
| PDF/PPTX derivative cache | Owner/connection/epoch/version bound memory cache only; at most four PDFs / 40 MB | Ten minutes, eviction, scope change, disconnect or process exit |
| Temporary PNGs, render results, extracted response windows, grade calculations | Request memory; no image dump/cache by the service | Request completion. Returned bytes/citations belong to the recipient's lifecycle thereafter |
| Parser/converter/OCR jobs: input.bin, request/result JSON, input PDF, subset PPTX, rendered images, LibreOffice profile/output | Private parser-root/jobs/document-* directory, OS sandbox and lease. Raw working files must be plaintext for the isolated native libraries; require encrypted host storage. Linux HOME/TMPDIR/XDG_CACHE_HOME and Windows TEMP/TMP use the job directory | Completion/error/cancellation removal; 600-second orphan threshold; active OS leases are skipped, never deleted out from under a worker |
| Windows AppContainer profile created by dependencies | Profile name derived from the private job path; native worker has no network capability or secrets | Normal native finally plus job/orphan cleanup retries DeleteAppContainerProfile; failed cleanup remains pending |
| Python/PDFium/Pillow/Office ZIP/XML/OCR dependency memory and temporary files | Worker stdout/stderr discarded, bounded output files validated; resource limits. Runtime packages are read-only and contain no per-student input | Working artifacts remain inside job directory; runtime/package caches are code, not coursework. A host-created crash dump is an external host artifact |
| Pseudonymization / identity mapping | No reverse-map table or persistent per-request pseudonym dictionary. Deterministic opaque references and issuer/subject hashes occur in scoped DB rows; privacy filtering is request-local | Row/fence lifetime. Process locks for removed connections are retired by cleanup; worker cancellation entries are bounded by the fence window |
| Temporary download URLs and review receipts | Random capabilities/digests in memory only for synthetic download handoff; live downloads authenticate recipient; encrypted review receipts bind scope/epoch | Existing TTL and per-request authorization; deletion invalidates epoch, cache and links; URLs in a user's history are outside service control |
| Operational logs and receipt memory | No application academic dump files; SQL parameter logging hidden; API access logging disabled; callback/token paths filtered | Seven-day receipt expiry. Proxy, process manager, Windows Event Log and container stdout are separately operated sinks requiring seven-day policy and redaction |
| Logical backups at operator-chosen paths | AES-GCM encrypted entire file, new-file-only, private permissions; signed-content expiry validated at restore | 30-day restore window; no sessions, jobs, credentials or raw document text. Operator removes physical copies within policy; CLI does not recursively delete arbitrary backup directories |
| SQLite pages/journals; PostgreSQL heap/WAL/temp files; filesystem snapshots; immutable backups; swap/hibernation/crash reports | Outside field-level logical deletion guarantees. Encryption at rest, restricted service identity, disabled sensitive crash dumps, bounded host backup/log policy required | Managed by storage operator; deletion from a table does not prove immediate physical erasure |
| Signed approval bundles, trusted public keys and encrypted correspondence | Separate private administrator paths; no correspondence through MCP; no ordinary-user self-certification | Explicit evidence policy above; not included in service logical backup |
| Source Canvas, ChatGPT, browser downloads/exports, independent calendar events | Controlled by their respective services/users | Bridge cannot erase these copies; use each controller's deletion operation |

Per-request and per-process memory cleanup releases references; it does not promise
forensic RAM zeroization. Libraries and operating systems can retain memory pages.
Raw worker files are the deliberately bounded exception to field/file encryption,
so an encrypted, protected processing volume is required before a real-data pilot.
Disable Windows LocalDumps/WER heap dumps and host debugger dumps for the service;
Linux workers set core limit zero. Application code does not override an
administrator's dump or backup configuration. Review those controls on the actual
deployment instead of treating a development flag as evidence.

## User controls and revocation

Authenticated **Settings → Stored data and deletion** lists connected sources,
connection expiration, database category counts, policy lifetimes and external
limitations. Counts include physically retained expired rows awaiting cleanup.

* **Delete local caches** removes document caches, download grants, derivative
  images/PDFs, normalized work, snapshots and queued jobs. Selection and saved
  study records remain.
* **Delete retained academic records** also removes saved preferences/plans/progress
  and course selection. The provider connection remains, and future explicitly
  authorized retrieval may create new records.
* **Disconnect and delete** disables retrieval, removes credentials and active
  records, and separately attempts upstream revocation.
* **Delete all local account data** applies deletion to all institutions and
  terminates application/browser/pending OAuth sessions.

Sensitive cache/record deletion requires an explicit confirmation checkbox, a
current authenticated application session, same-origin request, CSRF validation,
settings scope and an owner-bound connection under the existing generation/row
locks. Disconnect/account deletion retain their existing explicit settings flows.
There is no MCP deletion tool or generic SQL/file deletion capability.

A deletion fence is durably written before DB removal. The transaction increments
the connection epoch and removes rows; then it invalidates file keys/grants,
derivatives and worker cancellation tokens. Native workers check cancellation
during bounded waits. Cancellation and pending-artifact accounting also include
the service instance, so separate instances cannot cancel or count one another's
workers merely because their fixture or connection identifiers match. Separate
service processes reject stale epochs before
publishing results; their workers may finish within their existing time budget.
Deletion cannot retract bytes already delivered to another service.

Receipts report deleted row counts, pending temporary cleanup, and downstream/
physical-erasure limitations. Pending cleanup is not called completed. Minimal
completion log events contain only operation and pending count. Network failure
never means upstream revocation succeeded. The account can retry/disconnect or
revoke with the provider directly when the remote result is `not_confirmed`.

## Upgrade, backup and restore

Migration `c7d9130b42ae` encrypts existing academic fields with the existing vault.
Run it with the service/workers stopped and the correct vault key available
(`BRIDGE_VAULT_KEY_FILE`, or the programmatic migrate key-file argument). First
exercise a synthetic canary and the deployment's normal recovery procedure.
An empty fixture DB needs no key during migration; populated data does. Missing
keys/plaintext rows fail closed. Downgrade to plaintext is deliberately blocked.
Field encryption does not retrospectively erase old disk blocks or older backups.

New Windows DPAPI keys are bound to the Windows account and machine secret store.
They are not portable Linux container secrets; existing deployments keep their
existing key. The operator must arrange tested account/machine recovery or a
managed secret store before relying on DPAPI across host loss.

Logical backup format 2 includes authenticated creation and expiry dates. Restore
rejects format 1, future-dated, overlong and expired backups, missing/tampered
journals, or a nonempty target. It reapplies the original per-record expiry dates;
restore is not a fresh retention clock. Every restored connection is inactive,
unverified and credential-free, regardless of journal state; no jobs resume.
Deletion fences exclude affected connections and all their dependent records.

The journal must live independently of database rollback, with independently
protected copies. Compaction verifies every entry before removing fences older
than 31 days, after all eligible pre-deletion backups have expired. A damaged
journal blocks restoration. A database filesystem restore outside this command
is not a supported activation path: keep the service stopped, remove credentials,
apply the independently current fences, and validate before any linking.
Logical backups omit DB principal/tombstone copies too; restoration fences come
from the independently current journal instead of a rolled-back database copy.

Physical backup copies and immutable storage may remain after local deletion.
The service reports that limitation and cannot guarantee immediate physical
erasure. Operators must set actual object/version/WAL/snapshot expiry and verify
host-loss recovery. No real-data deployment or backup restore was performed here.

## Verification

`tests/test_retention.py` uses injected clocks and synthetic data for encrypted
field migration/roundtrips, cross-key isolation, secret-cache rejection, exact
expiry boundaries, confirmed owner-only deletion, interrupted/orphan worker
cleanup, failed-cleanup retries, active-download revocation, authenticated blob
integrity, Windows key protection and expired/inactive/fenced backup restoration.
Existing original-file tests cover expired links, concurrency and error paths;
existing authorization, egress and identity suites remain release prerequisites.
PostgreSQL and Linux isolation require their separate environment-specific jobs.
