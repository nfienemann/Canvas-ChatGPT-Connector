# Unified academic evidence graph

The `academic-evidence-1` model provides a common evidence foundation for the
existing deadline and grading workflows. It is a bounded Python/Pydantic graph;
no graph database, model API, Canvas write, roster API or new MCP tool is needed.

## Implemented slice

- `reconcile_course_deadlines` and `audit_course_consistency` return an
  `evidence_graph` built from the existing deadline reconciler. Its exact-title
  matches, ambiguous identities, missing years, date precision and timezone
  rules remain authoritative. The projection also compares matched document
  assertions with one another using the same date comparison function.
- Grade calculations return `evidence_graphs` alongside their unchanged
  calculations. The existing Decimal engine consumes policy/category/assessment
  assertions from the validated graph after gateway authorization.
  `get_course_grading_policy` and grade audits also return a
  `rule_evidence_graph` connecting conflicting or supporting Canvas category
  weights/drop rules and existing syllabus rule candidates. No second grade
  calculator or syllabus parser was introduced. Native responses include graph
  deadline queries and uncertain-rule queries with their supporting evidence.
- The vocabulary includes course, assessment, assignment, deadline, grade rule,
  grading category, learning objective, lecture, document, passage, figure,
  calendar event, study obligation and source assertion. It supports all nine
  requested relationship types. Automatic extraction in this slice is limited
  to deadlines and grades. Lecture/objective/requirement relationships can be
  represented with supplied evidence; new automatic extraction is deferred.

## Evidence contract

Every assertion references at least one observation or preceding assertion.
Calculated/inferred assertions require explicit dependencies. Observations keep
the original source ID, provider, version/hash, supplied URI and locator,
source type, observation/verification times, course and institution scope,
permission decision, expiry and original restrictions. Scope also includes the
principal and connection internally. The public projection omits those internal
identity fields.

An absent original locator/type stays unknown with an explicit limitation.
`not-returned`/`not-recorded` version markers mean unknown, not content hashes.
Some legacy Canvas grade inputs use hashes/locators of normalized grading
metadata; these are labeled accordingly and are not claimed to be original
document coordinates. The adapter-supplied calculation policy is labeled inferred
with a provenance limitation, rather than verified instructor policy. Synthetic
fixtures and local user input retain their actual source type and basis.

`Provenance.source_type` is an additive optional field in `academic-1` (older
inputs remain valid). The graph has its own independent schema version.

Entity/assertion identifiers bind scope/content. Graph validation rejects
unknown references, dependency cycles, mixed known versions of a source,
cross-student/institution/connection/course evidence and oversized snapshots
(2 MB; 1,000 observations/entities, 2,000 assertions, 4,000 relationships and
10,000 expanded assertion-to-source references).
Limits fail explicitly; they never silently truncate a graph into completeness.

## Queries and authority

The internal `EvidenceGraph` API provides:

| Question | Operation |
| --- | --- |
| Best-supported deadline / evidence for a requirement | `query(subject, predicate)` |
| Uncertain grade rules | `uncertain_rules()` |
| Contradictory documents | `conflicting_documents()` |
| Assessments linked to lectures | `related(reference, RelationKind.ASSESSES)` |
| What changed | `changes(previous, current)` / authorized session `history()` |

Queries return candidate assertions, citations, conflicts, possible supersession,
selection basis and uncertainty. They do not use recency as authority. Amendment
language may create a **candidate** `SUPERSEDES` edge only when the existing
reconciler establishes the assignment identity. Ambiguous matches stay separate.
Conflicting assertions and their citations remain present after policy selection.

`PrecedenceRule` is trusted application configuration, scoped to the exact
principal/institution/connection/course and predicate. It requires an explicit,
verified policy assertion in the graph. Documents and model/tool arguments cannot
install rules. There is no automatic precedence configuration in the MCP tools.
Tied preferred sources remain unresolved. Policy selection is evidence-based
configuration, not a claim that the connector independently verified the
instructor's intent.

## Freshness, invalidation and history

`changes` distinguishes a new observation, changed version, changed restrictions,
and a source not observed in the new snapshot. Not observed does not mean deleted.
It marks assertions and transitive derivatives whose supporting evidence changed
or disappeared, including changed fact values under an unchanged source version.
Changed facts retain old/new values together with both versions' provenance and
restrictions; the authorized session guards access to both snapshots.
Versionless evidence cannot validate an old derivative. The fresh grade/deadline
workflow reruns the existing deterministic engine and builds a new graph; old
results are never reused as current calculations.

`EvidenceSession` holds at most two snapshots in memory. A trusted application
must supply an authorization callback that checks access to the original sources,
including historical versions. The session checks scope, purpose, recipient,
expiry, freshness and prohibited classifications on update/read, and calls the
authority again before releasing a query. Failed updates leave the previous
snapshot intact. `clear()` removes both snapshots.

The pure graph and comparison functions **do not authorize access**. Existing
provider gateway consumption/release and final MCP access/egress checks remain
required. Serialized graph JSON cannot serve as an authorization receipt.

No automatic durable grade history or new database migration is introduced.
Current native tool responses explicitly say `no_prior_snapshot_supplied`.
Historical queries are available to an authorized in-process session; they are
not a new public history endpoint. Missing prior snapshots never become evidence
that a deadline or rule changed. A prior observation without verification is
reported as such, not as a verified historical baseline.

## Restriction inheritance

Derived facts union all source classifications, intersect allowed purposes and
recipients, use the earliest permission expiry, and retain every original source
restriction/ownership statement. A local calculation or graph projection cannot
grant sharing permission. Native graph adapters conservatively apply the union
of participating source classifications; the existing exact-source egress gate
still controls release. A stricter/new restriction invalidates old derivatives.

The session withholds unknown/unclassified, third-party educational,
restricted-assessment and confidential-research sources. Prompt-injection text
does not alter permissions, precedence configuration or numerical algorithms.

## Reproduction

```powershell
.venv/Scripts/python.exe -m pytest tests/test_evidence_graph.py -q
.venv/Scripts/python.exe -m pytest tests/test_provider_architecture.py tests/test_grade_audit.py tests/test_academic_intelligence.py tests/test_academic_dates.py tests/test_privacy.py tests/test_benchmark_lab.py -q
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --output .local/benchmarks/evidence-graph
```

The graph regression fixtures are fictional. The normal CI pytest job discovers
them automatically. The academic benchmark continues to gate numerical/privacy
regressions independently of graph representation. This local implementation
does not establish live institution, recipient, deployment or distribution
approval; [release gates](../evidence/release-gates.md) continue to apply.
