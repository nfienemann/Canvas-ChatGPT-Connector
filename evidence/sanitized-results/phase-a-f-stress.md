# Canvas Bridge A–F validation and stress testing

The six supplied archives were verified against their pinned hashes. The package and standalone fixture validators ran separately. Package totals already include fixture checks for several phases, so the two columns should be read separately.

| Phase | Package checks passed | Standalone fixture checks passed | Package negative controls passed |
|---|---:|---:|---:|
| A · Integration benchmark | 267 | 150 | 6 |
| B · Persistent readiness | 709 | 578 | 15 |
| C · Change impact and reconciliation | 1,283 | 1,122 | 25 |
| D · Forecasting and replanning | 606 | 484 | 16 |
| E · Resources and lead time | 344 | 220 | 15 |
| F · Artifact and group handoffs | 396 | 254 | 15 |

## Reproduced defects and regression coverage

| Phase | Failure and verified behavior |
|---|---|
| A | An empty import and matching empty inventory could certify a canonical case. The audit now checks the exact fixture membership and source identities. Text appearing in the slide body could also count as notes evidence. Each slide and notes check now requires the text on the corresponding native surface. Four fresh, isolated Codex reviews exercised baseline, repeat, corrected, and missing-deck cases. |
| B | Whitespace-only quotes anchored unsupported claims. Bounded assessments could certify all claims after inspection of just one selected artifact. The save path rejects empty normalized quotes and checks complete part coverage of each artifact. Previously saved multi-artifact assessments without that proof require review. Six waves of eight writers tested revision contention and winner replay. |
| C | Removing a blank line could convert a thematic break into a heading while retaining a proof of equivalence. Two different headings starting with the same criterion ID could also hide a changed clause. The comparison preserves structural differences and considers every section for that ID. Eighty reordered native packages preserved equivalence, while modified notes, ambiguous paths and oversized member inventories were detected. |
| D | An explicit zero remaining estimate produced a one-minute planning budget. Zero now survives rounding, scoped user overrides still govern active work, and completed work reserves zero. The overlap check previously compared pairs of simultaneously active intervals. It now counts distinct active episodes across interval boundaries. A pairwise oracle checked 100 shuffled populations, including adjacent intervals and overlaps within an episode. A separate load compared the earlier Phase D implementation with the current one using 500 validated histories and 16,000 timer intervals. The outputs matched exactly. Across three alternating, local runs, the median fell from 1.178 seconds to 0.083 seconds. |
| E | Zero run time let a complete candidate skip required setup and cleanup. In a partial schedule, 4,160 unrelated calendar windows exhausted the candidate search and dropped two feasible blocks. The corrected planner returns the same blocks with and without those windows, serving 120 minutes and reporting a 60-minute shortfall. A minute-level oracle checked 160 fractional-capacity schedules. Concurrent provider confirmation and lookup now converge on one durable effect and reject different receipts. |
| F | The article “A” and a grade of “B” could be mistaken for grounded member assignments. Short member IDs now require qualified mentions or a distinct full label. Concurrent send and lookup could report an idempotency conflict for the same durable output. Both callers now recover the confirmed receipt, with one synthetic effect. A different receipt still raises a conflict. |

A deterministic 180-case sweep also checked readiness precedence, corrected and retracted effort intervals against a per-minute oracle, and per-recipient acknowledgment state as of a cutoff.

## Execution boundaries

All coursework, output destinations, calendars and reservations were synthetic. Native runs used Codex CLI with a local, signed MCP server. Phase A's planning turn exposed its existing input boundary: the prose brief did not satisfy the structured planning schema. The host provided a proposed session, and the planning interface reported no saved or calculated plan. Visual layout and private host context were outside the text benchmark. Actual delivery, live calendar and reservation providers, installed ChatGPT acceptance and deployment remain unverified.

The run used the dirty working checkout based on commit `5bd086356e730b01b5a9f1be9de106446ef049c6`. The repository-wide Python run began during remediation. Separate final-source regressions exercise the changes made after that run started.


## Local verification

- The final A–F adversarial and B–F integration run passed 122 tests. Its nine opt-in host cases ran separately and all passed. Phase A passed its four native benchmark cases and separate build binding. Source-surface checks passed for all 15 imports across the four cases.
- The broader focused Python run passed 188 tests, with 14 opt-in tests skipped in that invocation. All 87 Node tests passed. Ruff passed across source, tests and scripts.
- Two older inventory assertions surfaced during the broader run and replay. One read the first diagnostic from a multi-branch response instead of the branch deliberately timed out. The other expected a transient metadata outage to purge cached content. The revised test verifies withheld reads/search, same-version recovery after reauthorization and purge after an actual file-level denial. All 36 tests in the affected module passed.
- The first repository-wide Python run recorded 2,847 passed, 59 skipped and one failure in the older cache assertion. After correcting the tests, a new full run on the final checkout recorded **2,863 passed, 59 skipped, zero failures** in 34m 37s (Hypothesis seed 188523424020898739335223277999419119286). Fourteen skips were the A–F opt-in cases, all exercised separately. The remaining 45 required other supplied suites, a Linux kernel, a disposable PostgreSQL database, or configured OCR/converter runtimes.

## Follow-up on open cases

**Phase A planning.** A supplemental signed MCP call produced the four-block BenchLink session from the earlier host review. It used a structured parent and four child steps, explicit assistant estimates and dependencies, and the supplied 14:00–15:00 UTC window. The returned allocations were 10, 20, 15 and 15 minutes. All 60 known minutes fit. No academic deadline or student completion was inferred. The original frozen prose-only capture remains an observation of the earlier interface.

**Phase D cases PHD-T16 and PHD-T27 now pass for the synthetic supported-host scope.** A signed client selected one Canvas assignment and one saved readiness forecast, then read the assignment before and after a source revision. Applying the earlier deadline conflicted with a future pin. The failed attempt preserved the generation. A new explicit release of that named future placement allowed the planner to move the same block and schedule all 30 minutes. Duplicate IDs, unknown IDs and releases after the block had started at the planning boundary were rejected. Changing only a placement protection leaves an already confirmed provider event untouched.

In a separate actual Codex turn, the prompt identified the assignment and forecast and omitted the deadline. The host fetched a third source version, applied its current effective timestamp in the existing timezone, saved the local generation and retrieved it. The source-to-work association was an explicit student selection. This verifies the connected source selection that was missing in the original Phase D report. Published historical receipts retain their original verdicts. [Synthetic source versions, block allocations and native readback](phase-a-f-closeout.json)

**Previously skipped environments.** The archived academic suites passed on the supplied files. The disposable PostgreSQL run passed 11 tests. The OCR and slide-converter modules passed 114 tests on the installed runtimes. A temporary, unprivileged WSL2 Linux test environment reproduced a CPU-limit diagnostic error. The kernel could kill a worker just below the launcher’s accounting threshold when both CPU limits were identical. The worker now receives SIGXCPU at nine CPU seconds and retains its ten-second hard ceiling. All 14 Linux sandbox tests passed on the correction, including the real process, network and file-isolation probes. Both disposable Linux environments were unregistered after testing.

**External acceptance.** The connected personal installation available in this chat did not advertise the new A–F tools. Verification against an installed ChatGPT test client and real provider destinations requires a designated test installation and destinations. Phase C compensation succeeded via signed MCP. Its noninteractive native host requires approval for the destructive recovery operation. Phase E’s interrupted native scenario explicitly requested that the other proposed calendar operations remain unissued.

**Final checks.** The expanded repository-wide Windows run passed 2,897 tests with zero failures in 33m 20s. Its 27 skips were 13 Linux-only tests and 14 opt-in benchmark checks. All of those cases passed in the separate real Linux and native-host runs. Final focused regression coverage passed 97 tests, including the protection-only provider case added after full-suite collection. Ruff passed. The Phase A source-binding guard rejected an intermediate matrix after the planner changed; a fresh binding passed all four reviews and the audit verified the returned text surfaces for all 15 imports. The PostgreSQL fixture server stopped and the two temporary WSL distributions were removed.
