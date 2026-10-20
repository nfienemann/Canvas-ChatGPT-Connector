# Course document reading — text extraction

The private Windows source deployment can read actual authorized PDF, UTF-8 text
Markdown, DOCX and PPTX files without asking the student to download/upload them. On
2026-10-20 the installed connector resolved a module PDF, downloaded it through
three approved storage redirects and returned all 15 PDF pages in five bounded
MCP responses. The actual paper contained 74,408 extracted characters, including
methods, results, references and an appended correction. No course text, private
IDs, signed URLs or credentials are included in this repository.

## Conversation and tool flow

Ask: “What is Bundle 2, Paper 3 in my Stem Cell Engineering course about?”
ChatGPT selects the course, finds the module/file and reads the text. The student
does not need IDs. A listing alone never counts as reading the paper.

| Tool | Inputs and behavior |
|---|---|
| `list_course_files` | `connection_id`, `course_id`, optional `module_id`; file name/type/size, module associations, stable Canvas link, extraction state and opaque `file_id` |
| `read_course_file` | `connection_id`, `file_id`, optional PDF `page_start`/`page_end`, `offset`, `length`, `expected_hash`; metadata, text, page passages, chunk ID, content hash, continuation and limitations |
| `search_course_files` | `connection_id`, `course_id`, literal case-insensitive `query`, optional `limit`; matching indexed passages with PDF pages and explicit unindexed/incomplete coverage |
| `get_file_extraction_status` | `connection_id`, `file_id`; fresh access check and available/downloaded/parsed/partially_parsed/unsupported/failed/inaccessible state, without downloading |

`get_course_outline` joins File module items to opaque material references.
When Canvas denies the general Files collection, visible module files are
resolved using fresh course-qualified file metadata. Coverage remains partial
for denied/truncated collections. `fetch_course_material` remains compatible
and delegates file references to the same reader. Existing page search is unchanged.

Page numbers are PDF positions, including cover/correction pages, not necessarily
printed journal numbers. TXT/Markdown use one artificial page, stated as a limit.
DOCX range indices refer to stable text sections, not rendered pages. PPTX indices
follow the presentation slide order. Speaker notes and image text are not extracted.
Text and figure captions may be extracted; figure images are not interpreted.
All returned content is marked untrusted source data, never executable instructions.

## Boundaries and caching

- Maximum download 10,000,000 bytes, three redirects, bounded request time,
  200 PDF pages, 250,000 extracted characters and 16,000 characters per window.
- Stable opaque IDs include owner, connection, course and upstream file identity.
  SHA-256 identifies original document bytes; chunk identity includes document,
  page range, offset and requested length. Continuation requires the returned hash.
- Current course selection and fresh course-qualified file permission checks run
  for every read/status/search hit, including cache hits. Download and post-parse
  metadata versions must agree. Version or parser changes invalidate cached text.
- Previously extracted text is cached for 24 hours by default (configurable 1–24).
  A running service purges expired text at startup and every 60 seconds. When
  stopped, cleanup occurs at the next startup. Access denial, deselection and
  disconnect remove scoped derived content. Logical backups omit file text.
- Raw bytes exist only in a private per-job temporary directory and are removed
  after success/failure. Abrupt OS/power failure may leave a temporary job folder;
  the operator must remove abandoned folders while the service is stopped.
  No raw-file public endpoint exists. Host/volume backups and previous ChatGPT
  responses have their own retention; database deletion is not forensic erasure.
- Search covers previously extracted documents only. It reports unindexed files
  separately and never claims that “no match” means an unindexed paper lacks a topic.

## Windows deployment

Apply migrations through `4be2ca7831f0`, after a private encrypted backup. In
private operator configuration set `BRIDGE_FILE_READING_ENABLED=true` and set
`BRIDGE_PARSER_ROOT` to a private local folder outside Git/cloud sync. Leave the
feature disabled elsewhere. Restart the existing launcher. Refresh the installed
custom connector's tools in ChatGPT if its catalog predates these tools.

The service copies only Python standard-library/runtime, pypdf and defusedxml code into an
isolated runtime. Each job uses a unique Windows AppContainer SID, no network
capabilities and write access only to its own temporary directory. The worker
receives bytes and format only, not tokens, database access, service code or
inherited handles. A Job Object limits it to one process, 384 MiB memory,
10 seconds CPU and 15 seconds wall time, and kills it on cleanup. Worker output
is capped at 2 MB. One extraction at a time runs per server process.

The downloader accepts only operator-reviewed exact HTTPS origins and optional
exact hostname templates with one numeric `{file_id}` substitution. Every hop
validates public DNS/IPs and pins the connection while preserving TLS hostname
verification. Canvas bearer credentials go only to the initial approved Canvas
route; storage requests receive no bearer, cookies or Referer. Signed URLs are
transient and never returned as citations or logged. An institution's storage
origins must be independently reviewed before enabling downloads there.

Tests verify private-file/env/network/process/runtime-write isolation, memory
limits and worker timeout on actual Windows, plus mocked Canvas transport,
refresh, permission loss, versions, continuations, Unicode, scans and corrupt data.
Linux CI tests contracts and pure parsing; Windows isolation tests explicitly
skip there. Independent security review and fleet-wide quotas remain release gates.

## Remaining phases

Live XLSX/CSV extraction, OCR, image/figure interpretation, scientific
chart analysis and faithful table/equation reconstruction are not implemented.
Scanned or partly unreadable PDFs return explicit partial coverage/OCR limitations;
unsupported/corrupt/time-limited documents return a reason instead of empty success.
Multi-column reading order and mathematical notation may be imperfect.

Linux/macOS need equivalent verified parser isolation before live file reading
can be enabled. Existing native installers remain fictional previews; this feature
is enabled in the owner's private Windows source service. This service must be
running, with its PC awake and HTTPS connection active. No reinstall or new student
token is needed for the already configured personal connection.
