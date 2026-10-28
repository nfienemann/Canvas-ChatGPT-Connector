# Identity and OAuth hardening — local synthetic validation

Date: 2026-10-25. Environment: Windows, repository Python virtual environment.
No real identity provider, Canvas installation, student record or credential was
used. The upstream authorization server uses HTTPX MockTransport and fictional
`.invalid` origins. HTTP/MCP contract checks use a local loopback server.

## Audit and implementation

Retained the existing JWT verifier, issuer/subject owner key, browser sessions,
OAuth state, vault, connection/epoch model, principal generation and selected
course authorization. Existing application PKCE, issuer/audience verification,
exact redirect/state checks, CSRF, scope checks and encrypted credential storage
were reused rather than introducing a second identity system.

Added institution-reviewed OAuth capability configuration and exact
institution-bound callbacks, optional S256 PKCE, bounded grant validation,
scope/capability binding, refresh rotation enforcement and refreshed-user
verification. New sensitive workflows require explicit capabilities. Signed
approval records must separately include the new submissions data category.

Application JWTs have a maximum one-hour lifetime. Sign-out/account deletion
records a durable issuance cutoff using the existing principal. Settings and
MCP responses, plus authenticated original-file chunks, check current session
authorization. A pending login started before sign-out cannot reopen a session
with a later-issued token. Valid application sessions require explicit sign-out
before switching accounts; upstream account replacement requires disconnect.

Disconnect invalidates staged originals and derivative records, purges stored
connection data and cancels queued work. Workers cancel running asynchronous
jobs when their durable connection/job epoch is revoked. Failed permission
refreshes cannot retain old cache leases. Revocation network failures remain
`not_confirmed`; changed registry origins never receive older bearer tokens.

## Checks

- Reused the preceding specification's 1080-pass/27-skip full-suite baseline;
  no redundant opening full run.
- Intermediate authentication, approval and egress group: **185 passed**.
- Final focused identity, browser OAuth, account deletion and HTTP/MCP group:
  **78 passed in 27.23 seconds**. This includes the final browser transaction
  cutoff, unverified-settings display and browser response revocation fixes.
- Full suite: **1119 passed, 27 skipped in 389.42 seconds**. The suite started
  before the final browser-only follow-ups; those were checked by the final
  78-test run above. No duplicate full run was needed for those isolated fixes.
- Skips: 13 Linux-kernel checks on Windows, 7 disposable-PostgreSQL checks,
  5 optional native-converter checks and 2 optional OCR checks. These remain
  environment-dependent acceptance work, not passing evidence.
- Ruff check across `src`, `tests` and `migrations`: passed.
- Ruff format check of the 29 Python files touched for this specification: passed.
- `git diff --check`: passed.
- New Alembic head `8d21f4c932ab` upgraded successfully in an isolated temporary
  SQLite database. The new connection authentication state defaults to unverified.
- Browser-only changes are server-rendered; no JavaScript assets changed for this
  specification. The preceding specification's UI build remains the applicable
  asset build check.

Synthetic regressions cover authorization-code interception, verifier mismatch,
wrong redirect/issuer/owner, replay, configuration changes, expired and malformed
grants, refresh-token rejection/rotation, cross-account refreshed identity,
cross-institution origin binding, scoped and explicitly unscoped deployments,
disabled capabilities, concurrent refresh, disconnect during renewal, sign-out,
mid-request session revocation, staged-file removal and running-job cancellation.
Existing tests cover exact cross-user/course references, MCP scope checks,
approval failure, egress restrictions and unaffected synthetic academic tools.

## Evidence boundary and activation

This is local implementation and synthetic verification. It is not live Canvas
OAuth acceptance, deployed MCP evidence, an approval grant or a compliance
certification. Provider/institution approval and real recipient/content approval
remain **NOT_ASSESSED**. No private operator configuration, current credentials,
course selection, permissions, running service or installed connector was changed.

Before an authorized deployment, apply migration `8d21f4c932ab`, review the exact
institution OAuth capabilities and app scopes, register its exact callback, and
explicitly reconnect/reverify existing credentials. Migration never marks older
credentials verified. Validate PostgreSQL races and actual provider behavior in
the appropriately approved environment. See
[implementation and operator details](../../docs/identity-oauth-hardening.md).
