# Cross-course knowledge and voluntary practice

`prepare_study_session` supports concept explanation, active recall, practice
assessment, figure practice, concept comparison and focused review in the ordinary
conversation. ChatGPT still provides conversational explanation and tutoring; the
connector supplies bounded evidence and deterministic checks, with no separate model
service or dashboard.

Choose up to six explicit authorized material references from at most three selected
courses. Each request reads at most 12,000 characters per material and reports unread
text or unavailable documents. The existing provider, source-sharing, privacy and
file-processing controls apply. Restricted assessments, third-party records,
confidential research and unclassified content cannot become practice through this
entry point. The final application integrity guard remains separate from data access.

## Context and relationships

The current deterministic extractor recognizes explicit English definitions such as
“Diffusion is …”, “X refers to …” and “X is defined as …”. It returns at most forty
source-specific candidates with their course, material, hash, exact passage and
locator. These are quoted definitions, not independently verified scientific facts.
This is deliberately limited extraction, not general semantic comprehension.

The same term in different courses retains separate identities and definitions.
A shared term creates a comparison candidate labeled `shared_term_only`; it never
establishes scientific equivalence. Explicit “Understanding X requires Y.” sentences
can support source-local prerequisite edges. Other relationships remain unverified.
Figure and assessment links are marked not checked unless separately supported; an
empty link list is not evidence that no relationship exists.

The client can explain or compare the returned contexts at the requested depth,
identify what it has encountered before among the supplied sources, and propose
further reading. It must keep inference separate from source statements. It cannot
claim a complete search of all previous courses.

## Practice and feedback

All generated questions carry `generated_practice` and `not_instructor_exam` labels.
Objective recall questions are constructed only from unique, unqualified source
definitions. Conflicting definitions, qualified wording, leaked answers and
duplicate answer descriptions are rejected. If the forty-concept ceiling is reached,
objective questions are withheld until scope is narrowed.

Recall and practice outputs omit answer-bearing concept lists, exact answer passages
and expected answers. An encrypted, owner/connection-bound receipt holds the answer
key for twenty minutes. The client presents questions first and waits for an actual
voluntary student response before calling `submit_practice_response`.

Multiple-choice letters can produce deterministic correct/incorrect outcomes.
Exact normalized recall answers can be marked correct. Unmatched free text may be
a synonym, so it remains unresolved for review. Advanced/open-ended and figure
questions have a rubric and require human/client discussion; the server does not
grade scientific meaning with an unvalidated model. Figure questions require a
current permitted render receipt and an attributed visual report. The report proves
source binding, not scientific accuracy.

Practice state distinguishes not attempted, unresolved, incorrect, correct with
assistance and independently reported correct responses. Confidence is a separate
student-reported field. An immediate repeat of a recorded question within the same
session counts as assisted. A new review session permits a newly reported unassisted
attempt; independence remains self-reported, never verified. An explanation view
never creates a practice record or a mastery claim. No response is inferred or
fabricated by the connector.

## Preferences, review and data control

Difficulty, session length, subject focus, question format, explanation depth,
practice frequency, review opt-in and availability are explicit session inputs.
They do not silently overwrite saved preferences. Focused review can rank explicit
weak areas and, when history is requested, current source-bound recorded outcomes.

Review recommendations require opt-in and a usable supplied availability window.
The transparent heuristic uses the requested base interval after assisted, incorrect
or unresolved practice and three times that interval after independently reported
correct recall. Elapsed time is shown. This is not a validated individual memory
prediction. A recommendation creates no event, reminder, scheduler or background job.

`submit_practice_response` requires the existing `preferences:write` scope because
it can save local results. `record_results` defaults to false and must reflect the
student's explicit choice. Saved records contain minimal outcomes, timestamps,
source IDs and counts, not raw responses, passages or answer keys. They use the
existing encrypted LocalRecord storage, thirty-day retention and account/academic
data deletion controls. Reading practice history requires freshly authorized source
material. Generic saved-preference reads exclude these records.

Every feedback call reauthorizes and rereads the source version. Changed content,
expired receipts, different owners, revoked selection and newly restricted sources
withhold feedback and prevent saving. Test fixtures cover science, engineering,
general education, ambiguous terms/questions, provenance, voluntary state transitions,
source privacy, review timing and the HTTP MCP scope boundary.

These local deterministic tests do not demonstrate better learning outcomes,
scientific interpretation accuracy or usability in an approved institutional client.
Those remain separate evaluation and release gates.
