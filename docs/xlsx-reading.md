# XLSX reading: worksheet names, cells and formulas

`read_course_workbook(connection_id, file_id)` returns worksheet names, order,
visibility, actual stored-cell bounds, declared dimensions, date system, named
ranges, merged regions and table definitions. The file ID comes from the existing
course-file listing; students need not know Canvas IDs or sheet names beforehand.
Pass `sheet_name` and optionally `cell_range` (for example `A1:F25`) to read cells.
`query` performs literal search over extracted cells, optionally across sheets.
The tool uses the existing authenticated file download and owner-scoped cache.

Each cell preserves its A1 address, typed value, raw XML value where present,
number format, date/time interpretation, formula expression, separately stored
cached result, and error state. Dates retain the workbook's 1900/1904 date system.
String sample IDs keep leading zeroes; a value of `0.25` with format `0.0%`
remains a decimal plus its format, not the number 25. Formula caches are labeled
`available_unverified_freshness` or `unavailable`. No formula is evaluated.
Array or other unsupported formula types retain their expression and XML
attributes with an explicit status. Reference flags are lexical hints, not
verified dependencies; external references are never fetched.

The parser uses [openpyxl's read-only and data-only modes](https://openpyxl.pages.heptapod.net/openpyxl/_modules/openpyxl/reader/excel.html)
in separate views, after the shared OOXML validator and hardened XML checks.
Only the parser helper, openpyxl and its et_xmlfile dependency are added to the
existing Windows/Linux isolated runtime. No network, filesystem or OAuth
permissions are added. Macros, executable objects, unsafe relationships and
unsupported package types fail closed. XLS, XLSM and encrypted files are not
supported. Workbooks are never saved back to Canvas or executed.

## Bounds and coverage

- Existing input/archive bounds apply: 10 MB input, 1,000 members, 20 MB expanded,
  10 MB per member and 200:1 maximum member compression ratio.
- At most 50 worksheets, 5,000 extracted nonempty cells, rows 1–5,000 and columns
  A–CV. The reader examines actual stored coordinates, not trusted dimensions.
- At most 240,000 cell-index characters, 900,000 structured-cell JSON characters,
  30,000 metadata JSON characters and 8,192 characters per scalar/formula.
- Each response returns at most 200 cells (default 100), further bounded by
  a 60,000-character cell-record budget. Continue using the returned parameters
  and content hash; cached chunks do not redownload or reparse the workbook.
- Existing OS CPU, memory, timeout and result-size limits remain in effect.

Extraction truncation marks both the affected worksheet and overall result
partial. Sparse far-away cells are reported in source bounds even when outside
the extraction window. Unreturned cells in a partial sheet are **not known blank**.
Continuation advances through the extracted selection, not omitted source cells.
An oversized metadata section or corrupt workbook fails explicitly rather than
inventing a workbook structure. Charts, pictures, pivots, conditional formatting,
external refresh and scientific interpretation remain unsupported.

`read_course_file`, `fetch_course_material` and course-file search also use the
XLSX text index, including sheet/cell labels. Structured reading is preferred for
formulas. Citations include the Canvas file URL, quoted sheet/cell locator,
content hash, retrieval time and source modification time. Parser v6 invalidates
older extraction caches. Existing retention, disconnect and deletion behavior
applies to both text and structured cells; no additional permanent store exists.

## Verification

Synthetic tests cover values, formulas with/missing caches, dates, both date
systems, errors, hidden and empty sheets, merged headings, named ranges, tables,
sparse dimensions, corrupt/malicious packages, resource limits, cache reuse,
source changes, revoked access and cross-user isolation. A real local HTTP MCP
test exercises authenticated tool discovery and sandboxed extraction. Linux CI
also extracts XLSX inside the restricted container. No real student records are
committed or needed for automated tests.

The Rowan `PCR_Analysis.xlsx` live acceptance check is pending: the installed
ChatGPT connection returned `UNAUTHORIZED` / `Reauthentication required` on
October 22, 2026. No claims about that workbook's sheets or data have been made.
This source push does not restart or replace the running personal service.
