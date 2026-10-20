# Release gates

Local development and repository upload are authorized. The owner explicitly
confirmed that no Canvas OAuth/hosting setup exists and requested local tests
first. The local build is not the specification's live pilot acceptance.

| Gate | State | Evidence / required next proof |
|---|---|---|
| G0 actual ChatGPT path | PASS private first-read proof; broader pilot pending | Installed plugin in the owner's ChatGPT Pro account invoked connection status, course list and workload tools; returned selected-course deadlines with Canvas links and coverage limits |
| G1 institutional access | BLOCKED external access | Candidate registry only; institution-approved key/scopes and student comparison needed |
| G2 public eligibility | UNRESOLVED | Current unofficial-connector restriction reviewed; documented acceptable path needed |
| G3 security/privacy suitability | PARTIAL synthetic | Isolation/network/lifecycle fixtures pass; independent review and actual privacy arrangement needed |
| G4 native Calendar interoperability | NOT TESTED | Separate Calendar capability and actual ChatGPT composition required |
| G5 operational ownership | PARTIAL local | PostgreSQL, migrations and logical recovery tested; hosting, budget, owner, offsite recovery and monitoring undecided |

Calendar writes and notifications are disabled. They do not block local reads,
but cannot be advertised as delivered. Binary parsing is limited to synthetic
primitives until a credential-free, network-isolated worker is verified.

Additional gaps: comprehensive non-assignment obligations, advanced grade
policies, fleet quotas,
production key rotation, real mobile/screen-reader tests and license adoption.
Desktop previews also require Windows publisher signing, Apple Developer ID
notarization and fresh consumer-OS accessibility/trust checks before general
student distribution. Native package tests do not establish those approvals.
The requirement ledger records these separately from code/test existence.

No purchase, institutional application, multi-user deployment, outbound message
or directory submission occurred. A private owner-only service is reachable over
HTTPS and has read the owner's selected coursework with explicit authorization.

The owner subsequently selected Rowan and ChatGPT Pro for a private first test
using their own coursework. Operator-only token setup and a configurable
read-only MCP catalog are implemented and tested with fictional records. A
private operator proof now verifies WorkOS sign-in, an exact owner restriction,
an ngrok HTTPS connection with local inspection disabled, encrypted Canvas token
storage, explicit course selection and a live workload read through the official
MCP client. The installed private plugin also completed a live ChatGPT Pro
conversation using connection status, course listing and workload tools. The
response distinguished submitted work, converted deadlines to the selected time
zone, linked to Canvas and stated assignment-only coverage limits. No grades or
writes were requested in this proof. Mobile, Calendar composition and broader
study workflows remain unverified in actual ChatGPT.
This does not change the hosted-pilot or public-distribution gates above.
