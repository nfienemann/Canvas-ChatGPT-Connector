# Release gates

Local development and repository upload are authorized. The owner explicitly
confirmed that no Canvas OAuth/hosting setup exists and requested local tests
first. The local build is not the specification's live pilot acceptance.

| Gate | State | Evidence / required next proof |
|---|---|---|
| G0 actual ChatGPT path | BLOCKED external setup | Official-client HTTP calls pass; ordinary ChatGPT conversation not tested |
| G1 institutional access | BLOCKED external access | Candidate registry only; institution-approved key/scopes and student comparison needed |
| G2 public eligibility | UNRESOLVED | Current unofficial-connector restriction reviewed; documented acceptable path needed |
| G3 security/privacy suitability | PARTIAL synthetic | Isolation/network/lifecycle fixtures pass; independent review and actual privacy arrangement needed |
| G4 native Calendar interoperability | NOT TESTED | Separate Calendar capability and actual ChatGPT composition required |
| G5 operational ownership | PARTIAL local | PostgreSQL, migrations and logical recovery tested; hosting, budget, owner, offsite recovery and monitoring undecided |

Calendar writes and notifications are disabled. They do not block local reads,
but cannot be advertised as delivered. Binary parsing is limited to synthetic
primitives until a credential-free, network-isolated worker is verified.

Additional gaps: comprehensive non-assignment obligations, advanced grade
policies, full account-wide deletion, fleet quotas,
production key rotation, real mobile/screen-reader tests and license adoption.
The requirement ledger records these separately from code/test existence.

No purchase, institutional application, public service deployment, message,
live student-account action or directory submission occurred.
