# Formats and processing

## Support matrix

Storage, parsing and understanding are separate capabilities. Every item exposes them separately. Below are proposed release scopes; existing parser limits remain until tested changes explicitly replace them.

| Format | L1 storage and owner retrieval | L1 analysis/preview | Later scope |
|---|---|---|---|
| PDF | Yes, validated original | Existing bounded text/OCR and page renderer, permission/configuration dependent | Higher limits only after resource and accuracy evidence |
| DOCX | Yes, validated non-macro package | Existing text/tables; no promised page-layout rendering | Tested layout renderer if needed |
| PPTX | Yes, validated non-macro package | Existing text and configured isolated slide rendering; notes/hidden content retain provenance | Larger decks only after bounded conversion tests |
| XLSX | Yes, validated non-macro package | Existing sheet/cell text and cached formula results; no recalculation or verified visual renderer | Explicit tested visual/recalculation capabilities |
| TXT, Markdown | Yes, UTF-8 | Bounded text with offsets; links never trigger fetches | Optional encodings with explicit detection |
| PNG, JPEG | Yes, safe decode required | Bounded sanitized preview; dimensions; optional local OCR with coverage; model interpretation only after actual pixel delivery | Additional raster formats after decoder tests |
| MP3, WAV, M4A | Disabled in L1 | None | L3 private original storage/playback; optional timestamped transcripts only through an approved processing adapter |
| MP4, WebM | Disabled in L1 | None | L3 private originals and owner streaming; bounded frame/transcript extraction; no automatic complete-video understanding |
| ZIP | Bounded batch carrier | Preflight manifest; only supported safe members; per-member receipts | Richer bundles separately gated; no nested Canvas export interpretation in this set |
| SVG, HTML, scripts, executables, macro Office, encrypted documents | Rejected in L1 | No active-content execution | A new reviewed allowlist entry and tests are required |
| Unrecognized/opaque binary | Rejected in L1 | No inference from extension | May be added as a narrowly named stored-only type later |

An accepted original above the extraction budget remains `available` and `processing=unsupported` only if file safety/type validation succeeds. Explain the limit before upload when known. A file whose safe structure cannot be checked is rejected/quarantined; “stored only” is not a way around validation.

## Proposed initial quotas

These numbers are product defaults for implementation/load testing, not statements about installed service capacity. Operators may lower them and must show effective limits before transfer. Raising them requires measured resource and funding evidence. All byte units are explicit.

| Limit | Default |
|---|---|
| Per-owner committed originals + retained versions + reservations | 1 GiB (1,073,741,824 bytes) |
| Per-owner active items | 1,000; retained versions also consume bytes |
| Single document original | 100 MiB storage; parsing still capped by existing format limits |
| PNG/JPEG original | 25 MiB and 40 million decoded pixels; 2,048-pixel maximum preview edge |
| Existing direct extraction budgets | 10,000,000 bytes except PPTX 25,000,000 bytes; retain parser expansion, page and execution bounds |
| ZIP | 50,000,000 compressed bytes; 100 entries; 200,000,000 total expanded bytes; 50:1 ratio; no nested archives |
| ZIP extraction members in first slice | At most 20 documents, each <=10,000,000 bytes, matching existing batch implementation |
| One upload selection | Up to 20 files; reservations enforce total remaining quota |
| Transfer concurrency | 2 uploading files per owner; 4 simultaneous ingress requests per owner |
| Processing concurrency | 1 heavy extraction/render per owner; bounded deployment queue and worker pool |
| L3 audio/video original | At most 500 MiB per file, still within owner quota; media duration <=2 hours |
| L3 transcript/frame jobs | Maximum 30 minutes of selected media per job, bounded continuation; no automatic full-library processing |

Derived storage has its own default 256 MiB owner budget and deployment ceiling. It cannot silently consume unbounded disk outside the original quota. Evict only rebuildable caches under current rights, never originals, and report incomplete indexes. Backups/quarantine/exports have independent deployment budgets included in capacity planning. Minimum L1 capacity plan accounts for 1 GiB originals plus versions within that quota, 256 MiB derivatives, worst-case reserved transfer, exports and the disclosed backup multiplier.

## Processing pipeline

Storage consent includes necessary type validation and safety scanning, disclosed at selection. Optional processing consent controls semantic extraction, OCR, indexing and study use. Declining extraction does not skip the safety checks needed to store a file; it does prevent creating a searchable text representation. Safety checks must not persist an incidental text extraction for other uses.

Identify type using a bounded signature/structure probe; validate extension/MIME consistency and reject polyglot/active-content hazards. Archive traversal, alternate stream names, symlinks, case/Unicode collisions, expansion ratio, member counts and actual decompressed bytes require checks. Reject nested archives by signature as well as filename. Existing checks must be strengthened where necessary; the current implementation alone is not proof of every new security case.

Workers receive only a bounded authorized source handle, destination and job configuration. They have no LMS credentials, unrestricted network, host filesystem access or permission-changing API. Reuse the current sandbox limits and private temporary cleanup. Disable external links, macros, embedded object execution and remote font/image fetches. Scanner failure produces `blocked`, never an assumed clean result.

Extract immutable text/structure representations keyed by original hash, parser version and policy. Keep original text separate from OCR, formula caches, speaker notes, captions and model observations. Store original locators and explicitly report omissions, truncation, hidden content and parser warnings. Index only current authorized representations. A job succeeds when it records bounded outputs and coverage, not when it merely finishes without an exception.

Image previews must remove irrelevant metadata, bound dimensions and reject decompression bombs. Exact originals remain available only through the separately authorized original channel. Audio/video previews/transcripts may reveal voices, faces, bystanders or other people's information; user possession is not a universal sharing grant. L3 needs specific privacy controls and no automatic transcription by an undisclosed external model.

## Evidence semantics

`stored` means verified bytes are retained. `extracted` means a bounded representation exists. `indexed` means specified representations are searchable. `rendered` means pixels or a media derivative were produced. `delivered` means a tested channel delivered that representation. `observed` requires actual model access to the pixels/media, and interpretation remains an attributed inference. None of these states imply the next one.

For study workflows, reuse existing permission checks and analysis engines. Unknown due dates, unsupported grade rules, incomplete readings and unavailable visuals remain explicit. Source text may contain instructions; treat it as untrusted evidence, never system policy or authorization to export, fetch, send or alter the library.
