# Assessment preparation budgets and verification

## Incident

The reported Ethics Quiz 12 call found eight candidates. The old loop admitted the first three by **position**, including failed attempts. It reviewed a schedule and extracted pages 1–4 of one PDF. A four-page progressive parser batch explains that page boundary. The third document returned `TASK_BUDGET_EXCEEDED`. The loop assigned `MATERIAL_DOCUMENT_LIMIT` to all five later positions before checking elapsed time or opening their content. The old 35-second aggregate and 15-second per-document deadlines have different reason codes. The four nearby readings carried unconfirmed relevance.

The historical response identifies the governor as the failing layer. Its shared error covers request count, units, reserved/received bytes, download attempts and elapsed task time, among other transport checks. The incident provides insufficient counters to attribute it to one of those dimensions. The MCP fixture below reproduces a 40-request stop under known conditions.

## Direct tool budgets

| Limit | Previous | Standard (default) | Thorough |
|---|---:|---:|---:|
| Candidate documents attempted per call | 3 | 6 | 12 |
| Material-phase elapsed seconds | 35 | 60 | 90 |
| Whole academic request, seconds | 90 | 90 | 135 |
| Read attempts including PDF depth | 3 | 6 | 20 |
| Normal per-attempt elapsed seconds | 15 | 20 | 20 |
| Extra elapsed allowance on the first file attempt only | 0 | up to 25 s | up to 25 s |

Use `review_mode="thorough"` for broader review. Either mode accepts up to 12 explicitly selected IDs. Standard takes the first six. The reader reserves the final 10 seconds of the academic request for the result and integrity decision. Every attempt also fits inside the remaining material budget. When another candidate is waiting for its first turn, the current candidate can consume at most half the remaining time. A cold allowance covers startup and I/O together. The parser prepares its runtime before starting the isolated worker deadline. The allowance is a ceiling on the first file attempt, including a cache hit or denial.

The assessment linked in the request gets priority over same-module candidates and schedule hints. For automatic selection, discovery resolves links for the selected assessment. A named assessment requires one assignment detail lookup. Automatic selection inspects details for up to 30 assessment-title matches. Assignment links have a separate 20-anchor, 10-second resolution budget. The outline can inspect up to 30 modules, 100 items per module, and the first 100 entries of the page/file lists. Partial inventory is disclosed separately.

Each candidate gets one turn before a long PDF gets another. Thorough mode then revisits PDFs in rounds using their first missing page. Each extraction visits at most four pages. `material_discovery.documents` reports source state, reasons, extracted pages, pages with usable text and extraction coverage. A blank or withheld page can be processed without yielding study material. Coverage concerns extracted text. Figures and layout require separate inspection.

## Continuation and output

- Pass `material_discovery.continuation` to `prepare_for_assessment` for a bounded group of deferred IDs. Keep earlier results and the original list if more IDs remain. A continuation returns the selected group's evidence. Each call rechecks access and integrity.
- Pass a document's `extraction_continuation` to `read_course_file` for missing PDF pages. Follow that reader's subsequent cursors with the same connection. The hash and parser version bind the read to the source. The ordinary cache supports reuse while fresh and authorized.
- `total_extracted_characters` counts available part text, excluding join separators. `excerpt_characters` counts text in that source's material excerpts. `excerpt_truncated` compares those two quantities. A first batch can have a complete excerpt and incomplete source extraction. A fully extracted PDF can have a truncated excerpt.
- The excerpt pool is 16,000 characters with a fair share per source, up to 4,000 characters and four parts per source. `excerpt_continuation` points at the first undisplayed character or part. Use `read_course_file` for a file ID or `fetch_course_material` for a page material ID. Other evidence fields, including citations, have separate bounds.
- Repeated terms come from extracted file/page text. They require overlap across at least two documents and carry versioned source passages. Filtering covers common instructional language, administrative terms and names following common instructor titles. This English keyword heuristic is fallible. Same-module relevance remains unconfirmed.

## Independent ceilings

- Canvas collection defaults are 100 entries per page, at most 20 pagination requests, 12 seconds per ordinary collection and 8 seconds per HTTP request. Workload refresh has its own multi-course scheduling budget. Direct assessment prep uses the ordinary collection path.
- All redirects, retries, preflight, discovery, membership, metadata and document transfers run through their existing controls. The governor's default task caps are 40 attempts, 100 units, 128 MiB and 120 seconds from the first accounted attempt. The operation ceiling is also 40 attempts. Downloads allow up to three redirects. The default download-attempt cap is six, or 24 under the private-development policy. Operator policy, owner limits, upstream cooldowns, file quotas and concurrency can bind sooner.
- The parser accepts PDFs up to 10,000,000 bytes and 200 pages. Aggregate extracted file text is capped at 250,000 characters. PPTX has its own configurable source ceiling of up to 32 MiB. The text worker has a 15-second wall deadline and 10-second CPU ceiling. The progressive PDF reader can recover finished pages after an interrupted worker. Cached reads still verify access and source metadata. Ordinary reader windows are at most 16,000 characters. Assessment prep previously requested a 1,000-character window internally and inspected the authorized stored parts. That window was never the full extraction limit.
- The composite academic workflow has an additional three-file, 120-HTTP-call, 30 MB document, 4 MB API, 30-second ordinary-step and 90-second workflow budget. The direct tool is the entry point for thorough review. The outer HTTP admission default is 240 seconds.

## Measurements

Earlier Windows AppContainer measurements on a 30-page synthetic PDF were 8.98 seconds cold, 0.63 seconds for four warm pages, 1.36 seconds for an authorized cache miss and 0.30 seconds for a cache hit. Other cold calls took 16.95 and 27.77 seconds. These measurements informed the one-time startup allowance and the four-page turn. Six first turns double the old breadth. Twelve covers the reported eight candidates with headroom. Twenty total turns cap depth work even with fast inputs. See [progressive PDF measurements](progressive-pdf-2026-11-04.md).

The assessment fixture contains eight PDFs totaling 22,959 bytes, including a 13-page paper, plus a schedule page. Direct service tests use real extraction logic with an in-process worker double and synthetic provider. They exercise access checks but do not share a single host request ID across all clients as an MCP call does.

| Synthetic run | Elapsed | Provider GETs | Result |
|---|---:|---:|---|
| Standard, cold extraction cache | 1.70 s | 38 | Six turns. First four long-PDF pages yielded 2,840 characters, all excerpted. Three candidates deferred by document count. |
| Thorough, after standard | 2.55 s | 50 | Twelve turns. All 13 long-PDF pages yielded 9,230 characters. The excerpt contained 2,840. |
| Thorough with a 10-turn cap and a delayed parser under a 1-second normal slice | 3.83 s | 55 | Eight parser invocations. Five documents fully reviewed, one long PDF partially reviewed, one blank PDF, one 403 and one timeout. Twelve usable PDF pages across five PDFs plus the schedule. A thirteenth extracted page was blank. |
| Synthetic HTTP/MCP with default thorough limits | 2.47 s | 40 | Three documents fully reviewed, four usable pages of the long PDF, a blank PDF and a genuine synthetic-provider HTTP 403. One governor failure and two deferred candidates. The emitted retry arguments worked in a fresh MCP call. |

The limited-pass test reads the omitted excerpt from cache with zero additional parser calls. The missing-page cursor starts at page 9 and adds one worker invocation. A targeted assessment continuation retries only the timed-out file. An injected task denial separately verifies that the affected file and the untouched suffix remain eligible to continue.

All measurements are local to the Windows working tree. No live coursework, service restart, private usage-ledger inspection, deployment or installed-client retest was performed.

## Checks

The assessment-specific suite passed all four tests in 19.22 seconds, including the synthetic HTTP/MCP continuation, protected text and explicit denied-link regressions. The broader development run passed 258 tests across academic requests, workload refresh, integrity preflight, usage integration, parser admission, progressive PDF reads, privacy and the benchmark lab. One usage integration test requires a disposable PostgreSQL database and was skipped. The broad run preceded the final linked-reading and regression-test edits. No full-suite result was reused.

After the linked-reading changes, the academic, benchmark, independent-document, October regression and integrity-preflight rerun passed 200 tests in 136.20 seconds. That run overlaps the earlier suites. The final four-test assessment run also exercised the denied-anchor and privacy-placeholder case. Ruff and the scoped Git whitespace check passed.
