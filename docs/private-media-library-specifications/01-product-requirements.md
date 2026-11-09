# Product requirements

## User journeys

1. A new user with no LMS connection opens Bridge's Add files action, chooses a PDF and a photo of personal notes, selects retention and sharing, and receives stable library IDs. The next chat can find the permitted files by title or collection.
2. A user with an already uploaded chat file selects Save to Bridge library. A supported host transfers it explicitly; an unsupported host opens the signed-in upload page with clear instructions. Neither path pretends a chat attachment is already stored.
3. A user imports several course materials, sees per-file outcomes, retries failures and keeps successful items. Course labels are optional organization, not LMS identifiers or permission grants.
4. A user asks about a large slide deck. The library reports whether it is stored, text-searchable or visually renderable, and returns exact source citations and coverage. Larger accepted originals can remain stored without supported extraction.
5. A user replaces a schedule, then opens an old citation. The library identifies the cited version and any restriction, rather than silently returning the new schedule's text.
6. A user disconnects Canvas and continues using independent materials. Deleting the library account, by contrast, disables all library access and starts its deletion workflow.

## Requirements and release scope

| ID | Requirement | Slice |
|---|---|---|
| PL-01 | A private library MUST belong to a verified Bridge principal and be available with zero LMS connections. | L1 |
| PL-02 | Every metadata, object, job, cursor, cache and delivery operation MUST enforce owner and current permission, including just before release. | L1 |
| PL-03 | Accepted originals MUST persist across chats, restarts and LMS disconnect until the selected retention event. | L1 |
| PL-04 | A device upload MUST work through authenticated settings with byte progress, cancellation, retry and a durable per-file receipt. | L1 |
| PL-05 | A native host intake MUST use a supported explicit handoff; absence of the capability MUST lead to the browser path. | L2 |
| PL-06 | Intake MUST stream into quarantine, reserve quota and publish only after integrity and safety checks. | L1 |
| PL-07 | Idempotency and hash checks MUST prevent duplicate publication and silent consent expansion. | L1 |
| PL-08 | Storage, extraction, search, rendering and media playback capabilities MUST be reported separately. | L1, L3 |
| PL-09 | Private collections, tags and titles MUST support bounded discovery without requiring a course or exposing another owner's metadata. | L1 |
| PL-10 | Reads/search MUST return bounded exact evidence, versions, coverage and continuation; omitted content MUST remain explicit. | L1 |
| PL-11 | Original-byte retrieval MUST reauthorize each request and verify the stored checksum; it MUST not depend on successful parsing. | L1 |
| PL-12 | Processing and recipient-specific text, visual, original and audio sharing MUST have distinct enforceable grants. | L1, L3 |
| PL-13 | Imported origin and known institutional dependencies MUST survive rename, replacement, export and reimport checks. | L1 |
| PL-14 | Existing independent academic tools MUST consume permitted library sources through the shared evidence core. | L1 |
| PL-15 | Replacement MUST create immutable versions and invalidate dependent representations without silently updating citations. | L1 |
| PL-16 | Revocation/deletion MUST stop current and queued access, propagate to derived state and survive restoration. | L1 |
| PL-17 | Export and backup MUST be owner-scoped, encrypted where applicable, restorable and subject to deletion fences. | L1 |
| PL-18 | Enforced storage, item, transfer and processing quotas MUST be atomic across workers and visible to the owner. | L1 |
| PL-19 | New retention MUST not silently extend existing temporary imports or weaken institutional TTLs. | L1 |
| PL-20 | Original content, filenames, grants and private URLs MUST stay out of routine logs and public analytics. | L1 |
| PL-21 | Host, policy, parser and storage failures MUST produce actionable distinct states without fabricating success. | L1, L2 |
| PL-22 | The UI MUST work with keyboard/screen reader, provide text equivalents and preserve the ChatGPT-first product. | L1, L2 |
| PL-23 | Hosted release MUST pass multi-user isolation, migration, deletion/restore and exact-client acceptance. | L1, L2 |
| PL-24 | Later audio/video and expanded archives MUST have explicit capability gates, bounded processing and synthetic acceptance. | L3 |

## Scope decisions

L1 includes durable versions, browser upload, existing document analysis, safe PNG/JPEG storage/preview, library metadata/search, original downloads, export/delete and operational recovery. It must be useful while native file handoff is unavailable. L2 adds tested host file inputs and optional host file selection. L3 adds approved audio/video storage and optional transcripts/frame processing; nested course-export interpretation is a separate future importer, not a hidden archive feature.

Public links, sharing with other users, collaborative folders, scanning a user's whole device/chat history, arbitrary URL ingestion, automatic LMS copying, provider credential reuse and backend conversational AI are out of scope. A user does not need a separate paid model account or a mandatory new password to use the library. No purchases or public release are authorized by this handoff.

An authenticated upload action may approve a whole displayed batch. Do not repeat confirmations per processing stage. Only materially changed retention, recipients, selected files or operations need a new authorization action. Text supplied by a model, including `confirmed=true`, cannot stand in for verified user authorization.
