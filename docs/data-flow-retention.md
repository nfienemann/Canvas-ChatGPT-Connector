# Data flow and retention

The enforced budgets, full dependency inventory, deletion controls and migration
limitations are in [Data lifecycle controls](data-lifecycle-controls.md).
`retention_policy.py` supplies the common budgets; the service performs cleanup
at startup and every 60 seconds, the worker also cleans up, and `purge` can run
independently. Expired analysis records are excluded from ordinary repository
reads before a cleanup sweep runs.

| Data | Purpose / recipient | Current handling | Live-release dependency |
|---|---|---|---|
| Issuer/subject hash | Internal principal | Stable scoped hash; never email-based merging | Approved identity provider |
| Canvas access/refresh tokens | Authorized Canvas reads | AES-GCM with principal/connection AAD; key outside DB | Managed secrets, rotation and operator access review |
| Selected courses / normalized assignments | Tool results and planning | Encrypted fields; normalized facts expire in 30 days; inventory ends at disconnect or 90-day connection expiry | Institution and recipient/privacy review |
| Visible grades | Requested own-grade tool | Explicit field allowlist, no unposted fields | Course-policy and visible-value comparisons |
| Canvas page text | Source retrieval/search | Encrypted fields; one-hour expiry; bounded in-memory matching after ownership checks; fresh object check on fetch/search | Full source coverage |
| Downloaded course files | Temporary parser input | Private per-job folder; removed on completion/failure; no public endpoint | Operator disk encryption and host protection |
| Extracted file text | Page-aware retrieval/search | Owner/connection/course scope; 24-hour default maximum cache age; startup and 60-second expiry sweep; fresh metadata/access check; excluded from logical backups | Host-level backup expiry and production fleet quotas |
| Local preferences/progress/plans | Explicit student request | Encrypted, versioned connector-local records; 30 days from explicit save; no Canvas mutation | Pilot UX review |
| Observation snapshots | Changes and bounded continuation | Encrypted; 30-day read exclusion and deletion | Guaranteed deployed scheduler |
| OAuth/browser session state | Authentication | Expiring, scoped, server-side; no tokens in browser storage | Deployed IdP/browser flow proof |
| Logs | Diagnostics | No API access log; sanitized tool-error class | Proxy redaction, 7-day policy and log review |
| Backups | Recovery | Encrypted; 30-day enforced restore window; no credentials, raw document text, sessions or jobs; restored connections inactive | Independent storage, physical expiry and restore exercise |
| Deletion journal / principal generation | Prevent resurrection | Authenticated minimal connection or principal hash, generation and time; obsolete fences pruned after 31 days | Journal must remain independent of DB rollback |
| Calendar / notifications | None in this release | No grants, writes or deliveries | Independent opt-in provider and approval/delivery gates |

Disconnect disables access and purges connection coursework, local records,
materials, snapshots, jobs and credentials. Deletion fences remain. It attempts
remote revocation separately and does not falsely report success on an outage.
Course deselection or detected access loss removes its work and materials,
related progress, and connection-wide snapshots, queued jobs and saved plans.
A conservative restore fence excludes that connection from older backups;
the student must reconnect after such a restore. Remaining selected courses
continue working in the active database.

“Delete all local account data” removes all of the authenticated owner's linked
connections and derived records in one transaction, cancels pending Canvas OAuth
and browser sessions, and signs out. A principal generation fences OAuth exchanges
already in flight; a returned grant cannot create a connection after deletion.
Local removal completes before bounded remote revocation attempts. Unconfirmed
revocation is reported explicitly. Only minimal deletion/generation fences remain.
Restore rejects pre-deletion connections. Any other restored connection remains
inactive, unverified and credential-free; a new explicit linking flow is required.
Physical backup expiry and independent-copy controls still require the actual
operator/privacy arrangement.

The protected JSON export contains retained connection metadata, courses, work,
snapshots, materials with citations, local records and jobs. It excludes
credentials, authentication secrets and other users' data. It uses the current
authenticated owner and an atomic database read; no public download link is created.

Automated fixtures contain no real student data. A separately authorized private
owner-only integration test used actual coursework; no source text or credentials
were committed. No blanket FERPA
certification, universal “never used for training” statement or legal suitability
claim is made. Applicable ChatGPT workspace controls, deployment region, institution
arrangements and privacy policy must be reviewed for the actual service.

Grade auditing adds no persistent grade/audit table or notification job. Visible
scores, configuration, rule candidates, scenario inputs and calculation bases
exist in the request and its returned response. Syllabus documents reuse the
existing material cache and its deletion/expiry behavior; no separate grade cache
or raw-record logging is introduced. Returned grades may remain in the student's
ChatGPT conversation and require that product's own deletion controls.

Semester analysis reuses authorized snapshots and request-local grading/module
evidence. It adds no poller, delivery queue, calendar record or persistent grade
history. Explicit acknowledgments occupy encrypted `semester_state` local records;
only issue/revision hashes are saved. Existing 30-day analysis retention, deletion
and course-withdrawal rules apply. User-approved semester preferences use the separate
independent preference record, with legacy connection preferences as a fallback.
A notification preference is not a schedule. Future delivery integration must stop
when opt-in or retained deduplication history expires and revalidate authorization
before every approved run. See [the semester contract](semester-intelligence.md).
