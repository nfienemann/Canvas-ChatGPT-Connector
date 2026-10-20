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

The desktop preview bundles everything it needs. Use the **Windows setup wizard**,
**macOS disk image**, or **Linux software-installer package** from
[Downloads](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases).
No Python, Git, terminal commands or model API keys are needed.

| Your computer | Local demo download |
|---|---|
| Windows 10/11, x64 | [Download the setup wizard](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases/download/demo-bb3e957b7e01/CanvasBridgeDemo-Windows-x64-Setup.exe) |
| Mac with Apple silicon, macOS 14+ | [Download the Mac app](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases/download/demo-bb3e957b7e01/CanvasBridgeDemo-macOS-arm64.dmg) |
| Mac with Intel, macOS 15+ | [Download the Intel Mac app](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases/download/demo-bb3e957b7e01/CanvasBridgeDemo-macOS-x64.dmg) |
| Ubuntu 22.04+ / compatible Debian, x64 | [Download the Linux package](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases/download/demo-bb3e957b7e01/CanvasBridgeDemo-Linux-x64.deb) |

Open **Canvas Bridge Demo → Set up local demo → Start local demo**. The launcher
opens the local settings page and includes a **Check study tools** button. It picks
an available port, keeps data in your user account, and stops when you close it.
Upgrades and uninstall preserve your separate data folder.

These packages are unsigned development previews; Windows/macOS may show publisher
warnings or block them. Signed Windows builds and Apple notarization remain gates
before general student distribution. No real institution or ChatGPT connection is
included. The future hosted student experience is intended to need **no install**:
connect in ChatGPT, sign in, and choose courses.

## Run from source (contributors only)

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

The initializer writes private, randomly generated test keys and a 24-hour test
token under `.local/`, plus an ignored `.env`. Run it again to renew the local
test token. Never use the synthetic issuer for live student data. The demo binds
only to loopback. Its SQLite database is an isolated development convenience;
live profiles require PostgreSQL.

## Available behavior

| Area | Implemented behavior |
|---|---|
| MCP | Official SDK, streamable HTTP, JWT audience/issuer/expiry/scope checks, OAuth resource discovery, bounded typed responses |
| Canvas reads | Reviewed GET routes, student-only course scope, effective assignment dates, own submission states, paginated reads, partial coverage |
| Planning | Explained priorities, bounded next actions, effort ranges, dependencies, busy times, pinned sessions, breaks/buffer and capacity shortfalls |
| Course knowledge | Modules, Canvas pages and authorized PDF/DOCX/PPTX/TXT/Markdown text; page citations, scoped indexed search and version-bound continuation |
| Grades | Own visible reported fields, deterministic supported Canvas/syllabus calculations and reconciliation; unsupported policy stays indeterminate |
| Local writes | Explicit version-checked preferences, personal progress and saved plans; no Canvas mutation |
| Lifecycle | Encrypted credentials, OAuth binding/refresh leases, disconnect and account-wide deletion, JSON export, leased jobs, retention, encrypted backup and deletion-fenced restore |
| Settings | Server-rendered authentication, course selection, timezone and privacy controls with CSRF protection |

PDF/TXT/Markdown reading is verified in the private Windows source deployment,
including an actual 15-page course paper returned through the installed connector.
It uses a network-isolated AppContainer worker and is disabled by default.
See [file reading](docs/file-reading.md) for tools, limits and deployment details.
DOCX sections and PPTX slides use the same isolated extraction path. Linux now
has a Landlock/seccomp worker and an unprivileged container verification suite;
see [Linux isolation](docs/linux-parser-isolation.md) for supported kernels and proof.
OCR, visual interpretation, macOS extraction, Calendar writes, automatic notifications, broad quiz/LTI
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
- [Tool contracts](docs/tool-contracts.md)
- [Original product specification](Codex_Spec.md)

Source publication was requested by the owner. An open-source license has not
been selected; see [license status](LICENSE-STATUS.md). No affiliation with
Instructure, Canvas, OpenAI or any university is implied.
