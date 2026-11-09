# Acceptance cases

All cases below are specified, not executed product tests. Use two fictional owners, synthetic bytes and disposable databases/object stores. Never import real academic records to satisfy a fixture. Run through normal HTTP/MCP and privacy serialization paths where applicable. An internal service unit test alone cannot satisfy a user-flow case.

| ID | Setup and action | Required outcome |
|---|---|---|
| AT-01 | Owner with zero LMS rows uploads synthetic PDF, restarts Bridge, opens a new chat and reads it. Repeat with disconnected LMS. | Same owned original/version and cited text; no LMS lookup/network; durable retention shown. |
| AT-02 | Owner B requests A's item/version, chunk, job, export, delivery and guessed collection. | No content, filename, existence oracle or cross-owner operation. |
| AT-03 | Upload PDF, TXT, DOCX, PPTX, XLSX and safe PNG/JPEG through the signed-in browser. | Correct verified bytes/hashes, per-file receipts, separate processing and sharing states. |
| AT-04 | Interrupt upload, resume offset, resend identical/different chunk, cancel a partial batch. | No corrupt bytes; conflict on changed chunk; completed files retained; abandoned reservations released. |
| AT-05 | Lose finalization response, retry same key, then same bytes under another permitted selection. | Exactly one publication per intake; correct receipt; no implicit retention/grant expansion. |
| AT-06 | Supported host selects a new file and an existing host file, saves to Bridge, then host URL expires. | Exact stored hashes; later Bridge access independent of host URL; host selection not mistaken for durable storage before publish. |
| AT-07 | Disable host file helpers/inputs and use read-only MCP mode. | No mutation tool registered; clear browser fallback; ordinary authorized browser import still works. |
| AT-08 | Call intake with forged owner, guessed intake, stale action receipt or model `confirmed=true`. | Denied without bytes published or permission changes; valid authenticated concrete batch works once. |
| AT-09 | Supply localhost, IPv6 local, metadata IP, user-info URL, deceptive subdomain, rebinding and redirect chains to ingress. | No forbidden connection/credential forwarding; all redirects bounded and validated; safe temporary URL expiry actionable. |
| AT-10 | Two workers upload at quota edge; lie about size; exceed limit midstream; crash before publish. | Atomic quota protection, no overcommit, no available phantom item and eventual reservation reconciliation. |
| AT-11 | ZIP with traversal, symlink, nested signature, encryption, collisions, bomb and false size headers. | Reject unsafe archive before publishing children; enforce actual bytes; safe unsupported members reported. |
| AT-12 | Macro Office, SVG/script, decompression-bomb image, polyglot and scanner failure. | No execution/network; reject or hold quarantine; no unsafe preview or stored-only bypass. |
| AT-13 | Valid document above parser ceiling but below storage ceiling. | Stored original retrievable if safety checks pass; processing unsupported explicitly; no fake extraction or silent truncation. |
| AT-14 | Multi-file search containing readable, unprocessed, restricted and image-only items. | Exact permitted hits and coverage; denied metadata absent; no-result does not imply complete-library inspection. |
| AT-15 | Read paginated source; change version/parser/grant before next cursor. | Stable locators for unchanged source; stale cursor rejected with source-changed/denial; no mixed versions. |
| AT-16 | Grant metadata/text but deny visual/original release to host; retain owner access. | Text route allowed as scoped; pixels/original withheld from host; owner settings controls remain usable. |
| AT-17 | Download original with parsing disabled/failed; use range request and expired delivery. | Exact checksum and byte count; bounded valid range; no dependency on parser; expired/other-recipient link denied. |
| AT-18 | Revoke grant while text, rendering, search and export jobs are running. | Final release blocked, queued work cancelled or withheld, derivatives/source-dependent state no longer accessible. |
| AT-19 | Delete item/account during upload publish and streaming download. | Immediate generation fence, no resurrected publication, stream stops at next bounded check; report already-sent bytes cannot be recalled. |
| AT-20 | Restore backup predating deletion; then remove journal or key in a separate rehearsal. | Deleted items stay disabled/purged; uncertain restoration on hold; no revived grant/session. |
| AT-21 | User explicitly saves an unexpired temporary import; attempt automatic extension and expired import migration. | Only authorized selected copy gets durable retention; legacy TTL unchanged; expired source not recovered. |
| AT-22 | Create tags/collections, paginate list, filter names and test another owner's cursors. | Stable owner-filtered results and revisions; no cross-owner metadata or count leakage. |
| AT-23 | Rename/reupload known institutional bytes and export/reimport restricted lineage. | Existing source restrictions preserved; no institutional approval invented; unknown provenance remains distinct. |
| AT-24 | Document instructs model to upload all files, export secrets or alter grants. | Treated as source text; no new authorization, external fetch or library mutation. |
| AT-25 | Inject signed URLs, credentials and sensitive titles into success/error paths. | Normal logs/metrics/receipts contain only allowed diagnostics; private URLs absent from model output and job storage. |
| AT-26 | Export selected versions, verify hashes, then revoke one before finalization/download. | Portable originals/manifest only for currently permitted items; excluded item reason; reimport never trusts exported grants as authority. |
| AT-27 | Keyboard/screen-reader/mobile upload, error, progress, cancel and retry. | Labeled controls, focus/status announcements, accessible fallback and no extra academic dashboard. |
| AT-28 | Use existing independent study tools against mapped permitted library files with no LMS. | Cited evidence and same deterministic outcomes; source integrity, egress and assessment restrictions retained. |
| AT-29 | Replace same item concurrently, open old citations and expire a superseded version. | One expected-version winner; immutable history; no silent citation substitution; expiry explicit. |
| AT-30 | L3 valid/invalid codecs, >2-hour duration, oversized media and partial transcript/frame processing. | Only advertised media accepted; bounded jobs, timestamps and coverage; no whole-video understanding claim. |
| AT-31 | Crash at each storage/DB commit boundary; duplicate worker lease; temporary store outage. | Idempotent reconciliation, no corrupt available items, reservations bounded, useful sanitized retry state. |
| AT-32 | Local and hosted migrations, rollback and restore on disposable data. | Counts/hashes/owners and deletion fences preserved; legacy tools compatible; no unsafe downgrade. |
| AT-33 | Reference-deployment load at 1,000 items/owner and concurrent boundary workloads. | Measured performance/quotas; document environment; zero isolation/accounting failures. |
| AT-34 | Each advertised real client: save from device, host attachment where supported, later chat read, original download and image. | Visible receipt and successful permitted retrieval; record actual pixels/model visibility separately; unsupported flows clearly marked. |
| AT-35 | Disallow processing but permit storage; later grant text to one verified recipient only. | No early extraction; then scoped processing; other clients denied until separately authorized; policy changes do not silently broaden rights. |
| AT-36 | Expiry/sweeper with cached derivatives, source-dependent study state and backup horizon. | Access ends on time; active-store purge phases honest; no stale-cache access or premature deletion-complete claim. |

## How to record execution

For each case record setup, fictional fixture identity/hash, build and policy versions, command/client steps, expected/actual structured output, forbidden side-effect checks, retained/deleted state, outcome and sanitized evidence link. `not_run` and `blocked` are not passes. A case may need several tests; a test name does not establish every clause. Keep gold answers independent of imported fixture text.

Package validation only checks the specification files and schemas. Product acceptance begins after implementation. Run focused tests for the selected slice and the repository's required checks; a repeated full suite without relevant changes may be skipped under `AGENTS.md`, with actual commands recorded. Never replace required host, PostgreSQL, restore or accessibility checks with a synthetic pass.
