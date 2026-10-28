# Provider-independent academic architecture — local verification

Date: 2026-10-25. All records used in these checks are fictional. No institutional
account was contacted, credential changed, approval created, or deployment made.

## Implemented increment

- Added immutable `academic-1` models for courses, assignments, deadlines, grade
  categories/results, assessments, events, documents/parts, source references,
  permission context, restrictions and freshness/provenance.
- Extracted the existing Decimal grade arithmetic into `academic/grade_engine.py`.
  Existing MCP calculations now pass authorized normalized evidence through
  `academic/services.py`. Compatibility exports and MCP response contracts remain.
- Moved Canvas grade acquisition into `providers/canvas_grades.py` and introduced
  `AuthorizedCanvasProvider`, which reuses existing identity, course selection,
  connection epoch, provider/institution approval and egress controls.
- Added a closed fictional provider and an offline `canvas-academic` entry point.
  The standalone demo does not initialize Canvas, account, settings, database or
  vault services. Existing application-level synthetic fixtures remain available.
- Added a local-document adapter accepting bounded bytes and an explicit expiring
  user permission tied to their hash. Binary text extraction reuses existing
  isolated workers. It permits local processing only, preserves parser limitations
  and does not claim visual interpretation or verified ownership.
- Reserved a future MCP adapter with no supported retrieval capabilities. Its
  public and direct helper paths deny; no future interface or reuse right is assumed.

Normalized metadata cannot grant access. Input receipts bind exact data and request
context within one trusted host process. Current policy is checked again before
analysis and output. Unknown/restricted classifications, changed source scope,
revocation, expired permissions and substituted identities/recipients fail closed.
No additional login or token system was introduced.

## Executed checks

| Check | Actual outcome |
|---|---|
| Full local pytest suite | **1,265 passed, 27 skipped** in 389.97 seconds |
| Final provider, existing grade-audit and egress-contract suites | **79 passed** in 36.15 seconds |
| Ruff check and format check | Passed; 272 files formatted correctly |
| Git whitespace check | Passed |
| Frozen lockfile check | Passed; 86 packages resolved without lock changes for this increment |
| Wheel build | Passed; includes the new packages and `canvas-academic` entry point |
| Cold wheel import and synthetic calculation | Expected `85.0000`; application socket connections/DNS blocked; no Canvas/config/storage/vault startup |
| Bandit medium/high severity and confidence checks | Passed; existing reviewed `B102` suppression emitted a no-finding warning |
| Source secret scan | Gitleaks: no leaks found |
| Dependency license metadata | 127 packages checked; zero blocked |

The full suite completed before the last localized provenance/completeness changes.
The final 79-test run covers those changes, all 38 new provider-architecture cases,
the existing 30 grade-audit cases, and 11 egress-contract cases. Counts overlap and
must not be added together. The unchanged opening full baseline was not repeated.

The final follow-up specifically tests missing Canvas source versions without
fabricated verification; Word sections, spreadsheet sheets and slide locators;
preserved parser warnings; unreadable/empty content; and rejection of a grading
receipt as document evidence. The built artifact was refreshed after these edits.

Other new cases cover equivalent arithmetic across fictional providers, offline
network prohibition despite live environment flags, scope/recipient substitution,
forged or changed receipts, expiration using an injected clock, missing scores,
classification propagation and changes, explicit local permission, local revocation,
prompt instructions remaining data, disabled-provider indirect calls, and an actual
isolated PDF worker invocation. Existing transport tests exercise the legacy MCP
grade and egress contracts against synthetic sources.

Windows event-loop initialization creates a local self-pipe. The cold-wheel check
initializes that runtime first, then blocks application socket connections and DNS
before importing and executing the offline entry point. This tests absence of LMS
network access; it is not a claim that Python uses no OS networking primitives.

## Evidence limits and remaining migration

The 27 skips are 13 Linux-kernel tests, seven disposable-PostgreSQL tests, five
optional native-converter tests and two optional OCR tests. These environment gates
remain open; no remote CI, platform installer, or deployed-MCP acceptance is claimed.

This is the requested first extraction, not a completed rewrite of every service.
Planning, workload analysis, schedule reconciliation, calendar proposals and visual
interpretation retain their existing controls and await incremental normalized-input
migrations. Legacy syllabus discovery also remains outside the new Canvas grade
collector. See the [migration map](../../docs/provider-architecture.md).

Local ownership attestation is not a copyright review or institutional/vendor
approval. Privacy inspection is bounded and is not proof of anonymity. A capable
adapter, working credential, MCP protocol or successful calculation never establishes
permission for an institution or a downstream recipient. Public release remains
subject to the [release gates](../release-gates.md).

Ignored local execution logs are under `.local/provider-*`; the wheel is under
`.local/provider-build/`. This report contains no approval correspondence, personal
records, tokens or private operator configuration.
