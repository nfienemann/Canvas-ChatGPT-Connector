# XLSX reading

`read_course_file` and `fetch_course_material` accept authorized `.xlsx` workbooks
through the existing credential-free OS worker. File discovery, status and search
use the same path. XLSX does not require or initialize optional PDF OCR libraries.
The workbook MIME type and Canvas's generic
`application/octet-stream` are accepted only with an `.xlsx` filename, ZIP
signature and readable workbook structure. XLS, XLSM and CSV remain unsupported.

## Returned content

The text is JSON lines: a sheet header followed by stored cell records in row and
column order. Sheet order follows `workbook.xml`, not archive entry order or sheet
IDs. `page_start` / `page_end` select one-based **sheet positions**. They do not
represent printed Excel pages. Each passage includes `sheet_name`, `sheet_state`,
`cell_references`, and a human-readable sheet/cell locator. Search uses the same
extracted text and cell spans.

- Strings preserve leading zeroes, Unicode, rich-text content and OOXML escapes.
  Phonetic annotations are excluded. Newlines and quotes are JSON-escaped.
- Numeric values are strings containing their original numeric representation.
  This avoids binary floating-point rounding or accidental identifier conversion.
  Explicit blanks, empty strings, numeric zero, booleans and errors are distinct.
  Unstored grid cells are not expanded or invented.
- Formula text and attributes are separate from `cached_value` and
  `cached_value_present`. No formula, DDE command, macro, hyperlink or external
  data connection is executed or fetched. Cached results can be missing or stale.
  Shared/array formula attributes are retained; shared formulas are not expanded.
- Numeric dates retain their serial value, number-format ID/code when available,
  and workbook `date_system` (`1900` or `1904`). ISO date cells retain their stored
  string. This is not a localized Excel display renderer or a date converter.
  Custom numeric formats such as `00000` are returned alongside the raw number.
  When a styles table exists, cells without an explicit cell/row/column style
  retain its default style at index zero, including in formula caches.
- Hidden sheets and stored cells in hidden rows/columns are included and labeled.
  Merged ranges are listed; only stored cells are read, without copying an anchor
  value into the rest of the merge. Charts, images, comments, pivot tables,
  conditional formatting and visual layout are not interpreted.

The representation follows Microsoft's documentation for
[cell values and types](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.cell),
[formula/cache storage](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.cellformula),
and [Excel date systems](https://support.microsoft.com/en-gb/excel/date-systems-in-excel).

## Limits, cache and authorization

Existing limits remain: 10 MB downloads, 250,000 extracted characters, 16,000
characters per response, OS memory/CPU/time restrictions, and 2 MB worker output.
Workbooks additionally allow at most 200 sheets, 50,000 visited cells, 1,000 ZIP
members and 20 MB total expanded ZIP bytes. ZIP duplicates, encryption, extreme
compression, embedded objects/macros, invalid references and XML entity/DTD
inputs fail closed. Sparse dimensions never cause expansion to a rectangular
grid. Whole cell records are omitted at the text/cell budget, and coverage is
explicitly partial. Remaining sheets/cells require another extraction strategy;
text continuation cannot recover content omitted by extraction limits.

Omitted row indices can be recovered from explicit cell references in the row;
conflicting row/cell indices still fail closed. Unknown cell types are rejected
even without a stored value, and duplicate value/formula/inline-string elements
are rejected instead of silently selecting the first value. Optional indices,
default style zero and single-value element cardinality follow the
[Microsoft row and cell schema documentation](https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/how-to-insert-a-chart-into-a-spreadsheet).

Workbook bytes determine the content hash. Continuation requires that hash and
the same sheet range; `chunk_id` is repeatable. File version, parser version and
expiry fence caches. Legacy unsupported/failed results without the current parser
version are cleared, including their stale limitations. Every read and search
hit still checks current course selection and course-qualified file permission.

Status exposes separate `access_state`, `format_supported`, `extraction_outcome`,
and `parser` fields while retaining legacy `state`. Format support does not imply
a successful extraction or complete visual interpretation. Parser version is also
returned with outline capabilities, which now list XLSX.

A previously discovered file reference for a visible module item can survive a
partial broad inventory. It is marked `previously_discovered_access_not_rechecked`
and its metadata is marked `not_rechecked`. Explicit fresh denial suppresses that
fallback. The reference never substitutes for the reader's fresh access check.

## Validation and deployment

`tests/test_spreadsheet_reading.py` uses only synthetic workbooks, exercises the
semantics above, reconstruction, search agreement, cache invalidation, access
loss, partial inventories, ZIP/XML attacks, a real Windows AppContainer, and an
authenticated HTTP MCP call through that sandbox. Linux XLSX extraction is added
to the existing kernel test matrix; Windows runs skip that Linux-specific case.

No database migration or credential/selection change is needed. Restart the
existing private service to load the new reader and parser version. The installed
tool catalog may also need refreshing to show XLSX in tool descriptions. Local
tests alone do not establish success through the installed ChatGPT connector;
the [live acceptance result](../evidence/sanitized-results/xlsx-reading.md) records
a successful installed-connector workbook read and continuation/search checks.
