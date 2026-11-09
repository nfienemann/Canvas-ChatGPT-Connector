# OP-07 disposable installation and recovery test

This is an operator test protocol, not release approval. Run only on a disposable
Windows x64 OS with no personal Bridge install, account, credentials or records.
The preparation machine is explicitly excluded by the kit's host digest.
An alternate directory or Windows account on that machine is not a disposable OS.

The current PC has Windows Home, no Windows Sandbox and no available hardware
virtualization or separate test machine. The available development installer is
unsigned; the project's release trust anchors are empty. Therefore OP-07 remains
BLOCKED. Do not execute the personal install/uninstaller to substitute for this test.

## Bundle preparation

The local kit includes this protocol, `Test-DisposableRecovery.ps1`, a manifest,
the synthetic canary, a blank stage ledger and the executed preflight receipt.
It includes no installer, database, key, credentials, private configuration or
institutional records. Empty artifact slots are intentional blockers.

A release operator must supply the supported baseline installer and separately
verified upgrade and rollback packages, built against reviewed release trust.
Record their SHA-256 hashes as `baseline-setup.exe`, `upgrade.zip`, `rollback.zip`
in a new manifest. Populate public publisher thumbprints and the signer-configured
flag only from the shipped, reviewed trust configuration. A digest alone is not
signature verification. Never create test trust in the production configuration.
The baseline and rollback must be at least 0.2.0; the upgrade must be newer than
the baseline. Both update packages must explicitly support the database revision
present at the time they are applied. Legacy or schema-incompatible rollback must
be rejected, not forced with a copied database.

Transfer only the kit and public release artifacts into the disposable OS.
Keep its network disconnected. Do not map host data folders into a guest.
In PowerShell on that OS:

```powershell
$env:CB_DISPOSABLE_RECOVERY = 'YES_DISPOSABLE_OS'
& .\Test-DisposableRecovery.ps1 -KitRoot $PWD
```

Any blocker stops the procedure. `READY_FOR_UI_VERIFICATION` only permits the
manual sequence below; it is not a signed-package verdict or completed test.
The script performs no installation, deletion, migration or authorization change.

## Execution and evidence

Use `C:\CanvasBridgeDisposableTest` for this test's evidence and synthetic data.
Record the OS build, release versions, artifact hashes and timestamps in the ledger.
Never export generated keys, databases or logs containing capabilities. Capture
only hashes, synthetic results and redacted screenshots. Leave unexecuted stages
as NOT_RUN. A failed prerequisite cannot become PASS by editing the ledger.

1. **Fresh install.** Run the verified baseline installer interactively. Complete
   the genuine setup wizard in Fictional demo or Offline documents mode. Confirm
   live provider access is disabled and no institutional account is connected.
   Record the installed version and successful startup. Do not bypass the wizard.
2. **Fictional task and persistence.** Import `recovery-canary.txt` through the
   normal local-document UI with explicit text sharing. Retrieve it through the
   registered independent-document tool and check the exact sentence. Save one
   local preference. Restart and verify the same document hash and preference.
   With the app stopped, record SHA-256 of its newly generated vault key and
   deletion journal (hashes only). Record the database's normal readiness check.
3. **Upgrade.** Use the official Update interface to select `upgrade.zip`. Its
   existing signature, publisher, expiry, version-direction and schema checks must
   succeed. Review and confirm the actual update. Record the new installed version,
   repeat the fictional task, and compare key/journal hashes and local preference.
   Institutional access must remain disabled. Keep failure receipts if rejected.
4. **Rollback.** Use the official Roll back interface with `rollback.zip`.
   Require its signature, minimum security version and current-schema compatibility
   checks to succeed. Record the restored version and repeat all persistence and
   authorization checks. Do not substitute re-running the same installer.
5. **Uninstall.** Exit the test app and use only this disposable install's registered
   uninstaller. Verify its executable and registration are removed; verify the
   documented retained data/key/journal policy using the synthetic hashes. Do not
   test destruction against the personal installation. Destroy the disposable OS
   after exporting sanitized evidence; never restore its generated credentials here.

OP-07 can pass only when all five stages actually execute on the disposable OS,
all required evidence is present, and no safety boundary was bypassed. Local unit
tests, a preflight receipt, a prepared kit, same-version reinstall, and installer
hashes each cover narrower claims and cannot close this case.
