# Registrar final-time lookup

Deadline reconciliation, course consistency audits and Calendar planning now return
an optional `registrar_lookup` handoff when retrieved evidence leaves final timing
uncertain. This is a ChatGPT/Claude host composition workflow: Bridge supplies
course evidence and the procedure; the student's existing authorized institutional
email connector searches and reads original messages. Bridge neither reads a
mailbox nor accepts email evidence back through a new permission path.

## Tool contract

`reconcile_course_deadlines`, `audit_course_consistency` and
`propose_calendar_sync` accept optional `registrar_lookup` identifiers:

```json
{
  "term": "Fall 2026",
  "term_start": "2026-08-20",
  "term_end": "2026-12-22",
  "courses": [
    {
      "course_id": "selected-course-reference",
      "course_code": "ETH101",
      "section": "01",
      "crn": "12345",
      "campus": null
    }
  ]
}
```

These are conversation-supplied identifiers, not independently verified facts or
permission. Unknown identifiers remain null. Without this argument, the handoff
asks the host to establish the term from available authorized context. The schema
rejects messages, sender claims, tokens, notices and transfer-permission flags.
Course references must belong to the selected audit/snapshot scope.

`run_independent_academic_workflow` accepts the same optional field inside its
request for `deadlines`, `consistency` and `calendar`. For this source-neutral
adapter, `course_id` is the selected dataset/document reference used for grouping;
it does not assert that the document establishes a course identity. Course code,
section, CRN and campus still require explicit known identifiers. Unmatched
document passages remain separate from work items rather than being guessed into
the same assessment. Existing independent-source permissions still apply.

The host merges affected courses into one search per term, including generic
subjects such as “your final exam schedule,” revisions and cancellations. Search
dates must accommodate notices sent before the term; the term window constrains
the assessment's applicability. The host inspects original messages and relevant
attachment rows or official linked schedules, verifies the actual sender address
against a trusted institutional source, and reconciles only applicable sections
and assessments. Search snippets and model answers are not evidence.

The result stays in the host conversation, with status, matched section, supported
date/start/end/location/timezone, sender, sent date, source link and attachment
page/row. Label it `host_inspected`. Missing fields remain unknown. An official
institutional timezone requires a cited basis. Do not import full messages,
rosters, unrelated rows, or these email findings as independent documents to
circumvent source permissions. A later reviewed evidence-transfer adapter could
support minimal imports; this implementation intentionally provides none.

## Calendar behavior

Bridge holds automatic proposals for finals with uncertain timing, returning the
existing owner/connection/course/work mapping marker and matching event IDs.
Ordinary deadline proposals continue normally. A known project-upload/paper
timestamp alone does not trigger an exam-slot lookup; an exam due timestamp does
not establish its start time. Undated source passages remain separate candidates
until the host establishes an assessment match.

| Host result | Behavior |
| --- | --- |
| Confirmed | Offer a cited change to the same assessment through the existing authorized calendar connector. Preserve its marker; inspect fresh complete mappings and versions before changes. |
| Candidate | Keep inferred grid timing tentative; do not overwrite an event. |
| Conflict | Show competing sources and leave the existing event unchanged. Newer timestamps alone do not supersede older notices. |
| Cancelled | Retain cancellation and original references. Removing an event needs separate authorization. |
| Unresolved | Distinguish completed search/no match, mailbox unavailable, inaccessible/incomplete sources, and missing identifiers. None establishes that no final exists. |

Explicit corrections supersede only the same applicable assessment; they cannot
resolve a different course or section. A room allocation for an exam cannot set a
project upload deadline. The supplied activity type, especially presentation,
survives the lookup. No inferred end time, background monitoring, sending or
calendar write is introduced. Calendar updates happen only after the host obtains
the user's authorization for concrete changes and reads back the provider result.

## Verification and limits

The bounded English detector inspects already retrieved work and source passages,
up to 100 candidates. It is not a complete final inventory or a general language
parser. Full course content remains subject to existing authorization, privacy,
retrieval and egress gates. No migration or mailbox configuration is needed.

Bridge-side tests cover discovery of undated presentations, unknown identifiers,
scope rejection, bounded requests, schema rejection of email imports, privacy
projection, selected-course audit integration, stable Calendar mapping/holds and
real loopback HTTP MCP delivery of the host instructions. Those checks do **not**
prove that a model follows the instructions or correctly reads a PDF.

Use [the synthetic host acceptance cases](registrar-host-acceptance.json) with an
authorized synthetic mailbox/attachment harness. Every case remains **NOT RUN in
a real host** until executed there. In particular, inspecting the original
multi-section PDF, matching exactly one CRN, inconsistent year headings,
correction versus unexplained conflict, unavailable versus searched/no-hit, and
Ethics versus Stem Cell are host acceptance gates, not backend test claims.

The original synthetic email and attached multi-section PDF are available under
`tests/fixtures/registrar/`, together with the inconsistent-year grid PDF. The
fixture builder is `scripts/build_registrar_fixtures.py` (requires reportlab;
available in the bundled document runtime). All three PDF pages were rendered
and visually checked locally. Fixture-byte and text checks prove the test inputs
contain the intended rows; they do not prove a host matches the correct section.

See [local verification](../evidence/sanitized-results/registrar-final-times-2026-11-03.md).
