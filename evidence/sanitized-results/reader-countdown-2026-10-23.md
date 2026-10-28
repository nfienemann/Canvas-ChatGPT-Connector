# Cancelable reader countdown — October 23, 2026

The shared PDF/PPTX reader offers a visible 30-second countdown on **Send Page
to ChatGPT** / **Send Slide to ChatGPT**, plus **Cancel automatic send**. The user
may send immediately, cancel to clarify in chat, or let the countdown finish.

## Behavior and boundaries

- Starts only after an image preview has loaded and the host supports the
  existing image handoff and private widget-state persistence.
- Counts only while the document is visible, at least half the preview is in
  view, and both action controls are fully in view. Background/suspended time
  cannot exhaust the countdown unseen.
- Cancellation survives widget remounts. Manual sends and automatic attempts
  also mark the preview, preventing a second automatic send after rehydration.
- Cancellation remains available during the automatic authorization refresh.
  Once image delivery starts, the cancel control is removed; it is not an undo.
- Failed attempts do not retry automatically. Unsupported hosts keep the
  existing manual action.
- Timer completion calls the same send function as the primary button. The
  existing authorized refresh, source hash, PNG digest, image content, provenance
  and interpretation prompt remain. No rendering, backend permission or image
  transport protocol was changed. Private widget state preserves existing fields.

The UI resource is v5 to separate the new interactive behavior from cached v4
widgets. OpenAI documents [widget-state persistence and resource URI caching](https://developers.openai.com/plugins/build/chatgpt-ui).
No external browser origins or new permissions are added.

## Validation

- `pytest tests/test_reader_countdown.py tests/test_visual_ui.py -q`: **36 passed**.
  Fake-clock scenarios include both formats, both transports, cancellation before
  expiry and during refresh/digest, reload persistence, send-now, hidden/offscreen
  pauses, suspension, loading, permission denial, version change, message failure,
  new preview reset, duplicate globals and unsupported state helpers.
- `npm run build`, focused Ruff checks, formatting and `git diff --check` passed.
- Actual bundled code in a synthetic browser host sent the exact authorized PNG
  and original-slide provenance once after the real 30-second countdown.
- Browser cancellation prevented delivery and remained canceled after reload.
- Both buttons fit at 280, 320, 375 and 390 px; 16 control measurements passed.
- Full rendering suites were not repeated for this widget-only behavior change.

## Deployment and live acceptance

The existing service restart at 21:20:14 America/New_York occurred after the final
UI source and asset build, loading this widget alongside independent parser work.
No restart was initiated by this countdown task. The supported ChatGPT **Refresh
tools** action was used to refresh the new UI resource metadata. Live cancellation
passed: the PDF preview displayed a decreasing countdown, cancellation stopped it,
no follow-up appeared after more than 30 seconds, and the canceled state survived
a conversation reload. The timer also stayed paused with its controls out of view.

Live PPTX automatic-send acceptance passed: the primary label decreased from 30
seconds through 28 and 3 seconds, without a primary-button click. The reader then
reported a successful image send, and ChatGPT produced a follow-up identifying two
features visible in the rendered slide with its original-slide citation. A full
conversation reload preserved the completed state without restarting the timer.

The additional live PDF automatic-send check was blocked: its fresh-page render
and bounded retries returned `retry_later` / `DOCUMENT_WORKER_BUSY` while another
document was being extracted. It never reached the countdown for that new page.
The PDF cancellation/persistence check above and synthetic PDF automatic-send
checks passed; this record does not claim live PDF automatic-delivery acceptance.
Earlier PPTX attempts likewise returned download/worker-busy before succeeding.
No limits or permissions were changed to work around these responses. The selected
four-course scope and six private configuration file fingerprints remained
unchanged, and MCP saved-state writes remained disabled.

The ChatGPT development session already had CSP enforcement and target-origin
checks disabled before this task. They were not changed. Live results establish
functionality in that existing development session, not production CSP acceptance.

Private screenshots and detailed verification remain in ignored
`.local/reader-countdown-check/`. This record contains no academic content.
