# Page and slide reader copy — October 23, 2026

The shared native document reader now uses format-appropriate copy:

- PDF: **Send Page to ChatGPT** and **Send this page directly to ChatGPT for visual analysis. No manual download or upload required.**
- PPTX: **Send Slide to ChatGPT** and **Send this slide directly to ChatGPT for visual analysis. No manual download or upload required.**

Access-check, progress, success, failure and retention text uses the same page or
slide terminology. Loading text calls the shared view a document reader. The
tool descriptions and widget description reference the matching button labels.
The original-file download card still describes its actual download action.
Other image-reader entry points share this view.

## Scope and local checks

The implementation changes only displayed copy and its format selection. The
resource URI, CSS, event handler, tool arguments, authorization refresh, source
and image hash checks, image bytes, file naming, source provenance, host
capability negotiation, upload/context/message calls and interpretation prompt
are preserved. No PDF rendering, conversion, authorization or transport behavior
was changed by this patch.

- `npm run build`: rebuilt the checked-in browser bundle with pinned dependencies.
- `pytest tests/test_visual_ui.py -q`: **18 passed**. Includes both page and slide
  copy, exact PNG bytes through both existing transport paths, original Slide 14
  provenance and denied-access blocking. The Windows Node test harness explicitly
  uses UTF-8 so the status ellipsis is asserted correctly.
- Ruff check and format check passed for the changed UI Python and test files.
- Source comparison against the pre-change snapshot confirmed that reader code
  outside displayed-copy assignments and copy helpers is unchanged. The app AST
  excluding docstrings is unchanged.
- The actual bundled widget ran in a synthetic browser host. Both buttons
  delivered the exact refreshed PNG, source receipt and follow-up message.
- Browser measurements at **280, 320, 375 and 390 px** showed no button clipping
  for either format. No styling changes were needed.
- The unchanged renderer suite was not rerun for this copy-only update.

## Live verification

The pre-deployment ChatGPT widget still showed the previous slide label. After
the concurrent parser chat completed its regression checks, the private API was
restarted at 21:11:49 America/New_York using the existing configuration and
normal Windows elevation. The database and tunnel were not restarted. All 72
deployed source fingerprints matched the checkout after startup. Independently
completed parser changes in the shared checkout are not attributed to this copy
patch; this record does not claim acceptance of those changes.

Before/after checks confirmed unchanged private configuration fingerprints,
active connection, four selected courses, scope snapshot and disabled MCP
saved-state writes. No credential or permission changes were made.

The first fresh-slide test at high resolution stopped at the existing
`RENDER_IMAGE_OUTPUT_LIMIT` after authorization, retrieval and conversion. No
image was delivered for that attempt, and no limit was changed. The test then
succeeded at the existing standard resolution. ChatGPT initially reused the
previous cached widget, so its supported **Refresh tools** control was used to
reload the deployed app metadata without changing permissions or credentials.
The same resource URI was retained. Existing historical widget instances retain
their cached copy; a fresh native reader displayed the updated copy after refresh.
The [official UI guidance](https://developers.openai.com/plugins/build/chatgpt-ui#embed-the-component-in-the-server-response)
describes resource-URI caching; no URI or image-delivery behavior was changed.

The fresh reader displayed original Slide 15, **Send Slide to ChatGPT**, the exact
slide explanation above and the matching retention note. Clicking it displayed
**Checking current Canvas access and slide version…**, then **Slide image sent
to ChatGPT for visual reading.** The ensuing ChatGPT response cited original
Slide 15 and correctly identified two concrete visual features of the displayed
image. The screenshot and response agreed. This was a different slide from the
prior live acceptance fixture, and no content summary for it had been supplied
before the click. The actual conversation image handoff is **PASS** at standard
resolution (1600 × 900).

The host's pre-existing development session displayed **CSP off** and a
target-origin-check override. These were not changed. This establishes functional
handoff in that client configuration, not normal CSP/origin enforcement,
universal client compatibility or unrestricted rendering of every slide.

Synthetic fixtures, screenshots and the isolated copy diff are retained under
ignored `.local/all-reader-copy-check/`. No academic contents are stored here.
