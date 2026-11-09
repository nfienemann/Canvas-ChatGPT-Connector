# Stage 4 course content portability acceptance

The frozen synthetic build passed 17 of the 18 combined acceptance cases. PORT-T18 passed its product checks and awaits independent scoring of the final host answer. All 254 selected Python tests and 87 JavaScript tests passed. The complete repository suite and deployment were outside this run.

[Implementation and operating scope](../../docs/course-content-portability.md) · [Implementation diff](course-content-portability.patch) · [Verified receipts and case index](course-content-portability-receipts.zip)

## What made the round trip

The marketing packet contained nine sources in six formats. On a clean destination, eight originals were eligible for direct restoration. BUS-PREF-01.txt travelled as a reference. Acquiring its original bytes separately mapped it to a different destination ID. All nine hashes then matched. The reviewed memo still carried the student's in-progress declaration, the chosen study preferences survived, and replay returned the original commit receipt.

Across six courses and a shared-materials selection, 16 sequential units accounted for 236 source files. The importer accepted 202, classified 32 CSV, JSON and PNG members as unsupported, and withheld two under its privacy checks. The destination restored and hash-checked 196 originals. Six selected references still required independent acquisition. The withheld sources were the operations syllabus PDF and the operations deadline-revision Markdown file. Each unit stayed under the existing 20-document owner limit. The synthetic runner removed verified materials between units. This measures a bounded semester workflow.

## Build and verification

- The tested base commit was `5bd086356e730b01b5a9f1be9de106446ef049c6` on `codex/visual-pdf-reading` with uncommitted work. The frozen application source SHA-256 was `13a8ecf364bf1bd95ed4efed3d948a939516a87874be468c4a44726b612e2eb4`. The patch covers 17 implementation paths, the two new test modules and the operating guide. Its pre-existing source paths were individually checked against the preceding model-independent build manifest. The diff passed an application check on that baseline.
- Python 3.14.5 ran authenticated settings and HTTP tool tests, the current local parser, two independently initialized SQLite stores, and the supplied Operations, VAI and model-independent replays. Controlled packet and semester tests used October 29, 2026 at 16:00 UTC and a synthetic owner. Other lifecycle and concurrency tests used isolated service clocks. The calendar read occurred two hours after the controlled baseline.
- The Stage 4 ZIP SHA-256 was `e91dc8bb1c5c1cf660155d087cab62057702b0bc02622f43815d47614ac0935f`. The package validator checked 49 package checksums, 73 controlled member hashes, nine ZIP CRC sets, 236 semester members and 39 literal quotations. The optional separate original-source ZIP was unavailable.
- Ruff checked lint and formatting for 18 Python files. The import script passed the Node syntax check. The JavaScript suite passed 87 tests. The regression run passed 254 Python tests with the four original acceptance bundles enabled. An earlier run on the moving checkout detected a source-fingerprint change during the Operations replay. The final freeze passed that replay and its end-of-run source check.

## Acceptance cases

Each numbered entry links to actual request and outcome files through `acceptance.json` inside the receipts archive. That file also identifies the tested build. `semantic-comparison.json` contains the per-unit semester results, unresolved items and one-course comparisons.

| Case | Outcome | Observed behavior |
| --- | --- | --- |
| PORT-T01 | Pass | The nine marketing and preference sources kept their byte versions and runtime bindings. The brief yielded three deliverables and its November 2 due date. Returned feedback attributes the design description to the feedback file. The original case and final submission remain unverified. |
| PORT-T02 | Pass | All entries in the supplied moved and 378-character-path packets received outcomes. Recognized moves kept their bindings. A Unicode normalization collision was rejected before either file was stored. |
| PORT-T03 | Pass | Reversed entry order and a second occurrence of identical material preserved the course binding set. The same reviewed memo survived recovery. Fresh calendar readback found one parent event and proposed zero duplicates. |
| PORT-T04 | Pass | Marketing and finance received different bindings and runtime IDs for identical reading bytes. Deleting the marketing copy left the finance copy readable. Role and term also separated identical bytes. Existing foreign-owner and recipient controls ran with the regression suite. |
| PORT-T05 | Pass | The revised notice received a new version while retaining its earlier hash and location. November 4 in the notice and November 2 in the unchanged brief remained unresolved. A separate requirement-change control preserved the earlier personal progress and required review. |
| PORT-T06 | Pass | Two same-content candidates produced an ambiguous decision. The signed-in student selected an existing destination from the preview. Its runtime ID and scope were retained. |
| PORT-T07 | Pass | The selected baseline and semester coverage identified MKT320-C01, OPS330-N02 and OPS330-R04 as missing at unknown versions. Readable assignment passages and deliverables remained available. |
| PORT-T08 | Pass | The fresh dropout had no retained F01. Reacquiring its exact original SHA-256 made the feedback available under its own source. The original case remained missing. Other selected source hashes and bindings stayed stable. |
| PORT-T09 | Pass | An omitted F01 was still readable in an existing workspace. Explicit deletion blocked later import and an older export. Deletion was also checked when a reference would map to a different destination ID. |
| PORT-T10 | Pass | A clean same-owner destination could create eight sources. The preference-source file required separate local acquisition. All nine source hashes then matched. The explicit personal memo progress, selected preferences and source-ID map survived the round trip. |
| PORT-T11 | Pass | A declaration and its child retained their typed value, source, observation time and dependency. A grade fixture retained numeric zero, null, omitted fields and false. The memo due timestamp and personal progress remained distinct from official evidence. The old plan required replanning. |
| PORT-T12 | Pass | An edited destination produced an explicit version conflict. The stale replacement preview was rejected. A fresh approved replacement advanced the destination revision. A separately created destination review was retained and reported as unresolved. |
| PORT-T13 | Pass | A storage failure after document staging rolled back the unit. Retrying the same reviewed selection committed it once. Two concurrent retries returned one durable receipt. Unresolved parents stayed in the package. The existing import cancellation/retry regression also passed. |
| PORT-T14 | Pass | A verified current store or paired live source supplied deletion continuity. Wrong owners, a changed generation, missing authority, an expired review, and post-export deletion blocked activation. An aged container retained its original expiry. Sharing required a fresh destination decision. |
| PORT-T15 | Pass | A real local adapter and a synthetic Canvas adapter produced separate namespaces. Explicit confirmation grouped their assignment and kept both deadline assertions. An authorized same-store export recognized the link, unlink restored two entries, and disconnect left only eligible local evidence. The separate finance replay preserved its word-range conflict under a deadline-only amendment. |
| PORT-T16 | Pass | Malformed or truncated packages, incorrect payload digests, duplicate record IDs, traversal, absolute names, Unicode collisions and oversized entries received explicit outcomes. Missing selected dependencies stayed inactive. The destination remained coherent. |
| PORT-T17 | Pass | The supported combination is course-workspace-1 with academic-process-export-1. A future major, a future required record kind and malformed schema metadata were rejected. The tested typed citation remap preserves the source version and work identity. This is the first workspace format and has no legacy workspace migration. |
| PORT-T18 | Product passed, host review open | After a two-hour clock advance, the historical plan required replanning. The current plan remained provisional, one existing parent event was recognized, zero duplicate proposals were generated and zero external writes were executed. An independently captured final host response against this build is still needed for the six fidelity checks. |

## Remaining evidence boundary

The current planning result was provisional. The verified calendar snapshot contained one matching parent event and produced zero proposals or provider writes. No final host answer from this build was captured. The receipt archive includes a host input containing only the released planning and calendar results, plus a separate six-check evaluation rubric. An independent reviewer can run the isolated case and score the actual answer. Raw live Canvas accounts, live calendar writes, cross-installation PostgreSQL continuity, and simultaneous 236-document storage were outside the supported test scope.

The receipt ZIP contains 90 entries. Its SHA-256 is `7b5515c70b398b083557385ce2b099a54389077fbbe97d706290c9a94d39707f`.
