# Authorization-policy gateway — local validation

Date: October 25, 2026. Scope: the first authorization and policy enforcement
specification supplied by the owner. All records, administrator keys, academic
data and upstream responses used for testing are synthetic.

The implementation adds independently signed provider/institution/sharing
approvals, strict scoped decisions, encrypted private evidence references,
network guards, MCP response fencing and HTTP download/export sharing checks.
Existing user/resource authorization remains required. No approval mutation tool
was added, and no real approval was generated or inferred.

## Actual checks

- Initial affected retrieval/authorization suite: **124 passed**.
- Initial gateway and local MCP/HTTP contract regressions: **57 passed**.
- OAuth, personal-profile, settings and MCP compatibility run before the final
  full suite: 93 passed and one new fixture failure; the filename fixture was
  corrected and the gateway suite above passed afterward.
- First full suite: **1,016 passed, 27 skipped** in 318.38 seconds.
- Final review added verified OAuth recipient identity, redaction for stale user
  scope, overlapping-record rejection and per-chunk user-scope checks. The
  affected gateway/authentication/permissions/OAuth/deletion/MCP/download suite:
  **261 passed** in 62.84 seconds. The identity fixture expectation was updated
  to include only the newly retained verified client ID alongside issuer.
- Final full suite after those changes: **1,024 passed, 27 skipped** in 295.07
  seconds. This includes **62 gateway/MCP/HTTP regression cases**. Skips were
  13 Linux-kernel tests on Windows, seven tests requiring a disposable PostgreSQL
  database, five requiring a trusted native converter, and two requiring OCR.
- `ruff check .` and `git diff --check`: passed.
- `ruff format --check` on all **25 Python files touched by this implementation**:
  passed.
- Formatting was applied to the gateway's edited Python files with an AST
  comparison confirming no behavioral change. Repository-wide format checking
  also found existing formatting differences in five unrelated files:
  `academic_intelligence.py`, `course_files.py`, `normalize.py`, `retrieval.py`
  and `tests/test_inventory_followup.py`. Those existing edits were preserved.

The regressions cover absent/pending/denied/expired/revoked approvals, each
independent authority, mismatched institution/mechanism/deployment/category/
activity/recipient, conditions, signature/delegation/evidence tampering, ordinary
user isolation, injection text, direct helpers, retries, cached results, final
response revocation, verified-client recipient binding, download recipients,
overlapping records, stale status redaction and synthetic-only transports.

## Evidence boundary

Local tests exercise the real MCP and HTTP transports with fictional upstream
data. They do not establish production deployment, ordinary ChatGPT acceptance,
external permission or legal compliance. No private operator configuration,
credential, course selection or live service state was changed. No real Canvas
request was made for this work. Existing checkout changes were preserved.

Deployment requires actual verified approvals and an administrator-controlled,
read-only service trust/evidence mount; signing and evidence-decryption keys must
remain outside the service. The gateway cannot replace those external decisions.
