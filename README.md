# Canvas Bridge

Canvas-read-only academic tools for ordinary ChatGPT conversations.
ChatGPT handles conversation; this service supplies authorized facts, provenance,
coverage and deterministic planning. No model API key, second chatbot, academic
dashboard or student subscription is required.

**Current release: local synthetic development.** This repository contains a
working authenticated MCP service, not a live university integration or approved
ChatGPT Directory listing. The owner requested local construction and testing
first. No real Canvas account has been accessed.

## Run the local demonstration

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
| Course knowledge | Modules and Canvas pages, access-rechecked search of fetched pages, version-bound text continuation |
| Grades | Own visible reported fields; unknown policy stays unknown. Simple-points arithmetic is tested internally, not advertised as exact Canvas reconstruction |
| Local writes | Explicit version-checked preferences, personal progress and saved plans; no Canvas mutation |
| Lifecycle | Encrypted credentials, OAuth binding/refresh leases, disconnect and account-wide deletion, JSON export, leased jobs, retention, encrypted backup and deletion-fenced restore |
| Settings | Server-rendered authentication, course selection, timezone and privacy controls with CSRF protection |

Binary PDF/DOCX/PPTX parsers are bounded **synthetic-development primitives**.
Live binary retrieval remains disabled until a separately isolated worker is
verified. Calendar writes, automatic notifications, broad quiz/LTI ingestion,
public onboarding and exact course-grade scenarios are not advertised.

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
