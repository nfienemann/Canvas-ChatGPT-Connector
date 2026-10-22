# Deferred roadmap: Rowan-first hosted student release

Recorded 22 October 2026. **Status: deferred; current correctness and reliability
issues take priority.** Resume this roadmap when the owner explicitly returns to
public-launch work. Saving it does not start outreach, purchases, deployment,
student recruitment, or a directory submission.

This roadmap preserves [Codex_Spec.md](../Codex_Spec.md) and the
[release gates](../evidence/release-gates.md). It extends distribution ticket C12
and depends on the student-access, lifecycle, and usability work in C05/C08/C09.
It is a future-work record, not evidence that a gate has passed.

## Agreed direction and student experience

The owner selected **Rowan first** and a **hosted service with zero downloads**.
The operator or a sponsor covers service costs. Expand to other institutions
only after their access paths and supported behavior have been verified.

The intended student journey is:

1. Open the approved Canvas Bridge listing or supported institution-managed
   connection in ChatGPT and select Connect.
2. Complete connector sign-in if required, then authenticate on Rowan's genuine
   Canvas/SSO page and approve the disclosed coursework access.
3. Select courses and confirm the display timezone in the same guided journey.
4. Return to ChatGPT and ask about coursework. Renew credentials in the
   background when permitted; explain when reconnection is necessary.

Students must not need a local server, terminal, Git checkout, developer mode
configuration as the general-release setup, manually generated Canvas token,
model API key, new connector password, or separate student subscription.
The ordinary backend supplies authenticated facts and deterministic processing;
ChatGPT supplies conversational reasoning. No separate model inference service
is required. Hosting, authentication, storage, backups, and support still cost
money. Actual ChatGPT plan/workspace eligibility must be verified before claims
about availability or additional subscription requirements.

Minimize visible sign-in steps while preserving two separate authorization
relationships: ChatGPT to Canvas Bridge, and Canvas Bridge to the student's
Canvas account. Reuse the established identity provider and existing sessions
where supported. Do not promise one-click setup or silently merge identities
by email. OpenAI's plugin-specific Continue with ChatGPT integration was a
limited partner trial at this review; it is an optional future improvement,
not a launch dependency or an assumed entitlement.

## Starting point and external dependencies

The repository contains authenticated MCP tools, coursework and planning
features, Canvas OAuth linking and renewal code, encrypted credential storage,
course-selection settings, deletion/export controls, and deployment groundwork.
Recorded real-client evidence establishes an owner-only ChatGPT Pro connection.
It does not establish other-student onboarding, a production hosted service,
institutional OAuth approval, or public listing eligibility. Downloadable desktop
previews are synthetic demonstrations, not the proposed student access path.

Two external dependencies determine whether this launch can proceed:

- **Rowan Canvas access (G1):** obtain an institution-enabled OAuth developer key,
  reviewed read scopes, exact callbacks, and the applicable privacy/access
  arrangements. Canvas requires per-user OAuth for multi-user applications.
  Operator-held client credentials must never become student setup tasks.
- **Distribution eligibility (G2):** obtain a documented acceptable path under
  OpenAI's restriction on plugins that primarily function as unofficial
  third-party connectors. A student OAuth grant, Rowan approval, extra planning
  features, or a new name does not establish OpenAI approval. Evaluate an
  institution-managed pilot separately if appropriate; it is not a policy bypass.

Review the linked primary sources again when this roadmap resumes. External
approvals have no committed completion date. Do not promise a launch date from
the existence of working code or a published repository.

## Dependency-ordered work

| Milestone | Future deliverable | Completion evidence |
|---|---|---|
| P01: confirm access and distribution | Prepare the Rowan administrator packet: purpose, exact read scopes and callbacks, data flow, retention, support ownership, and pilot boundaries. Resolve the acceptable ChatGPT distribution route. | Documented institutional configuration/authorization and platform guidance for the intended route; G1/G2 remain unresolved until evidence exists. |
| P02: establish hosted operations | Deploy the existing API and worker with PostgreSQL, stable HTTPS, a supported isolated parser environment, private secrets, resource quotas, redacted monitoring, backups, and an incident/support process. Select operator, region, provider, budget cap, and cost ownership before provisioning. | Clean deployment and rollback exercise, credential-rotation exercise, independent backup restore with deletion fences, measured capacity/cost, and a named operational owner. |
| P03: complete low-friction onboarding | Integrate connector sign-in, Rowan OAuth, course/timezone selection, cancellation, return to ChatGPT, and reconnect into one guided flow. Retain the existing `/mcp` and settings interfaces; register exact deployment callbacks, including `/settings/canvas/callback`. | A new student completes setup using the guide alone, without keys or technical assistance; repeat sessions and token expiry do not unnecessarily repeat setup. |
| P04: verify privacy and account isolation | Review the hosted data flow and publish the actual operator/contact, recipients, retention, deletion/export, and support information. Verify isolation, safe file processing, revocation, and abuse limits in the deployed configuration. | Independent security/privacy review plus synthetic negative tests and deployed lifecycle evidence; no claim of compliance based solely on OAuth or encryption. |
| P05: run a controlled Rowan pilot | After applicable access/privacy gates, invite a small approved adult-student cohort. Test only the documented features and intended ChatGPT plans/surfaces. Record usability failures and fix them before widening access. | Independent accounts complete unaided onboarding and representative workflows; multi-day auth, fresh Canvas comparisons, accessibility, and hosted recovery checks pass. Record limits and unresolved failures. |
| P06: prepare supported distribution | After eligibility is resolved, prepare the current plugin package, publisher/domain verification, public privacy/support pages, safe reviewer access, positive/negative scenarios, and walkthrough evidence. Resolve source licensing and audit public claims. | Required review and approval for the selected route, an installation test from a fresh eligible account, and a supported-institution/client matrix matching the tested release. |

P01 feasibility should be addressed before investing in public packaging.
Independent synthetic fixes and preparation can continue while external access
is pending. P02-P04 must be ready before real student pilot processing; P06 must
not be advertised as complete before actual approval and installation evidence.
Existing release requirements remain authoritative; this table does not waive
them or authorize future external actions.

## Acceptance scenarios

- **Setup:** fresh eligible account, returning account, denied consent, expired
  callback, interrupted onboarding, unsupported institution, and wrong-account
  selection. Cancellation leaves no active coursework connection.
- **Identity and access:** two students cannot read each other's courses, files,
  grades, saved state, exports, or cached content. Course deselection, revoked
  access, expired grants, and changed institutional scopes fail safely.
- **Renewal and reliability:** repeat use after both access-token lifetimes and
  over multiple days, server restart, concurrent renewal, provider outage,
  throttling, and recovery. Stale or failed reads never become an empty workload.
- **Academic usefulness:** compare selected-course deadlines, submission status,
  source links, document reading, planning, and supported grade behavior with
  the student's actual authorized Canvas view. Preserve coverage and uncertainty.
- **Lifecycle and usability:** disconnect, account-wide deletion, export,
  deletion-fenced restore, keyboard/screen-reader operation, and every advertised
  desktop/mobile ChatGPT surface. Confirm published claims against that release.
- **Capacity:** measure normal usage and bounded document-processing bursts;
  verify per-user/fleet limits, cost alerts, and a recoverable failure mode.

Use synthetic records for repository tests and public evidence. Keep real
academic records, credentials, private operator configuration, and backups out
of source control. Record actual checks rather than inferring success from code.

## Boundaries and resumption checklist

Canvas stays read-only. No roster access, arbitrary HTTP/SQL tools, token-paste
onboarding, second chatbot/dashboard, academic-data monetization, or student
upsells. Calendar writes and notifications remain separately authorized work;
they are not automatically activated by this roadmap. Desktop signing and
notarization matter if real desktop distribution is pursued later, but are not
prerequisites for this zero-download hosted direction.

When resuming, inspect the current repository and release evidence, reconcile
documentation drift, identify unresolved correctness issues, and revalidate
platform rules. Carry forward the confirmed Rowan-first/hosted choices. Resolve
the remaining operator, funding, region, identity-flow, and pilot-access decisions
with concrete proposals before external commitments. Do not treat the private
owner configuration as a production multi-user template.

Primary sources reviewed for this discussion on 22 October 2026:

- [Canvas OAuth and multi-user token requirements](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth)
- [Canvas developer-key scope and institutional enablement](https://developerdocs.instructure.com/services/canvas/oauth2/file.developer_keys)
- [OpenAI plugin authentication](https://developers.openai.com/plugins/build/auth)
- [OpenAI plugin guidelines and distribution restrictions](https://developers.openai.com/plugins/plugin-guidelines)
- [OpenAI plugin submission requirements](https://developers.openai.com/plugins/deploy/submission)
- [Sign in with ChatGPT for plugins and trial eligibility](https://developers.openai.com/siwc/chatgpt-plugin)
