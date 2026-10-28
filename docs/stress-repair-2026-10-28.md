# Stress-test diagnostics repair and offline execution

Implemented October 28, 2026 from the supplied repair brief. The attached report
was reproduction evidence; its fixture results were not treated as product results.
The supplied ZIP SHA-256 is
`ad17863adc9c1edc9248702be90ee53f8f4ac4f0d2372b1f69303745c273d873`.
Only fictional fixtures were copied into `tests/fixtures/stress-repair`; the
fixture registry binds their bytes. Gold answers are never imported as sources.

## Diagnosis and changes

Five empty independent requests failed Pydantic validation before reaching their
workflow handler. FastMCP converted those exceptions to SDK errors, and
`fence_mcp_outputs` correctly removed unreviewed error text. The two other
capabilities reached the handler and produced the existing safe missing-input
error. Thus, removing final error redaction would expose inputs without repairing
the actual validation boundary.

The transport now recognizes a bounded set of custom validation codes and field
locations before SDK invocation. It reconstructs fixed diagnostics through the
same egress and final privacy serializer. It never serializes exception messages,
contexts, rejected values, document IDs or source content. Unknown validation
failures retain the existing redaction. Valid requests follow the complete normal
authorization, integrity, processing and final egress path.

All seven missing-source branches return `needs_input / INDEPENDENT_INPUT_MISSING`
with capability-specific required fields and the signed-in import/selection path.
Empty integrity scopes explain local scope alternatives. Missing/invalid hashes
use `INDEPENDENT_HASH_REQUIRED`; authorized stale versions use
`INDEPENDENT_SOURCE_CHANGED`. Ownership, provenance and current sharing are checked
before version comparison so unknown, foreign and restricted IDs produce the same
denial. Unsupported native versions/formats and malformed native data have safe
schema guidance without a successful calculation claim.

`integrity/guidance.py` supplies one static guidance builder to policy decisions,
guidance and assistance refusals. It includes permitted administrative
alternatives, limits, needed policy evidence and suggested clarification topics.
These alternatives still require authorized sources; acknowledgments cannot grant
instructor permission. The builder generates no assessed submission and sends no
message. Inactive-connection errors list independent setup checks and explain
that reconnection alone does not establish approvals. Those checks do not assert
which additional blockers are currently present.

## Published native format

The supported version is exactly `independent-academic-1`. The checked-in schemas
are generated from the deployed Pydantic models and tested for equality:

- [Academic records schema](schemas/independent-academic-1.schema.json)
- [Workflow request schema](schemas/independent-workflow-request.schema.json)
- [Fictional complete example](../tests/fixtures/independent-intelligence/academic-input.txt)

Import a permitted TXT or Markdown file containing the JSON object through the
existing authenticated document settings UI. Explicit source ownership, text
sharing and academic-analysis consent remain necessary. Fetch its real ID and
`content_hash` using `get_local_document_status`, then select it as `dataset` with
`expected_hash`. Requirements/assessment evidence instead uses `documents`.
Conversation attachments do not populate this store.

Unknown scores remain `null` with `score_state: "ungraded"`. Date-only values use
`kind: "local_date"`; timestamps require explicit offset information. Partial
course inventory remains partial. Calendar proposals require fresh authorized
event and mapping coverage on the live route; they perform no writes.

## Reproducible offline harness

From the repository's configured Python environment:

```powershell
.venv\Scripts\python.exe scripts/run_stress_repair.py --output .local/stress-repair-new-run
```

Use a fresh output directory. A targeted rerun can add
`--select 'GR-01 or OP-04'`. The script runs the explicit 73-case catalog;
`tests/stress_repair_cases.py` is intentionally outside ordinary pytest discovery.
Failures return a failing pytest exit status. Unsupported cases are pytest skips
and are recorded as **BLOCKED**, never PASS. A run with changed source hashes is
invalidated. Exit success alone does not mean every case passed; inspect
`summary.json` and coverage limits.

`tests/stress_support.py` validates the neutral package marker and native model,
adapts supported points/weighted/drop/bonus and planning records, and retains a
course-specific sidecar with the source hash, source locators, term and unsupported
sections. It does not turn unsupported facts into anonymous text. The 12-course
import regression loads all 36 fictional Markdown sources through the normal
importer with LMS entry points disabled. Each scenario has a separate disposable
profile, real generated IDs and current hashes, preventing cross-course mixing.

The harness calls HTTP MCP and the normal independent workflow where available.
Process-only cases explicitly record the pure/repository operation used. Synthetic
provider authority, acknowledgments and permissions exist only inside disposable
fixtures. They never become production permission. Calendar context is explicitly
synthetic and only reaches the pure proposal path. Parsers process the fixture
bytes in process; this is not an OS parser-sandbox acceptance run.

Each case receipt includes original expected/forbidden results, exact test input,
observed output, imported source hashes, coverage limits and PASS/FAIL/BLOCKED.
`build.json` binds the application commit, working source/test/migration/fixture
hashes, interpreter and key dependency versions. These exact inputs and outputs
are fictional; live smoke evidence separately retains only static outcomes and
request IDs. Document pagination follows returned cursors and checks every
returned hash. The local reader has no hash argument, so this checks continuity
rather than claiming an atomic version-bound continuation API.

## Evidence boundaries

The later [follow-up repairs](stress-followup-2026-10-28.md) address the three
failures and expand evidence for previously blocked cases. The initial report
remains a historical record of its own source-bound run.

The [verification report](../evidence/sanitized-results/stress-repair-2026-10-28.md)
separates fixture self-checks, product integration, repository regressions and
installed-connector smoke. Blocked visual cases have no observed pixels; successful
rendering or text extraction does not establish visual interpretation. Disposable
SQLite recovery does not establish fresh Windows installation/rollback acceptance.

This repair does not migrate the personal database, grant approvals, reconnect
OAuth, import the corpus into the personal store, expose institutional content,
or add writes/publishing. Existing release and independent-review gates remain.
