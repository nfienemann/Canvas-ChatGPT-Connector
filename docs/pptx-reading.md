# PPTX analysis budgets and evidence

The v9 reader separates source download, ZIP expansion, extraction, rendering,
and original delivery. Local code is not proof that the installed connector has
loaded it. See [validation](../evidence/sanitized-results/pptx-analysis-2026-10-22.md).

## Audited paths

| Boundary | Code / configuration | Limit |
|---|---|---|
| Inventory / authorization | `course_files.list_files`, `authorized`, `file_metadata` | Discovery is not content access; fresh course/file checks precede reads, cache hits and renders |
| Canvas API JSON | `CanvasClient`, `BRIDGE_MAX_RESPONSE_BYTES` | 2 MB default JSON; 8 s request / 12 s refresh defaults, independent of source file capacity |
| Extraction source | `file_download`, `document_policy`, `BRIDGE_PPTX_SOURCE_MAX_BYTES` | PPTX 33,554,432 bytes (32 MiB), configurable downward; other formats retain 10,000,000 bytes |
| Source transfer | `BRIDGE_PPTX_DOWNLOAD_BUDGET_SECONDS` | 60 s total PPTX download/retry budget, configurable up to 90; per-request timeout still applies; one active analysis download per process |
| Transport | `file_download` | Three approved redirects, identity encoding, 64 KiB chunks; bearer only on initial approved Canvas route |
| PPTX ZIP | `presentation_worker.Package` | 4,096 members, 64 MiB total declared expansion and cumulative actual reads, 32 MiB per member, 4 MiB per XML/rels member, 200:1 expansion ratio, 200 slides |
| Text worker | `parser_sandbox`, Windows/Linux sandbox | One worker per process; 384 MiB committed memory, 10 s CPU, 15 s wall; no credentials/network/service mounts |
| Text output | `parser_worker`, parent validation | 250,000 canonical characters including separators; 128 spans per slide; 2 MB worker output |
| MCP text response | `chunk_result`, `app.register` | PPTX eight slides / 8,000 characters per batch (general input still permits 16,000); 250 KB UTF-8 JSON envelope |
| On-demand search | `document_search` | 45 s budget, up to three new documents; use direct read for a specific large deck if search times out |
| Original delivery | `file_delivery`, `BRIDGE_FILE_DELIVERY_*` | Independent 50 MiB source / 90 s / 512 MiB staging / 300 s default expiry |
| Inline original | `BRIDGE_FILE_DELIVERY_INLINE_BYTES` | 128 KiB; larger files use existing resource/browser handoff; native attachment is unimplemented and host support is separately negotiated |
| PDF pixels | `visual_worker`, `visual_files`, MCP image blocks | 10 MB PDF input, edge up to 2,400 pixels, 1.3 MB PNG, 1,733,336 base64 characters; metadata envelope 250 KB |

Content-Length is checked when present, never trusted in place of counted bytes.
Unknown metadata size is supported within the same cap. Invalid sizes fail;
known stale sizes/header disagreement/truncation return `INCOMPLETE_TRANSFER`.
Responses close on failure, cancellation and timeout. Source buffers are bounded;
media is not inflated during text extraction. A 25 MB source fits source policy,
but not necessarily XML, expansion, memory or CPU policy. The approximately 41 MB
regression deck remains outside the standard extraction tier.

## Slide contract

Use existing `read_course_file`; page ranges address slide indices. Follow the
returned continuation exactly, including range and hash: it advances character
windows, then slide batches. Search indexes all extracted slides up to the text
cap. No overlapping presentation-reading endpoint was added.

Slide indices come only from the direct, namespace-qualified presentation slide
list. PowerPoint section references do not add slides or change their numbering.
Hidden slides remain in source order and expose `hidden` in each slide record.

Legacy text/passages/page_extraction/sources remain. `slides` adds slide number,
source file/version/hash, text window, notes, text provenance spans, media counts,
warnings and citations. Notes and chart caches also appear in canonical text,
with separate spans; locator labels never enter that text. Table text uses XML
order, not reconstructed geometry. Cached chart labels/values are not evaluated
formulas or visual interpretation. Embedded XLSX workbooks are not opened. Active
OLE/macros are rejected. Notes omit slide-number/date/footer placeholders.

Empty and image-only slides retain records/citations. Damaged slide/related XML
gets `unreadable` and partial coverage, preserving other slides. Invalid ordering
or global ZIP failures reject the package. Truncation declares omissions.
Unreadable records never claim `text_complete_in_response`, even when empty.
`visual_observation=null`, `graphics_inspected=false` and
`visual_status_scope=this_text_extraction_only` prohibit invented visual claims.
Rendering has its own response/receipt; complete XML is not complete deck review.

SHA-256 identifies original bytes. Current metadata version, parser version and
configured source limit fence cache reuse; fresh permissions and final connection
epoch checks remain mandatory. V9 invalidates earlier parser caches. Existing 24-hour maximum
text retention/purge remains; no source or image is persistently cached here.

Schema 1.0 retains `FILE_TOO_LARGE` and legacy observed_size/limit_bytes, adding
`budget_code=SOURCE_FILE_TOO_LARGE`, observed/limit and retryable=false. Original
delivery uses `budget_code=ORIGINAL_DELIVERY_LIMIT`. ZIP failures use
`PPTX_EXPANSION_LIMIT`, stage `zip_expansion`, numeric observed/limit and a budget
key. Failed extraction is not cached as empty success.

## Experimental rendering: default off; scoped private acceptance

`BRIDGE_PPTX_RENDERING_ENABLED=false` is the default. A public LibreOffice runtime
can be supplied through `BRIDGE_PPTX_RENDERER_ROOT`. `render_course_slide` uses a
private one-slide PDF derivative; `render_course_file_page` remains a compatibility
alias. Linux/macOS conversion fails closed. Do not enable/advertise this
route until native rendering, isolation and client-pixel gates pass on that host.

The prototype validates package/XML and raster dimensions, rejects active
objects, embedded packages, external linked media and unsupported media types,
accepts validated static self-contained SVG, builds a one-slide dependency package
inside isolation and exports it through LibreOfficeKit. It validates the single
PDF page and geometry, then uses the existing PDFium rasterizer. PDF page 1 maps
explicitly to the original slide, including hidden slides. Fonts/layout/animations may differ
from PowerPoint. PNG/JPEG/GIF/BMP/TIFF images have a 16-million-pixel bound.
Macros are disabled; hyperlinks are never clicked. Operator program/share/presets
are copied without an existing user profile. Native binaries are not in Git.

EMF support is intentionally narrow and runs inside the same isolated worker.
Classic EMF accepts only bounded static pens, brushes, fonts, text, clipping,
paths, lines, ellipses, rectangles and source-free PATCOPY. Escape, OpenGL,
color-profile, nested-metafile and unknown records are rejected. Full-frame
EMF+ premultiplied BGRA bitmap wrappers with the supported identity-transform
sequence are normalized to PNG. Their optional, structurally bounded PDF
alternative is discarded without parsing; original EMF+ bytes never reach the
native converter. The original source is unchanged. WMF and other EMF variants
remain unsupported. Bounds include 8 MiB per EMF, 20,000 records, 4,096 handles,
32 saved states, 16 million pixels and 32 MiB total normalized PNGs. All source
media are checked, including unrequested slides; raster extensions must decode
as an allowed raster format. The converter identity and isolated runtime digest
advance to prevent stale reuse. See the [bounded EMF evidence](../evidence/sanitized-results/bounded-emf-2026-10-23.md).
The earlier [sectioned-deck repair record](../evidence/sanitized-results/presentation-order-2026-10-23.md)
preserves the preceding, blocked state.
Render failures report `text_fallback.status` as `available`, `failed` or
`not_checked` using current file/version/parser evidence for the requested slide.
This never substitutes for visual coverage. Aggregate server-stage evidence is
preserved on both success and failure, including version-checked cache reuse;
model visibility and interpretation still require evidence from the client.

The converter is a fixed child in the same credential-free, no-network
AppContainer and non-breakaway Job: two concurrent processes, 384 MiB per process
/ 512 MiB aggregate, 10 s CPU per process / 20 s aggregate, 75 s wall. Conversion
gets a 60 s budget without an unsandboxed fallback. A 100 ms monitor rejects
links, over 2,048 entries and over 128 MiB staging;
this is monitored cancellation, **not a hard filesystem quota**. PNG encoding uses lossless RGB row filtering; it never changes dimensions, colors
or pixel values to fit the cap. Existing PNG, pixel and worker-output caps remain. Job close kills children; per-job profiles,
source and intermediate output are deleted on success/failure. Normal text/PDF
workers retain their single-process restriction.

Failures use `PPTX_RENDERER_UNAVAILABLE`, `SLIDE_RENDER_RESOURCE_LIMIT` or a
specific `PPTX_*` conversion or `RENDER_*` PDF failure and stage. Cached text survives render failure. Pixels
use existing authenticated MCP image blocks/private widget metadata, not a public
image URL. Versions/permissions are checked again after conversion. Receipts are
owner/connection/file/version scoped and expire; PPTX receipts cannot authorize
the PDF schedule route. `assistant_pixel_visibility=not_confirmed_by_server`
means the model must actually receive and inspect pixels before interpreting.

PDF derivatives have a separate 10 MB cap, ten-minute process-memory retention
and four-object / 40 MB aggregate cache. Every hit rechecks current access and
source version; selection withdrawal, disconnect, deletion and expiry invalidate
entries. Source/PDF hashes remain separate. See the [pipeline diagnosis and
operator steps](pptx-visual-pipeline.md) and [follow-up validation](../evidence/sanitized-results/pptx-visual-pipeline-2026-10-22.md).

Native synthetic hidden/image-heavy slides and one actual requested slide now
convert under the unchanged limits. Codex inspected the actual pixels locally;
the initial [October 23 evidence](../evidence/sanitized-results/pptx-single-slide-2026-10-23.md)
was local-only. The subsequent [bounded EMF acceptance](../evidence/sanitized-results/bounded-emf-2026-10-23.md)
records connected native-image visibility for a full 54-slide source in Codex and
a separate control. Other clients require their own acceptance checks.
Missing-font, broader fidelity and cross-platform acceptance remain outstanding.

Primary references: [LibreOffice export](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html),
[restart codes](https://github.com/LibreOffice/core/blob/master/include/desktop/exithelper.h),
[Windows memory accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).
