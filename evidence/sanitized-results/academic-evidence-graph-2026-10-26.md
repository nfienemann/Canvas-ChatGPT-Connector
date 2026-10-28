# Academic evidence graph — local synthetic verification

Date: 2026-10-26. Scope: the initial deadline/grade slice of
`academic-evidence-1`; no live academic records, provider calls, service restart,
database migration, deployment or publication.

## Implementation exercised

The existing authorized grade service now projects normalized records into
validated graph assertions, reads policy/category/assessment inputs from that
graph, and invokes the existing Decimal calculator. Deadline reconciliation
reuses the existing parser/matcher/date comparator and queries the graph for
supporting evidence and unresolved conflicts. Grade-policy tools link existing
Canvas and syllabus rule candidates without introducing another rule parser.

The shared model retains source versions, locators, observations, scope and
disclosure restrictions; compares authorized snapshots; invalidates dependent
results; and preserves old/new fact evidence in a bounded in-memory session.
Missing provenance stays unknown. Unknown/restricted third-party content is
withheld. Configured precedence requires verified policy evidence and does not
erase contradictory sources. Native tools do not infer a historical baseline.

## Actual checks

Final affected-suite command:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_evidence_graph.py tests/test_provider_architecture.py tests/test_extension_sdk.py tests/test_grade_audit.py tests/test_academic_intelligence.py tests/test_academic_dates.py tests/test_privacy.py tests/test_benchmark_lab.py tests/test_egress_policy.py -q --tb=short
```

Result: **381 passed in 78.34 seconds**. This includes **33 graph tests** covering
source attribution, scope isolation, legacy derived-basis preservation, source
versions, changed values under unchanged versions, transitive invalidation,
old/new facts with restrictions, missing baselines, permission expiry/revocation,
restriction intersection, prohibited classifications, prompt injection,
supersession candidates, configured precedence, incomplete dates, exact grade
results, native workflow integration and graph byte/expanded-provenance budgets.

An additional assertion that native deadline queries survive the privacy filter
was checked after the suite had collected tests: the focused test passed in
3.45 seconds. Grade graph and grade-rule graph privacy projections were also
checked in the suite. The earlier 379-test run preceded the last graph-consumption
integration; the 381-test result above supersedes it.

Scoped Ruff lint passed; Ruff format check passed for all 12 touched Python files.
Bandit passed on the three new production modules. The periodic/release benchmark
workflow YAML parsed successfully and now includes graph tests. The normal CI
pytest job discovers them as well. Hosted CI was not run locally. A whole-repository
full suite was not run for this change; existing unrelated dirty files were preserved.

## Academic regression comparison

```powershell
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --output .local/benchmarks/evidence-graph-2026-10-26 --baseline evidence/sanitized-results/academic-benchmark-lab-2026-10-26.json
```

The [saved JSON receipt](academic-evidence-graph-2026-10-26.json) records:

- 83 paired tasks on the same versioned fictional corpus.
- **81 objective passes, zero failures, two interpretation cases requiring review.**
- Objective, critical and no-regression gates passed; interpretation review is incomplete.
- **Zero regressions and zero measured correctness improvements** against the
  earlier local backend run. That reference is an actual prior run, not a promoted
  stable release or a model/competitor comparison.
- No confidence interval or latency improvement claim: this is a curated paired
  regression census without a shared controlled-performance-study reference.

Run: `6f47d502c2adc2fecd7f131c7d61232062687582f3a2370919ae0ab269d86fb8`.
Prior run: `5be3b7806f60e7110e4d12b840ac55852588b7c0f708477326ae769e48f0ab43`.
Source SHA-256: `17ffcfb4dac7109d09966da900fb137b64a63de46377be88e8c308066dfaee27`.
Corpus SHA-256: `8623a8031e7e00780e3d9720aa4d9dc5553d0050d8d3dfa82f0fa39d5cbef5b6`.
The runner recorded a stable source tree during measurement; the receipt source
hash was checked again before saving it. This fingerprint covers backend Python
and JSON sources, not documentation or repository publication status.

## Remaining boundaries

The graph vocabulary and evidence-backed relationship API cover the requested
entity types, but automatic requirement, lecture and learning-objective extraction
are deferred beyond this initial deadline/grade slice. The graph is not a visual
interpretation engine. Original grade provenance can still lack document-level
coordinates or independent upstream verification; those gaps remain explicit.

History is an authorized two-snapshot in-memory session, not automatically retained
student grade history or a new public history endpoint. Permission metadata in
graph JSON does not grant access. Existing gateway, source and recipient checks
remain authoritative. No external approval gate is satisfied by these results.

See [the implementation contract](../../docs/academic-evidence-graph.md) and
[release gates](../release-gates.md).
