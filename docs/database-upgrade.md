# Personal PostgreSQL database upgrades

Startup never upgrades a schema. It checks compatibility before creating the
bridge or running retention. Stale schemas report
`CANVAS_BRIDGE_DATABASE_MIGRATION_REQUIRED`; lost keys and journals have separate
findings. Provider approval, browser authentication and network health remain
independent of database readiness.

From the repository, with Windows PowerShell 5.1 or later:

```powershell
.\scripts\Database-Upgrade.ps1 -DeploymentRoot '<actual service directory>'
```

The default is check-only. Use the `WorkingDirectory` from the installed launcher,
containing its private `.env`, not the repository. The wrapper uses the repository
virtual environment, never Python on PATH, and preserves paths with spaces.
No username or app-package path is embedded in the implementation.

Equivalent commands using `.venv\Scripts\canvas-bridge.exe`:

```text
doctor --database --deployment-root <service-directory>
database-upgrade --deployment-root <service-directory> --check
database-upgrade --deployment-root <service-directory> --status
```

Diagnostics report the configuration source, sanitized endpoint, target hash,
current revision, discovered head, ordered pending source filenames/hashes and
conservative risk flags. These flag rewrites, deletion, security state and
one-way encryption; they do not certify safety. Review the actual pending source.
Missing, multiple, unknown or divergent revisions fail closed; no stamping occurs.
An empty valid journal does not prove the absence of historical deletions.
New installations use explicit provisioning, not this upgrade command.

Only explicit personal `postgresql+psycopg` configurations with host, port, role
and database are accepted. URL query options and shell `BRIDGE_*`/`PG*` overrides are
rejected to prevent alternate endpoint selection. Use the same reviewed `.env`
as the service. Direct server identity and port must agree with the configuration;
connection proxies are not supported.

## Backup and apply

Create a private backup parent directory outside the repository and OneDrive.
Secure a separate recovery copy of the **existing** vault key. The command asks
you to affirm the copy exists; it never copies or replaces keys. Use the target
hash printed by the check:

```powershell
.\scripts\Database-Upgrade.ps1 -DeploymentRoot '<service directory>' `
  -Mode BackupOnly -ExpectedTarget '<target hash from check>' `
  -BackupDirectory '<existing private backup parent>'

.\scripts\Database-Upgrade.ps1 -DeploymentRoot '<service directory>' `
  -Mode BackupAndApply -ExpectedTarget '<target hash from check>' `
  -BackupDirectory '<existing private backup parent>' -StopApplication
```

There is no `--yes` or noninteractive consent flag. Review the target and risks,
approve backup/key readiness, approve maintenance, then approve the exact
before/after revisions after archive verification. Without `-StopApplication`,
the service and workers must already be stopped. The helper validates the
service PID/parent, interpreter, command, listening port and resource metadata
before stopping the listener. Unknown workers are not killed; remaining database
sessions block application. PostgreSQL and ngrok are untouched. Do not use the
old launcher's `-Action Stop`: it stops PostgreSQL too.

All service/worker processes must use the updated source and normal deployment
directory. Store connections hold a shared PostgreSQL advisory lock; the upgrade
requires its exclusive counterpart. Stop old builds and external writers and
disable their automatic restart first. The session check detects existing legacy
connections but cannot prevent an unmanaged process reconnecting later. This is
a private operator workflow, not a distributed maintenance controller.

The upgrade creates a persistent `.database-maintenance` startup hold, obtains
exclusive maintenance, reinspects the plan, and creates a unique restricted
backup directory. Matching-major-version `pg_dump -Fc` receives credentials only
through its child environment. Exit status, archive size, `pg_restore -l`, and
SHA-256 are checked. Before Alembic runs, the plan, configuration/key/journal
hashes and archive checksum are checked again. Alembic receives explicit URL,
key and migration directory. Actual head and schema columns are verified before
the hold is cleared. Restart is a separate operator action using the launcher.

The Python CLI supports `--pg-bin <directory>` to override bundled tools. The
stop helper is included in wheels; the convenience wrapper targets source
checkouts. Desktop GUI upgrade integration is not claimed.

## Failure and recovery

Failure preserves the backup and maintenance hold. Child errors and SQL
exceptions are not printed. `--status` reports the actual revision and last
sanitized result. Do not blindly retry, downgrade, stamp, reset, generate a key,
or create an empty replacement journal. Review the current schema and migration
transactional behavior and preserve current deletion/revocation history. Only
after explicit recovery review should the operator remove `.database-maintenance`
from the verified service directory. No automatic rollback is attempted.

Archive listing is **not full restore validation**. For stronger validation,
provision an isolated PostgreSQL database of the same major version, use
`pg_restore --exit-on-error --dbname <isolated-database> <archive>` with credentials
in a private child environment, compare revisions/schema and representative
synthetic records, and verify decryption with the separately retained key.
Never rehearse over the service database. Real recovery must preserve newer
deletion/revocation fences and usage-accounting holds. This command provides no
restore operation and cannot reactivate access.

Backups are never automatically deleted. Manage retention under the existing
data policy; backup retention grants no permission to resurrect expired records.
Keep archives and keys out of the repository, CI artifacts and synced folders.

## Installed launcher integration

This change does not edit private launcher/configuration files. On an explicitly
approved launcher update, replace its generic failure text with:

```text
Canvas Bridge could not start. Check the private service log for the specific
diagnostic. For a database mismatch, run scripts\Database-Upgrade.ps1
-DeploymentRoot <this launcher's directory> -Mode Check from the repository.
Startup never migrates. Missing security state requires recovery review.
```

Preserve existing launcher identity/authorization checks. The application already
writes the actionable command to its service error log. An ngrok error or
provider denial is not a database mismatch diagnosis.

See [validation and limits](../evidence/sanitized-results/database-upgrade-2026-11-03.md).
