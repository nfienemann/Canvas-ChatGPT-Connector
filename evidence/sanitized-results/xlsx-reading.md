# XLSX validation — 2026-10-22

Scope: XLSX only, following the owner's clarification. PDF/DOCX diagnostic work
and CSV support are deferred. Existing uncommitted work in this checkout was
preserved. No credentials, real workbook content or private identifiers are
included in this record.

## Implemented

- MIME/extension dispatch and ZIP verification for XLSX, including generic Canvas
  binary MIME metadata with an `.xlsx` name.
- Credential-free Windows/Linux worker packaging for the workbook parser.
- Stored typed values, separate formulas/cached results, exact numeric lexical
  values, Unicode/Excel string escapes, zero/blank/empty distinctions, number
  formats and date system, sheet order, merged ranges and hidden content labels.
- Sheet/cell citations, deterministic text continuation, hash guards and search
  over the same cell text; compatible material-reader routing.
- Parser-version invalidation of previous failed/unsupported results; separate
  access/format/extraction status fields; XLSX capability and tool descriptions.
- Previously discovered module references survive partial inventory while fresh
  access checks remain mandatory. Explicit denial suppresses the fallback even
  when a later module request times out.

## Executed checks

- Full suite: **562 passed, 22 skipped** (118.91 seconds). Skips were Linux-only
  kernel tests, disposable-PostgreSQL tests and optional OCR test configuration.
- After the final explicit-denial/timeout correction, focused XLSX and file
  inventory suite: **88 passed** (8.18 seconds). No redundant full-suite rerun.
- After removing XLSX's dependency on optional PDF OCR configuration, the focused
  workbook/file/MCP/search suite passed **85 tests** (19.35 seconds), including a
  real MCP workbook read with a deliberately nonexistent OCR installation.
- Ruff lint passed. Formatting check passed for all 11 changed Python files.
  Repository-wide formatting reported an existing `scripts/build_desktop.py`
  formatting issue in prior uncommitted work; that unrelated file was not changed.
- `git diff --check` passed.
- Real Windows AppContainer XLSX extraction passed, including macro rejection.
- Authenticated local HTTP MCP test passed through the real Windows XLSX worker;
  it did not replace the parser with an in-process fixture implementation.
- Linux XLSX coverage was added to the kernel test matrix but is **not verified
  on this Windows host**.

## Private real-workbook check and installed connector gate

The updated direct local reader successfully downloaded and extracted the
owner-authorized workbook identified in the report. It returned `ok`, format
`xlsx`, parser `canvas-bridge-documents-v5-xlsx`, one sheet, 9,525 extracted
characters and a 1,500-character first response containing 21 cell references.
The result was indexed. Fingerprints verified unchanged connection credentials,
course selection and private configuration. Only the ordinary extraction cache
was populated. The private proof contains summary metrics, not workbook content.

That initial check was direct local reader evidence, not a deployed-MCP success.

The owner authorized a service restart. Automatic approval review rejected the
guarded private API stop/restart command as `blocked by policy`; it did not run.
After the owner reported refreshing tools, the exact installed-connector XLSX
request still returned `unsupported_feature` / unsupported format. Refreshing the
catalog did not establish that the serving process loaded the new code.
The owner then restarted the actual service. XLSX dispatch became available but
worker startup still failed. XLSX initialization unnecessarily depended on the
optional PDF OCR installation, whose configured model path was redirected into
the Codex Windows package's AppData. Windows file-handle path inspection verified
the mismatch. XLSX now initializes without OCR; no OCR/private configuration was
changed. The owner restarted once more after this fix.

**Installed connector gate: PASS.** The exact originally reported XLSX request
returned `ok`, format `xlsx`, parser `canvas-bridge-documents-v5-xlsx`, 1,500
characters and 21 cell references. Further calls through the installed connector
verified:

- Seven hash-consistent chunks reconstructed all 9,525 extracted characters.
- Repeat-read text and chunk ID matched; `fetch_course_material` returned the
  same complete text; an incorrect continuation hash returned `source_changed`.
- Status reported `parsed`, `indexed: true`, `access_state: available`, and
  `format_supported: true`.
- Cached search returned the workbook with the same hash and cell citations.
  Overall search status remained `partial_data` because the broader page/file
  inventory was partial; this is not a claim of complete course search coverage.
- The workbook contained 150 stored cells and no formulas. Formula/cache,
  hidden/merged content, date and hostile-file edge cases are synthetic test
  evidence, not claims about features present in this real workbook.
- Final fingerprints confirmed unchanged credentials, selection and private
  configuration after restart and installed-connector reads.

The private installed-MCP proof records request IDs and summary metrics without
workbook cell contents. The earlier automatic restart rejection was resolved by
the owner's manual restarts; there is no remaining restart blocker for XLSX.

## Intentional limitations

Formula recalculation, shared-formula expansion, localized display rendering,
automatic serial-date conversion, charts/images and complete Excel layout are
not implemented. Cached formula results may be stale. Content beyond extraction
budgets is explicitly partial and cannot be recovered by text continuation.
See [the XLSX contract](../../docs/xlsx-reading.md) for exact limits and semantics.
