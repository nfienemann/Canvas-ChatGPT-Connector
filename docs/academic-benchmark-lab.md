# Academic intelligence benchmark laboratory

The laboratory measures academic outcomes against a versioned fictional university.
It adds no MCP tools, production routes, student records, model-serving service or
dashboard. Its current executed lane calls the real **backend Python workflows**;
it does not measure a deployed ChatGPT conversation or claim superiority over an
LLM or another repository.

## Corpus and gold

`benchmarks/academic/v1` contains 12 fictional courses and 83 scenarios: 43 fast
cases and a full 83-case corpus. The full set includes 81 objective cases and two
interpretive cases awaiting independent expert review. Courses cover points,
weighted categories, mixed assessment denominators, missing/unposted grades,
extra credit, dropped/excused work, unsupported policy and incomplete evidence.
The records also include conflicting deadlines, qualitative requirements,
calendars, unknown effort, stale authorization, discussion participation,
prompt injections, and fictional private peer records.

The two-page PDF and two-slide PPTX contain original scientific plots as embedded
images. One shows mean/SD trends; the other uses a logarithmic axis with omitted
replicate information. Their scientific labels deliberately require pixels.
Text extraction tests assert partial visual coverage. They do not claim to have
interpreted either figure. The assets have been rendered and inspected for layout;
that inspection is not independent expert scoring of a candidate's answer.

The fixture license is scoped in `benchmarks/academic/LICENSE.txt`. All identities,
origins, grades and research observations are fictional. No external course
material was copied. Tests need no Canvas credentials, institutional permissions,
network access or authoring packages.

Files have distinct roles:

| File | Role |
|---|---|
| `dataset.json` | Normalized course/source records, exact locators, content hashes and access labels |
| `scenarios.json` | Task questions, input references, adapter operation, category and criticality |
| `gold.json` | Expected fields, relevant evidence, uncertainty, prohibited assumptions, calculations, operation and success/failure contracts |
| `rubrics.json` | Versioned scientific interpretation dimensions; currently draft, with no invented expert approval |
| `manifest.json` | Exact hashes for every corpus file and asset; corpus version and study design |

The grade oracle uses `fractions.Fraction` and a small literal arithmetic grammar.
It never imports the product calculator, executes formula code, or derives answers
from a candidate run. Gold values are explicit. A test deliberately corrupts the
production calculator and confirms that the independent benchmark rejects it.
Other objective gold contracts are explicit source-grounded counts, states,
comparisons and scheduling constraints. Inspect the gold and formulas directly;
they are not an opaque model-generated score.

## Local commands

Run from the repository root using its existing environment:

```powershell
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab validate
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier fast --output .local/benchmarks/fast
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --output .local/benchmarks/full
.venv/Scripts/python.exe -m pytest tests/test_benchmark_lab.py -q
```

Each run writes JSON metrics, a readable category table, exact candidate
observations and failure capsules. Failed cases remain under
`failures/<run-id>/<scenario-id>.json`, with the original task, source records,
gold, observation, source fingerprint and failure taxonomy. A later successful
run does not overwrite the earlier capsule. Review confirmed failures and retain
their scenarios in the versioned corpus before changing the implementation.

Exit codes are 0 for the requested gates passing, 1 for a failed gate, and 2 for
invalid inputs. An ordinary full run can pass objective gates while clearly
reporting `review_complete: false`. `--require-reviewed` additionally fails on
unscored interpretation. Missing observations count as failed tasks and never
vanish from the denominator.

The runner blocks DNS and socket connection attempts, runs cases sequentially,
uses fixed academic input times and fingerprints product source before and after
execution. A changing checkout cannot certify one source revision. No synthetic
approval mutates real connection state. Parser fixtures run directly through the
existing parser with known original bytes; this is not a new sandbox-isolation
certification. Existing parser, MCP, authorization and egress test suites remain
separate evidence.

## Measurements and interpretation

Reports retain separate category measurements for exact answers, numerical error,
source attribution, unsupported structured claims, uncertainty and task
completion. They record tool calls, network attempts, workflow latency, process
CPU, traced Python memory, human correction steps and optional external token
counts. Unknown external measurements stay null, rather than becoming zeros.
There is no weighted composite score.

Backend runs make zero MCP/model tool calls. Their operation trace records Python
workflow stages; their latency includes that backend stage and excludes a model,
ChatGPT host, real provider network, and human correction session. Peak traced
Python allocation is not process RSS, GPU memory or host resource consumption.
Each observation retains its measurements; category denominators remain explicit.

Structured fields must match the gold, cite relevant source IDs, versions, URLs
and locators, preserve required uncertainty, and avoid disallowed operations or
private canaries. Optional prose always requires independent claim review, even
when its structured fields pass. This prevents arbitrary unreviewed narrative from
receiving automatic success. It does not claim a universal semantic detector for
every possible false sentence.

The failure taxonomy distinguishes retrieval, coverage, parsing, visual
interpretation, calculation, inference, prioritization, stale evidence,
authorization, orchestration, and presentation/citation errors.

These are deliberately selected regression cases, clustered within 12 courses.
Repeated executions do not create additional independent academic observations.
Confidence intervals are therefore withheld, with the reason recorded. Any
population-level model study needs a preregistered sampling frame, independent
course/task units, equal inputs and conditions, adequate sample size, and an
appropriate paired/cluster analysis before confidence intervals or superiority
claims are justified.

## Baseline model and alternative configurations

Export the exact normalized comparison packet without gold answers:

```powershell
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab export --tier full --output .local/benchmarks/packet/tasks.json
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --comparison-set --output .local/benchmarks/bridge-comparison
```

Export copies the referenced PDF/PPTX bytes into the packet's `assets` directory.
Raw private upstream fixtures are excluded from this comparison cohort. The
packet gives every candidate identical source records, answer fields, task
parameters and uncertainty vocabulary. The public corpus is suitable for
regression testing, not a claim of contamination-resistant held-out evaluation.

Run the baseline model through an independently authorized evaluation environment
with normalized sources and **no specialized tools**. Preserve its actual model
version, full prompt, decoding settings, seed where supported, execution receipt
and telemetry. No model or competitor has been run by building this lab.

An imported candidate JSON has this structure (values below describe the contract,
not a completed benchmark run):

```json
{
  "schema": "academic-benchmark-1",
  "corpus_sha256": "<manifest fingerprint from validate>",
  "system": {
    "id": "<actual system identifier>",
    "kind": "normalized_model",
    "version_sha256": "<SHA-256 of immutable version descriptor>",
    "configuration_sha256": "<SHA-256 of preserved prompt/settings/seed configuration>",
    "measurement_scope": "model_end_to_end",
    "run_receipt": "<actual retained execution receipt>",
    "input_export_sha256": "<canonical digest of the exported packet JSON>"
  },
  "observations": [{
    "scenario_id": "<exact task id>",
    "answer": {},
    "evidence": {},
    "uncertainty": [],
    "operations": [{"name": "model_reasoning", "scope": "model", "success": true}],
    "response_text": "",
    "tool_calls": 0,
    "latency_ms": null,
    "human_correction_steps": null
  }]
}
```

Use `canvas_bridge.benchmark_lab.dataset.digest` for canonical JSON digests.
Each evidence receipt contains exactly `source_id`, `sha256`, `locator` and `uri`.
Do not interpret a version-descriptor hash as verified access to model weights.
Unmeasured CPU, memory, token usage and correction steps remain absent or null.

```powershell
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab evaluate --tier full --candidate candidate.json --output .local/benchmarks/model
```

For `alternative_tools`, retain real installation, authorization, run and tool
configuration receipts, plus an `operation_mapping` from actual native tool names
to the scenario's semantic workflow operations. Actual traces and counters must
reflect the installed configuration. Unsafe operations remain forbidden regardless
of their mapping. Imported provenance is labeled **externally attested, not
independently verified**. Inspect the receipts before publishing comparative
claims. Merely naming a repository, importing a manifest, or guessing its features
does not benchmark that repository.

`previous_bridge` imports and `--baseline <report.json>` support previous versions.
Pair only identical corpus/answer versions and task sets. The comparison lists
each improvement and regression separately; any regression fails its gate even
if many other cases improve. End-to-end model latency cannot be compared directly
to backend-only latency; the report explicitly marks different scopes.

## Independent interpretive review

The scientific rubric is **draft pending expert review**. An independent human
with relevant scientific expertise must review its axes, values, uncertainty,
causality and citation dimensions before changing its status to `expert_reviewed`.
Record the reviewer, expertise, review date, evidence and rubric version. Any
rubric change requires a new corpus hash and reviewed version; do not alter old
gold silently.

A candidate review file is a JSON list. Each entry binds `scenario_id`,
`corpus_sha256`, `observation_sha256`, `rubric_sha256`, `reviewer_kind: "human"`,
`reviewer_id`, `expertise`, `reviewed_at`, `review_record`, and `dimensions` mapping
every rubric dimension to `pass` or `fail`. The reviewer must differ from the
evaluated system. For optional prose on objective cases, the required dimensions
are `all_factual_claims` and `source_grounding`; the rubric digest is the canonical
digest of `{"dimensions":["all_factual_claims","source_grounding"]}`.

Pass reviews to `evaluate --reviews <file> --require-reviewed`. A valid human
attestation cannot override failed objective assertions or privacy checks. The
CLI records an attestation; it does not verify a human's identity or credentials.
No evaluated model is installed as its own judge, and no expert approval has been
fabricated for this initial corpus.

## CI, stable versions and scope

The existing CI workflow runs the fast gate before other build work and uploads
results even on failure. Its existing publication dependency therefore retains
the academic gate. The full laboratory workflow runs weekly, on release tags and
on explicit dispatch, including adversarial evaluator tests. Release candidates
require a real stable baseline; interpretation remains visibly unscored until
independently reviewed. `--require-reviewed` is available for a study that claims
interpretive performance. No branch-protection setting or hosted job was changed
or claimed executed locally.

There is no historical stable result at introduction. See
`benchmarks/academic/baselines/README.md` for deliberate promotion. Release
comparison reports this gap and fails when a baseline is required; it does not
invent a previous version. A new baseline cannot silently redefine critical gold.

To reproduce source records, run `scripts/build_academic_benchmarks.py` only during
an intentional, reviewed corpus revision. It uses explicit answers and an independent
rational stress cohort. CI consumes the committed assets. Optional media authoring
uses `scripts/create_benchmark_media.py` (matplotlib/reportlab) and
`scripts/create_benchmark_presentation.mjs` (the bundled Artifact Tool). Media
byte reproduction depends on the recorded authoring environment; benchmark runs
instead verify the exact committed asset hashes. Authoring dependencies are not
added to the product runtime.

Local results and remaining boundaries are in
[the execution record](../evidence/sanitized-results/academic-benchmark-lab-2026-10-26.md).
The institutional, privacy, public-distribution and deployment gates in
[release-gates.md](../evidence/release-gates.md) remain independent.
