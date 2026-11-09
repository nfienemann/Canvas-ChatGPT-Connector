# U06 - Explain changes that affect the student's next action

Priority: medium | Status: development specification, not implemented evidence
Read README.md first. Outcome: important changes become clear decisions without a noisy activity feed.

## 1. Extend existing change tracking

Inspect existing changes/snapshots/hashes/event IDs and calendar proposals [README R5]. Reuse their complete-observation rules; detection is not delivery. Do not add another polling service.

First ship on-demand independent-version digests. Imports establish only an “as of” view, not fresh instructor activity. Live refresh and optional scheduled delivery remain separate gates; this spec activates neither.

## 2. Detect a real change

Compare usable versions of one explicit source/work identity, optionally from U01/U02. Names alone cannot establish replacement. First observation creates a baseline, not invented history.

Track due/open/close dates, requirements, assessment scope, posted own feedback, amendments/cancellations and supported grade configuration with exact old/new evidence. Failed/partial/disappeared records cannot prove deletion, completion or cancellation.

Use semantic fingerprints that exclude retrieval timestamps and rotating transport URLs while preserving meaningful content changes. Keep raw-source hashes separate. A parser-version change, formatting-only difference or altered extraction coverage is a processing event until actual academic change is established. Never silently reset a baseline to make a test pass.

Conflicting sources stay conflicting unless explicit applicable amendment evidence resolves them. Date-only versus timed values preserve precision; uncertainty about a time is not a verified reschedule. Approved manual decisions remain labeled student assumptions.

## 3. Connect a change to a consequence

Show what changed, its student-specific consequence and a next action, with evidence/time/freshness/limits. Default to five actionable entries plus continuation.

Explain deterministic impacts: a plan ending after an earlier deadline, a checklist using superseded rules, or new feedback linked to a goal. Unknown effort cannot support exact hours-lost or grade-impact claims.

Use versioned plans without mutation. Calendar conflicts need real current authorized reads. Offer review/replanning, not claimed execution; preserve write confirmation/read-back rules.

Use action needed/review suggested/informational categories ranked by known impact and user preference. Not every re-import or grade is urgent. No relevant changes means a quiet qualified result.

## 4. Contracts and acknowledgment

Reuse the change-result envelope with event ID, owner/course/work identity, source versions, changed fields, old/new evidence, first-observed time, source timestamp when known, impact basis, affected plan IDs, recommended action and coverage.

Event identity must be stable for repeated observations of the same transition, and different for a later transition back to an earlier value. Deduplicate several detectors reporting the same canonical transition without collapsing distinct requirements or course scopes. Do not use raw private text in public IDs.

Keep viewed/acknowledged/snoozed/delivered separate. Reads do not acknowledge. Explicit mutations use authentication, idempotency and versions, with a UI path for read-only deployments. Old snoozes cannot hide new distinct changes.

A missing requested baseline returns available history limits and a next step. An inaccessible source reveals no title or details. A refresh error returns a stale/partial status, not a definitive “nothing changed.”

## 5. Optional delivery, not an invented background capability

After on-demand validation, optional delivery needs explicit opt-in and a verified scheduler/channel contract. Offline/unavailable execution cannot promise background checks. No second Google OAuth flow or notification product by default.

Expose scope/channel/timezone/cadence/quiet-hours/stop controls. Default to one daily digest, no empty push and generic lock-screen previews. Document DST handling without duplicate delivery; relative times use the selected timezone.

Reuse outbox/receipts with stable channel/event keys and bounded retries. External exactly-once delivery is not guaranteed: distinguish prepared/sent/confirmed/failed/unknown. Unknown outcomes need reconciliation, not blind sends. Recheck permission before release; purge revoked queued payloads.

The baseline needs no delivery credentials. Disabled channels preserve on-demand access; subscribing never enables Canvas refresh.

## 6. Lifecycle, resource and safety rules

Apply the shared deletion/retention policy to snapshots, snippets, impact results and queued messages. A deletion marker may suppress replay but cannot retain the removed source body. Source revocation invalidates dependent disclosure; non-sensitive acknowledgment metadata follows its allowed retention. No private payload in logs.

Bound work/traversal/output to 100 changed entities per batch or stricter limits, with continuation. Atomically insert events/advance cursors for restart safety. Rollback disables delivery but preserves read/export/delete.

## 7. Acceptance tests

U06-A1: Import two reviewed fictional schedule versions changing a deadline from November 8 to November 6, with a saved block ending November 7. Return one cited earlier-deadline event and a plan-review proposal; write no calendar event. Assert zero Canvas requests.

U06-A2: Re-query unchanged data and rotate transport timestamps/URLs. Produce no new academic event. A later change back is a distinct transition, not suppressed as an old duplicate.

U06-A3: First baseline, incomplete pagination, failed source read and disappeared item cannot establish deletion or “nothing changed.” Parser-only changes remain separately labeled.

U06-A4: Same-title work in another course, uncertain replacements, conflicting amendments and date precision differences preserve scope/ambiguity. No arbitrary authoritative source is selected.

U06-A5: A read creates no acknowledgment. Explicit acknowledge/snooze/retry is versioned and idempotent. New distinct urgent changes are not swallowed by an old snooze.

U06-A6: Source prompt injection cannot schedule delivery, contact an instructor or alter a plan. Foreign/revoked sources are withheld from all channels, including pending notification previews.

U06-A7: Restart after event insertion without losing events. If delivery is implemented, test uncertain sends, receipts, quiet hours, DST repeats/skips and disabled/offline channels; no blind duplicates.

U06-A8: Delete source/account and perform deletion-fenced restore. Old events, queued bodies and restricted derived text cannot reappear. Independent on-demand digests still work with all providers and senders disabled.

## 8. Usefulness and release gate

Freeze ten consequential and ten nuisance/no-change observations. Surface every supported consequential change with evidence and no nuisance action alerts. Pilot actionability/noise and report sample limits.

Release on-demand first; report delivery verification separately. A detected event, proposal or outbox row is not proof of receipt. Keep unapproved live refresh disabled.
