# Dependency-ordered implementation record

| Ticket | Local deliverable | State / remaining proof |
|---|---|---|
| C01 audit/traceability | Empty local/remote repo inspected; R01–R43 and T01–T46 registered | Implemented |
| C02 feasibility | Current official MCP/auth/Canvas/distribution contracts reviewed | Implemented review; external gates unresolved |
| C03 boundaries | Typed principal/connection model, endpoint policy, vault, threat/data-flow ADR | Implemented local; independent review pending |
| C04 authenticated slice | Running official-SDK HTTP tools, scoped synthetic provider and negative tests | Verified synthetic |
| C05 actual student read | Private owner-only Rowan read through WorkOS, HTTPS tunnel and actual ChatGPT Pro | First read and short renewal proof passed; institutional OAuth and broader pilot remain pending |
| C06 coursework | Student courses, assignment pagination, effective dates/statuses and coverage | Verified subset; broader inventory pending |
| C07 planning | Effort ranges, priorities, bounded review, dependency ordering, busy times, pinned replanning and shortfall | Verified local; real student usefulness pending |
| C08 lifecycle | Disconnect, account-wide deletion, OAuth/queue fences, export, encrypted backup, restore journal, SSRF and parser fixtures | Verified local; hosted operations/sandbox pending |
| C09 live UX | Local settings keyboard/visual check, HTTP CSRF tests and private ChatGPT read | Broader ChatGPT workflows, mobile and native Calendar remain untested |
| C10 knowledge/math | Modules/pages/files, course-bound module references, scoped page search, text continuation, bounded file transport and simple-points primitives | Partial; binary extraction requires verified OS isolation; full policy subsets remain gated |
| C11 optional Calendar | No live grants/actions/receipts or notifications exposed | Deferred until independent authorization and approval proof |
| C12 distribution | Reproducible dependencies, guides, CI template, truthful claims | Source upload authorized; listing/license/live cost gates unresolved |

## Deferred public-launch follow-up

The owner selected a Rowan-first hosted release with zero student downloads and
no student API keys on 22 October 2026. The
[public-launch roadmap](../docs/public-launch-roadmap.md) records the dependency
order, external approval gates, onboarding target, and acceptance scenarios for
C12 with dependencies on C05/C08/C09. This work is deferred while current
correctness and reliability issues are addressed. No implementation, outreach,
hosting purchase, student pilot, or directory submission is started by this record.
