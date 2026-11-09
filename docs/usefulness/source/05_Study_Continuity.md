# U05 - Resume from actual study evidence

Priority: medium | Status: development specification, not implemented evidence
Read README.md first. Outcome: a new conversation resumes useful practice without inventing mastery.

## 1. Reuse and smallest useful slice

Inspect preferences, plans/progress and study preparation. Task progress is not concept understanding. Extend owner-scoped state, not another memory store or reliance on general chat memory.

Deliver select goal -> attempt -> explicitly save outcome -> resume through a fresh authorized read. Independent state needs no LMS connection. U03 links are optional; no knowledge graph or mastery score is required.

## 2. Explicit student control

Save selected study outcomes, not all chat turns. Plan preparation grants no recording consent. Show scope, content and correction/deletion controls. Label self-reports separately. No microphone capture, invented transcripts or unrelated chat retrieval.

Reuse authenticated writes with receipts, idempotency and expected versions. Read-only deployments use the settings/review UI; reads cannot silently save goals, acknowledge progress or start timers.

Allow “forget this session,” “that interpretation is wrong,” and “do not save study history.” Disabling future collection and deleting existing history are distinct actions with clear results. No streaks, guilt messages or repeated pressure to complete optional practice.

## 3. Minimal evidence model

Extend current records with an owner/course-scoped goal ID, session/attempt IDs, source references and versions, concept label, attempted prompt, optional minimal response excerpt, event time and evidence kind. Evidence kinds distinguish student self-report, submitted practice response, deterministic check and host qualitative interpretation.

Observations record demonstrated behavior, uncertainty, evaluation method, correction and next exercise. Full answers require explicit permitted selection. Do not duplicate documents/chats or label model summaries as official learning outcomes without evidence.

Attempt observations are append-only with versioned corrections/supersession. Repeated transport retries are not additional attempts. Preserve attribution when a student rejects a host interpretation; do not keep presenting the rejected claim as fact. Store actual timestamps, not invented durations or assumed effort. Leave unknown confidence/score fields absent rather than generating percentages.

Optional U03 links and source/policy changes affect their dependencies, not unrelated independent goals or the whole account.

## 4. Resume behavior

Resume from permitted state and current source/policy status. Show up to three choices if the goal is ambiguous. Return the actual prior attempt, one unresolved issue and next practice, distinguishing user statements from observed performance.

If a student previously named an experimental control but could not explain its purpose, start with a new permitted example testing that distinction. Do not repeat the identical question indefinitely or treat viewing the explanation as demonstrating success. A new response may update the evidence, but one correct answer does not establish permanent mastery.

Honor supplied time, preferences and stopping points; unknown availability stays unknown. Suggested review dates are not reminders. Requested scheduling uses existing proposal/confirmation/read-back paths, never implicit notifications.

A stale source can prompt review or a new reference, with the prior observation labeled historical. If source access is revoked, withhold dependent restricted excerpts and interpretations under the policy service. Truly independent student-authored notes may remain only where their separate permissions and content allow it. Do not use “memory” as a way around source restrictions.

## 5. Contracts, privacy and rollout

Extend existing state actions. Inputs carry course/goal, expected versions, proposed observation and authenticated receipt; outputs carry state version, provenance, suggestions and limits. Ownership comes from authentication, not caller claims.

Retain scope/version checks through final serialization. Course-level opt-out, export and deletion use existing lifecycle services. Suggested maximum retention for newly saved learning observations is 90 days unless the student explicitly chooses otherwise within allowed policy; existing stricter limits win. Pending deletion and restore fences cover backups and derived summaries. Logs contain operation IDs and safe counters, not answers or difficulty labels.

Initially cap each saved attempt at 8 KB of permitted text and each resume pack at five relevant observations within the existing response budget. Larger material remains in the original source store. Concurrency must reject/reconcile stale edits without losing another session's update. Migrations and rollback run against a disposable database; disabling the feature preserves export/delete access.

## 6. Acceptance tests

U05-A1: Save one explicitly authorized fictional practice outcome, restart the service, then resume in a new client session. Return the correct goal and next exercise with no reliance on earlier chat context or live Canvas.

U05-A2: “I read it,” an actual response and a checked response retain different evidence kinds. None automatically becomes verified mastery or official assignment completion.

U05-A3: No save request creates no enduring record. Repeated save with the same idempotency key creates one attempt. Concurrent corrections use expected versions; rejected interpretations stop appearing as current facts.

U05-A4: Multiple courses and similar concept labels do not merge histories. Foreign-owner handles and a request to “show everyone struggling” disclose nothing.

U05-A5: Source revision marks only relevant observations for review. Revocation withholds restricted derivatives; an unrelated independently saved goal remains usable while Canvas is disabled.

U05-A6: Delete a session, export remaining state and restore a backup under deletion fences. Deleted responses and summaries cannot reappear. Disable collection without silently deleting unrelated records.

U05-A7: A five-minute request yields a bounded practice proposal and stopping point. Suggested review times create no calendar event or notification. Source instructions cannot authorize recording, scheduling or messaging.

U05-A8: Read-only deployments offer a working authenticated save UI without mislabeling tool annotations. Inspect every output channel for source restrictions; assert zero provider requests during independent save/resume/error paths.

## 7. Usefulness and release gate

Freeze ten resume scenarios covering mixed courses, missing/rejected/stale state and incomplete attempts. Require correct prior evidence and no invented history. Compare setup effort to baseline.

Pilot setup effort and acceptance/correction of next exercises; disclose sample/errors, not promised grade gains. Release requires save-correct-resume-delete across fresh sessions, not just a memory table or summary.
