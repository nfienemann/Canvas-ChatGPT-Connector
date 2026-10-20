# Threat model

Assets: per-student credentials, academic facts, derived text, saved preferences,
OAuth sessions, job/action state, deletion history and encrypted backups.
Trust boundaries: MCP host → resource server; browser → settings; service →
institution; API/worker → database; key mount → vault; restored backup → deletion
journal. No course text is an instruction source.

| Threat | Implemented control | Verification / remaining boundary |
|---|---|---|
| Wrong user, school or guessed object ID | Issuer+subject principal; owner+connection filters; canonical course-qualified IDs | Synthetic and PostgreSQL isolation tests; real multi-school proof pending |
| Token substitution / expired issuer key | RS256-only pinned configured JWKS, exact issuer/audience/expiry/subject/scopes, bounded key cache | Invalid-token and expired-cache tests |
| Login CSRF / replay / refresh race | Browser-bound expiring one-use state; exact redirects; PKCE settings flow; database refresh lease | State and refresh race fixtures; real external IdP login pending |
| Powerful Canvas credential | Typed GET allowlist, student enrollment check, exclusion of staff/mixed-role courses, own-user response filtering | No roster/write route; staff-power fixture |
| SSRF or malicious continuation | HTTPS origin checks, unchanged route/query, public-IP DNS pinning, no API redirects | Private/mapped IP, redirect/pagination and pinned-IP tests |
| Course prompt injection | Source-data labels; no credential-return or calendar/action tool; server ACLs independent of content | Text-preservation/route tests; real adversarial ChatGPT conversations pending |
| Parser exploits | Size/member/expanded-size/ratio limits, defused XML, no macros/embedded object execution | Synthetic PDF/DOCX/PPTX only; live binary parser not enabled without OS/network isolation |
| Cached access after revocation | Current course checks, at most five-minute entitlement lease; fresh page check before fetch/search | Permission-loss fixtures; no stale cache offered after known denial |
| Disconnect versus in-flight job | Connection row locks, deletion epochs, no job resurrection | Queue and token-refresh race fixtures; PostgreSQL worker owner checks |
| Account deletion versus OAuth completion | Principal generation, ordered principal/connection locks, one-use state and separate durable owner fence | Token-exchange/profile-read cancellation, PostgreSQL link/delete race, pre-deletion restore fixtures |
| Restore resurrects deleted records | HMAC journal flushed before removal; empty-target restore; later fences applied before import | Encrypted backup/restore fixtures; offsite journal durability is an operator gate |
| Browser forgery / XSS | HttpOnly sessions, CSRF token, origin/Fetch Metadata validation, HTML escaping, CSP | HTTP and actual browser keyboard checks; full accessibility audit pending |

This is not a completed penetration test. Live student deployment is blocked
until independent review, operational ownership and the release-gate evidence
are complete. Application ACLs are the primary boundary; no RLS claim is made.
