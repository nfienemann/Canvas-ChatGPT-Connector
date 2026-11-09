# Concurrent-session authorization repair — November 3, 2026

The shared membership lease could be cleared by a second request's incomplete
course refresh while the first request was still reading. Individual SQL row
locks did not serialize the complete request through its response fence.

Implemented a per-owner/per-connection read guard at the MCP boundary and the
course-list refresh boundary. Same-task nesting is reentrant; child tasks cannot
inherit ownership. PostgreSQL session advisory locks coordinate application and
operator processes. The guard includes final authorization and content release,
uses a bounded 60-second wait, and closes its database session on timeout,
cancellation, or completion. Windows database calls run off the event loop;
short calls finish before cancellation cleanup closes their session.

Revocation, selection changes, credential checks, source reviews and the final
scope fence remain enforced. Failed refreshes still invalidate the lease.
SQLite synthetic fixtures use the local async guard. No database migration,
credential changes, source attestations or usage-ledger resets were performed.

Checks completed:
- Initial focused authorization/private-sharing run: 70 passed.
- Updated guard, MCP contract, retrieval lifecycle, preflight and permission
  consistency run: 62 passed.
- Separate Windows processes against the private PostgreSQL server used synthetic
  lock identities only: exclusion while held, then acquisition after release,
  both passed. No academic records were queried or changed by this check.
- Standard private service restart completed.
- Simultaneous native reads of two approved sources (assignment and page): both
  status ok and EGRESS_RELEASE_PERMITTED. The page previously reproduced stale scope.
- A recovered PDF body remained withheld with EGRESS_CONTENT_HASH_REVIEW_REQUIRED;
  the old footer-only review was not reused.
- A second competing read returned a redacted retry. Added AUTHORIZATION_BUSY to
  the fixed diagnostic vocabulary so contention is reported without private text.

Further safe-error contract tests and final installed retests follow below.

## Final installed acceptance

- Guard and alternate-channel egress tests: 19 passed; Ruff checks passed.
- Final standard restart completed with the fixed busy diagnostic installed.
- A pre-restart upstream reservation temporarily blocked another read. No usage
  accounting was reset; normal expiry/recovery cleared that admission constraint.
- The final approved assignment read then returned ok / EGRESS_RELEASE_PERMITTED.
- Final native permission audit: ok, scope_consistency consistent, all 35 checks
  AUTHORIZED_LOCAL_SCOPE, and EGRESS_RELEASE_PERMITTED.
- All three approved current text samples (two assignments and a Canvas page)
  succeeded during the installed retests. No STALE_SCOPE_SNAPSHOT occurred in
  these post-fix source reads. The two-source simultaneous test also passed.
- The recovered PDF still requires a fresh exact-text review; remaining unreviewed
  packet entries were not attested or released. These results establish this
  bounded private-instance acceptance, not unlimited concurrency or public release.
