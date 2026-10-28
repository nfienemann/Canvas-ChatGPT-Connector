# Release gates

## Academic integrity permissions (2026-10-28)

The [Academic Integrity Permission Engine](../docs/academic-integrity.md) adds
activity-specific decisions, authorized policy discovery, scoped uncertainty
acknowledgments and MCP evidence-release fencing. Controls `CB-INTEGRITY-01` through
`06` require executed synthetic receipts; file existence does not establish TESTED.
Source access, sharing permission and instructor permission remain independent.
The bounded English interpreter and institution-specific source authority need
independent review before public completion features. No live policy approval,
deployment, misconduct determination or general dishonesty-prevention claim is made.

## Provider portability and extension SDK (2026-10-26)

The [v1 SDK](../docs/provider-extension-sdk.md) adds explicit provider contracts,
operation-bound receipts and bounded declarative numeric extensions. Synthetic and
local grade forecasting remain independent of live LMS accounts. New providers
require independently reviewed authorization implementations; new projections and
module versions require review and compatibility tests. Arbitrary native-code
extensions are unsupported. No new external provider or publication is authorized.
Execution evidence is tracked by `CB-SDK-01` in the governance registry.

## Reproducible governance evidence (2026-10-25)

`canvas-bridge compliance-report` produces Markdown and strict JSON from the
[control/approval register](../governance/controls.json) and source-bound execution
receipts. Files alone never establish TESTED. See the
[reviewer workflow](../docs/compliance-evidence.md) and fifteen maintained templates.

Offline distribution, institutional pilot and public connected plugin have distinct
approval/manual-review gates. Missing approvals, licensing decisions, independent
reviews and operational evidence remain blocking even after successful code tests.
Requested public preview publication now enforces the offline gate in CI. No
existing artifact is certified retroactively, and no live authorization is created.

## Provider-neutral architecture milestone (2026-10-25)

Grade calculation now consumes the versioned academic model through an
authorization receipt; Canvas evidence acquisition is behind its grade adapter.
A token-free fictional demo and explicitly permitted local-document path run
without Canvas startup. The reserved future MCP provider always denies retrieval.
See [architecture and migration map](../docs/provider-architecture.md) and
[verification](sanitized-results/provider-architecture-2026-10-25.md).

This is an incremental milestone. Remaining planning/workload/calendar and
document-interpretation collectors keep their existing controls and are not
claimed as migrated. No additional provider interface, downstream reuse right,
institutional approval or public deployment is enabled by these changes.

## Security and supply chain prerequisite (2026-10-25)

The local P1 hardening adds shared outbound/ingress/principal admission, provider
cooldowns/circuits, total stream/request deadlines, a file-lock cleanup race fix,
the pypdf 6.21.2 security update, pinned build/scanner inputs, SBOM and blocking CI
checks. See [security verification](sanitized-results/security-hardening-2026-10-25.md),
[threat model](../docs/threat-model.md), [patch procedure](../docs/supply-chain-security.md)
and [incident runbook](../docs/runbooks/incidents.md).

External release still requires Linux image/configuration and kernel checks,
optional native-runtime/platform inventory and license review, independently
reviewed isolation, an appointed security/incident owner and private reporting
channel, edge TLS/timeouts/log redaction and aggregate quotas for any multi-process
deployment. A Windows synthetic suite, source SBOM or clean scanner result does
not satisfy those operational gates or the separate provider/institution approvals.

## External authorization prerequisite — October 25, 2026

The [authorization-policy gateway](../docs/authorization-policy-gateway.md) now
requires separate trusted provider, institutional and sharing approvals in
addition to authenticated user/resource permissions. Missing records disable
live retrieval and sharing, including cached MCP and original-download paths.
Synthetic development remains available. Credentials, prior private functional
proofs and the historical gates below do not establish these approvals.

**External approval status: NOT_ASSESSED by this implementation; live eligibility
is not established.** No real approval bundle was supplied or created. This is
local implementation work, not a deployment or a new authorization claim. See
the [synthetic validation record](sanitized-results/authorization-policy-gateway-2026-10-25.md).

## AI egress and content-governance prerequisite — October 25, 2026

The [data egress gateway](../docs/data-egress-governance.md) requires an exact,
administrator-reviewed recipient plan/workspace, authenticated environment
claims, content classification and applicable source/modality/byte-hash reviews
after ordinary access checks. Unknown content fails closed; text sanitization
does not establish permission for documents, images or originals. Live bearer
download links and unclassified aggregate exports are disabled. Authorized local
analysis and isolated synthetic academic tools remain available.

**Real recipient/content approval status: NOT_ASSESSED.** No actual approvals,
content-owner rights, processing contracts or identity-provider claim mappings
were established. This is local implementation only; it does not activate the
gateway in the running private service. See the
[synthetic validation record](sanitized-results/data-egress-governance-2026-10-25.md).
Earlier functional download/reader proofs below do not satisfy this new gate.

## Identity and OAuth prerequisite — October 25, 2026

The [identity hardening](../docs/identity-oauth-hardening.md) retains the existing
identity system and adds reviewed institution-specific OAuth capabilities,
restricted workflow scopes, refreshed-user verification, durable application
session revocation and temporary-file/job invalidation. Authentication remains
independent of all provider, institutional and data-sharing approvals.

**Live identity/OAuth acceptance remains unverified.** Activation requires
migration `8d21f4c932ab`, reviewed private institution capabilities, registration
of exact institution-bound callbacks and explicit reconnection/reverification of
credentials migrated as unverified. No private service, credentials, selection
or permissions were changed. The [synthetic validation record](sanitized-results/identity-oauth-hardening-2026-10-25.md)
does not establish institutional OAuth support or public distribution eligibility.

## Data lifecycle prerequisite — October 25, 2026

[Data lifecycle controls](../docs/data-lifecycle-controls.md) add encrypted
academic fields, central retention budgets, confirmed Settings deletion,
encrypted temporary downloads, worker cancellation/orphan recovery and expiring
backups that restore without active credentials. The
[synthetic validation record](sanitized-results/data-lifecycle-2026-10-25.md)
records checks and limitations.

**Deployment acceptance remains unverified.** Activation requires migration
`c7d9130b42ae` with the existing vault key and stopped workers, plus a synthetic
canary on the actual database/host. Downgrade to plaintext is blocked. No private
service was migrated or restarted. Encrypted processing volumes, disabled
sensitive host crash dumps, seven-day external logs, physical backup expiry,
independent current deletion journals, evidence-custodian disposal schedules and
host-loss recovery remain operator release gates. Local deletion does not prove
immediate physical erasure from disks, immutable backups or downstream services.
No provider/institution eligibility is changed by these controls.

## Prior functional and release evidence

Private whole-deck follow-up: [bounded EMF and acceptance record](sanitized-results/bounded-emf-2026-10-23.md).
The exact 54-slide fixture now passes text continuation and direct native-image
inspection in this Codex environment, including the requested slide and the
five-slide text/title-image control. Section-order parsing, narrow EMF support,
lossless PNG filtering and evidence-preserving diagnostics are deployed to the
restarted private service. Authorization and resource budgets remain unchanged.
The [earlier blocked record](sanitized-results/presentation-order-2026-10-23.md)
is historical. This result does not establish general metafile support,
universal clients or independent PowerPoint fidelity, and does not change the
public-distribution or hosted-pilot gates below.

PDF visual inspection v2: [contract and compatibility](../docs/visual-inspection-v2.md)
and [acceptance record](sanitized-results/visual-inspection-v2-2026-10-23.md).
Rendering/delivery/visibility/interpretation now have separate evidence states;
bounded figure candidates and attributed visual reports preserve the reader.
Actual pixels were observed through the existing connected renderer in Codex.
This does not establish ordinary ChatGPT client support or deployment of the new
tools. Keep the end-to-end ordinary ChatGPT visual gate pending its client test.

PPTX visual integration follow-up: [pipeline diagnosis and operator steps](../docs/pptx-visual-pipeline.md)
and [single-slide validation](sanitized-results/pptx-single-slide-2026-10-23.md), followed by
[installed-plugin activation](sanitized-results/pptx-installed-plugin-2026-10-23.md).
The live v8 extractor reads the 25-slide acceptance deck. The one-slide derivative
now converts and renders the real image-heavy acceptance slide in the unchanged
AppContainer; Codex inspected its pixels with original-slide provenance. Synthetic
hidden-slide, mapping, cache/auth and native footer-number checks pass. Rendering
is now enabled on the private server; restart and user-confirmed connector refresh
are complete. The installed plugin delivered actual pixels and original-slide
citations to this Codex conversation. The subsequent
[ChatGPT web reader-button test](sanitized-results/pptx-web-reader-2026-10-23.md)
passed: the model received the image, explained visible content, cited original
Slide 14 and acknowledged unreadable overlap. This closes that private functional
gate for one slide. The web host's existing development CSP/origin-check bypass
was not changed; normal client enforcement, broader visual coverage and public
release remain unverified.

PPTX v8 local work is recorded in [the October 22 analysis record](sanitized-results/pptx-analysis-2026-10-22.md).
Large synthetic extraction is verified separately from live-service acceptance.
The installed connector reproduced the former 10 MB refusal; no deployment is
claimed by that historical record. Its native-timeout statements are superseded
by the October 23 single-slide result above. Only one actual slide has been
visually inspected; whole-lecture visual coverage has not been established.

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
Bounded English OCR and PDF page rendering have synthetic checks and private
evidence in the [PDF investigation](sanitized-results/pdf-processing-2026-10-22.md).
Complete visual interpretation and macOS parser workers remain unimplemented.
The [cross-format stress record](sanitized-results/document-stress-2026-10-22.md)
tracks DOCX/XLSX/PDF parser-v7 fixes separately from installed-service acceptance.
Calendar proposals now compose with the existing native
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

**Budget decision — October 22, 2026:** The owner is retaining the current browser
fallback and ngrok interstitial for single-user private use, with native download
and attachment work deferred until development budget is available. Hosted
browser delivery is a later step; it does not itself supply native ChatGPT file
support. See the [restart plan](implementation-tickets.md#budget-decision-and-restart-plan--october-22-2026).
This deferral changes work priority, not the public acceptance requirements above.

# Additional workload regressions — local validation

The [October 23 additional-regression repair](../docs/additional-regressions-2026-10-23.md)
preserves workload selection in planning, permits conditional future allocations,
separates uncertainty from measured shortfall, and resolves explicit assignment
file links through normal authorization. The
[sanitized validation record](sanitized-results/additional-regressions-2026-10-23.md)
distinguishes synthetic HTTP/MCP and migration tests from live acceptance.
Activating this build requires migration `62ab7d391c04`, service restart and fresh
workload snapshots. No private service migration/restart or installed-connector
retest is claimed by this local repair. Historical live hash variation remains
an unconfirmed cause; the original hash is preserved alongside semantic identity.

## Third-party privacy gate — October 25, 2026

[The privacy pipeline](../docs/third-party-privacy.md) adds endpoint minimization,
local text/document inspection, scoped pseudonyms and exact MCP serialization
receipts. Live content reviews require separate signed privacy modality reviews.
Synthetic tests do not establish absence of arbitrary real-world identifiers or
permission to release student/faculty information. Institutional content/privacy
review, operational ownership and deployed-client acceptance remain release gates.
No live access, deployment or approval is established by this local change.

[Local privacy validation](sanitized-results/third-party-privacy-2026-10-25.md):
1,193 tests passed and 27 environment-dependent checks skipped. This includes
44 new privacy cases and does not remove the live review gates above.

## Discussion read gate — October 26, 2026

[Discussion reading and participation](../docs/discussion-reading.md) adds local
synthetic verification of discovery, self-only entry retrieval, coverage-aware
participation and integrations with the existing inventory/audit/planner.
The [validation record](sanitized-results/discussion-reading-2026-10-26.md)
separates tests from live acceptance. Group threads and peer-content disclosure
remain unavailable. No live authorization, production read, service restart,
deployment or institutional/public release approval is established by this work.

## Academic benchmark gate — October 26, 2026

The [academic benchmark laboratory](../docs/academic-benchmark-lab.md) adds a
versioned fictional corpus, independent objective gold, explicit interpretation
review gaps, and non-compensating per-case regression comparisons. Existing CI
requires the fast academic gate; the full release-candidate workflow additionally
requires a real stable baseline. No historical baseline or external model/tool
comparison is fabricated at introduction. An unscored scientific interpretation
is not evidence of visual accuracy or readiness for a particular institution.
See [executed local checks](sanitized-results/academic-benchmark-lab-2026-10-26.md).
These results cannot satisfy institutional authorization, independent expert
review, code licensing, distribution approval or deployed-client acceptance.

## Academic evidence graph gate — October 26, 2026

The [initial evidence graph](../docs/academic-evidence-graph.md) integrates existing
deadline and grade functions with source-bound assertions, explicit conflicts,
restriction inheritance and bounded authorized in-memory change history. Native
tools do not claim prior history when no baseline was supplied. Requirements,
lecture and learning-objective extraction remain outside this initial slice.
Synthetic regression results do not establish live deployment, historical-source
access rights, institutional approval or downstream sharing permission. See the
[local verification record](sanitized-results/academic-evidence-graph-2026-10-26.md).

## Scientific comprehension v3 gate — October 26, 2026

[The scientific evidence contract](../docs/scientific-document-comprehension-v3.md)
retains original source locators and separates structure, rendered delivery,
attributed pixel observations and scientific explanation. The
[local verification record](sanitized-results/scientific-comprehension-v3-2026-10-26.md)
is synthetic backend evidence. Retrieval success and fixture layout inspection do
not establish interpretation accuracy. Advertising validated scientific
interpretation requires all cases and rubrics independently expert-reviewed via
`--require-reviewed`, current client visibility/fallback acceptance and appropriate
native conversion/privacy approvals. Unknown model visibility cannot be promoted
by a receipt. DOCX/XLSX have no verified visual renderer. This work grants no live
content access, institutional clearance, deployment or release approval.

## Semester intelligence gate — October 26, 2026

[Semester intelligence](../docs/semester-intelligence.md) provides on-demand,
selected-course findings with evidence, explicit uncertainty and heuristic priority.
Its synthetic regressions include unknown weights, incomplete history, acknowledgment
and scope races, timezone changes, and notification deduplication. Grade and privacy
regressions remain individually blocking. Local results do not establish deployed
acceptance or institutional authorization. Notification eligibility is a tested pure
adapter contract; no delivery host, schedule or monitoring is activated by installation,
an overview call, or a saved preference. A future approved host must preserve explicit
opt-in, scope, quiet hours, frequency, authorization checks and confirmed delivery
receipts. See the [execution record](sanitized-results/semester-intelligence-2026-10-26.md).


## Local onboarding release boundary (2026-10-26)

The Windows local 0.2.0 wizard separates offline and synthetic editions from an
independently approved hosted institutional service. Packaged local MCP checks do
not establish ChatGPT acceptance. Signed-update verification and a per-user
installer are implementation evidence, not a signing identity or distribution
approval. Empty public trust configuration blocks updates and institutional routes.

General student release additionally needs a protected Windows publisher identity,
verified signed installer/uninstaller and real update/rollback rehearsal,
nontechnical usability observations, accessible UI review on an unlocked consumer
desktop, and independently tested advertised clients. No macOS/Linux release is
claimed. Keep G1/G2/G5 and existing institutional/distribution gates independent.
See [onboarding acceptance](sanitized-results/onboarding-2026-10-26.md) and
[study protocol](../docs/review-templates/onboarding-usability.md). No approval,
selection or background monitoring is enabled by installation or upgrade.

## Academic process workflow gate — October 28, 2026

The [17 process specifications](../docs/process-specifications/implementation.md)
are implemented behind an opt-in flag. The CI process gate requires current source
fingerprints and passing synthetic acceptance for every specification; no failed
privacy, authorization or recovery case can be offset by other passing cases.
Backend tests and HTTP MCP tests do not establish installed-client acceptance or
model interpretation accuracy. PostgreSQL concurrency, native conversion/OCR and
deployment recovery retain their own environment-specific checks.

The public portfolio workflow returns a hold until a separately trusted rights
review is available; assistance permission and caller declarations cannot grant
publication rights. Degree projections remain unofficial. No sending, submission,
calendar mutation, public publishing or monitoring is activated by this feature.
See the [verification record](sanitized-results/process-specifications-2026-10-28.md).

## Stress diagnostics repair — October 28, 2026

The [repair evidence](sanitized-results/stress-repair-2026-10-28.md) separates
supplied fixture self-checks, the 73-case offline product benchmark, repository
regressions and installed-connector diagnostics. FAIL and BLOCKED cases remain
open; missing capabilities, unobserved pixels and partial coverage cannot count
as acceptance. Safe diagnostics and synthetic provider authority confer no
institutional approval. The personal institutional connection must remain disabled.

The [follow-up evidence](sanitized-results/stress-followup-2026-10-28.md) records
repairs and additional synthetic acceptance. Genuine UI acknowledgment, original
PPTX pixel observation and disposable deployment-recovery acceptance retain
their own gates; corpus improvements do not waive them.
