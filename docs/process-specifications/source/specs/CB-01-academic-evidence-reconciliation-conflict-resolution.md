# CB-01: Academic Evidence Reconciliation & Conflict Resolution

**Phase:** foundation  
**Status:** proposed  
**Primary audience:** Codex / CanvasBridge maintainers  
**Integration:** authorization registry, academic intelligence core, local document store, existing Academic Integrity Policy Engine

## Purpose
Reconcile contradictory claims from syllabi, schedules, announcements, assignments and user corrections without silently selecting the newest text.

## Scope and required behavior
1. Extract atomic claims with course/term/entity/field/value, source version, observed_at, effective_at and citation pointers.
2. Separate disagreement from supersession: explicit instructor updates outrank old schedules only for the affected field and scope.
3. Rank source authority via configured institution/course rules; recency alone is not authority.
4. If unresolved, preserve competing claims, mark contested and generate a question for the student/instructor.
5. Propagate resolved changes via dependency invalidation; do not directly mutate calendar.

## Out of scope
- No autonomous institutional access or attempt to defeat provider restrictions.
- No automatic submission, public publishing, instructor messaging, or external calendar writes.
- No claim of legal, academic-policy, degree-audit or grading authority without authoritative verification.

## Suggested typed domain objects
- `EvidenceClaim`: versioned ID, scope, provenance, timestamps, validity/state fields, serialized validation and audit fields.
- `ConflictSet`: versioned ID, scope, provenance, timestamps, validity/state fields, serialized validation and audit fields.
- `ResolutionDecision`: versioned ID, scope, provenance, timestamps, validity/state fields, serialized validation and audit fields.

## Event and API shape
- `evaluate_01(request, evidence_context, authorization_context) -> Result[decision, evidence_refs, warnings, proposed_actions]`
- `preview_01(decision_id) -> DiffPreview`
- `apply_01(decision_id, explicit_user_approval, idempotency_key) -> Result[revision_id, audit_ref]`
- `invalidate(source_or_revision_id, reason) -> InvalidationSummary` (where relevant).
- These are conceptual names; adapt to actual codebase conventions after inspecting its current architecture.

## Failure handling
- Missing source: return insufficient evidence and local-only fallback when lawful.
- Ambiguous evidence: surface competing explanations; do not auto-resolve high-stakes decisions.
- Stale/revoked permission: deny or quarantine affected action, while preserving eligible independent records.
- Partial write or crash: replay idempotently or roll back; never report success until committed.

## Acceptance tests
1. Different exam dates produce a conflict with both source citations.
2. Explicit new announcement can supersede prior syllabus date with audit trail.
3. Two equally authoritative conflicting sources remain unresolved.
## System invariants
- **Authorization isolation:** institutional LMS/API access is disabled unless required institution/provider permissions are actually validated; student-owned local imports remain independently operable under their own rights.
- **Integrity boundary:** use the existing/in-progress Academic Integrity Policy Engine as a gate for assignment-completion assistance; do not reimplement or bypass it. Planning, grade viewing and study help have separate policy checks.
- **No silent external writes:** changes to calendars, messages, submissions, remote sources, public sites or shared documents require explicit authorization, preview and action-specific consent.
- **Evidence over fluency:** unavailable, missing, stale, low-coverage or contradictory evidence cannot become an unqualified fact. Cite evidence, limitations and timestamps.
- **Privacy by design:** minimize collection, keep secrets out of logs, tag source provenance, use bounded retention, and enforce source-level revocation downstream.
- **Idempotency:** retries, reconnects, and process restarts must not duplicate irreversible actions or corrupt state.

## Implementation contract
- **Module boundary:** implement a service or domain module behind an interface independent of any specific LMS provider. Provider adapters translate source data into canonical, permission-tagged records.
- **Storage:** use explicit schema versions, stable IDs, revisions, and indexed lineage. All writes must be transactional or compensatable.
- **API behavior:** include typed success, unresolved, denied, stale and error outcomes; expose machine-readable reasons plus human-readable next steps.
- **Auditability:** record actor, policy decision, provenance, source timestamps, change reason and downstream effects without copying sensitive raw contents into logs.
- **UI:** offer an evidence inspector and preview for decisions that impact student obligations or permissions; don't imply certainty where none exists.

## Security and privacy test baseline
1. No authority escalation via imported PDFs, HTML, slides, tool responses or connected content.
2. No private student data sent to another external service without user approval and applicable permission.
3. Revoked connector permissions cannot be bypassed by cache hits, generated summaries, search indexes or retry queues.
4. Sensitive metadata is excluded from default telemetry and exception messages.
5. Same workflow works using permitted local-import data without requiring access to a restricted LMS.

## Rollout / migration
1. Add feature-flagged schema and read-only observation mode with synthetic fixtures.
2. Backfill only authorized, still-retainable data; preserve external IDs and provenance.
3. Enable limited opt-in workflows with dry-run previews and regression gates.
4. Expand after testing partial imports, permission changes, interrupted operations and rollback.
5. Keep kill switch, exported backup, versioned migration and troubleshooting documentation.

## Definition of done
- Typed interface and persisted schema documented; unit, integration, adversarial and recovery tests passing.
- Outcomes explain what was inferred versus confirmed and link to available supporting evidence.
- No unauthorized provider access, silent external mutations or bypass of the Academic Integrity Policy Engine.
- Documented failure modes, manual override boundaries, rollback and migration strategy.

## Dependencies and integration notes
- Foundational dependencies: canonical provenance, per-source authorization, versioned records, structured errors and local-import capability.
- For any assignment-completion action, call the preexisting Academic Integrity Policy Engine at decision time and immediately before any external side effect.
- Validate against current repository code before choosing library/framework/storage specifics; this specification is an engineering target, not a claim about currently implemented internals.
