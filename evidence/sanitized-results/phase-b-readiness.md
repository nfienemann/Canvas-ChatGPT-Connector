# Phase B persistent assignment readiness

The five Phase B specifications were integrated in dependency order into the existing academic-process feature. A host can now save an evidence-backed assignment review, recall it after the service restarts, record progress and propose work using the existing planner. The tested scope is independently imported materials in a signed, synthetic loopback deployment.

| Native journey | Observed result |
| --- | --- |
| Baseline review and fresh recall | Revision 1 held four required criteria, with three needing work and one satisfied. The fresh host recovered the same revision, assessment time, evidence, bindings, counts and tasks after a serving-process restart. |
| Personal progress and planning | Revision 2 recorded the limitations task as personally done. Its artifact criterion still needed work. The planner used two assistant-supplied effort ranges to allocate 40 minutes within the supplied one-hour window. |
| Corrected deck | Revision 3 assessed all four criteria as satisfied. The corrected 410-second rehearsal had a ten-second margin. The earlier baseline revision remained retrievable. |
| Missing deck and fresh recall | Three deck-content criteria stayed unknown with one grouped followup. The retained rehearsal supported one timing action for the named baseline version, 35 seconds over its limit. |

All 24 scoped acceptance cases passed in the combined evidence. Fourteen evaluator-authored scenarios produced 56 matching criterion results, including status, version applicability and coverage. Nine deterministic controls covered aggregation and applicability. Source sharing changes withheld affected rows, and two concurrent updates from the same revision produced one commit and one explicit conflict. An injected transaction failure left the prior snapshot intact.

Six fresh Codex CLI host turns and two actual process restarts exercised Phase B. The four native Phase A reviews and the planning probe were replayed independently on the same product fingerprint, with the earlier baseline’s supported findings and control outcomes preserved. The focused existing regression run passed 144 tests. Package validation passed 709 checks and all 15 negative controls.

The native matrices used base commit `5bd086356e730b01b5a9f1be9de106446ef049c6` plus working-tree changes, product manifest `75168594ec51317aeb22fc3fe54313a9c365e001ce3b72366eb19c4920922eb0`. The final diagnostic overlay changed only the fixed error catalogs in `egress_errors.py` and `processes/reasons.py`. It exposed actionable public quote/locator errors and passed five readiness tests and 22 diagnostic regressions on product manifest `df38c4c555a23f6d41391596694e4a356b02fd0a4ced5882edb6e9cd843e20d1`. Both per-file manifests are included. A repository-wide suite, deployment and installed ChatGPT client acceptance were outside this verification.

[Replay instructions](../../benchmarks/academic/phase-b/README.md) · [Verified receipts, transcripts, scorecard and Phase C handoff](phase-b-readiness-receipts.zip) · [Implementation patch](phase-b-readiness.patch)
