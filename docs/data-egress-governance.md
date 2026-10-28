# AI data egress and content governance

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

Tests include all ten requested content fixtures and real local MCP/HTTP tests for
alternate text/search/metadata/image/attachment/download routes, signed recipient
identity, source changes, modality and byte-hash review, policy changes before
release, SDK errors, and continued synthetic/local operation. Read the
[validation record](../evidence/sanitized-results/data-egress-governance-2026-10-25.md)
for actual checks and remaining deployment gates.
