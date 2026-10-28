# Provider portability and extension SDK: scoped verification

Verified locally on 2026-10-26 using fictional records. No live integration,
deployment, institution authorization or publication approval is established.

## Delivered

- Provider API and declarative extension SDK 1.0.0, retaining normalized `academic-1` records.
- Explicit operation, field, permission, freshness, resource and sharing discovery; no capability is an approval grant.
- Operation-bound authorization receipts, downstream-sharing checks and provider resource limits checked at retrieval and again before release.
- A closed numeric extension language with explicit input/output schemas, deterministic registration vectors, exact module versions and bounded arithmetic/time/size budgets. No Python/native plugin loading, file, network, token or raw-record access is exposed to manifests.
- An independent grade forecast module and permitted local numeric-grade adapter using existing ownership, expiration and revocation controls. Weighted/drop policies and unresolved/incomplete evidence stay indeterminate.
- Migration guidance, JSON schemas and governance control `CB-SDK-01`.

See [the SDK guide](../../docs/provider-extension-sdk.md) for public contracts,
example commands, trust assumptions and the deliberately limited v1 projection.

## Actual validation

The final scoped run passed **125 tests, zero skipped, zero failures**:

- `tests/test_extension_sdk.py` — 50 cases.
- Existing provider architecture and grade-audit integration tests.
- All seven compliance walkthroughs.

The SDK cases cover equivalent forecasts from fictional, local and synthetic-transport
Canvas adapters, incompatible versions, missing fields/capabilities, authorization
failure propagation, privacy metadata preservation, operation substitution,
sharing downgrades, revocation during execution, pinned module upgrades,
I/O denial, arithmetic/time/output exhaustion and malformed manifests.

Scoped Ruff lint and formatting, Bandit at the project's medium/high threshold,
and a redacted Gitleaks scan of the SDK source all passed. The secret scan is not
a new Git-history or whole-repository assessment. Both actual console commands
were exercised: the fictional demo and permitted local numeric import returned
85.0000% current and 86.6667% forecast for the same explicit future-score assumption.

An earlier wider focused run also passed 151 tests, including the compliance
reporting tests. After confirmation that another chat was editing discussion-related
files, the user requested SDK-scoped validation. No full suite was rerun and no
fresh whole-repository readiness claim was produced. Unrelated formatting findings
and concurrent edits were preserved.

## Evidence identity and artifacts

The final test recorder correctly reports that the **whole repository changed**
during execution. Separately, all 30 explicitly recorded SDK, integration-test,
documentation and registry files stayed unchanged and still matched after the run.
Their path/hash map is in `.local/provider-sdk-review/verification.json`.

The SHA-256 of that sorted path/hash map is
`2e918ae89925ae7282e60704ea5be52b81d1094f363f5749663608f8a74e04b5`.
This is a scoped snapshot, not the repository-wide compliance fingerprint. The
compliance generator must not promote a stale or changing-source test receipt.

The ignored local review package contains:

- `provider-api-1.0.0.schema.json` and `extension-sdk-1.0.0.schema.json`.
- `grade-forecast-1.0.0.json`, the independent declarative example.
- `synthetic-provider.json`, discovery with explicit permission-granted false.
- Fictional local input and both console demonstration outputs.
- Sanitized per-case test results, scoped file hashes and static-check statuses.

The registered example module's pinned digest is
`e0af0b38cdb58afdf88c9d6f677b7f50baf1b8ecf5a66926c2957854f0c9d4c3`.
Three built-in vectors pass before registration, and a compatibility regression
pins this version's serialized content. New module versions do not replace the
selected version automatically.

## Remaining boundaries

Only the grade-points projection and loop-free numeric graphs are supported in v1.
Arbitrary native extensions and additional live LMS providers are not implemented.
Adapters remain reviewed host code with independent upstream/institution/user/egress
checks; the numeric language is not a sandbox for arbitrary host code. Registration
vectors do not certify an author's algorithm or any institution's grading policy.
Local ownership attestations do not grant external transmission. New providers,
projections and modules require review; release approval gates remain independent.
