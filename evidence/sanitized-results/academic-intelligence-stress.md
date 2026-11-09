# Academic intelligence stress replay

The pinned revision reproduced 37 failures in 140 synthetic cases. The local checkout at base `5bd086356e730b01b5a9f1be9de106446ef049c6` started with 42 failures. The repaired checkout passed 140 of 140. The [case ledger](academic-intelligence-stress.json) records case IDs, expected and observed values, the build references, and source hashes for the uncommitted repair.

| Spec | Verified outcome |
| --- | --- |
| AI-01 | All 48 word-limit fields matched the source. A 1,900-word report passed the current 1,800–2,200 range. Both endpoints passed and the adjacent outside counts failed. The archived rubric was historical in either file order. Separate discussion bodies require separate counts. |
| AI-02 | The strategy notice produced two mandatory checklist entries, a PDF memo and an XLSX workbook. A PDF-or-DOCX instruction produced one entry with two allowed formats. The checklist describes what the student must submit. It does not verify a receipt. |
| AI-03 | Each of the six amended assignments had a cited comparison to its own structured deadline. Dates lacking a year or timezone retain their unresolved precision. The exact-time, differing-time, ambiguous-locale and DST-fold controls passed. |
| AI-04 | All eleven natural absences preserved the available brief in the simulated mixed-selection cases. Stale selections blocked outdated evidence. Authorized transient reads preserved retry guidance. |
| AI-05 | Eleven in-window reminders, zero creates on marker replay, zero new reminders when all work was marked done, and zero suggested minutes for the completed midterm. Reopening just one independently completed item restored its eligibility. |
| QA-01 | The preserved ZIP has 285 physical entries, 265 verified logical payloads, 11 missing payloads and 16 verified mirrors. Nine supplied scoring scenarios name missing evidence. Only verified student material enters the corpus integration test. |

The five additional baseline failures came from the current registrar filter holding a written final plan (two calendar controls), and three conditional AI permissions that this checkout parsed as unconditional. The registrar now distinguishes a named written deliverable from a final exam or presentation. The conditional-permission repair and its regression tests came from the pinned project revision.

## Reproduction

Extract the supplied stress-test bundle into a private directory. From the checkout, use the locked project Python. Replace the two directory placeholders with the extracted bundle and an empty results directory outside it.

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe <bundle>/replay.py --repo . --archive benchmarks/academic/damaged-business-coursework/business-coursework.zip --out <results> --ci
.\.venv\Scripts\python.exe -m pytest -q tests/test_damaged_academic_corpus.py tests/test_integrity_conditions.py
```

The pinned comparison used a separate checkout of `29652557b5701df6eb9147ac232fd3c656449104`. The damaged fixture SHA-256 is `6d3322be08e6d449bb32a5f64b0928e6a350eb69aff6866fcab84a2c473cdf51`. The six-course replay uses October 29, 2026 at noon in America/New_York. Observed course grades and hypothetical grades agreed with all six independent calculations.

The 140 cases exercise deterministic analysis, synthetic policy parsing and simulated storage. The local HTTP MCP tests exercise a synthetic owner, the real importer, storage and egress. The default test runs the production parser in-process. Set `BRIDGE_TEST_CORPUS_SANDBOX=1` for the isolated worker variant. The bundle's nine historical deployed controls concern an empty inventory. Acceptance on an installed client with imported coursework requires a separate isolated deployment.

## Adapter and regression checks

The local HTTP adapter passed all nine empty-profile controls. With an injected storage error after authorization, it returned `retry_later` for a sole selection. With one surviving selection, it returned `partial_data`, cited that source version, and included the failed slot and retry guidance. This test caught a response-formatter defect that the 140-case replay could not observe.

The four-module academic, dates, registrar and independent-workflow run returned 113 passes and four timeouts. A separate rerun reproduced the DOCX and PPTX AppContainer deadlines and the two local HTTP timeouts. The opt-in corpus test also timed out in isolated file extraction. Its in-process parser variant passed the importer, datastore, version checks, HTTP MCP transport and egress assertions. The full repository suite and installed-client acceptance remain unverified.
