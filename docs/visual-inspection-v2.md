# Visual inspection v2: contract and compatibility

Implementation and investigation date: October 23, 2026 (America/New_York).
Local implementation is available for review. The ordinary ChatGPT client
acceptance gate is **not complete**. No live service restart/deployment occurred.
The existing deployed renderer did supply actual viewable images through the
Canvas Bridge tool in this Codex conversation; that is a separate surface.

## Transport findings

The existing implementation already emits standard MCP `ImageContent` with PNG
base64 in `content`. Rendering was not the missing transport implementation.
MCP specifies image tool content but does not guarantee a particular host UI or
model input path. The current ChatGPT bridge documents optional image handoff
through `uploadFile`, widget `imageIds`, and follow-up messages. The existing
reader also feature-detects MCP Apps image model-context support. Capability
checks must not branch on a browser user-agent or infer universal support.

Primary documentation inspected for this investigation:

- [MCP tool image content and interaction model](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
- [OpenAI component bridge and imageIds](https://developers.openai.com/plugins/reference).
- [OpenAI UI capabilities and feature detection](https://developers.openai.com/plugins/build/chatgpt-ui).

| Surface / mechanism | Evidence | What remains unknown |
|---|---|---|
| Local HTTP MCP client | Synthetic native image blocks, valid rendered PNGs, hashes and dimensions checked | No model participates in a Python protocol test |
| Current Codex desktop conversation / connected Canvas tool | Actual returned `image` blocks forwarded with the provided image-content helper; this model saw the pixels for fixtures A and B | This is not an ordinary ChatGPT web/desktop/mobile test; the exact MCP initialization identity was not exposed |
| Ordinary ChatGPT direct tool result | Earlier repository record and supplied reproduction report metadata without visible pixels | Current build/client retest required; no universal incompatibility claim |
| Ordinary ChatGPT native reader | User supplied successful manual handoff; synthetic bridge regression checks pass | Current end-to-end client retest is outstanding |
| ChatGPT mobile and other surfaces | Not exercised | Unknown, independently gated |

No evidence registry was populated from the Codex observation: a unique exact
client-build identity for that route was unavailable. Successful HTTP delivery,
an image hash, a screenshot shown only to the human, or a UI method returning
success is insufficient to register model visibility.

The owner requested all three ordinary ChatGPT surfaces where possible and can
return a new stress-test report. Use the ready-to-paste
[cross-client test request and report template](visual-inspection-stress-test.txt).
It can test the existing deployed renderer now and detects missing v2 tools
without confusing tool deployment with host image support.

## Backward compatibility and delivery selection

`render_course_file_page` retains its arguments, image content, private reader
payload, receipts, expiry and source checks. Its metadata gains `visual_pipeline`,
`render_diagnostics`, and `image_delivery`. The legacy private image copy is
necessary for the existing OpenAI widget globals. Pixels never appear in
`structuredContent` or text content. The new explicit native mode emits image
bytes once in `ImageContent`; its reader can re-fetch through the legacy tool.

`inspect_course_figure(connection_id, file_id, figure_label?, page?,
expected_hash?, continuation?, delivery_mode="auto")` uses the same authorized
file IDs and renderer. No URL/path input is accepted. Modes:

- `auto`: native image only for a current operator-verified exact client build;
  otherwise preserve the native reader and explicitly report unknown/unsupported.
- `native`: explicit diagnostic attempt at standard MCP image delivery. This
  does not set support or visibility to true. Retry `reader` after host failure.
- `reader`: private existing page-reader payload, with fresh access validation
  before its button uploads or updates model context.
- `text`: bounded candidate excerpts and a text-reading fallback; no rendering.

A server cannot observe a host silently dropping pixels after receiving a tool
response. It cannot automatically repair that host behavior. The tool guidance
and reader provide the supported retry paths without claiming successful vision.
When neither path exposes pixels, report `visual_inspection_unavailable`.

## Stable evidence metadata

`visual_pipeline` has seven named stages, each with `status` and `evidence`:

| Stage | Evidence accepted |
|---|---|
| `source_authorized` | Current file authorization and selected-scope checks |
| `source_retrieved` | Source bytes and stable version checked by the renderer; or historical render receipt when recording a report |
| `page_rendered` | Validated worker PNG; or historical receipt |
| `image_delivered_to_host` | Unknown in a prepared response; an assistant report is labeled `reported`, never server-verified |
| `image_visible_to_model` | Unknown until an attributed actual-pixel report; unavailable reports are explicit |
| `visual_interpretation_completed` | Attributed assistant report, independently unverified |
| `interpretation_verified` | Always unknown/false here; no validated scientific verification backend exists |

`established` is server-observed evidence, `reported` is an assistant assertion,
`reported_unavailable` records a visibility failure, and `unknown` means no
adequate evidence. Receipt validation establishes provenance, not truthfulness.

`image_delivery` reports schema version, mode, prepared/not-attempted status,
MIME type, byte count, capability basis and fallback reason. Render diagnostics
include duration, dimensions and source-version consistency. Error categories
are stable codes. No diagnostic log contains image/document bytes, private URLs,
credentials, or full receipts.

## Figure search and limits

Line-start captions rank ahead of in-paragraph references. Figure/Fig./Table and
Panel labels, graph terminology, nearby explanatory excerpts, neighbors and
explicit page references supply candidate signals. They cannot confirm a graph.
An explicit page is inspected first; after a negative or ambiguous visual result,
follow the sealed continuation to the next ranked candidate. One call renders at
most one page, preserving the existing single-page reader.

The continuation binds owner, connection, exact file, scope epoch, source hash,
version, candidate queue, cumulative render attempts, image bytes, processing
time and one-hour expiry. Each continuation freshly authorizes the source.
There is no server loop that assumes text matches are visual confirmations.

Defaults and configurable ceilings:

| Setting | Default | Maximum |
|---|---:|---:|
| `BRIDGE_VISUAL_CANDIDATE_PAGES` | 40 text pages searched | 200 |
| `BRIDGE_VISUAL_CANDIDATE_LIMIT` | 6 ranked candidates | 8 |
| `BRIDGE_VISUAL_RENDER_ATTEMPTS` | 3 per continuation chain | 8 |
| `BRIDGE_VISUAL_TOTAL_IMAGE_BYTES` | 3,900,000 | 10,400,000 |
| `BRIDGE_VISUAL_EXECUTION_SECONDS` | 90 cumulative processing seconds | 120 |
| `BRIDGE_VISUAL_WORKER_MEMORY_MB` | 384 MiB for PDF rendering | 384 (minimum 128) |

Existing parser/source limits still apply: 10 MB PDF, 200 PDF pages, 250,000
extracted characters, 384 MiB worker memory, 10 CPU seconds, 15 worker wall
seconds, 1.3 MB PNG, and nominal 2400-pixel longest edge (2401 rounding ceiling).
The visual memory setting can only lower the existing ceiling; ordinary text
extraction retains its current limits. Windows uses its Job memory bound and
Linux passes the reduced bound to the isolated bootstrap's address-space limit.
Authorization/network calls retain their own existing timeouts. A cancelled
await does not remove the worker's OS-enforced limit or cleanup. Candidate text
discovery may reuse the existing full-document extraction cache; the candidate
page setting bounds ranking, not a replacement PDF parser. Image renders remain
transient, with no new persistent image cache. A render exceeding the cumulative
byte allowance is discarded. Budgets bound a linear continuation chain, not an
account-wide quota; independent/replayed requests retain existing worker limits.

Image-only pages without text signals and pages beyond the search window remain
unsearched unless explicitly requested. No matches are not proof of no figure.
Regions in observations are normalized annotations on an already bounded image;
this version does not offer pixel crops or add a second conversion backend.

## Scientific observations and text reconciliation

`record_course_figure_observation(connection_id, render_receipt, observation)`
accepts an actual-pixel report, reauthorizes its file/version, and returns an
attributed record to the conversation. It never saves or overwrites extracted
text, repairs source content, or claims independent scientific verification.

The schema supports `figure_confirmed`, `figure_not_found`, `figure_ambiguous`,
and `visual_inspection_unavailable`. Visible reports need a descriptive visible
feature. Confirmation also needs a normalized region. These are assistant
assertions, not independently established model visibility. Missing pixels
cannot support observations; unconfirmed figures cannot have graph panels.

Each panel keeps separate labels, graph type, axes, units, legend/groups, trends,
uncertainty indicators, statistical annotations and limitations. Fields are
`observed`, `unknown`, or `not_readable`. Unknown/unreadable fields cannot contain
fabricated values. Numerical readings require a region, evidence, and a precision
class: `explicit_label`, `reliably_read`, or `visual_estimate`. Do not infer
significance from differences or assign SD/SE/CI to unspecified error bars.

Direct visual observations, source interpretation with an attributed passage,
and assistant inference remain separate. Source-passage matches against current
page text are identified; unmatched visual transcriptions remain unverified.
Reconciliation supports table-cell assignment, reading order, interleaved
columns, labels, numerical errors, superscripts/subscripts, units and mismatched
captions. Each proposed correction has its own region, confidence and attribution.
An available current text cache checks an exact anchor; a mismatching anchor is
rejected. Missing text is labeled unavailable, never silently reconstructed.

## Operator verification record

Optional `BRIDGE_VISUAL_CLIENT_EVIDENCE_FILE` points to a private JSON array
(at most 16 KiB and 20 records). Missing, corrupt, expired, duplicate, ambiguous
or unsupported evidence resolves to unknown and cannot prevent MCP startup.
Each record contains `client_name`, `client_version`, `native_image` (`supported`
or `unsupported`), `basis: "model_visible_probe"`, `evidence_id`, ISO timezone-aware
`observed_at` and `expires_at` (at most 30 days apart), and
`client_identity_unique_to_tested_surface: true`. The name/version must match
the MCP initialization record exactly. If multiple surfaces share that identity,
do not enable this record. Do not store tokens, image contents or transcripts in it.
These delivery hints never change authorization.

Before registering support, run the synthetic four-page fixture in
`tests/visual_fixtures.py` through the intended client with `delivery_mode=native`.
Ask for the color, shape and position of its unlabeled visual marker without
revealing the answer in tool text. Compare the response with the separately
reviewed image. Test the reference page, graph page, prose negative control and
table layout independently. Verify reader fallback, then record surface/build,
transport, timestamp, result and sanitized evidence reference. Repeat for every
advertised surface. See [acceptance results](../evidence/sanitized-results/visual-inspection-v2-2026-10-23.md).
