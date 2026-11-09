# API usage governor — local synthetic validation

Date: October 29, 2026 (America/New_York).

Scope: the six supplied CB-BUDGET specifications. All provider responses and
contracts used here are fictional. No private database migration, service restart,
Canvas access, commercial activation, signing-key provisioning, or external message
was performed.

The governor-only acceptance run passed **67 tests**, with **one PostgreSQL skip**.
Its recorder reported unchanged source during that run. The discussion/retention
regressions passed **76 tests** after adding bounded cooldown waiting and the new
retention category.

The final combined regression command passed **191 tests**, with **one PostgreSQL
skip**, in 169.03 seconds:

```text
.venv/Scripts/python.exe -m pytest -q tests/test_usage_governor.py tests/test_usage_integration.py tests/test_discussions.py tests/test_retention.py tests/test_account_deletion.py tests/test_request_limits.py tests/test_approval_policy_contract.py tests/test_egress_contract.py --tb=line -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/compliance-input/api-usage-regression-final.json
```

Its recorder detected concurrent source changes, so it is an executed regression
result, **not a current whole-repository source attestation**. The generated local
compliance report correctly remains `IMPLEMENTED_UNVERIFIED`, with external approval
`REQUIRES_EXTERNAL_APPROVAL`; the API call-path audit has no findings. No release gate
was promoted. Receipt and generated reports remain under ignored `.local/` paths.

The broad repository run (`pytest -q --tb=line` with the same compliance recorder)
finished with **2,033 passed, 8 failed, 30 skipped** in 1,286.85 seconds. Its source
changed during execution. The failures were four discussion fallback cases, the
document-egress client timeout, an outdated HTTP 429 reason-code expectation, and
two tests affected by loading different migration/model versions during the run
(a spawned-process race and the frozen-schema comparison). The latter two pass
in the subsequent combined run with a consistent model/schema. HTTP 429 now has
the specified `UPSTREAM_THROTTLED` classification while permissions remain unknown.
The earlier interrupted exploratory full run is not passing evidence.

The final rerun of **every failed case**, plus the entire permission-consistency
module, passed **39 tests in 42.68 seconds**. No known failure from the broad run
remains unretested. This does not turn the earlier changed-source full run into a
passing current full-suite receipt. The final retest receipt is
`.local/compliance-input/api-usage-failed-cases-retest.json`.

The document-egress contract retains all authorization/reclassification assertions.
Its test-client timeout is now 30 seconds instead of five, allowing the multi-step
signed-authorization workflow to finish; the isolated retest passed in 28.95 seconds.
Production timeouts were not enlarged. The original five-second harness failures
are not counted as passing evidence.

The 100,000-request allocation simulation made zero network attempts and booked
100,000 fictional units against the illustrative 285,000 usable units, leaving
185,000. It is allocation planning evidence, not a database concurrency test.

The durable SQLite race tests admitted exactly 25 of 100 contenders under a
25-unit allowance. A separate two-process race admitted exactly one caller for the
last unit. A measured repeat of the 100-caller/20-thread SQLite race reported p50
13.5 ms and p95 2,376.9 ms for the contender's complete reserve/send-marker/settle
path (or denial), under concurrent local test load. This is a local contention
baseline, not hosted throughput or an isolated admission-latency SLO. The report
also exposes bounded per-process admission samples, or N/A when unavailable.

Recovery retains uncertain sent charges; verified vendor evidence is
required to refund them. Unknown terms, ledger failures, unknown endpoints and
revoked authorization fail closed. PostgreSQL acceptance requires a separately
configured disposable TEST_DATABASE_URL and remains unverified in this environment.

Additional deterministic cases cover cycle rollover before send, quarantine across
cycle rollover, a newly raised stop between reservation and send, revocation during
cooldown, late vendor reports after attempt-detail expiry, and backup restore holds.
The standalone frozen migration's table/column shapes match the runtime model.
Alembic reports a single new head, `f17a6b204c31`; this did not apply any migration.

Ruff lint, scoped formatting, diff whitespace and governance registry validation
passed. Bandit found zero issues and zero scanner errors in the new governor
package. Runtime approval remains independent of these checks. Source-bound
compliance evidence must retain skipped, changed-source
or unexecuted acceptance as unverified. Other concurrent work in this shared checkout
is preserved; no unrelated changes were reverted.
