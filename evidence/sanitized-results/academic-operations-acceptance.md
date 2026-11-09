# Academic operations acceptance

The supplied suite reproduced four failures on the starting checkout. All 114 assertions passed after the planning and calendar repairs. An authenticated HTTP MCP client then exercised the working source in an isolated synthetic Bridge with the Windows parser worker, real import IDs and content hashes. The planning clock was fixed per scenario. Authentication, import retention and response timestamps used the real clock.

## Student-facing source review

All dates below are scenario dates in America/New_York. The baseline assumes that all work remains. The briefs give seven, eight and eight hours for the whole assignments. The 18 step ranges are host estimates. Real progress and submission receipts are unknown.

- **Marketing research memo.** Due November 2 at 23:59 EST, moved from October 30. Prepare a 1,400–1,800-word decision memo PDF (exhibits excluded), an editable calculation workbook, and a source and contribution appendix. The student verifies counts, lift and economic assumptions, evaluates causal scope and survey limitations, then writes the recommendation and decision rule. MKT320-C01 is missing from the damaged archive. Claims about the experimental design need that source. Calculation explanations and mechanical editing require disclosure. Sources MKT320-A05 and MKT320-N01.
- **Operations recommendation.** Due November 6 at 17:00 EST. The brief says the date moved from November 4 and the 1,600–2,000-word range supersedes the 1,200–1,500-word template. Prepare the memo PDF (exhibits excluded), editable calculations and a data and assumption appendix. The student checks capacity, staffing, inventory inputs and limitations before writing the decision, evidence owners and operating guardrail. OPS330-N02 and OPS330-R04 are absent. The privacy check withheld OPS330-N01 at import. The current deadline and range are grounded in OPS330-A05. Calculation explanations and mechanical editing require disclosure.
- **Finance investment memo.** Due November 8 at 23:59 EST, moved from November 6. Prepare a management memo in DOCX, an annual cash-flow schedule in XLSX or CSV, base and downside valuations, and an explicit assumptions and authorship statement. The student constructs the schedule, calculates valuations and payback, and writes the recommendation. The brief says 1,000–1,400 words excluding schedules and the archived rubric says 800–1,000. Ask which range applies. The deadline correction addresses timing only. Assistance covers brainstorming about structure, assumptions and evidence. Sources FIN310-A03, FIN310-C01, FIN310-N02 and FIN310-U01.
- **Availability.** The selected preferences supply 22 hours of study windows, 45-minute blocks, ten-minute breaks and a final file-and-receipt check. The baseline adds a synthetic busy hour and pins the marketing check at 19:40–20:00 EST on November 2. Source BUS_SHARED_Study_Preferences.

The source manifest in the evidence ZIP gives document IDs and byte hashes for each source above. The source reads and requirements responses include their locators. The application extracted 22 cited work and deliverable passages from the three briefs and located the host’s step citations in their selected versions. Those checks establish the passages used. The student still decides how much work remains.

## Replanning results

Each row is a separate intervention against the baseline. Unscheduled totals are **work minutes**. Breaks and deadline placement affect how much calendar time is needed.

| Scenario | Known remaining | Allocated | Total unscheduled | Direct capacity | Blocked by prerequisites |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 1380 | 1010 | 370 | 70 | 300 |
| single-finance | 480 | 480 | 0 | 0 | 0 |
| deadline-extension | 1380 | 1020 | 360 | 60 | 300 |
| lost-evening | 1380 | 825 | 555 | 170 | 385 |
| analysis-completed | 1200 | 1005 | 195 | 110 | 85 |
| progress-isolated | 240 | 240 | 0 | 0 | 0 |
| remaining-estimate | 1290 | 1005 | 285 | 90 | 195 |
| missing-critical-source | 1335 | 900 | 435 | 0 | 435 |
| clock-advanced | 1380 | 375 | 1005 | 380 | 625 |
| earlier-deadline-pin-conflict | — | — | — | — | — |
| same-state-repeat | 1380 | 1010 | 370 | 70 | 300 |

Begin with the three source reviews on Thursday. The finance cash-flow schedule needs another 70 work minutes before the remaining valuation, recommendation, assembly and file check can finish. Reserve more time ahead of the finance deadline or revisit the remaining estimates. In the missing-source row, the 435 known unscheduled minutes are in addition to the finance recovery step of unknown duration. The earlier-deadline row has no executable plan. The evidence ZIP includes the full proposed schedule and host response for every transition.

## Verification boundary

Base commit `5bd086356e730b01b5a9f1be9de106446ef049c6`. The tested source-tree SHA-256 is `63636b6bf267a063663649c3e66e8baf0a3b32c16fc778316ec81941d304e741`. The checkout already had uncommitted changes. The source manifest was checked before and after the running-service replay.

The final sequence made 65 calls through the local MCP client. Separate controls covered five input permutations, stale and incomplete calendar listings, source replacement, confirmed updates, and a reimport that required review. Deleting an integrity-bound original caused the expected fail-closed response on its reimport. Production ChatGPT-client verification remains open. No service was deployed, and all calendar events were synthetic proposal inputs.

A broader intermediate run had 495 passes and one failure comparing the two planning entry points. After their summary fields were aligned, the final affected run passed 58 tests, including that comparison and the importer/MCP sequence. Ruff passed for the edited Python files. The full repository suite was not run or reused. Raw engine replay files retain the supplied harness's historical labels. The build manifest and dispositions identify the checkout actually exercised.

[Machine-readable dispositions](academic-operations-acceptance.json) · [Source hashes, MCP responses, engine replays and per-transition host answers](academic-operations-receipts.zip)
