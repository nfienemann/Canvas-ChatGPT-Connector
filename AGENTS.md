# Working agreement

Preserve the product constraints in Codex_Spec.md and the evidence boundaries in
evidence/release-gates.md. Do not expose Canvas writes, roster access, arbitrary
HTTP/SQL tools, student token-paste onboarding, or a second chatbot/dashboard.

Use synthetic fixtures. Do not commit secrets, real academic records, database
backups, private operator configuration, or generated credentials.

When consecutive prompts would rerun the same full suite without a relevant
change, the second redundant full run may be skipped. Record actual checks.
