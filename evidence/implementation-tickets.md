# Dependency-ordered implementation record

| Ticket | Local deliverable | State / remaining proof |
|---|---|---|
| C01 audit/traceability | Empty local/remote repo inspected; R01–R43 and T01–T46 registered | Implemented |
| C02 feasibility | Current official MCP/auth/Canvas/distribution contracts reviewed | Implemented review; external gates unresolved |
| C03 boundaries | Typed principal/connection model, endpoint policy, vault, threat/data-flow ADR | Implemented local; independent review pending |
| C04 authenticated slice | Running official-SDK HTTP tools, scoped synthetic provider and negative tests | Verified synthetic |
| C05 actual student read | Private owner-only Rowan read through WorkOS, HTTPS tunnel and actual ChatGPT Pro | First read and short renewal proof passed; institutional OAuth and broader pilot remain pending |
| C06 coursework | Student courses, assignment pagination, effective dates/statuses and coverage | Verified subset; broader inventory pending |
| C07 planning | Effort ranges, priorities, bounded review, dependency ordering, busy times, pinned replanning and shortfall | Verified local; real student usefulness pending |
| C08 lifecycle | Disconnect, account-wide deletion, OAuth/queue fences, export, encrypted backup, restore journal, SSRF and parser fixtures | Verified local; hosted operations/sandbox pending |
| C09 live UX | Local settings keyboard/visual check, HTTP CSRF tests and private ChatGPT read | Broader ChatGPT workflows, mobile and native Calendar remain untested |
| C10 knowledge/math | Modules/pages/files, course-bound module references, scoped page search, text continuation, bounded file transport and simple-points primitives | Partial; binary extraction requires verified OS isolation; full policy subsets remain gated |
| C11 optional Calendar | No live grants/actions/receipts or notifications exposed | Deferred until independent authorization and approval proof |
| C12 distribution | Reproducible dependencies, guides, CI template, truthful claims | Source upload authorized; listing/license/live cost gates unresolved |

## Public-release download roadmap — October 22, 2026

These C12 follow-ups belong to M4 in [Codex_Spec.md](../Codex_Spec.md).
They extend existing requirements without changing R01–R43 identities or
upgrading [G0–G5](release-gates.md). This is planned work, not deployment approval
or a claim that the gaps are fixed. The private browser fallback remains acceptable
to the owner for now.

### Budget decision and restart plan — October 22, 2026

**Owner decision:** Keep browser downloads for the current single-user private
connector. Defer native in-chat downloads, conversation attachments and download
UI improvements until development budget is available. Accept the ngrok **Visit
Site** interstitial for now. Preserve the working fallback and current buttons;
this decision requests documentation, not an implementation or deployment.

Browser downloads already save originals to the user's device. The deferred work
is delivery through ChatGPT's interface, not the ability to obtain a local copy.
The present local connector must remain online; links still expire and fresh
downloads must reauthorize. Continue prioritizing useful, reliable connector reads.

| Stage | Decision / trigger | Related tickets |
|---|---|---|
| Current private use | Keep the existing browser route and ngrok interstitial unchanged. No hosting purchase, migration or native-download work now. | Existing working fallback |
| Hosted delivery later | When the owner allocates budget and requests hosting, move the existing browser-delivery workflow to an always-on backend with stable HTTPS. Start with the current owner-only scope. | D01, D04, D05, applicable D06 |
| Native delivery later | Revisit in-chat downloads, capability-aware UI and attachments after hosting, or in a separately requested native-delivery effort. Hosting is the chosen order, not a technical prerequisite for research. | D02, D03, applicable D06 |

The future backend can fetch authorized Canvas originals, stage them privately,
serve expiring browser links and clean up temporary files using the existing
`/course-file-download/{capability}` and `/course-file-original/{delivery_id}`
routes. It needs an actual application runtime; static website hosting alone is
insufficient. Preserve access checks, private-link handling and retention. Start
with one API process per staging root, consistent with the present memory-only
delivery records; restart invalidates old links and requires fresh preparation.
Multi-instance scaling is separate design work. A stable deployment can remove
the development-tunnel interstitial and laptop dependency, but does not grant
ChatGPT the missing host capability or create native attachments automatically.

**Resume checklist for the next funded task:**

1. Read the [investigation](../docs/original-file-delivery.md#in-chat-download-investigation--october-22-2026)
   and [verification record](sanitized-results/original-file-delivery.md). Confirm
   the requested budget/scope and current local/deployed versions. Recheck current
   platform contracts; do not assume the October 22 capability findings remain
   current. Preserve unrelated changes and the existing private download path.
2. Establish a synthetic baseline with
   `node scripts/diagnose_download_handshake.mjs` and
   `.venv/Scripts/python.exe -m pytest tests/test_file_delivery.py tests/test_file_delivery_contract.py -q --tb=short`.
   The diagnostic builds in memory and does not rewrite the shipped widget.
   Record actual results; a previously completed identical suite need not be
   repeated without relevant changes.
3. For hosting, choose the provider, cost ceiling and operator in that funded
   task. Prepare stable HTTPS, authenticated MCP access, secure secrets/database,
   bounded private staging, log redaction, monitoring and rollback. Use the
   [deployment template](../compose.yaml) as a starting point, not proof of hosted
   readiness. Verify a synthetic deployment before an authorized owner-only
   cutover; keep the existing private setup available for rollback.
4. Close the hosted browser-delivery work only after testing a clean-browser
   download without the ngrok development page, exact original-byte preservation,
   expiry/fresh preparation, denied access, cleanup, outage/restart recovery and
   operation with the developer's local service offline. Test each advertised
   client and record evidence without private files or capability URLs. Expiry
   and restart may require a new link; never claim old links survive migration.
5. For the later native-delivery effort, capture safe live handshake diagnostics
   first. Use the existing standard route only where the host advertises support;
   otherwise investigate a documented alternative with synthetic originals.
   Verify downloads and conversation attachments separately, including size,
   integrity and retention constraints. Keep the browser route working throughout;
   if no supported native route exists, leave that feature explicitly deferred.

**Status:** Deferred until owner-allocated development budget; no target date or
scheduled work. D02's investigation is retained, not marked as a completed fix.
Public-release acceptance requirements below remain in force; private acceptance
of the interstitial does not waive public security, institution or listing gates.

### Evidence and current limitation

In the referenced **Fetch downloadable file** conversation, the owner reported
that **Download in browser** worked after selecting **Visit Site**. The supplied
screenshot shows an ngrok free-service interstitial. It establishes the
interstitial's identity; the completed download is user-reported. The exact
ChatGPT surface/build, negotiated capabilities, saved-byte comparison and native
attachment were not captured. No private hostname, IP, file, or capability URL
is reproduced here.

The owner also reported that **Download original** said the client did not offer
an in-chat download and explained the private, expiring browser fallback and
online-server dependency. In the inspected [widget](../ui/page-reader/download.js),
that message is emitted when `app.getHostCapabilities()?.downloadFile` is absent.
This is evidence of the fallback branch, not proof of why negotiation omitted
the capability or that every ChatGPT client lacks it. Hosting changes alone do
not establish host download support. Preparation, host handoff, a saved original,
and attachment to a conversation remain distinct outcomes.

### C12-D01 — Remove the development-tunnel interstitial

**Priority:** P1, required for public downloads. **Owner:** operator/maintainer.
**Trace:** R26, R28, R29; G5. **State:** planned; production route unverified.

Select a stable HTTPS delivery origin and supported hosting/tunnel configuration
that serves authorized attachments without the observed ngrok warning. Verify a
first visit in a clean browser profile, with no previously accepted interstitial
cookie, through the real ChatGPT browser action. Do not rely on users clicking
through a development warning or installing custom headers. Preserve legitimate
ChatGPT/browser navigation and download consent. Record the chosen configuration
and redacted evidence; choosing a domain or paying for hosting alone is not proof.

### C12-D02 — Make download actions reflect negotiated support

**Priority:** P1, required for public downloads. **Owner:** integration/UX/QA.
**Trace:** R20, R26, R29, R40; G0. **State:** investigated locally; absent host
capability reproduces the message; raw live negotiation and UX changes pending.

The owner reports the limitation on web, desktop and mobile. An unchanged-bundle
probe with the real pinned SDK reproduces the message only in the absent-capability
case and dispatches downloads when support is advertised. See the
[investigation and fix options](../docs/original-file-delivery.md#in-chat-download-investigation--october-22-2026).
No browser fallback behavior changed.

Capture client/build, SDK/protocol and redacted capability negotiation after the
handshake. Check `downloadFile` and external-link support independently. Prefer
the supported action immediately instead of requiring a failed primary click to
reveal the browser fallback. Explain external delivery and expiry in plain
language; if neither route works, retain the authorized Canvas source action.
Test supported, unsupported, rejected and timeout/disconnected states. An unknown
outcome must remain unknown, without automatic duplicate downloads or a claimed
save. Do not infer capabilities from product name or user-agent alone.

### C12-D03 — Resolve native conversation attachment feasibility

**Priority:** P2 enhancement; required only for a native-attachment claim.
**Owner:** integration/product. **Trace:** R20, R31, R34, R40; G0.
**State:** initial contract review complete; no verified adapter or attachment receipt.

Optional ChatGPT file helpers are candidates for a separate synthetic prototype;
their availability, original-file use, size/retention constraints and actual
conversation-attachment behavior remain unverified. The standard download RPC
does not itself close this ticket. See the [investigation](../docs/original-file-delivery.md#in-chat-download-investigation--october-22-2026).

Investigate documented output-file/attachment contracts separately from the MCP
Apps download handoff. Prototype only a supported path with synthetic originals;
record actual host receipts, user-visible attachment, integrity and retention
behavior. File-upload helpers or an accepted download request alone do not prove
this workflow. If the target client lacks a suitable contract, record the
limitation and defer attachment with an accurately labeled browser fallback.
Do not promise universal in-chat delivery or add a separate chatbot/model API.

### C12-D04 — Validate private-link security and recovery in deployment

**Priority:** P1, required for public downloads. **Owner:** security/backend/QA.
**Trace:** R01, R16–R18, R43; G3. **State:** synthetic coverage exists; deployed proof pending.

Keep short expiry, current authorization/source-version checks and explicit fresh
download requests. A bearer URL grants access to its holder; it is not an
identity-bound download. Verify proxy/tunnel/analytics redaction, private staging
cleanup, attachment/no-store headers and absence of URLs/bytes in model-visible
output. Exercise expiry, source replacement, course deselection, disconnect,
revocation, restart, rejected access and interrupted transfers using synthetic
fixtures. Fresh downloads must reauthorize rather than extend stale grants.
Explain that already saved copies cannot be recalled. Never solve friction with
public permanent links or relaxed access checks.

### C12-D05 — Provide reliable public delivery operations

**Priority:** P1, required for hosted public downloads. **Owner:** operator/product.
**Trace:** R18, R28, R29; G5. **State:** hosting, ownership and budget unresolved.

Choose an operating model that does not depend on the developer's laptop staying
awake or its temporary tunnel staying online. Record availability/cost targets,
monitoring, support ownership, staging quotas, cleanup and restart/incident
recovery. Honor the current single-process staging-root constraint or explicitly
design and verify a replacement before scaling. Demonstrate outage and restart
recovery without preserving expired grants or reporting success for lost
transfers. The private local service still requires the server to stay online;
the roadmap does not authorize a hosting purchase or migration now.

### C12-D06 — Complete client acceptance and publish bounded claims

**Priority:** P1, required for each advertised download surface. **Owner:** QA/product.
**Trace:** R20, R26–R29, R31, R40; G0, G3, G5. **State:** user-reported private browser success only; formal client acceptance pending.

Test ChatGPT web and at least one mobile flow before cross-device claims, plus
every desktop/mobile surface specifically advertised. Use synthetic files on the
intended deployed path, including below/above the inline-payload limit. Record
client/build, capability results, route, filename/type/size and saved SHA-256
against the prepared original and an independent authorized source copy. Verify
clean-profile navigation, expiry/fresh download, failure/retry, keyboard and
screen-reader use. Report preparation, handoff, save/byte match and attachment in
separate columns. Update student/support guides and the compatibility matrix;
leave unsupported surfaces and native attachment explicitly unverified/deferred.

### Dependencies and source boundary

Follow the budget decision above: retain private browser delivery now, address
hosting when funded, then revisit native delivery. D02 capability investigation
and D03 attachment research can run independently of hosting if separately
requested. D06 public-path acceptance depends on D01, D02, D04 and D05;
D03 can remain deferred if no native-attachment claim is made. Institutional
access and distribution eligibility remain separate release gates.

Official documentation reviewed on October 22, 2026 describes optional
[ChatGPT file helpers](https://developers.openai.com/plugins/reference#file-apis)
and recommends checking actual capabilities and providing fallbacks in
[MCP Apps UI integration](https://developers.openai.com/plugins/build/chatgpt-ui#layer-on-chatgpt-extensions).
These contracts are research inputs, not evidence of this connector's support on
a particular client. Recheck them at implementation time. Current implementation
and earlier test scope are in [original-file delivery](../docs/original-file-delivery.md)
and its [verification record](sanitized-results/original-file-delivery.md).
