# AI data egress and content governance — local validation

Date: 2026-10-25. Scope: local checkout, synthetic coursework, fictional signed
approvals, isolated `.invalid` HTTP fixtures, and local authenticated MCP/HTTP.
No real course content, approval correspondence, tokens, workspace identifiers,
or credentials are included in this record.

## Implemented boundary

- Central `DataEgressPolicyEngine`, seven classifications and five decisions.
- Independent provider/institution/user/sharing authorization remains required.
- Signed sharing-record recipient registry, exact verified issuer/client and
  environment/workspace claims, plan-specific processing/retention/amount limits.
- Owned and version-bound source context, explicit content-owner and modality
  review, and file byte-digest binding. Fresh output cannot borrow a different
  cached version's review. Signed restrictions survive deadline minimization.
- Structured/text MCP output, document readers/search, images and private reader
  metadata, original attachments, HTTP downloads, settings exports, static
  resource/catalog metadata, and reconstructed application/SDK/protocol errors.
- Live bearer links fail closed, including old synthetic capabilities after a
  profile transition. Reviewed inline attachments and authenticated downloads
  remain available to approved recipients. HTTP egress is checked per chunk.
- No installed external AI/document processor; attempted external processing
  explicitly denies. Authorized local analysis and synthetic academic tools work.
- Egress audit records contain exactly five non-sensitive policy fields.

## Synthetic acceptance cases

| Case | Verified outcome |
|---|---|
| Public course document | Source/version and destination review allow release |
| Authenticated student's grade | Exact environment allows minimized own-grade fields |
| Another student's grade | Denied; removing identifiers does not grant rights |
| Copyrighted lecture slide | Requires content-owner and visual review |
| Unreleased exam | Denied, including derived output |
| Private instructor feedback | Requires source and owner review |
| Confidential research | Denied across alternate channels |
| Unknown file | Requires authorized classification; no text, image or original escape |
| Safe derived deadline | Allowed minimized, with explicit source restrictions retained |
| Disguised original URL | Denied in plain, encoded, escaped and signed-query forms |

Additional checks cover unverified/mismatched destination claims; retention,
training, downstream processing and amount limits; expiry/revocation; exact course
scope; source/version/hash/modality changes; source instructions claiming approval;
policy changes between read and release; cached HTTP capabilities; revocation
between download chunks; SDK argument-validation and malformed protocol errors;
and all registered tool names having an egress purpose without policy-edit arguments.

## Checks

- Prior prompt's full baseline (1,024 passed / 27 skipped) was reused rather than
  redundantly rerun before implementation.
- Initial full regression: 1,064 passed, 27 skipped, 7 failures. The failures
  identified missing ephemeral syllabus/rubric/grading source provenance and
  over-redacted fixed reader diagnostics. Those were repaired without weakening
  unknown live-content handling.
- Final focused egress suite: 56 passed in 24.45 seconds.
- All seven affected academic/reader regression tests: 7 passed in 13.45 seconds.
- Full regression after those compatibility repairs: 1,078 passed, 27 skipped in
  326.37 seconds. The final source-version regressions and download-card guard
  were added during that run; a final full run follows below.
- `ruff check .`: passed.
- Formatting check on 23 Python files touched by this specification: passed.
- `git diff --check`: passed.
- `npm run build` in `ui/page-reader`: passed; download card bundle rebuilt.

Final full suite against the completed implementation: **1,080 passed, 27 skipped
in 330.64 seconds** (`.venv/Scripts/python.exe -m pytest -q`). This run includes
the final source-version restrictions and rebuilt download-card guard.

The expected platform/runtime skips are Linux kernel tests on Windows (13),
unconfigured disposable PostgreSQL (7), optional native converter runtime (5),
and optional OCR runtime (2). These are not claimed as successful checks.
Unrelated pre-existing edits remain in the checkout. No repository-wide
reformatting or cleanup was performed.

## Evidence limits and release status

These are local synthetic implementation checks, not installed-connector or
ordinary ChatGPT client acceptance. No real Instructure/institution/content-owner
approval, recipient contract or identity-provider claim mapping was obtained or
inferred. Recipient terms are enforced from reviewed configuration; the service
does not independently observe a third party's actual retention/training behavior.

Live aggregate exports and unbound composite outputs remain restricted until an
appropriate source-aware policy exists. Large original files cannot use an
unauthenticated browser fallback. No service restart, migration, deployment,
public publication, credential change, course-selection change or private
operator-configuration edit was performed. Historical functional proofs do not
satisfy the new authorization or egress prerequisites.
