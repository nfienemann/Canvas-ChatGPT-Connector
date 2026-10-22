# Original Canvas file delivery

`prepare_course_file_download` fetches an unchanged authorized original. It does
not run a parser, rewrite archives, normalize text, execute macros/formulas,
recalculate a workbook, or convert a file. `read_course_file` still extracts text.
Preparation is **not** evidence of a user download or conversation attachment.

**October 22 follow-up:** The owner subsequently reported a working browser
download after ngrok's **Visit Site** interstitial, and an unsupported in-chat
download message. Client/build and saved-byte equality remain unrecorded. The
[public-release download roadmap](../evidence/implementation-tickets.md#public-release-download-roadmap--october-22-2026)
tracks the remaining UX, host compatibility, security and hosting work. The
verification table below describes the earlier implementation test session.

## Inspection and compatibility baseline

- Entrypoint: `app.create_app`, official Python FastMCP, authenticated streamable
  HTTP at `/mcp`, `Result` schema version `1.0`, existing status vocabulary and
  Pydantic input validation. Tested installed/locked MCP SDK: **1.30.0**, protocol
  negotiated by the actual synthetic MCP client: **2025-11-25**. No protocol or
  authentication migration was made. `uv.lock` pins Python dependencies.
- Existing native reader: `visual_ui.py`, bundled `ui/page-reader/reader.js`,
  **@modelcontextprotocol/ext-apps 2.0.3**, esbuild **0.28.2**. Both UI assets use
  the same pinned SDK and combined dependency notices. No CDN runtime dependency.
- `request_identity`, `authorization.py`, `course_files.authorized` and
  `checked_row` resolve the trusted principal, exact owned opaque file/course,
  selected scope, connection epoch and resource capability. Authorization is
  fenced again before each MCP response and HTTP transfer.
- Current metadata comes from the course-qualified Canvas File endpoint. A
  partial collection does not prevent an individually authorized file read.
  The existing conservative `file_visible` policy is preserved, including its
  explicit current-user flags; this change does not newly enable hidden files.
- `file_download._download_once` is shared by reader and original acquisition.
  It resolves approved metadata URLs, strips ambient cookies/authentication,
  sends Canvas credentials only on the initial approved Canvas-origin hop, and
  uses `network.PublicTransport` to resolve/check public IPs once and connect to
  that numeric address with the original TLS hostname. All redirects are checked.
  The existing three-redirect ceiling and institution origin rules are retained.
- The existing reader retains extracted text, not reusable original files.
  `parser_worker.extract` hashes the **raw input bytes** for `content_hash`.
  That meaning is unchanged; `bytes_sha256` is the explicit original-byte digest.
  `file_version` separately hashes stable authorized metadata, excluding rotating
  signed URLs and retrieval times. An upstream ETag is not a file checksum.
- No documented native conversation-output attachment adapter was established.
  Optional host `downloadFile` support must be checked after the UI handshake.

## Public and private contracts

Model-facing tool:

```json
{
  "name": "prepare_course_file_download",
  "arguments": {
    "connection_id": "existing opaque connection ID",
    "file_id": "existing opaque file ID",
    "expected_source_version": "optional lowercase 64-character SHA-256 version",
    "expected_bytes_sha256": "optional lowercase 64-character raw byte SHA-256"
  }
}
```

Only the first two inputs are required. Resolve the file through the ordinary
file inventory/outline. No raw URL, numeric Canvas ID, principal, token, callback,
local path, output path or host file ID is accepted.

The `ok` result says **Original file prepared**, with safe filename, original name
when changed, MIME/type origin, course/file IDs, actual byte count, raw hash,
source version, source page, source check time, source-binding evidence, expiry,
delivery ID and available transport names. Its state is `acquisition_state=staged`,
`delivery_state=prepared`, `host_handoff=not_attempted`. The source-binding method
is metadata checked before/after transfer; it explicitly does not claim an
immutable upstream snapshot. Guard mismatch or a mid-transfer version change
discards the object; the initial implementation does not silently restart.

App-visible supporting tool:

```json
{
  "name": "get_course_file_download_payload",
  "arguments": {"connection_id": "owned connection", "delivery_id": "issued ID"}
}
```

Its UI visibility is `app`. This visibility is discovery metadata, **not an
authorization boundary**: the same authenticated ownership checks apply if
called directly over MCP. Byte payloads and capability URLs are returned solely
in `CallToolResult._meta.canvas_bridge_download`, never in model text or
`structuredContent`. Serialized payloads are capped at 250,000 bytes. Repeated
payload requests rotate that object's capability, never its expiry.

`get_connection_status` reports configured limits, host support
`not_negotiated`, native attachment `not_implemented`, and local-server reliance.

## Delivery routes

1. **Authenticated machine access:**
   `GET|HEAD /course-file-original/{delivery_id}` with an MCP OAuth access token
   carrying `academic:read`. Issuer, audience, scope, expiry and owner are checked
   using the existing verifier. The ID alone does not grant access.
2. **Host download:** after `app.connect()`, check
   `app.getHostCapabilities()?.downloadFile`. The click obtains a fresh authorized
   payload. Up to 128 KiB uses an embedded MCP binary resource whose base64 is
   independently checked in the widget with WebCrypto. Larger files use a server
   issued resource link. `app.downloadFile` acceptance is reported as a handoff,
   not a local save. Rejection is not assumed to specifically mean cancellation;
   timeout/connection loss reports an unknown outcome and never auto-repeats.
3. **Explicit external fallback:** `Download in browser` uses the host's
   `openLink` bridge to open a private, expiring link. It is labeled external and
   secret. The link is `GET|HEAD /course-file-download/{capability}`. It is a
   random 256-bit bearer grant; only its digest is stored. Possession grants
   access, and does not establish the redeemer's identity. Every redemption
   checks the original owner's current scope, credentials, file access and
   pinned source version. It never forwards a Canvas credential to the host.

The download card is static `ui://canvas-bridge/original-download-v1.html` and has
no network CSP origins. It receives transport objects only from the authenticated
app call, not arbitrary model text. No download occurs on mount/rerender. The
ordinary UI shows filename, course, size, original-file label, download/retry and
separately labeled Canvas source actions. No hashes/internal IDs are displayed.

All binary HTTP responses use attachment disposition with UTF-8 filename
encoding, exact length, `private, no-store`, `nosniff`, `no-referrer`, and a sandbox
CSP. HTML and active originals are attachments, never rendered on this origin.
HEAD does not consume a grant. **Ranges are intentionally unsupported**:
`Accept-Ranges: none`; any Range header receives the complete pinned representation
with HTTP 200. This is not resume support and does not splice versions.

## Integrity, limits and recovery

Both paths use the existing public-only, DNS-pinned downloader. Original delivery
adds an exclusive private sink, incremental size/hash accounting, a post-transfer
version/access check, and atomic promotion. Unexpected HTML/JSON in Office/PDF
responses, type mismatches, dishonest lengths and truncated/disconnected streams
cannot become prepared originals. Identity content encoding is requested; encoded
responses fail explicitly rather than risking different or double-decoded bytes.
Authorized empty and malformed files are delivered unchanged. Unparseable or
encrypted files do not require extraction permission or parser support.

Settings use the existing `BRIDGE_` environment prefix:

| Setting | Default / bound |
|---|---|
| `FILE_DELIVERY_ENABLED` | true |
| `FILE_DELIVERY_ROOT` | dedicated `original-delivery` sibling of the private vault key |
| `FILE_DELIVERY_MAX_BYTES` | 50 MiB, adjustable downward |
| `FILE_DELIVERY_INLINE_BYTES` | 128 KiB, adjustable downward (0 disables nonempty inline payloads) |
| `FILE_DELIVERY_TTL_SECONDS` | 300 seconds, maximum 900 |
| `FILE_DELIVERY_STAGING_BYTES` | 512 MiB, adjustable downward |
| `FILE_DELIVERY_BUDGET_SECONDS` | 90 seconds, adjustable downward |

The Compose template places staging in its existing temporary filesystem with a
64 MiB aggregate budget, leaving room for parser jobs. It does not try to write
alongside read-only mounted secrets.

There are two active operations per principal, four per process, and at most 256
prepared records. Acquisition reserves the declared bytes against the aggregate
quota before transfer; actual bytes are checked during streaming. Available disk
space is checked. HTTP response chunks are 64 KiB and obey backpressure. Existing
upstream HTTP timeout defaults to eight seconds per operation; current metadata
reads retain the existing refresh budget. Host deadlines may be shorter; a timeout
does not create a resumable job or justify reporting success.

Use **one API process per staging root**. An exclusive process lock prevents a
second process deleting active files. Staging failure does not disable unrelated
reader tools. POSIX staging mode is 0700; Windows removes inherited access and
grants the service identity and SYSTEM. Generated object IDs, never filenames,
form disk paths. Keep this directory private and out of backups/source control.

Delivery records/capability digests are memory-only. Restart revokes every old
reference, and startup removes abandoned generated objects under the exclusive
directory lock. Normal cleanup runs at each operation and every 60 seconds.
Expired/failed objects are removed; Windows deletion failures are retried and
continue to count against quota. An authorized active stream pins its object,
with a bounded transfer deadline. No new transfer may start with an expired grant.
Retention is normally the same five minutes as the grant, shorter than the spec's
suggested fifteen-minute maximum. Shutdown removes staged files.

Expiry uses both wall time and monotonic elapsed time. Backward time, a clock
discontinuity over five seconds, restart, and configured origin changes invalidate
references conservatively. A forward jump/sleep cannot extend the grant. Laptop
sleep, offline server or dead tunnel can interrupt delivery. `Get a fresh download`
reauthorizes and fetches current bytes; it never extends an old record. Explicit
expected-version/hash inputs continue to apply on refresh.

Uvicorn access logging suppresses bearer-route URLs even if access logging is
enabled. Existing outbound wire-log suppression is reused. Tunnel/proxy request
inspection must also remain disabled or redact `/course-file-download/*`; the
application cannot redact another service's logs. Existing delivered copies are
outside connector revocation and cleanup control.

## Verification and release boundary

See `evidence/sanitized-results/original-file-delivery.md` for actual checks.
Synthetic tests include complete MCP and HTTP byte comparisons, unsupported parser
formats, version/hash guards, cross-owner substitution, stale scope, denied files,
private payload separation, source replacement at redemption, encoding/errors,
quota/cancellation, clocks, restart cleanup, safe filenames and host failure states.
Existing network tests exercise redirects, private/IPv6 destinations and pinned
DNS; reader/authorization regressions cover the shared transport.

| Surface | Original downloaded | Byte match | Native conversation attachment |
|---|---|---|---|
| ChatGPT web | Not tested: available browser profile signed out | Not established | Not established |
| ChatGPT desktop | Not tested | Not established | Not established |
| ChatGPT mobile | Not tested | Not established | Not established |
| Official MCP client + HTTP test client | Synthetic pass | Exact match | Not applicable |
| Chromium external browser | Synthetic pass | Exact match | No |
| Private operator using live Canvas and in-process HTTP endpoint | Pass | Reference = staged = delivered | No |

At the earlier implementation check, the installed private connector ran the
previous catalog. The later owner report does not identify the deployed build.
Inspect the current service/catalog before deciding whether a restart or metadata
refresh is needed as part of an intended deployment. No database migration, new OAuth scope, token replacement,
paid storage or model API key is needed. Actual ChatGPT download support remains a
release gate; backend tests and a compiled widget do not establish it. Test web
and at least one mobile flow before advertising cross-device support.

Repeat in the intended ChatGPT client after deployment/catalog refresh:

> Find PCR_Analysis.xlsx in my selected Omics course. Prepare its unchanged
> original with prepare_course_file_download and show Download original. Report
> preparation separately from download or attachment. After I save it, compare
> its byte count and SHA-256 with the prepared original and an independently
> retrieved current authorized Canvas copy. Then test expiry and Get a fresh
> download, and confirm read_course_file still extracts the workbook.

Capture negotiated host capabilities, surface/build, actual downloaded filename,
length and SHA-256; test unsupported host, rejection and lost transport separately.
Do not identify a native attachment without a real supported attachment receipt.

Primary contracts checked on October 22, 2026:
[OpenAI plugin reference](https://developers.openai.com/plugins/reference),
[MCP Apps downloadFile](https://apps.extensions.modelcontextprotocol.io/api/classes/app.App.html#downloadfile),
[Canvas Files API](https://developerdocs.instructure.com/services/canvas/resources/files).
