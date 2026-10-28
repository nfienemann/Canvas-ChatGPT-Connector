# Academic Integrity Permission Engine

The AIPE implementation adds an activity-specific permission layer to the existing
source-access, privacy and egress checks. It does not grant Canvas access, generate
submissions, decide whether a student cheated, contact instructors, or certify
institutional compliance. ChatGPT remains the conversational interface.

## Requirements reviewed

All eight documents in `Canvas_Bridge_Academic_Integrity_Specs.zip` were reviewed:
the README, AI-01 through AI-06, and the Rowan/global-invariants appendix. Their
requirements were assessed against `Codex_Spec.md` and the existing release gates;
document prose was not treated as authorization to deploy, change credentials or
publish. The implementation stays in this working checkout and uses fictional data.

| Bundle specification | Implementation | Reproducible verification |
| --- | --- | --- |
| AI-01 classification | `integrity/models.py`, `surfaces.py`; fixed A-E taxonomy and expected-output floor | engine activity cases; administrative-package and unknown-tool regressions |
| AI-02 discovery | `integrity/discovery.py`, existing authorized course/file collectors and independent imports | real synthetic provider collection, unavailable lookup, invalid public review, source revocation |
| AI-03 interpretation | `integrity/parser.py`, `engine.py`; original passages, authority, specificity and version checks | quotation, negation, limited permission, conflicts, amendments, injection and partial coverage |
| AI-04 student agency | `integrity/service.py`; owned, versioned and expiring acknowledgments | explicit action, owner/scope mismatch, expiry, policy change, egress denial and history deletion |
| AI-05 workflow coverage | guarded MCP registration, final egress fence, exam collector and controlled assistance package | HTTP MCP tests; tool switching; local copy lineage; no-network offline workflow |
| AI-06 evidence | `CB-INTEGRITY-01` through `06`, synthetic scenarios, source-bound pytest receipts | compliance recorder and reviewer report; no external approval implied |

## Activity and permission contracts

Administration (A), independent learning (B), logistical assignment planning (C),
substantive assignment assistance (D) and submission-content generation (E) have
separate decisions. Brainstorming, substantive outlines, research, draft feedback,
mechanical corrections, assessed data analysis, debugging, partial answers, writing,
rewriting, code, discussion responses and assessed visual deliverables are distinct.
Declaring an administrative activity cannot lower a submission-content output.

`prepare_academic_assistance` is the controlled evidence-release operation, not a
language-model backend. Administrative and logistical uses of this endpoint return
no completion evidence. Learning packages exclude known assessment instructions;
requests for substantive assessed help require their own activity decision. A
restricted activity cannot be authorized by splitting it into partial-answer calls.

All registered MCP tools have a reviewed operation classification. Unknown tools
fail closed. Normal reader entry points discover policy; final output fencing
checks known course and assessment bindings. Grade/deadline functions remain
available under existing data permissions. Requirement reviews preserve metadata
while withholding raw assessed content in a known restricted workflow. Reader,
visual, search and study tools cannot release a known restricted assessment by
changing tools. Existing original-file delivery retains its independently reviewed
user-download contract; downloading one's source is not permission for AI completion.

The six proposed tools are implemented, alongside `prepare_academic_assistance`
and minimal acknowledgment list/revoke tools. Mutating acknowledgment/evidence
operations require the existing write scope and disappear in MCP read-only mode.
The server never accepts caller-created rules, verified-authority labels or an
override boolean. A receipt reference is owner-bound state, not a bearer grant.

## Discovery and interpretation limits

Discovery reuses selected-course authorization, assignments and rubrics, syllabus
HTML, recent announcements, title-discovered/linked policy files, and independently
imported documents. Limits remain explicit: 30 assignments, three file reads and
bounded recent announcements; discovery has a 90-second deadline. A filename is
only a candidate hint. Each candidate reports `DISCOVERED`, `READ_COMPLETE`,
`READ_PARTIAL`, `UNREADABLE`, `NOT_FOUND`, `ACCESS_DENIED`, `STALE` or `NOT_CHECKED`
as applicable. Partial extraction cannot establish policy absence or a grant.
Existing OCR/visual readers remain available; visual interpretation is not silently
promoted to a verified policy. Arbitrary files and announcement authorship need
review before they can grant instructor permission.

The interpreter recognizes a bounded set of English clauses. It does not claim
general natural-language interpretation accuracy. Unknown conditional wording is
ambiguous; quoted/sample policies do not become adopted course rules. Unrecognized
language can still be missed: external review must test the actual institution's
wording before public completion features. Test accuracy is fixture accuracy only.
Explicit grants never override an applicable prohibition. An unresolved conflict
with a prohibition blocks assistance. Reviewed supersession requires exact prior
source/version, matching issuer and scope, complete extraction and a later effective
date. Fresh changes to the authoritative syllabus/assignment are reread, not frozen
by old permission receipts. Merely uploading an apparent amendment cannot verify it.

Missing institutional evidence returns `LOOKUP_UNAVAILABLE` and prevents substantive
permission or acknowledgment eligibility. A completed fictional discovery with no
applicable rule may offer acknowledgment; permission remains unconfirmed afterward.
An instructor-permission requirement, approved-tool requirement, confirmed restriction,
unresolved authoritative conflict, unauthorized source or prohibited egress cannot
be acknowledged away. Student attestation is not accepted as instructor permission
in this implementation. There is no operator bypass or tool-approval switch.

## Public institutional references

The optional adapter reads `BRIDGE_INTEGRITY_POLICY_REVIEWS_FILE`, a private,
administrator-reviewed JSON array of `InstitutionalReview` models. It performs no
search or HTTP fetch and transmits no student query to an external provider. No
arbitrary URL-fetch endpoint is exposed. Without a current reference it returns
`LOOKUP_UNAVAILABLE`. Invalid, oversized or expired reviews fail closed.

Each review identifies an institution, official HTTPS hosts, checked/review-due
times (at most 30 days apart), and source records including authority, URL, hash,
locator, coverage, effective date if known, retrieval date and verification status.
`source.version` must equal `fingerprint(source.parts)`; editing a passage without
updating its independently reviewed record invalidates it. A source must be an
institutional, departmental or illustrative public reference, never an invented
instructor permission. This operator review is evidence administration, not external
institutional approval. Review changes invalidate policy fingerprints and receipts.
No automatic refresh expands permissions. The deployment owner must review changes
by the recorded deadline; this implementation creates no scheduled automation.

Rowan is a reference profile, not a special case in the engine. Public references
were checked on **2026-10-28**. The [Academic Integrity Policy](https://confluence.rowan.edu/spaces/POLICY/pages/61426359/Academic%2BIntegrity%2BPolicy)
identifies revision/review **2026-10-19**, interim status, and scope covering non-medical
students, faculty and staff. Attachment 7 requires instructor permission for
coursework use and citation when permitted. It distinguishes mechanical edits from
plagiarism while preserving instructor restrictions. This observation is not an
installed policy grant; the effective date is not separately stated.

The [Faculty Center page](https://sites.rowan.edu/academic-affairs/facultycenter/resources/generative-ai/)
provides example syllabus statements for instructors to adopt. Those examples are
illustrative, not binding across all courses. The [academic-integrity information
page](https://sites.rowan.edu/academic-affairs/academic_integrity/) provides context.
These three references need renewed review by **2026-11-27**, and earlier if changed.
A dated Rowan test profile exercises a bounded Attachment 7 excerpt against fictional
coursework and checks its review expiry. It records partial policy coverage. No
Rowan source interpretation or approval was installed in private configuration.

## Receipts, privacy and deletion

The existing encrypted `IndependentResource` store holds owner-bound decision,
acknowledgment and policy-context records. No schema migration is needed. Decisions
and acknowledgments expire after 15 minutes; context/known-copy bindings expire
after at most 24 hours and still require current underlying-source access. They are
subject to the existing sweep/account-deletion controls. A per-owner 200-record
limit and 256 KiB per-record limit prevent unbounded logging. History lists only acknowledgment IDs, activity
and expiry, and supports revocation. Read-only source discovery may update bounded
server caches; it never records a student's acknowledgment implicitly.

Decision audits store classification, source IDs/versions/locators, state, reason,
conditions, time and outcome. Policy context retains only relevant rule passages;
full prompts, conversations, drafts and answers are not retained for auditing.
The same academic-data encryption applies. Unrelated independently imported papers
remain learning sources. Known matching copies inherit assessment restrictions;
source deletion/revocation does not create an authorized alternative path.

## Reproduce and interpret evidence

Use the repository virtual environment and fresh output names:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_integrity_engine.py tests/test_integrity_workflows.py -q -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/integrity-tests.json
.\.venv\Scripts\python.exe -m canvas_bridge.cli compliance-report --results .local/integrity-tests.json --output .local/integrity-review
```

The synthetic demonstrations cover A: a provider syllabus prohibition, B: limited
brainstorming, C: eligible uncertainty, D: an institutional permission requirement,
and E: offline policy/assessment imports. The offline tests use the production text
parser in process to isolate integrity behavior; they do not certify parser sandboxing.
HTTP tests use real authenticated MCP transport with fictional principals and data.

The governance registry starts at `IMPLEMENTED_UNVERIFIED`; only successful,
source-matching execution receipts can derive `TESTED`. Review the sanitized result
report for actual pass/skip/failure counts. Metrics distinguish fixture prohibition
detection, false-positive cases, missed restrictions, classification consistency,
citations, override/bypass rejection, version invalidation and offline compatibility.
They are not one confidence score and do not establish live Rowan compatibility.

The Bridge cannot control undisclosed assessments, external transformations it has
never seen, arbitrary user-pasted content or ChatGPT reasoning outside its tools.
It provides no AI-authorship detector, misconduct adjudication, surveillance archive,
automatic instructor reporting, universal prevention claim or legal certification.
External release still requires the existing independent institutional, security,
privacy, distribution and operational approvals.
