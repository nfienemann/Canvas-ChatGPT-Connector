# AI data egress and content governance

## Temporary permissive private mode

`BRIDGE_EGRESS_MODE=permissive` skips recipient/workspace, classification-review,
modality/hash-review and egress amount-policy requirements, and purpose-specific
output minimization. Restart the service after changing this setting. Restore
`strict` to re-enable these checks. Strict remains the default.

Permissive mode is supported for synthetic fixtures and owner-only, read-only
personal services bound to loopback. Ownership, ordinary authorization, privacy
filtering, known restricted/third-party/confidential content, credential/link
protection, transport validation and academic-integrity checks remain active.
Bearer original downloads and external processors retain their separate denials.
Responses carry `EGRESS_PERMISSIVE_MODE`; unknown classification stays unknown.
This temporary mode does not establish recipient permission or release readiness.

## Explicit private course-content permission

An optional signed `private_course_listing.course_content` grant represents an
owner's explicit permission for private course-content use. It names exact course
references and text/structured/visual channels, and binds an encrypted permission
evidence digest. Evidence may be an owner attestation of institutional/provider
permission; that is not independently verified correspondence, a public release
approval, or a fabricated per-source privacy review.

This default-off grant uses the parent's exact owner/issuer/registered ChatGPT
client binding. It applies only to a read-only personal deployment on loopback,
and only `read_course_file`, `render_course_file_page`, `render_course_slide`,
`get_file_extraction_status`, and `get_assignment_details`. It does not grant
original downloads, other clients,
hosted release, submissions, grades, or external processing. Source and byte
identity must be present and consistent. The metadata-only extraction-status
route requires source-version identity but does not require already extracted
bytes: it must be able to report an uncached file without downloading it. This
exception cannot authorize text, images, or original bytes. Canvas authorization
and the independent
provider/institution/sharing checks still run; selected-course access, revocation,
expiry and privacy filtering are not bypassed. Known third-party, restricted,
confidential or restrictive reviewed sources remain denied.

Previously unclassified content admitted under this scope is reported as
`OWNER_AUTHORIZED_PRIVATE_COURSE_CONTENT`, not public or instructor-owned. This
describes the private authorization basis, not independently certified ownership
or recipient retention/training/workspace terms. Changing/removing the signed
grant affects the next request. Full egress governance, when configured, retains
its own review requirements rather than inheriting this private exception.

The offline `restore_reviewed_file_text_digest` helper can also recover an omitted
text binding from the original encrypted review evidence. It requires exact
source/version/byte-hash/rights-reference matches and changes no permission or
channel. Changed extraction text still requires a matching review unless an
explicit broader private course-content grant covers the transfer.

Implemented locally on 2026-10-25 against synthetic fixtures. This is an
enforcement mechanism, not evidence of institutional permission, content-owner
rights, vendor authorization, or an approved ChatGPT deployment. The separate
[authorization gateway](authorization-policy-gateway.md) remains mandatory.

## Release boundary

`DataEgressPolicyEngine` runs after resource authorization and source-specific
privacy normalization, then applies a final privacy filter, source classification,
purpose-specific minimization, and recipient/content policy evaluation.
Authorization to retrieve or analyze a document locally does not authorize release.

The MCP registration wrapper gates structured and JSON text responses, document
extraction/search, PDF/PPTX images, figure readers, private image metadata, original
attachments, and temporary links. The SDK boundary also sanitizes input-validation
and unknown-tool errors and gates the fixed tool/resource catalog and static UI
resources. HTTP protocol errors are reconstructed without reflected input values.
OAuth resource discovery passes the static metadata gate. There are no dynamic
MCP resource templates or arbitrary resource-fetch tools.

Original-file HTTP routes check content policy before response headers and before
each body chunk, in addition to the existing fresh ownership, scope, source and
integration checks. Already delivered bytes cannot be recalled. Aggregate settings
exports also cross the engine: live archives are unclassified mixed content and
fail closed. There is no installed external AI/document-processing adapter;
`external_processing` explicitly denies. Existing parsers and renderers run locally.

## Trusted configuration

The existing administrator-signed **sharing** approval record accepts an optional
`egress` object (`EgressGovernance`). Missing governance does not inherit permission
from a broad sharing grant. Records are reloaded for each release; changes,
revocation, expiry and invalid signatures take effect without a grant cache.
Underlying evidence remains in the approval gateway's encrypted evidence store.
No approval evidence, correspondence, administrator references, or recipient
registry is returned through MCP.

An `egress` object contains:

- `policy_version`: the administrator's private configuration revision.
- `recipients`: exact reviewed destinations, with policy ID, recipient category,
  environment, workspace, plan, issuer, client ID, content classifications,
  purposes, output channels, maximum output bytes, retention days, training use,
  and downstream processing categories.
- `max_retention_days`, `allow_training`, `allowed_processing`: institutional
  ceilings for those recipient policies.
- `content_reviews`: exact opaque source ID and source version, classification,
  permitted purposes, reviewed channels, and an externally established
  content-owner permission reference where required. File text, pixels, original
  bytes and links additionally require the matching `content_sha256`.

Content-bearing reviews also require `privacy_reviewed_channels` and a private
`privacy_review_reference`. These are independent of content ownership and
extraction coverage. See [the privacy pipeline](third-party-privacy.md).

Use `egress_models.py` for the strict field vocabulary. Unknown fields are rejected.
Maintain these records with the existing offline administrator signing workflow;
the running service has public verification keys only. An administrator must obtain
and verify the permissions and processing terms before signing a real record.
The fictional records in `tests/egress_fixtures.py` are examples for tests only.

The authenticated issuer must supply non-user-editable, signed
`bridge_recipient_environment` and `bridge_recipient_workspace` claims. They are
matched exactly alongside the verified issuer and OAuth client ID. The plan is the
administrator-reviewed plan associated with that exact environment/workspace.
Missing or mismatched claims deny academic release. MCP arguments, clientInfo,
headers, a user's settings checkbox, filenames, Canvas text, and model instructions
cannot select or change these claims or the registry. Before a pilot, verify the
identity provider's claim mapping cannot be controlled by an ordinary user.

This policy enforces configured processing conditions; it does not independently
observe a recipient's actual retention or training behavior. Changes to the real
recipient environment require administrator review and corresponding record updates.

## Classification and decisions

The engine supports `PUBLIC_OR_APPROVED`, `FIRST_PARTY_EDUCATIONAL_RECORD`,
`THIRD_PARTY_EDUCATIONAL_RECORD`, `INSTRUCTOR_OWNED_COURSE_CONTENT`,
`RESTRICTED_ASSESSMENT`, `CONFIDENTIAL_RESEARCH`, and `UNKNOWN_OR_UNCLASSIFIED`.

Source context is built from owned connection/course/work/material records and
signed reviews, never an asserted license or classification in retrieved text.
Subject mismatch, assessment restrictions and confidentiality override a permissive
label. Third-party educational records, restricted assessments and confidential
research deny release in this implementation. Unknowns require authorized review.
Derived results inherit their source restrictions: transforming, summarizing,
redacting, embedding or rendering content does not reset its classification.
An explicit restricted source review also blocks minimized deadlines. A reviewed
source whose version changes becomes unclassified until reviewed again. The
returned source version cannot borrow permission from a different cached version.

The five decisions are `ALLOW`, `ALLOW_MINIMIZED`, `ALLOW_REDACTED`, `DENY`, and
`REQUIRES_AUTHORIZED_REVIEW`. Errors explain that content was not transmitted and
that authorized local analysis remains available. Reconstructed safe errors have
their own `ALLOW_REDACTED` decision; the denied content's decision is separately
reported as `data.content_decision` when available.

Live workload responses project assignment titles, dates and personal work status;
own-grade responses project four Canvas grade fields; course lists project basic
authorized course metadata. Raw documents, source excerpts and arbitrary extra
fields are omitted from these minimized operations. Other live composites without
resolvable, reviewed source provenance remain blocked. Pure local analysis and
the isolated synthetic academic workflows remain available.

Instructor-owned materials, submissions, feedback, pages and documents require
source/version-bound review. A public/approved classification itself must be
supported by external evidence; sanitization never establishes legal rights.
File reviews bind both metadata version and source byte digest. An image requires
an explicit `visual` review; text extraction and email redaction cannot certify
pixel privacy. Any unreviewed modality, content hash or changed source requires
new review.

## Original-file limitations

Live bearer download links are disabled: a capability URL does not prove the
recipient's environment. Previously minted links also fail after a transition to
live mode. An approved small inline attachment can still be returned to a verified
MCP environment, with `external_url: null`. Larger files require the authenticated
HTTP route with a verified recipient token; the MCP host handoff fails safely when
it would require an unauthenticated link. The download card explains an unavailable
browser fallback. Synthetic expiring-link fixtures continue to function.

Known original-file/capability URLs, including encoded forms, are rejected when
hidden in ordinary summaries, metadata, errors or purportedly derived outputs.
Only the dedicated, source-bound delivery code can construct attachment carriers.

## Audit and verification

The `canvas_bridge.data_egress` logger emits only `policy_version` (engine version),
`classifications`, `recipient_category`, `decision`, and `reason_code`. It does not
include source IDs, user IDs, workspace IDs, tokens, evidence, raw content or
excerpts. The administrator's private revision and references are not exposed.

Blocked `release` calls additionally emit a warning-level `data_egress_blocked`
correlation event with the server-generated request ID, fixed reason code and
decision. This event contains no source identifiers, versions or content. Earlier
five-field decision records cannot be retroactively correlated to a request ID.
Classification errors expose `processing_stage: source_classification`; the
denied `content_decision` survives repeated error reconstruction separately from
the safe error envelope's own allowed release decision.

Tests include all ten requested content fixtures and real local MCP/HTTP tests for
alternate text/search/metadata/image/attachment/download routes, signed recipient
identity, source changes, modality and byte-hash review, policy changes before
release, SDK errors, and continued synthetic/local operation. Read the
[validation record](../evidence/sanitized-results/data-egress-governance-2026-10-25.md)
for actual checks and remaining deployment gates.

## Explicit private course-list consent — November 3, 2026

An optional signed sharing-record `private_course_listing` grant permits only the
minimized `list_courses` structured metadata response for one exact owner hash,
issuer and registered MCP client. This operator-requested private exception does
not assert verified plan, workspace, retention or training facts. It requires an
owner-restricted personal profile, loopback binding, MCP read-only mode, existing
provider/institution/sharing authorization, authenticated client mapping, source
ownership, privacy filtering and minimization. Output is capped at 100,000 bytes.
It is unavailable to hosted profiles and all other tools, modalities and source
kinds. General egress governance remains necessary for documents, grades and
other academic outputs. Revocation, expiry and invalid signed records deny access.


The same signed private grant may explicitly select `minimized_study_metadata` to
also permit only `get_workload` structured, minimized schedule output from owned
course/deadline sources. The original `minimized_course_listing` scope does not
inherit that permission. Empty windows retain their requested/coverage course
provenance and require current assignment authorization. No file/page, grade,
raw submission, assessment answer, other tool or modality inherits this grant.


## Private version-bound text review

The signed private grant can explicitly select `reviewed_private_text` and carry
`private_text_reviews` on its sharing record. These use the existing ContentReview
vocabulary and retain exact source/version binding, file-byte hash binding, explicit
rights references and separate privacy-reviewed channels. Duplicate source/version
reviews are invalid. Only reviewed text/structured `read_course_file`, `fetch_course_material`
and structured `get_assignment_details` output is supported; no pixel, original-file, grade,
peer, restricted assessment or confidential-research permission is inherited.
The private owner/issuer/client, loopback, read-only, authorization and privacy
checks continue to apply. This mode does not certify recipient training/retention
or workspace terms. Missing reviews remain denied. A local operator must inspect
actual text and provide a supporting rights reference before a review is signed;
preparing a packet, parser success and model assertions never create that review.


## Explicit private permission diagnostics

`private_course_listing.allow_permission_diagnostics` is a separate signed,
default-false permission for minimized `audit_permission_consistency` structured
output. It is bound to the same exact personal owner/issuer/client, loopback and
read-only profile. The transfer is reconstructed from a fixed diagnostic field
vocabulary and an owned-connection diagnostic source. It returns permission
states, opaque course references, reason codes and explicit upstream-check flags;
course content, approval correspondence and credentials are excluded. This does
not enable other audit tools, academic content, hosted release or upstream probes.
The audit still reports stale/denied/unchecked states truthfully and does not
refresh scope, change selection, repair permissions or mutate Canvas. Existing
provider/institution/sharing decisions and privacy/output checks remain required.


## Private material inventory and extraction identity

`private_course_listing.allow_course_material_inventory` separately permits the
minimized `list_course_files` metadata response, bound to the owned selected
course and its files capability. Only opaque references, inspected filenames,
format/size/access/extraction states are retained; bodies and download URLs are
removed. This does not grant content or binary release.
Private file/page text reviews additionally bind `extracted_text_sha256` to the
exact sanitized cached text. Parser/OCR improvements cannot inherit a footer-only
review merely because original file bytes and metadata are unchanged. Changed or
missing extraction identity requires fresh source review. Images/originals remain
separately gated. The private review helper records this digest only after the
operator actually reviews the displayed text.
