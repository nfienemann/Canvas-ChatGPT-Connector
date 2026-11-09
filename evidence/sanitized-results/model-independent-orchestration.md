# Model-independent orchestration acceptance

## Result

Two signed client configurations exercised the existing Bridge HTTP MCP endpoint on synthetic data. The tested scope includes individually reviewed temporary documents, deterministic academic workflows, owner-scoped local preferences and calendar proposals. Live ChatGPT and second-host acceptance is blocked. The operator confirmed that the two hosts were unavailable on an isolated synthetic build.

| Case | Executed result | Boundary |
| --- | --- | --- |
| MI-T01 | Pass. Two verified issuer/client/environment/workspace tuples reached the release engine with distinct recipients. Wrong client, issuer, environment and workspace controls passed. Both clients sent the same display name. | The preflight populated the verifier's test-issuer public key cache. The measured requests used the hosted profile and real signature checks. |
| MI-T02 | Pass. The external client was denied for a legacy A-only import, released after an owner review, and denied again after revocation. Changes to policy terms or source bytes required another review. Purpose, channel and byte-limit controls withheld output. | The additional grant covers text, structured output and metadata on an explicitly reviewed source. |
| MI-T03 | Pass at protocol level. Both sessions negotiated MCP, discovered the selected schemas and consumed text and structured results. Two reads at returned character boundaries reconstructed the permitted excerpt. A missing source produced partial coverage. | Both consumers used MCP Python SDK 1.30.0. |
| MI-T04 | Pass at protocol level. Both clients returned matching versioned claims, deadlines, conflicting finance word counts and grade arithmetic. The Operations plan allocated 1,010 minutes, with 70 blocked by capacity and 300 by dependencies. Both generated the same three parent proposals. | The 86% grade used a separate synthetic points fixture. The VAI sources and Operations base request came from the supplied archive. Host wording is unreviewed. |
| MI-T05 | Pass for local preferences. A fresh session read the same default key, version and value. A second subject had an empty namespace. A changed source needed fresh permission and its new hash. | The tested durable category was local preferences. Institutional plan and progress readback across the two hosts remains unreviewed. |
| MI-T06 | Pass. A stale write returned `source_changed`. Concurrent updates at the same version produced one commit and one conflict. A fresh read returned the winning value. Matching calendar events yielded zero duplicate proposals. | Recorded progress and task completion semantics also have separate upstream Operations regression coverage. Calendar writes were outside scope. |
| MI-T07 | Pass at protocol level. The reference configuration received a native PNG with unknown model visibility. The restricted client received text and zero image blocks. Missing calendar context returned `INDEPENDENT_CALENDAR_MISSING`. | Actual model observation and either host's own calendar connector remain unreviewed. |
| MI-T08 | Blocked. Zero host final answers collected. | The VAI rubric requires every critical and major check to pass. Both host scores remain unreviewed. |

## Build and replay

The base commit was `5bd086356e730b01b5a9f1be9de106446ef049c6` plus the working tree. The product source manifest SHA-256 was `d48d1ee02855fad90a0c866f1f4881d2d5b0ce4e3652bd95203a426782db59be`. The academic comparison used October 29, 2026 at noon in America/New_York. Both clients used the same owner, source versions, clock, request and constraints. Runtime was Windows 11 with Python 3.14.5. Tests used synthetic originals, local extraction and a loopback service. The PNG check exercised the Windows isolated renderer.

Set `BRIDGE_TEST_MI_SUITE` to the supplied ZIP and run `python -m pytest -q tests/test_model_independent.py` in the project environment. Set `BRIDGE_TEST_MI_OUTPUT` to a private output directory to retain the synthetic receipts. The input archive SHA-256 was `591d1944d02a8070e1d6c4ad256b6989b595a6d843b1afda14e8dc0144e5c8cf`. Its validator checked 17 fixture files and 39 literal quotations. All 32 listed member checksums matched.

The [receipt archive](model-independent-orchestration-receipts.zip) contains the case dispositions, per-session requests and results, observed release decisions, reviewed policy digests, synthetic source hashes, semantic comparison and full product file manifest. Each receipt has a checksum. A live-host run still requires an isolated instance of this build, a reviewed connection from each host, and actual host answers evaluated against the supplied VAI rubric.

## Verification record

The nine-module regression run passed 171 tests with zero skips, including the upstream Operations and VAI replays against the same product manifest. Four serializer warnings from the test fixture were corrected by validating its policy variants. The final six-test orchestration replay passed without warnings and recorded 57 MCP tool calls. Repository Ruff lint, formatting, diff checks, receipt checksums and the post-run product manifest check passed. The full repository suite and deployment were outside this run.

Receipt archive SHA-256: `9f4296aa50231c8b08da5b7888b074e8fdc9c97825e269b200e7f99f9261f414`.
