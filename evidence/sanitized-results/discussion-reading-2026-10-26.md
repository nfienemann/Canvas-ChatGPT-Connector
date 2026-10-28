# Discussion reading — local validation, October 26, 2026

All records are fictional, including the Biomedical Ethics October 14 fixture.
HTTP uses `httpx.MockTransport` and `.invalid` origins. Local MCP tests use the
existing loopback authenticated test server. No live Canvas, production records,
service restart, deployment, credential change or external approval was performed.

The checkout already contained substantial uncommitted work. Existing changes
were preserved. Additional local-document, capability-profile, authorization and
migration changes appeared concurrently during validation. Results are therefore
checkpoints of a changing combined working tree, not a certified release snapshot.
No initial full-suite run was performed; one full run followed focused validation.

## Executed checks

- Final discussion, activity-planning and read-only catalog checks: **76 passed
  in 17.92 seconds**. Command: `.venv/Scripts/python.exe -m pytest
  tests/test_discussions.py tests/test_activity_planning.py
  tests/test_personal.py::test_T21_T37_read_only_catalog_omits_writes_instead_of_relabeling
  -q --tb=short`. This includes all **49 discussion cases**, all DP-01–DP-35
  acceptance mappings, real local MCP serialization and integrated audit/obligation
  responses. The catalog assertion now checks the three new read tools explicitly
  while retaining the existing read-only and excluded-write assertions.
- Full regression checkpoint: **1,396 passed, 27 skipped, 4 failed in 462.97
  seconds**. The failures were a source-hash freshness receipt, a brittle numeric
  substring assertion in the new discussion test, the old fixed tool-count
  assertion and an unrelated new migration's downgrade-message mismatch.
  The numeric assertion now checks actual sensitive fields instead of a substring
  that can occur in a random provenance hash. Both discussion/catalog test fixes
  pass in the final 76-test run. The freshness test also passes in the follow-up
  below. The migration test remains failing; no migration behavior was changed.
- Follow-up approval/egress contracts and the two affected governance checks:
  **18 passed, 1 failed in 36.05 seconds**. Command: `.venv/Scripts/python.exe -m
  pytest tests/test_approval_policy_contract.py tests/test_egress_contract.py
  tests/test_compliance.py::test_filtered_parameter_run_cannot_certify_full_control
  tests/test_compliance.py::test_passing_code_checks_cannot_clear_missing_approvals
  -q --tb=short`. Egress, catalog classification and both governance checks pass.
  The remaining failure concerns concurrently changed local saved-preference
  behavior, detailed below.
- Ruff lint/format: passed for the three new implementation modules and
  `tests/test_discussions.py`. Bandit: no findings in those three implementation
  modules. Repository-wide lint/format had passed earlier, before the concurrent
  changes; it is not claimed for the final combined tree.
- `git -c core.safecrlf=false diff --check`: passed.

## Unresolved combined-tree regressions

1. `tests/test_retention.py::test_existing_plaintext_migration_encrypts_in_place`
   expects a downgrade error containing `plaintext`. The concurrently introduced
   `d914cb092014_independent_resources.py` instead rejects downgrade with
   `Recovery requires a reviewed encrypted backup; automatic destructive downgrade
   is unsupported.` The last targeted execution confirms the mismatch. Both paths
   reject downgrade; resolving the new migration/test contract is outside this
   discussion feature.
2. `tests/test_approval_policy_contract.py::test_cached_live_tools_and_alternate_readers_deny_without_network`
   expects `get_saved_study_state` to return `permission_denied` without institutional
   approval. Concurrent changes made its default local-preferences response return
   `ok`. Discussion-specific missing/pending/expired/revoked approval tests pass;
   this separate local-preferences authorization contract still needs reconciliation.

During concurrency, two discussion MCP tests also encountered a setup error from
the new `render_local_document_page` lacking a return annotation. That annotation
was supplied by the concurrent edit before our attempted patch; no patch from this
task changed that function. Both MCP tests pass in the final run above.

The full suite was not repeated against a still-changing checkout. A stable-tree
full regression run remains required for a repository-wide green result. The 27
skips cover environment-dependent Linux-kernel, disposable PostgreSQL, native
converter and OCR checks, not successful validation of those environments.

## Acceptance mapping

All discussion cases reside in `tests/test_discussions.py`; existing planning,
privacy, authorization, egress and MCP contracts supply additional regression
coverage. Parameterized cases contain independently asserted expected outcomes.

| Acceptance IDs | Fixture/test coverage |
|---|---|
| DP-01–04 | `test_DP01_04_verified_active_counts`: empty complete view, one/multiple posts and reply |
| DP-05 | `test_DP05_nested_relationships` |
| DP-06, DP-13 | `test_DP06_13_deduplicate_new_entries` |
| DP-07–08 | `test_DP07_08_peer_and_deleted_not_counted` |
| DP-09 | `test_DP09_more_than_ten_replies` |
| DP-10–11 | `test_DP10_11_pagination_exhaustion`, success and interrupted second page |
| DP-12 | `test_DP12_503_bounded_fallback`, exact bounded attempt count |
| DP-14 | `test_DP14_conflicting_versions_not_arbitrarily_selected`; fresher-version and metadata-count regressions |
| DP-15–16 | `test_DP15_16_limits_and_unsupported_never_absent`, rate/page/entry/timeout/malformed cases |
| DP-17 | `test_DP17_unselected_course_no_requests`, cross-owner rejection |
| DP-18–20 | Restricted group/parent/post-before-view/anonymous fixtures and missing-author case |
| DP-21, DP-23, DP-25, DP-27, DP-35 | Privacy, injection, log redaction, HTML and GET-only fixture |
| DP-22 | `test_DP22_peer_mode_disabled_before_network` |
| DP-24 | Malicious pagination/attachment origin rejection |
| DP-26 | Connection revocation, signed external approval revocation and absent/pending/expired/revoked approval fixtures |
| DP-28–31 | Distinct checkpoint dates, original creation time, unknown dates, separate threaded-reply counts and explicit no-grade assessment |
| DP-32–33 | Canonical assignment/topic deduplication, excluded group child, obligations/audit/plan uncertainty |
| DP-34 | Fresh second read sees a new entry; no cross-owner cache |

Additional checks cover serialized MCP self-role/coverage fields, linked assignment
date requests, date override minimization, authenticated source provenance and
the existing unrelated workflows.

## Remaining boundaries

Group membership verification and group thread routes are not implemented.
Peer-content reading is blocked independently of self participation. Optional
discussion search indexing is deferred. Required-reply field availability,
anonymous API variants, effective dates and UI agreement need a separately
authorized target-institution acceptance run. No posting outcome is hardcoded.
Some Canvas deployments may require pagination variants rejected by the existing
strict cursor validator; rejection preserves uncertainty rather than bypassing it.

See [the feature and permission matrix](../../docs/discussion-reading.md) and
[the existing release gates](../release-gates.md). Synthetic verification cannot
establish institutional/vendor approval, universal anonymity, hosted readiness,
or deployed ChatGPT behavior.
