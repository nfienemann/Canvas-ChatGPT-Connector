# PPTX ChatGPT web reader acceptance — October 23, 2026

## Result

PASS for the private, button-assisted ChatGPT web reader on the original
image-heavy Slide 14 of the 25-slide acceptance presentation. This closes the
previously pending functional web-reader gate for this fixture and client context.
It does not establish whole-deck coverage or general-release security readiness.

An authenticated `chatgpt.com` conversation was opened in the desktop app's in-app
browser. The installed Canvas Bridge Personal plugin opened its native slide
reader at high resolution (2,400 x 1,350), identifying original Slide 14 of 25.
The initial request supplied locators only, with no scientific description, and
explicitly deferred interpretation until the image handoff.

The tester clicked **Read slide in ChatGPT**. The reader first displayed
**Checking current Canvas access and page version…**, then **Page image sent to
ChatGPT for visual reading.** ChatGPT subsequently described image-specific
report text, multiple trait panels, a photograph and their overlap. The tester
compared those observations with the rendered image; a receipt or success flag
alone was not treated as visual evidence.

A final follow-up, without another tool call or rendering request, produced a
grounded teaching explanation that separated visible report statements from
interpretation, explicitly cited the original filename and Slide 14, and stated
that overlapping text could not be interpreted reliably. The citation uses the
source slide, not page 1 of the internal PDF. The six source image references
do not establish six separate, fully readable panels. Coverage remains 1 of 25.

## Security and scope

- No source, server configuration, permissions, client settings or resource
  limits were changed during this test; no server restart was needed.
- Before/after live connection-status snapshots matched for advertised file
  analysis budgets, connection state and scope snapshot. MCP saved-state writes
  remained disabled. No Canvas or Calendar mutation was requested.
- The web host already displayed **CSP off. Open developer settings**; its app
  sandbox URL also advertised the host's development origin-check bypass. Those
  settings were not changed. This proves the functional private development
  path, not enforcement under normal client CSP/origin checks. That security
  acceptance remains pending before public release.
- The button-assisted route is verified. Automatic inspection without the
  reader button, other client surfaces and other real slides remain unverified.
- No new converter experiments, code changes or repeated automated suites were
  needed. The preceding targeted tests remain recorded separately.

## Evidence handling

The actual web conversation, screenshot of the cited explanation and private
proof metadata are retained in the owner's private environment, outside Git.
This sanitized record contains no course identifiers, tokens, slide text,
academic images or conversation identifiers. See also the preceding
[installed-plugin proof](pptx-installed-plugin-2026-10-23.md).
