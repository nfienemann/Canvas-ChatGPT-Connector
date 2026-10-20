# Contributor guide

Read README, AGENTS.md and architectural decisions. Use `uv sync --frozen`.
All committed fixtures must be synthetic.

Run focused tests while changing code, then the full suite and Ruff checks before
release. PostgreSQL tests are explicitly skipped without a disposable test
database. Never relabel a skip as a pass. Avoid repeating an unchanged full suite
solely because a new prompt starts.

Maintain the official MCP transport, typed envelope, owner/connection filters,
student-only routes, explicit missing states, date-only semantics, partial
coverage and deletion fencing. Course text cannot grant scope or authorize exports.

Do not add a model API dependency, student billing, academic dashboard, generic
proxy, roster access or Canvas academic writes. Calendar tools remain absent
until independent provider authorization and a tested approval mechanism exist.

Update evidence with precise scope. Fixtures do not prove a university, ChatGPT
client, mobile surface or public listing works. Public claims need observations.

Dependency changes must update `uv.lock`, pass security/contract checks and
`pip-audit`, and consult current vendor documentation for auth/transport changes.
Use SECURITY.md for vulnerability reporting.

The owner has not selected a project license. Do not announce an approved
open-source release as if that decision were already made.
