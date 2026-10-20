# ADR 0001: one service, explicit boundaries

Status: accepted for local development, 2026-10-20.

The initially empty repository uses Python 3.14, the official `mcp` SDK,
Pydantic, HTTPX/httpcore, SQLAlchemy/Alembic and PostgreSQL. Exact dependency
versions are locked. SQLite is allowed only in isolated synthetic experiments.

There is one modular service and one worker entry point. There is no LLM call,
embedding service, custom conversation UI or subscription code.
Academic operations use an enum of reviewed Canvas GET routes. Authorization
token exchange/revocation is a separate component.

Issuer plus subject determines the connector principal. Neither email nor a
Canvas token is accepted as connector identity. A configured external OAuth
authorization server owns login, PKCE and client registration. Browser settings
use a separate PKCE client with server-side sessions; the MCP host has its own
client registration.

Every repository lookup includes owner and connection. The initial implementation
uses application authorization, not database row-level security. Workers verify
job owner, connection state and deletion epoch even when their database role
could read every row. PostgreSQL tests exercise pooled connections and competing
local writes. RLS could be added as defense in depth after independent tests.

AES-GCM binds encrypted credentials to owner and connection. The deployment must
mount its 32-byte key from managed secrets. Database encryption is not a substitute
for controlling this key. Synthetic keys are generated locally and ignored by Git.

The HTTP transport validates DNS addresses and connects to the validated numeric
IP while preserving the original TLS hostname. Pagination cannot alter route,
origin or immutable query parameters. API redirects are rejected. No generic
file/URL tool or cross-origin credential forwarding exists. An internal file
transport accepts only a course ID and file ID, obtains fresh course-qualified
metadata, and validates every redirect against exact operator-reviewed HTTPS
origins. It uses a separate HTTP session, sends a bearer only on the first
reviewed Canvas download route, and bounds transfer size and total elapsed time.
MCP file retrieval uses this transport, then passes only document bytes and a
format identifier into a credential-free Windows AppContainer worker. No network
capabilities, inherited handles or service configuration enter the worker.
Job Objects enforce memory, CPU, wall time and one-process limits. Unsupported
platforms fail closed. See the separately verified [file boundary](../file-reading.md).

Canvas reported dates are used in the authenticated context. Broader override
arrays are not interpreted. Staff/mixed-role courses are excluded until a safe
student-view contract is proved. Workload scope currently covers assignments;
syllabus-only obligations and independent discussion sub-deadlines remain gaps.

Plans are stateless proposals unless explicitly saved. Local writes require
`preferences:write` and compare-and-set versions. Calendar writes and notifications
are disabled, so no model-supplied approval Boolean can authorize them.

Known production gaps: institution-wide/fleet quotas, hosted parser sandbox,
managed key rotation, comprehensive course inventory, real-client evaluations,
reviewed retention/region/operator decisions, live browser/Canvas OAuth proof,
and public distribution eligibility. They are tracked rather than hidden.
