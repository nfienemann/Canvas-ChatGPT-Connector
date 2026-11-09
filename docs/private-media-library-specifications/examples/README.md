# Fictional contract examples

`fictional-note.txt` contains only invented content. The example item, browser intake and receipt use its actual byte count and SHA-256. Their IDs are inert placeholders, not credentials, accounts or implemented resources.

`submit-library-files.input.json` is a separate host-handoff input-shape example. Before such a request, an authenticated user action must create an intake bound to `example-host-file-01`, the selected retention/grants and server-approved byte ceiling. Its `.invalid` URL is intentionally nonfunctional and must never be fetched. This file does not demonstrate successful host transfer.

The library-item example describes technical original-download support but grants the current host only metadata and text. The host cannot download originals from that capability flag; the owner-session route has a separate permission evaluation. No example grants institutional acquisition or assessment assistance.

Validate these files with `python validate_package.py` from the package root in an environment with `jsonschema`. Validation checks shapes and fictional byte identity, not application security or real-host acceptance.
