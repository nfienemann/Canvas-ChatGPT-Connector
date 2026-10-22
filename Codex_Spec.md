# Codex_Spec — Canvas-to-ChatGPT Academic Connector

**Consolidated implementation specification · Version 2.0 · 20 October 2026**  
**Product owner:** Nick  
**Working name:** Canvas Bridge (descriptive working title; no affiliation implied)  
**Product:** A ChatGPT-native extension for dependable, student-specific academic assistance across explicitly supported Canvas institutions.

> Do not build another AI assistant. Make the assistant students already use more useful.

## 0. Document authority, evidence, and how Codex must use this file

This file supersedes `Canvas_ChatGPT_Connector_Codex_Spec.md` v1.0 wherever they conflict. It reconciles the original specification, the latest product requirements pasted in the conversation, and `Pasted text(20261020-160608).txt`, titled **CANVAS TO CHATGPT: CRITERIA REVIEW AND DEVELOPMENT ROADMAP**. Codex should not need the earlier files to understand the implementation requirements.

### 0.1 Source hierarchy

1. **H0 — Latest product-owner requirements:** ChatGPT-native identity; no standalone chatbot or student dashboard; no separate student subscription or mandatory model API key; interoperable connected tools; supported installation and public distribution; infrastructure-supported funding.
2. **H1 — Criteria review handoff:** the uploaded roadmap, prepared 20 October 2026. Preserve its R01–R33 requirement identities, student journeys, uncertainty treatment, multi-institution boundaries, acceptance tests, and evidence discipline.
3. **H2 — Original v1.0 specification:** retain useful engineering, document retrieval, provenance, grade testing, and personal-development details unless superseded above.
4. **E — Current primary documentation:** sources in §26. These constrain what platforms permit and support; they do not prove this project implements anything.
5. **D — Consolidation decisions:** new choices made here to resolve ambiguity. These are explicit design requirements/defaults, not features claimed to exist or vendor guarantees. Consequential deployment, legal, funding, and identity-provider choices remain approval gates.

**Implementation evidence at this handoff: UNKNOWN.** No repository, running service, deployment configuration, Canvas token, live student-data result, calendar operation, or executed test was inspected for this consolidation. This is a specification review, not a code audit. The supplied review also explicitly says implementation was unverified. Do not infer that code does not exist; inspect the actual implementation when Codex receives one.

Current verified deliverable: this consolidated specification and its internal consistency review. No account has been linked and no automation has been activated by preparing it.

### 0.2 Normative language and execution boundary

**MUST** is a release requirement. **SHOULD** is the default unless an architectural decision record (ADR) explains a tested alternative. **MAY** is optional and cannot weaken a MUST.

Codex must first inventory any supplied repository and preserve working code. Convert this specification into tickets and tests, then build the smallest end-to-end slice. Do not claim compliance from scaffolding, a README, mocked screenshots, or an API endpoint that has never been exercised through ChatGPT.

This specification authorizes a development plan, not unrequested purchases, institutional applications, public publishing, production migrations, messages, or actions on student accounts. Implement locally with synthetic data first. Use existing authorized deployment access only within the user's actual execution instructions. Do not ask for credentials in conversation.

## 1. Product identity and non-negotiable boundaries

### 1.1 North star

A student opens an ordinary ChatGPT conversation and asks:

> “Given what is actually due for me, what I have already completed, and the time I have available, what should I do next—and why?”

ChatGPT obtains authorized Canvas facts, reasons over the student's constraints, and returns a useful next action with evidence, freshness, and limitations. The student should not have to maintain a second academic workspace to make this work.

The product is not measured by its number of tools. It is measured by correct information, reduced coordination work, useful planning, and trustworthy completion of authorized actions.

### 1.2 Architectural invariants

- ChatGPT is the primary academic interface. Normal workflows remain inside its conversations; optional inline components must have a text-equivalent path. UI integration must follow the tested supported host contract. [E35]
- Use supported public MCP and ChatGPT plugin/app mechanisms. Never rely on undocumented ChatGPT endpoints, browser-session scraping, credential forwarding, or OpenAI-internal infrastructure.
- ChatGPT performs conversational reasoning, explanation, synthesis, and tutoring. The connector performs authentication, authorization, retrieval, normalization, deterministic arithmetic and constraint checking, bounded search, and separately authorized external operations.
- No separate chatbot, model-serving system, custom AI conversation UI, student-facing subscription, freemium academic tier, or mandatory separate LLM API key.
- No standalone academic dashboard. A minimal authentication/configuration/privacy/troubleshooting surface is allowed. A task board, grade dashboard, or study-planning portal outside ChatGPT is not an acceptable substitute.
- No mandatory separately paid account. Prefer a seamless federated/JIT identity flow without another password. A secure internal principal and consent record are still necessary; “no extra account friction” does not mean “no identity or server state.”
- Canvas coursework is read-only. Calendar writes and connector-local preferences/plans are distinct, explicitly authorized capabilities, not exceptions that unlock arbitrary Canvas writes.
- No tool or document can widen its own permissions. Server-side authorization is the security boundary.
- Every advertised capability must match its tested institution, student role, ChatGPT surface, and deployment version.
- The product supports multiple universities by design, but launches only at institutions with a verified access path. “All Canvas schools” is not a permissible claim without evidence.

### 1.3 Explicit non-goals

Do not implement assignment submission, quiz attempts, question-bank extraction, access to locked exam material, grade editing, teacher impersonation, roster harvesting, automated instructor/classmate messaging, LMS administration, or bypasses of institutional policy. Do not replace Canvas as the academic system of record.

No advertising or sale of academic records; no behavioral-profile monetization; no student-facing upsells. Donations, grants, sponsorships, deployment services, and institutional support may fund infrastructure, subject to platform rules and owner approval. Funding must not change the ChatGPT-native identity or give sponsors access to student data.

## 2. Alignment decisions and changes from v1.0

The handoffs agree on the desired outcome but differ in scope and sequencing. The following decisions resolve those differences deliberately rather than silently combining incompatible assumptions.

| Topic | Earlier tension | Consolidated decision |
|---|---|---|
| Audience | v1.0 was private and single-user; H1/H0 target students across universities. | Public-capable, tenant-isolated architecture from day one; one-institution pilot first. Personal testing is a development lane, not the final product. |
| Student interface | v1.0 allowed a later mobile dashboard. | Remove that destination. Only auth/settings/support pages outside ChatGPT; optional native inline UI inside it. |
| Intelligence | A broad API wrapper is insufficient; no duplicate AI infrastructure. | Add transparent ranking, effort ranges, plan validation, and deterministic grade math; leave natural-language intelligence to ChatGPT. |
| First useful release | v1.0 primarily listed upcoming assignments. | Include “what first?” with a feasible next action and honest limits, not just a sorted deadline list. |
| Authentication | Nick already has a personal token. | Use it only for his private development/testing in server-side configuration. Every other user's onboarding uses authorized Canvas OAuth. No public token-paste mode. |
| Account friction | OAuth often implies another account flow. | Use an established authorization system with federation/JIT enrollment where feasible. Do not invent a password database or merge accounts by matching email. |
| Storage | SQLite fit one user; the new target needs isolation and concurrent work. | Reference hosted implementation uses PostgreSQL with tested authorization boundaries. SQLite may remain for isolated experiments, not an untested production shortcut. |
| Calendar | Native cross-tool use and durable server sync are different. | Support conversation handoff first; independently authorize and test connector-owned Google Calendar sync later. Never reuse another plugin's credentials. |
| Read-only language | Calendar and saved plans can mutate state. | Say **Canvas-read-only**. Annotate and authorize local writes and calendar actions truthfully. |
| Grade work | Exact simulations are complicated, but honest grade interpretation is foundational. | Visible grades and uncertainty are P0. Exact scenarios launch only for proven policy subsets. |
| Reliability | v1.0 deferred substantial operations work. | Identity isolation, coverage, deletion, backup recovery, and safe failures are pilot prerequisites. |
| Search/fetch | v1.0 treated universal search/fetch as mandatory. | Domain tools are primary. Add standard `search`/`fetch` when the selected ChatGPT discovery/research surface requires them; test the exact compatibility contract. |
| Public release | Publishing source or running MCP is not approval. | Separate institutional access, ChatGPT custom connection, directory eligibility, and listing approval gates. Start feasibility checks at M0. |
| Evidence | A roadmap can sound like a completed implementation. | Preserve R01–R33 and use independent delivery and verification status with references. All implementation verification starts UNKNOWN here. |

**New externally identified release risk:** OpenAI's current guidelines state that plugins primarily functioning as unofficial third-party connectors, including pass-through intermediaries, cannot be approved. Therefore, a public Canvas listing is an **unresolved distribution-policy risk**, not a promised outcome. Obtain a documented acceptable authorization/partnership/distribution path and platform guidance before committing to directory launch. Adding planning features, changing the name, or obtaining a student OAuth grant does not by itself establish eligibility. Custom/private or institution-managed deployment must independently satisfy applicable rules; it is not a loophole. [E03]

## 3. Target users, launch profiles, and release gates

### 3.1 Audience

Initial audience: adult higher-education students at explicitly supported institutions and in reviewed deployment regions. Rowan is the candidate first pilot institution because it motivated the project, not because access or approval has been verified. Do not hard-code Nick, Rowan, American dates, course names, semester dates, or `America/New_York` as universal values.

Default UI language for the initial pilot: English. Store Unicode faithfully. Obtain an IANA display time zone from the student or verified context; show the chosen zone. Broader languages, jurisdictions, minors, observers, and instructors require their own documented support decisions.

### 3.2 Supported profiles

| Profile | Purpose | Credentials | What it does not prove |
|---|---|---|---|
| Synthetic development | Unit, integration, isolation, and UX tests | Fake provider, synthetic records, isolated secrets | Real Canvas access or ChatGPT support |
| Personal developer proof | Nick tests his own records privately | His token entered through secure operator configuration; MCP authentication remains required | Other-user onboarding, institutional permission, public availability |
| Controlled student pilot | Real students at an approved supported school | Per-user Canvas OAuth; applicable privacy/access arrangements | Universal compatibility or public listing approval |
| Public/institution-managed release | Nontechnical students use a supported installation path | Reviewed authentication and institution registry | Availability for every plan, country, school, or client |

Do not invite peers into the personal-token proof. No shared service account token may stand in for their individual authorization.

### 3.3 Early feasibility gates

**G0 — Actual ChatGPT path:** record the supported connection method, plan/workspace restrictions, tool behavior, and client surface. Demonstrate one authenticated tool call in an ordinary ChatGPT conversation. A Codex-only or API-Playground-only success is not this gate.

**G1 — Canvas institutional access:** verify developer-key availability, enabled scopes, callback configuration, student access, and effective capability behavior at the candidate school. A global key still needs relevant account enablement. [E07, E08]

**G2 — Public distribution eligibility:** resolve the unofficial-connector policy risk; record written guidance/authorization and the submission route. A technical MCP success cannot satisfy this gate. Final listing approval belongs to M4, but feasibility starts at M0. [E03, E04]

**G3 — Security/privacy suitability:** approved data-flow and retention records, attack fixtures, isolation, and an appropriate live-data arrangement before student pilot use.

**G4 — Native cross-tool interoperability:** test Canvas plus a separately authorized Calendar capability in the same ChatGPT workflow. When absent, disclose the gap; do not claim calendar access.

**G5 — Operational ownership:** identify operator, deployment budget, incident owner, credential response path, and tested restore/deletion processes.

When a gate is blocked, continue independent synthetic development. Do not replace the product with a standalone app, an unsupported browser hack, or a calendar feed and report the original goal complete.

## 4. Student journeys and answer contracts

These are requirements, not descriptions of currently implemented behavior.

| Journey | Required response | Required boundary |
|---|---|---|
| “What is due this week?” | Student-effective dates, status, source links, overdue/undated sections, course coverage. | A failed refresh is not an empty workload. |
| “What should I work on first?” | A short ranked set, one concrete first action, effort range, urgency/stakes explanation, uncertainty. | Do not equate points, stress, or earliest date with universal priority. |
| “I have 45 minutes.” | A feasible task or useful subtask fitting the window and known dependencies. | Do not repeatedly postpone major work for easy short tasks. |
| “Read my syllabus.” | Requirements, dates, policies, locations in the source, and conflicts with current Canvas fields. | Extracted or inferred dates do not silently become authoritative calendar events. |
| “Which assignments matter most for my grade?” | Raw points, category context, known required-completion rules; supported calculations only. | Raw points from different courses/categories are not comparable grade impact. |
| “Make a study plan for tonight/this week.” | Feasible blocks around commitments, breaks and buffer; shortfall when capacity is insufficient. | A proposal is not a calendar action or a durable saved preference. |
| “Add these deadlines to Calendar.” | Reviewable target, dates, exact changes, then verified operation results if authorized. | No invented receipts, duplicate events, or access to another plugin's tokens. |
| “What changed since yesterday?” | Old/new values, first-observed/source times, baseline coverage, effect on a proposed plan. | Newly discovered is not necessarily newly published. |
| “Prepare me for class.” | Authorized reading manifest, cited briefing, methods/evidence/limitations, discussion prompts. | Filenames and text extraction alone do not establish a complete reading or figure interpretation. |
| “I am behind.” | Recoverable work, locked/uncertain work, a realistic next step, and issues to clarify with the instructor. | No shame, invented penalties, or impossible catch-up schedule. |

Default responses should be compact and actionable, with deeper evidence available on request. Do not dump raw JSON, lecture the student about implementation internals, or repeatedly ask for preferences already available and authorized. Ask a narrow question only when it materially affects a safe/correct result. Useful partial results are preferable to an unnecessary onboarding questionnaire.

## 5. Reference architecture and ownership of responsibilities

### 5.1 Modular service, not another AI application

```text
Student in ordinary ChatGPT conversation
    |
    | supported authenticated MCP / plugin tools
    v
Canvas Bridge backend
    |-- request identity + per-object authorization
    |-- Canvas normalization + evidence + coverage
    |-- deterministic prioritization / plan validation / grade calculations
    |-- bounded material retrieval and full-text search
    |-- typed tools + optional inline UI resources
    |
    +--> Institution-specific Canvas adapter --> Authorized student Canvas account
    |
    +--> PostgreSQL: scoped records, snapshots, preferences, jobs, action ledger
    +--> Secret manager / encrypted credential vault (separate access boundary)
    +--> Worker: bounded refresh, parsing, reconciliation, retention
    +--> Short-lived private document storage when needed

Separate optional path, never implicit:
    Calendar provider OAuth --> Calendar adapter --> Owned events + receipts

ChatGPT may instead orchestrate its separately connected Calendar tools.
That orchestration does not transfer their credentials to Canvas Bridge.
```

### 5.2 Reference implementation decisions

Use a **modular monolith**, one repository, and an API process plus worker process from the same codebase. Avoid microservice sprawl. Reference runtime: Python with the official supported MCP SDK, typed validation, asynchronous HTTP client, database migrations, and a durable database-backed job queue/outbox initially. Python retains the original document-processing direction. TypeScript is an acceptable existing-code choice if verified working code already exists; record an ADR rather than rewriting it solely to match this preference.

Use PostgreSQL for the hosted service, full-text search first, and encrypted secrets through an established service. Select current maintained runtime/package versions during implementation and commit lockfiles; no unverified version number in this specification is a package requirement. Database row-level policies may provide defense in depth but cannot replace application authorization; tests must include worker/admin connection behavior and connection-pool context reset.

No model inference API is required for the ordinary product. No hidden use of a paid embedding, OCR, or summarization service. Prefer local text extraction and full-text retrieval. Future external processing needs explicit privacy review, consent where applicable, budget caps, and a fully usable non-paid baseline.

A static Netlify site alone is not this backend. An operator may choose supported serverless/container infrastructure, but must prove MCP transport, OAuth, durable storage, job execution, resource limits, and stable HTTPS. Students must not deploy servers to use the hosted supported product. Self-hosting is an optional operator/contributor distribution path.

### 5.3 Responsibility separation

| Component | Owns | Must not own |
|---|---|---|
| ChatGPT | Conversation, explanation, source-grounded synthesis, proposed task decomposition | Secret storage, authoritative grades, proof that an external action succeeded |
| Connector tools | Authorized facts, structured constraints, deterministic outputs, receipts | A second chatbot or unrestricted autonomous agent |
| Planning engine | Feasibility, capacity, priority tiers, stable arithmetic | Inventing effort, deadlines, commitments, or instructor policy |
| Canvas adapter | Reviewed routes, student context, pagination, capabilities | Generic API proxy, rosters, academic writes |
| Calendar adapter | Separately granted access, preview/commit, reconciliation | Reusing native connector tokens or changing Canvas dates |
| Minimal settings UI | Linking, course selection, timezone, privacy, reconnect, support | An alternate academic workflow or paid subscription funnel |

## 6. Authentication, institutions, and onboarding

### 6.1 Keep authorization relationships separate

**A: ChatGPT → connector.** Use an established OAuth authorization system compatible with the current MCP requirements. Validate issuer, audience/resource, expiry, scopes, and subject per protected request. Require PKCE S256, protected-resource discovery, appropriate client identification/registration, and exact approved redirects. Use the callback actually supplied by the client-management flow; do not assume a universal callback. Pin and test the relevant platform contract. [E01, E02]

**B: Connector → Canvas.** The service obtains a separate per-student OAuth grant at each supported institution and keeps its credential encrypted server-side. Bind the result to the authenticated connector principal and the verified Canvas origin/user. Canvas tokens must never be accepted as connector identity tokens or forwarded to the MCP client. [E07, E10]

**C: Connector → Calendar, only for connector-owned actions.** This is an independent opt-in provider grant with its own scopes, lifecycle, and credential reference. Native Calendar tools in ChatGPT do not satisfy C.

OAuth credential exchange/refresh/revocation is an authorization lifecycle operation. The Canvas academic adapter remains GET-only; narrowly allowlisted OAuth lifecycle requests may use required POST/DELETE methods through a separate component. Do not accidentally prohibit disconnect or token refresh, and do not expose those exceptions as arbitrary coursework writes.

### 6.2 Low-friction identity without another product account

Target one linking journey: choose supported institution, authenticate on its genuine Canvas/SSO page, approve the disclosed scopes, select courses, return to ChatGPT. Use mature federation or broker support and JIT internal principal creation where feasible. The internal record is not a new paid service account or password registration requirement.

Do not assume ChatGPT supplies a reusable OpenAI user identifier or an identity token from a different plugin. If a supported identity-provider login is technically unavoidable, disclose it as a minimal authentication step; do not add a separate account-management ecosystem. Evaluate the current supported flow before promising one-click onboarding.

A returning authenticated principal may explicitly link another institution. Never merge identities solely by email address. Bind OAuth state to principal, institution, intended flow, nonce, redirect, and expiry. Prevent login CSRF, issuer mix-up, callback replay, and one student attaching another student's connection without authorization.

### 6.3 Institution registry

Store reviewed institution ID, display name, canonical API origin, approved login origins, API/developer-key configuration references, enabled scopes, include-parameter behavior, supported features, compatibility evidence, administrator/support route, and status.

States: `candidate`, `access_pending`, `pilot_supported`, `supported`, `temporarily_degraded`, `unsupported`, `retired`. State labels require evidence, not a successful hostname lookup.

School URL input is a request to identify a known supported institution, not permission for the backend to contact arbitrary hosts. Registry updates are operator-admin actions with review. Support self-hosted Canvas only through an explicit registration and network review.

Canvas documents institution-specific keys, account enablement for global keys, and conditions under which scoped keys ignore `include` parameters. Test the returned capabilities, not the shape expected from an unrestricted token. [E08]

### 6.4 Nontechnical onboarding acceptance

A supported-school student must be able to install/connect using only the student guide, without terminal commands, a Git checkout, a personal API key, or a new AI subscription. Explain access and retention before connection. Make course selection, account identity, timezone, disconnect, and support easy to find.

Cancellation must leave no active connection. Unsupported institutions need a clear explanation and administrator request guidance, not a suggestion to bypass policy with a shared token. Reauthorization must retain the correct institutional identity and avoid leaking another connection's records.

## 7. Authorization and security requirements

### 7.1 Tenant and resource boundaries

Every request, row, cache entry, chunk, job, cursor, export, and action belongs to an authenticated principal and authorized connection. Scope canonical identities by institution/origin, Canvas user, course, entity type, and source ID. Identical numeric IDs in two institutions must never collide.

Resolve Canvas user identity server-side. Tools must not accept arbitrary `student_id`, `as_user_id`, raw credentials, Canvas base URLs, arbitrary SQL, shell commands, or HTTP methods. An opaque ID is not an authorization grant: recheck its ownership and current entitlement.

Only selected courses and student-role features are enabled. A token with teacher/admin abilities must not expand this product's permissions. Reject class-roster and aggregate/classmate-submission endpoints even when the upstream token would permit them. Do not cross-user deduplicate academic text into a searchable shared index in the initial product.

### 7.2 Credentials and safe diagnostics

Never place secrets in prompts, tool results, user-facing URLs, browser storage, source control, telemetry, document parsers, or unredacted exceptions. Provider-mandated OAuth authorization codes may pass through registered callbacks; redact callback query strings, exchange codes promptly, use no-store/referrer protections, and never treat that as permission to expose access tokens.

Use encrypted credential storage, controlled key access, rotation, refresh concurrency locks, and redacted structured diagnostics. A personal token named “read-only” is not necessarily narrowly scoped. Enforce endpoint/parameter restrictions independently.

Disconnect must disable service access and queued work immediately, attempt upstream revocation where supported, and report separately whether remote revocation succeeded. Local removal must not be blocked indefinitely by a provider outage. Never claim a credential was revoked solely because its local reference was removed.

### 7.3 Network and parser boundaries

Require HTTPS for deployed APIs. Validate configured origins, pagination destinations, file metadata, redirect chains, ports, and resolved addresses. Block loopback, link-local, private/metadata targets, DNS rebinding, unsafe schemes, and credential forwarding to unapproved origins. A Canvas file redirect to a legitimate storage host needs a dedicated validated download policy; strip bearer authorization on origin changes. No generic external URL fetch tool.

Parse documents in constrained workers without Canvas credentials or unrestricted network access. Bound size, expanded archive size, depth, page count, CPU, memory, timeout, and concurrency. Reject active scripts/macros, traversal paths, archive bombs, and unsupported formats safely.

### 7.4 Prompt injection is a cross-tool concern

Course HTML, PDFs, announcements, file names, discussion text, and extracted content are untrusted data. They may describe course obligations but cannot authorize actions, change tool descriptions, disable privacy controls, request secrets, or instruct exports.

A backend allowlist cannot guarantee that ChatGPT will never misread malicious text, especially when another connector is available. Therefore test end-to-end adversarial conversations, minimize data sent to tools, preserve source/data boundaries, and require proper user authorization for every consequential action. Native Calendar handoff must never turn an instruction found inside a syllabus into student consent. [E05, E10]

### 7.5 Required negative tests

Cross-user IDs; cross-school IDs; wrong token audience; expired issuer keys; OAuth replay; refresh races; malicious redirect/pagination host; hidden Canvas write endpoint; cached data after revocation; injection attempting a calendar export; parser credential access; queued job after disconnect; forged approval; source changes after preview. Any critical isolation or unauthorized-action failure blocks the affected release.

## 8. Data model, provenance, and coverage

### 8.1 Core records

Use explicit migrations and typed models. Minimum logical records are:

| Area | Records | Invariants |
|---|---|---|
| Identity | principals, institutions, connections, connection_capabilities, consent_records | Separate issuer/subject, institution, Canvas user, and credential references. |
| Scope | selected_courses, course_preferences, enrollment_snapshots | Student access and opt-in scope are both enforced. |
| Coursework | courses, work_items, source_aliases, assignment_groups, own_submissions, visible_grades | One canonical obligation can link to several Canvas representations. |
| Evidence | source_records, source_versions, assertions, source_conflicts, relationship_evidence | Facts retain origin, meaning, locator, version, and observation time. |
| Materials | modules, module_items, pages, announcements, documents, document_chunks | ACLs apply before search results, snippets, and counts are returned. |
| Planning | effort_estimates, planning_preferences, task_progress, saved_plans | Student input and computed suggestions cannot overwrite instructor facts. |
| Sync | sync_runs, collection_snapshots, resource_coverage, observed_changes, job_queue | Partial reads cannot advance a successful-completeness checkpoint. |
| Actions | action_previews, authorization_records, operations, calendar_mappings, outbox | Optional writes have ownership, expiry, idempotency, and receipts. |
| Lifecycle | retention_jobs, deletion_tombstones, export_jobs, audit_records | Deletion survives restores and races with workers. |

Do not store the whole upstream payload “just in case.” Keep a reviewed field allowlist and sufficient normalized evidence. Private debugging fixtures must be synthetic or explicitly scrubbed; never commit student API recordings.

### 8.2 Canonical work item

Required concepts, not an instruction to store each value in one JSON column:

```text
WorkItem
  id: opaque connector ID
  owner_principal_id, connection_id, institution_id, course_id
  source_type + source_id + source_aliases
  title + kind + canonical_source_url
  description_source_ref + rubric_source_refs + material_refs
  effective_due: timestamp | local_date | known_none | unknown
  available_from, closes_at: separately typed values
  instructor_date_assertions[] + personal_working_deadline
  submission_state + assessment_state + timeliness_state
  availability_state + revision_state + submission_requirement
  points_possible + visible_score + assignment_group_ref
  mandatory_completion / prerequisites: evidence-backed or unknown
  effort_remaining: range + origin + as_of + student_correction
  personal_progress: separate from Canvas completion
  retrieved_at + source_updated_at + snapshot_id
  permission_checked_at + capability_coverage + evidence_refs[]
```

Keep `known_none`, `not_returned`, `permission_denied`, `not_refreshed`, and `unsupported` distinct. Do not use a single null for all of them. Preserve raw semantic flags needed for diagnostics while minimizing unrelated upstream data.

### 8.3 Evidence and assertions

Each material fact must have a source reference and retrieval time. Add source update time when actually available, not inferred from fetch time. Extracted facts also need document version, page/slide/section locator, parser method, and any limitations.

Classify values as `source_fact`, `deterministic_calculation`, `student_input`, `assistant_inference`, or `unknown`. Confidence labels describe uncertainty; they are not probabilities unless calibrated. A recent source timestamp does not automatically resolve authority conflicts.

Source URLs should open an authorized human-readable Canvas item. Expiring signed download URLs are not permanent citations. Do not invent a clickable locator when the provider only supports the parent document link; include page/slide information in text.

### 8.4 Result envelope

Domain tools use a compact structured response with a matching readable explanation. Version the schema and validate it before returning.

```json
{
  "schema_version": "1.0",
  "status": "partial_data",
  "data": {"items": []},
  "sources": [],
  "meta": {
    "request_id": "opaque-request-reference",
    "snapshot_id": "opaque-snapshot-reference",
    "retrieved_at": "2026-10-20T16:00:00Z",
    "display_timezone": "America/New_York",
    "freshness": "live",
    "coverage": {
      "requested_courses": ["course-a", "course-b"],
      "completed_courses": ["course-a"],
      "incomplete_courses": ["course-b"],
      "resource_results": [
        {"course_ref": "course-a", "resource": "assignments", "state": "complete", "pagination_complete": true},
        {"course_ref": "course-b", "resource": "assignments", "state": "unavailable", "pagination_complete": false}
      ]
    },
    "next_cursor": null,
    "warnings": [{"code": "upstream_unavailable", "message": "One selected course could not be checked."}]
  }
}
```

This is a **synthetic shape example**, not a report about Nick's account. `live` describes the successful reads and does not make the aggregate complete. Production results must populate sources for every returned fact.

Safe statuses include `ok`, `partial_data`, `stale_data`, `reconnect_required`, `permission_denied`, `unsupported_feature`, `source_changed`, `needs_input`, `retry_later`, and `operation_uncertain`. Separate authentication HTTP/protocol errors from normal domain-state results according to the SDK contract. Return a retry hint only when appropriate; never return secrets or raw provider dumps.

Opaque pagination handles must be principal-bound, filter-bound, snapshot-aware, expiring, and validated server-side. Bound outputs by item count and content size. Never label a truncated first page as a complete course/document.

## 9. Canvas adapter and feature-to-endpoint inventory

The table is a candidate implementation map, not proof of student access. Codex must produce `docs/capability-scope-matrix.md` with the **exact current endpoint scope strings**, approved parameters, institution settings, test evidence, limitations, and fallback for each enabled feature. Check each endpoint's official scope declaration; do not construct a scope by guessing a route name.

| Source area | Candidate route/family | Purpose and boundary |
|---|---|---|
| Self identity | `GET /api/v1/users/self/profile` | Verify the connected account; retain minimum identity fields. |
| Courses | `GET /api/v1/courses`, course detail | Selected student enrollments, term, current authorized course view. |
| Assignments | `GET /api/v1/courses/:course_id/assignments`, assignment detail | Canonical obligations and student-effective dates. |
| Own submissions | `GET /api/v1/courses/:course_id/assignments/:assignment_id/submissions/:user_id` or documented self include | Server resolves this user's ID; no aggregate submission enumeration. |
| Assignment groups | Course assignment-groups family | Known category weights and supported drop/exclusion rules. |
| Own visible grades | Authorized own-enrollment records | Preserve reported value and definition; no unposted or classmates' scores. |
| Modules/items | Course modules and individual module-items collections | Order, requirements, dependencies, accessible linked objects. |
| Pages/syllabus | Course syllabus field, course page collection/detail | Original requirements and policy context. |
| Announcements | Announcements with selected course contexts and bounded dates | Instructor notices; don't silently truncate history. |
| File metadata/download | Authorized files/folders and validated download path | Metadata first, content only within scope and limits. |
| Planner | Planner items in authorized scope | Supplement inventory; personal completion is not submission evidence. |
| Canvas calendar | Calendar-events collection in selected contexts | Events and additional obligations; deduplicate linked assignments. |
| Discussions | Topic metadata/instructions and safe student-visible details | Participation requirements; avoid bulk student-post ingestion. |
| Classic quizzes | Student-accessible quiz metadata | Dates, instructions, duration when visible; no attempt launch or restricted questions. |
| New Quizzes | Separate New Quizzes capability and assignment linkage | Treat as independently tested; no assumption that classic routes expose the same information. |
| External/LTI tools | Linked assignment and accessible metadata only | Source link and explicit limitation; no bypass of a second provider's authentication. |

Official resource families supporting this map are recorded in E09, E11–E17, and E26–E34. Test **API existence**, **this student's authorization**, and **correct semantic interpretation** separately.

### 9.1 Adapter constraints

Maintain an allowlist of method, route template, parameters, includes, response fields, and expected side effects. GET-only academic access is necessary but not sufficient: exclude routes/options that mark readings complete or otherwise change academic state. OAuth lifecycle exceptions remain isolated under §6.

Do not request `all_dates`, student visibility lists, aggregate grade statistics, roster fields, or observed-user records merely because the token permits them. Use the student's effective fields and own submission context. Avoid broad data collection and instructor/admin-only routes.

A missing nested submission in an `include` response may indicate missing scope/include support; it must not automatically become “not submitted.” Capabilities must be independently checked and degrade honestly.

### 9.2 Pagination and request budgets

Follow the provider's pagination contract, validating every continuation. Canvas uses Link-based pagination and cost-aware throttling; a large `per_page` value does not prove completeness. [E15, E16]

Use per-connection and per-institution concurrency controls, retry budgets, exponential backoff with jitter, and provider retry guidance. Distinguish throttling from authentication, authorization, and unsupported-feature responses. Do not label every 403/401 the same or retry authorization failures forever.

If a bounded request cannot finish, return a truthful partial result and continuation/refresh status. A UI deadline query must not wait for a large PDF extraction job. Document processing and near-term workload reads need separate quotas.

## 10. Dates, completion, conflicts, and deduplication

### 10.1 Dates

Use Canvas's effective `due_at`, `unlock_at`, and `lock_at` for the authenticated student, with tests for overrides; do not invent a precedence algorithm for every student's overrides. [E09]

Store source timestamp/offset and meaning; normalize instants to UTC while preserving date-only values as dates. Display with the selected IANA timezone. Resolve “tonight” and “this week” at query time, including the student's week-start preference where material. Use half-open intervals for timed queries and explicitly defined local-date rules for all-day items.

Test DST gaps/overlaps, dates around local midnight, travel, missing zone context, and course/student zones that differ. Never turn a date-only deadline into an invented 11:59 PM instant. A personal target date is not an instructor deadline.

Keep due date, opens-at, and closes-at separate. An overdue but still open assignment may be recoverable; a close time does not necessarily document a late-penalty policy. State uncertainty.

### 10.2 Orthogonal states

Preserve independent concepts rather than a single complete boolean:

```text
submission: not_submitted | submitted | resubmitted | not_applicable | unknown
assessment: graded | pending | excused | unknown
timeliness: on_time | late | missing | not_applicable | unknown
availability: available | future_locked | closed | inaccessible | unknown
revision: none_known | requested | resubmission_available | unknown
personal_progress: not_started | in_progress | student_marked_done | unknown
```

Keep raw source states for interpretation. A submitted item may be late, ungraded, or require revision. Paper/offline work may have no electronic upload. Zero is a value, not missing data. A self-marked planner item does not prove the course's submission requirement was satisfied. “Returned for revision” must be backed by explicit feedback/state or labeled interpretation, not invented from a grade change.

### 10.3 Source conflicts

Keep API-recorded date, syllabus statements, announcements, and student-reported verbal changes as separate assertions. Show conflicts with source locations and times. Do not automatically overwrite a recorded Canvas date with an extracted statement, nor ignore a credible extension announcement.

Use a narrow clarification or explain uncertainty when it affects a consequential action. A provisional study plan may use an explicitly labeled conservative assumption; a calendar deadline write needs an unambiguous source or the student's explicit choice of a personal reminder date.

### 10.4 Canonical obligations

Use explicit assignment/quiz/discussion/planner/calendar linkage to deduplicate representations. Titles alone are insufficient. Graded discussion initial posts and replies may be separate obligations when supported by instructions; preserve that structure rather than falsely collapsing all participation into one upload.

Group work reflects the authenticated student's visible submission and requirements, without harvesting group-member records. Unpublished future work is unknown, not nonexistent. Concluded/archived courses require explicit scope handling and current access.

## 11. Prioritization, effort, and feasible study plans

### 11.1 P0: useful “what first?” without pretending to know everything

Start with an explainable rules-based baseline, not a universal numeric productivity score. The engine returns priority tiers, reasons, known constraints, and the missing inputs that could change the ranking. ChatGPT translates that into natural language.

1. Determine eligible obligations within scope. Exclude excused/satisfactorily completed work where appropriate; retain revision, mandatory participation, and uncertain offline status.
2. Identify hard constraints: effective due/close times, prerequisite work, available blocks, fixed commitments, minimum uninterrupted duration, and student-defined workload limits.
3. Compare schedule flexibility using usable study time, remaining effort ranges, buffer, known stakes, and dependencies.
4. Choose a concrete next action that fits the current opportunity; offer a small set of alternatives and explain why the recommendation wins.
5. Surface uncertainty and protect larger work from repeated postponement. Do not optimize only for point totals or shortest tasks.

### 11.2 Effort model

Effort is **remaining work**, expressed as a range, with origin (`student_estimate`, `instructor_estimate`, `rule_of_thumb`, or `assistant_estimate`), timestamp, and editable assumptions. Missing effort stays unknown unless a labeled provisional estimate is used. Points, pages, or word counts alone cannot become authoritative duration estimates.

Student corrections take precedence for personal planning, not for instructor facts. A conversational correction need not be persisted unless the student requests remembering it or has enabled a clear preference-saving policy. Persistent changes use a write capability with receipts, not a hidden side effect of reading workload.

Task decomposition may be proposed by ChatGPT from actual assignment requirements. The connector validates task IDs, dependency order, effort sums/ranges, deadlines, and plan feasibility. Suggested steps are not new instructor requirements.

### 11.3 Capacity and slack

Let `A(t)` be the number of usable study minutes before deadline `t` after fixed commitments, protected non-study windows, chosen breaks, and buffer. For an individual item's effort range `[e_min, e_max]`, diagnostic slack is `[A(t) - e_max, A(t) - e_min]`.

That per-item calculation is not sufficient to prove a multi-task plan feasible: tasks compete for the same windows. Before reporting a feasible plan, allocate the combined tasks into non-overlapping windows and check cumulative workload, prerequisites, minimum block lengths, and deadlines. Never spend the same free minutes twice.

**Synthetic example:** 180 available study minutes before a shared deadline cannot accommodate tasks requiring 120 and 90 minutes. Each task individually fits; together they exceed capacity by at least 30 minutes, before any extra buffer. The answer must show the shortfall, not produce an overlapping timetable.

When availability is unknown, give a deadline/stakes-based provisional recommendation, not a “conflict-free” plan. Request only the availability needed for the current task, or use an actually available calendar capability with permission.

### 11.4 P1: plan and replan

Generate proposals with scheduled blocks, task linkage, effort range, assumptions, conflicts, unmet work, breaks, buffer, and source snapshot. Leave unallocated time unallocated; do not fill every free minute.

Do not infer psychological traits, diagnose procrastination, or punish missed sessions. “I am behind” should yield a recovery plan and realistic options. Required sleep/work/class windows are constraints, not available capacity.

Replanning compares source changes and new student input with the existing plan. Preserve student-pinned blocks and decisions. Suggest adjustments; do not silently move events or rewrite saved preferences. Saving a plan and applying it to a calendar are separate operations.

## 12. Materials, syllabus interpretation, and study assistance

### 12.1 Retrieval before synthesis

Build a source manifest before a briefing: requested scope, identified readings, assigned-versus-optional evidence, accessed versions, extraction coverage, and exclusions. Do not infer next class solely from file upload dates or “Week 6.” Use schedule evidence or a clearly labeled assumption.

Preserve course → module → assignment/page/file relationships, with locators supporting an inferred link. Relational tables are enough; a graph database is not required.

### 12.2 Parser coverage

Initial supported formats: HTML/text, text-bearing PDF, DOCX, and PPTX with declared coverage. Preserve headings, page/slide numbers, scientific symbols, and tables when reliable. Track parser version, content hash, coverage, warnings, and content version. Same filename does not imply same content.

Image-only scans, multi-column reading order, complex equations, figure-dependent claims, charts, speaker notes, embedded files, and multi-page tables need explicit support tests. Text extraction is not figure understanding. Do not say all six papers were read if one could not be parsed or most evidence was graphical.

OCR is an optional constrained fallback, not a mandatory paid dependency. Figure/image delivery to ChatGPT is a separate capability requiring tested MCP/client handling and privacy controls. Unsupported material must remain visible as an unresolved source with a link.

Bounded ZIP extraction is optional after archive-security tests; it is useful for reading bundles but not a pilot prerequisite. External publisher/library/LTI pages are not automatically authorized by a Canvas link. Return an access limitation and source link; do not forward Canvas credentials externally.

### 12.3 Search and citation

Start with scoped full-text search, phrase queries, title/module boosts, and source-specific filters. Search authorization applies before ranking, snippets, or result counts. Avoid inaccessible-document titles leaking through search suggestions.

Return source IDs, original titles, course context, locators, stable Canvas URLs, freshness, and extraction limitations. Reading long documents must use explicit bounded continuation; a first chunk is not the complete reading.

A useful scientific-paper briefing separates the research question, methods, findings, supporting evidence, limitations, connections, and discussion questions. Generic background knowledge must be labeled as outside the retrieved source when relevant. Never fabricate a figure interpretation or source quotation.

### 12.4 Syllabus requirements and quizzes

Syllabus extraction returns evidence-backed candidate obligations and grading policies. ChatGPT can interpret them, but a saved requirement or calendar write must preserve source and uncertainty. No automatic bulk conversion of ambiguous syllabus prose into authoritative deadlines.

For quizzes, support visible metadata and preparation resources separately for classic quizzes, New Quizzes, and external systems. Do not start attempts, fetch restricted question banks, infer an answer key, or promise access merely because an API exists. [E17, E32]

## 13. Grades and deterministic scenario calculations

### 13.1 Three separate outputs

- **Canvas-reported visible grade:** retrieved source value with its actual field meaning.
- **Local reconstruction:** connector calculation over an explicitly supported set of rules and visible records.
- **Hypothetical scenario:** a conditional result based on specified future scores and known/assumed remaining work.

P0 requires honest visible-grade interpretation. Exact reconstruction and scenarios are separately gated P1 capabilities, not prerequisites for useful deadline and prioritization support.

### 13.2 Supported policy declaration

For each course identify the available treatment of points, weighted groups, grading periods, excluded/excused work, drop rules, never-drop items, extra credit, zero-point items, late penalties, ungraded/unposted work, empty categories, manual final overrides, and unpublished future assignments. Mark each rule `supported`, `not_applicable`, `unknown`, or `unsupported` with evidence.

Unknown grading information blocks an exact claim about grade impact. A zero-point extra-credit item must not trigger division by zero. A missing score is not zero. Do not apply a late penalty a second time to a score that already includes it. Do not expose unposted scores.

Canvas provides enrollment grade fields and group rules; those inputs alone do not prove the entire course policy is known. Its documented assignment-group drop behavior must not be replaced with a naive “drop the lowest percentage” implementation when point denominators differ. [E12, E13, E14]

### 13.3 Calculation and reconciliation

Use deterministic decimal/rational arithmetic with documented rounding. In a simple points-only scenario:

```text
required_remaining_points = target_fraction * final_known_possible_points - earned_points
required_remaining_fraction = required_remaining_points / remaining_possible_points
```

For weighted categories, calculate within each supported category and apply actual category weights. Do not average assignment percentages or compare points across unrelated grading structures.

**Synthetic fixture:** earned 320 of 450 completed possible points, 150 remaining possible points, target 70%, no other rules. Required points: `0.70 * 600 - 320 = 100`; required remaining percentage: `100 / 150 = 66.666...%`.

Handle zero remaining points, already-met targets, infeasible targets, score ceilings, negative inputs, ambiguous policy, and user-defined assumptions explicitly. “Based on currently published work” must not become “guaranteed final grade.”

Compare reconstructed values with the matching Canvas-reported definition. Use an explicit precision/rounding tolerance, not a large unexplained forgiveness margin. A mismatch disables exact projections pending explanation; an agreement is a diagnostic, not proof every hidden policy is implemented. Return calculation basis, included/excluded items, assumptions, policy coverage, and discrepancy.

## 14. Freshness, permissions, change history, and synchronization

### 14.1 Coverage is first-class

Track success by course and resource type, plus pages consumed, time window, omitted fields, parser coverage, and last successful snapshot. A healthy server does not mean every course is current.

Never update `last_successful_refresh` after a failed attempt. Preserve successful results from other courses with an explicit partial marker. An empty visible result is meaningful only with adequate coverage for the question.

### 14.2 Reference freshness defaults

These are proposed configurable defaults, not measured promises:

| Data/use | Default rule |
|---|---|
| Imminent deadlines, submission checks, grade scenarios, calendar commits | Attempt relevant fresh read; clearly label inability to refresh. |
| Ordinary course/workload metadata | Up to 5-minute cache, with timestamp and coverage. |
| Modules/material listings | Up to 15-minute metadata cache; access validation remains separate. |
| Extracted content | Version/hash cache; current authorization required before retrieval. |
| Authorization lease during ordinary reads | At most 5 minutes since successful entitlement check, then fail closed if it cannot be renewed. |
| Known revocation/disconnect | Immediate denial; no stale-data grace period. |
| Opted-in background refresh | Proposed normal-condition target of 30 minutes, subject to measured quotas and load. |

A fresh course membership does not necessarily prove a particular locked file is accessible. Apply object-level policy. On permission failure quarantine/remove the affected index and cache; do not offer a cached copy as a bypass. Sensitive content reuse and high-consequence actions may require stricter checks than these defaults.

### 14.3 Change detection

Baseline complete collections before computing absence/deletion. Preserve source update time versus first/last observed times. Detect meaningful changed dates, requirements, rubrics, versions, announcements, and visible feedback/grades. Ignore cosmetic text changes for urgent alerts unless they affect meaning.

If a scan is partial, do not treat omitted objects as deleted or create a removal action. A 404 can mean access loss or provider behavior; avoid asserting why without evidence. Do not retain unauthorized old content solely to show a diff.

“What changed since yesterday?” requires a stored observation baseline covering that period. With no baseline, explain that only the current view is available; do not invent historical changes. A read must not silently acknowledge/dismiss changes.

### 14.4 Durable refresh

Use durable jobs with leases, principal/connection references, retry budgets, cancellation, and fencing against deleted connections. Incremental reads are resource-specific optimizations; periodic reconciliation remains necessary. Do not assume student credentials provide webhooks, Live Events, or a changed-since filter for every collection.

Separate on-demand queries from scheduled opt-in work. No job may revive a disconnected connection or write content after a deletion epoch. Queue recovery, migrations, and source outages must be tested before claiming ongoing sync.

## 15. MCP tools, optional skills, and ChatGPT interoperability

### 15.1 Contract principles

Use the official supported SDK and typed, bounded input/output schemas. Mark tool capabilities from actual behavior. Server authorization is mandatory regardless of client annotations. Surface only enabled capabilities; an unavailable feature should produce a useful limitation, not a plausible fabricated output. [E06]

Tool inputs accept authorized opaque references, bounded date windows, enumerated preferences, and constrained task data. Reject arbitrary identities, URLs, external recipients, code, and free-form API requests. Descriptions should say when to use a tool, what it does, important limitations, and whether it changes state. Avoid vague universal “academic agent” tools.

### 15.2 Proposed tool surface

Names are the reference contract. A verified existing implementation may preserve different names through an explicit compatibility mapping.

| Tool | Principal inputs | Output / effect | First gate |
|---|---|---|---|
| `get_connection_status` | optional owned connection reference | Minimal identity, institution support, selected scope, capability states, freshness, reconnect guidance | M0 |
| `list_courses` | owned connection, archive preference, cursor | Authorized student courses and enrollment states | M1 |
| `get_workload` | time window, selected course refs, status filters, undated/overdue options, cursor | Canonical obligations, effort/stakes evidence, source links, coverage | M1 |
| `get_assignment_details` | work reference | Requirements, rubric, own status/feedback, linked materials, conflicts | M1 |
| `get_changes` | since timestamp/baseline ref, scoped courses, cursor | Observed differences, old/new evidence, baseline limits | M1 basic; M3 scheduled |
| `get_course_outline` | course/module reference, cursor | Ordered modules, requirements, authorized material references | M2 |
| `get_announcements` | scoped courses, bounded period, cursor | Relevant source text and locators | M2 |
| `search_course_materials` | query, selected courses, source types, limit/cursor | Authorized source snippets, locators, extraction state | M2 |
| `fetch_course_material` | source reference, bounded page/slide/section continuation | Source text and coverage; never arbitrary external fetch | M2 |
| `get_gradebook` | selected course | Visible own grades, meanings, available policy, limitations | M1 basic; M2 full |
| `calculate_grade_scenario` | course, target/hypothetical scores, explicit assumptions | Nonpersistent deterministic result for supported rules only | M2 |
| `propose_study_plan` | workload snapshot, availability intervals, effort overrides, constraints | Ranked next actions or feasible draft blocks; no saved plan/calendar write | M1 next-action; M2 full |
| `update_study_preferences` | constrained patch of owned planning preferences | Authorized persistent local preference change and receipt | M2 |
| `record_personal_progress` | work ref, personal status/remaining-effort update | Local student annotation; never Canvas completion | M2 |
| `save_study_plan` | proposal ref/content, expected prior version | Explicit persistent local plan and version receipt | M2 |
| `preview_calendar_changes` | authorized destination, source snapshot, plan/event kind | Exact bounded operation preview; may persist preview state, no provider mutation | M3 |
| `apply_calendar_changes` | bound preview ref, operation idempotency reference | Authorized provider operations, per-item receipts or unresolved status | M3 |
| `get_operation_status` | owned operation reference | Durable/reconciled outcome; no guessed success | M3 |

Do not expose disabled future tools as if they work. `get_connection_status` includes enough identity information that a separate `get_profile` is optional, not required tool proliferation.

### 15.3 Key behavior contracts

**`get_workload`:** resolve date expressions outside the API into explicit bounds/timezone; include undated items separately when requested/defaulted. Aggregate source coverage, not just successfully returned items. Default result limits must have explicit continuation. A 100-item page limit is an output budget, not permission to drop remaining work. Do not automatically expose detailed grades/feedback for a simple deadline query.

**`propose_study_plan`:** accept only permitted task references and bounded availability/constraint data. When ChatGPT passes availability from a native Calendar tool, label it `provided_via_conversation`; the backend must not claim it independently verified the provider. Use minimum necessary free/busy windows rather than meeting titles. Default to stateless proposals. Returning a proposal does not write a calendar, update Canvas, or persist a new student preference.

**`fetch_course_material`:** recheck ownership and entitlement, return explicit extraction/continuation boundaries, and avoid serving hidden versions after access removal.

**Local-write tools:** require explicit user intent or a previously authorized narrow saving policy; return old/new version information. Use compare-and-set/version checks to prevent stale conversational updates overwriting newer choices.

**Calendar preview:** annotations must reflect any durable preview record. It is not externally destructive, but the word “preview” does not automatically make all implementation effects read-only.

### 15.4 Standard search/fetch compatibility

When a chosen ChatGPT surface requires the standard research/company-knowledge discovery interface, implement `search` and `fetch` to its current documented schema and output encoding, without adding incompatible required arguments. Preserve authorized URLs and source text. Domain tools remain useful in ordinary conversations even when that optional compatibility mode is not in scope. Test citations in the actual client; returning a URL is not proof a citation renders correctly. [E24]

### 15.5 Optional workflow skill

A supported bundled skill may improve reliable tool use without creating another chatbot. It should guide ChatGPT to check connection state, retrieve relevant data, disclose coverage, distinguish facts from assumptions, use available native Calendar tools when authorized, and require real action results. Skills are guidance, not an enforcement boundary. Package and test them using the current supported plugin mechanism. [E25]

Do not embed privileged instructions or hidden tools in course content. Do not claim a skill forces every future model response to be correct. Evaluate the full installed plugin, not only isolated endpoint calls.

### 15.6 Native interoperability acceptance

In a real supported ChatGPT conversation:

1. Retrieve actual authorized Canvas work through this connector.
2. Use an independently available Calendar capability to obtain relevant availability when permitted.
3. Produce a plan using both results, with no token exchange between services.
4. On an explicit calendar request, follow the available Calendar tool's authorization/confirmation rules and report its actual result.
5. Repeat with Calendar absent, read-only, expired, or denied; maintain useful Canvas support without pretending to schedule.

Do not advertise interoperable calendar scheduling from a mocked tool transcript. If the host cannot orchestrate the needed combination, record that as a compatibility gap and use a separately authorized adapter only after its own gate passes.

## 16. Calendar actions, confirmation, and durable reconciliation

### 16.1 Three different capabilities

| Mode | Meaning | Product role |
|---|---|---|
| Calendar export | A static file/snapshot that a user may import | Optional fallback; clearly not ongoing synchronization |
| Native conversational handoff | ChatGPT uses an existing authorized Calendar capability | Preferred early interoperability path; receipts belong to that tool |
| Connector-owned Calendar adapter | Bridge holds an independent provider grant and durable mappings | Optional path for dependable unattended sync and recovery |

Keep capability and support claims separate. Native handoff does not populate a trustworthy server action ledger unless a real receipt is supplied and verifiably associated; it must not be retroactively claimed as Bridge-owned synchronization.

Reference provider for connector-owned sync: Google Calendar, with the least necessary supported scopes and any required provider verification. Request event-write access only when the student enables writes. Use a dedicated student-selected calendar by default; an existing destination requires its own permission and ownership review. [E18, E19]

### 16.2 Event semantics

Deadlines, class/exam events, and study blocks are different event kinds. A deadline does not become a two-hour study session. The displayed deadline marker duration must be documented as a display choice; do not move the deadline to avoid a conflict.

Date-only source events stay all-day dates unless the user explicitly supplies a reminder time. Unknown/ambiguous dates do not become fabricated events. An instructor-changed deadline updates the corresponding marker under the user's chosen sync policy; proposed study time may be moved only within its authorization.

Detect existing Canvas-feed/import duplicates before enabling connector-owned creates. Never delete or overwrite another integration's events to solve that problem. Offer disabling one path or choosing an isolated calendar through an authorized configuration action.

### 16.3 Preview → authorize → commit → receipt

The exact preview includes principal, source snapshot/version, calendar destination, date/timezone, privacy level, event kind, creates/updates/deletes, affected IDs, conflicts, and expiration. Reference preview lifetime: 10 minutes, configurable and revalidated at commit. Store a hash of normalized operations, not just natural-language intent.

A clear original request may already provide adequate authorization; do not add redundant “are you sure?” prompts when the supported host has correctly captured it. However, a model argument such as `confirmed: true` is not an independent proof of user consent.

Implement a **tested approval adapter** with one of two supported paths:

- A documented host-enforced authorization/confirmation mechanism whose behavior for the exact operation is verified and recorded.
- An authenticated approval surface, preferably inline in ChatGPT, that binds the user's approval to the immutable preview and writes a server-side authorization record. A minimal external authorization page is permissible only when the supported host cannot supply the required control.

Do not invent an MCP signed-consent field or assume a natural-language transcript is independently verifiable by the server. When neither path can enforce the required authorization, leave consequential writes disabled. OAuth write scope is an access grant, not automatic approval for any future event mutation.

Changes to destination, sharing, source dates, operation set, or material event details after authorization require revalidation and renewed approval where the prior authorization no longer covers them. Background sync uses an explicitly enabled, bounded standing policy—not an unlimited implied consent.

### 16.4 Operation state machine

```text
proposed -> authorized -> executing -> succeeded
                              |----> partial_success
                              |----> failed
                              |----> uncertain -> reconciling -> resolved
proposed/authorized -> expired | cancelled | source_changed
```

Validate principal ownership, connection state, source snapshot, scope, expiry, event ownership, and current calendar state before commit. Serialize overlapping operations for the same owned event and use durable operation IDs.

Create a stable mapping keyed by principal, institution connection, canonical work identity, destination, and event kind. Use provider-supported deterministic event IDs/idempotency features where appropriate, plus your own durable action records; do not claim universal exactly-once execution. Google documents client-supplied event IDs and version-aware updates; conform to its actual constraints. [E18, E21]

If a create may have succeeded but the response was lost, reconcile by the intended event identity before retrying. Do not send an unbounded duplicate create. An unresolved provider outcome must remain `uncertain`, with a recoverable operation reference.

Receipts include provider, destination identifier, event identifier/link, result state, provider version when available, and completion/observation time. A successful queue insertion is not a provider-success receipt. Report partial batch results per item.

### 16.5 Conflicts, user edits, deletion, and undo

Track source version, last synced provider version, connector-owned fields, and detected user edits. Respect provider conditional updates where available. Default to preserving student edits and asking/showing the conflict rather than silently overwriting them. Support a documented reset/resume-sync choice. [E21]

Only operate on owned events within the authorized destination and purpose. Never auto-delete events because a Canvas scan was incomplete. Access loss stops content propagation and future actions; calendar cleanup requires the approved lifecycle policy and valid calendar authority.

Undo is a new authorized compensating operation, not guaranteed rollback of an external system. Restore only the connector's changes when current versions make that safe. Preserve unrelated edits and explain when a conflict prevents reversal.

### 16.6 Durable sync and destination privacy

Store mappings, cursors/checkpoints, and operation outbox durably. Handle provider cursor invalidation with documented full reconciliation; full resync must preserve ownership and avoid duplicate creates. [E20]

Preview destination sharing when the provider exposes it. Offer neutral titles and minimal descriptions; omit grades, private feedback, and classmates' names. Do not add attendees or send invitations unless specifically authorized as a separately reviewed capability; attendee creation is out of scope for the first calendar release.

Students can pause sync, change scope, disconnect, and choose whether to retain already-created events. Disconnect must not silently purge their calendar, and retaining events must not keep a background sync grant alive.

## 17. Notifications and background behavior

No on-demand MCP tool inherently proves a scheduling or notification channel exists. Implement background features only with a supported scheduler and a tested delivery path. Never promise that the server can spontaneously post into an ordinary ChatGPT conversation.

Allowed approaches are a verified supported ChatGPT task/event mechanism or a separately authorized channel such as email. Platform capabilities must be checked at implementation and release; do not assume an experimental feature is available to all accounts.

Require explicit opt-in, verified destination, timezone, quiet hours, frequency limits, pause/stop controls, and deduplication. Default notification content should avoid grades and sensitive details on lock screens/shared inboxes. Limit alerts to actionable changes and chosen summaries, not every refresh.

Use deterministic messages initially without a separate AI API bill. If later unattended model-written summaries are proposed, treat them as an optional provider/cost/privacy project, never a prerequisite for core student workflows. Test restart recovery, duplicate delivery suppression, revoked authorization, and unsubscribe while messages are queued.

## 18. Privacy, retention, FERPA, and accessibility

### 18.1 Data-flow inventory and live-data gate

Document each category from Canvas through normalization, parsing, search, ChatGPT tool results, optional Calendar, notifications, logs, exports, and backups. Record purpose, access control, recipient, location, retention, deletion behavior, and provider agreement/control where applicable.

Minimize records about other students. Default discussions support topic/instructor instructions without bulk-ingesting peers' posts. Do not ingest clinical PHI, government identifiers, payment credentials, or unrelated restricted information as course material without a separately reviewed lawful and platform-permitted design. A link accessible in Canvas does not settle downstream processing permission.

Do not assert that all ChatGPT plans have identical data-use/training settings. Deployment documentation must identify the actual user/workspace controls and relevant provider terms. No blanket “never used for training” promise without verified applicable controls.

### 18.2 FERPA positioning

Distinguish a student-directed service from an institution-contracted deployment. OAuth demonstrates an access grant, not complete legal authorization for every downstream use. Institutional arrangements relying on the school-official exception require the institution to assess the relevant conditions, including the outsourced function, educational interest, direct control, and restrictions on use/redisclosure. Do not market an automatic FERPA certification because OAuth and encryption are present. Obtain qualified institutional/privacy review for the actual arrangement before its release. [E22]

This specification is an engineering review requirement, not a legal determination. Jurisdictions, age groups, and cross-border use outside the reviewed launch scope remain unsupported until assessed.

### 18.3 Proposed retention defaults

These defaults are design proposals requiring owner/privacy approval before real-student deployment. Public policy must state the actual configured durations, not vague “as necessary” language.

| Data | Proposed default | Required behavior |
|---|---|---|
| Raw downloaded documents | Delete after extraction; failed-job temporary storage at most 24 hours | Encrypted private temporary storage; no durable raw archive by default |
| Derived document text/index | Selected active courses; purge within 30 days of deselection/term retirement unless the user chooses an authorized archive policy | Access disabled immediately on scope/permission loss; retention does not imply availability |
| Current normalized coursework | While selected and authorized, then same course-purge policy | Do not retain indefinitely by accident |
| Change history | 30 days | Preserve only justified fields; remove inaccessible content |
| Redacted operational logs | 7 days | No assignment text, credentials, full URLs with secrets, or routine personal identifiers |
| Minimal action/security records | Proposed 90 days, with a separately reviewed purpose and field set | Avoid grade/material content; document deletion exceptions if legally required |
| Encrypted backups | Proposed maximum 30 days | Deletion tombstones/fencing applied before restored data can be served |
| Credentials after disconnect | Immediately disabled and removed from active use; revoke remotely where supported | No delayed job may revive them |
| Full account deletion | Immediate access disable; active-store purge target within 24 hours; backup expiry per disclosed policy | Report completion/limitations, not an unsupported promise of instantaneous universal erasure |

Raw Canvas API response dumps are not a backup strategy. Saved personal plans/preferences have an explicit user-controlled lifecycle; disconnect must explain whether they are deleted or retained as disconnected local records under the selected policy.

### 18.4 Deletion/export acceptance

Authenticated export contains only the student's own retained records with provenance, using short-lived protected delivery. Protect against spreadsheet formula injection if providing CSV exports. Deletion covers credentials, derived text, embeddings if any, caches, pending jobs, aliases, previews, and notification subscriptions, not just a user row.

Use a deletion epoch/tombstone checked by workers and restore procedures. Test deletion while parsing, refreshing, exporting, or committing an action. Do not promise deletion of copies already present in ChatGPT conversations, downloaded files, provider logs, or independently created calendar events; explain which system controls each copy.

### 18.5 Accessibility and mobile

Owned auth/settings/approval surfaces and optional inline components target WCAG 2.2 AA. Test keyboard navigation, screen-reader semantics, focus, contrast, error messages, reflow, non-color status, and date/timezone clarity. ChatGPT is outside the project's direct UI control; record client-specific limitations instead of claiming ownership of its accessibility. [E23]

Every academic workflow has a conversational text path. No hover-only explanations, desktop-only interactions, or mandatory spreadsheet-like dashboard. Test actual supported mobile ChatGPT clients, not only a narrow browser viewport. Public mobile claims require end-to-end evidence; an available web path does not prove iOS/Android support.

## 19. Operations, hosting, maintenance, and measured targets

### 19.1 Baseline before pilot

Separate synthetic staging from production; use managed secrets, encrypted backups, redacted observability, health/readiness checks, dependency and secret scanning, constrained parser execution, and emergency disable controls for external writes and scheduled jobs. A public health endpoint must not expose student identity or course counts.

Test clean deployment, migrations, rollback, backup restore, reconnect, and deletion recovery. Track ownership for incidents, vulnerability reports, quota changes, and upstream API/client-contract changes. Do not leave a public academic service dependent on an unmonitored personal laptop.

### 19.2 Proposed performance objectives

These are test targets from the handoff/consolidation, not service guarantees or estimates of development completion:

| Objective | Initial target | Measurement boundary |
|---|---|---|
| Critical correctness fixtures | All pass | Identity, dates, source mapping, exact supported arithmetic, unauthorized-action rejection |
| Cached read-only backend tools | p95 below 2 seconds | Excludes ChatGPT generation, network path to client, and cold provider fetches |
| Interactive refresh response | Return useful result or explicit partial/status within 15 seconds | Do not conceal an unfinished course scan |
| Opted-in refresh lag | Normally within 30 minutes | Report upstream outages, queue delays, and quota constraints |
| Connector-owned endpoint availability | Initial monthly target 99.5% | Separate own availability from Canvas/Calendar dependency failures |
| Cross-user disclosure / unauthorized writes | Zero tolerated in acceptance tests | Any reproducible critical failure blocks release |

Benchmark representative course counts, large reading bundles, concurrent students, slow institutions, and degraded providers before publishing promises. Platform generation behavior is not fully controlled by the backend; do not claim a universal zero-hallucination guarantee from a passed evaluation set.

### 19.3 Monitoring and cost

Measure backend latency, request budgets, failed authorization, stale/partial course ratios, queue age, parser coverage, retry exhaustion, uncertain actions, deduplication, deletion backlog, and support workload. Prefer aggregate metrics without assignment bodies or per-student behavioral tracking. Any essential security telemetry with identifiers needs disclosure and a retention purpose.

Publish measured infrastructure cost per active student and its assumptions: requests, parsing, storage, egress, backups, identity provider, notifications, and support. Introduce fair technical quotas with clear explanations, not paid academic tiers. Large-file work should not starve critical deadline queries.

Pin supported SDK/protocol versions and maintain compatibility checks. Watch vendor changelogs; stage updates, rerun critical journeys, and update support documentation. A once-passing test is not permanent certification.

## 20. Prioritized requirements matrix and traceability

**P0:** foundation before real-student pilot or before enabling the relevant foundational capability.  
**P1:** completes the intended product or prepares supported public distribution; each feature must pass its own gate.  
**P2:** evidence-led expansion after the core service is dependable.  
**U:** implementation verification is UNKNOWN in this handoff. It does not mean absent, broken, or complete.

R01–R33 preserve the review handoff's identities and priorities. Acceptance wording is consolidated here and linked to test cases in §21. New R34–R43 make the latest product constraints explicit. An optional disabled capability does not have to block unrelated read-only functionality, but its tests cannot be waived while advertising that capability.

| ID | Priority | Requirement and acceptance evidence | Gate | Tests | State |
|---|---|---|---|---|---|
| R01 | P0 | Identity/tenant isolation: principal and school resolved server-side; guessed IDs never expose another record. | M1 | T13, T21, T26, T39 | U |
| R02 | P0 | Canvas linking: approved OAuth path; cancellation, revocation, reconnect, and two-school credential separation behave correctly. | M1 | T14, T18, T43 | U |
| R03 | P0 | Complete scoped inventory: all pages or explicit partial coverage; deduplication, archived/inaccessible and undated work handled. | M1 | T01, T07, T10, T46 | U |
| R04 | P0 | Student-specific dates: effective individual/section/group/overlap cases match student context; opens/due/closes separate. | M1 | T02, T03, T04 | U |
| R05 | P0 | Completion states: submitted/ungraded/late/missing/excused/revision/offline/personal progress distinct. | M1 | T06, T07 | U |
| R06 | P0 | What-first recommendation: useful feasible next action, ranked alternatives, evidence and uncertainty. | M1 | T20, T41, T29 | U |
| R07 | P0 | Honest grading: reported values preserved; known rule coverage; no false exact impact when policy is incomplete. | M1 | T08, T28 | U |
| R08 | P0 | Effort uncertainty: remaining-work ranges, editable origin, unknowns; no authoritative points-to-hours conversion. | M1 | T20, T41 | U |
| R09 | P0 | Evidence/explainability: each academic fact has provenance/time; ranking states why and what could change it. | M1 | T11, T29, T45 | U |
| R10 | P0 | Least privilege: feature/route/scope inventory; student-only academic reads even with powerful token. | M1 | T21, T22, T39 | U |
| R11 | P0 | Credential safety: no leaks; encrypted storage; rotation, refresh locks, revocation/disconnect tested. | M1 | T14, T23, T43 | U |
| R12 | P0 | MCP/ChatGPT contract: Inspector plus actual supported conversation; auth, schemas, cancellations, bounded output, version record. | M0→M1 | T21, T30, T35 | U |
| R13 | P0 | Untrusted content/network: injection cannot authorize actions; SSRF, redirects, unsafe parsers bounded. | M1 | T12, T23, T24 | U |
| R14 | P0 | Reliable reads/freshness: outages and incomplete pages become partial/stale states, never “nothing due.” | M1 | T01, T15, T29 | U |
| R15 | P0 | Privacy/suitability: reviewed flow, consent, retention, disconnect, export, deletion before live records. | M1 | T18, T24, T34, T43 | U |
| R16 | P0 | Accessibility/usability: owned UI targets WCAG 2.2 AA, keyboard/screen-reader path, zone clarity, text fallback. | M1 | T19, T36, T42 | U |
| R17 | P0 | Foundational quality: critical identity/date/permission fixtures pass; evaluation set never invents deadline/action success. | M1 | T01–T04, T12–T16, T29 | U |
| R18 | P0 | Production baseline: health, redaction, budgets, secrets, restore, rollback, incident owner. | M1 | T15, T34, T35, T40 | U |
| R19 | P1 | Study/replanning: respect time, commitments, dependencies, breaks, capacity; retain student choices. | M2 | T20, T41, T42 | U |
| R20 | P1 | Syllabus/files: declared format coverage; page/section citations; honest scan/table/equation/image limits. | M2 | T11, T25, T45 | U |
| R21 | P1 | Course breadth: modules/pages/announcements/discussions/rubrics/quiz metadata to verified student-access level; external limits visible. | M2 | T07, T10, T24, T46 | U |
| R22 | P1 | Calendar preview: destination, zone, exact operations/conflicts; deadlines separate from study blocks; no invented dates. | M3 | T05, T31, T32, T46 | U |
| R23 | P1 | Calendar commit/recovery: actual receipts, idempotent retries, recoverable partial/uncertain states, owned-event boundaries. | M3 | T16, T17, T31, T32 | U |
| R24 | P1 | Ongoing sync: source/access changes and completion reconciled durably; independent of open chat/laptop. | M3 | T09, T15, T18, T27, T32 | U |
| R25 | P1 | Notifications: opt-in, verified channel, quiet hours, deduplication, caps, pause/stop. | M3 | T18, T33, T43 | U |
| R26 | P1 | Public onboarding/support: supported-school beginner succeeds; unsupported school gets truthful admin/support path. | M4 | T14, T38, T44 | U |
| R27 | P1 | International/multi-school: zones, DST, Unicode, simultaneous school accounts; published support boundaries. | M4 | T04, T13, T19, T42 | U |
| R28 | P1 | Capacity/deployment: measured latency, availability, lag/cost; quotas, worker recovery, migrations, rollback. | M4 | T15, T35, T40 | U |
| R29 | P1 | Documentation: student/admin/operator/contributor guides, scopes, privacy, recovery, limitations; clean-guide test. | M4 | T35, T44 | U |
| R30 | P1 | Open-source release: approved license, notices, fixtures, contribution/security policies, releases, reproducible builds; no private data. | M4 | T35, T37, T38 | U |
| R31 | P1 | ChatGPT distribution: eligibility resolved, actual plan/workspace path tested, review/listing approved where required. | M0 feasibility→M4 approval | T30, T38, T44 | U |
| R32 | P2 | Advanced study: source-backed practice/spaced repetition/calibration with user controls and usefulness evidence. | M5 | New feature-specific fixtures required | U |
| R33 | P2 | Additional roles/providers: distinct authorization models and tested compatibility, not inferred from API existence. | M5 | Extend T13, T21, T39 | U |
| R34 | P0 | ChatGPT-native identity: all core academic journeys completed in normal conversations; no custom chatbot replacement. | M1 onward | T30, T36 | U |
| R35 | P0 | No duplicate AI or student AI billing: baseline works without model API keys, inference subscriptions, or model-hosting layer. | M1 onward | T37 | U |
| R36 | P0 | No external academic dashboard: external UI limited to allowed administrative/authorization needs; text path works. | M1 onward | T19, T36 | U |
| R37 | P0 | Native interoperability: actual Canvas-plus-Calendar composition tested; no credential reuse; absent Calendar handled honestly. | M1 supported path | T30 | U |
| R38 | P0 | Low-friction supported pilot onboarding: no token paste for other students; no mandatory paid account; minimum identity ceremony. | M1 | T14, T37, T44 | U |
| R39 | P0 | Early access/distribution risk gate: G0–G5 recorded; no universal support/listing claim while eligibility or institution access is unknown. | M0 onward | T38 | U |
| R40 | P0 | Evidence ledger: implemented/verified/planned/blocked distinguished with references, version, environment, and limitations. | M0 onward | Evidence audit | U |
| R41 | P0 | Funding/product boundary: no freemium academic tiers, data monetization, sponsored rankings, or student upsell dependency. | All releases | T37, policy review | U |
| R42 | P1 | Search/fetch/citations: exact supported compatibility interface and rendered citations verified when advertised. | M2 targeted surfaces | T25, T26, T45 | U |
| R43 | P0 | Lifecycle honesty: local disconnect, remote revoke, pending operations, deletion and independent copies handled distinctly. | M1; extend M3 | T18, T34, T43 | U |

### 20.1 Evidence ledger

Use a machine-readable registry with these independent axes:

- `delivery_state`: `planned`, `in_progress`, `partial`, `implemented`, `deferred`, or `blocked`.
- `verification_state`: `UNKNOWN`, `REPORTED`, `VERIFIED`, or `FAILED`.
- `verification_scope`: precise capability, institution, role, environment, SDK/protocol version, ChatGPT plan/workspace/surface, and dependency conditions.

A README or developer assertion is REPORTED, not VERIFIED. An implementation path plus relevant reproducible tests/observed behavior is needed for VERIFIED. Fixture verification cannot be presented as real-institution verification. A reproducible failure is FAILED for the affected scope, even if other environments pass.

Minimum record:

```yaml
requirement_id: R04
owner_role: integration_lead
delivery_state: planned
verification_state: UNKNOWN
implementation_refs: []
test_refs: [T02, T03, T04]
test_results: []
commit_sha: null
environment: null
institution: null
student_role: null
chatgpt_surface_and_plan: null
observed_at: null
limitations: []
blocker: null
next_proof_required: Student-context date fixtures and authorized live comparison
```

This is a schema example, not an executed test. Initially all implementation requirements remain UNKNOWN unless an actual repository audit establishes otherwise. Do not publish an implementation-readiness percentage from this document.

## 21. Acceptance tests and evaluations

### 21.1 Synthetic-first fixture suite

T01–T20 explicitly preserve the uploaded review's 20 critical scenarios, in the same order. Additional cases close the alignment and implementation gaps. Tests must specify inputs, expected structured output, forbidden side effects, and retained/deleted state.

| Test | Scenario | Required outcome |
|---|---|---|
| T01 | Multiple course/assignment pages; middle page fails | Complete results only when all required pages succeed; otherwise partial coverage; no false removals. |
| T02 | Individual, group, section and overlapping overrides | Student-effective opens/due/closes match the authorized student's Canvas view. |
| T03 | Explicit no due date vs field missing/denied/not refreshed | Distinct states and no invented timestamp. |
| T04 | Due/close differ; DST gap/overlap; local midnight | Correct instant/date rendering, no accidental day shift, separate availability. |
| T05 | Instructor changes extension after calendar preview | Commit rejects stale operation or requires reauthorized revised plan; no old-date write. |
| T06 | Submitted/ungraded, late, excused, revision, paper work | Accurate orthogonal states; no generic “unsubmitted” inference from missing upload. |
| T07 | Planner completion conflicts with actual coursework | Keep personal completion separate; deduplicate source representations. |
| T08 | Weights, drops, extra credit, absent grade policy | Correct supported math or explicit unsupported/unknown result; never false precision. |
| T09 | Cached module/file loses permission | Access stops; index/cached content cannot bypass revocation. |
| T10 | Classic quiz, New Quiz, external-tool representations | One obligation when linked; feature-specific metadata limits; no attempts or locked questions. |
| T11 | Scan, table across pages, conflicting syllabus date, unsupported file | Correct extraction coverage and source conflicts; no invented content. |
| T12 | Course text requests token disclosure or record export | No authority gained; no secret leak or unapproved cross-tool/calendar action. |
| T13 | Same numeric IDs at different schools/users | No collision across storage, cursors, search, jobs, action mappings, or exports. |
| T14 | OAuth expiry/race, revoked scopes, denied school key | Safe refresh/reconnect, no wrong-school token reuse, no retry storm. |
| T15 | Throttling, slowness, restart, interrupted reconciliation | Bounded retries, durable recovery, unchanged last-success marker on failure. |
| T16 | Calendar create accepted remotely; response lost | Reconcile intended identity before retry; no duplicate; uncertainty reported until resolved. |
| T17 | Student edits synced event or changes shared destination | Preserve edits or show conflict; do not silently overwrite or leak details. |
| T18 | Disconnect/delete while parser, sync, or action jobs are queued | Epoch/authorization checks prevent resurrection; pending outcome resolved safely. |
| T19 | Keyboard/screen reader, small screens, locale variations | Core journeys usable; no color/hover-only status or unannounced focus loss. |
| T20 | More work than usable study time | Explicit shortfall; no double-booking, overlap, or falsely feasible plan. |
| T21 | Missing auth, wrong audience/subject, foreign resource refs | Denial without leaking private records or existence through snippets. |
| T22 | Canvas academic write request, including disguised routes | Rejected; narrowly permitted OAuth lifecycle operations still work. |
| T23 | Malicious URL/redirect/DNS, oversized file, ZIP traversal/bomb | Request blocked or bounded; no internal-network access/credential forwarding/execution. |
| T24 | Peer posts or sensitive unrelated content included upstream | Minimize/exclude according to scope; no automatic bulk peer-content ingestion. |
| T25 | Replacement file, same filename, long document continuation | Correct version and locators; truncation/extraction coverage visible. |
| T26 | Search across unauthorized institutions/courses | No cross-scope hits, titles, snippets, counts, or shared-index leakage. |
| T27 | First scan, repeated scan, no historical baseline | First observed distinct from new; no duplicate changes or invented yesterday-state. |
| T28 | Grade formula boundaries and reconciliation | Fixture result correct; zero remaining points, impossible targets and mismatches handled explicitly. |
| T29 | Natural-language “am I caught up?” during partial outage | Answer qualifies coverage; no “nothing due” or invented missing records. |
| T30 | Real ChatGPT Canvas+native Calendar; absent/denied Calendar variant | Actual supported composition, source-grounded plan, no token transfer or phantom action. |
| T31 | Forged approval, expired preview, different principal, changed destination | Unauthorized commit denied; no invented confirmation primitive or reused approval. |
| T32 | Repeated sync, existing Canvas feed, unrelated user event | Stable owned mapping; duplicates prevented; foreign events untouched. |
| T33 | Duplicate notification, quiet hours, paused/expired destination | Correct suppression/delivery; unsubscribe stops queued future sends. |
| T34 | Retention expiry and restore from pre-deletion backup | Tombstones applied before serving; no deleted content reappearance. |
| T35 | Clean container/operator deployment, migration, restore, rollback | Documented reproducible operation; no manual undisclosed source edits. |
| T36 | Every core workflow with inline UI disabled | Works in conversational text; no external academic dashboard required. |
| T37 | Network/dependency/config audit for paid AI or subscription path | Baseline requires no separate model API key, student-paid account, upsell, or hidden inference call. |
| T38 | Unsupported school/plan/distribution route or unapproved listing | Accurate blocked/limited state and documentation; no claim of universal/public approval. |
| T39 | Upstream token has instructor/admin powers | Same student-only product allowlist; no roster/other-student/grade-write access. |
| T40 | Concurrent students, heavy parser queue, quota exhaustion | Isolation and fair budgets; critical reads responsive; measured latency/lag/cost. |
| T41 | 45-minute request, unknown estimates, repeatedly deferred large task | Useful bounded subtask; ranges/assumptions visible; avoid starvation of urgent large work. |
| T42 | Travel timezone, date-language ambiguity, calendar unavailable | Narrow clarification or explicit assumption; no fabricated local instant or free time. |
| T43 | Disconnect with provider down and uncertain action in progress | Local access stops; remote revoke/outcome reported separately; no silent calendar purge. |
| T44 | New nontechnical student follows only published guide | Supported connect→first-answer→help→disconnect without coding, personal token paste, or extra AI payment. |
| T45 | Request for a source quote/figure claim not in extracted evidence | Faithful quotation/location or clear limitation; no false citation/visual interpretation. |
| T46 | Undated offline obligation, syllabus-only event, discussion sub-deadlines | Obligations remain discoverable; dates/classification preserve source and uncertainty. |

### 21.2 Separate test layers

**Deterministic tests:** schema validation, identity/ACLs, dates, arithmetic, sorting, constraint allocation, retry/idempotency, provenance, parser boundaries, deletion, and state transitions. Prefer precise expected outputs and property-based edge cases for time math and isolation.

**Contract/integration tests:** real supported SDK transport/auth discovery; provider sandbox fixtures; schema changes; rate-limit and timeout behavior; capability negotiation; normal and canceled requests.

**Conversational evaluations:** direct requests, paraphrases, follow-ups, ambiguous course aliases, unsupported requests, malicious course text, source conflicts, partial data, user corrections, and “did it happen?” questions. Assess correct tool selection, useful recommendations, faithful explanations, no invented facts, and real receipts.

**End-to-end tests:** install/link→select courses→first answer→what first→materials→plan→calendar action where enabled→reconnect→disconnect, on each advertised ChatGPT surface. Record actual entitlement and workspace policy; do not infer them from a plan label.

**Human usefulness pilot:** compare recommendations with students' judgments and record reasons for disagreement. Proposed evaluation cohort: at least eight consenting students across two independently authorized institutions before a multi-institution public-support claim. This is a design target, not a representative statistical guarantee. Measure successful task completion, time spent finding requirements, useful next actions, corrections needed, and sustained voluntary use. Engagement alone is not success.

Suggested UX exit target: at least 80% of pilot participants complete install-to-first-correct-answer and a basic planning journey using only the guide without developer intervention; investigate every safety/correctness error regardless of aggregate rate. Results must be measured, not fabricated to meet the target. A smaller single-school controlled pilot is allowed before this wider gate.

### 21.3 Hard release blockers

Any confirmed cross-user disclosure, wrong student-effective deadline in critical fixtures, unauthorized write, leaked credential, material false action-success claim, missing-data-as-empty behavior, or deletion resurrection blocks the affected release until fixed and regressed. Grade-specific failures can disable exact scenarios without disabling safe reads. Calendar-specific failures keep writes off. Unresolved public policy blocks public listing claims, not unrelated synthetic engineering.

## 22. Milestones, dependencies, and exit evidence

Milestones are dependency- and evidence-based, not invented calendar estimates. Roles can be held by the same person; they identify responsibility, not a claim that a staffed team exists.

### M0 — Consolidated specification, repository audit, and feasibility proof

**Owners:** product owner, integration lead, security/privacy owner.

Inspect any actual implementation and populate the evidence ledger. Record ADRs for identity, runtime/storage, institution registry, ChatGPT connection path, calendar modes, distribution policy, and data flow. Build a synthetic MCP vertical slice, then—only with proper private setup and authorization—one selected-course real read through ChatGPT.

**Exit:** this spec is translated into tracked requirements; G0 has observed evidence; G1 access feasibility and G2 public-policy risk have owners/status; no secrets in chat; token/source/synthetic records cannot cross boundaries. Actual first read proves title, effective date, and source link, not every later capability. If blocked, report it and continue independent tests rather than fake the integration.

### M1 — Trustworthy, useful Canvas-read-only student pilot

**Owners:** integration/backend lead, QA, security/privacy owner, operator.

Deliver OAuth-supported pilot onboarding, scoped courses/work inventory, individual dates/states, assignment details, basic visible grades, next-action recommendations, basic change snapshots, source provenance, partial-data handling, core native Calendar interoperability, and pilot operations.

**Exit:** R01–R18 and applicable R34–R41/R43 pass for the stated pilot configuration; OAuth is required for other students; live-data/privacy arrangements are approved; no external academic dashboard; no model API key; actual ChatGPT journey and negative tests pass. Exact grade scenarios, broad material extraction, connector-owned Calendar writes, and notifications may remain disabled.

### M2 — Course knowledge and constraint-aware planning

**Owners:** retrieval/planning lead and QA.

Deliver verified modules/pages/announcements/files, source manifests and search, syllabus conflict handling, full time-aware plan proposals, explicit local preferences/progress/plan persistence, and grade scenarios for supported tested rule subsets only.

**Exit:** R19–R21 and relevant R42 tests pass. A student can get a useful evidence-backed class briefing and a feasible plan, or an honest shortfall/limitation. Unknown policies block exact grade projections. No unsupported format or unread figure is claimed understood.

### M3 — Authorized Calendar adapter, durable sync, and optional notifications

**Owners:** calendar/actions lead, security, operator, QA.

Add independent provider OAuth only when requested, precise previews, enforceable authorization, durable receipts, uncertain-operation recovery, source/event ownership mapping, reconciled sync, and opt-in notifications.

**Exit:** enabled R22–R25 capabilities pass, particularly T05/T16–T18/T31–T34/T43. A repeated or interrupted sync does not duplicate events. Confirmation is tied to real authorization, not a Boolean supplied by a model. Notification delivery is observed, not assumed from queue success.

### M4 — Supported public/institution-managed distribution

**Owners:** product owner, institutional-access lead, privacy/security, operator, maintainer.

Resolve public connector eligibility; obtain required provider/institution authorization and listing approval. Complete nontechnical onboarding, mobile and accessibility tests, international/timezone support records, measured cost/capacity, guides, license, vulnerability reporting, demo environment, and release packaging.

**Exit:** R26–R31 pass for the advertised scope; G2 resolved for the exact route; advertised multi-school support has independently authorized tests at more than one institution; demo/reviewer access uses synthetic sample data, never a real student's account. Source release is not directory approval. Calendar may stay disabled if its gate is unmet; listing text must say so.

**Original-file delivery follow-up (22 October 2026):** Complete the applicable
[C12-D01–C12-D06 public-release download tickets](evidence/implementation-tickets.md#public-release-download-roadmap--october-22-2026)
before advertising original-file downloads. These cover the development-tunnel
interstitial, capability-aware download actions, native attachment feasibility,
private-link lifecycle, production availability, and actual client acceptance.
The owner's reported browser download is bounded private-use evidence. Native
attachment may remain deferred with truthful scope; a working, verified browser
fallback is required wherever advertised. These tickets do not resolve G1 or G2.

### M5 — Evidence-led expansion

Add R32–R33 capabilities only after feedback shows useful demand and sustainable operation. Possible extensions: calibrated effort estimates, source-backed spaced practice, additional calendar providers, multilingual support, more institutions, or separately authorized roles. No extension may reintroduce a standalone chatbot, academic dashboard, student AI subscription, or generic privileged Canvas proxy.

## 23. Repository, documentation, and implementation tickets

### 23.1 Reference repository layout

Adapt existing verified code; do not create empty folders and declare completion.

```text
canvas-bridge/
  Codex_Spec.md
  README.md
  AGENTS.md
  pyproject.toml + dependency lockfile
  Dockerfile + compose.yaml
  .env.example + .gitignore
  src/canvas_bridge/
    app.py
    auth/          # MCP authorization, Canvas linking, approval adapter
    policy/        # principal, school/course/resource, route and outbound rules
    canvas/        # API client, capabilities, pagination, normalization
    domain/        # facts, dates, states, conflicts, changes
    planning/      # priorities, effort, capacity, validation
    grades/        # supported policies, exact calculations, reconciliation
    retrieval/     # manifests, downloads, constrained parsing, locators, search
    tools/         # typed MCP tools and optional compatibility adapters
    storage/       # models, scoped repositories, migrations, ledger
    jobs/          # refresh, retention, outbox, deletion fences
    calendar/      # optional provider grants, previews, actions, reconciliation
    notifications/ # optional deterministic delivery
    settings/      # minimal auth/config/privacy/support; not academic dashboard
  plugin/          # supported manifest/skill packaging when applicable
  tests/
    unit/ contract/ integration/ security/ e2e/ evaluation/
    fixtures/synthetic/
  scripts/
    doctor, seed_synthetic, verify_read, backup, restore, purge, benchmark
  docs/
    architecture-decisions/
    institution-support-matrix.md
    platform-compatibility-matrix.md
    capability-scope-matrix.md
    tool-contracts.md
    threat-model.md
    data-flow-retention.md
    privacy-policy.md
    student-guide.md
    institution-admin-guide.md
    operator-guide.md
    contributor-guide.md
    distribution-review.md
    runbooks/
  evidence/
    requirements.yaml
    test-index.yaml
    sanitized-results/
    release-gates.md
```

Use configuration placeholders only in `.env.example`. Real credential values belong in private operator secrets. No real institution username, token, course body, grade, or backup in repository history or example test artifacts. Keep packaging syntax aligned to current platform documentation rather than guessing from an older sample.

### 23.2 First dependency-ordered tickets

| Ticket | Owner role | Deliverable / done condition | Dependencies |
|---|---|---|---|
| C01 | Product/QA | Audit supplied repository; register R01–R43 with truthful evidence states and gaps. | This spec; repository if available |
| C02 | Integration | Platform/institution/public-policy feasibility records; verified current contracts and blockers. | C01 |
| C03 | Security/architect | Threat/data-flow ADRs, identity model, scopes, tenant boundaries, retention proposal. | C01–C02 |
| C04 | Backend/QA | Synthetic authenticated MCP slice and negative auth tests. | C03 |
| C05 | Integration/operator | Authorized personal or institutional read through actual ChatGPT; sanitized evidence. | C02–C04; valid access |
| C06 | Integration/QA | Courses/assignments/self status, pagination, effective dates, explicit capability coverage. | C04; C05 for live proof |
| C07 | Planning/QA | Effort ranges, next-action ranking, capacity validation, missing-data answers. | C06 |
| C08 | Security/operator | Deletion/reconnect/backup/restore, isolation/SSRF/parser boundaries, incident controls. | C03–C06 |
| C09 | QA/UX | Pilot end-to-end, native Calendar composition, text/mobile accessibility, guide-only onboarding. | C05–C08; supported OAuth pilot |
| C10 | Retrieval/planning | M2 materials, manifests, source conflicts, full plans, supported grade engine. | M1 |
| C11 | Calendar/security | M3 separate grants, consent adapter, previews/receipts, idempotent reconciliation. | M1 facts; M2 for study blocks |
| C12 | Maintainer/product | M4 approvals, packaging, measured costs, support/docs/license and public claim audit. | Applicable earlier gates; G2 resolution |

Do not postpone C02's public-distribution feasibility until after all implementation. Do not postpone C08's foundational safety until after a live student pilot.

### 23.3 Required guides

**Student guide:** supported schools/plans/surfaces; connect, select, ask useful questions, interpret freshness/uncertainty, Calendar choices, correct effort, reconnect, disconnect/delete, limitations, and help. No command line in normal student onboarding.

**Institution administrator guide:** rationale, exact requested scopes, OAuth endpoints/redirects, tenant isolation, data recipients/retention, access approval process, privacy arrangements, emergency disable, and support ownership.

**Operator guide:** deployment, secrets/rotation, logs, quotas, migrations, restore/deletion fences, external-outage handling, incident runbooks, measurable service/cost targets, and compatibility upgrades.

**Contributor guide:** deliberate license choice, setup using synthetic fixtures, test expectations, protected architectural invariants, threat reporting, dependency policy, release process, and requirements/evidence updates. A permissive license such as Apache-2.0 is a proposal, not a license already adopted by this document; the owner must approve the actual project license and dependency notices before publication.

## 24. Completion reporting and forbidden shortcuts

After each development increment, Codex must report what changed, which requirements it addresses, test commands and outcomes actually run, environments tested, remaining unknowns, and the next dependency-ordered work. Record skipped tests as skipped/not run; do not turn them into passes.

Use this compact status structure:

```text
Increment / commit:
Implemented:
Verified in automated fixtures:
Verified through actual ChatGPT:
Verified against institution(s):
Not verified / partially supported:
Blocked by external access or approval:
Tests executed and evidence paths:
Known limitations / risks:
Next gated work:
```

Never say “connected” just because a token is configured, “complete” because mocks pass, “supports every school” because the URL is configurable, “FERPA compliant” because secrets are encrypted, or “calendar updated” without a real operation result. A directory rejection or policy limitation must not be hidden by silently rebranding the app.

Do not add a mandatory OpenAI API key to make ordinary ChatGPT use work. Do not build a standalone chatbot/dashboard as a workaround for account limits. Do not collect other students' personal Canvas tokens. Do not expand token privileges to avoid missing fields. Do not solve access issues through browser-cookie scraping or unauthorized impersonation.

The first useful release is done when a properly authorized pilot student can ask ordinary ChatGPT what is due and what to do first, receive accurate source-backed individualized information with honest coverage, and trust the product's access boundaries. The broader product adds study/material support and safe optional actions only as their evidence supports them.

## 25. Codex kickoff instruction

> Read this entire specification before changing code. Treat the latest ChatGPT-native product requirements as binding. First inspect any existing repository, map its actual implementation to R01–R43, and distinguish UNKNOWN, REPORTED, VERIFIED, and FAILED with evidence. Preserve working code rather than blindly scaffolding a replacement.
>
> Build a ChatGPT-native Canvas extension, not a standalone AI app. Use a tenant-isolated, multi-institution-ready backend while proving one supported-school vertical slice first. ChatGPT handles conversation and reasoning; the connector handles authorized facts, normalization, deterministic planning/math, retrieval, and separately controlled actions. Do not require a separate LLM API key, student subscription, external academic dashboard, or paid account.
>
> Begin with M0: verify current supported ChatGPT MCP/auth/distribution contracts, Canvas institution/OAuth feasibility, and the public unofficial-connector policy risk. Use synthetic data until the appropriate security/privacy/access gates are met. A personal developer token may be entered only in private operator configuration for that developer's own testing; all other students need authorized OAuth.
>
> Prove an actual authenticated ChatGPT-to-Canvas read before advanced features. Then implement complete scoped workload retrieval, individual dates, own status, evidence/freshness/coverage, and a useful next-action recommendation. Enforce student-only academic reads even when upstream credentials are more powerful. Do not add a generic HTTP/SQL/Canvas proxy.
>
> Keep native Calendar orchestration separate from connector-owned Calendar authorization. Leave writes disabled until preview binding, actual authorization, idempotent recovery, event ownership, and receipts are tested. Never invent completed actions, exact grade impacts, effort estimates, availability, or source history.
>
> Add materials, full planning, supported grade scenarios, optional durable sync, and public distribution in the documented dependency order. Run the corresponding fixtures and real-client evaluations; update the evidence ledger after each increment. Continue independent non-secret work when access or approvals are blocked, and state those blockers precisely. Deliver working, documented, tested increments—not a polished shell around unverified promises.

## 26. Source register and verification boundaries

Primary documentation was consulted for this consolidation on **20 October 2026**. Recheck current versions at implementation and release. These references support platform facts and constraints, not implementation status, institutional approval, account entitlement, or legal suitability. Most product requirements and test cases come from H0/H1/H2; architecture defaults, thresholds, and new gates are consolidation decisions.

### 26.1 Supplied planning sources

| Ref | Source | Use |
|---|---|---|
| H0 | Product-owner message: Criteria Review Handoff summary and **Core Product Requirement: ChatGPT-Native Integration** | Highest-priority product identity, UX, technical acceptance, exclusions, funding constraints. |
| H1 | `Pasted text(20261020-160608).txt` — **CANVAS TO CHATGPT: CRITERIA REVIEW AND DEVELOPMENT ROADMAP**, prepared 20 October 2026 | Original R01–R33; 20 critical scenarios; planning, institutional, privacy, evidence and release framework. |
| H2 | `Canvas_ChatGPT_Connector_Codex_Spec.md` — **Canvas Bridge — Canvas-to-ChatGPT Connector**, v1.0, prepared 20 October 2026 | Earlier personal connector architecture, retrieval, grade, API, safety and implementation details; superseded as recorded in §2. |

### 26.2 External primary references

| Ref | Primary source | URL |
|---|---|---|
| E01 | OpenAI — Authentication | `https://developers.openai.com/plugins/build/auth` |
| E02 | OpenAI — Connect and test your plugin | `https://developers.openai.com/plugins/deploy/connect-chatgpt` |
| E03 | OpenAI — Plugin guidelines, including unofficial connectors and data practices | `https://developers.openai.com/plugins/plugin-guidelines` |
| E04 | OpenAI — Remote MCP server review requirements | `https://developers.openai.com/plugins/deploy/app-review` |
| E05 | OpenAI — Security & Privacy | `https://developers.openai.com/plugins/guides/security-privacy` |
| E06 | OpenAI — Build an MCP server | `https://developers.openai.com/plugins/build/mcp-server` |
| E07 | Instructure — OAuth2 overview, manual-token limits, per-user OAuth | `https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth` |
| E08 | Instructure — Developer Keys, scope/account enablement and includes | `https://developerdocs.instructure.com/services/canvas/oauth2/file.developer_keys` |
| E09 | Instructure — Assignments | `https://developerdocs.instructure.com/services/canvas/resources/assignments` |
| E10 | Model Context Protocol — Security Best Practices, versioned 2026-07-28 reference | `https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices` |
| E11 | Instructure — Submissions | `https://developerdocs.instructure.com/services/canvas/resources/submissions` |
| E12 | Instructure — Assignment Groups | `https://developerdocs.instructure.com/services/canvas/resources/assignment_groups` |
| E13 | Instructure — Enrollments | `https://developerdocs.instructure.com/services/canvas/resources/enrollments` |
| E14 | Instructure — How do I create rules for an assignment group? | `https://community.instructure.com/en/kb/articles/660670-how-do-i-create-rules-for-an-assignment-group` |
| E15 | Instructure — Pagination | `https://developerdocs.instructure.com/services/canvas/basics/file.pagination` |
| E16 | Instructure — Throttling | `https://developerdocs.instructure.com/services/canvas/basics/file.throttling` |
| E17 | Instructure — New Quizzes | `https://developerdocs.instructure.com/services/canvas/resources/new_quizzes` |
| E18 | Google — Create Calendar events | `https://developers.google.com/workspace/calendar/api/guides/create-events` |
| E19 | Google — OAuth consent and scope configuration | `https://developers.google.com/workspace/guides/configure-oauth-consent` |
| E20 | Google — Synchronize Calendar resources efficiently | `https://developers.google.com/workspace/calendar/api/guides/sync` |
| E21 | Google — Calendar resource versions and conditional modification | `https://developers.google.com/workspace/calendar/api/guides/version-resources` |
| E22 | U.S. Department of Education — Online course tools and the FERPA school-official exception | `https://studentprivacy.ed.gov/faq/i-want-use-online-tool-or-application-part-my-course-however-i-am-worried-it-violation-ferpa` |
| E23 | W3C — Web Content Accessibility Guidelines 2.2 | `https://www.w3.org/TR/WCAG22/` |
| E24 | OpenAI — Building MCP servers for plugins and API integrations | `https://developers.openai.com/api/docs/mcp` |
| E25 | OpenAI — Build skills | `https://developers.openai.com/plugins/build/skills` |
| E26 | Instructure — Courses | `https://developerdocs.instructure.com/services/canvas/resources/courses` |
| E27 | Instructure — Modules | `https://developerdocs.instructure.com/services/canvas/resources/modules` |
| E28 | Instructure — Files | `https://developerdocs.instructure.com/services/canvas/resources/files` |
| E29 | Instructure — Planner | `https://developerdocs.instructure.com/services/canvas/resources/planner` |
| E30 | Instructure — Calendar Events | `https://developerdocs.instructure.com/services/canvas/resources/calendar_events` |
| E31 | Instructure — Discussion Topics | `https://developerdocs.instructure.com/services/canvas/resources/discussion_topics` |
| E32 | Instructure — Classic Quizzes | `https://developerdocs.instructure.com/services/canvas/resources/quizzes` |
| E33 | Instructure — Pages | `https://developerdocs.instructure.com/services/canvas/resources/pages` |
| E34 | Instructure — Announcements | `https://developerdocs.instructure.com/services/canvas/resources/announcements` |
| E35 | OpenAI — Add UI to your MCP server | `https://developers.openai.com/plugins/build/chatgpt-ui` |

E03 is especially important: this specification does not establish that an independently developed Canvas connector qualifies for public listing. E07/E08 likewise do not establish that any particular university has enabled the required access. Verify those two dependencies independently.

## 27. Outstanding owner/operator decisions and final acceptance checklist

These are explicit release dependencies, not questions that prevent Codex from doing independent synthetic development.

| Decision | Current state | Who resolves it | Before |
|---|---|---|---|
| Actual existing repository and deployed implementation | Not inspected in this consolidation | Codex / maintainer audit | Claiming implementation status |
| First institution and OAuth/key approval | Rowan is a candidate, not verified support | Institutional-access lead / institution | Other-user live pilot |
| ChatGPT plan/workspace/client path | Not tested here | Integration lead / authorized account owner | ChatGPT integration claim |
| Public distribution-policy eligibility | Unresolved; explicit unofficial-connector policy risk | Product owner / platform and relevant service owners | Public listing commitment or submission |
| Identity provider / federation flow | Established compatible provider required; vendor not selected | Architect / security / operator | Production linking |
| Hosting, operator, region, budget | Not selected | Product owner / operator | Production student-data processing |
| Legal/privacy arrangements and retention defaults | Proposed; actual deployment needs review | Privacy/institutional owner | Live student pilot |
| Exact project license and dependency notices | Not adopted by this specification | Product owner / maintainer | Open-source publication |
| Connector-owned Calendar and notification rollout | Optional, disabled until feature gates pass | Product owner / security / QA | Corresponding writes or unattended delivery |
| Additional languages, minors, jurisdictions, roles | Out of initial support unless explicitly reviewed | Product/privacy owners | Advertising expanded support |

Final implementation acceptance must answer all of the following with evidence:

- Does the student complete the core workflow in an ordinary ChatGPT conversation without another AI product, mandatory model API key, or academic dashboard?
- Do individualized facts, source links, freshness, unknowns, and coverage agree with the authorized source?
- Does “what first?” produce a feasible, understandable next step rather than a large unsorted list?
- Are access, parsing, caches, jobs, and deletion isolated across students and universities?
- Are Calendar actions actually authorized, idempotently recoverable, and supported by receipts?
- Can the operator recover from outages, revocations, restores, and provider changes without inventing success or resurrecting deleted data?
- Do onboarding, documentation, mobile support, institution coverage, and public-distribution claims match what was truly tested and approved?

**Final product rule:** fewer dependable capabilities are better than a large unverified tool catalog. Expand only when the next feature makes ChatGPT more useful without making the student's trust harder to justify.
