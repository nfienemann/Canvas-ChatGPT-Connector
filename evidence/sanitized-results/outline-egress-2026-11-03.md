# Course outline egress investigation — November 3, 2026

## Outcome

The installed personal connector reproduces `EGRESS_CLASSIFICATION_UNKNOWN`.
This is a missing source-review and unsupported private-operation authorization
case, not evidence that Canvas access failed. No source classification, signed
approval, selection, credential or release policy was relaxed. Successful live
outline retrieval remains blocked pending authorized review and an applicable
recipient/operation policy. Diagnostic defects were repaired and verified live.

## Historical evidence boundary

The supplied failed request ID was not found in repository-local logs or the
installed personal service logs. The old egress decision event has no request ID;
the error path does not persist a denied payload or per-source decision record.
Consequently the exact historical source set cannot be reconstructed honestly.
No particular title, Canvas metadata field or single file can be named as the
historical culprit from the retained evidence.

The current owned-course database inspection found 39 file records, all lacking
any signed source review (not merely a review for an older version). Some have
no cached content version; a later content review would also need current source
identity. Exact current opaque references and available versions were retained
only in the ignored local operator packet `.local/outline-governance-sources.json`.
That packet is a current inventory, not a historical request transcript or approval.

## Execution path and decisive rule

1. `app.py`'s guarded MCP registration verifies the authenticated identity, binds
   recipient claims and request ID, takes the connection read guard, runs
   `authorize_tool` and the integrity preflight.
2. `retrieval.outline` refreshes course access and requires selected ownership.
   Its bounded client reads pages, files, modules and module items, with bounded
   file metadata fallback. It does not download document bodies for this listing.
3. `canvas.py` applies allowlisted endpoint/resource authorization, upstream
   privacy normalization, pagination and request budgets. `retrieval.py` retains
   visible metadata, creates scoped Material references and records coverage.
4. The wrapper calls `validate_request_authorization` after retrieval.
5. `egress_sources.resolve_sources` walks arguments and returned metadata refs.
   Owned Material records are authorized again as files/pages. Classification
   starts at `UNKNOWN_OR_UNCLASSIFIED` and changes only for an exact signed
   `source_id`/`version` review (or isolated synthetic fixtures). The version comes
   from `governance_source_version`, then cached `version`, then `version_hash`.
   There are no matching reviews for the affected course's current file records.
   Neither filenames nor a source's own asserted classification grants permission.
6. `prepare_transfer` applies final privacy scanning before minimization. Outline
   has purpose `metadata`, channel `structured`, and no dedicated minimized
   private projection. Listing metadata is not automatically public content.
7. `DataEgressPolicyEngine.evaluate` checks ownership/authorization and privacy,
   rejects hard-restricted classes, then rejects **any** unknown class with
   `REQUIRES_AUTHORIZED_REVIEW / EGRESS_CLASSIFICATION_UNKNOWN`. Recipient-policy
   evaluation comes later and is therefore masked by this first failure.
8. The wrapper reconstructs a safe DomainError response. SDK response gating and
   privacy projection run again. No denied academic payload is released.
   `meta.egress: ALLOW_REDACTED` concerns this safe error, not the course content.

## Why list_courses succeeds and outline does not

The current signed records validate successfully. Broad sharing category checks
for courses, pages, files and modules return `APPROVAL_AUTHORIZED`. These checks
are necessary but insufficient for AI egress. The personal service is read-only
and loopback-bound. Its signed sharing record has no general `egress` governance,
uses private scope `reviewed_private_text`, enables material inventory, and has
four private text reviews elsewhere; none covers this course's current files.

`list_courses` classifies owned course metadata as first-party, projects a fixed
minimal vocabulary and is explicitly supported by the private grant. Outline is
not in that grant's operation allowlist. `allow_course_material_inventory` permits
`list_course_files`, not outline module/page metadata. Even assigning an approved
classification would not make the private outline operation authorized. An empty
outline also lacks a known course-classification rule for this tool.

## Required review and remaining work

The configured trusted sharing administrator must verify evidence from the
instructor/content rights holder and an authorized institutional privacy reviewer.
The signing administrator must be trusted for this institution and sharing
authority. The records do not establish a named human authorized to approve this
new outline scope; this investigation does not designate or impersonate one.

Evidence must cover the exact sources and current versions; permitted metadata
purpose and structured channel; rights to disclose titles/module organization and
any included excerpts; independent privacy review; assessment/confidentiality
restrictions; and the actual recipient client/environment and processing terms.
File content reviews additionally require matching original-byte identity and,
for private extracted text, sanitized extraction identity. Approving a text reader
does not approve every outline source or modality.

The operator must then use an applicable signed recipient policy. A new narrow
private outline exception would require an explicitly reviewed product change,
fixed minimization, provenance and restriction inheritance, plus a distinct signed
grant; the current grant cannot be silently widened. Full governed outlines also
need complete source/version coverage, including modules and empty-output cases.
Classification alone is not a promise of successful retry. Reconnecting cannot
supply these approvals.

## Diagnostic changes

- Preserve `content_decision` through repeated safe-error reconstruction and the
  final privacy field projection; allow only the two fixed denial values.
- Reconstruct `processing_stage: source_classification` from the fixed error code.
- Emit warning-level `data_egress_blocked` correlation events with only generated
  request ID, fixed reason code and decision, without source IDs or content.
- Add MCP regressions for approved, unknown and restricted outline sources;
  private grant scope isolation; repeat-safe projection; and log correlation.

## Installed connector verification

The application process was restarted using the verified application-only stop
helper and existing private launcher. PostgreSQL/tunnel were not stopped and no
approvals were edited. The installed tool's changed response confirms new code
was loaded; launcher success alone was not used as proof.

- Before restart: outline reproduced the supplied classification failure.
- After restart: outline remains `permission_denied`, now including
  `processing_stage: source_classification` and
  `content_decision: REQUIRES_AUTHORIZED_REVIEW`, with empty sources/evidence.
  Its request ID was found in the warning event in the installed service log
  (the console formatter wraps the identifier across lines).
- After restart: `list_courses` returns `ok`, live freshness and complete coverage.
- No successful live outline retrieval or newly authorized source review is claimed.

## Local verification

`python -m pytest tests/test_actionable_error_diagnostics.py
tests/test_private_course_listing.py tests/test_egress_contract.py
tests/test_egress_policy.py -q --tb=short`: **102 passed in 198.96 seconds**.
These include real loopback HTTP MCP tests with synthetic records, not live
institutional approval. Ruff check and format checks passed for all five changed
Python files. `git diff --check` passed (existing line-ending notices only).
No fresh full-suite run is claimed. Existing unrelated working-tree changes were
preserved. The installed-connector observations above remain separate evidence.
