# Platform compatibility

| Surface | Evidence | Claim |
|---|---|---|
| Official Python MCP client → local HTTP server | SDK 1.30.0; protocol 2025-11-25 negotiated in executable check | Verified locally with synthetic records |
| Auth metadata / missing-token challenge | HTTP contract tests | Verified fixture contract |
| Resource JWT checks | Valid/invalid issuer, audience, expiry, scope and key-cache tests | Verified fixture boundary |
| Settings in Codex in-app browser | Keyboard sign-in, labels and narrow viewport visually inspected | Partial browser usability evidence |
| Ordinary ChatGPT conversation | Not exercised | Not verified |
| Private first-read catalog | Eleven reading/planning tools; three saved-state writes omitted by configuration | Fixture-tested; actual ChatGPT account discovery pending |
| ChatGPT + native Calendar composition | No live configuration | Not verified |
| iOS / Android ChatGPT | Not exercised | Not supported claim |
| Public Directory install | Policy/authorization unresolved | Blocked |
| Docker clean deployment | Template supplied; no Docker runtime on development host | Not run |
| Native Windows Python / PostgreSQL | Python 3.14.5; PostgreSQL 17.11; migrations and tests executed | Verified synthetic development |

The [official MCP server guidance](https://developers.openai.com/plugins/build/mcp-server)
supports domain tools with typed schemas and authentication. A working MCP server
alone does not establish any of the client-specific claims above.
