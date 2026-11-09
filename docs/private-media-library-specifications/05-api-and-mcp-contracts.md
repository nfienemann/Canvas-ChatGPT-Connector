# API and MCP contracts

## Common rules

All interfaces authenticate the same Bridge principal, enforce current owner/source/recipient permission and return bounded JSON or authorized byte streams. Caller input never contains an ownership override, SQL, filesystem path, arbitrary fetch URL or executable workflow. IDs are opaque and not credentials. Unknown and other-owner IDs have the same safe external response.

Reuse the repository's `Result` envelope and source records for evidence tools. Proposed detailed reason codes belong in structured data; do not invent incompatible top-level statuses. For example, `source_changed` uses the existing status, quota exhaustion uses `retry_later`, and missing capability uses `unsupported_feature`. The intake descriptor has its own narrow receipt schema as its declared `outputSchema`.

Mutation requests use an idempotency key scoped to owner and operation. Metadata writes carry `expected_revision`; replacements/deletions/grant changes carry expected version and current permission revision. A stale request returns conflict without applying a partial mutation. Batch atomicity is per item unless the manifest requires all-or-nothing archive safety validation.

## HTTP contract

Paths are proposed additions under the existing authenticated settings/library surface. JSON APIs return structured errors; HTML forms render the same outcomes. No route accepts a caller-supplied local file path.

| Method and path | Input / output | Required behavior |
|---|---|---|
| GET `/settings/library` | Private picker/settings page | Library/upload/privacy UI only, no academic dashboard |
| GET `/api/library/status` | Quotas, capabilities and policy versions | No provisioning or consent mutation |
| POST `/api/library/intakes` | Concrete selection, retention, processing/sharing choices, idempotency key | Authenticated user action; returns intake/selection IDs, expiry, reservations and upload routes |
| PUT `/api/library/intakes/{intake}/files/{selection}/chunks` | Raw bytes, offset, chunk checksum | Sequential bounded streaming; CSRF/session; owner/intake binding |
| GET `/api/library/intakes/{intake}` | Per-item progress, authoritative offsets and receipts | Supports lost-response recovery |
| POST `/api/library/intakes/{intake}/complete` | Expected selected manifest hashes | Verify and publish once; extraction may remain queued |
| DELETE `/api/library/intakes/{intake}` | Expected intake revision | Cancel unpublished work; preserve completed items |
| GET `/api/library/items` | Collection/type/tag filter, limit <=50, cursor | Owner-scoped stable pagination; titles are private metadata |
| GET `/api/library/items/{item}` | Optional exact version | State, rights, retention, processing and provenance summary |
| PATCH `/api/library/items/{item}` | Title/tags/collection and expected revision | Metadata only; cannot change origin or grants |
| POST `/api/library/items/{item}/versions` | New intake and expected current version | Same quarantine pipeline; immutable replacement |
| POST `/api/library/items/{item}/grants` | Authenticated reviewed recipient/channel changes, expected permission revision | Explicit grant mutation; no model assertion alone |
| GET `/api/library/items/{item}/versions/{version}/original` | Owner-session download, optional single byte range | Reauthorize, fixed attachment disposition, checksum, bounded range; no public storage redirect |
| POST `/api/library/exports` | Selected items/versions, idempotency key | Bounded asynchronous export; current permissions on every selected source |
| DELETE `/api/library/items/{item}` | Expected version/revision | Immediate fence; phase receipt; idempotent retry |
| GET `/api/library/deletions/{receipt}` | Purge phase status | Owner-only; no exposed internal object paths |

Cookie-authenticated mutations require CSRF and origin validation. A separately authenticated MCP intake is not exempt from its consent checks. Do not place bearer credentials in return URLs. HTTP 401/403/404/409/413/415/429/503 map respectively to authentication, safe denial, safe unknown, conflict, size, type, limit and unavailable outcomes; include a stable reason and permissible next step.

## MCP surface

Prefer a small coherent library surface while retaining existing local document names as compatibility adapters. Do not register every HTTP endpoint as a tool.

| Tool | Contract | Annotation / gate |
|---|---|---|
| `get_library_status` | Effective quotas, host capability states, upload/settings link; no content | Read-only |
| `list_library_items` | Filters, <=50 items, cursor; permitted metadata and processing state | Read-only; metadata egress |
| `get_library_item` | Item and optional exact version; safe status and allowed actions | Read-only |
| `search_library` | Query <=200 chars, optional <=20 item IDs/collection, <=20 hits, version-bound cursor | Read-only; text egress; explicit search coverage |
| `read_library_item` | Exact item/version, locator and bounded range; <=18,000 chars/part, <=5 parts, total result <=120 KB | Read-only; purpose and source checks |
| `render_library_item` | Exact version and one page/slide/image or bounded approved media range | Read-only; separate visual/audio grant and tested modality |
| `prepare_library_download` | Exact item/version and recipient/channel; bounded expiring owner/recipient-bound delivery | May create an ephemeral delivery receipt: `readOnlyHint=false`, `destructiveHint=false`; browser original route is the fallback in MCP read-only mode |
| `submit_library_files` | Preauthorized intake, explicit host files, idempotency key; returns per-file state | Mutation: `readOnlyHint=false`, `destructiveHint=false`, `openWorldHint=true`; optional approved ingress, absent in MCP read-only mode |

Library deletion, retention/grant changes and collection writes initially remain in authenticated UI. The native submit tool does not authorize arbitrary external writes; `openWorldHint=true` truthfully reflects host URL acquisition. Annotations inform the host and do not enforce access. Existing read-only independent study tools consume mapped library selections after all source checks.

`contracts/submit-library-files.tool.json` is a machine-readable proposed descriptor with self-contained input/output schemas. It is not registered by this package. Its synthetic file-reference example contains a reserved `.invalid` URL; never fetch it. `transfer_received` means staged transfer only. `published` means an immutable original exists; processing can still be unsupported or pending.

## Citation and pagination contract

Every evidence hit includes item ID, immutable version ID, original SHA-256, representation ID/version, exact locator, extraction state, quoted range, source category and uncertainty. Locators distinguish PDF page, original PPTX slide, DOCX paragraph/table cell, workbook sheet/cell, text offsets, image region and media time range. A derivative hash is never substituted for the original.

Cursors bind owner, query/filter/scope, original versions, representation version, policy/generation and sort order; expire after 15 minutes. Reauthorization occurs on every page. If the version or permissions changed, return `source_changed`/denial and require restart. Partial search reports scanned/eligible counts and omitted modes; no result is not proof of absence from images/audio or unprocessed files.

## Required error reasons

`AUTH_REQUIRED`, `RESOURCE_UNAVAILABLE`, `CONSENT_REQUIRED`, `RECIPIENT_UNVERIFIED`, `RETENTION_REVIEW_REQUIRED`, `SOURCE_CHANGED`, `QUOTA_EXCEEDED`, `UPLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA`, `UNSAFE_ARCHIVE`, `CHECKSUM_MISMATCH`, `TRANSFER_EXPIRED`, `HOST_TRANSFER_UNAVAILABLE`, `SCAN_UNAVAILABLE`, `PROCESSING_UNSUPPORTED`, `PROCESSING_PARTIAL`, `PROCESSING_FAILED`, `STORAGE_UNAVAILABLE`, `DELETE_PENDING`, `RESTORE_ON_HOLD`.

Each outcome includes `retryable`, a bounded safe `next_action`, and a correlation ID. Do not suggest reconnecting Canvas for library storage, parser or missing-file failures. Retries never broaden scope, retention or recipient permissions.
