# Academic provider and extension SDK v1

The public Python/JSON contracts live in `academic/contracts.py`, `providers/base.py`
and `extensions/`. Provider API and extension SDK versions are **1.0.0**, independently
of the application's version. The normalized record format remains `academic-1`.
This is a local implementation, not permission to connect or publish a provider.

## Trust and data flow

```text
Reviewed provider + independent host/provider approvals
  -> versioned capability check -> authorized retrieval -> normalized academic-1
  -> gateway receipt bound to identity, purpose, recipient, operation and data
  -> host-selected numeric projection -> bounded declarative module
  -> authorization/privacy/expiry recheck -> result with original provenance and restrictions
```

Provider adapters are trusted host integration code and must be reviewed and
independently authorized. They are not downloaded or loaded from model instructions,
package entry points or arbitrary manifests. A provider name, credentials or an MCP
interface cannot establish approval. New provider implementations must enforce
`require()` before their own network helpers, preserve normalized labels, and verify
records against trusted source state; the gateway is an additional check.

Untrusted **extension manifests** are data interpreted by a closed numeric language.
They cannot supply Python, JavaScript, native binaries, imports, callbacks, URLs,
filesystem paths, recipients or policy changes. There is no general plugin loader or
model-callable registration operation. Arbitrary native-code extensions are
unsupported; an OS sandbox for them is not claimed. Administrators can register
reviewed declarative modules explicitly in a host-owned `ExtensionRegistry`.

## Provider contract and discovery

Implement `AcademicProvider` with explicit `provider_id`, `api_version`, `supported`,
`capability_fields`, permission requirements, freshness and downstream-sharing
semantics. Implement `require(request, phase=...)`, `verify_record(record, request)`
and `retrieve(operation, request)`. Existing identity systems remain authoritative.
An adapter instance belongs to one scoped analysis; mutable record state must not
be shared across accounts. `describe()` returns a typed `ProviderManifest`.

All five v1 operations have explicit capability entries:

| Operation | Normalized fields available in v1 |
|---|---|
| `list_courses` | courses |
| `get_assignments` | courses, assignments, assignment deadlines |
| `get_grade_summary` | courses, grade categories, assessments/results, grading rules |
| `get_schedule` | courses, events |
| `get_authorized_document` | documents, document parts |

Provenance, permission context, classifications and freshness accompany every
record; advertising a field does not promise a non-null value. Unsupported fields
remain absent and unsupported operations raise a safe error. Capabilities declare
read-only behavior, permission requirements, freshness semantics, downstream sharing
(`local_only`, `per_request_authorization`, or `unavailable`) and bounded resources.
`permission_granted` is always false in discovery. The operation-keyed
`get_source_capabilities()` wrapper remains compatible with existing callers.

The gateway enforces at most 512 normalized records, 2 MB serialized evidence and a
120-second asynchronous retrieval deadline, or the adapter's narrower limits. This
deadline bounds cooperative provider I/O; untrusted document CPU/memory remains
controlled by the existing isolated parser workers. A provider's direct helpers
must preserve those underlying controls. Capability scope and sharing restrictions
are checked again when a receipt is consumed or released. A changed contract cannot
reuse an earlier receipt to authorize broader operations.

## Implemented provider targets

| Provider | Supported behavior |
|---|---|
| Synthetic | Fictional courses, assignments and point grades; no LMS connection |
| Local document | Existing permitted text extraction, local recipient only |
| Local grades | Explicit bounded numeric JSON import; local ownership permit, local recipient, no LMS identity |
| Authorized Canvas | Existing grade adapter and independently enforced provider/institution/user/recipient checks |
| Future approved MCP | Versioned discovery with all retrieval unsupported; no speculative endpoint or enable flag |
| Other LMS | Author an independently reviewed adapter; no Moodle or other live integration is claimed |

## Declarative extension contract

`ExtensionManifest.model_json_schema()` and `ProviderManifest.model_json_schema()`
provide machine-readable contracts. `ExtensionRegistry.register(bytes)` validates a
maximum 64 KB UTF-8 JSON manifest, rejects duplicate keys, verifies compatibility,
and executes 2–16 supplied deterministic vectors before registration. Up to 32 exact
module versions may be registered in one host registry. Re-registration cannot
overwrite a module version; execution must name an exact version, never `latest`.
Registration vectors demonstrate reproducibility, not independent validation of an
author's algorithm or scientific claims. Hosts must review new modules and vectors.

Each manifest declares:

- SDK minimum version, module ID/version and normalized input schema.
- Required provider capabilities and permission purpose.
- Input and output numeric schemas with bounds.
- An explicitly supported host projection and a loop-free arithmetic graph.
- Deterministic tests and narrower optional resource budgets.

V1 supports the `grade_points_v1` projection and `grade_planning` purpose. It supplies
only `earned_points`, `possible_points`, `future_possible_points` and
`future_score_percent`. It never supplies record bodies, document text, identifiers,
tokens, connections or a gateway object to the interpreter. Provider-independent
grade calculation determines the eligible observed points. Future points and scores
are explicit user assumptions, not inferred source facts. New projections require
host review, a compatible SDK change, and authorization/privacy regression tests.

The language supports add, subtract, multiply, divide, minimum and maximum. There
are no loops or recursive expressions; references can only point to inputs or earlier
steps. Limits are 64 steps, 4 KB numeric input, 4 KB numeric output and 100 ms checked
between bounded operations, with bounded Decimal magnitude/digits/exponents and
four-decimal half-up output rounding. Invalid arithmetic, budget exhaustion, wrong
schemas or failed vectors return static errors. Budgets cannot exceed host limits.
The graph's finite operation and operand bounds provide the resource isolation;
this is not a preemptive general-purpose execution sandbox.

The host preserves source provenance, freshness, uncertainty and restrictions in
the result envelope. Modules cannot emit or overwrite that envelope. The gateway
rechecks identity, connection state, receipt integrity, purpose, recipient and source
restrictions after calculation. An expiry or revocation during execution denies
the output. External MCP publication still requires the established final egress
controls; these local SDK entry points do not add an MCP tool or sharing grant.

## Grade forecasting example

`extensions/forecast.py` is a standalone declarative module using only the SDK.
The engine and manifest do not use Canvas identifiers or data formats. Run:

```console
canvas-academic demo-forecast --future-points 100 --future-percent 90
```

The fictional current 170/200 points is 85%. Assuming another 100 possible points
at 90%, the forecast is 260/300 = 86.6667%, a 1.6667 percentage-point change. This
is a hypothetical aggregate scenario, not an official final grade or a guarantee
about which work remains. V1 refuses weighted/drop policies and incomplete or
unresolved grades rather than inventing a forecast. Existing richer core grade
calculations remain available through their established interfaces.

For an explicitly permitted local numeric import (for example, manually exported
numeric values from the user's spreadsheet), create `local-grades-1` JSON:

```json
{"schema_version":"local-grades-1","complete":true,"rows":[
  {"possible":"100","result":{"state":"posted","score":"80"}},
  {"possible":"100","result":{"state":"posted","score":"90"}}
]}
```

```console
canvas-academic forecast-grades own-grades.json --acknowledge-own-material --future-points 100 --future-percent 90
```

The console host supplies a five-minute, hash-bound ownership permit using the
existing local-import mechanism. `complete` and points-policy applicability are
user assertions; they never become institutional verification. Unknown fields,
personal identifiers and unsupported numeric values are rejected. Local processing
does not authorize model transmission. At most 100 rows and 64 KB are accepted;
raw bytes and permit state are cleared at completion. No database, environment
credentials, synchronization, live LMS retrieval or persistent cache is required.

For embedded use, register `grade_forecast_manifest()` and call
`registry.execute("grade_forecast", "1.0.0", provider.gateway, authorized_input,
assumptions=...)`. Acquire `authorized_input` through `provider.get_grade_summary()`.
Passing plain normalized JSON or a model-supplied connection ID is insufficient.

## Compatibility and migration

Version policy follows [Semantic Versioning 2.0.0, sections 1–8](https://semver.org/spec/v2.0.0.html)
(reviewed 2026-10-26): compatible additions increment minor; incompatible changes
increment major; compatible fixes increment patch. This implementation accepts
stable numeric `MAJOR.MINOR.PATCH` values only. Prereleases/build labels are outside
the supported SDK subset. A consumer's required SDK version must be no newer than
the host and share its nonzero major version. Module versions are separately pinned.

Pre-SDK adapters must explicitly declare v1, fields, limits and sharing semantics
after reviewing their implementations. Missing versions fail closed; there is no
automatic legacy capability inference. Unknown operations/fields are rejected,
so an older adapter cannot silently advertise a later capability. The old discovery
wrapper still returns operation-keyed supported/reason fields, now with metadata.

For breaking changes, publish a new major interface, an explicit migration guide
and separate compatibility fixtures; retain the previous major in a deliberate
adapter or reject it. Never silently rewrite manifests or relabel old records.
Private in-process gateway receipts gained operation binding in this migration and
must be reacquired; they are ephemeral and were never a serialized public API.
Installing a newer module version does not change the selected version. A host
upgrade must rerun the pinned compatibility/vector tests before activation.

## Verification and limitations

`tests/test_extension_sdk.py` verifies cross-provider equality using synthetic/local
and synthetic-transport Canvas adapters, explicit missing capabilities, authorization
failure propagation, operation binding, downgrades, privacy preservation, malformed
manifests, version handling, pinned upgrades, no network/filesystem access, resource
exhaustion and revocation during execution. No institution-controlled records are used.
The compliance registry includes this SDK; source changes invalidate old evidence
receipts. External approvals and platform acceptance remain separate release gates.
