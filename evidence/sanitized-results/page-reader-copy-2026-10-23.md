# Page-reader copy: live verification — October 23, 2026

The running Canvas Bridge Personal widget displays the requested copy:

- Primary PDF button: **Send Page to ChatGPT**
- Explanation: **Send this page directly to ChatGPT for visual analysis. No manual download or upload required.**

The source copy and bundled asset were already included in the service's latest
authorized restart at 20:57:41 America/New_York. This verification required no
additional restart, production-code change, configuration change, or permission
change. The copy patch itself changes only displayed text and references to the
button label; rendering, authorization and transport changes from separate work
are not attributed to this patch.

## Actual ChatGPT web check

A fresh native reader was requested for page 2 of an authorized course PDF,
distinct from page 1 used in the earlier baseline. Both requested strings were
observed in the live widget. Clicking **Send Page to ChatGPT** showed the existing
access/page-version check, then **Page image sent to ChatGPT for visual reading.**
The resulting ChatGPT response identified page 2 and described two visible layout
features from its pixels. The new page's image was therefore supplied to the
conversation through the renamed button; this was not a synthetic-host test.

Before/after installed-connector status checks confirmed the same active
connection, four selected courses and disabled MCP saved-state writes. No Canvas
or Calendar writes, credential updates, scope changes or configuration changes
were performed by this verification.

The existing ChatGPT development session displayed **CSP off** and its sandbox
URL included an origin-check override. These pre-existing settings were left
untouched. This is functional evidence for that client configuration, not
acceptance of normal CSP/origin enforcement or all ChatGPT clients.

## Other verification

- In-memory build with the pinned dependencies exactly matched the shipped
  page-reader asset; no rebuild mutation was necessary.
- Previous copy-update tests: 39 passed; 2 optional OCR checks skipped because
  the operator runtime was unavailable.
- Previous synthetic browser checks covered exact authorized PNG handoff,
  denied-access blocking, and unclipped mobile layout at 280, 320, 375 and 390 px.
- No redundant full suite was rerun in this deployment-verification turn.

Private screenshots, the actual conversation reference and detailed live status
are retained in ignored `.local/page-reader-copy-check/`. No source-page images
or academic contents are included in this tracked evidence record.
