# U02 - Complete the student's obligation picture

Priority: high | Status: development specification, not implemented evidence
Read README.md first. Outcome: fewer missed requirements without more false overdue warnings.

## 1. Extend the existing inventory

Inspect existing obligations, workload, discussion participation, independent datasets and planning. Earlier code handles assignments, classic-quiz instructions, discussions and event preparation [README R6]. Verify current gaps; extend normalization rather than building a universal adapter.

Start with U01 reviewed records and personal tasks. Future approved adapters use the same model without becoming independent-planning dependencies. No Canvas submissions, quiz attempts, peer-message reads or source writes.

## 2. Useful coverage, not indiscriminate collection

Represent evidence-backed peer reviews, initial posts/replies, required module activities, revisions, in-class deliverables, lab preparation and individual group responsibilities. Existing authorized adapters may add supported quiz metadata. Unsupported New Quiz/external-tool resources stay coverage gaps; one fixture cannot establish general compatibility.

Visibility does not prove an item is required; group deadlines do not establish personal roles. Graded work may still need an explicit revision. Separate attendance, preparation and deliverables. Peer-review obligations require only minimized own-task records, not peers’ names/submissions.

Separate required, student-chosen, optional and unresolved work. Default to actionable items plus a compact clarification section. Personal tasks gain no invented grade impact; “submitted on paper” remains a user assertion, not an official receipt.

## 3. Canonical model and relationships

Extend the existing normalized work identity with:

- Opaque owner/course-scoped ID, activity kind, title, source aliases and optional parent activity.
- Requirement status/basis, responsibility, explicit completion rule and supporting evidence references.
- Open/close/due/event times, each with precision, timezone evidence and source version; unknown fields remain null.
- Own official submission/participation observations, student progress assertions and conflicts as separate fields.
- Coverage by source/type, last checked time, permitted source set and version-bound inventory ID.

Extend current models, not another database. Alias links require explicit source relationships or reviewed mappings with expected versions. Similar titles/files/dates never merge work; two courses’ “Lab 1” remain separate.

Represent multipart requirements as child obligations, such as initial post plus two replies, with separate supported deadlines. Unknown reply count or deadline stays unresolved. Do not multiply aliases into duplicate tasks.

Support requirement groups: “complete two of three essays” becomes a selection rule with a minimum count, not three mandatory essays. The separate “best two scores count” rule does not alone prove that the third essay is optional. Record grading eligibility and participation requirements independently. Declining an optional item does not excuse mandatory work.

## 4. State, reconciliation and planning

Compute effective actionability from source evidence, user choices, dates and completion rules. Retain uncertainty instead of converting absent submission records into missing work. A locked item can be upcoming work requiring preparation rather than overdue work that can be submitted now. Distinguish submitted, graded, excused, user-marked-done and unknown; do not mark the LMS complete from personal progress.

Require evidence that individualized dates apply. Preserve date-only precision and conflicting passages; newer documents are not automatically authoritative. Manual corrections remain versioned assumptions.

Feed one bounded, versioned inventory into existing planning/calendar proposals, preserving filters across pages. Account for every selected activity as scheduled, excluded, optional, blocked, unresolved or over capacity. Unknown effort stays unknown; points/quiz duration are not estimates. Resolve two-of-three choices before allocating essays.

Partial failure cannot hide known independent work. “No work due” requires complete checked scope; propagate unchecked types and coverage into plans.

## 5. Interfaces and operational boundaries

Extend existing requests with permitted sources, course/window/timezone and personal-task filters. Return canonical activities, requirement groups, conflicts, coverage and continuation. Personal-task/mapping saves use authenticated, versioned, idempotent local mutations; retain the read-only deployment’s UI write path.

Keep current pagination and stricter caps, never over 100 activities per response. Bound relationship depth, detect cycles and prohibit completion claims from partial pages. Recheck access before titles/counts. Revocation removes dependent mappings; only genuinely independent permitted tasks survive.

Future live adapters need exact capability/scope documentation and existing authorization gates. Test synthetically; leave disabled pending approval. No scraping, undocumented or privileged access. Uploads cannot forge official submission state.

## 6. Acceptance tests

U02-A1: A fictional course contains a lab, peer review, discussion initial post plus two replies, revision, in-class essay and optional reading. Return distinct supported actions, shared parent relationships and no peer identities. Run with Canvas disabled and zero upstream requests.

U02-A2: Three essays require any two; only the best two count toward grades. Return the requirement group, no arbitrary mandatory third essay, and no claim that grading rules alone waive participation.

U02-A3: Assignment/quiz/module aliases refer explicitly to one activity. Produce one canonical task. Same-title items in different courses remain separate; uncertain aliases request review.

U02-A4: Excused work, submitted-but-ungraded work, an unknown submission, a requested revision and student-marked completion retain their distinct states. No unknown score or completion becomes zero/false.

U02-A5: Conflicting individual/class deadlines, date-only values, DST ambiguity and open/close boundaries neither invent times nor authorize source precedence.

U02-A6: Fail one source collection or later page. The inventory and resulting plan preserve known work, disclose partial coverage and do not say the student is caught up.

U02-A7: Select work with insufficient time, unknown effort and a prerequisite cycle. Account for every selected ID; do not silently drop tasks or double-book capacity.

U02-A8: Foreign IDs, revoked sources, stale mappings and injected “mark all complete” text cannot alter state or disclose data. Concurrent personal-task edits have one versioned winner, not lost updates.

## 7. Usefulness and release gate

Freeze 12 fictional scenarios with gold required/optional/unknown states. Supported fixtures must miss no explicit obligation and misclassify no optional item as mandatory. Report improvement over baseline; this does not prove university-wide completeness.

Release independent inventory-to-plan first. Report provider-specific blocks, coverage, executed tests, migration/rollback and unsupported types. Do not create one tool per activity kind.
