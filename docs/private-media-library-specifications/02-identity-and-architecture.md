# Identity and architecture

## One account and one evidence core

Use the existing Bridge identity derived from verified issuer and subject. Do not accept `owner_id`, email, Canvas user ID or tenant ID as client-selectable ownership. Hosted federation and local identity may have different issuers; linking them requires a verified account-link flow, never matching email or filename. A library may be provisioned lazily on the first authorized write. Status/read requests must not create consent or content.

Library lifetime belongs to the Bridge account. LMS disconnect affects sources whose lineage depends on that LMS, not independent ownership. Application sign-out revokes the session; it does not delete stored files. Deleting the Bridge account revokes every library session and queued operation. Host client recipients are separately verified and may require separate sharing grants even when they act for the same person.

## Components

| Component | Responsibility | Reuse or delta |
|---|---|---|
| Identity and settings session | Authenticate owner, CSRF, revocation generation | Reuse `auth.py`, settings and principal state |
| Library service | Catalogue, intake transactions, versions, quotas and ACL evaluation | Extend independent service; normalize durable metadata |
| Storage adapter | Private encrypted object put/read/delete, checksums and recovery | New `LibraryObjectStore` interface; no caller paths |
| Quarantine and worker queue | Validate originals; schedule bounded extraction | Extend current parser, request-limit and worker lifecycle code |
| Representation index | Authorized extracted text and exact source locators | Reuse readers/usefulness search; add durable version keys |
| Host intake adapter | Translate verified host file references into bounded ingress | New optional adapter; no general HTTP tool |
| Delivery gateway | Authorize original/preview/text release and audit outcome | Extend existing original-delivery and visual-delivery patterns |
| Study adapters | Consume permitted selected evidence | Reuse independent academic and process engines |

Flow: authenticated selection → intake/consent record → quota reservation → private quarantine → content validation → immutable original publication → asynchronous representations → current authorization → bounded MCP evidence or owner download. Host references are temporary transfer inputs; Bridge IDs are persistent source identities.

## Storage contract

`LibraryObjectStore` MUST support private staging writes, atomic publish, version-addressed authenticated reads, checksum verification, idempotent deletion and inventory reconciliation. Keys are server-generated opaque values, never user filenames. Application requests carry owner and version context; the adapter cannot accept arbitrary paths or URLs. Do not expose object keys, credentials or vendor signed URLs in model responses.

Hosted metadata uses PostgreSQL with owner-qualified constraints and tested transaction/row-lock behavior. A private object bucket has no public ACL or listing; encryption keys and storage credentials remain server-side and separate from metadata access. Local mode uses a private encrypted directory outside static assets and synced/public workspace folders, with restrictive OS access. It uses the same API and evidence semantics; local success does not establish hosted concurrency or remote availability.

Keep originals outside the encrypted JSON rows used for current temporary imports. Stream bytes to storage and keep only protected metadata and references in the database. Store derivatives separately with parent IDs, parser/renderer versions, limits, creation time and deletion epoch. No cross-owner deduplication or hash-existence endpoint is permitted in L1. Within an owner, deduplication can reuse physical bytes while keeping source provenance and grants separate.

## Authorization evaluation

Before every operation, validate account/session, owner, item/version state, deletion generation, provenance dependencies, requested processing purpose and recipient/channel grant. Use the existing egress and academic-integrity boundaries. Recheck after expensive work and before response serialization or stream release. A broader library grant never overrides a narrower source restriction.

Browser owner downloads and local preview use the owner-session channel. Returning bytes to a model is a distinct recipient release. Metadata also needs its own disclosure decision because titles and filenames can identify people. The model-visible inventory excludes items not permitted for metadata sharing; the owner's settings page can still show all their own items and reasons for withholding.

## Reachability and continuity

Remote hosts need the approved HTTPS MCP and upload endpoints to be reachable. Local storage on a sleeping/offline computer is unavailable; report that state rather than claiming cloud continuity. A hosted library provides cross-device access only through the same verified account. Client OAuth tokens are not object-storage credentials. Reconnect to Bridge never implies permission to reconnect Canvas.

Background processing is deterministic and bounded. No backend model service or embedding API is required for L1. A later paid/external processing adapter must have its own user-visible capabilities, recipient controls, budget and deployment approval.
