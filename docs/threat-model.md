# Threat model

Review: 2026-10-25, local implementation and synthetic tests. Deployment,
institution/provider approvals and independent penetration testing remain separate
release gates. Attacker capabilities include malicious documents, arbitrary MCP
arguments, stolen application credentials, compromised upstream responses,
hostile redirects/DNS, concurrent clients and compromised dependency artifacts.

## Surface inventory

| Surface | Entry points and trust boundary | Controls / residual responsibility |
|---|---|---|
| Public HTTP | `/mcp`, OAuth protected-resource discovery, `/health`, `/ready` | SDK host/origin validation, 128 KB MCP request ceiling, global admission, JWT issuer/audience/scope checks; readiness reveals only availability. Edge TLS, connection/read deadlines, DDoS protection and proxy log redaction remain operator responsibilities |
| Browser authentication/settings | `/settings`, `/settings/login`, `/settings/callback` and issuer-specific variant; `/settings/canvas/callback` and variant | Separate application/upstream OAuth, state/browser binding, exact redirect, configured PKCE capabilities, encrypted expiring sessions; no credentials in access logs |
| Browser mutations | `/settings/demo` (synthetic only), `/select`, `/link`, `/sign-out`, `/disconnect`, `/export`, `/delete-caches`, `/delete-records`, `/delete-account` under `/settings` | Authenticated settings session, CSRF and origin validation; sensitive deletions require the user's confirmation; `/settings/storage` and `/privacy` describe retention. None are unrestricted MCP delete tools |
| File delivery | `/course-file-download/{capability}`, `/course-file-original/{delivery_id}` | Bound owner/connection/epoch, expiring capability/receipt, private encrypted staged bytes, fresh identity and policy checks; live bearer-link delivery is denied. No arbitrary URL fetch route |
| MCP tools/resources | Registered functions in `app.py`; categories and offline set in `policy_surfaces.py`; static page/download widgets | Authenticated principal admission, argument validation, separate upstream/tenant/user/sharing checks, final egress/privacy serializer fences. No tool can administer approvals, expose tokens, access rosters or issue Canvas writes |
| Canvas REST | Typed GET `Endpoint` enum: self profile/enrollments, selected courses, assignments, assignment groups, modules/items, pages, quizzes, files, announcements, discussions and calendar | Explicit route/query and course scope; own-user minimization; bounded pagination; no account/user enumeration or arbitrary HTTP endpoint |
| Identity infrastructure | Exact configured JWKS, OAuth token and revocation endpoints | `infrastructure_http` exact method/URL permit, bounded reads, standard TLS and public-address transport; upstream credentials cannot substitute for MCP identity |
| File origins/CDNs | Fresh course-qualified metadata URL plus individually validated redirect destinations | Reviewed exact HTTPS origins/file-ID hostname templates; no implicit approval from redirects, DNS results or successful HTTP; initial Canvas hop alone receives bearer credentials |
| Outbound network | `PublicTransport` → public DNS-pinned numeric IP, original TLS hostname | All production clients share concurrency, token buckets, cooldowns and circuits; reject private/mixed DNS answers, mapped IPs and non-443 ports; no environment proxy or automatic redirects |
| Workers | Text/OOXML/PDF, rasterization/OCR, selected-slide LibreOfficeKit and bounded EMF conversion | Separate AppContainer or Landlock/seccomp worker; one-process/CPU/memory/wall/output limits, private leased job directory, no credentials/network/process spawning; unsupported isolation fails closed |
| Persistence | SQL database, vault/key material, file-text cache, ephemeral encrypted originals, in-memory derivatives, worker files, deletion journal, backups | Owner/tenant isolation, encrypted sensitive records, central retention, revocation fencing, explicit deletion; see [storage inventory](data-lifecycle-controls.md) |
| Dependencies/builds | `uv.lock`, Node lockfile, Python/Tk/native PDFium/Pillow/OCR/LibreOffice runtimes, base image, actions and build tools | Pinned critical packages/scanners/image digests, lock/source/hash checks, secret history scan, license screening, static/vulnerability/config scans, Python+Node SBOM; native OS inventory requires image/platform gates |
| Host integration | CLI, local desktop launcher, service/worker supervisor, PostgreSQL, Windows ACL/AppContainer/Job Objects, Linux filesystem/syscall filters, optional runtime folders | Synthetic host binds loopback only; Uvicorn disables access logs/proxy headers and bounds connections. Database, secret mounts and runtime folders stay private; no public local admin service or shared desktop client secret |

The authoritative endpoint inventory is executable code, not this prose alone.
New routes/tools/providers must update the inventory, threat tests and release
gates before external use. Source text, document metadata, filenames, images and
model-produced instructions are all data; they cannot grant permissions or alter
the configured provider/tenant/recipient, host access or signed approval records.

## Resource and network budgets

Production HTTP clients share a per-event-loop limiter: 16 active outbound
requests total, four per approved hostname, burst 40 and refill five requests
per second per hostname. A streaming response retains its slot until closed;
cancellation, failure and timeout release it exactly once. No unbounded queue is
created. Up to 1,024 keys are retained; idle entries expire after an hour, while
active work and provider cooldowns cannot be evicted to reset a limit.

`Retry-After` seconds and HTTP dates retain their full delay across clients and
retries. Long delays return a safe unavailable result rather than sleeping inside
an interactive request or retrying early. Exhausted provider rate headers impose
a cooldown. Five sustained transport/server/rate failures open the circuit for
at least 30 seconds, followed by one recovery probe. An older concurrent success
cannot reset a newer failure. Authorization errors never trigger fallback routes
or credential switching. Existing retry counts stay bounded at three, with
exponential backoff and jitter for short retriable failures.

All HTTP routes share 32 active slots, burst 120 and refill 20 requests per second;
forwarded headers and model-supplied identifiers cannot allocate extra buckets.
Authenticated MCP work additionally allows 16 active operations globally/four per
verified principal, burst 120 and refill five per second. Uvicorn limits active
connections/tasks to 64, backlog to 64 and idle keep-alive to five seconds. A
240-second application deadline also bounds slow request bodies/handlers;
outbound headers have a 15-second total deadline and body streams a 90-second
total deadline, in addition to the existing shorter operation/inactivity limits.
API compression is refused before body iteration to avoid decompression bombs.

These are process-local safety ceilings, not performance guarantees or fleet-wide
tenant quotas. Hosted replicas require coordinated ingress/tenant limits and a
review of aggregate provider budgets before scale-out. Synthetic/offline data
uses MockTransport and never reaches the production network limiter or real DNS.
Identity and policy checks remain authoritative before any admission/send and
again before returned data is released; limiter state never caches approval.

Document budgets remain in their existing workers: source/expanded ZIP/member
and XML limits, media pixel limits, path/relationship checks, CPU/memory/output
limits and kill-on-timeout. Fresh metadata/source hashes and serialized file locks
avoid duplicate parsing; weak lock entries cannot be removed between queued
waiters. Limits for native PPTX/EMF/OCR paths remain independent and are not
weakened when conversion fails.

Assets: per-student credentials, academic facts, derived text, saved preferences,
OAuth sessions, job/action state, deletion history and encrypted backups.
Trust boundaries: MCP host → resource server; browser → settings; service →
institution; API/worker → database; key mount → vault; restored backup → deletion
journal. No course text is an instruction source.

| Threat | Implemented control | Verification / remaining boundary |
|---|---|---|
| Wrong user, school or guessed object ID | Issuer+subject principal; owner+connection filters; canonical course-qualified IDs | Synthetic and PostgreSQL isolation tests; real multi-school proof pending |
| Token substitution / expired issuer key | RS256-only pinned configured JWKS, exact issuer/audience/expiry/subject/scopes, bounded key cache | Invalid-token and expired-cache tests |
| Private token proof becomes multi-user access | Personal-profile subject allowlist, operator-only hidden entry, verified expected Canvas ID, private registry status rejected in hosted mode | Fixture HTTP, other-user JWT rejection, duplicate/deletion races and private owner first read; institutional approval remains pending |
| Login CSRF / replay / refresh race | Browser-bound expiring one-use state; exact redirects; PKCE settings flow; database refresh lease | State and refresh race fixtures; private external IdP login and short ChatGPT renewal proof; long-duration/revocation proof pending |
| Identity-provider mix-up | Exact response issuer by default; provider-specific callback fallback; encrypted transaction binds issuer, endpoints, client, resource and callback mode | HTTP fixtures reject wrong/missing/duplicate issuer, wrong callback, replay, browser mismatch and changed configuration before code exchange |
| Powerful Canvas credential | Typed GET allowlist, student enrollment check, exclusion of staff/mixed-role courses, own-user response filtering | No roster/write route; staff-power fixture |
| Misleading or leaked grade calculation | Own-user and assignment identity, valid posted timestamp, visible-field allowlist, hidden-total refusal, summary/detail comparison, source-version-bound review, pure Decimal arithmetic | Grading regressions cover foreign/unposted scores, uncertainty, policy conflicts and withdrawal races; no independent institutional policy verification |
| SSRF or malicious continuation | HTTPS origin checks, unchanged route/query, public-IP DNS pinning, no API redirects | Private/mapped IP, redirect/pagination and pinned-IP tests |
| File redirect leaks tokens or probes another service | Fresh course-qualified metadata, exact storage origins, separate credential-free HTTP session, bearer only on initial approved Canvas route, bounded raw stream and redirects | Synthetic redirect chains, ambient-auth/cookie stripping, timeout/cancellation, metadata/type/size/signature rejection; private actual PDF storage redirects verified; new institutions need separate origin review |
| Course prompt injection | Source-data labels; no credential-return or calendar/action tool; server ACLs independent of content | Text-preservation/route tests; real adversarial ChatGPT conversations pending |
| Parser exploits | Windows AppContainer/Job Objects; Linux Landlock and default-deny seccomp; explicit per-job file access, process/network denial, memory/CPU/wall/output limits, no service code or credentials | Existing platform-specific worker tests; current Windows regression result is in the security evidence record; Linux image rerun and optional native-runtime acceptance remain CI/operator gates; macOS extraction fails closed |
| Retry storm / connection exhaustion | Shared outbound global/per-host quotas, bounded idle state, full Retry-After cooldown, failure circuit with one recovery probe; global ingress and per-principal MCP admission | Injected-clock and simultaneous-stream tests; process limits are not fleet-wide quotas. Hosted replicas require an edge/distributed tenant budget |
| Duplicate expensive parsing / lock cleanup race | Existing source/epoch-bound caches and serialized file work; weak lock registry retains queued waiters, idle entries disappear without eviction races | Concurrent waiter/retention regression; cross-process jobs still rely on database leases and deployment sizing |
| Dependency substitution or leaked historical secret | Approved registry URLs, artifact hashes, locked install, pinned scanner checksums, full Git history plus current-source scan, vulnerability/license/static/config gates | Tampered archive/registry/hash/license fixtures; scanners cannot prove a dependency is benign. Native distributions and release artifacts need platform-specific checks |
| Cached access after revocation | Current course checks, at most five-minute entitlement lease; fresh page/file check before fetch, page recheck before search | Permission-loss fixtures; no stale cache offered after known denial |
| Disconnect versus in-flight job | Connection row locks, deletion epochs, no job resurrection | Queue and token-refresh race fixtures; PostgreSQL worker owner checks |
| Account deletion versus OAuth completion | Principal generation, ordered principal/connection locks, one-use state and separate durable owner fence | Token-exchange/profile-read cancellation, PostgreSQL link/delete race, pre-deletion restore fixtures |
| Restore resurrects deleted records | HMAC journal flushed before removal; empty-target restore; later fences applied before import | Encrypted backup/restore fixtures; offsite journal durability is an operator gate |
| Browser forgery / XSS | HttpOnly sessions, CSRF token, origin/Fetch Metadata validation, HTML escaping, CSP | HTTP and actual browser keyboard checks; full accessibility audit pending |

This is not a completed penetration test. Live student deployment is blocked
until independent review, operational ownership and the release-gate evidence
are complete. Application ACLs are the primary boundary; no RLS claim is made.
