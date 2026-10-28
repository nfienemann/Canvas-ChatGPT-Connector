# Third-party privacy validation — October 25, 2026

Local implementation and synthetic tests only. No real Canvas requests, changes
to production credentials, private-service migration/restart, deployment or
publication were performed. This record does not establish vendor/institutional approval or
anonymity of arbitrary real-world content.

## Implementation

- Positive schemas at every enabled Canvas endpoint; exact verified own-user
  binding for self-records; preservation of course/access restrictions before
  personal fields are discarded.
- Local bounded text inspection and known-alias removal. Unknown fields are
  omitted. Uncertain personal content is withheld with fixed diagnostics.
- Existing Vault-derived HMAC pseudonyms scoped to owner, institution, connection,
  course, entity, epoch and operator rotation. No mapping database or resolver.
- Sanitized document text/properties before encrypted cache storage, Office
  auxiliary XML inspection, PDF annotation-author aliases, post-OCR inspection,
  and parser revision invalidation of older extraction caches.
- Independent signed privacy modality reviews using the existing administrator
  approval records. Original bytes and pixels are never cleared by text filtering.
- Final structured/text/private-metadata inspection, request-local exact response
  receipts, fixed resource/catalog snapshots and safe SDK/protocol errors.

The [implementation and tool inventory](../../docs/third-party-privacy.md)
documents trust boundaries, changes to existing workflows and operator decisions.

## Checks

The prior task's 1,149-pass/27-skip full run served as the starting baseline; no
redundant opening full suite was run.

- 97 focused repair/compatibility checks passed after fixing preservation of
  invalid-vs-absent states, course restrictions, lock flags and owned planning maps.
- 100 privacy/egress checks passed, including local HTTP/MCP transport tests.
- All 44 new privacy tests passed after the independent synthetic-revocation test
  exposed and verified the pseudonym helper's additional state/expiry check.
- Final full suite against the completed code: **1,193 passed, 27 skipped in
  361.76 seconds**. This includes all 44 new privacy tests. The skips require
  a Linux kernel, disposable PostgreSQL, or optional native conversion/OCR
  runtimes unavailable in this Windows run; they are not counted as passes.
- Ruff lint, repository-wide formatting and `git diff --check`: passed at completion.
  Existing CI automatically includes the new tests; no remote CI run or packaged
  desktop build is claimed.

The new cases cover direct and nested identifiers, unknown/person-shaped records,
first-party grades, aliases, encoded text, sensitive contexts, biomedical
preservation, document properties/comments/notes/revisions/annotations, hash and
modality binding, final MCP serialization, forged envelopes, alternate content
channels, catalog mutation, request concurrency, key/scope separation, rotation,
deletion, revocation and bounded processing. Existing authorization, identity,
retention, downloads, file analysis and academic regression suites remain part of
the full run. Synthetic real HTTP/MCP evidence is not deployed-client acceptance.

## Bounded benchmark

One local measurement, with Python `tracemalloc` enabled: 2,000 structured records,
222,021 input JSON bytes, 0.1541 seconds, 623,005 peak tracked allocation bytes.
All 2,000 safe academic records survived; unknown private fields were omitted.
This measures Python-tracked allocations, not whole-process RSS or native-worker
memory, and is not a production latency guarantee.

All eight biomedical vocabulary fixtures remained unchanged (0/8 changed),
including gene symbols, scientific names, formulas, identifiers and a citation.
That is a small synthetic compatibility result, not a general false-positive rate.

## Limits and release gates

Automated patterns do not detect every identity, language, indirect narrative,
handwritten annotation or identifying combination of facts. Binary media and
uninspected/custom document objects require the applicable content/privacy review.
Pseudonyms remain personal data. No test proves universal deidentification.

Live reviewers must establish actual provider/institutional permission, exact
recipient and purpose, content rights, privacy review by modality, evidence
custody/expiry and operational controls. Missing or changed reviews fail closed.
Unknown fields/properties may disappear and withheld text may lose detailed
locators; these are documented compatibility changes. Original downloads remain
unchanged originals. Offline fictional academic tools remain available.
