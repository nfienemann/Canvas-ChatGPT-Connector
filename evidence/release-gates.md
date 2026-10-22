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
| G4 native Calendar interoperability | PASS actual read/proposal composition; writes untested | Actual ChatGPT used native Google Calendar reads plus a fresh Canvas workload and the deduplicated proposal tool; no create/update/delete executed |
| G5 operational ownership | PARTIAL local | PostgreSQL, migrations and logical recovery tested; hosting, budget, owner, offsite recovery and monitoring undecided |

Calendar writes and notifications are disabled. They do not block local reads,
but cannot be advertised as delivered. PDF/TXT/Markdown reading now has a verified
Windows AppContainer worker and a private actual-course PDF proof. DOCX/PPTX text extraction now shares that sandbox and passes synthetic OS-isolated
acceptance. A Linux Landlock/seccomp worker now has synthetic kernel and container
checks; actual Linux student reads and hosted deployment remain unverified.
OCR, visual interpretation and macOS parser workers remain unimplemented. Calendar proposals now compose with the existing native
connection; actual writes still require explicit event approval and read-back.

Additional gaps: comprehensive non-assignment obligations (classic quiz/topic and
dated Canvas calendar inventory and selected activity planning now have bounded tests; Canvas Planner API and group-child
coverage remain absent), advanced grade
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
writes were requested in this proof. Mobile and broader study workflows remain unverified. Calendar read/proposal
composition was subsequently verified; see the current validation record.
This does not change the hosted-pilot or public-distribution gates above.
# Original-file delivery gate — October 22, 2026

Original acquisition, private staging, authenticated/bearer HTTP redemption and
the optional MCP Apps download card now have synthetic implementation checks.
A private operator test against one authorized current workbook verified identical
reference, staged and HTTP-delivered bytes. This was an in-process HTTP test,
not a deployed MCP tool or ChatGPT client download. The available browser test
profile was signed out. A subsequent October 22 owner report confirms that the
browser fallback worked after selecting **Visit Site** on an ngrok interstitial;
the supplied screenshot confirms that warning page. This is user-reported private
success, with client/build and saved-byte verification unrecorded. Formal
web/desktop/mobile acceptance and native attachment remain unverified; see
[the verification record](sanitized-results/original-file-delivery.md) and
[the delivery contract](../docs/original-file-delivery.md).

The [C12-D01–C12-D06 public-release roadmap](implementation-tickets.md#public-release-download-roadmap--october-22-2026)
tracks removal of the development interstitial, capability-aware UI, native
attachment feasibility, private-link lifecycle, production availability and
client acceptance. D01/D02/D04/D05/D06 must pass for the applicable advertised
public download scope; D03 may remain explicitly deferred if native attachment
is not advertised. The owner accepts the current fallback for private use only.
This does not upgrade the broader gates above or authorize deployment.
