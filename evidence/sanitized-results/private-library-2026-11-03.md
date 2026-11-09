# Private library — current-worktree verification, November 3, 2026

Historical checkpoint: subsequent local implementation and verification are in
[the local completion record](private-library-local-completion-2026-11-03.md).

The local durable-library implementation remains disabled by default. No private
service was restarted, database migrated, file imported, account changed or code
published as part of this continuation. Unrelated work was preserved.

The library implementation itself matched the earlier tested source hashes.
Six shared integration/configuration files had changed since October 29:
`.env.example`, `cli.py`, `config.py`, `egress_sources.py`, `service.py` and
`storage.py`. Those changes were retained and the library was retested against
the current checkout. [Current source hashes](private-library/source-hashes-2026-11-03.json)
cover 42 implementation, integration and test files; a final hash comparison found
no intervening changes. Historical results remain in the
[October verification record](private-library-2026-10-29.md).

## Executed checks

On Windows with Python 3.14 and synthetic disposable fixtures:

```text
.venv\Scripts\python -m pytest -q tests/test_private_library.py tests/test_private_library_boundaries.py tests/test_additional_regressions.py::test_snapshot_scope_migration_preserves_inventory_and_requires_legacy_refresh tests/test_approval_policy_contract.py::test_all_mcp_surfaces_classified_and_no_approval_mutation tests/test_retention.py::test_existing_plaintext_migration_encrypts_in_place --disable-warnings --maxfail=3
```

**46 passed in 118.42 seconds**: 43 library cases plus the three corrected
compatibility contracts. This includes normal authenticated HTTP format/range
flows, actual MCP serialization, source/grant fences, search revocation during
representation access, quota admission, immutable versions, current receipts,
terminal manifest scrubbing, deletion and backup/restore boundaries. One case
uses the actual isolated Windows scanner; most fault tests use deterministic
scanner/parser substitutions as documented in the earlier report.

Additional current checks:

- `ruff check src tests scripts migrations --output-format concise`: passed.
- `ruff format --check src tests scripts migrations`: 403 files formatted.
- `python -m canvas_bridge.cli compliance-report --validate-only`: registry valid,
  30 controls, no authorization granted.
- Scoped `git diff --check`: passed; line-ending normalization warnings only.

Other pytest processes were already running in the shared workspace, so this
continuation did not launch a duplicate full-suite run or claim results from those
processes. The earlier full run's 2,086 passes, 30 skips and three subsequently
corrected assertion failures remain historical evidence, not a fresh full-suite
result for November 3.

## Delivery boundary

See the [implementation guide](../../docs/private-media-library.md),
[requirement ledger](private-library/requirements.csv) and
[36-case acceptance ledger](private-library/acceptance.csv).

The browser-based local L1 path is implemented and tested. The entire specification
set is **not operationally accepted**: hosted private-bucket implementation,
PostgreSQL multiworker/load/recovery acceptance, full accessibility/adversarial
matrices and real-host acceptance remain open. L2 host file intake is absent;
L3 audio/video remains disabled. Physical backup deletion is an operator lifecycle
requirement, separate from the implemented restore-expiry and deletion fences.
No local result is substituted for those missing implementation or acceptance steps.
