# PPTX slide structure and picture reading

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

This is **original-picture extraction**, not a complete PowerPoint renderer.
Cropping, masks, rotation, overlays, group geometry, layout/master/background
images, SmartArt, charts, animations, equations, embedded media and inherited
labels are not composed. The original picture can contain areas hidden by slide
cropping. Transparency is shown on white; downsampling can obscure tiny labels.
Unsupported vectors (SVG/EMF/WMF), linked images and animated pictures are not
decoded or fetched. No OCR is performed on slide pictures, so picture-only text
does not enter search. Unread visual content keeps coverage partial, even when
speaker notes are readable. No claims of complete image-heavy lecture digestion
are justified until the relevant images and context have actually been reviewed.

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

This increment does not change or restart the personal service or repair its
authentication. Live Rowan and actual native ChatGPT PPTX review remain unverified
until that service is updated and its separately managed connection works.
