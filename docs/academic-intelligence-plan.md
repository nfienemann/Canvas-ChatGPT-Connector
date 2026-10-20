# Ten-feature implementation plan

Baseline inspected: commit 33d271a. The preceding 274-test run is reused as the
unchanged baseline; the next full run follows implementation changes.

| Order | Feature | Existing capability | Increment and acceptance proof |
|---|---|---|---|
| 1 | Shared evidence/coverage | Source, Coverage, FactDate and unknown-aware normalization | Unified provenance records and conservative contradictory-state reconciliation |
| 2 | Document reading | Authorized PDF/TXT/MD, isolated parser, continuation/search | Isolated DOCX/PPTX extraction with section/slide locators and hostile-archive tests |
| 3 | Change detection | Scoped complete snapshots, baseline limits | Availability, points, requirements and instruction fingerprints; sequential first-observed changes and stable dedupe IDs |
| 4 | Deadline reconciliation | Canvas dates only | Source-backed dated obligations, conservative matching, missing/conflicting dates and precision/timezone preservation |
| 5 | Grade auditing | Four native tools and Decimal engine | Reuse engine; shared provenance and 84-versus-91 acceptance fixture, retain unsupported-policy refusals |
| 6 | Instruction/rubric conflicts | Requirements and rubric retrieval | Passage-based contradictions, amendment evidence, draft review without predicted grades |
| 7 | Prioritization | Deadline/effort/prerequisite allocation | Explicit importance/student overrides, completed-work exclusion, urgency/importance explanations |
| 8 | Exam preparation | Material inventory and readers | Bounded assessment-focused evidence pack, explicit versus inferred relevance and repeated concepts |
| 9 | Calendar synchronization | Supplied busy windows; no Calendar credentials | Compose with native Google Calendar in ChatGPT: bounded availability/event inputs, deterministic dedupe and mapping markers, confirmation-only write proposals |
| 10 | Integrated audit | Separate grade/workload readers | Prioritized supported findings, evidence/impact/action and explicit unperformed checks |

Implementation remains one native MCP service. Canvas requests stay GET-only.
Calendar credentials remain in the existing Google Calendar connection; Canvas
Bridge will not acquire another grant or execute calendar writes from a Boolean
approval argument. ChatGPT must obtain explicit approval for the concrete event
proposal before using the separate Calendar tool. No real events are created by
development acceptance tests.

Each increment receives synthetic acceptance, missing/contradictory evidence,
authorization and bounded/stale-data checks. Shared adapters' existing pagination,
isolation and failure tests remain applicable; final checks include the complete
suite, native MCP contracts, dependency audit/CI and authorized live read-only
proof. Feature completion is recorded against observed acceptance, not route
registration. External deployment and institutional gates remain separate.

## Follow-on course breadth increment

Baseline `b175fae` already passed the 309-test full run; it was not rerun unchanged.
Original specification R03/R21 still lacked non-assignment discovery. The next
increment adds a fresh canonical obligation inventory through reviewed quiz,
discussion-topic and Canvas-calendar GET collections. Existing workload and study
plan contracts are preserved. Explicit aliases, source dates, unknown completion,
bounded continuation and authorization receive synthetic acceptance before a
private read-only check. See [scope and limitations](course-obligations.md).


## Follow-on timing correctness

Before expanding new-activity planning, a baseline audit reproduced date-only
deadline and DST capacity errors. The shared allocator now uses source-preserving
conservative date bounds and elapsed instants across native planning, saved-plan
validation and Calendar study proposals. Acceptance and limitations are recorded
in [planning date boundaries](planning-date-bounds.md).
