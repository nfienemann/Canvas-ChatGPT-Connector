# Installed PPTX plugin activation — October 23, 2026 (local)

The user authorized activation/restart and confirmed refreshing the connector in
their signed-in ChatGPT settings. The private elevated server was restarted with
listener, parent-PID and OAuth resource identity checks through the standard
Windows administrator prompt. Database and tunnel remained running.

The first actual plugin request returned `DOCUMENT_RUNTIME_SETUP_FAILED` before
native conversion. A source-free diagnostic identified recursive public-runtime
ACL provisioning exceeding its existing 15-second timeout. The server now reuses
the previously validated private parser/runtime location instead of provisioning
a second LibreOffice copy. No timeout or ACL rule was relaxed. First-use runtime
provisioning under a new location remains a limitation requiring operator setup.

Three private settings changed: renderer enablement, trusted LibreOffice path,
and parser staging/runtime path. All other settings are unchanged. A private
configuration backup remains outside Git. No production code changed this turn.

## Installed-tool acceptance

The `render_course_file_page` PPTX compatibility route returned `status=ok`, one
native MCP image block, source/version hashes, a distinct derivative hash and the
original Slide 14 citation. Codex actually inspected the returned tool image in
this conversation; no direct-function call or previously saved image substituted
for the live plugin result. The visible footer correctly reads 14.

| Measurement | Observed |
|---|---:|
| Original source / slide count | 14,176,811 bytes / 25 |
| Original slide -> PDF page | 14 -> 1 |
| Image references / retained members | 6 / 44 |
| Internal PPTX / PDF | 772,703 / 543,150 bytes |
| Conversion stage / rasterization | 12,041 / 1,147 ms |
| Peak process / Job commitment | 283,381,760 / 326,344,704 bytes |
| PNG | 2,400 x 1,350; 1,060,524 bytes |
| Credential/epoch/state/course-selection fingerprint | Unchanged |
| Advertised source and rendering budgets | Unchanged |
| MCP saved-state writes | Disabled |

The server correctly does not claim model visibility or interpretation from its
own render receipt. The receiving model observed report screenshots and gave a
grounded explanation with original-slide provenance. Upper-right overlap remains;
six references do not prove six separate fully readable panels. Only one real
slide was reviewed, not the entire presentation.

Installed connector/backend and native delivery to this Codex conversation pass.
A separate ordinary ChatGPT web conversation and reader-button interaction were
not exercised in this activation run. The subsequent
[web-reader acceptance](pptx-web-reader-2026-10-23.md) passes that functional path
in its documented private client context; do not generalize to every surface or
normal client CSP enforcement. Connector refresh is user-confirmed. Broader slide
and cross-platform release gates remain.

No full suite repeated because this turn changed configuration/deployment only;
the preceding targeted/native tests remain applicable. Private proof metadata is
outside Git. No tokens, identifiers, source images or slide text are in this record.
