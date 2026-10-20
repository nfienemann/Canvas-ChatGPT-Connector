# Incident and recovery runbook

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
