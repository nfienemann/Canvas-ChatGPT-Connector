# Provider-neutral academic architecture

Implementation milestone: 2026-10-25. This is the first incremental extraction,
covering grade calculation and a local-document text path. It is not a claim that
all existing tools have been migrated or that any new live provider is approved.

The October 28 [authorization decoupling repair](independent-academic-intelligence.md)
adds source-bound independent MCP workflows for planning, assessment evidence,
requirements, grade scenarios, deadlines and calendar proposals. Its current audit
updates the historical migration map below. Institutional acquisition remains gated.

## Boundary

```text
Trusted host identity and source-specific permission
  -> provider adapter (authorization before retrieval)
  -> academic-1 normalized records with provenance and restrictions
  -> authorization/privacy/recipient checks and an in-process input receipt
  -> credential-free academic service
  -> permission recheck and permitted output
  -> existing MCP privacy/egress serializer, when used by MCP
```

`academic/grade_engine.py` contains the existing Decimal arithmetic. It imports
no provider, network client, database or credentials. `academic/services.py`
consumes versioned records through `AcademicGateway`; it cannot retrieve more
data. The existing grade MCP workflow now normalizes its authorized evidence
before invoking this service. Canvas retrieval and normalization are in
`providers/canvas_grades.py` and `providers/canvas.py`. Syllabus document discovery
in the legacy grade orchestration is a later migration step.

`grading_engine.py` retains legacy names, the `canvas` policy-basis label and
comparison output vocabulary. Those labels are compatibility metadata, never
authorization. The raw arithmetic kernel remains usable for numerical unit tests;
it has no ability to obtain provider data or release a result through MCP. The
public academic service requires a current, intact authorization receipt.

## Versioned data contract

`academic/models.py` defines immutable, extra-field-rejecting `academic-1` types:

| Type | Meaning and retained uncertainty |
|---|---|
| Course | Provider-independent reference, supplied title and optional timezone |
| Assignment | Course reference, deadline, submission state and optional effort |
| Deadline | Timestamp, local date, known absence, unsupported, denied or not returned; no invented time/timezone |
| GradeCategory | Category membership, optional weight and explicit supported drop rules |
| GradeResult | Posted/ungraded/unavailable/excused/conflicting; a non-posted state cannot carry a visible score |
| Assessment | Course/category reference, possible points, grade result, explicit eligibility and exclusion evidence |
| CourseCalendarEvent | Supplied start/end and unknown-or-explicit attendance requirement |
| AcademicDocument | Content hash, format, optional course and bounded parts |
| DocumentPart | Actual PDF page, slide, Word/text section or worksheet number, extraction status and text; visual interpretation is explicitly not performed |
| SourceReference | Provider namespace, source ID/version, optional supplied URI/locator; reasoning never manufactures a source URL |
| PermissionContext | Trusted principal/tenant/connection, permitted scope, decision reference and expiration **description** |
| Provenance / Restrictions | Observation/verification/freshness, completeness, derivation and uncertainty; privacy classes, copyright status, purpose and recipient limits |

Record identifiers are opaque strings, not Canvas numeric IDs. Nested Deadline
and GradeResult facts inherit the enclosing record's provenance and restrictions.
All document parts must preserve their parent's permission and restrictions.
Cross-course category references and unsupported schema versions are rejected.
Observed versions may be content hashes of normalized evidence; they are not
represented as official provider revisions. Missing upstream versions use an
explicit `not-returned` marker. Fictional and user-supplied sources have no claimed
institutional verification timestamp.

PermissionContext JSON is not evidence of approval. A model cannot submit one to
grant itself access. `AuthorizedInput` is an internal, non-serialized receipt
bound by a per-gateway ephemeral HMAC to the exact dataset and trusted request.
Mutation, recipient/identity substitution, cross-gateway reuse, expiration and
revocation are rejected. It is neither an application access token nor a provider
credential. Adapters are scoped to one request/analysis; do not register a shared
singleton containing multiple users' mutable source state.

The gateway checks classifications, scope, freshness bounds, privacy findings and
source references before analysis. Unknown, third-party educational, restricted
assessment and confidential-research classifications fail closed. Derivation does
not clear labels. Canvas normalization includes the classifications resolved by
the existing content-governance engine and rechecks later changes, including for
local analysis. For an external recipient, the existing egress engine runs before
the new service and the established final MCP fences still run afterwards.

## Adapters and distribution configurations

The internal interface advertises `list_courses`, `get_assignments`,
`get_grade_summary`, `get_schedule`, `get_authorized_document` and
`get_source_capabilities`. These do not add public MCP tools. Unsupported methods
return an explicit unsupported result; an empty invented schedule is not returned.

| Adapter / configuration | Implemented behavior | Authorization boundary |
|---|---|---|
| `providers.synthetic.SyntheticProvider` / synthetic demonstration | Fixed fictional course, assignment and grades; no HTTP-shaped data, account, token or environment startup | Closed fixture data only; arbitrary records cannot be loaded by a demo flag |
| `LocalDocumentProvider` / offline academic utility | UTF-8 text/Markdown; PDF, DOCX, PPTX and XLSX text through the existing isolated worker; PPTX up to 25 MB (25,000,000 bytes), other formats up to 10 MB | Trusted local host supplies bytes plus an explicit, expiring ownership attestation bound to the content hash and user; local recipient only; no model-callable upload/approval or arbitrary file fetcher |
| `AuthorizedCanvasProvider` / approved integration | Grade-summary capability and the existing grade MCP calculation path | Existing Bridge principal, connection, course/epoch, OAuth scope, signed provider/institution approvals and content/recipient policies; credentials and adapter availability never establish approval |
| `FutureApprovedMCPProvider` / reserved platform integration | Capability discovery reports unsupported; all retrieval/helper paths deny | No client, endpoint, token exchange, data-shape assumption or enable flag. A future adapter needs its own independently reviewed provider/institution/downstream permission implementation |

The existing MCP synthetic deployment remains available and uses its fictional
transport/account fixtures for application-protocol tests. The new standalone
synthetic path demonstrates that the reasoning engine itself does not require
that Canvas-shaped transport or institution-controlled accounts.

Use the installed `canvas-academic` entry point, or directly:

```powershell
python -m canvas_bridge.academic.cli demo-grade
python -m canvas_bridge.academic.cli capabilities
python -m canvas_bridge.academic.cli inspect-document .\my-own-notes.txt --acknowledge-own-material
```

The local-document flag records explicit user ownership attestation for **local
processing**. It does not verify copyright, institutional approval or permission
to send content to ChatGPT. Materials with uncertain ownership need the relevant
permission before import. The adapter rejects external recipients even if the
caller supplies such a flag. Privacy inspection is bounded and is not proof of
anonymity or factual ownership. PDF/slide text is not visual interpretation.

The offline CLI reads a bounded regular file only at the explicit console user's
path, does not load `.env` or `BRIDGE_*` configuration, and creates no Bridge,
database, vault or authentication system. Its temporary worker directory and
in-memory permit/bytes are cleared when processing ends. It is an operator/local
utility, not a second chatbot or dashboard. Existing isolation support limits
still apply; unsupported platforms fail closed for binary parsing.

The wheel contains both configurations. A separate distribution is not necessary
to select the independent entry point. Dependency installation may require a
package registry; analysis itself makes no external LMS request.

## Incremental migration map

| Service | Current boundary | Next migration step |
|---|---|---|
| Grade calculation | Migrated: normalized, authorized input -> existing Decimal kernel | Additional provider-specific grade adapters after authorization/interface review |
| Grade audit / consistency | Existing math and MCP comparison contract preserved; calculations use new boundary | Move syllabus discovery and generic comparison vocabulary behind source adapters |
| Document text extraction | Shared isolated worker used by local-document adapter; restrictions/provenance retained | Authorized document adapters for other sources, without URL/file-system fetch tools |
| Assignment prioritization / study-plan generation | Existing deterministic `planning.py` remains unchanged and authorized by existing tool wrappers | Adapt normalized assignments/deadlines to planning inputs and preserve scheduling regressions |
| Workload / deadline interpretation / schedule reconciliation | Existing acquisition/orchestration retains its current authorization gates | Migrate one collector and its provenance contract at a time; do not claim account-wide coverage |
| PDF / slide interpretation | Existing scoped Canvas rendering remains; new local adapter exposes text only | Separate approved pixel delivery/visual coverage from extraction and reasoning |
| Calendar proposals | Existing pure proposal functions and confirmation contract remain | Map normalized events into proposals; no new calendar or Canvas write capability |

A future adapter must supply a trusted policy implementation and tests for
provider/tenant/recipient boundaries; reusing a source ID, MCP protocol or OAuth
credential is insufficient. It must not borrow Canvas approval records. Keep
capabilities unsupported until the actual interface, terms, data model and
downstream reuse permissions are known. Public distribution and real institutional
approval remain governed by [release gates](../evidence/release-gates.md).

The [provider and extension SDK v1](provider-extension-sdk.md) now adds explicit
semantic versions, field/permission/freshness/resource discovery, operation-bound
receipts and a restricted declarative extension interpreter. Its first module is
an aggregate points forecast shared by synthetic, permitted local numeric imports
and approved provider adapters. It does not introduce automatic provider loading,
native-code extensions or an external authorization grant.
