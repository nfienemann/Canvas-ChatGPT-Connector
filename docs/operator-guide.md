# Operator guide

## Course file inventory and download policy

The source build inventories accessible course files and resolves visible module
files directly when the course Files collection is denied. PDF/DOCX/PPTX/TXT/Markdown
reading can be enabled in a Windows source deployment using the verified
AppContainer worker or a supported Linux deployment using Landlock/seccomp.
See [Linux isolation](linux-parser-isolation.md) for kernel requirements, separate
runtime/job directories and the unprivileged container proof. Existing `fetch_course_material` supports the same file
path as `read_course_file`; every chunk rechecks current access. See
[file reading](file-reading.md) for setup, sandbox budgets and cache retention.

The internal download transport uses fresh course-qualified metadata. Optional
institution `download_origins` entries must be exact HTTPS origins reviewed by
the operator; the default is empty. Do not infer trust from a returned redirect
or use wildcard suffixes. `download_origin_templates` permits only an exact
operator-reviewed hostname containing one `{file_id}` numeric substitution;
it is bound to the requested Canvas file. A signed storage URL is transient and never a citation,
database field or exported source. Every hop uses public-IP DNS pinning, a maximum
of three redirects, at most 10 MB, matching metadata/type/signature checks and
the overall refresh time budget. Canvas credentials are sent only to the initial
approved Canvas download route; cookies and ambient client authentication are
excluded from all file requests.

Schema revision `1c8d7b420ad1` adds the page/file discriminator. Apply migrations
before starting this source version. Existing rows default to pages. An explicit
downgrade removes derived file records before dropping that discriminator, so
older code cannot confuse a file ID with a page ID. Back up before migration.
Revision `4be2ca7831f0` adds extraction state; its downgrade clears derived file
text before dropping that state. Neither migration alters Canvas.

## Local development

Use the README commands. `init-demo` creates a private `.env`, key files, a
24-hour fixture access token, migrations and fictional selected courses. It
refuses to replace a live profile. `.local/` and `.env` are ignored by Git.
`serve` binds to loopback in synthetic mode. API access logs are disabled to avoid
logging callback codes or bearer credentials. Errors use sanitized categories.

`doctor` reports presence/readiness without printing credentials.
`verify-read` exercises the official MCP client with synthetic records.

## PostgreSQL and hosted configuration

Live profiles require PostgreSQL, explicit `BRIDGE_LIVE_ACCESS_ENABLED=true`,
HTTPS resource/issuer/JWKS URLs and a separately mounted vault key. Hosted
student use additionally needs supported institution entries and private OAuth
client credentials. These flags are not
evidence of institutional approval. Complete the release gates first.

Migrate with `uv run alembic upgrade head`. The schema has upgrade/downgrade tests
against PostgreSQL 17.11. Back up before live migration. A downgrade can destroy
data; use a reviewed maintenance procedure.

`compose.yaml` supplies PostgreSQL, a migrator, API and worker. Provide an ignored
`.env` whose database URL uses the Compose `db` hostname, private
`.local/db-password`, and `.local/vault.key`. The vault key is exactly 32 random
bytes. Terminate public HTTPS at an operator-managed proxy. API is published only
on host loopback. Linux CI exercises isolated extraction in the restricted
service image. The full hosted Compose deployment remains unverified; containers
were not run on this Windows host.

The external authorization server must implement the current MCP contract,
including issuer/resource binding, discovery, S256 PKCE and exact redirects.
For browser settings configure `BRIDGE_BROWSER_CLIENT_ID`,
`BRIDGE_BROWSER_AUTHORIZATION_URL`, `BRIDGE_BROWSER_TOKEN_URL`, and optionally
`BRIDGE_BROWSER_CLIENT_SECRET_FILE`. Browser endpoints must share the configured
issuer host. By default the callback requires an exact issuer `iss` parameter.
Register `/settings/callback` at the deployment resource base. For a provider
that does not support RFC 9207 authorization-response issuer identification, set
`BRIDGE_BROWSER_REQUIRE_ISSUER_PARAMETER=false` and register the **exact**
`browser_callback_url` reported by `doctor`. This uses a separate callback path
for each exact issuer, following RFC 9700 section 4.4.2.2. Do not register a
wildcard. A returned `iss`, when present, must still match. The encrypted one-use
login transaction also binds the issuer, authorization/token endpoints, client,
resource and callback policy; changing configuration requires a fresh login.

For WorkOS AuthKit, use the environment's AuthKit issuer and `/oauth2/jwks`,
`/oauth2/authorize`, and `/oauth2/token`. Inspect that environment's discovery
before choosing the callback mode. Configure the exact resource indicator to
match `BRIDGE_RESOURCE_URL`; the environment client ID is not a substitute
audience. Static Connect OAuth applications can be assigned the app's custom
scopes. The settings client needs `academic:read preferences:write settings:write`;
the initial read-only MCP client needs `academic:read`. Dynamically registered
WorkOS clients do not receive these custom scopes by default. Do not bypass
scope validation or treat `openid` as coursework permission. This configuration
guidance describes configuration requirements; the separate private first-read
proof is recorded in the platform compatibility matrix.

For a persistent ChatGPT connection, also request `offline_access` as a base
OAuth scope. WorkOS only supplies a refresh token when the authorization grant
permits it; an initially successful read without renewal can fail minutes later.
This scope renews the existing authorization and does not grant additional
academic operations. Keep coursework access at `academic:read`. Test a new call
after the initial access token expires, not just immediately after sign-in. See
the [WorkOS refresh-token contract](https://workos.com/docs/reference/workos-connect/token)
and [ChatGPT authentication setup](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

Keep operator files and secret mounts outside public artifacts. Reverse-proxy
logs must omit authorization headers and callback query strings.

## Private developer proof

This is only for the operator's own Canvas records. It is not a student onboarding
alternative. Canvas documents personal testing tokens separately from the OAuth
grants required for other users. No personal credentials or real records have
been used in repository tests.

Use a separate, migrated PostgreSQL database and private operator configuration.
Set `BRIDGE_PROFILE=personal`, explicit live enablement, the HTTPS/authentication
settings above, and `BRIDGE_PERSONAL_SUBJECT` to the operator's exact subject from
that identity provider. The service rejects every other subject, even when a
different user has a valid token from the same issuer. An email address or Canvas
token cannot substitute for that authenticated subject.

After confirming the institution allows this personal test, copy the institution
registry into private configuration and point `BRIDGE_INSTITUTIONS_FILE` at it.
Enable only the intended entry with status `personal_testing` and its verified
HTTPS origin. This status is rejected by hosted profiles and is never advertised
as a supported school. The published Rowan entry remains `candidate`.

Set `BRIDGE_MCP_READ_ONLY=true` for an initial reading/planning trial. This removes
the three saved-state write tools from the MCP catalog and dispatch entirely; it
does not label writes as reads. Course selection and privacy controls still use
the authenticated settings page. The setting does not prove plan compatibility;
test discovery and actual calls in the user's ChatGPT account.

From a private interactive operator terminal, run:

```console
uv run canvas-bridge link-personal --institution YOUR_REGISTRY_ID --expected-canvas-user YOUR_NUMERIC_CANVAS_USER_ID
```

The expected ID is the operator's Canvas user ID, not a campus student/Banner ID.
The command prompts for the operator's testing token with terminal echo disabled.
There is no token command-line argument, web form, MCP input or `.env` token
setting. It refuses redirected/echoed input and sanitizes setup failures. Use a
dedicated testing token; never supply another person's credential.

The command checks `/api/v1/users/self/profile` at the allowlisted origin and
compares the returned user ID before saving an owner-bound encrypted credential.
It fetches no courses during import. Then sign in to settings, select courses,
and perform the first read through actual ChatGPT. Token setup alone is not that
acceptance test. The same student-only route/role restrictions apply to personal
tokens even if Canvas granted broader permissions.

A second import cannot silently replace an active connection. Disconnect first;
the normal disconnect/delete controls purge local records and attempt provider
revocation. An expired/revoked personal token requires a new private setup and is
not sent through OAuth refresh. If deletion cancels a pending import, the supplied
token is not saved or automatically revoked; the operator still controls that
token in Canvas. No success is reported for the interrupted setup.

For reachability, evaluate the user's custom MCP connection options before
buying hosting. [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
can keep the service private, but requires separate Platform tunnel permissions,
a restricted runtime credential and the correct ChatGPT workspace association.
It does not replace application OAuth or automatically expose its authorization
server. A private owner-only proof uses WorkOS staging and an ngrok HTTPS tunnel
with local request inspection disabled. The installed ChatGPT Pro plugin has
completed a live coursework read. This PC-based service must be running and the
computer awake; it is not an always-on hosted student service. Operator secrets,
runtime configuration and private screenshots remain outside the repository.

## Worker and retention

`uv run canvas-bridge worker` processes explicitly queued refresh jobs and purges
expired snapshot/OAuth records. No recurring refresh is scheduled by a read.
Jobs use leases, three attempts, ownership checks and connection epochs.
Disconnect removes pending jobs and blocks in-flight writes.

`uv run canvas-bridge purge` runs independently. Snapshot retention defaults to
30 days. Scope removal denies access and purges course-derived active records,
as described in the retention guide. Account-wide deletion additionally fences
pending authorizations and browser sessions across every linked institution.
Aggregate telemetry and deployment-specific backup expiry still need pilot review.
No background notifications are delivered.

## Backup and restore

`uv run canvas-bridge backup .local/snapshot.backup` creates an encrypted logical
snapshot in a new file. PostgreSQL uses repeatable read. Browser sessions and
incomplete OAuth transactions are excluded. Retain the vault key separately.

Maintain `BRIDGE_DELETION_JOURNAL` independently of database rollback.
Disconnect flushes an authenticated fence before local removal. Copy the journal
to independently protected storage under a tested procedure. A same-disk journal
is not offsite protection.

Account-wide deletion writes a `principal:` fence and increments the minimal
principal generation under a database lock. Preserve these journal entries with
connection fences. The restore procedure excludes pre-deletion connections and
raises restored principal generations before serving data. Never hand-edit or
truncate the journal to bypass a restore error.

Restore only into an **empty, migrated database**:

```console
uv run canvas-bridge restore .local/snapshot.backup --journal .local/deletions.jsonl
```

The command refuses existing records or missing/tampered journals, applies newer
deletion fences before import, and cancels restored jobs. Test a canary read and
deletion fixture before serving restored data. Offsite backup and host-loss
recovery have not been deployed.

## Operational boundaries

No production service, budget, region, incident owner, vendor contract, live SLO,
managed key rotation or distribution approval is implied by these files.
Review [release gates](../evidence/release-gates.md) before serving real records.
