# Data and lifecycle

## Logical records

Names below are proposed contracts, not existing database tables. Reconcile with the actual migration strategy before implementation. Every content-bearing child has an owner-qualified foreign key; application filtering alone is insufficient for relationships.

| Record | Required fields and invariants |
|---|---|
| Library account | owner, status, deletion generation, quota policy, committed/reserved bytes and slots, retention policy version; one per principal |
| Library item | opaque ID, owner, encrypted display title/name, current version, media kind, created/updated time, state, metadata revision |
| Immutable version | item/owner, opaque version ID, original SHA-256, verified byte length/MIME, opaque object reference, acquisition channel/time, source lineage, retention mode/expiry, permission version |
| Grant | owner, item/version or reviewed selection, authenticated action receipt, recipient identity, allowed purposes/channels, issued/expiry/revocation time, policy version; no caller-selected classification |
| Collection membership | owner, collection ID, item ID, revision; collections and tags are private metadata, not access grants |
| Intake | owner, opaque ID, selected manifest, consent receipt, transfer mode, idempotency key, reserved bytes/slots, offset/chunk receipts, generation, expiry, per-file outcomes |
| Representation | owner/item/version, original hash, type, parser/renderer version, policy version, derived hash, source locators, coverage, limits, object/index reference, state |
| Job | owner/item/version, bounded operation, expected generation/grant, lease, retry count, progress and sanitized reason; never signed source URLs |
| Delivery | owner/item/version, recipient/channel, single-purpose capability digest, expiry, permission generation, consumption state; never a permanent public link |
| Tombstone | owner/item/version or account scope, monotonically increasing epoch, disabled_at, purge phases, backup horizon, durable journal acknowledgement |
| Legacy mapping | owner, old independent document ID/hash, new item/version, migration state; mapping cannot outlive permission to its target |

`schemas/library-item.schema.json` defines a bounded model-visible projection. It intentionally excludes storage keys, full grants and protected lineage detail. Technical capability states and `permitted_channels` are distinct: a supported renderer cannot be used without a visual grant. A projection is not a writable database record.

## State machines

Intake: `created → uploading → validating → published`, with terminal `cancelled`, `expired`, `rejected` or `failed`. A published intake is immutable and can be replayed as a receipt. Batch state is derived from child outcomes, including partial completion.

Item storage: `quarantined → available → deleting → deleted`. Rejected quarantine is never listed to the model. An available item can have processing `not_requested`, `queued`, `running`, `ready`, `partial`, `unsupported`, `blocked` or `failed`. `available + unsupported` is a valid stored-only file, not an upload failure. Malware/unsafe active content is rejected rather than exposed as stored-only.

Sharing is separate from storage and processing. Revoking a recipient grant disables that recipient's inventory, search, representations and delivery immediately. The owner may still inspect, export or delete their file if its underlying source permissions allow it. Legal/source holds must have explicit user-facing state; do not add them silently as a generic error mechanism.

## Versions and duplicate handling

An item has immutable originals. Replacement requires `expected_version_id`; concurrent mismatch yields `source_changed`. New bytes get a new version and fresh derived representations. Older versions remain accessible only under their own current rights and selected retention. Default history retains the latest five versions and at most 30 days of superseded originals; disclose automatic history expiry before replacement. Current originals follow the selected library retention. All retained versions consume quota.

Permissions for a replacement never expand silently. Reuse at most the intersection of existing grants and the new authenticated selection; new recipients/channels require an explicit change. Parser upgrades create representation versions, not changed original hashes. Citations pin original version and representation identity. Never resolve an old citation to new content. Retired/expired versions return explicit unavailable history, not a guessed reconstruction.

Deduplication is owner-local and constrained by provenance, purpose and retention. Identical bytes with incompatible lineage or grants can share encrypted storage internally only if those constraints remain independent. A repeat intake never turns off an old restriction. Use unique database keys for owner plus idempotency key and transactionally publish once.

## Retention

| Data | Proposed default | Enforcement |
|---|---|---|
| New library originals | Until user deletion; optional user expiry | Explicit Save to private library action and displayed policy |
| Existing temporary imports | Existing expiry, at most 24 hours | No automatic conversion or TTL increase |
| Abandoned intakes/quarantine | At most 24 hours | No read access; sweeper purges and releases reservations |
| Superseded originals | Latest five, at most 30 days | User-visible version policy; explicit pinning only within quota and rights |
| Derived caches/previews | Rebuildable, at most 24 hours without use | Never outlive source/grant; representations carry exact version |
| Minimal operational diagnostics | 7 days | No content, titles, names, URLs or raw queries |
| Encrypted library backups | At most 30 days | Deletion fences and recovery verification; separate from legacy backup exclusions |
| Deletion fences | Backup horizon plus safety margin | Preserve at least 31 days and longer while an eligible backup/job can resurrect content |

Library retention does not extend a shorter source license, authorization or grant expiry. Grant expiry can block sharing before bytes expire. No silent deletion merely because Canvas disconnects or a chat ends. Inactivity deletion, if introduced later, requires a disclosed policy and notice; it is not part of this default.

## Delete, export and recover

Delete first records a durable tombstone and advances generation, then disables list/read/search/download and cancels jobs before acknowledging access disabled. Purge originals, superseded versions, thumbnails, OCR/text, index entries, transcripts, embeddings if later present, and source-dependent study state. Target active-store purge within 24 hours. Return phase statuses including backup expiry; never call a pending physical purge complete.

Before publication, workers recheck the tombstone and generation inside their commit transaction. Downloads recheck before opening and between bounded chunks; deletion cannot retract bytes already sent. A delete/restore race must not revive content. Lost tombstone journals or missing key material put restoration on hold, never into a permissive recovery mode.

An owner export contains authorized originals, a UTF-8 metadata manifest, hashes, stable citations and current retention/grant descriptions. Generated export filenames are sanitized and collision-safe. Bound export size, use asynchronous jobs where needed, and reauthorize at archive publication and download. Exclude restricted/deleted items with owner-visible reasons. Exporting grants does not make them portable authority on reimport; imported exports require fresh local processing/sharing choices and preserve known lineage.

Back up durable library metadata and private objects consistently, with encrypted keys managed independently. Restore into an isolated environment, reconcile tombstones after the backup snapshot, verify checksums and owner bindings, and rebuild indexes only for currently authorized sources. Do not change the legacy backup routine to include all independent records indiscriminately. A deployed durable-library claim requires a demonstrated restore, not just configured replication.

Bridge deletion cannot erase existing host-conversation copies, downloaded files or other independent copies. The UI states the scope of each deletion action without claiming control of those systems.
