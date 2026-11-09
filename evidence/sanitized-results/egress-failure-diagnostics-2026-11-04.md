# Canvas Bridge egress diagnostics validation

November 4, 2026. Local Windows tests used fictional coursework, a loopback MCP server, the installed Python MCP client, and disposable databases.

**Release evidence.** All 66 tests marked as MCP contracts passed on the final task-specific source. The complete suite on the preceding candidate reported 2,357 passed, 50 failed and 20 skipped. Every one of those 50 failures passed in follow-up testing. There was one complete suite run. Final-revision coverage comes from the affected cases and the full MCP contract selection.

## What the client and operator observed

A synthetic document read returned the fixture text. The test then exercised both `check_academic_assistance_permission` and `prepare_academic_assistance` under permissive mode. Independent fault injections produced different codes for an absent inspection receipt, changed response, unexpected return type, SDK failure and thrown exception. Additional injections exercised a verified domain failure wrapped by the SDK, a privacy-rejected extra block, hostile unknown codes, invalid input, a broken journal and failed emergency-path serialization. The test checks the entire public response, matching local events and captured default logs for its secret marker.

In one preparation attempt the public diagnostic and local lookup shared request ID `ddf6ff499f1942daba453bc4417dea22`. The last event reported `RESPONSE_INSPECTION_RECEIPT_MISSING`, stage `final_response_verification`, requested-content policy `requires_review`, sanitized-error release `allow`, and requested-content delivery `none`. The earlier event in this synthetic attempt recorded incomplete policy coverage. The lookup ran with the fixture's vault directory and the same interpreter used by the service.

```console
python -m canvas_bridge.failure_events ddf6ff499f1942daba453bc4417dea22
```

The fixture deliberately introduces faults. The original Paper 3 cause remains undetermined. These runs involved no live account, course paper, hosted client, production deployment, or live database change.

## Validation commands

Commands below use the repository virtual environment. Paths to intermediate outputs have been abbreviated as `<work>`.

| Command or check | Observed result |
|---|---|
| `python -m pytest -q tests/test_actionable_error_diagnostics.py tests/test_egress_contract.py tests/test_visual_error_projection.py tests/test_integrity_workflows.py` | Initial focused run passed 68 tests. |
| `python -m pytest -q tests/test_failure_boundaries.py tests/test_file_delivery.py tests/test_mcp_contract.py tests/test_independent_intelligence.py::test_local_state_storage_error_is_actionable_in_mcp` | Intermediate run passed 61 tests. An earlier invocation caught a missing import during collection, which was repaired. |
| `python -m pytest -q tests/test_failure_boundaries.py tests/test_egress_contract.py tests/test_file_delivery.py tests/test_actionable_error_diagnostics.py tests/test_integrity_workflows.py tests/test_mcp_contract.py tests/test_permission_consistency.py::test_structured_logs_have_correlation_without_identifiers_or_content tests/test_independent_intelligence.py::test_local_state_storage_error_is_actionable_in_mcp` | On the isolated patch candidate, 114 passed and one failed. A midstream policy denial had become a generic exception for in-process consumers. The fix retains the typed, sanitized denial and records partial delivery. |
| `python -m pytest -q tests/test_failure_boundaries.py tests/test_egress_contract.py::test_egress_is_reevaluated_before_each_download_chunk tests/test_file_delivery.py::test_interrupted_original_after_first_chunk_records_partial_only_locally --basetemp <work>/safety-fixtures` | All 11 final targeted checks passed. The sample lookup above used this run. |
| `ruff check .` and `ruff format --check .` | Passed on the isolated task tree, with 653 files checked for formatting. |
| `uv pip check --python .venv/Scripts/python.exe` and `pip-audit --local` | 85 installed packages compatible. Dependency audit reported zero known vulnerabilities and skipped the local Canvas Bridge package, which has no PyPI release. |
| `node --test tests/course_file_audit.test.mjs tests/course_file_audit_png.test.mjs tests/course_file_audit_checkpoint.test.mjs` | 78 passed, including legacy fallback handling. |
| `npm audit --prefix scripts/audit-png-runtime` | Zero reported vulnerabilities. |
| `canvas-bridge compliance-report --validate-only` | Registry valid, 30 controls. |
| `python -m bandit -r src -ll -ii` | Passed at the repository thresholds. A separate `bandit -q -r src -ll` run also included low-confidence results and reported one pre-existing SQL-construction finding in `library/models.py`. |
| `python -m canvas_bridge.benchmark_lab run --tier fast --output <work>/benchmark` | All configured gates passed. |
| `python -m canvas_bridge.scientific_benchmark --output <work>/scientific.json` | Retrieval accuracy 1.0. No interpretation rating was available. |

## Full regression and corrections

The full command was `python -u -m pytest -q --tb=short --junitxml <work>/patch-full.xml`. It collected 2,427 tests and ran for 2,819.25 seconds. Of the 20 skips, 13 require a Linux kernel, five require an explicitly trusted native converter and two require the optional OCR installation.

| Failures | Finding and resolution |
|---:|---|
| 40 | Two private-course test modules shared a settings stub lacking `egress_mode`. The fixture now explicitly exercises strict mode. Its source and recipient restrictions still apply. |
| 4 | Two permission tests expected an exact pre-diagnostic dictionary. Two source-privacy tests compared request IDs across independent calls. The revised checks require the additive diagnostic, validate unique correlation, and compare all other public facts across unknown, foreign and restricted selections. |
| 3 | Mid-request session revocation, an unavailable independent source and an unresolved file reference needed reviewed authorization codes at their owning boundaries. The corrected responses preserve actual denial and withhold the content. |
| 1 | The changed-catalog test now checks the sanitized MCP error, its protocol code and absence of injected text. |
| 2 | A PDF HTTP client timed out and an isolated renderer exceeded its worker deadline during the suite. The renderer case passed on rerun. The PDF test now waits up to 45 seconds for the actual bounded worker result. Its content, image and continuation assertions still run. Production worker deadlines retain their configured values. |

The JUnit failures supplied fifty exact node IDs to the following command.

```console
python -u -m pytest -q --tb=short @<work>/failed-nodeids.txt tests/test_failure_boundaries.py tests/test_egress_contract.py tests/test_integrity_workflows.py tests/test_file_delivery.py::test_interrupted_original_after_first_chunk_records_partial_only_locally --junitxml <work>/corrected.xml
```

That run produced 90 passes and one PDF client timeout. After the test-client adjustment and the final buffered HTTP verification, the following selections passed.

| Final command | Result |
|---|---|
| `python -u -m pytest -q --tb=short tests/test_pdf_processing_regressions.py::test_pdf_read_and_render_first_through_actual_mcp_worker tests/test_failure_boundaries.py` | 12 passed, including a changed post-SDK payload and a malformed JSON-RPC envelope. |
| `python -u -m pytest -q -m contract --tb=short --junitxml <work>/mcp-contract.xml` | 66 passed, 2,363 deselected, in 518.36 seconds. This selection exercised the installed MCP client and loopback transport. |
| `ruff check .` and `ruff format --check .` | Passed on the final task-specific source. |

## Source boundary

The checkout already had uncommitted changes and another task was editing overlapping files during implementation. The patch isolates the requested changes against the starting working tree and includes the companion fixture, assertion and access-code corrections needed for compatibility. Concurrent timeout and inventory extensions are separate. It passed forward application against the reconstructed input and reverse application against its output. The recovery guide is also in the repository's `docs/error-reporting.md`. No commit was created.

Earlier full-suite attempts were stopped on superseded candidates. After the midstream repair, a fresh run used an isolated source copy with the review patch, the existing development runtime and a newly initialized PostgreSQL cluster bound to loopback. The runner passed its database URL only to the test process. It excluded operator configuration and private working data from the source copy.


All three disposable PostgreSQL harnesses stopped. Automatic command review rejected recursive cleanup of their scratch data directories as blocked by policy. The stopped synthetic cluster files remain in the projectless workspace under `work`.
