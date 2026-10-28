# Security, abuse prevention and supply-chain verification

Date: 2026-10-25. Scope: local implementation, synthetic fixtures and public
dependency advisory/release metadata. No real Canvas requests, permission/course
selection changes, provider credential changes, deployment, commits, publication
or history rewriting were performed.

## Implemented

- Shared production outbound concurrency/token budgets, full provider cooldowns,
  sustained-failure circuits with one recovery probe, bounded limiter state and
  cancellation-safe streaming leases. Each actual send retains its existing
  identity/policy permit. Separate global ingress and verified-principal MCP limits.
- Total outbound header/body and ASGI request deadlines supplement existing
  per-operation limits. Uvicorn connection/backlog/keep-alive limits are explicit.
  API compression is rejected before iteration. Long Retry-After values no longer
  become three-second retries; both delta seconds and HTTP dates are supported.
- Weak file-lock registry preserves queued waiters across retention cleanup;
  existing source/epoch/owner-bound caching and worker isolation remain in place.
- Critical dependency/build/scanner pins; Python and Node source/hash validation;
  locked CI installs; license metadata gates, Bandit/Ruff, dependency audits,
  redacted current-source/full-history Gitleaks checks, Trivy config/image gates
  and Python+Node/image SBOM generation. Desktop CI screens platform packaging
  licenses as well; its actual artifacts remain a separate review gate.
- Expanded [surface inventory/threat model](../../docs/threat-model.md),
  [incident response](../../docs/runbooks/incidents.md),
  [patch and license procedure](../../docs/supply-chain-security.md) and
  [reporting policy](../../SECURITY.md).

The audit found three pypdf 6.21.1 denial-of-service advisories:
CVE-2026-115572, CVE-2026-115585 and CVE-2026-115580. The pin/lock/runtime were
updated to 6.21.2, the fixed release. The maintainer documents the fixes in the
[6.21.2 release](https://github.com/py-pdf/pypdf/releases/tag/6.21.2) and
[repeated missing-object advisory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-6c7f-9265-g8fw).

## Actual checks

| Check | Result and boundary |
|---|---|
| Opening full-suite baseline | Reused prior prompt's 1,193 passed / 27 skipped result; no redundant opening run |
| Focused request, service-security and retention tests | 81 passed |
| Full suite after main hardening/parser update | **1,231 passed, 27 skipped**, 368.86 seconds |
| Final deadline changes and HTTP/OAuth/approval/egress boundaries | **93 passed**, 50.40 seconds; includes the two new deadline cases. This targeted run followed the full sweep; the full sweep was not repeated after the final deadline addition |
| New request-limit and supply-chain tests | 40 passed; fake clocks cover cooldown/circuit/expiry, events cover cancellation/stream concurrency; no sleep-based expiry assertions |
| Ruff check / format | Passed; 257 Python files formatted |
| `git diff --check`, workflow YAML parse | Passed |
| `uv lock --check`, `uv pip check` | Passed |
| `pip-audit --local` after pypdf patch | No known vulnerabilities reported for installed dependencies at scan time |
| `npm audit` including development dependencies | Zero reported vulnerabilities |
| Bandit (`src`, medium/high severity and confidence) | Zero findings; fixed trusted Linux bootstrap `exec` has a specific reviewed B102 suppression after OS restrictions |
| Gitleaks 8.30.1 full Git history | 52 commits / about 5.90 MB scanned, no findings after the narrow manifest exception |
| Gitleaks current staged source and saved SBOM | No findings; source scan about 4.58 MB, SBOM about 405 KB |
| Synthetic secret canary | Scanner rejected the temporary fictional credential fixture with two detections; no live credential used |
| License metadata screen | 127 records: 113 allowed, seven conditional reviews, seven not installed on this platform, zero blocked. Conditional terms and missing platform coverage are documented, not inferred as universal compatibility |
| Saved CycloneDX 1.5 SBOM | 128 dependency components / 129 dependency nodes; schema validation passed |

The initial history scan flagged five generic-key candidates in the historical
source manifest. Each was a 64-character SHA-256 for a named Python source file;
we verified the hashes against the matching Git revision (accounting for checkout
line endings). The exception requires both that exact manifest path and the
strict source-path/hash line format. No global secret-rule or test-directory
suppression was introduced.

New negative fixtures cover modified dependency registries, missing/weak hashes,
unreviewed licenses, altered scanner archives, traversal-bearing archive members,
global and per-key saturation, rate exhaustion, retained cooldowns, one circuit
probe, older-success races, stream cancellation/deadlines, no-permit network
denial, ingress header spoofing and the queued file-lock cleanup race. Existing
synthetic tests cover identity/scope/egress bypass, prompt injection, redirects,
token leakage, malicious PDF/ZIP/XML/media, parser failure/timeout, path escape,
cache revocation and offline tools.

## Artifacts and remaining gates

[Python and Node SBOM](security-sbom-2026-10-25.cdx.json) records the locked graph
including optional/build platforms. Local ignored reports are under `.local/`;
they are not deployment proof. CI additionally generates the actual image SBOM.

The 27 skips are 13 Linux kernel tests, seven disposable-PostgreSQL tests,
five explicit native converter tests and two optional OCR tests. Windows has no
Docker or installed WSL distribution, so Trivy config/image execution and Linux
container acceptance were **not** performed here. CI gates were added and syntax
checked, not represented as a completed remote CI run.

No optional LibreOffice/Tesseract runtime was installed or changed. Actual native
artifact inventory/licenses/signatures, clean platform builds, independent
security review, designated incident contacts, edge TLS/connection protection
and coordinated quotas for multiple service processes remain external-release
requirements. Provider/institution approvals remain separate and are not created
by these security changes. No general compliance certification is claimed.
