# Canvas Bridge

Canvas-read-only academic tools for ordinary ChatGPT conversations.
ChatGPT handles conversation; this service supplies authorized facts, provenance,
coverage and deterministic planning. No model API key, second chatbot, academic
dashboard or student subscription is required.

**Current status: private personal integration verified.** The owner connected
their own Rowan account and completed a live coursework read in ChatGPT Pro using
the installed Canvas Bridge Personal plugin. Public downloads remain synthetic
desktop previews. Institutional OAuth onboarding, general student distribution and a
ChatGPT Directory listing are not approved or delivered.

An operator-only personal testing path is implemented and tested. It
restricts access to one configured identity and verifies the expected Canvas
user before storing an encrypted credential. It is separate from the desktop
demo and from student OAuth onboarding. See the private developer proof section
of the [operator guide](docs/operator-guide.md) and the
[platform evidence](docs/platform-compatibility-matrix.md). The private proof
covers selected-course assignment reads; it does not establish complete Canvas
coverage or general availability. Credentials and academic records stay outside
the repository.

## Try the local demonstration

The Windows x64 setup wizard bundles its runtime and offers separate **Offline
academic intelligence** and **Synthetic demonstration** editions. Open Canvas
Bridge Demo, choose an edition, review data use, then select **Check and set up**.
Setup must complete a fictional academic task before it reports success. No terminal,
Python installation, API token, manual server configuration or administrator access
is required. Local data removal is an explicit option during uninstall.

The new onboarding build is a local development preview; it has not been published.
[Earlier downloads](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases)
are historical packages and do not establish support for this wizard. Current
release support targets Windows 10/11 x64. macOS and Linux are experimental only.
Publisher signing and nontechnical participant testing remain release gates.

Institutional integration uses a separately approved hosted service. The local
wizard cannot grant approvals and includes no approved service by default. The
future hosted student experience remains installation-free. See
[desktop setup, updates and deletion](docs/desktop-distribution.md) and the
[onboarding acceptance record](evidence/sanitized-results/onboarding-2026-10-26.md).

## Run from source (contributors only)

The [17 academic process workflows](docs/process-specifications/implementation.md)
add evidence reconciliation, local state recovery, planning, degree projections and
privacy controls behind `BRIDGE_PROCESS_FEATURES_ENABLED=false`. Their implementation
and synthetic tests are separate from activation and installed-client acceptance.

Install Python 3.14 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```console
uv sync --frozen
uv run canvas-bridge init-demo
uv run canvas-bridge serve
```

On Windows, `.\Start-LocalDemo.ps1` runs those steps and also supports an
installation of uv through `python -m pip install uv` when `uv` is not on PATH.

Open [connection settings](http://127.0.0.1:8000/settings). The clearly labeled
synthetic sign-in opens fictional course selection and privacy controls.
In another terminal:

```console
uv run canvas-bridge doctor
uv run canvas-bridge verify-read
```

`verify-read` uses the official MCP client over HTTP to authenticate, retrieve
fictional coursework and request a study recommendation. It does **not** prove
that a ChatGPT account or university has been connected.

The initializer writes private, randomly generated test keys and a one-hour test
token under `.local/`, plus an ignored `.env`. Run it again to renew the local
test token. Never use the synthetic issuer for live student data. The demo binds
only to loopback. Its SQLite database is an isolated development convenience;
live profiles require PostgreSQL.

## Available behavior

Contributors can generate a sanitized security review package with
`uv run canvas-bridge compliance-report`. See the [evidence workflow](docs/compliance-evidence.md)
for execution receipts, control/approval registers, reviewer walkthroughs and
separate release gates. Successful report generation is not release approval.

The first [provider-independent architecture milestone](docs/provider-architecture.md)
extracts grade calculation and local document text processing. Contributors can run
`uv run canvas-academic demo-grade` without Canvas credentials, account setup or LMS
requests. Live adapters retain the existing approval gates; other workflows migrate
incrementally as described in the architecture guide.

The [provider and extension SDK](docs/provider-extension-sdk.md) adds versioned
capability discovery and bounded declarative modules. Try
`uv run canvas-academic demo-forecast --future-points 100 --future-percent 90`.
Permitted local numeric imports use the same forecast without an LMS connection;
extension registration never grants provider or downstream sharing permission.

| Area | Implemented behavior |
|---|---|
| MCP | Official SDK, streamable HTTP, JWT audience/issuer/expiry/scope checks, OAuth resource discovery, bounded typed responses |
| Canvas reads | Reviewed GET routes, student-only course scope, effective assignment dates, own submission states, paginated reads, partial coverage |
| Planning | Explained priorities, bounded next actions, effort ranges, dependencies, busy times, pinned sessions, breaks/buffer and capacity shortfalls; [selected course activity planning](docs/activity-study-planning.md) includes quizzes, discussions and event preparation |
| Course knowledge | Modules, Canvas pages and authorized PDF/DOCX/PPTX/TXT/Markdown text; page citations, [bounded unread-document search](docs/document-search.md) and version-bound continuation |
| Grades | Own visible reported fields, deterministic supported Canvas/syllabus calculations and reconciliation; unsupported policy stays indeterminate |
| Local writes | Explicit version-checked preferences, personal progress and saved plans; no Canvas mutation |
| Lifecycle | Encrypted credentials and academic fields, bounded retention, encrypted temporary downloads, worker cleanup, expiring backups and inactive credential-free restores |
| Settings | Server-rendered authentication, course selection, stored-data inventory, confirmed cache/record deletion, disconnect and account deletion with CSRF protection |

PDF/TXT/Markdown reading is verified in the private Windows source deployment,
including an actual 15-page course paper returned through the installed connector.
It uses a network-isolated AppContainer worker and is disabled by default.
See [file reading](docs/file-reading.md) for tools, limits and deployment details.
DOCX sections and PPTX slides use the same isolated extraction path. Linux now
has a Landlock/seccomp worker and an unprivileged container verification suite;
see [Linux isolation](docs/linux-parser-isolation.md) for supported kernels and proof.
Bounded English OCR now makes image-only PDF text searchable with explicit
uncertainty. Page-image MCP responses are implemented, but the tested native
ChatGPT surface did not expose pixels for model inspection; see
[visual PDF reading](docs/visual-pdf-reading.md) for the partial acceptance result.
Verified visual interpretation, macOS extraction, Calendar writes, automatic notifications, broad quiz/LTI
ingestion, public onboarding and unsupported grade policies are not advertised.

See [academic intelligence](docs/academic-intelligence.md) for deadline reconciliation,
requirements conflicts, assessment preparation, evidence-based priorities, native
Calendar proposals and integrated course audits, including acceptance boundaries.

## Verify

```console
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pip-audit --local
```

PostgreSQL tests require `TEST_DATABASE_URL` in a private environment variable
pointing to a **disposable test database**. They create random schemas, test
migration/rollback and concurrency, and remove those schemas afterward.
Without that variable they are explicitly skipped. CI supplies PostgreSQL.

See [recorded checks](evidence/sanitized-results/verification.md),
[requirement ledger](evidence/requirements.yaml), and
[release gates](evidence/release-gates.md) for the precise verified scope.

## Deployment and release

The [operator guide](docs/operator-guide.md) documents migrations, secrets,
the Compose template, identity-provider configuration and restore procedures.
A hosted deployment needs approved institution OAuth configuration, an established
identity provider, stable HTTPS, reviewed privacy arrangements and operational
ownership. It is not safe to turn the demo into a public service by exposing its port.

OpenAI currently excludes plugins that primarily function as unofficial third-party
connectors from Directory approval. Eligibility remains an explicit release gate;
this repository is not evidence of approval. See the
[distribution review](docs/distribution-review.md).

- [Student guide](docs/student-guide.md)
- [Institution administrator guide](docs/institution-admin-guide.md)
- [Contributor guide](docs/contributor-guide.md)
- [Threat model](docs/threat-model.md)
- [Privacy and retention](docs/data-flow-retention.md)
- [Data lifecycle controls and storage inventory](docs/data-lifecycle-controls.md)
- [Third-party privacy pipeline and limits](docs/third-party-privacy.md)
- [Tool contracts](docs/tool-contracts.md)
- [Original product specification](Codex_Spec.md)

Source publication was requested by the owner. An open-source license has not
been selected; see [license status](LICENSE-STATUS.md). No affiliation with
Instructure, Canvas, OpenAI or any university is implied.

## Discussion participation (local synthetic verification)

Read-only discussion discovery, prompts and self-participation evidence are now
available through three dedicated tools and the existing optional course audit
and obligation flows. Partial coverage never establishes nonparticipation.
Group participation and peer-thread disclosure remain unavailable; external live
approval gates remain intact. See [the contract and status matrix](docs/discussion-reading.md).

## Academic benchmark laboratory

The [offline benchmark lab](docs/academic-benchmark-lab.md) exercises 12 fictional
courses with independently checkable gold answers, per-category measurements,
failure capsules and CI regression gates. It adds no MCP tools. Model/alternative
comparisons require actual execution evidence; interpretive rubrics remain pending
independent expert review. Run `python -m canvas_bridge.benchmark_lab run --tier fast`.

## Unified academic evidence

The [versioned evidence graph](docs/academic-evidence-graph.md) connects deadline
and grading assertions to permitted sources, keeps conflicts and uncertainty
visible, and tracks source-dependent invalidation. Existing tools consume the
model. Historical comparisons require an authorized in-memory session; no
automatic durable grade history or new Canvas access is introduced.

## Scientific document evidence

[Scientific comprehension v3](docs/scientific-document-comprehension-v3.md) adds
source-bound document structure, original-slide figure retrieval and separately
attributed visual/textual explanations to existing tools. Ten fictional scientific
fixtures have a deterministic retrieval gate; interpretation stays unscored until
independent expert review. Word/Excel visual rendering and deployed host acceptance
remain explicit gaps. Run `python -m canvas_bridge.scientific_benchmark`.

## Semester intelligence

The [independent academic path](docs/independent-academic-intelligence.md) supports
permitted local planning, assessment evidence, requirement comparison, grades,
deadlines and calendar proposals without an LMS connection. Local-only saved
preferences remain readable after disconnect; institutional records keep their gates.

The [academic workflow engine](docs/academic-workflows.md) provides seven bounded
read-only sequences with shared evidence, capability negotiation, explicit partial
results and existing calendar proposals. [Cross-course study](docs/cross-course-study.md)
adds source-specific concepts, labeled generated practice and voluntary local outcomes.
Missing sources remain unknown; neither feature starts monitoring or infers mastery.

The [semester overview](docs/semester-intelligence.md) combines selected courses into
cited obligations, consequential changes, grade uncertainties and explainable
priorities. Stable findings support explicit acknowledgment and user-controlled
planning preferences. Analysis is on demand; notification preferences do not start
monitoring. A future delivery adapter still requires explicit opt-in and an approved
host schedule. Run `python -m pytest tests/test_semester_intelligence.py -q`.
