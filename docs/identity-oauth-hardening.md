# Identity, OAuth and least privilege

This change reuses `JWTVerifier`, `PrincipalState`, `BrowserSession`, `OAuthState`,
`Connection`, the credential vault, selected-course authorization and deletion
journal. It does not establish any provider or institutional approval. The
authorization-policy and data-egress gateways remain independent prerequisites.

## Authentication boundaries

Application access is a signed RS256 JWT with the exact configured issuer and
resource audience, a verified subject, required scope, expiration and a maximum
lifetime of one hour (configurable downward). The owner key is derived from the
verified issuer and subject. Model arguments cannot choose that principal.
Application tokens are never forwarded to Canvas.

The settings application already used authorization codes, S256 PKCE, one-use
state, a browser nonce, exact redirects and issuer/mix-up defenses. These are
retained. Browser sessions expire no later than their application access token.
Changing application accounts requires signing out first while a valid browser
session exists. Expired sessions can start a fresh login. Cookies remain secure
on HTTPS, HttpOnly and SameSite; mutations require same-origin CSRF validation.
Settings rechecks the session before mutations and before returning fetched
course data. Unverified or approval-disabled connections display their status and
retain disconnect/sign-out controls without fetching coursework.

Upstream OAuth uses a separate confidential server client and encrypted,
owner/connection-bound credentials. New OAuth connections require an explicit
`oauth` block in the institution's private registry:

```json
{
  "client_type": "confidential_server",
  "pkce": "S256",
  "refresh_rotation": "rotating",
  "granular_scopes": true,
  "documentation_reference": "operator-reviewed deployment protocol reference",
  "issuer_parameter": false,
  "max_access_token_seconds": 3600
}
```

This is a protocol example, not a Canvas deployment claim or approval record.
An administrator must establish which capabilities the particular deployment
actually supports. `pkce` can instead be `unsupported`; refresh rotation can be
`stable`. Unsupported features are never claimed to work. Only confidential
server clients are implemented; there is no public desktop client containing a
shared secret and no public token-paste onboarding. Existing operator-only
personal proof remains subject to its single-owner and approval restrictions.

Each upstream authorization transaction has a distinct callback derived from the
institution ID and exact origin. The exact resulting URL must be registered at
that provider. Its encrypted state binds PKCE, callback, browser, principal
generation, institution, client, capabilities and scopes. Configuration changes
invalidate pending transactions and existing grants. Old generic callbacks do
not complete new transactions. The HTTP callback also requires the original
authenticated application owner; duplicate response parameters are rejected.

Grant responses must contain a bounded Bearer token and an explicit positive
expiration no longer than the reviewed ceiling. Returned scopes, when present,
must match the request. Refreshes retain stable refresh tokens only for a reviewed
stable-token deployment; rotating deployments must return a different token.
Every refreshed access token must resolve to the connection's previously verified
upstream user before storage. Connection epoch, credential and refresh-lease
comparisons fence races. Newly returned grants are cleaned up on failed identity
verification or lost authorization. Remote cleanup can remain unconfirmed.

Revocation never sends a bearer token to a changed registry origin. The encrypted
credential records its issuing origin; if that origin no longer matches the
reviewed endpoint, cleanup reports `not_confirmed`.

## Capabilities and resource access

Institution `capabilities` default to `courses` and `course_membership` only.
Administrators must separately enable `assignments`, `submissions`, `grades`,
`files`, `modules`, `pages`, `syllabus`, `quizzes`, `discussions`, `announcements`,
`calendar` or `calendar_proposals` for approved workflows. There is no write or
roster capability. Embedded submission/grade includes are gated too. Submission
data is also a separate category in signed approval records.

Only known GET scopes needed by enabled workflows are requested. Profile and
course-discovery scopes are required for scoped OAuth. The `scopes` registry
remains the application's endpoint ceiling when a provider cannot grant granular
OAuth scopes; no scope parameter is sent in that reviewed mode. Application
controls **do not restrict the power of a stolen unscoped upstream token**.

Every network send and returned API response rechecks the connection and relevant
capability. Cached and model-bound outputs retain the existing exact owner,
connection, selected-course, lease, approval and egress fences. Changing origin,
client, capabilities or scopes requires reconnecting; it cannot silently expand
an old credential. Failed course permission refreshes immediately clear the
previous authorization lease even after a transient network failure.

## Revocation and status

Authentication status is explicitly `unverified`, `verified`, `expired` or
`revoked`, separate from connection state and integration approval. Failed token
refreshes restrict caches, invalidate staged originals/derivatives and invalidate
jobs' epochs. Invalid grants or changed upstream users disconnect and purge the
connection. Network failures never imply successful upstream revocation.

Disconnect commits local credential/cache/queue removal and the durable deletion
fence before attempting remote revocation. Original-file capabilities are removed
immediately; active transfers fail their subsequent checks. Running workers watch
the durable job/connection epoch and cancel pending asynchronous work after
revocation; network and persistence fences also apply across worker processes.

“Sign out all Bridge sessions” increments the existing principal generation,
records a token issuance cutoff, deletes browser/pending authorization sessions,
cancels jobs and invalidates temporary files. Account deletion sets the same
cutoff. JWTs issued at or before the cutoff are rejected on subsequent requests
and at final tool/stream release. Another principal's sessions remain valid.
Tokens issued in the same clock second as sign-out can require a new sign-in on
the next second. Identity-provider sessions themselves are controlled by that
provider; this operation revokes Bridge acceptance, not the provider's login.
Authorization transactions started before the cutoff cannot reopen a session
even if their token exchange returns a newly issued application token afterward.

The separately retained journal restores the cutoff after backup restoration.
For conservative recovery, a principal sign-out fence also excludes older
connection snapshots from restore. External conversations and exported copies
remain outside local deletion control.

## Deployment and validation boundary

Migration `8d21f4c932ab` follows `62ab7d391c04`. It adds the principal cutoff and
upstream authentication state. Existing credentials migrate to **unverified**;
they are never automatically promoted. An authorized operator must apply the
migration, configure reviewed capabilities, register exact callbacks and explicitly
reconnect/reverify affected connections before live use. No private configuration,
running service or real credential was changed during implementation.

The synthetic OAuth server tests interception, PKCE, exact redirects, replay,
issuer/owner/configuration mismatch, expiration, revoked refresh grants, rotation,
identity confusion and concurrent refresh fences. Local HTTP/MCP tests cover
session revocation and prevention of data release after revocation. Original file
and job tests cover staged-byte cleanup and cancellation. Existing approval,
egress, scope, cross-user/course and offline tool regressions remain required.
See the [sanitized validation record](../evidence/sanitized-results/identity-oauth-hardening-2026-10-25.md).

Protocol references reviewed on 2026-10-25:
[Instructure OAuth overview](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth),
[Instructure OAuth endpoints](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth_endpoints),
and [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html).
These describe protocol behavior; they do not authorize this integration.
