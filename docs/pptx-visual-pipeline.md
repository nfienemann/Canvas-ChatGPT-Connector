# PPTX visual pipeline diagnosis — updated October 23, 2026

Current result: the single-slide path converted the actual acceptance slide once,
and Codex inspected its pixels. See the [single-slide validation record](../evidence/sanitized-results/pptx-single-slide-2026-10-23.md).
This is local authorized analysis evidence, not deployed ChatGPT plugin acceptance.

Subsequent authorized activation and installed-plugin pixel delivery succeeded in
the Codex client; see the [deployment follow-up](../evidence/sanitized-results/pptx-installed-plugin-2026-10-23.md).
Ordinary ChatGPT web reader-button testing remains a separate client gate.

Before this repair, the live v8 text extractor successfully reports 25 slides for
the authorized acceptance file. A live request for slide 14 returns
`PPTX_RENDERER_UNAVAILABLE` before downloading or converting it. The connection
advertises `pptx_visual_rendering=disabled`. These observations supersede the
earlier record of the old live 10 MB extraction limit.

| Stage before repair | Implementation / execution | Boundary and next reference |
|---|---|---|
| Authorized fetch | Existing, used by extraction | Fresh course/file authorization, bounded 32 MiB source stream |
| Text extraction | Working live v8 | 25 ordered slide records, no visual claims |
| Conversion | Optional Windows AppContainer prototype; not attempted live | Disabled flag and absent configured runtime; prior synthetic timeout does not establish a live conversion defect |
| Derivative registration | Absent | Prototype converts only one page, immediately discards PDF; no reusable derivative identity or mapping |
| PDF rasterization | Existing PDFium worker | PDF bytes to bounded PNG; prototype calls it after conversion |
| Tool exposure | Generic page renderer has optional PPTX branch | No named slide route; extractor returns null visual fallback |
| Native reader | Existing authenticated MCP image block and private widget metadata | Refreshes authorization before sending image to model context |
| Model-visible pixels | Not reached for this PPTX | Server success cannot establish visibility |
| Interpretation | Not attempted | No scientific description of slide 14 established |

The demonstrated integration failure is the unavailable conversion route plus
missing derivative lifecycle and discoverability. Native conversion remains an
independent validation gate, not an assumed cause. Source PPTX and derivative PDF
hashes must be separate. No real course content belongs in repository fixtures.

## Implemented integration

`render_course_slide(connection_id, file_id, slide=1,
expected_source_hash=None, resolution="standard")` is read-only and uses the
same authenticated image response and native reader as PDF pages. The old
`render_course_file_page` remains a compatibility alias for PPTX. Text extraction
now names the slide tool as its visual fallback, including when the backend is
disabled (the tool then returns an explicit availability result).

The entire original source still passes the existing bounded ZIP/XML/media
preflight. Inside isolation, `presentation_subset` creates a temporary PPTX with
one selected slide and its dependency closure (layouts, masters, themes, media,
notes and chart parts). Original bytes are unchanged. Unselected slides, unused
masters, custom shows and sections are excluded. Cross-slide dependencies fail
closed as `PPTX_SLIDE_MAPPING_UNCERTAIN`. Dynamic slide-number fields become styled
static text with the original displayed number, since LibreOffice otherwise
renumbers them. Namespace prefixes used by compatibility attributes are retained.

LibreOfficeKit exports only page 1, including a hidden selected slide and excluding
notes pages, notes and bookmarks. PDFium requires exactly one valid page with
finite bounded geometry. The manifest maps that page explicitly to the requested
original slide; `page_count` remains the original slide count for reader navigation.
Source/PDF hashes, source count, selection, hidden flag, subset bytes/members,
image references and converter/build identity stay separate. This verifies mapping,
not complete visual fidelity. Source and subset still have the same size ceilings.

Validated PDFs remain in private process memory for ten minutes: at most four
objects / 40,000,000 bytes total, each PDF at most 10,000,000 bytes. Cache keys bind
owner, connection, source file, authorization epoch, current source version and
converter configuration and slide selection. Expected source hashes are checked
against the validated manifest on hits as well as misses. Different slides can
coexist within the same four-entry limit. Every hit repeats fresh authorization and upstream
metadata checks, then checks version/epoch again after rendering. Revocation or
source-change failures invalidate matching entries. Selection withdrawal,
disconnect, account deletion, expiry and process shutdown clear applicable entries.
No binary cache enters the database or backup; no PDF is uploaded to Canvas or
served via public URL. Each worker's private source/profile/output is deleted.

PDFium rendering is reused unchanged except for a bounded edge selection:
standard 1,600 px, high 2,400 px; output still must fit the existing 1.3 MB PNG
and MCP image contracts. The native reader's v4 resource refreshes the original
slide with its source hash before handing the image to the model. It supports
capability-negotiated MCP Apps image context or ChatGPT's optional upload/imageIds
helpers. Missing helpers give an explicit limitation. Neither a server response
nor a UI preview sets `visually_inspected`. Interpretation stays with ChatGPT.

Structured `pipeline_events` distinguish authorization, source fetch, conversion,
registration, rasterization, response preparation, image delivery, model visibility
and interpretation. Results are `not_attempted`, `completed`, `failed` or
`unavailable`, with milliseconds, numeric byte/memory/pixel measurements and
sanitized reason codes. The last three client/model stages stay unconfirmed on
the server. Native stderr, document text, paths, tokens and signed URLs are not
logged. Conversion timeouts are retryable, not successful partial renders.

## Actual additional blockers found

An authorized in-process test downloaded the exact 14,176,811-byte acceptance
file, then failed preflight because it contains SVG media. Static, self-contained
SVG validation now permits paths, text, shapes, gradients and internal references;
it rejects scripts, foreign objects, event handlers, external URLs, CSS imports
and XML entities. The real deck passes this validation and reaches conversion.

The Windows startup investigation identified runtime parent enumeration and VCL
thread dispatch requirements. A nested public runtime permits enumeration without
exposing its private cache parent. LibreOfficeKit bypasses desktop instance IPC;
document operations execute on its own process's VCL thread. Synthetic conversion
now succeeds in AppContainer. Whole-deck native conversion still failed near the
existing process-memory cap; the exact native failure was not proven to be OOM.

The selected-slide approach succeeded on the real source: 773,842-byte internal
PPTX, 542,809-byte PDF, 2,400 x 1,350 PNG, 13.064 s conversion-stage duration,
280,686,592-byte peak process commitment and 323,297,280-byte peak Job commitment.
All original CPU, memory, network, process, staging and timeout limits remain.
No further real conversion was performed. The first image exposed footer
renumbering; a subsequent synthetic native test verifies the field-freezing fix.

## Operator and release steps

Keep `BRIDGE_PPTX_RENDERING_ENABLED=false` until the opt-in native test passes.
Supply only a trusted public LibreOffice runtime with program/share/presets via
`BRIDGE_PPTX_RENDERER_ROOT`; never point at a personal profile. Current isolation
is Windows-only; Linux/macOS conversion returns unavailable. A portable verified
backend remains required before general release. No unsandboxed real-document
fallback is permitted.

Run `tests/test_presentation_rendering.py::test_native_single_slide_hidden_mapping_and_pdf_pixels`
with `BRIDGE_TEST_OFFICE_ROOT` and optional `BRIDGE_TEST_PARSER_ROOT` in a local test
process. Its normal omission is an explicit skip, never native acceptance.

After native conversion and isolation pass, restart the existing private server
with the reviewed configuration. No database migration is needed. Refresh the
installed connector catalog to discover `render_course_slide`; request a fresh
reader (v4 resource URI) so an old cached widget is not reused. Then test the real
slides 3, 12, 14, 22 and 25 and address every slide. Pass the release gate only
after ChatGPT actually receives pixels, explains the visible content and cites
the original slide. The subsequent private
[ChatGPT web-reader acceptance](../evidence/sanitized-results/pptx-web-reader-2026-10-23.md)
verifies the button-assisted path for original Slide 14. The host already had
development CSP/origin-check bypass enabled; no client security setting was
changed. Normal client enforcement, other real slides and portable backend
acceptance remain pending. The earlier local Codex observation alone did not
establish this web-reader result.

Native host contract: [OpenAI plugin UI](https://developers.openai.com/plugins/build/chatgpt-ui).
Conversion contract: [LibreOffice PDF export parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html).
