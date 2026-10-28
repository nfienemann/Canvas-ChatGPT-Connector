# Bounded EMF support and private acceptance — October 23, 2026

## Implementation

Metafile decoding and validation run only inside the existing credential-free,
network-denied AppContainer. The native converter remains in the same non-breakaway
Job. Authorization, version fencing, process counts, memory/CPU/wall limits,
staging cancellation, PDF/PNG caps and no-write restrictions are unchanged.

A narrow EMF+ full-frame bitmap sequence is decoded from premultiplied BGRA to
PNG. An optional bounded MULTIFORMATS PDF alternative is discarded without parsing
or passing it to a native decoder. The original source stays immutable. A known
producer variation in the record count and palette-free EOF is accepted only
for this normalized representation. Crops, transforms, continued objects, other
pixel formats, opaque comments and extra drawing records are rejected.

Classic EMF retains a validated static record allowlist. Unknown commands,
escapes, OpenGL, profiles, nested media and source bitmap blits fail closed.
Limits include 8 MiB/member, 20,000 records, 4,096 handles, 32 saved states,
16 million pixels, bounded coordinates and 32 MiB normalized media total.
Every source media part is preflighted, including unrequested slides. Raster
extension spoofing cannot bypass the metafile policy.

Single-slide packaging rewrites only validated internal media relationships and
PNG content types. Original presentation order, source locators and hidden-slide
handling are preserved. Converter identity advances to v6-bounded-emf and the
isolated-runtime digest includes the new validator.

## Additional lossless PNG repair

The connected whole-deck run reached a separate existing PNG output limit on a
later image-heavy slide, after successful PPTX conversion. The rasterizer now
uses lossless adaptive RGB row filters instead of unfiltered scanlines. It keeps
every RGB pixel, row geometry, requested resolution and the 1,300,000-byte cap.
No quantization, thresholding, grayscale conversion or rescaling is introduced.
Synthetic tests compare every decoded pixel (including padded input rows), check
compression of a color field and retain rejection above the original cap. The
renderer identity and runtime digest advance; PDF derivatives are unaffected.

## Checks and acceptance

**Private whole-deck acceptance passed in this Codex environment.** This does
not establish general EMF support, universal clients, animations, or independent
pixel-for-pixel PowerPoint fidelity.

- The exact authorized fixture's source version, original-byte hash and length
  were checked independently; its actual presentation order is 54 slides with
  none hidden. Source version and tool-returned content hash were checked
  throughout. Identifiers were not substituted for one another.
- Seven connected text batches used the returned continuation arguments and
  expected hash. Complete text records: 54; truncated/partial: 0; failed: 0.
  Twenty records contain only a printed number. The text tool correctly remains
  text-only/partial-data and does not establish visual review.
- All 54 original slides were rendered and the assistant directly inspected the
  native image blocks. No new Send Page click was required. Original Slide N
  locators were retained. The requested slide was also inspected at high
  resolution and through the alternate page-render entrypoint.
- The earlier control retained all five text slides and a directly visible native
  title-slide image, including after the final lossless-PNG restart.
- The requested-slide explanation uses displayed axes, equation, adjacent plate
  layout/raw readings and the following calculated sample table. It distinguishes
  displayed data from teaching interpretation; an unavailable fit-probability
  field stays unknown. Scientific details and course pixels are not copied here.
- One worker-execution failure and two busy-worker responses succeeded on retry.
  A separate image-output-limit failure was repaired by the lossless encoder.
  No failed request was counted as a blank or completed visual review.
- Completed conversions observed up to 298,377,216 committed bytes per process
  and 347,123,712 per Job, below unchanged 384/512 MiB limits. The previously
  oversized slide now uses 1,050,710 PNG bytes at 1600 x 900, below 1,300,000.
- The private service was restarted with process/parent and resource-identity
  checks, then restarted once more for the PNG change. Before/after fingerprints
  confirmed unchanged credentials, authorization epoch/state, course selections
  and saved settings. Connected status retained the same four-course scope,
  disabled writes and unchanged budgets. Successful item reads/renders separately
  established current file access; status alone was not used as proof.
- All images used the bounded-EMF converter. Slides 1-47 were first inspected
  with the prior unfiltered PNG encoding; slides 48-54 used lossless row filtering.
  The requested slide, title slide, alternate entrypoint and control were then
  rechecked on the final encoder. The pixel-preserving encoder change did not
  alter source bytes, PDF conversion, dimensions or colors.
- Server aggregates establish authorization, source retrieval and rasterization
  where evidenced. Host visibility and interpretation remain unknown on the
  server; the observation above is explicitly client-side evidence. The reader
  fallback remains available for other environments.

Private originals, text, images, source IDs/hashes, request correlation and
receipt-free connected coverage records remain in private operator storage.
No Canvas/Calendar records, permissions, selections or source files were changed.
No real academic fixture, private configuration or credential was added to Git.

Validation:
- Initial EMF full suite: 911 passed, 27 skipped.
- Focused EMF/parser/converter suite with explicit native runtime: 92 passed.
- PNG exact-pixel/cap and updated OCR-validator tests: 9 passed. An intermediate
  focused run exposed six obsolete renderer-ID fixture failures; the fixture now
  uses the current renderer constant and its negative checks remain intact.
- Final current-checkout full suite: 959 passed, 27 skipped in 283.62 seconds.
  Skips cover unavailable Linux/PostgreSQL/OCR environments and opt-in native
  tests; the focused native run above executed with its explicit runtime.
- Targeted lint/format and whitespace checks passed.

Format references: Microsoft [EMF header](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/e4a35c41-e8e3-43f9-bc07-a18e99bb866d),
[MULTIFORMATS](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/4bc4608e-ca82-426d-ac0e-5ded2ad3fc4e),
[EMF+ DrawImage](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emfplus/778bfc49-e058-4fb2-b19d-9f801f8e458a).
