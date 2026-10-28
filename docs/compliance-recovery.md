# Compliance recovery and independent academic use (CB-09–CB-14)

This implementation separates service health, application identity, source authority,
and model sharing. Passing its tests grants no institutional, provider, or platform
approval. It does not repair a deployed database or change an account automatically.

## Source-aware operations

`source_authorization.py` classifies the actual registered MCP tools. The generated
compliance report includes their schemas, authorization dependencies, source types,
data classifications, network dependencies, read/write status, and widget references.
Missing classifications fail registration. Synthetic records are fictional; their
permissions do not apply to a personal or hosted deployment.

`get_local_study_preferences` and `update_local_study_preferences` use the existing
application principal and a strict timezone/week-start/break/buffer schema. They do
not need an institutional connection. No free-text academic content fits that schema.
The compatibility tool `get_saved_study_state` now defaults to preferences only and
selects only those rows. Set `include_institutional=true` to request saved plans and
progress; the existing provider, institution, user and egress gates then apply.
This is an intentional, restrictive response-contract change.

Institutional courses, work, snapshots, plans and materials retain their server-owned
owner/connection/course relationships. Local storage, a renamed file, an instruction
inside a document, and a successful prior read never grant new authority. Known
institutional document digests are retained as non-content restrictions for 91 days,
including after cache deletion and account deletion; logical backups may retain these
restrictions. This cannot identify every modified or previously unseen institutional
copy. Independent import therefore also requires an explicit content-rights statement;
it is not a way to self-certify upstream authorization.

## Independent browser imports

Sign in at the canonical `/settings` page and choose **Import independent documents**.
Upload PDF, DOCX, PPTX, TXT, Markdown, or XLSX (PPTX: 25 MB / 25,000,000 bytes;
other formats: 10 MB; at most 20 active imports). The offline `inspect-document`
CLI uses the same format-specific limits. These are local implementation limits;
installed-connector support requires separate deployment and client verification.
The authenticated browser streams a bounded body into memory with same-origin and
CSRF checks. It accepts bytes, never URLs or filesystem paths. Existing OS-isolated
parsers enforce their format, ZIP/XML, CPU, memory, network and temporary-file limits.
ChatGPT attachments are not automatically available to MCP; the user must import
the permitted material through this settings flow.

Each import has an opaque document ID, content hash, authenticated owner, independent
origin, content-rights attestation, privacy classification, allowed purposes, recipient
policy snapshot, expiration and deletion dependency. Raw bytes and extraction are
encrypted together using the existing vault. They expire within 24 hours (configurable
downward with `BRIDGE_INDEPENDENT_RETENTION_HOURS`). They are excluded from logical
and pre-upgrade backups. Local preferences expire 30 days after an explicit save.

The MCP surface is:

| Tool | Result |
|---|---|
| `list_local_documents` | Owned import IDs, hashes, format and expiry |
| `read_local_document` | Bounded excerpts, part locators, coverage and continuation |
| `search_local_documents` | Matching excerpts in one explicitly selected document |
| `get_local_document_status` | Extraction coverage, limitations and source identity |
| `prepare_local_study_materials` | Cited excerpts for ChatGPT to turn into notes or questions |
| `render_local_document_page` | Permitted PDF page image through native MCP image content |

The backend extracts and validates evidence; it does not claim to perform language-model
reasoning. Image delivery reports model visibility unknown, even when an ImageContent
block was sent. Independent Office documents currently provide text; independent pixel
delivery supports PDF only. Existing institution-bound slide tools retain their gates.

The operator must configure `BRIDGE_INDEPENDENT_EGRESS_FILE` outside the repository
using the strict `RecipientPolicy` schema. It identifies the exact signed application
issuer, client, environment and workspace, purposes, modalities, classifications,
retention and downstream processing. It is separate from institutional approval records.
Only an explicitly configured ChatGPT recipient without training is supported here.
Changing or removing the policy stops existing imports from sharing until they are
imported with new consent. No API or MCP argument can supply this policy.

The browser separately asks permission to share text and PDF page images. Page images
require the user to review the whole page for private information and content rights;
automatic text filtering does not prove image anonymity. A detected page-content
redaction blocks visual import. Ambiguous extraction privacy blocks import. Each output
passes the existing privacy and egress enforcement again. Unknown lineage, another
owner, expiry or deletion denies release. Browser-only confirmed deletion removes both
bytes and extraction and fences active workers; it cannot delete prior ChatGPT output.

## Startup and controlled recovery

Run `canvas-bridge doctor` first. It does not initialize a Bridge, acquire credentials,
call an LMS, create a database, regenerate a key or create a journal. It reports a
hashed `database_target`, installed and expected Alembic revisions, missing fields,
key readability/binding, journal integrity, service health and separate approval health.
Startup refuses an outdated schema or missing/unreadable security material. `/ready`
uses the same checks and never reports service readiness as external approval.

For an upgrade, stop the service and workers and copy the doctor target identifier:

```text
canvas-bridge deployment-upgrade --expected-target <doctor-target> --backup <private-exclusive-path.sealed>
```

This uses the configured database URL, verifies the existing vault against encrypted
records or its sealed deployment marker, verifies the journal, writes and decrypts an
exclusive encrypted snapshot, and only then invokes Alembic on that same database.
It checks the resulting schema again. The command never overwrites a backup or key.
Preserve the encrypted snapshot and existing key on failure; do not retry by replacing
security material. Coordinate exclusive downtime externally; the command does not
automatically terminate other processes or claim to enforce a fleet-wide maintenance lock.

For a genuinely empty database only, add `--new-installation`. Add `--create-key` only
when no key exists. Fresh bootstrap creates the journal and a sealed key/history marker.
`init-demo` refuses to repair an established installation with missing security material
or an outdated schema. It remains a synthetic setup command, not a production repair tool.

An established missing journal requires an independently retained original journal or
an explicit operator recovery decision:

```text
canvas-bridge recover-journal --expected-target <doctor-target> --acknowledge-history-loss
```

This refuses an existing journal, persists `unknown_after_explicit_recovery`, and creates
a new empty journal for subsequent events. It cannot reconstruct historical deletions.
Live-profile logical restore stays blocked when historical deletion assurance is unknown.
A legacy empty/recreated journal is also marked unknown during upgrade; passing an HMAC
check on an empty file does not prove historical continuity. There is deliberately no
automatic command to upgrade unknown history to verified history.

Pre-upgrade snapshots are encrypted operator recovery artifacts, may contain credentials,
expire by policy after 30 days, and have no automatic restore endpoint. Operators must
remove expired physical copies and perform schema-specific, revocation-aware recovery.
Logical application backups separately strip credentials and restore connections inactive.
No command claims physical erasure from host or immutable backups.

## Browser identity and authorization stages

Noncanonical GETs to `/settings` or `/settings/login` redirect to the configured origin
before state or cookies are created. Redirect destinations never come from request query
parameters or Host headers. Callbacks on another origin fail; codes are not forwarded.
State, issuer, exact redirect path, PKCE, secure cookies and single-use exchange remain
required. Safe reason codes distinguish missing/expired state, absent/mismatched browser
cookie, callback origin/redirect mismatch, issuer mismatch, failed exchange, and verified
token rejection (including personal owner-subject mismatch). Raw tokens, state values,
authorization codes and subject values are never included in these explanations.

Settings display independent stages for provider approval, institution approval, sharing
approval, deployment configuration, OAuth client configuration, upstream identity,
credential status and course selection. A link action is offered only when the configured
approved path passes those prerequisites. Signing in to Bridge does not establish any
upstream permission; email equality does not establish the personal owner identity.

`BRIDGE_CAPABILITY_PROFILE=offline_research` blocks institutional access while imports
and preferences work. `institutional_pilot` retains all existing approval and scope gates
and also requires explicit live enablement. `public_connected` remains fail-closed until
the public release process is implemented and approved; selecting the value is no grant.
The default remains `institutional_pilot` for compatibility, with live enablement false.
Non-synthetic application identity still requires HTTPS and PostgreSQL, including when
using independent content without an LMS connection.

## Reproducible acceptance and remaining evidence

October 26, 2026 local import-limit validation: 115 tests passed across
`tests/test_local_import_limits.py`, `tests/test_recovery_independence.py`,
`tests/test_provider_architecture.py` and `tests/test_presentation_reading.py`.
Synthetic browser streaming and CLI tests accept a 25,000,000-byte PPTX and reject
25,000,001 bytes; other formats retain their 10 MB ceiling. Existing real Windows
AppContainer PPTX extraction checks also passed. Targeted Ruff lint/format checks
and `git diff --check` passed. This is local source validation, not deployment or
installed-connector acceptance; the full repository suite was not rerun.

```text
python -m pytest tests/test_recovery_independence.py tests/test_deployment_recovery.py tests/test_recovery_identity.py -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/recovery-input/tests.json
canvas-bridge compliance-report --category offline_core --results .local/recovery-input/tests.json --output .local/recovery-review
```

The fixtures use fictional records, signed test identities and no real institution.
They demonstrate blocked institutional tools, usable independent reading/search/study
evidence/preferences, restricted cached plans, deletion/expiry, prompt injection, consent
revocation, real local MCP image transport and Windows AppContainer rendering. PostgreSQL
upgrade checks require an explicitly configured disposable `TEST_DATABASE_URL`.

The report's operational-regression entries become TESTED only from passing, current,
source-bound test receipts. Shared-checkout changes make receipts stale. Incident history,
the actual deployment database, private owner mapping, and installed ChatGPT widget
behavior remain separate operator/client reviews. An offline test cannot satisfy a pilot
approval gate. This document does not claim production recovery, client certification,
or permission to contact Rowan or another institution.
