# DOCX tables and their relationships

`read_course_docx(connection_id, file_id)` returns the body order, table overview
and first structured records. Pass a returned `table_id` such as `T1` to read
that table's definition and cells. Follow `continuation` with its content hash.
The tool uses the existing authorized file retrieval and owner-scoped cache;
there is no new OAuth permission or Canvas write.

The structure retains:

- Body paragraphs and tables in XML order, with stable IDs within the source
  version. Paragraph style IDs and explicit outline levels remain source facts.
- Each table's explicit caption/description, grid column widths, row coordinates,
  repeating-header flags and omitted leading/trailing grid positions.
- Each cell's row, starting grid column, horizontal span, vertical merge origin
  and resolved row span. Empty continuation cells stay empty; origin text is never
  copied into them. Omitted grid positions are distinct from empty stored cells.
- Ordered paragraph/nested-table blocks inside cells. Nested tables have separate
  IDs and a precise `parent_cell` link; read those IDs to retrieve their contents.
- Preceding/following block IDs for each table within its containing body/cell.
  These are structural neighbors, not automatically captions, applicable policies
  or semantic headers. Floating tables flag uncertain visual placement.

Each returned record includes a Canvas reference URL, paragraph or table/cell
locator, content hash and retrieval timestamp; the response also contains the
Canvas source version. For example: `Table T1, R3C2`. DOCX text sections remain
compatible with `read_course_file`/`fetch_course_material` continuation and search;
they are **not rendered Word pages**. The compatible plain text index retains
author text without adding locator prefixes that could alter deadline or policy
matching. It references nested tables; use the structured reader for exact
block relationships and table/cell citations. Generic text search cites sections.
Reading subsequent records reuses extraction while rechecking existing access and
version boundaries. Parser v9 invalidates older flattened/prefixed DOCX caches; start a
new text read instead of resuming a pre-upgrade DOCX character offset.

## Uncertainty and exclusions

Conforming vertical merges must continue the same grid-column span in the next
row. Unmatched origins, changed spans, invalid merge values, legacy `hMerge`,
contradictory grid widths and content inside a continuation produce explicit
uncertainties and partial coverage. They do not create guessed merged values.
Missing table grids preserve span-based coordinates but mark the structure
partial. Unsupported row/table wrappers are reported, since skipped cells could
make the remaining coordinates incomplete. Semantic column headers, scientific
interpretation and grading rules are not inferred by this parser.

Body/cell content controls are supported. Tracked insertions, deletions and moves
are omitted and reported rather than silently choosing an authoritative revision.
Property changes and row/cell revision markers are detected separately; stored
row/cell records remain available with partial coverage and explicit uncertainty.
Images, equations, text boxes, headers/footers, comments and footnotes/endnotes are
not interpreted. Fields are never executed; stored field-result text may be stale.
Hyperlink display text can be read, but link destinations and external package
relationships are not followed. No visual Word renderer, style inheritance or
automatic list numbering is added. Word table semantics follow the
[documented vertical-merge rules](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticalmerge?view=openxml-3.0.1)
and distinguish [merged and omitted grid positions](https://python-docx.readthedocs.io/en/latest/user/tables.html).

## Bounds and privacy

The existing hardened OOXML and OS worker remain in place: 10 MB input/member,
1,000 ZIP members, 20 MB expanded, 200:1 member compression ratio, worker CPU,
memory/time limits and a 2 MB result limit. No new library is required.
Additional DOCX bounds are 100 tables, 200 rows per table, 100 grid columns, 4,000
cells, 5,000 paragraphs/records, nesting depth 8, 16,000 characters per paragraph,
32,000 JSON characters per record, 40,000 overview JSON characters, 240,000 index
characters and 900,000 structured-record JSON characters. Excessive or invalid
input fails explicitly instead of returning silently incomplete tables.
Responses return at most 50 records (default 20) and 60,000 record JSON characters.

The same scoped cache expiry, disconnect and deletion rules apply to text and
structure. No downloaded file is made public or permanently cached separately.
All content is untrusted source data. No credentials, permission policy, service
deployment or real Canvas content is changed by this increment.

## Verification boundary

Synthetic tests cover rubric headers, horizontal/vertical merges, omitted cells,
nested tables, adjacent paragraphs, continuation, precise citations, malformed
merges, revisions, XML/archive limits, cross-user denial and stale/revoked access.
They exercise the actual Windows worker and authenticated local HTTP MCP path.
The Linux container proof also checks merged/nested DOCX table extraction.
Live student documents remain unverified; the separately managed personal
service/auth work is outside this increment.
