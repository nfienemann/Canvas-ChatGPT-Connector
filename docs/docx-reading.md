# DOCX reading

Parser `canvas-bridge-documents-v6-docx` reads bounded WordprocessingML text through
the existing credential-free OS worker. DOCX uses the same fresh course/file
authorization, download checks, temporary-file cleanup and resource limits as
other course documents. No new tool, permission, download origin or dependency
is introduced. The PDF-only image renderer remains PDF-only.

## Text and references

- Adjacent text runs join without injected labels or spaces. Tabs, line breaks
  (`w:br` and `w:cr`), soft hyphens and nonbreaking hyphens are preserved.
- Body paragraphs, hyperlink labels, stored field results and table-cell text
  follow XML order. Hyperlinks are never fetched and fields are never evaluated.
- Nested text boxes are traversed once with paragraph boundaries; their visual
  placement on a Word page is not reconstructed.
- Inserted/moved-to text is included. Deleted/moved-from text is excluded.
  This is a text-extraction policy, not a reconstruction of revision history or
  Word's formatting/review settings.
- Mutually exclusive compatibility content uses its fallback only. Unsupported
  extension-only content is omitted with a returned limitation.
- Both standard transitional and strict WordprocessingML namespaces are accepted.
  Non-Word text nodes, including equation XML, are not ordinary body text.
- Empty paragraphs are omitted. An empty body returns one empty text section,
  `partial_data`, explicit no-text warnings, and `indexed=false`.

Section indices are connector text groups, **not rendered Word pages or native
OOXML section breaks**. Whole text blocks are grouped toward 8,000 characters;
one long paragraph can exceed that target and remains subject to the 250,000
character document cap. Canonical text has no locator labels. Short reads of the
same parser/source version reconstruct that text; sources carry section labels
separately. Exhausting the text budget with unread content always reports partial
coverage, including when a paragraph ends exactly at the cap.

Heading text and list-item text can be read, but heading hierarchy and automatic
list numbering are not reconstructed. Table text is flattened; merged cells,
column alignment and visual row order are not verified. Headers, footers,
footnotes/endnotes, comments, images, equations and embedded objects are not
interpreted. Text extraction does not establish a complete visual reading.

The `w:cr` behavior and nested paragraph handling follow Microsoft's descriptions
of [CarriageReturn](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.carriagereturn)
and [TextBoxContent](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.textboxcontent).

## Failure status and upgrades

Access, format support and extraction outcome remain separate. A malformed main
document returns `EXTRACTION_INVALID_DOCX_STRUCTURE` at `text_extraction`;
malformed XML/ZIP returns a bounded unreadable-content error. These failures and
processing resource limits produce `state=failed` / `extraction_outcome=failed`,
while `format_supported=true` and `access_state=available` can still hold.
Unread search uses the same classification. The existing top-level
`unsupported_feature` status for corrupt content is retained for compatibility;
it must not be interpreted as a statement that DOCX as a format is unsupported.
Explicit capability exclusions, such as macros/embedded active content, remain
`unsupported`. Runtime setup, worker launch, timeout and result failures retain
the shared stage-specific diagnostics described in [file reading](file-reading.md).

The parser version change invalidates old success/failure caches on the next
authorized access. Failed extraction is retried by a later authorized read.
Restart the existing service as part of a coordinated deployment before live
acceptance; an already-running v5 process does not become v6 merely because the
source files changed. After an upgrade, start a fresh read at offset zero.

Synthetic validation and the installed-service evidence boundary are recorded in
[the DOCX investigation](../evidence/sanitized-results/docx-processing-2026-10-22.md).
