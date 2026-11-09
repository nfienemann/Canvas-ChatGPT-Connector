# U01 - Simpler document imports

Priority: first | Status: development specification, not implemented evidence
Read README.md first. Outcome: ordinary materials become usable cited evidence without student-written JSON or an LMS connection.

## 1. Reuse and smallest useful slice

Reuse the authenticated import UI, independent store, parser workers, policy/egress controls and `independent-academic-1` adapter. Local list/read/search tools already exist; ChatGPT attachments are not automatically transferred. Inspect current code and repair only reproduced gaps, without another account, store or parser fleet.

Deliver: authenticate -> choose course -> add files -> review candidates -> ask a cited question. Extend settings, using one service for single and batch imports.

## 2. Student flow and sharing boundary

Offer “Add course materials” for verified PDF/DOCX/PPTX/XLSX/TXT/Markdown support and bounded ZIPs. Unsupported formats get an explanation. Allow course selection/creation and an optional purpose: syllabus, schedule, lecture, reading, instructions or own feedback. Filenames may suggest a course, never establish membership or authority.

Show filename, size, state and actionable failures. Support remove, course correction, failed-item retry and cancel. Cancellation stops pending work and cleans temporary data; completed items follow the chosen partial-import behavior. Never call a partial batch complete.

Separate local processing permission from sharing excerpts/images with ChatGPT. Show effective restrictions and an inspect/remove path without model sharing. Reuse per-document visual permission. Batch consent covers a concrete displayed selection, avoiding repetitive clicks. Mentioning a file is not sharing consent.

Use the authenticated browser file picker. Native-chat transfer is optional after verified host support, ownership and expiry. No arbitrary URLs, server paths or claimed upload IDs as substitutes for bytes.

## 3. Turn documents into reviewable records

Ready permitted documents support reading/search without obligation extraction. Propose dates, requirements, weights and titles with exact passages using supported deterministic rules. Optional host proposals use already-shared excerpts and remain labeled interpretations.

Show fact, evidence, precision, ambiguity and keyboard-accessible accept/edit/omit controls. Batch-review displayed unambiguous items; isolate conflicts, inferred dates/zones and unsupported rules. Never invent 11:59 PM. Preserve original candidates and student corrections as user assertions, not instructor amendments.

Compile reviewed records through the existing normalized schema and validated `independent-academic-1` adapter, never student-written JSON or an anonymous text blob. Preserve unknowns and rule/source links. Review cannot bypass unsupported grade-policy guards; plain text is not equivalent structured data.

## 4. Logical state and contracts

Reuse current models; map these requirements into them rather than duplicating names:

- Import batch: opaque ID, authenticated owner, selected course scope, idempotency key, declared/effective permissions, limits, per-item states and cleanup deadline.
- Source version: stable document ID, content hash, parser version, original filename for display only, inert origin metadata, extraction coverage, restrictions and retention.
- Candidate: stable ID, typed field/value, source version and locator/offset, exact passage, precision, extraction method and interpretation status.
- Review: actor/action receipt, expected candidate/source versions, accepted/edited/omitted items and resulting dataset version.

Use staged/validating/extracting/ready/partial/failed/cancelled states. Only ready permitted representations enter search/workflows. Store private bytes under generated names. Retries return the same result; same-owner deduplication never grants new course/sharing permissions or reveals another owner’s files.

Replacement targets an explicit document ID, not a matching filename. Changed evidence invalidates affected reviews. Return IDs/hashes and a continuation into study tools; parsing success is not model reading.

## 5. Acquisition, safety and resource controls

Enforce README’s no-acquisition boundary, including archive URLs. Preserve origin and restrictions on retained institutional copies. A caller’s “independent” label grants nothing; merely mentioning Canvas causes no blanket denial. Unclear rights require scoped clarification through existing policy controls.

Reuse isolated parsing and lifecycle controls. Validate extension/signature/container together; never execute active content or external relationships. Apply README R3. Extracted text does not establish visual interpretation.

Proposed initial bounds: 25 documents per batch; at most 10 MiB per document; 50 MiB compressed ZIP; 200 MiB total expanded bytes; 100 archive entries; 50:1 expansion ratio; one batch per owner concurrently. Enforce stricter existing parser limits, streamed byte counts and global queue capacity. A user ZIP may contain ordinary folders but not nested user archives. OOXML's internal ZIP structure is handled by its existing bounded format parser, not mistaken for an allowed nested import.

Before publication, reject traversal, absolute paths, symlinks, path collisions, encrypted archives and budget violations. List excluded harmless unsupported entries. Quarantine expires within 24 hours or stricter policy. No private paths/content/secrets in logs or errors.

## 6. Acceptance tests

U01-A1: Import a fictional syllabus, deck and reading through the normal authenticated UI with Canvas disabled. Obtain actual returned IDs; ask a supported question through HTTP MCP and verify exact source locations. Assert zero provider-network attempts.

U01-A2: A syllabus with one explicit date, one TBD date and conflicting word counts produces separate candidates; only reviewed facts reach the dataset. No fabricated time or resolved conflict appears.

U01-A3: No-source calls for all seven independent workflow capabilities return safe required-input guidance. Genuine sharing denial remains denial, not “upload missing.” Test final serialized channels.

U01-A4: Duplicate upload/retry creates no duplicate document; identical names in two courses do not overwrite. Replacement invalidates only dependent candidates and uses expected-version checks.

U01-A5: Traversal, symlink, ZIP bomb, false MIME, external relationship, corrupt OOXML and prompt-injection fixtures neither execute nor escape the sandbox. A restricted item cannot leak through a batch summary.

U01-A6: Foreign owner, revoked sharing mid-request and expired upload handle release no data. A known restricted retained copy cannot be relabeled; a permitted independent document remains usable with LMS authorization absent.

U01-A7: Restart/cancel/timeout preserves accurate per-item states and cleans quarantine. Account deletion and deletion-fenced restore remove sources and derived datasets.

## 7. Delivery gate

Require UI-to-MCP proof. Pilot target: four of five first-time users complete the fixture journey without operator help, JSON or commands; separate active time from parsing. This is an unmeasured target. Test old-import compatibility and disposable-database rollback. Report host-handoff limits honestly; live Canvas is not required.
