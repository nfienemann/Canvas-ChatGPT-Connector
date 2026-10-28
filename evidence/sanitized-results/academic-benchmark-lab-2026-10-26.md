# Academic benchmark laboratory — October 26, 2026

All academic inputs and scientific plots are fictional. This work made no live
Canvas requests, model API calls, competitor installations, deployment changes,
approval changes, commits or publication. Existing uncommitted work in the shared
checkout was preserved.

## Executed outcome

- Versioned corpus: **12 courses, 83 scenarios**, with all twelve requested task
  categories represented. Fast tier: 43 cases.
- Final full benchmark: **81 objective cases passed; 0 failed; 2 scientific
  interpretation cases require independent expert review**. Objective and critical
  gates passed; `review_complete` remains false. No visual accuracy score is claimed.
- Final laboratory tests: **75 passed in 2.88 seconds**. These include independent
  arithmetic, deliberately corrupted product calculations, incorrect citations,
  withheld uncertainty, prohibited operations, privacy canaries, network blocking,
  missing comparison results, self-judging rejection, baseline gates and exact-byte
  fixture regeneration.
- Broader affected suite checkpoint: **313 passed in 49.05 seconds**. The final
  evaluator/environment/line-ending changes were then checked by the 75 laboratory
  tests and the final full benchmark above. A whole-repository full suite was not
  rerun; this is not a blanket green claim for unrelated work in the checkout.
- Scoped Ruff lint/format and Bandit passed. `git diff --check` passed. Both workflow
  YAML files parsed successfully. The existing compliance registry validation
  returned `valid` for 23 controls and **authorization_granted: false**; registry
  validity is not external approval or execution evidence for every control.

Exact final observations, category metrics, input/source fingerprints and environment
versions are retained in [the machine-readable report](academic-benchmark-lab-2026-10-26.json).
The environment receipt includes Python, OS, relevant library versions and the
dependency-lock hash. The source remained stable during the final benchmark.

## Actual commands

```powershell
.venv/Scripts/python.exe -m pytest tests/test_benchmark_lab.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/test_benchmark_lab.py tests/test_grade_audit.py tests/test_academic_intelligence.py tests/test_domain_planning.py tests/test_academic_dates.py tests/test_discussions.py tests/test_privacy.py tests/test_provider_architecture.py -q --tb=short
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --output .local/benchmarks/academic-2026-10-26
.venv/Scripts/python.exe -m ruff check src/canvas_bridge/benchmark_lab tests/test_benchmark_lab.py scripts/build_academic_benchmarks.py scripts/create_benchmark_media.py
.venv/Scripts/python.exe -m ruff format --check src/canvas_bridge/benchmark_lab tests/test_benchmark_lab.py scripts/build_academic_benchmarks.py scripts/create_benchmark_media.py
.venv/Scripts/python.exe -m bandit -q -r src/canvas_bridge/benchmark_lab
.venv/Scripts/python.exe -m canvas_bridge.cli compliance-report --validate-only
git -c core.safecrlf=false diff --check
```

The CI files were parsed with PyYAML in a separate ignored authoring environment.
The unit tests also execute the CLI baseline requirement and verify that missing
history returns a failing exit code. The rebuilt corpus uses explicit LF bytes,
matching repository checkout policy on Windows and Linux; the independent rebuild
test verifies the exact manifest fingerprint.

## Media verification

Both PDF pages were rendered with Poppler and visually inspected. Both PPTX slides
were rendered with the bundled Artifact Tool and visually inspected. PPTX package
integrity, geometry/font checks and exact-file import passed with zero findings.
Native PowerPoint execution was not tested. Visual layout inspection by the
authoring agent is not the independent scientific rubric review.

| Asset | SHA-256 |
|---|---|
| `scientific-lecture.pdf` | `2763b4da1e386a93add2ea7c03586a1ffc79f0d747a18bc2a68c4c80458f9d14` |
| `scientific-lecture.pptx` | `ce4fc1d7972cbda0ab0e2e462b77f7a37d29a7145b69e99dd8324302562d9fe4` |

Original plots used matplotlib 3.11.2 and reportlab 5.1.0 in an ignored authoring
environment. PPTX creation used bundled Artifact Tool 2.8.99. These authoring
packages were not added to the connector runtime or its dependency lock.

## Evidence boundaries

| Area | Status |
|---|---|
| Objective backend workflows and adversarial evaluator | Locally verified on synthetic inputs |
| Fast and periodic/release CI gates | Implemented and locally validated; hosted jobs not executed here |
| First previous-stable benchmark | Absent; required-baseline mode fails explicitly |
| Normalized LLM baseline | Import/export protocol tested; no real model run performed |
| Alternative Canvas MCP configurations | Receipt/mapping contract tested; no competitor installed or benchmarked |
| Scientific interpretation | Draft rubric; independent expert review and actual interpretation scoring pending |
| Statistical superiority | Unclaimed; curated cases do not justify population confidence intervals |
| Deployed ChatGPT/MCP latency and real-provider reliability | Not measured by the backend workflow lane |

Tool-call totals in this report are zero because the runner calls Python workflows
directly. Its operation trace and measured backend latency are not ChatGPT/MCP
client measurements. Unknown external token/resource/correction measurements stay
null. Privacy results cover the named synthetic guards and canaries; they do not
prove universal real-world anonymization or permission to disclose records.

See [the laboratory contract](../../docs/academic-benchmark-lab.md) for comparison,
review, baseline promotion, failure-capsule and corpus-maintenance procedures.
