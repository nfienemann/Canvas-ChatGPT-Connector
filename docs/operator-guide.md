# Operator guide

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
HTTPS resource/issuer/JWKS URLs, a separately mounted vault key, supported
institution entries and private OAuth client credentials. These flags are not
evidence of institutional approval. Complete the release gates first.

Migrate with `uv run alembic upgrade head`. The schema has upgrade/downgrade tests
against PostgreSQL 17.11. Back up before live migration. A downgrade can destroy
data; use a reviewed maintenance procedure.

`compose.yaml` supplies PostgreSQL, a migrator, API and worker. Provide an ignored
`.env` whose database URL uses the Compose `db` hostname, private
`.local/db-password`, and `.local/vault.key`. The vault key is exactly 32 random
bytes. Terminate public HTTPS at an operator-managed proxy. API is published only
on host loopback. Containers were not tested on this Windows host.

The external authorization server must implement the current MCP contract,
including issuer/resource binding, discovery, S256 PKCE and exact redirects.
For browser settings configure `BRIDGE_BROWSER_CLIENT_ID`,
`BRIDGE_BROWSER_AUTHORIZATION_URL`, `BRIDGE_BROWSER_TOKEN_URL`, and optionally
`BRIDGE_BROWSER_CLIENT_SECRET_FILE`. Browser endpoints must share the configured
issuer host. The callback requires an exact issuer `iss` parameter.
Register `/settings/callback` at the deployment resource base.

Keep operator files and secret mounts outside public artifacts. Reverse-proxy
logs must omit authorization headers and callback query strings.

## Worker and retention

`uv run canvas-bridge worker` processes explicitly queued refresh jobs and purges
expired snapshot/OAuth records. No recurring refresh is scheduled by a read.
Jobs use leases, three attempts, ownership checks and connection epochs.
Disconnect removes pending jobs and blocks in-flight writes.

`uv run canvas-bridge purge` runs independently. Snapshot retention defaults to
30 days. Scope removal denies access and purges course-derived active records,
as described in the retention guide. Aggregate telemetry, full account deletion
and deployment-specific backup expiry still need pilot review.
No background notifications are delivered.

## Backup and restore

`uv run canvas-bridge backup .local/snapshot.backup` creates an encrypted logical
snapshot in a new file. PostgreSQL uses repeatable read. Browser sessions and
incomplete OAuth transactions are excluded. Retain the vault key separately.

Maintain `BRIDGE_DELETION_JOURNAL` independently of database rollback.
Disconnect flushes an authenticated fence before local removal. Copy the journal
to independently protected storage under a tested procedure. A same-disk journal
is not offsite protection.

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
