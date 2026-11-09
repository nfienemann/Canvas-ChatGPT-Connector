# U03 - Turn feedback into a concrete improvement

Priority: high | Status: development specification, not implemented evidence
Read README.md first. Outcome: the student knows what to change and can practice that change.

## 1. Reuse and scope

Inspect assignment details, own comments, assessed rubrics, requirements review, readers and integrity workflows. Verify the missing delta. Rubric descriptions are not awarded rubric results.

Start with permitted imports of the student’s own feedback and existing practice preparation. Future approved adapters may supply visible own comments/posted scores. No second tutor, grading engine, paid model backend or broad performance profile.

## 2. Student journey

Resolve the requested work and feedback version. Return at most three improvements, each with its feedback passage, proposed change, relevant course reference and one voluntary practice activity.

Separate required corrections, suggestions and praise. Rubric criteria alone prove no weakness. Vague/conflicting comments prompt a clarification question, never an automatic message. Missing feedback does not mean no concerns.

Allow rejecting interpretations, correcting work links, selecting practice or explicitly saving an improvement. Reading creates no enduring judgment. U05 may consume saved outcomes; ephemeral U03 output must not depend on it.

## 3. Evidence and logical contracts

Normalize through existing source models:

- Feedback item: owner/course/work reference, source ID/hash/locator, exact passage, evidence kind, date when known, and visible/posted state.
- Rubric observation: criterion ID and description, possible/awarded points when supplied, associated comment, scale and missing fields.
- Proposed improvement: feedback references, interpretation label, concrete action, supporting learning references, optional practice prompt and applicable integrity decision.
- Practice result: attempted activity, explicit student response or self-report, evaluation method, correction and optional next action.

Record author role only when established; imports remain student-provided copies, not authenticated instructor statements. Minimize contact details. Missing scores stay null. Delegate supported arithmetic to the existing grade engine; do not invent grade changes or reapply penalties.

Work matching uses explicit references or reviewed associations. Similar assignment names do not justify cross-course linkage. Multiple copies/exports of one comment count as one observation, not independent corroboration. Stale or partial feedback remains visible as such.

## 4. Interpretation without pretending to automate understanding

The backend retrieves evidence and validates scope/version/locators; ChatGPT interprets already-shared passages. Host proposals must cite existing handles. Reject fabricated references, stale hashes and unsupported quotes. Valid citations do not prove correctness: preserve the interpretation label and correction path.

Prefer improvements observable in a subsequent response: explain a control, interpret an axis, connect a claim to evidence, or separate results from implications. Avoid broad personality or ability labels. A single comment cannot establish a recurring pattern. A suggested repeated issue requires evidence from at least two distinct relevant assessed works, with counterexamples shown when available; describe the observations, not a diagnosis.

Select policy-permitted relevant examples. Use U04 or literal lookup; failed retrieval never justifies invented citations.

## 5. Practice and integrity boundaries

Check existing assistance policy for the actual source/assessment. Feedback access and open-note rules do not authorize AI rewriting of graded work. Where restricted, use permitted explanations, analogous ungraded practice or clarification alternatives.

Practice targets one improvement with an observable check, such as naming a control and explaining its purpose. Label generated practice, not predicted exam content. Deterministic checks apply only where suitable; host evaluations are tentative, never instructor grades or measured mastery.

“Finished reading” or “understood” is a student report, not an observed successful application. After an attempted response, report what that response demonstrated and any uncertainty. The student may skip practice without repeated pressure. Do not generate the assessed answer while explaining that policy forbids doing so.

## 6. Privacy, persistence and errors

Use only own feedback and permitted shared-work excerpts. Minimize third-party data; anonymization grants no rights to peer work. No rosters, classmates’ submissions or hidden grades. Feedback instructions cannot authorize tool calls or contact.

Default to ephemeral output. Explicit authenticated saves use expected versions and compact reviewed references, not full submissions/chats. Shared lifecycle rules cover derived records on revocation. No answers, scores or comments in logs.

Bound requests to five works/20 feedback items or stricter existing limits. Paginate. Distinguish missing input, denial, partial extraction, ambiguous links and stale versions, with safe next steps and no foreign-resource oracle.

## 7. Acceptance tests

U03-A1: Imported fictional feedback says “describe the result and explain its implication.” The evidence pack preserves the exact passage; the reviewed output proposes that distinction and a separate permitted practice task, with no new requirement attributed to the instructor.

U03-A2: Praise, optional suggestions and mandatory revisions are represented separately. A blank comment and missing rubric score remain unknown, not criticism or zero.

U03-A3: Two copies of one comment do not establish a trend. Two distinct relevant works can support a tentative repeated-issue description; contradictory feedback remains visible.

U03-A4: Same-name work in another course, fabricated passage handles, edited quotations and changed source hashes cannot be accepted as valid evidence.

U03-A5: Restricted active-assessment help returns supported alternatives without writing the submission. A malicious feedback passage cannot alter policy, send messages or trigger hidden reads.

U03-A6: Foreign, hidden, unposted or peer-only evidence is withheld from every result channel. Mid-request revocation invalidates derived output and queued persistence.

U03-A7: No save request creates no enduring profile. Authorized save/retry yields one versioned record; delete/export/restore and read-only UI fallback behave as documented.

U03-A8: A practice response that names a control but does not explain it is not marked fully successful by an exact checker; a qualitative host evaluation is explicitly provisional. Run baseline retrieval and persistence with Canvas disabled and zero provider requests.

## 8. Usefulness and release gate

Evaluate ten fictional cases for fidelity, action specificity and practice relevance. Require no invented instructor statements and an actionable step for each explicit permitted case. Pilot later practice without claiming causal grade gains. Ship evidence-to-action-to-practice, not retrieval alone; imports must work with live providers disabled.
