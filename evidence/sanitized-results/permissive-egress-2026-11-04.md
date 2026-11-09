# Temporary permissive private egress — November 4, 2026

Added explicit `BRIDGE_EGRESS_MODE=permissive` for synthetic and loopback,
owner-only, read-only personal operation. Strict remains the default and hosted
configuration rejects permissive mode. Egress review requirements and
purpose-specific projection are skipped; ownership, authorization, privacy
filtering, known restricted-content checks and academic-integrity checks remain.
Unknown content retains its unknown classification. This is not public-release
or recipient/content approval evidence.

Validation performed:

- `pytest tests/test_permissive_egress.py tests/test_egress_policy.py tests/test_egress_contract.py -q`:
  66 passed (before the additional MCP permissive-outline case was added).
- `pytest tests/test_egress_contract.py::test_permissive_outline_releases_unreviewed_content -q`:
  1 passed.
- Ruff lint and formatting checks passed on the five changed Python files.
- Scoped `git diff --check` passed, with existing Windows line-ending notices.
- Enabled the setting in private operator configuration, restarted only the
  application service, and verified the expected OAuth resource identity and
  `EGRESS_PERMISSIVE_MODE` in the restarted service's runtime decision log.
  Existing service logs were preserved locally. No credentials or academic
  records are included in this evidence.

The reported study-assistance request reached `prepare_academic_assistance`.
Its generic redacted response did not establish an egress-policy denial; the
underlying failure was not identified or reproduced. The exact real-client
study-note workflow remains unverified. No full suite was run for this change.

Rollback: set the private `BRIDGE_EGRESS_MODE` to `strict` and restart the service.
