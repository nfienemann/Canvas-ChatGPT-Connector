# Independent academic intelligence and authorization repair

Implementation: October 28, 2026. Local development; no running service, credentials,
institutional approvals or existing user database were changed.

Academic reasoning and permission to obtain or disclose its inputs are separate.
Independent processing uses the authenticated account and each source's current
permissions. It does not require an LMS connection. Institutional and derived
institutional records retain their original access and disclosure requirements.

## Findings and examined paths

| Examined surface | Finding | Resolution |
| --- | --- | --- |
| `get_saved_study_state`, local-only | Confirmed defect: middleware skipped institutional policy correctly, but `Bridge.local_state` unconditionally called `Store.connection`, which rejects inactive connections. | Owner-scoped legacy preference lookup bypasses connection **state**, never ownership. The optional connection ID selects the legacy namespace; omission reads independent account preferences. Unknown/empty namespaces return empty results. |
| `get_saved_study_state`, institutional mode | Legitimate institutional protection of stored plans, progress and other derived records. | Existing policy, connection and final egress checks remain. Missing connection is `needs_input`. |
| `update_study_preferences` | Same unnecessary active-connection dependency for schema-restricted preferences. | Only the `preferences/default` storage branch uses an owner-locked namespace without an active-state gate. All other saved-record kinds retain the original connection fence. |
| `get_local_study_preferences`, `update_local_study_preferences` | Independent namespace already existed. Reads needed validation of retained provenance and payload schema. | Validate owner, explicit origin, lineage, version and allowed preference fields. New records carry source category and content identity. |
| `list_local_documents`, `read_local_document`, `search_local_documents`, `get_local_document_status`, `prepare_local_study_materials`, `render_local_document_page` | Independent adapters already existed. MCP privacy projection omitted part/continuation metadata. | Reuse the importer/reader; preserve reviewed part, count, next-part and role fields. Strengthen known-origin, classification and operation checks. Rendering remains the existing separate tool. |
| `propose_study_plan`, `propose_course_study_plan` | Snapshot/course acquisition legitimately requires institutional access. Missing independent adapter. | New adapter normalizes permitted work records into the same `planning.propose` engine. No second scheduling algorithm. |
| `prepare_for_assessment` | Course selection/acquisition is legitimately institutional. | Reuse local document reads and extract shared bounded excerpt construction. Independent scope is explicitly selected, not claimed instructor scope. |
| `review_assignment_requirements` | Protected acquisition; reusable comparison already exists. | Reuse `instruction_findings` for instructions, rubrics and selected draft text. Qualitative grading remains review-only. |
| `calculate_course_grade`, `audit_course_grade`, `simulate_grade_scenario` | Institutional grade/source checks are legitimate. A manual numeric SDK existed but lacked this source-backed MCP path. | Reuse the Decimal kernel for permitted structured input and scenarios. No Canvas-reported grade is invented; syllabus interpretations require exact version/rule review. |
| `reconcile_course_deadlines`, `audit_course_consistency` | Protected source collection with reusable deterministic comparison. | Reuse date parsing/matching and requirement comparison with independent reference labels. Ambiguous years, identities, timezones and DST remain unresolved. |
| `propose_calendar_sync` | Snapshot acquisition is institutional; proposal construction is already pure. | Reuse `calendar_proposal` with independent labels, source versions and existing calendar evidence. Empty source URLs cannot falsely match unrelated events. |
| `run_academic_workflow`, semester overview, course study/practice services | Their existing contracts explicitly consume selected institutional courses. | Retain those gates. The additive independent entry point covers the supported capabilities below; it does not silently switch the old contracts to local data. |

The defect was reproduced through actual local HTTP MCP: disconnected local-only
state returned `reconnect_required / CONNECTION_INACTIVE`. Authentication of the
application user remained necessary throughout; LMS authentication was never used
as a replacement for that identity.

## Additive tool contract

`run_independent_academic_workflow(request)` accepts seven capability names:
`planning`, `assessment`, `requirements`, `grades`, `deadlines`, `consistency`, and
`calendar`. It is read-only. It has no connection ID, URL fetcher, tool-name argument,
permission override, source-classification selector or executable graph.

Each selected source has `document_id`, `expected_hash`, `start_part` and `limit`.
Use `get_local_document_status` for the current hash. Select at most five evidence
documents plus one structured academic dataset. Evidence documents can be materials,
instructions, rubrics, schedules or drafts. Each selection reads at most five parts;
reasoning uses at most 4,000 characters per part and marks truncation. Assessment
excerpts have the same 16,000-character overall ceiling as the institutional path.
Input/request/output ceilings are 80/60/120 KB. A larger request needs narrower scope.

The source adapter verifies ownership, retained provenance, exact version, permitted
operation, current integrity rules and recipient policy before reasoning and again
before output. If independent documents have a registered institutional dependency,
this route withholds them instead of initiating institutional retrieval.

The pure `academic/independent_engine.py` functions receive normalized values,
source references and an explicit clock. They do not create connections, read a
database, obtain credentials or call an LMS. The surrounding source adapter owns
authorization. The existing final privacy/egress middleware still runs through MCP.

## Supplying academic records

The versioned [records schema](schemas/independent-academic-1.schema.json),
[request schema](schemas/independent-workflow-request.schema.json), and
[stress-corpus adapter instructions](stress-repair-2026-10-28.md) are published
alongside this contract. Schema snapshots are checked against the implementation.

Existing permitted TXT/Markdown imports can contain an `independent-academic-1`
JSON object. This is a bounded structured data format, not executable content.
It supports up to fifty work items and one grading-policy/assessment collection.
The [fictional example](../tests/fixtures/independent-intelligence/academic-input.txt)
can be imported through the existing signed-in document settings page. Ordinary
assessment/requirement documents do not need this format.

Manually authored records use the same trusted import boundary. They are not
institutionally verified. Arbitrary conversational/model assertions cannot create
an owned source, assign its classification or supply institutionally protected IDs
as independent records. There is no model-callable import or approval operation.
This implementation does not add a conversational manual-entry form or a new dashboard.

An explicit import checkbox permits additional grade, planning and schedule use.
It does not grant external sharing: the recipient policy must separately allow
`grade_planning` or `schedule`, and text-sharing consent remains required. Combined
consistency review requires both `study` and `schedule`. Old imports and operator
policies are not silently upgraded. Reimport with the appropriate permission when
the source's use is permitted. Unknown rights need review, not a changed label.

Work dates, effort ranges and progress are user-supplied fields, never fabricated.
No supplied deadline means unknown timing. Assessment inclusion in grading defaults
to unconfirmed; `eligibility_verified` means the user has checked applicability,
not institutional verification. Unknown scores are not zero. Unknown weights,
incomplete coverage and unsupported rules preserve the existing arithmetic refusal.

For a syllabus interpretation, first inspect the returned policy version and rule
IDs. A subsequent `policy_review` must confirm that exact version, rule set,
completeness and applicability. Hypothetical modes also retain the existing visible-
inventory acknowledgment. Neither review establishes an official grade.

Calendar proposals require a fresh, complete listing and mapping search supplied
through the existing authorized calendar client. Missing calendar information is
unknown. Stable markers deduplicate proposals. Approval, fresh source/event checks,
provider writes and readback remain with the existing calendar workflow. This tool
performs none of those writes and never invents free time.

## Provenance, local state and migration

The existing encrypted `IndependentResource` namespace already separates imports
and account preferences from connection-bound `LocalRecord` plans/progress. No SQL
schema change or database migration is needed. New import provenance includes source
category, acquisition mechanism/time, content identity, owner attestation, retained
classification, lineage, permitted operations and sharing restrictions. Normalized
results retain exact parent sources, versions and restrictions.

New legacy preference writes include a hash-bound `user_manual` provenance envelope.
Local-only reads validate it and return the existing preference value schema.
Older plain preference records are accepted only when their complete payload passes
the known narrow preference schema; extra/mixed fields cause withholding. Plans,
practice, progress and unknown kinds never move into the unrestricted preference
response. Records are not deleted or recategorized because a connection is revoked.
Separate independent preference writes continue to use their existing encrypted,
versioned namespace and retention/deletion controls.

This is a non-destructive, read-time compatibility repair. Ambiguous legacy records
are retained but withheld. No records are copied across users or namespaces. Older
software may withhold the new legacy preference envelope; rollback must not strip
provenance or weaken authorization to recover it.

Mixed selections can preserve independent valid documents while excluding denied
sources before reasoning. The response is `partial_data` and exposes no denied
content. A single mixed/unknown import is conservatively withheld as a whole;
field-level salvage is not claimed. Known institutional byte fingerprints and
retained source/policy lineage continue to block relabeling and reimport laundering.
Undisclosed external origin cannot be conclusively determined from arbitrary text;
explicit rights attestation is not evidence that all restrictions have vanished.

## Diagnostics and validation

Results include capability, selected adapter, required institutional authorization,
policy decision category, included/excluded source classes, source versions and a
correlation ID. Logs and receipts contain no source bodies or credentials. No-source
and invalid-input failures are actionable independent errors; local storage failure
is `LOCAL_STORAGE_UNAVAILABLE`, never advice to reconnect Canvas.

Run the reproducible diagnostic from the repository environment:

```text
python -m pytest tests/test_independent_intelligence.py -q -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/independent-intelligence.json
```

Tests process real permitted fictional inputs through HTTP MCP with zero connection
rows and with connection lookup/network entry points set to fail if invoked. Other
tests cover revoked/disconnected/denied state, ownership, mixed records, purpose
restrictions, source mutation, policy review, privacy projection, calendar inspection,
deduplication, missing inputs, storage failure and equivalence with the shared engine.
The existing CI full pytest job includes these tests automatically.

Current executed results are recorded in the
[verification report](../evidence/sanitized-results/independent-intelligence-2026-10-28.md).
These synthetic results do not establish deployment, institutional approval,
independent scientific review, arbitrary document understanding or actual client
usability. Unsupported qualitative grading and visual interpretation remain explicit.
