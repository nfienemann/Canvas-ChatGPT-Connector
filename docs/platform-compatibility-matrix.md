# Platform compatibility

| Surface | Evidence | Claim |
|---|---|---|
| Official Python MCP client → local HTTP server | SDK 1.30.0; protocol 2025-11-25 negotiated in executable check | Verified locally with synthetic records |
| Official Python MCP client → private HTTPS service → Rowan | WorkOS owner sign-in; encrypted operator token; selected-course workload returned successfully through ngrok | Verified private operator read |
| Auth metadata / missing-token challenge | HTTP contract tests | Verified fixture contract |
| Resource JWT checks | Valid/invalid issuer, audience, expiry, scope and key-cache tests | Verified fixture boundary |
| Settings in Codex in-app browser | Keyboard sign-in, labels and narrow viewport visually inspected | Partial browser usability evidence |
| Actual ChatGPT Pro conversation with installed private plugin | Connection status, course listing and workload calls completed; response included Canvas links, local deadlines, submission states and coverage limits | Verified owner-only first read on 2026-10-20; broader workflows and other client surfaces remain untested |
| Private first-read catalog | Eleven reading/planning tools; three saved-state writes omitted by configuration | Catalog verified with official MCP client; three read tools exercised by actual ChatGPT |
| ChatGPT + native Calendar composition | No live configuration | Not verified |
| iOS / Android ChatGPT | Not exercised | Not supported claim |
| Public Directory install | Policy/authorization unresolved | Blocked |
| Docker clean deployment | Template supplied; no Docker runtime on development host | Not run |
| Native Windows Python / PostgreSQL | Python 3.14.5; PostgreSQL 17.11; migrations and tests executed | Verified synthetic development |

The [official MCP server guidance](https://developers.openai.com/plugins/build/mcp-server)
supports domain tools with typed schemas and authentication. A working MCP server
alone does not establish any of the client-specific claims above.
