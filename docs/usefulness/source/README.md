# CanvasBridge: six usefulness-first specifications

Prepared for Nick and Codex | 2026-10-28 | Package version 1.0

Extend the existing product, not six new applications. Each roughly 7 KB specification targets a student outcome and includes contracts, failure behavior, acceptance cases and a release gate. Read this README with each selected spec.

This package requests development and tests, not production deployment, credential changes, purchases, institutional applications, publication, messages or calendar writes. It contains specifications, not implemented features or executed product tests.

## Contents and implementation order

| ID | File | Student outcome | Reuse/dependencies |
|---|---|---|---|
| U01 | `01_Simpler_Document_Imports.md` | Ordinary files become usable evidence without student-written JSON. | Independent store, authenticated import UI, parsers and policy controls. |
| U02 | `02_Complete_Obligation_Coverage.md` | Fewer missed requirements and false overdue warnings. | Existing obligations/planning; U01 reviewed records. |
| U03 | `03_Feedback_To_Improvement.md` | Own feedback becomes a specific change and relevant practice. | Readers/integrity/practice; U01 intake; optional U02 work links. |
| U04 | `04_Smarter_Document_Search.md` | Find evidence without knowing its exact wording. | Readers/index/continuation; U01 improves intake. |
| U05 | `05_Study_Continuity.md` | Resume from actual attempts and selected goals. | Existing personal state; optional U03 feedback links. |
| U06 | `06_Consequential_Change_Digests.md` | Understand important changes and their effect on plans. | Existing snapshots; U01 versions/U02 obligations improve scope. |

Suggested order: **U01 -> U04 -> U02 -> U03 -> U05 -> U06**. U03/U04 can start with existing permitted imports. U05/U06 must deliver minimal useful versions without waiting for all other enhancements. A dependency is not a permission grant. Do not build a general extension framework to deliver these outcomes.

## Preflight and evidence limits

Codex must inspect the actual checkout/build and earlier completed specs first. Record existing equivalents, regression tests and missing deltas. Extend working components; do not duplicate stores, policy engines or tools. Proposed field/interface names are logical contracts, not claims that exact modules exist. Preserve compatibility and map each proposed change to its actual implementation.

On October 28 the installed catalogue exposed local document list/read/status/search, study-material preparation, PDF rendering and independent academic workflows. The latter describes `independent-academic-1` structured input. A local inventory call returned zero documents and reported no institution contacted. This establishes a responding inventory route, not successful source-based workflows.

The prior comparison inspected public planning, grading, documents and change tracking, but that source snapshot was older than the installed catalogue. Today's reread of document-search documentation still describes literal matching [R4]. The October 28 repair brief records missing-input diagnostic issues and incomplete independent testing [R7]; reproduce before assuming those defects remain. No complete current repository audit or product test suite was performed for this package.

## Shared requirements

### Independent operation and acquisition

All six baseline journeys must work with permitted fictional imported sources while Canvas is disabled. Independent authorization must not require an active institutional connection. Preserve ownership, source restrictions, assessment rules and recipient/egress checks. A file saying “approved” grants nothing; mentioning Canvas causes no blanket denial of an otherwise permitted independent document.

No API exporters, scraping, browser automation, credential/cookie capture, arbitrary URL fetches or background LMS refresh as import shortcuts. Retained institutional content cannot be relabeled to bypass restrictions. Future live adapters require existing provider/institution authorization and independently verified scopes.

Instructure's published API Policy section 3(i) restricts unapproved MCP-based access to its services/APIs/documentation [R1]. The baseline avoids that acquisition; this package is not Instructure approval or a legal certification. Uploaded content still carries applicable copyright, privacy and school/instructor restrictions. Download access is not blanket AI-sharing permission.

### One academic core and honest evidence

Reuse source/version references, exact locators, integrity decisions, planning/calculation logic, preferences and lifecycle controls. Keep source facts, user assertions, deterministic results and host interpretations distinct. Unknown stays unknown; do not duplicate whole documents into derived records. U01 compiles supported reviewed records through existing schemas; U02 extends coverage rather than becoming a prerequisite for basic import.

The service retrieves evidence and validates typed state. ChatGPT interprets already-shared material. No backend language-model service, mandatory paid embeddings or second chatbot is required. Valid references/structure cannot certify an interpretation's truth. Native attachment transfer is not assumed without actual host verification.

### Writes and user control

Canvas coursework remains read-only. Local imports, edits, saved attempts, acknowledgments and preferences are mutations: use authenticated UI/actions, explicit authorization and expected versions. Do not label them read-only. A read-only deployment uses its authenticated UI for local writes. A model-supplied `confirmed=true` does not prove an authenticated approval action. A proposal is never external execution. Tool annotations describe behavior; enforce authorization in the service rather than trusting annotations [R2].

Local preview and deletion must remain possible without sharing content with ChatGPT. Batch approvals can cover concrete displayed selections; avoid unnecessary repeated confirmations. Source content cannot alter policy, consent or execution.

### Security, lifecycle and recovery

Reuse tenant isolation, encryption, parser sandboxing, retention, deletion journal and restore fences. Filter before retrieval and recheck before release. Required revocation reaches dependent caches, excerpts, vectors, saved interpretations and queued alerts. No document bodies, answers, grades, credentials or signed URLs in logs. New tables require disposable-database migration, rollback and concurrency tests; never weaken missing/deleted-history safeguards.

Proposed limits are design defaults, not vendor limits. Stricter existing limits win unless a measured change is approved. Report partial useful results without revealing restricted resources. Missing input, unsupported content, stale versions and genuine denial need distinct safe next steps. Do not fix missing-input errors by disabling egress or hiding real authorization failures.

## Acceptance and evidence discipline

Each spec contains numbered product acceptance cases. They are instructions to implement and execute, not results. Use disposable synthetic profiles with explicit test consent/source policy. Never install fictional approvals in the personal production profile. Keep gold answers outside imported content and freeze the clock/timezone where dates matter.

Run unit, normal-service integration and actual HTTP MCP/UI serialization tests. Independent success/error/retry paths must make zero provider-network attempts. Inspect structured content and every text/image/resource output channel, not only internal objects.

Shared regressions: foreign owner, revoked/deselected source during a call, version changes, prompt injection, missing inputs, partial pagination, deletion/restore, restart, duplicate mutations, read-only deployment and exhausted response budgets. Conditional delivery/vector/live-provider cases apply only to those implemented stages; report unavailable stages separately without preventing a verified independent baseline release.

Compare baseline/candidate on identical corpora and host configurations. Measure useful task completion, consequential errors/omissions, student interventions, latency and resource cost. Safe refusal alone is not success. Spec thresholds are proposed targets, not measured performance. Pilot samples do not establish universal learning benefits.

Report: commit/build; reused components; implemented delta; executed/passed/failed/skipped cases; actual ChatGPT/UI proof; institution-specific proof; blocked work; limitations; evidence paths; migrations/rollback; and next gated work. Missing fixture/runtime/approval is blocked, never passed. Keep independent and live-provider verification separate. A fixture self-check is not product integration proof.

## Copyable Codex handoff

> Read README.md and the selected specification. Inspect the current repository and earlier implemented work; document only the missing delta. Implement the smallest complete independent-source journey. Preserve authorization, integrity, egress, read-only Canvas and lifecycle boundaries. Execute numbered acceptance cases through normal service/transport paths. Do not connect to Canvas or change production authorization. Report implemented, verified, partial and blocked behavior separately with exact evidence. Add no unrelated features.

## References

External sources checked October 28, 2026. Project documents describe their own scope, not independent validation. Follow the installed SDK's negotiated protocol; references do not mandate an upgrade. Requirements, data shapes, limits and sequencing in this package are design proposals.

- R1: Instructure API Policy, effective August 12, 2025, section 3(i): https://www.instructure.com/policies/canvas-api-policy
- R2: MCP tools, annotations, results and user interaction: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- R3: OWASP File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- R4: CanvasBridge document search: https://github.com/nfienemann/Canvas-ChatGPT-Connector/blob/main/docs/document-search.md
- R5: CanvasBridge academic intelligence and changes: https://github.com/nfienemann/Canvas-ChatGPT-Connector/blob/main/docs/academic-intelligence.md
- R6: CanvasBridge activity planning: https://github.com/nfienemann/Canvas-ChatGPT-Connector/blob/main/docs/activity-study-planning.md
- R7: `CanvasBridge_Codex_Repair_Brief.md`, user Library, October 28, 2026. Consulted for diagnostics/testability; not bundled or presumed unfixed.

`MANIFEST.json` records bytes, SHA-256 hashes and acceptance-case IDs. It is a package integrity inventory, not a security signature or test report.
