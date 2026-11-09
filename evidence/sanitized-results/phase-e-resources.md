# Phase E resource and lead-time planning

The local implementation covers PHE-01, PHE-02, PHE-03, PHE-04 and the PHE-QA-01 acceptance workflow. The case report maps 28 scoped cases to executed evidence across all 16 synthetic scenario groups.

| Spec | Observed outcome |
| --- | --- |
| PHE-01 | Typed phases separate student attendance, passive run time, resource quantities and supplies. Resource aliases, versioned capacity intervals, scoped bookings, known-at checks and course-zone calendars are represented. An optional source passage is checked against the imported version. |
| PHE-02 | The prototype consumed 65 active minutes, 120 unattended minutes and 135 station-minutes. A serial elapsed chain had a forward-verified latest start of 15:00 UTC. The capacity-limited case proved a 60 station-minute shortage. The bounded unsuccessful case returned its search limit. |
| PHE-03 | An outage moved a run from FORM-A to compatible FORM-B with zero student blocks moved. A delayed supply moved its affected block 120 minutes. A real Phase C material change rejected the old forecast and gave the new work episode distinct blocks. |
| PHE-04 | Saved generations retain their bases, proposed operations and actual receipts. A later event edit blocked a compensating inverse. The signed MCP client verified all required Phase F record, artifact and blocker fields. |
| PHE-QA-01 | Four native Codex sessions used five distinct serving processes. Before recovery, one calendar effect was confirmed and one reservation response was uncertain. A fresh process found the committed reservation by its operation ID. The other three calendar proposals remained pending. |

## Verification

The canonical archive passed 344 package checks and 15 negative controls. Its standalone fixtures passed 220 checks and 12 negative controls. The broad regression run passed 281 tests with eight opt-in cases skipped. The Phase E native journey passed separately. The final targeted run passed 64 tests with two opt-in native cases skipped. These test populations overlap. Ruff passed on the changed Python files.

The resource engine adapts the supplied reference arithmetic for bounded candidate checks. It also generates candidates from real typed inputs, derives proof candidates, scopes uncertainty and validates placements independently of the bundled fixture files. Runtime code uses the owned journal and source authorization gates. The case evidence distinguishes package checks, generated and supplied placements, signed MCP calls, persistent provider-double effects and final host answers.

The final reviewed source fingerprint is `dddea641b0bf228de17f4bea041d11b5fa7c65b3be40b750d3bc019cf64c26be` on base commit `5bd086356e730b01b5a9f1be9de106446ef049c6`. The native run began on fingerprint `79971a4488046d27862b473d3a5f1e588b03cb4e9c442530a9d5c8fa61a5e27a`. The final targeted gate covers the subsequent capacity, consumable quantity, turnaround and action-capability checks. The scoped eleven-file patch was applied to a temporary reconstruction of the Phase D base and compared with the delivered text.

The receipt ZIP contains the 28-case report, eight measures, tool schemas, scenario results, native calls and answers, actual provider recovery readbacks, the Phase F handoff and a verified hash manifest. Production deployment, installed ChatGPT acceptance, a live facility provider and a repository-wide full test run remain outside these checks. The downstream Phase F workflow was not started.
