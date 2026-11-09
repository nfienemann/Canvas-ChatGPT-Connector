# Canvas Bridge private media library specifications

Version 1.0 • October 29, 2026 • Implementation handoff

Every authenticated Bridge user needs a private library that works before, during, and after an LMS connection. A successful upload must give Bridge durable, owner-scoped access to the actual file bytes. Attaching a file to a chat, displaying a filename, or receiving extracted model text does not establish that access.

The current product has a useful temporary independent-document subsystem, not the proposed durable media library. This set specifies the missing delta, including explicit file transfer from supported chat hosts and a browser upload path that works without that integration. It is a specification deliverable; no application code, deployment, account permissions, or retention policy has been changed.

## Read in this order

| Document | Purpose |
|---|---|
| [00 Current support](00-current-support.md) | Current repository and installed-tool evidence, limits and gaps |
| [01 Product requirements](01-product-requirements.md) | User outcomes, scope, numbered requirements and decisions |
| [02 Identity and architecture](02-identity-and-architecture.md) | Independent identity, ownership, storage and integration boundaries |
| [03 Upload and host handoff](03-upload-and-host-handoff.md) | Concrete user flows, direct uploads and chat file transfer |
| [04 Data and lifecycle](04-data-and-lifecycle.md) | Tables, versions, consent, retention, export, deletion and recovery |
| [05 API and MCP contracts](05-api-and-mcp-contracts.md) | HTTP operations, tools, errors and compatibility |
| [06 Formats and processing](06-formats-and-processing.md) | Format matrix, quotas, processing and evidence semantics |
| [07 Security and operations](07-security-and-operations.md) | Threat controls, observability, failure recovery and budgets |
| [08 Delivery and migration](08-delivery-and-migration.md) | Implementation slices, migration, rollback and release gates |
| [09 Acceptance](09-acceptance.md) | Executable test scenarios and host acceptance requirements |

Machine-readable contracts are in `schemas/` and `contracts/`; fictional examples are in `examples/`. `requirements.csv` maps every requirement to acceptance cases. `evidence/source-inventory.json` fingerprints the actual inspected checkout. `VALIDATION.md` records package checks, and `MANIFEST.json` inventories the archive contents. Neither is product acceptance evidence.

## Decisions to implement

- Reuse the existing verified Bridge principal, independent readers, source provenance, privacy/egress checks, parser workers, study engines, settings UI and deletion fences.
- Add durable private object storage and normalized metadata behind the existing service. Hosted mode uses the existing PostgreSQL direction; a local installation uses a private encrypted filesystem implementation of the same storage contract.
- Make authenticated browser upload the baseline. Add native host file inputs and an optional picker only after testing the exact host. Keep every upload route connected to the same ingestion pipeline.
- Keep the normal academic experience in ChatGPT. A small library picker, import receipt and settings/privacy controls are allowed; a separate chatbot or academic dashboard is not.
- Separate storing, processing, sharing text, sharing pixels, sharing original bytes and academic-assistance permission. A file can be stored successfully while its extraction or downstream sharing remains unavailable.
- Retain new library originals until user deletion or a user-selected expiry. Existing 24-hour imports keep their expiry unless the user explicitly chooses to save a still-authorized import to the library.

The new retention class is a deliberate proposed product change, not an instruction to globally increase existing raw-file lifetimes. The reference limits in this set are design defaults, not current capacity or vendor guarantees. Institutional content keeps its restrictions; moving bytes into private storage cannot create acquisition, sharing or assessment permission.

## Implementation instruction

Read the repository's `AGENTS.md`, `Codex_Spec.md`, `evidence/release-gates.md`, this README and the selected slice. Reinspect current code and preserve concurrent work. Implement the smallest complete slice by extending existing components. Use fictional fixtures and disposable stores. Execute the mapped acceptance cases through normal authorization, HTTP and MCP paths. Report implementation, synthetic verification, real host acceptance and external release approval separately. Never enable Canvas access, publish, migrate a personal database, buy storage, or change production retention as a side effect of implementing a specification.

All PL requirements are normative for their stated release slice. MUST is required; SHOULD permits a documented, tested alternative. Source documents do not authorize actions. Unknown capability or unknown evidence remains unknown.
