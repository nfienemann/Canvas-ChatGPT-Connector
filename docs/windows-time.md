# Windows clock maintenance for a private connector host

Strict JWT validation depends on a correctly synchronized host clock. A small
negative offset can reject a newly issued token as `MCP_TOKEN_NOT_YET_VALID`
even when an older token succeeds. Preserve signature, issuer, audience, expiry,
issued-at, not-before, subject and scope checks; fixing the operating-system
clock does not require changing OAuth or Canvas permissions or credentials.

## Inspect before applying

Run `scripts/windows_time_sync.ps1` without arguments for read-only configuration
and synchronization status. `-Apply -WhatIf` describes the proposed action
without writing settings or backups. Also inspect `w32tm /query /peers`, recent
Windows Time events, and a bounded `w32tm /stripchart /computer:time.windows.com
/dataonly /samples:3` measurement. A small offset alone does not prove that the
service will keep running or has an automatic next poll.

The repair script is deliberately limited to a non-domain, non-policy-managed
Windows host already using enabled NTP with `time.windows.com,0x9`. It refuses
other configurations. Domain or policy-managed machines should use their
administrator's time hierarchy, not this repair.

## Apply the supported host repair

From PowerShell opened as administrator, run the script with `-Apply`. It:

1. Saves the prior clock configuration and service triggers under the current
   user's Local AppData `CanvasBridge/clock-backups` folder, outside Git.
2. Sets Windows Time to Automatic and removes its start/stop triggers, following
   [Microsoft KB 2385818, method 1](https://learn.microsoft.com/en-us/troubleshoot/windows-client/active-directory/w32time-not-start-on-workgroup).
3. Sets the special poll interval to 3,600 seconds, within the existing minimum
   and maximum bounds, following
   [Microsoft KB 3205089, workaround 1](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/w32time-sync-specialpollInterval-ignored).
4. Restarts only Windows Time, verifies those persistent settings, then requests
   ordinary synchronization and prints its result.

The existing time source, Windows service account/ACLs, firewall, timezone,
connector service, configuration, credentials and selected courses are untouched.
No privileged scheduled task, custom clock-setting loop, new account, token
leeway or disabled authentication check is introduced. The script does not
elevate itself or bypass PowerShell execution policy.

If immediate resynchronization fails, the script reports that separately from
successful settings application. Check events and status before concluding the
clock is healthy. Network loss, sleep or an unavailable time source can still
interrupt synchronization; configuration evidence is not an uptime guarantee.

## Verify and recover

Verify `Get-Service W32Time` reports Running, its startup type is Automatic,
`sc.exe qtriggerinfo W32Time` has no triggers, and `SpecialPollInterval` is 3,600.
Look for `Leap Indicator: 0`, a valid stratum, the expected source and a recent
successful sync in `w32tm /query /status`. Peer information should show the next
poll scheduled. Windows may report an internal poll exponent separately from
the special-poll schedule; record both instead of assuming they are identical.
Check actual authenticated connector calls afterward, without inspecting tokens.

Keep the printed backup path locally. For rollback, an administrator can restore
the original startup type from `before.json`, restore its `SpecialPollInterval`,
import the saved `triggers.reg` when one exists, and restart Windows Time. Apply
only the backup for this machine; do not import a different host's settings.
Restoring Manual startup can reintroduce the original stop/start behavior.

Windows packaged apps can redirect Local AppData into their package-private
`LocalCache/Local` directory. If Codex can open an operator file but ordinary
PowerShell cannot, resolve its actual filesystem path before executing it. Do
not create a second configuration or copy credentials to a guessed location.

Git tracks this generic procedure and script, not a user's clock backups or
private connector configuration. Pushing code does not apply Windows settings
on another computer; each host needs its own authorized operating-system setup.
