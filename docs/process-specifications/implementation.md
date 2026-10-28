# Academic process specifications

The 20 Markdown files under `source/` are supplied requirements, not executable
instructions or authorization grants. `source/manifest.json` binds them to the
original ZIP. The implementation adapts their conceptual interfaces to the existing
Bridge service and preserves `Codex_Spec.md` and `evidence/release-gates.md`.

## Delivery map

Implementation is in `src/canvas_bridge/processes/`. Acceptance cases named
`test_cb01_` through `test_cb17_` are in `tests/test_process_*.py`. Additional
integration cases exercise authenticated HTTP MCP calls, deletion, source-version
races, encrypted persistence, corrections and exports.

| Spec | Implementation | Acceptance coverage |
|---|---|---|
| CB-01 | `evidence.py`: scoped claims, explicit supersession, trusted authority ranking, unresolved competing claims | Authority versus recency, partial coverage, incompatible scope |
| CB-02 | `impact.py`, `state.py`: canonical diffs, stable proposal IDs, dependent invalidation | Earlier deadlines, cosmetic changes, deduplication, withheld historical versions |
| CB-03 | `evidence.py`: coverage, extraction gaps, decision-specific sufficiency | Missing pages, unreadable evidence, high-stakes abstention |
| CB-04 | `state.py`: expiring previews, atomic revisions, concurrency, rollback | Interrupted transaction, concurrent commit, stale preview, transitive invalidation |
| CB-05 | `identity.py`: conservative multi-signal matching and reversible confirmed aliases | Different terms/owners, ambiguous links, preserved origins and permissions |
| CB-06 | `purge.py`, existing disconnect/withdrawal/retention hooks | Revocation purges current/history/preview payloads; unrelated imports survive |
| CB-07 | `lifecycle.py`, existing Integrity engine | Draft versus submission evidence, grade evidence, policy checks, archival |
| CB-08 | `knowledge.py`: concepts, relationships, evidence categories, review dates | Exposure never certifies mastery; unsupported assessments remain unverified |
| CB-09 | `feasibility.py`: effort ranges, commitments, prerequisites, buffers and breaks | Capacity shortfalls, three scenarios, timezone normalization |
| CB-10 | `degree.py`: versioned requirements, prerequisites/corequisites, credits, baskets and substitutions | Catalog ambiguity, prerequisite order, unverified completion/substitutions |
| CB-11 | `clarification.py`: cited question drafts, confirmed status changes, narrow responses | Self-service first, no automatic send, no global policy override |
| CB-12 | `trust.py`, existing authorization/egress wrappers | Instruction/exfiltration attempts remain untrusted; quoted examples remain usable |
| CB-13 | `state.py`, existing deployment-upgrade/backup recovery | Unsupported process schema refusal, encrypted recovery, authorization unchanged |
| CB-14 | `evaluation.py`, CI acceptance step | All 17 specs represented; every process test required; failures cannot average out |
| CB-15 | inventory, annotation, recovery and export methods | Scoped JSON/Markdown, deletion cascade, malformed portability input refusal |
| CB-16 | `diagnostics.py`: fixed-category report and exact preview | No raw logs, credentials, coursework or implicit transmission |
| CB-17 | `portfolio.py`: content/version-bound rights review and attribution/privacy checklist | Group/research holds, patient-data refusal, assistance never grants publication rights |

## Runtime and conversation tools

`BRIDGE_PROCESS_FEATURES_ENABLED` defaults to `false`. Enabling it registers eight
tools through the existing authentication, authorization, privacy, academic integrity
and recipient-egress wrapper:

- `evaluate_academic_process`: evidence, feasibility, lifecycle, identity, knowledge,
  degree, clarification/status, annotation and portfolio evaluation.
- `preview_academic_process_change`: prepare a local create/correction.
- `confirm_academic_process_change`: apply the reviewed preview with confirmation
  and a stable idempotency key; recheck permissions and policy at commit time.
- `get_academic_process_records`: inventory or inspect selected records.
- `get_academic_process_impacts`: inspect change proposals and repair needs.
- `preview_academic_process_recovery`: preview deletion or rollback.
- `export_academic_process_records`: return explicitly selected JSON or Markdown.
- `get_academic_support_report`: preview a minimal diagnostic report.

`BRIDGE_MCP_READ_ONLY=true` omits all three preview/confirm tools. Evaluation does
not save records. The conversation is the evidence inspector; no second dashboard
or chatbot is introduced. Tool descriptions require explicit student confirmation
of a preview before confirmation. This is a client interaction contract, not a
claim that a Boolean proves a human click.

Use existing tools to import independent documents or refresh selected-course
resources first. Process requests reference exact source IDs. Provider cache
observations must be current within 15 minutes; missing access is never repaired or
granted by a request. Caller interpretations, identity matching signals and manual
degree completion claims remain user-declared. Document text cannot assign itself
instructor authority. Observed official assignment deadlines come from the existing
authorized provider adapter.

For a local save, evaluate, request a preview with `record_id`, review its evidence
and changes, then confirm its `preview_id`. Use `expected_revision=0` for creation
and the current revision for correction. Retry uncertain confirmations with the
same idempotency key. Dependencies must be explicit and include inherited source
lineage. Corrections invalidate dependent records; repair requires a fresh preview.
A historical value whose exact version is no longer authorized is withheld even
when a current correction is permitted.

## Storage, deletion and recovery

State uses existing encrypted `IndependentResource` storage with kind
`academic_process_state` and schema `academic-processes-1`, with a monotonic state
version. It does not become an independently authorized source. Records include scope,
revision, source versions, dependencies, validity and timestamps. Revisions contain
actor, reason, before/after images, affected records and impact proposals.
The reverse dependency index is validated and cycles are rejected.

Each principal has at most 500 records and retains the most recent 500 history
entries and 500 idempotency receipts. An evicted preview cannot replay a mutation
because its state version is stale. State retains its original 30-day expiry;
saving does not extend it.
Source expiry and authorization apply independently. Encrypted previews are
limited to 30 pending entries and expire after 15 minutes. Principal locking,
state revisions and account-generation checks protect commits.

Source deletion, expiry, course withdrawal and connector disconnection purge linked
records, dependents, sensitive history and pending previews transactionally.
Unrelated imports survive. Record deletion removes dependent copies and leaves a
minimal receipt rather than a recoverable deleted before image. Rollback is a new
authorized revision; it cannot restore revoked rights or deleted source content.
Support reports and ordinary logs contain no academic payloads.

No new relational migration is required for these additive encrypted resource kinds.
Existing deployment-upgrade preflight, key binding, encrypted backup, journal and
restore procedures remain authoritative. Unknown process schemas fail closed;
there is no automatic conversion or destructive downgrade. Disabling the feature
removes its tools. A deployed rollback still needs a verified backup and compatibility
rehearsal; these tests do not establish that rehearsal.

## Capability boundaries

Feasibility uses a bounded deterministic heuristic and distinguishes a proven
capacity shortfall from failure to find a schedule. It does not promise an optimal
timetable. Degree outputs are unofficial and expose manual completion assumptions;
they do not certify graduation. Concept exposure is not mastery.
Clarification status records a confirmed event; no mail transport is installed.
Identity links preserve per-origin permissions and can be removed through recovery.

The portfolio core supports trusted human review bound to exact content and source
versions. The public MCP adapter has no trusted rights-review registry configured
and returns a review checklist/hold; caller approval flags cannot clear it.
Reviewed-export support is a tested internal contract, not an enabled publishing
path. Publication, messages, submissions, calendar mutations and autonomous
monitoring are absent.

## Verification and rollout

Run the synthetic suite with a fresh receipt path, then the process gate:

```console
python -m pytest -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/process-tests.json
python -m canvas_bridge.processes.evaluation --results .local/process-tests.json --output .local/process-evaluation.json
```

The recorder refuses to overwrite receipts. The gate requires current unchanged
source fingerprints, complete selection, a passing run, every process test passing,
and acceptance coverage for all 17 specs. It permits zero critical regressions.
CI runs the same gate after its full synthetic suite. Model interpretation accuracy
is not measured here; extraction precision/recall belongs to the existing academic
benchmark lab and separately reviewed datasets.

Actual commands and outcomes are recorded in
[the verification record](../../evidence/sanitized-results/process-specifications-2026-10-28.md).
Local backend evidence does not establish deployed acceptance, PostgreSQL concurrency
acceptance, native renderer/OCR execution, institutional approval or distribution.
This work did not change private settings, migrate a live database, restart the
installed plugin or enable these tools in a running client.
