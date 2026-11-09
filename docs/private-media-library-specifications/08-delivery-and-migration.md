# Delivery and migration

## Implementation slices

| Slice | Concrete deliverable | Exit evidence |
|---|---|---|
| L0 inventory and contracts | Map current modules to PL requirements; reconcile schemas, source restrictions and duplicate functionality | Current source hashes, gap matrix and reviewed contracts; no deployment changes |
| L1a durable foundation | Normalized metadata, private object adapter, quota reservations, tombstones, browser intake, status/list/read originals | Zero-LMS synthetic end-to-end upload → restart → exact original read; isolation and crash tests |
| L1b useful library | Existing document extraction/search/study compatibility, safe PNG/JPEG previews, collections, immutable versions, export/delete | Mapped AT cases through real local HTTP/MCP, no bypass of egress or integrity checks |
| L1c operational release | Backup/restore, migration, accessibility, hosted concurrency, actual supported-client fallback | Non-compensating release checklist with actual outcomes and reference deployment |
| L2 native host intake | Proposed host file-input tool and optional picker integrated with the same pipeline | Exact host version tested with upload, preexisting file, expired reference, new chat and unsupported-host fallback |
| L3 broader media | Approved audio/video storage and optional bounded processing | Decoder, duration/size, streaming, recipient, transcript/frame and cost tests; no claim of general comprehension |

Implement L1 before requiring L2. Users need a reliable supply path even if native file transfer is absent. Do not advertise L3 as part of L1. A nested archive/course-export importer needs a separate reviewed manifest/provenance mapping and cannot be smuggled in by relaxing ZIP limits.

## Code integration map

- Extend `independent.py` or extract a library service without duplicating owner/egress logic. Its current `require` accepts only `authenticated_browser_upload` plus `bounded_browser_upload`; a new versioned provenance validator must explicitly recognize durable browser and host intake records. Simply changing an origin string will currently fail, and removing validation is not a fix.
- Extend `IndependentResource` through an explicit migration/compatibility mapping, not by overloading the current content JSON with large durable media. Protect new sensitive metadata using existing encryption conventions.
- Reuse `independent_ui.py`, `settings_ui.py` and `usefulness/ui.py` for upload/consent controls. Replace inconsistent size messages with effective storage-versus-processing limits.
- Reuse `usefulness/imports.py` batch receipts/ZIP rules and strengthen limits/signature checks as mapped by acceptance. Preserve successful items on cancellation.
- Add tools in `app.py` using truthful mutation registration. Preserve `mcp_read_only` behavior: browser imports remain possible while MCP mutation tools are absent. Existing `list/read/search/render_local_document` tools resolve explicitly mapped library IDs under the same current authorization.
- Reuse parser, visual, delivery and privacy middleware. Update field allowlists so necessary citation/status fields survive MCP projection; test the serialized response, not only service-return dictionaries.
- Extend `lifecycle.py` and retention sweepers for the new retention class and object store. Existing independent backups deliberately omit document bytes; do not present those backups as library recovery.
- Preserve `independent_intelligence.py` and process/usefulness source-dependency semantics. Durable originals do not automatically extend 30-day derived-state lifetimes or resurrect expired attempts.

## Migration

1. Reinspect the actual running build and database revision. Use disposable synthetic databases for migration/rollback rehearsals. Record prerequisites and checksums; do not migrate the user's private database as part of this specification task.
2. Add new tables, indexes and object-storage configuration behind `library_enabled=false`. Keep the existing 24-hour path usable. The new flag must not enable LMS acquisition or host file inputs.
3. Offer Save to library for each still-available temporary import, or a displayed batch. Explain durable retention, copied bytes, quota and current recipients. Require an authenticated explicit selection; preserve or narrow permissions and source lineage.
4. Copy bytes to quarantine, verify original hash, publish immutable library version and record owner-qualified legacy mapping transactionally. Keep the old source expiry unchanged. Mark the mapping eligible only after publication; duplicates reuse the same authorized result.
5. Do not recover already expired/deleted imports from backups, model responses, temp directories or a host conversation. Ask the user to select a legitimate available original again through the normal flow when necessary.
6. Rebuild authorized representations with current parsers and bind dependent records through explicit lineage. Old citations keep their original hashes. A mapping cannot convert institutional material to independent material or widen a recipient grant.
7. Validate source counts, checksums, owner boundaries, stored bytes and deletion fences; record actual migrated/skipped/withheld counts. A migration failure leaves the old permitted path intact and no falsely available new item.

## Rollback

Disable new writes/intakes first. Preserve authenticated export, deletion and already-authorized reading through a compatible maintenance version. Do not roll back to a binary unable to enforce the new provenance and tombstone rules. Drain/cancel jobs with generation fences; reconcile reservations. Never remove durable tables or objects simply to make an old migration pass. Object/metadata backups must restore as a matched set under the current deletion journal. A rollback plan must be rehearsed before enabling durable user storage.

## Release ledger

Track requirement delivery (`not_started`, `implemented`, `partial`) separately from verification (`not_run`, `synthetic_pass`, `host_pass`, `failed`, `blocked`). The bundled ledger starts `specified`/`not_run`. Add source hashes, build, environment, exact test commands and sanitized results when implementation occurs. All authorization, provenance, deletion and recovery cases are individually blocking.

Pilot acceptance must include one new account with no LMS record and one independent user whose LMS connection is disconnected. Use fictional content first. Actual client acceptance records client/surface/version, selected flow, visible receipt, later-session retrieval and observed pixels where claimed. Directory eligibility, institutional approvals and public distribution retain their own unresolved gates; this package cannot satisfy them.
