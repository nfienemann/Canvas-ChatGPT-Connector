# Authorization and policy enforcement gateway

Implemented locally on October 25, 2026. This gateway enforces administrator-attested
approvals actually obtained. It does not establish legal eligibility, obtain
permission, or replace review by Instructure and the applicable institution.
No real approval records are distributed with the project.

## Independent authorities

All applicable checks must pass:

| Authority | Source of authority | Enforcement |
|---|---|---|
| Provider | Verified written permission for the integration method | Signed `provider` record, explicitly including both `rest_api` and `mcp` |
| Institution | Verified deployment and data-use approval | Separate signed `institution` record for the exact registry institution ID |
| User | Authenticated server-resolved principal and current Canvas access | Existing owner, connection, selection, course lease, capabilities, item visibility and upstream access checks |
| Sharing | Verified permission to process or disclose the specified content | Separate signed `sharing` record, requested recipient and content conditions |

OAuth consent, personal tokens, environment flags, an enabled institution registry
entry, successful HTTP requests, installation and source licenses do not satisfy
the provider, institution or sharing checks. Personal development with real
records has the same approval prerequisites as other live profiles.

`ApprovalState` implements `NOT_ASSESSED`, `APPROVAL_PENDING`, `APPROVED`,
`RESTRICTED`, `DENIED`, `EXPIRED` and `REVOKED`. `RESTRICTED` permits only its
explicit scope. Missing, invalid, unverified, future-effective, expired, denied
or revoked approvals fail closed. The effective interval includes its start and
excludes its expiration. No approval has an unbounded expiration.

## Administrator trust and confidential evidence

Three optional configuration paths locate records; they never create approval:

- `BRIDGE_APPROVAL_TRUST_FILE`: administrator public keys and their delegated
  organizations, authority types and explicit institutions.
- `BRIDGE_APPROVAL_RECORDS_FILE`: the current signed approval bundle.
- `BRIDGE_APPROVAL_EVIDENCE_ROOT`: encrypted, content-addressed evidence envelopes.

Provision these outside the repository, database backups, cloud-synced folders,
static web roots and user-controlled upload/storage areas. The operating-system
administrator must give the service account read access only; ordinary users
must have neither read nor write access. Keep signing keys and evidence-decryption
keys outside the service's access boundary. The trust file is a deployment trust
root, not a student preference. Compromise of that root or the executing code is
outside the application-level protection provided by signature verification.

An authorized administrator first verifies the approving organization and
authority, actual written authorization, applicability to MCP, institution,
deployment, data categories, recipients, dates and conditions. The administrator
then records that determination. A digital signature authenticates this
attestation; it cannot establish that an organization actually issued permission.
Unresolved authority or conditions must remain unverified/pending or denied.

The trust file has this shape (placeholders are intentionally nonfunctional):

```json
{"administrators": [{
  "key_id": "administrator-key-id",
  "public_key": "BASE64_RAW_ED25519_PUBLIC_KEY",
  "organization": "Verified approving organization",
  "authorities": ["institution", "sharing"],
  "institutions": ["exact-registry-id"]
}]}
```

An institution-only key cannot sign provider approval. Delegate `provider`
authority only through the separately reviewed administrator trust process.
There is no runtime private key and no MCP/browser approval-management endpoint.

The bundle is `{"schema_version": 1, "records": [...]}`. Each entry contains
`key_id`, `record` and `signature`. Signatures use Ed25519 over UTF-8 JSON of the
original `record`, with sorted keys, separators `,` and `:`, and ASCII escaping.
The strict schema rejects unknown fields. The administrator-maintained record
contains:

- `record_id`, `authority`, provider `instructure_canvas`, approving organization
  and authority, written authorization reference and encrypted evidence SHA-256.
- State, verification status, verifier and verification time.
- Explicit institutions, mechanisms, deployment modes, activities, data
  categories and recipients. Wildcard institution grants are unsupported.
- Aware `effective_at` and `expires_at` timestamps and enforceable conditions.

Categories are `identity`, `courses`, `assignments`, `grades`, `syllabus`, `files`,
`modules`, `pages`, `quizzes`, `discussions`, `calendar`, and `announcements`.
Activities are `retrieve`, `share`, `link`, and `refresh`. Recipients are `local`,
`chatgpt`, and `user_download`. Unknown categories or recipients have no grant.

Conditions support explicit resource allow/deny lists, local-processing-only,
and a list of unimplemented conditions. A nonempty unimplemented list denies
access. These are administrator-authored constraints; course text and model
instructions cannot alter them. Resource restrictions are conservative: an
aggregate request with no resource identity is denied when it cannot establish
that a restriction is satisfied. Requests are never authorized by unioning
partial grants. Only one current record is accepted for each authority/institution;
overlapping records fail closed so an older broad grant cannot mask a new restriction.
Replace obsolete grants instead of appending historical ones. Retain history
separately and privately.

The offline administration module accepts existing keys; it does not generate
keys, assign authority, change approval states or publish records:

```text
python -m canvas_bridge.approval_admin seal-evidence --input PRIVATE_CORRESPONDENCE --key-file ADMIN_EVIDENCE_KEY --evidence-root PRIVATE_EVIDENCE_DIRECTORY
python -m canvas_bridge.approval_admin sign-record --input REVIEWED_RECORD_JSON --key-file ADMIN_ED25519_PRIVATE_KEY --key-id ADMIN_KEY_ID --output SIGNED_RECORD_JSON
```

Both keys use raw 32-byte files. Evidence uses AES-256-GCM with authenticated
context `canvas-approval-v1`; the command prints only its ciphertext-envelope
digest. Put that digest in `evidence_sha256`. The evidence filename is
`<digest>.sealed`. The service validates the signature, delegation, evidence
envelope and ciphertext digest without decrypting or exposing correspondence.
An authorized administrator combines the signed entries into the current bundle
and atomically replaces it in the protected location. Use an atomic replacement
for revocation as well. Missing/partially written/invalid files disable access;
there is no last-known-good approval cache. Secure backups, ACLs and rollback
protection for this trust root remain deployment/operator responsibilities.

## Enforcement paths

`Bridge.require_policy` is the shared policy entry point, alongside existing
`authorize_course_resource` user checks. The request context fixes the recipient
in trusted server code. Live MCP classifies a client as `chatgpt` only when its
verified token supplies an unambiguous `azp`/`client_id` matching the administrator's
`BRIDGE_MCP_CHATGPT_CLIENT_IDS` JSON list. No SDK default, model-supplied name or
missing claim identifies a recipient. Unknown clients fail sharing approval;
this client mapping by itself never grants approval. Tools cannot select a more
permissive recipient. Operators must independently verify the client registration
and restrict token issuance; a stolen bearer token remains an authentication risk.

`CanvasClient` defaults to rejecting an unbound live client. Its guarded transport
checks the actual endpoint before every network request, including `_get`,
pagination, retries and metadata probes. Extra syllabus/grade includes are
classified. File acquisition separately gates every storage redirect, with the
existing destination allowlist and credential-stripping rules preserved. Raw
`PublicTransport` sends without a matching authorized context are rejected before
DNS/network access. No scraping, alternate-domain, proxy or token fallback exists.

Linking and refresh require approval before token exchange; linking additionally
binds the profile lookup to the authenticated owner/generation. Identity-provider
JWKS and sign-in exchange use exact configured identity endpoints. Credential
revocation uses only the exact Canvas token DELETE endpoint so users can still
remove access. These infrastructure paths cannot read academic resources and do
not grant integration eligibility. Local deletion remains available.

MCP has a closed tool-to-category classification. Unclassified new tools deny.
Composite tools currently require conservative category supersets. All academic
tools, including cached plans, search, diagnostics, visuals and private download
payloads, check policy before running. Before returning any result, the request
fence rechecks user scope and reloads approvals for sharing. A swallowed policy
error still suppresses the response. Connection status redacts unapproved cached
course data and reports a safe policy decision. Local preference updates remain
available because they only return user-supplied input.

HTTP original-file redemption checks the `user_download` recipient before
response construction and before every body chunk. Settings exports check the
same recipient before and after preparing their data. Already transmitted bytes
cannot be retracted; denial stops further delivery. Offline calculations and
synthetic study workflows do not depend on live approvals.

Decisions expose a random decision ID, authority, state, reason code and allowed
boolean. Logs and MCP errors omit evidence, organization details, written
references, keys and credentials. The approval failure message tells the user
that live access/sharing is disabled and administrator review is needed. It does
not suggest refreshing a credential as a way to obtain upstream approval.

## Synthetic development and release boundary

Synthetic mode requires the synthetic institution and an injected HTTPX mock
transport for API and file acquisition. A synthetic profile alone cannot enable
real Canvas requests. Signed fixtures in tests are explicitly fictional and
never qualify a live deployment. Approved pilot configurations still need every
existing security, institution-registry and release prerequisite.

The [local validation record](../evidence/sanitized-results/authorization-policy-gateway-2026-10-25.md)
separates synthetic implementation checks from live approval and deployment.
No real authorization was obtained, no private operator configuration was edited,
and no running service was migrated or restarted for this implementation.

The subsequent [data egress gateway](data-egress-governance.md) adds signed recipient
environment and content-governance policy to sharing records. Integration approval
alone no longer enables academic output: live release also needs an exact verified
recipient environment and the applicable source/modality/content-hash review.
