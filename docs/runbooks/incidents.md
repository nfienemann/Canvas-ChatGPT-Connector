# Incident and recovery runbook

## Classification and ownership

| Severity | Examples | Immediate response |
|---|---|---|
| Critical | Suspected cross-user disclosure, credential theft, approval bypass, parser escape or compromised release artifact | Isolate affected service/workers and downloads; stop distribution; assign incident lead and restricted evidence custodian |
| High | Repeatable unauthorized access attempt with uncertain containment, revocation failure, exploitable dependency in enabled processing | Disable affected live connection/workflow, restrict cache access and investigate scope before resuming |
| Moderate | Contained parser crash, bounded abuse, unavailable upstream, unsuccessful exploit blocked by policy | Preserve minimal reason codes/counts, throttle or disable affected capability, triage and patch |
| Low | Documentation or configuration issue with no known data exposure | Track owner and correction; escalate if new evidence changes impact |

These are operational priorities, not legal conclusions or universal reporting
deadlines. Before any pilot, appoint an on-call operator, security lead,
institution contact and privacy/legal escalation contact in private operator
configuration. No contacts are invented by this repository. Use only the
deployment's approved channels; no automatic public issue, email or student
notification is sent by the software or this runbook.

## Containment and credential handling

1. Record a random incident identifier, UTC start time, affected release digest,
   safe reason codes and counts. Record suspected impact separately from confirmed
   disclosure. Stop the affected API/worker process or remove its ingress using
   the deployment's service supervisor. Preserve unrelated offline study tools.
2. Deny/revoke the affected approval/connection in the trusted administrator
   workflow. Invalidate application sessions, temporary links, pending jobs and
   in-memory derivatives. Local disconnect fences retrieval even if the provider
   is unavailable; record provider revocation as pending until positively confirmed.
3. Isolate affected cache/job/backup locations with operator-only access. Retain
   only the minimal evidence needed for investigation under an explicit, expiring
   preservation hold. Do not collect course bodies, signed URLs, raw tokens, full
   correspondence or memory dumps by default. Hash artifacts locally; restrict any
   necessary raw evidence to encrypted incident storage, never Git or MCP.
4. Revoke compromised upstream/application refresh tokens and rotate relevant
   client/issuer/vault credentials through their actual authorized administrators.
   A network failure is not successful revocation. Do not destroy a vault key needed
   to preserve or re-encrypt retained evidence without a reviewed recovery plan.
5. For a compromised dependency/build, quarantine output artifacts and stop
   publishing; identify affected hashes and build inputs. Rebuild in a clean
   environment after the patch review. Do not reuse suspect runtime caches.

## Communication, recovery and review

The incident lead supplies the authorized institution/provider/security contacts
with a minimal factual timeline through the approved channel. Privacy/legal
owners decide applicable notification duties and timing from the facts,
contracts and jurisdiction; do not assume a single breach-notification deadline.
Never use an issue tracker to disclose student content or credentials.

Before reopening, verify the root cause and patch, rerun negative authorization,
egress, revocation, worker and affected supply-chain checks, and confirm fresh
approved identity/connection state. Verify temporary links are invalid, pending
jobs cannot resume and restored backups cannot reactivate deleted or revoked
accounts. Record the authorized recovery decision, residual restrictions and
monitoring owner. Require independent review for a critical trust-boundary issue.

Close with a sanitized timeline, affected versions, confirmed scope, corrective
actions/owners and evidence-retention deadline. Verify release artifacts/SBOMs
match the reviewed source. Expire the preservation hold and perform verifiable
local deletion when authorized; report backup/downstream limitations honestly.

## Existing recovery constraints

For a suspected cross-user disclosure, wrong student date, unauthorized action,
credential leak or deletion resurrection: stop the affected release and API/
worker processes, preserve minimal sanitized evidence, and notify the designated
operator through the deployment's approved process. No incident contact has been
appointed for this local-only build.

Revoke affected credentials with the actual issuer/provider where supported.
Report local disable and confirmed remote revocation separately. Rotate compromised
vault/issuer credentials through a reviewed re-encryption/reauthorization procedure;
automated managed-key rotation has not been implemented.

For an upstream outage: keep failed refreshes partial/unavailable, preserve the
last successful timestamp, and do not claim an empty workload. Permission failures
remove access to cached material. Do not retry authorization failures indefinitely.

For restore: isolate the target, migrate an empty database, supply the latest
independently retained deletion journal, restore encrypted data, verify the
deletion canary and scoped read, then reopen only after review. Restored jobs remain
cancelled. Never restore a pre-deletion database without the current fences.
