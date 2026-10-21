# Parser foundations: first increment

The shared `OfficePackage` reader now validates DOCX and PPTX inside the existing
isolated worker. Its immutable format registry also describes XLSX packages for
the next increment. **XLSX cell extraction is not enabled by this change.**

The package must contain the expected main part, declared content type and an
internal root document relationship. A renamed ZIP or a different Office format
cannot pass solely because its filename and ZIP signature look plausible. XML
uses the existing hardened parser; internal relationships resolve only to
validated members. External relationships are never fetched. The helper does
not extract files to disk, evaluate formulas or execute embedded content.

Shared bounds are 10 MB input, 1,000 ZIP entries, 20 MB expanded total, 10 MB per
member, and a maximum 200:1 member expansion ratio. Ambiguous names, traversal,
symlinks, encryption, macros, embedded objects, unsupported compression and
duplicate declarations fail closed. The current OS memory, CPU, wall-time and
output limits remain in effect. The standalone helper is explicitly copied and
hashed in both Windows and Linux runtimes; no new package or OS permission is
added. OLE containers are reported as encrypted **or legacy**, not conclusively
password-protected.

Parser version v5 invalidates older cached results. Existing tool contracts,
DOCX section references, PPTX slide references and text chunks are preserved.
DOCX sections are not rendered page numbers; tables are still flattened and
image/chart/layout interpretation remains outside text-extraction coverage.
XLSX container validation alone does not imply worksheet or formula support.
Safe parser error codes contain no raw XML, document text, local paths or URLs.

## Small follow-up increments

1. XLSX worksheet metadata and bounded cells; preserve formulas separately from
   cached values, with sheet/cell citations and explicit incomplete coverage.
2. PPTX structured slide content and relationships, with slide/object references
   and explicit coverage of tables, notes and visual-only content.
3. DOCX tables and their relationships: preserve row/column structure, merged
   cells and surrounding headings, while retaining the working text view.

Each increment should reuse native locators and coverage records in search and
continuation before expanding to additional modular parsing specifications.

Validation uses synthetic DOCX, PPTX and XLSX packages plus the existing
authorized read/search, cache-version and OS sandbox tests. No real workbook
contents or student records are used. Authorization and permission-audit code,
MCP permissions, download routing and the running personal connection are unchanged.
