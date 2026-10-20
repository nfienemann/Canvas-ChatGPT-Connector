# Data flow and retention

| Data | Purpose / recipient | Current handling | Live-release dependency |
|---|---|---|---|
| Issuer/subject hash | Internal principal | Stable scoped hash; never email-based merging | Approved identity provider |
| Canvas access/refresh tokens | Authorized Canvas reads | AES-GCM with principal/connection AAD; key outside DB | Managed secrets, rotation and operator access review |
| Selected courses / normalized assignments | Tool results and planning | Field allowlist; no raw response archive or peer roster | Institution and recipient/privacy review |
| Visible grades | Requested own-grade tool | Explicit field allowlist, no unposted fields | Course-policy and visible-value comparisons |
| Canvas page text | Source retrieval/search | Scoped index; version hash; fresh object check on fetch/search | Reviewed retention and full source coverage |
| Local preferences/progress/plans | Explicit student request | Versioned connector-local records; no Canvas mutation | Tested consent UX and retention choice |
| Observation snapshots | Changes and bounded continuation | 30-day purge via worker/CLI | Guaranteed deployed scheduler |
| OAuth/browser session state | Authentication | Expiring, scoped, server-side; no tokens in browser storage | Deployed IdP/browser flow proof |
| Logs | Diagnostics | No API access log; sanitized tool-error class | Proxy redaction, 7-day policy and log review |
| Backups | Recovery | Encrypted logical backup, separate deletion fences | Independent storage, <=30-day expiry and restore exercise |
| Deletion journal / principal generation | Prevent resurrection | Authenticated minimal connection or principal hash, generation and time | Separate durable retention policy |
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
Restore rejects pre-deletion connections, while a new explicit post-deletion
connection can be restored. Deployed backup expiry and independent-copy controls
still require the actual operator/privacy arrangement.

The protected JSON export contains retained connection metadata, courses, work,
snapshots, materials with citations, local records and jobs. It excludes
credentials, authentication secrets and other users' data. It uses the current
authenticated owner and an atomic database read; no public download link is created.

No real student data was used for this development release. No blanket FERPA
certification, universal “never used for training” statement or legal suitability
claim is made. Applicable ChatGPT workspace controls, deployment region, institution
arrangements and privacy policy must be reviewed for the actual service.
