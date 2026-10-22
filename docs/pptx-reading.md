# PPTX structure, pictures and complete slide rendering

`read_course_presentation(connection_id, file_id)` returns an overview with actual
slide order, titles where declared, hidden-slide flags, notes status and counts of
tables and pictures. Choose `slide` to retrieve records: text objects, grouped
objects, tables, pictures and separate speaker-note paragraphs. Continue with
the returned offset and content hash. Existing `read_course_file` and file search
also index slide text, table cells and speaker notes with their locator labels.

Objects retain source IDs, names, stored EMU transforms, parent group membership,
paragraph levels and bullet types. Object order is stored z-order, not a promise
of visual reading order. Tables retain row/column coordinates, row heights,
column widths, spans and horizontal/vertical merge flags, including empty cells.
No headings, units or values are inferred from adjacent cells. Each returned
object/note has a Canvas URL, slide/object locator, source version/content hash and
retrieval timestamp. Table cells additionally identify their exact `R2C3` locator.
Notes exclude slide-number, date, footer/header and slide-image placeholders.
Absent notes and a present but empty notes part are distinct. Malformed or
inaccessible notes fail extraction explicitly, rather than becoming "no notes".

## Image-heavy lectures

1. Discover the authorized course/deck with the existing course-file tools.
2. Read its overview and relevant slide records, including notes and tables.
3. For a picture, call `read_course_slide_image` with its slide, `object_index`
   and expected content hash. This decodes one embedded PNG, JPEG or static WebP
   into a bounded PNG image with a slide/object citation.
4. If the native ChatGPT surface exposes only image metadata to the model, the
   existing native image reader offers **Read image in ChatGPT**. Clicking it
   checks access/version again and adds the pixels to this conversation. No
   student download/re-upload is needed. ChatGPT file retention applies.
5. ChatGPT can review the pixels alongside slide text, notes and authorized course
   context. It must distinguish visual observations, author text, and its own
   interpretation. Course context cannot establish what an unseen picture shows.

`read_course_slide_image` is **original-picture extraction**, not a complete PowerPoint renderer.
Cropping, masks, rotation, overlays, group geometry, layout/master/background
images, SmartArt, charts, animations, equations, embedded media and inherited
labels are not composed. The original picture can contain areas hidden by slide
cropping. Transparency is shown on white; downsampling can obscure tiny labels.
Unsupported vectors (SVG/EMF/WMF), linked images and animated pictures are not
decoded or fetched. No OCR is performed on slide pictures, so picture-only text
does not enter search. Unread visual content keeps coverage partial, even when
speaker notes are readable. No claims of complete image-heavy lecture digestion
are justified until the relevant images and context have actually been reviewed.

## Complete static slides

`render_course_slide(connection_id, file_id, slide, expected_hash=None)` composes
one complete slide through an optional isolated LibreOffice installation, exports
that slide to a temporary PDF, then uses the existing isolated PDF renderer to
return bounded PNG pixels. Its native reader offers **Read slide in ChatGPT**.
Download, access, version checks and image delivery reuse the existing paths.
The citation identifies the original Canvas presentation, source hash/version
and actual slide number; the intermediate PDF hash is separate. Hidden slides
retain their original numbering and are identified as hidden presentation slides.

Read notes and tables with `read_course_presentation` alongside these pixels.
The complete image preserves layout, backgrounds, picture crops and overlay
labels where LibreOffice supports them. Fonts, SmartArt, charts and effects may
differ from PowerPoint. Animation/video playback and external resources are not
supported. This tool does not add slide OCR or visual search indexing; image
interpretation happens in ChatGPT, with explicit uncertainty for unreadable content.
It never represents structure-only fallback as a successfully rendered slide.

The first verified complete-slide platform is Windows. Set the operator-only
`BRIDGE_SLIDE_RENDERER_ROOT` to a trusted LibreOffice installation containing
`program/mergedlo.dll` and exactly one bundled `python-core-*/bin/python.exe`.
Other platforms or an unset root return an explicit unsupported result; existing
text, notes, tables and original-picture support remain available.

For deployment, use an official checksum-verified LibreOffice distribution in a
dedicated **runtime-only parent directory**, with the installation in its child
directory. Give Windows AppContainers read/execute access to that dedicated
parent and its runtime files, never to a workspace, credentials or student data.
LibreOffice inspects its installation directory via its parent; granting access
only to the installation itself can produce a misleading profile-creation error.
The verified synthetic runtime was LibreOffice 26.8.1.1 on Windows x64. This is
operator provisioning, not student setup; no runtime is silently downloaded.

The worker initializes LibreOfficeKit, then loads the presentation directly with
the published UNO `XLoadable` document interface. It avoids the failing desktop/
IPC startup path. Macros and external updates are disabled; interaction requests
are aborted. Before conversion, the existing isolated OOXML worker rejects active
content, external resource relationships and document actions. Hyperlinks remain
inert. No additional Canvas or OAuth privileges are needed.

Conversion uses a separate one-process AppContainer profile: no capabilities,
network or inherited handles; 768 MiB memory, 30 CPU seconds, 45 wall seconds and
a checked 50 MB temporary-storage budget. This does not increase ordinary parser
limits. A private random OS-temp job keeps LibreOffice's profile paths short;
deep workspace paths can crash Windows Office components. The PPTX, PDF and
profile are deleted after the worker exits, including failure and timeout paths.
Cancellation does not abandon the bounded worker's cleanup. There is no persistent
render cache, public file URL, raw-PDF tool attachment or external conversion service.
The 10 MB source/output-PDF limits and existing bounded PNG output still apply.

API references: [UNO XLoadable](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1frame_1_1XLoadable.html),
[macro execution modes](https://api.libreoffice.org/docs/idl/ref/namespacecom_1_1sun_1_1star_1_1document_1_1MacroExecMode.html),
[PDF export options](https://help.libreoffice.org/latest/en-US/text/shared/01/ref_pdf_export_general.html).

## Isolation and bounds

PPTX extends the existing hardened OOXML package reader and Windows/Linux worker;
it adds no dependency, OAuth scope, Canvas write or new authorization policy.
The existing account/course/file checks, download restrictions, cache expiry and
deletion behavior are reused. Text/structure is cached in the same owner-scoped
record; pictures are transient and worker files are deleted after each request.
Parser v7 invalidates older flattened slide caches. No binary public endpoint or
external image URL is introduced.

Existing bounds remain: 10 MB input/member, 1,000 ZIP members, 20 MB expanded and
200:1 member compression ratio; 200 slides, sandbox CPU/memory/wall limits and
2 MB worker output. Structure additionally allows 200 objects per slide, group
depth 16, 400 cells per table, 200 note paragraphs per slide, 16,000 characters
per paragraph, 32,000 JSON characters per object, 240,000 index characters and
900,000 structured-page JSON characters and 50,000 overview JSON characters per
deck. Note paragraphs also have a 32,000 JSON-character bound. Exceeding an extraction budget
fails explicitly; it does not label omitted content blank. Read responses return
at most 30 records (default 10) and 60,000 record JSON characters. Continuation
uses the actual returned count and reuses extraction. Pictures are bounded to
12 million input pixels, 2,400 pixels per output dimension and 1.3 MB PNG;
oversized output is downsampled. Private source bytes and exception text are not
logged or returned. Raster decoding uses a restricted format list and fresh
pixel-only output, stripping source metadata.

The structure reader follows [PresentationML notes relationships](https://learn.microsoft.com/en-us/office/open-xml/presentation/working-with-notes-slides).
Raster validation follows [Pillow's image-opening and decompression limits](https://pillow.readthedocs.io/en/stable/reference/Image.html).
It does not execute document actions, scripts, hyperlinks or embedded objects.
All extracted text, notes and alternate descriptions remain untrusted source data.

## Verification boundary

Synthetic tests cover out-of-order slide filenames, hidden slides, group
membership, notes, merged tables, picture-only slides, chart limitations,
malformed/missing/external relationships, bounds, actual isolated image decoding,
cache reuse, version changes, cross-user denial, source citations and the real
HTTP MCP envelope. Native-reader tests cover both PDF and PPTX image delivery,
fresh-access failures, stale hashes, unavailable pixels and both host transports.
The restricted Linux container proof also exercises PPTX notes/tables/pictures.

Complete-slide verification on Windows used the synthetic two-slide fixture in
`tests/fixtures/full-slide.pptx`. Both output images were inspected: the first
retained background, cropped drawing, overlay labels, sidebar and footer; the
second retained its hidden-slide identity and purple background. Actual isolated
conversion, source/hash attribution, cleanup, synthetic HTTP MCP image delivery,
private-file/network/child-process/runtime-write denial and timeout termination
passed. Native-reader tests cover complete-slide delivery and stale/access failures.
Run the optional real-renderer tests with `BRIDGE_TEST_SLIDE_RENDERER_ROOT` set;
CI without that Windows runtime skips them explicitly rather than claiming proof.

This increment does not change or restart the personal service or repair its
authentication. Live Rowan and actual native ChatGPT PPTX review remain unverified
until that service is updated and its separately managed connection works.
