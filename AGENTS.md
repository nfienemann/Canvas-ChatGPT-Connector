# Working agreement

Preserve the product constraints in Codex_Spec.md and the evidence boundaries in
evidence/release-gates.md. Do not expose Canvas writes, roster access, arbitrary
HTTP/SQL tools, student token-paste onboarding, or a second chatbot/dashboard.

Use synthetic fixtures. Do not commit secrets, real academic records, database
backups, private operator configuration, or generated credentials.

When consecutive prompts would rerun the same full suite without a relevant
change, the second redundant full run may be skipped. Record actual checks.

Start with the [contributor guide’s troubleshooting table](docs/contributor-guide.md#where-to-start-when)
for missing files, incomplete document reads, or failed downloads.
When resuming, read `.local/dev-handoff.md` if present. Refresh it when pausing
or handing work over, using the [private handoff template](docs/contributor-guide.md#private-session-handoff).
Before reusing a full-suite result, compare its commit and relevant working-tree
changes with the current checkout.
