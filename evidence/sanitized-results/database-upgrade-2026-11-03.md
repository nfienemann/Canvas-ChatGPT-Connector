# Safe database upgrade automation — 2026-11-03

## Implemented

Added `database_upgrade.py`, the cooperative PostgreSQL fence in `maintenance.py`
and Store, explicit CLI modes and doctor routing, and a supplied-connection path
in Alembic's environment. Upgrades use the same session for the maintenance lock
and migrations. Strengthened startup diagnostics and multiple-revision detection.
Added a PowerShell 5.1 wrapper and identity-checked application-only stop helper;
the helper is included in wheel resources. README and operator documentation
describe target selection, explicit consent, backup, verification and recovery.

Check/status do not create a database, key, journal or maintenance file. Apply
requires interactive consent, a target hash, existing security material and a
verified logical backup. Failed upgrades retain the maintenance hold. Successful
upgrades verify discovered head and schema, including representative read queries.
No automatic restart, downgrade, stamp, journal recovery or access reactivation
is introduced.

## Executed evidence

- Focused final run: `pytest tests/test_database_upgrade.py
  tests/test_database_upgrade_postgres.py tests/test_database_upgrade_windows.py
  tests/test_deployment_recovery.py -q`: **30 passed**.
- The PostgreSQL test creates its own loopback cluster under a temporary path
  containing spaces using bundled binaries. It runs the real orchestration with
  synthetic operator confirmation, performs `pg_dump -Fc` and archive listing,
  upgrades from an older revision to the discovered head, and restores into a
  second disposable database. Both databases contain fictional data only.
- A fictional disabled connection remains disabled/unverified; an older plaintext
  field becomes encrypted and decrypts using the unchanged key. A fictional
  revoked credential remains decryptable in the isolated restored backup.
- Live shared/exclusive PostgreSQL lock behavior was exercised. Synthetic failure
  tests cover target mismatch, security preflight, backup failure, empty/unreadable
  archives, version mismatch, concurrent maintenance, migration failure and
  postflight failure. Failures preserve holds and suppress private exception text.
- Windows PowerShell 5.1 executed the stop helper against mocked process/network
  inventories: the exact virtualenv-parent/base-Python-child chain is selected,
  mismatching metadata is refused, and fictional PostgreSQL is never stopped.
- `ruff check src tests scripts migrations`: passed. Formatting check for those
  directories: passed. Full-source Bandit at the repository
  `-ll -ii` threshold passed; unrestricted focused Bandit notes the expected low-severity
  subprocess import/call advisories for local tool execution.
- `canvas-bridge compliance-report --validate-only`: valid registry, 30 controls;
  authorization remains false. This is structural validation, not release approval.
- Repository-wide `ruff check .` and format checks remain blocked by pre-existing
  imported specification files: import formatting in
  `docs/private-media-library-specifications/validate_package.py`, a Python code
  block in the API governor specification, and non-UTF-8 content in
  `docs/api-usage-governor.md` and `evidence/release-gates.md`. These unrelated files
  were not rewritten.
- Full regression suite: **2,134 passed, 30 skipped in 1,524.67 seconds**.
  Skips cover unconfigured native conversion/OCR, Linux-only checks and existing
  externally configured PostgreSQL suites. The new upgrade PostgreSQL test ran
  against its own disposable cluster. The full run began during implementation;
  final diagnostic/guard refinements were checked by the focused suite afterward,
  without a redundant second full run.

## Evidence boundaries and remaining limits

No real service database was queried or modified, no private backup was taken,
no running service was stopped, and no private launcher/configuration was changed.
Read-only launcher/process metadata inspection confirmed the working directory,
the old Stop action's PostgreSQL shutdown, and Windows Python parent/child layout.
This is not installed deployment acceptance or real process-stop acceptance.

Actual application-only stopping was simulated; the real installation still needs
an operator-approved maintenance rehearsal. Launcher failure-message integration
is documented for an approved private launcher update, not silently installed.
Ordinary service errors already include the diagnostic command.

Source risk cues are conservative prompts for operator review, not a formal
migration safety proof. Unknown/external writers must be stopped and prevented
from restarting; advisory locks cannot govern unmanaged software. No concurrent
hosted/fleet acceptance is claimed. Ordinary backups are archive-listing verified;
the stronger restore result applies only to the executed synthetic fixture.
Private archive/key custody and policy-compliant backup retention remain operator
responsibilities. Existing institutional authorization and release gates remain
independent and unchanged.
