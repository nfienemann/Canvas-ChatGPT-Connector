# Private media library implementation

Implemented against the October 29, 2026 specification archive in
`docs/private-media-library-specifications/`. The archive is a requirements
source, not authority to deploy, migrate personal data, contact an institution,
purchase infrastructure or publish. Existing uncommitted work was preserved.

## Availability and activation

The durable library is **off by default**. It does not require an LMS connection
and does not enable institutional access. Existing temporary imports retain their
original maximum 24-hour lifetime. No personal service/database was migrated or
restarted during implementation.

For a separately reviewed installation, apply migrations `a28e70b915cd` and
`b39f81ca26de` after `f17a6b204c31`, configure a private `BRIDGE_LIBRARY_ROOT` outside the repository,
static content and cloud-synced folders, and enable `BRIDGE_LIBRARY_ENABLED`.
The parser sandbox must be configured to publish uploads: a missing or failed
safety worker holds the original in quarantine. Start the existing worker process
for queued extraction and retention work.

`BRIDGE_LIBRARY_UPLOADS_ENABLED=false` stops new intakes while keeping an enabled
library's authenticated reads, export, privacy controls and deletion available.
Destructive migration downgrade is deliberately refused. Keep a compatible
maintenance binary with the current provenance and deletion checks.

The local object adapter uses independently authenticated AES-GCM chunks with
opaque keys, owner/key/offset binding, checksum verification and atomic manifest
publication. Windows ACLs or POSIX permissions protect the directory. Object bytes
are separate from encrypted SQL metadata. Hosted PostgreSQL constraints and a
storage adapter interface are implemented; an actual hosted bucket adapter,
PostgreSQL multiworker acceptance and hosted operations remain release work.

## User flow

Open **Settings → Private library — Add files**. Select up to twenty files,
review retention, storage permission, optional processing and separate recipient
channels, then choose **Save to private library**. Upload progress counts bytes.
Retry checks the receipt and authoritative offset; cancellation preserves files
already published. No model-facing upload, grant, deletion or arbitrary-URL tool
can manufacture the browser authorization action.

The library shows durable IDs and processing states. **Manage file** contains
title/tags/collection controls, exact-version replacement, permission changes,
owner export and deletion. Original downloads use the signed-in owner session
and do not require successful extraction. Every download verifies the whole
original's checksum before releasing bytes, then rechecks access between 64 KiB
release blocks. One bounded byte range is supported. Already-sent bytes cannot
be recalled.

Temporary imports have an explicit **Save to private library** action. It copies
only a currently authorized original, preserves or narrows grants, records a
legacy mapping and leaves the old expiry unchanged. Expired/deleted imports are
not recovered.

## Formats and evidence

Supported storage types are PDF, non-macro DOCX/PPTX/XLSX, UTF-8 TXT/Markdown,
PNG/JPEG and bounded ZIP document batches. An isolated structural safety worker
checks signatures/structure, active content, archive paths, normalized collisions,
symlinks, nested archive signatures, expansion limits and image decode budgets.
This is a bounded structural scanner, **not antivirus-product certification**.
Embedded chart XLSX workbooks are recursively validated under a shared expansion
budget; arbitrary embedded objects and macro payloads remain blocked.

ZIPs are preflighted completely before any member is published. Safe unsupported
members are excluded; unsafe structure rejects the carrier. Office containers
are distinguished from hidden nested archive carriers. A ZIP is not a Canvas
course-export importer. Audio/video, HTML, SVG, scripts, executables, macro Office,
encrypted documents and unknown binary types remain disabled.

Storage limits are 100 MiB/document, 25 MiB/image and 50,000,000 compressed
bytes/ZIP. Parsing retains existing 10,000,000-byte document and 25,000,000-byte
PPTX limits. Safe larger originals can be stored with processing unsupported.
OCR, layout coverage, hidden content and cached formulas retain existing parser
semantics. No file is described as fully understood because storage or extraction
succeeded.

Text evidence pins original version/hash and representation ID/version, supplies
exact locators and quoted offsets, and reports omitted modes. Read parts are
bounded to five parts and 18,000 characters/part with a 120 KB result cap.
Literal search inspects a bounded permitted scope and explicitly reports coverage.
It does not claim that a negative result searched every image or unprocessed file.
Fifteen-minute owner/scope/version/representation/permission-bound cursors reject
stale continuations.

PDF/PPTX use existing isolated renderers; PNG/JPEG previews are decoded, resized
and re-encoded without incidental metadata. Pixel production, transport and model
observation remain separate evidence states. Existing independent readers and
study workflows accept `lib_<immutable-version-id>` through the same evidence,
egress and academic-integrity core.

## Authorization and durability

Owner identity comes from the existing verified Bridge principal. Metadata,
processing, text, pixels and originals have distinct checks. Model inventory omits
metadata that its verified recipient cannot receive. Recipient profiles compare
normalized policy objects, including issuer/client/workspace, rather than relying
on list order or a caller's classification. Original owner downloads are a distinct
channel from model release. User possession does not establish institutional
rights; known institutional fingerprints remain blocked after renaming.

Owner-qualified database relationships cover library children. PostgreSQL uses
composite foreign keys; SQLite additionally installs child-validation triggers
because legacy connections do not globally enable foreign-key pragmas. Admission
is serialized across workers and enforces owner and deployment byte limits.
Defaults: 1 GiB/owner, 1,000 active items, 256 MiB derivatives/owner, 1 GiB
deployment derivatives, 10 GiB deployment originals/reservations, two heavy
operations/deployment and one/owner. Database leases also enforce four active
ingress requests/owner and sixteen/deployment, one export/owner and two/deployment,
and a 256 MiB deployment export-memory reservation (original size plus 32 MiB
headroom per archive). Export assembly streams each original into its bounded
archive; stream close/disconnect releases the lease, and abandoned leases expire.
Retained versions consume original-byte quota. Settings may lower these limits.

Sequential encrypted 8 MiB upload chunks have immutable per-offset receipts.
The 900-second transfer and 60-second idle deadlines can be lowered with
`BRIDGE_LIBRARY_TRANSFER_SECONDS` and `BRIDGE_LIBRARY_IDLE_SECONDS`; effective
values appear in the status response.
Publication rechecks account/session generation and the reviewed selection.
Owner-local duplicate content with identical retention and grants reuses the
published version; incompatible choices do not overwrite or widen an old grant.
Replacement is compare-and-swap against the exact version and permission revision.
Older citations continue to identify the original immutable version.

Deletion journals a fence before disabling access. It invalidates queued/running
work, representations and dependent process/study state, then purges object bytes.
Receipts distinguish access disabled, active-store purge and backup expiry.
Reads also consult the independent deletion journal, so a journaled deletion
remains effective if the metadata transaction or a restoration races/fails.
Missing/invalid journals fail closed. Sweepers enforce original/history expiry,
abandoned reservations, 24-hour representation lifetime, delivery/export expiry,
and 24-hour orphan reconciliation. Raw names, source text, signed URLs and grants
are not routine log fields.

## Export, backup and restore

Owner exports are bounded to twenty versions and 100 MiB of originals. They contain
originals and a UTF-8 manifest with hashes, lineage and descriptive grants. Every
selected version is checked again before archive release and between stream
blocks; changed permission withholds the export. Exported grants are never trusted
as reimport authority. No public storage URLs are issued.

The existing generic backup intentionally continues to exclude library data.
Use the separate operator commands with the verified opaque owner ID:

```text
canvas-bridge library-backup OWNER private-backup.zip
canvas-bridge library-restore OWNER private-backup.zip --journal current-journal
```

Stop writers for operational backup/restore rehearsals. The owner-qualified backup
contains encrypted object chunks and a sealed metadata manifest. Keys remain
separate. It expires after thirty days. A signed journal anchor detects a missing
or empty rollback journal. Restore requires an empty isolated library, starts on
hold, validates owner bindings/checksums/current deletion history, excludes deleted
versions and restores neither sessions nor recipient grants nor processing consent.
Any uncertainty keeps restoration on hold. A deployment must retain its independent
journal outside the backup rollback boundary; file encryption alone does not prove
backup availability or resistance to an operator rolling back that boundary.
The thirty-day horizon rejects expired restores; it does not prove physical
deletion of operator backup files. Configure and verify the deployment backup
storage lifecycle before advertising that deletion assurance. Terminal transfer
manifests are scrubbed, retaining only minimal reconciliation receipts.

## Host gates and contract reconciliation

Browser upload is the implemented baseline. `get_library_status` truthfully reports
native host file intake unsupported and the picker/inline client observation
unverified. `submit_library_files` is not registered. No temporary URL acquisition,
undocumented host API or generic fetch fallback exists. L2 requires reviewed exact
host domains and client handoff acceptance before activation. L3 audio/video is
disabled and requires its own codecs, duration, processing and privacy acceptance.

The new read-only tools are `get_library_status`, `list_library_items`,
`get_library_item`, `read_library_item`, `search_library`, and `render_library_item`.
`prepare_library_download` creates a five-minute owner-session receipt and has
`readOnlyHint=false`; it is absent in MCP read-only mode. The authenticated original
route and upload/settings link remain usable. These tools use the existing `Result`
envelope and the final serialized privacy/egress fences.

The supplied proposed HTTP receipt is extended with upload offsets/revisions and
`files[].items[]` for per-member ZIP results. The native submit descriptor and its
strict output schema remain a future gated contract; they are not falsely
registered against the browser receipt. Metadata/grant changes use compare-and-swap
revisions; clients reconcile after a lost response instead of blindly repeating a
stale mutation. Quotas reject per selection; archive publication is all-or-nothing.
The proposed item schema is also extended with `document_id`, collections/tags,
revisions and `audio_video` capability inside the existing `Result` envelope.
Parser coverage preserves existing vocabulary, including `complete`; consumers
should use the runtime tool schema and this reconciled contract rather than assume
the archive proposed strict JSON schemas describe the HTTP API.

See the [local completion and release blockers checklist](private-library-release-checklist.md)
and [local completion evidence](../evidence/sanitized-results/private-library-local-completion-2026-11-03.md).

See [current-worktree verification](../evidence/sanitized-results/private-library-2026-11-03.md)
and the [earlier browser/full-suite record](../evidence/sanitized-results/private-library-2026-10-29.md)
for executed checks and remaining environment-specific gates.


## Local operations and managed backup retention

The optional `BRIDGE_LIBRARY_BACKUP_ROOT` must be a dedicated private directory
outside the repository, cloud-sync and original-object roots. Files created there
have server-generated opaque names. `BRIDGE_LIBRARY_BACKUP_BYTES` defaults to
30 GiB; backup creation reserves capacity against actual directory usage before
copying. A sealed manifest binds each encrypted part's size and hash. Neither a
valid ZIP CRC alone nor a successful write is treated as verification.

```text
canvas-bridge library-managed-backup OWNER
canvas-bridge library-health --verify-originals --verify-backups
canvas-bridge library-maintain
```

Health is a read-only aggregate check. Its JSON `state`/`alerts` report quota drift,
purge backlog, processing failures, checksum failures, restore hold and backup
attention. A missing configured backup volume is unavailable, never silently
recreated or reported empty. Health contains no owner IDs, names, source text,
URLs or grants. Aggregate request/upload/processing/purge/restore counters use
closed categories and thirty-day retention; they are operator diagnostics, not
public analytics or model tools. A missing key can prevent startup, so monitoring
must also treat command/startup failure as an alert.

Managed backups expire after thirty days and maintenance physically removes them;
failed removals remain pending. Completed but unrecorded managed backup files are
quarantined for up to twenty-four hours. No scheduler or notification destination
is installed automatically. Run the existing retention worker continuously and
schedule backup creation/verification through the deployment's operator controls.
Manual `library-backup OWNER PATH` files outside the managed root are not owned by
the sweeper: their physical retention is still the operator's responsibility.
Keep encryption keys and the current deletion journal outside the backup rollback
boundary, and perform recovery in an empty isolated target.

Configure lower budgets through `BRIDGE_LIBRARY_DEPLOYMENT_DERIVED_BYTES`,
`BRIDGE_LIBRARY_EXPORT_MEMORY_BYTES` and the other documented library settings;
`.env.example` lists the defaults. These changes do not enable library storage.

The browser includes title, exact-tag and collection filters. An exhausted failed
extraction exposes an authenticated retry with its unchanged current grants; it
cannot retry a revoked, unsupported, blocked or stale-version source. Ordinary
transient processing failures still receive at most three automatic attempts.
The retry endpoint is `POST /api/library/items/{item}/retry-processing` with the
same version/metadata/permission expectation contract as deletion; it is not a
model-callable mutation tool.

The reproducible benchmark command is:

```text
python scripts/benchmark_library.py --output evidence/sanitized-results/private-library/local-load-YYYY-MM-DD.json
```

It uses a disposable synthetic SQLite/filesystem corpus, no `.env` and no upstream
requests. It measures listing, bounded search and finalization after structural
validation, and reports corpus size, concurrency, sample count and exclusions.
It does not measure hosted throughput or end-to-end parser latency.
