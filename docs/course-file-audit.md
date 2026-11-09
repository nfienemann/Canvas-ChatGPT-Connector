# Public-path course-file audit

`scripts/course_file_audit.mjs` exports `CourseFileAudit`. Run it inside the
authenticated tool host by supplying `callTool(name, arguments)`, a private
checkpoint `save(state)` callback, the returned-image decoder, and the exact
connection reference from `get_connection_status`. It never reads the Bridge
database, Canvas credentials, raw source URLs, or an operator-only reader.
The same installed connector resolves the recipient and enforces authorization.
Do not replace a failed call with local source access.

Resume by passing the saved `state`. Completed attempts and successful continuation
windows are retained; use `run({retryFailed: true})` to explicitly retry failed or
partial files after a repair. Throttled in-flight files remain pending. A final fresh audit must
start a new checkpoint. Archive the earlier checkpoint rather than representing
old file successes as a fresh full pass. Checkpoint writes must be atomic; keep
live checkpoints outside the repository and cloud-synchronized directories.

The checkpoint contains opaque course/file identifiers, stable source identities,
source hashes, discovery paths, page/sheet numbers, continuation arguments,
outcomes, fixed diagnostic codes, request IDs and coverage flags. It excludes
document text, filenames, sheet names, source URLs, signed links and credentials.
The Node adapters in `scripts/course_file_audit_node.mjs` provide atomic private
checkpoint writes and an image decoder that pipes returned pixels to Pillow in
memory. They never download a URL. Supply the workspace Python executable to
`imageDecoder(python)`; corrupt/truncated data and render-success flags fail.
The caller must not persist complete tool responses. Image decoding must operate
on actual returned image blocks in memory; a render-success flag is insufficient.
The visual reader is also checked independently after a text-release failure:
text and image grants are distinct. Format hints retain only a fixed format enum,
never the filename. If a first visual page is released, its checked count/hash
drive every remaining page and each returned image must decode. Page-specific
failures do not skip later pages; source-wide permission denial stops that route.
Complete images with incomplete text remain partial file coverage.

Retries are limited to three attempts for `retry_later`. Retry-After is honored;
delays exceeding 60 seconds leave a resumable hold. A shared throttle or malformed
tool envelope halts the whole sweep. A numeric retry time must pass before resume;
where no delay is supplied, use a successful normal recovery probe before clearing
the audit hold. This does not clear or bypass Bridge's durable admission state.
Permission denials do not
trigger automatic grant changes. Unknown governance and stale authorization are
not counted as legitimate individual-file access denials.

## Resumable public discovery and acceptance boundary

The service now exposes `list_course_files(inventory_mode="resumable", cursor=...)`.
Follow `meta.next_cursor` with the same connection/course until absent. Each call
processes one upstream collection page or course-qualified linked-file lookup.
Files, the flat folder/subfolder collection, modules and all module-item pages,
and assignments are separate branches. Assignment discovery requests no grade or
submission expansion and is not restricted to a workload date window. It parses
all explicit file anchors within the existing description-byte limit instead of
silently stopping at twenty links.

Pass `resumableInventory: true` after verifying that the installed native tool
accepts resumable mode and follows its cursor. The current native tool passed
that capability probe with the ChatGPT recipient despite its displayed schema
being stale. A capability probe alone is not a complete inventory or file read.
The default bounded mode remains compatible with existing callers.

Continuations contain encrypted checkpoint references, never plaintext upstream
URLs. Server checkpoints use the existing encrypted, owner/connection-bound local
record store, bind the selected course and connection epoch, expire after 24 hours,
and cap traversal metadata at 2 MB. Normal authorization lease renewal is separate
from cursor expiry. Every page rechecks current authorization. Expiry, scope change,
oversized state, timeouts, malformed pages, cycles and denied branches prevent a
complete inventory. A transient response retains the unfinished cursor and its
Retry-After; replay repeats at most that operation, not the completed crawl.

Folder parents and opaque assignment/module paths survive the privacy projection.
Linked-file metadata denial returns an explicitly unverified reference; its reader
still performs the ordinary course-qualified metadata check and may remain denied.
Known restrictive assignment reviews also fence the release of linked-file
provenance. A reference, source listing, or resumable checkpoint is never a grant.

An interrupted discovery pass resumes after its completed courses and saved page.
Each new
finished pass explicitly refreshes all courses; file reading resumes from its
saved continuation. Historical discovery paths survive source-version changes,
while read/render coverage resets for the changed version.

Folder semantics: [Canvas Files API](https://developerdocs.instructure.com/services/canvas/resources/files)
documents the course folders endpoint as a paginated flat list including all
subfolders. Each folder's file pages require a fresh course-qualified folder check
with matching course context. Global folder routes are rejected without that
temporary binding. Caller-supplied URLs are never accepted.

No public tool invalidates the document cache or forcibly expires a scope lease.
The host may call `read(course, file, { render: false })` to finish text
continuations across courses before the visual sweep. PDFs/decks remain pending
until their required images decode; a later default `read` resumes visual
coverage without replaying completed text. This ordering option changes no
completion criteria. Public extraction status can establish an observed
unindexed-to-indexed transition around native reads; record those request IDs
and distinguish cache probes from full-file coverage.

Cold-cache and expiry behavior must use synthetic fixtures or independently
observed natural cache misses/expiry; do not assert a cold-cache run from the
first call in a chat. The normal course-list/reader refresh remains the supported
renewal route. A missing metadata, text, visual or original-byte grant remains a
distinct denial, even where other modalities have a grant.

## Checks

Install the pinned decoder dependencies with `npm ci --ignore-scripts --no-audit
--no-fund` from `scripts/audit-png-runtime`. Run
`node --test tests/course_file_audit.test.mjs tests/course_file_audit_png.test.mjs tests/course_file_audit_checkpoint.test.mjs`
from the repository root for synthetic runner and image-decoder cases, and
`python -m pytest tests/test_file_audit_refresh.py` for refresh diagnostics.
Installed connector results are separate evidence from these tests. Zero files
returned by a blocked inventory means zero discovered, with the true count
unknown; it does not mean an empty course.
Course enumeration must also report live freshness (or synthetic freshness in
fixtures), complete pagination and complete coverage. Missing, cached or
not-refreshed course enumeration keeps every reported inventory incomplete.

## Recursive validation request bounds

Each `inventory` invocation permits at most `maxInventoryPagesPerRun` tool calls
(default 1000, configurable from 1 to 1000). Reaching the limit records an
`AUDIT_REQUEST_BUDGET` hold with the next cursor intact. A subsequent `run()` can
resume the saved discovery; no completed page needs to be replayed. This is an
execution budget, not a claim that the remaining resources are inaccessible.

Successful text extraction and failed text extraction now use the same visual
audit path. Actual image decoding is necessary but insufficient: the source hash,
page number and page count must also agree with the requested document. A mismatch
remains partial and cannot produce `fully_read`.

The optional `decodeNativeImages` adapter accepts native tool image blocks. It
fully inflates and decodes bounded RGB/RGBA PNG pixels, verifies chunk CRCs and
the zlib checksum, and requires exact image dimensions and decoded byte count.
It returns `true` only when every image block passes, `false` when no images
exist, and `null` when the format or validation requires the existing Pillow
fallback. Never treat `null` as successful coverage. The adapter does not fetch
source bytes, change permissions, or establish source/page identity by itself.
Text requests use the public reader's existing 16,000-character maximum while
preserving returned continuation offsets, page ranges, and content hashes.
Known PPTX sources use `render_course_slide` at `standard` resolution with the
expected source hash. Other visual sources use `render_course_file_page`.
Slide identity and total count must match before decoded pixels count as coverage.
Operation records retain elapsed time and allowlisted numeric pipeline timings,
without copying source contents or resource URLs.

A host may maintain separate text and visual workers, but dispatch native calls
serially for the same connection. The connection guard serializes reads and
membership refreshes; overlapping long renders can make inventory requests hit
the guard's wait limit and return `AUTHORIZATION_BUSY`. Give each worker its own
checkpoint and honor each worker's rate-limit holds; never let them replace the
same checkpoint. Once both workers are stopped, `mergeVisualCheckpoint` imports
only matching connection/course/stable-file/reference/version/hash/format/page-
count evidence. It preserves the main inventory, text coverage, and current
denials. Rejected evidence requires a fresh read of the current source. A
subsequent `read()` reconciles the outcome without replaying decoded pages.
Deduplicated operation records retain the independent native request IDs.

For remote host orchestration, `checkpointDelta` sends changed metadata and
new operation records rather than the accumulated history. The local
`saveCheckpointDelta` adapter validates the prior revision, event boundary and
changed values, then atomically replaces the private checkpoint. Repeating the
same revision after a lost acknowledgement is idempotent. A conflict stops the
writer; reload the authoritative file before resuming. Keep one writer per
checkpoint and never merge or replace a checkpoint owned by a running worker.
The save adapter may acknowledge its committed revision on the isolated state
copy it receives. `flush()` retains that revision only after the save succeeds,
including across a no-change flush and a handoff to another worker.
