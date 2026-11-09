# Stage 6 academic operations analytics verification

On November 5, 2026, the development checkout reproduced the supplied numerical expectations in all 13 synthetic scenarios. All 24 additional acceptance-case constructions passed. The report was also requested over authenticated local MCP HTTP. The remaining client check is direct invocation from an installed ChatGPT connector pointed at this build.

[Implementation diff](stage6-academic-analytics.patch) · [Source and history matrix](../../docs/academic-analytics.md) · [Synthetic requests, reports and verification records](stage6-academic-analytics-receipts.zip)

## Implementation and verification by spec

| Order | Spec | What was implemented and checked |
| --- | --- | --- |
| 1 | ANL-01 | Scoped, versioned observations distinguish effective time, observation time and source basis. Native inventory uses the retained workload population. Scope, capture-only history, parent identity, bounded coverage and primary-save survival have regression coverage. |
| 2 | ANL-02 | Deadline and personal-progress rates expose known and unknown counts. Accepted and proposed plan snapshots retain separate busy coverage. Tests include offline work, date-only boundaries, daylight saving time and overlapping intervals. |
| 3 | ANL-03 | Forecast/actual matching enforces the revision, work scope and forecast timing. Interval coverage, point error and budget error have separate samples. Requests, transport attempts, distinct confirmed effects, manual minutes and machine time have separate measurements. Tests cover zero, replay and mismatched work. |
| 4 | ANL-04 | Authenticated review, explicit measurement saves, immutable saved reports and later restatements run through existing MCP and local-state infrastructure. Tested the report after privacy projection, including denial from an underlying restricted parent. Compared a repeated two-period request and a single-period request. The independent dataset route preserves declared provenance. |
| 5 | ANL-QA-01 | Executed the 13-fixture arithmetic comparison and all 24 case constructions. Reviewed baseline, sparse and corrected HTTP responses against all eight host criteria. Direct installed-client acceptance is open. |

The receipt archive lists each case, requirement and associated evidence. The fixture replay seeds typed observations at the production storage boundary for historical facts that the synthetic provider cannot emit on demand. Separate integration tests use the native normalizer and inventory, saved plans, owned measurements, workflow diagnostics, restricted source checks and actual HTTP serialization. The scenario expected values came from the supplied archive.

### Executed checks on the final source

| Run | Result |
| --- | --- |
| Stage 6 and adjacent regression modules | 518 passed, zero skipped, in 5 minutes 14 seconds |
| Affected modules with recorded HTTP outputs and case receipts | 156 passed, zero skipped, including all 42 Stage 6 tests |
| Earlier Operations, verifiable intelligence and model-independent compatibility suites with their supplied archives | 12 passed, zero skipped |
| Static and artifact checks | Ruff passed on all Python files in the implementation diff. All 16 new Python files passed formatting. The diff passed forward and reverse application checks. |

The 156-check run overlaps the 518-check run. The full repository suite was outside this focused verification. The final product manifest covered 270 files, with SHA-256 `3de45abbd39af91d53bfa133cb46d6b02b985caee6faa24c9442647953e759f7`. The manifest was rechecked when packaging the evidence.

## Actual host review

These are the Codex host's answers after reading the three captured local MCP responses from this build. Each answer corresponds to the named HTTP receipt in the ZIP. The installed connector available in this session did not advertise the new analytics tools.

### Two-week review

> Across the three synthetic courses, the week of October 19 had one on-time, one late and one missed deadline among three known outcomes. The week of October 26 had two on time, one late and zero missed among three known outcomes. Each week had a fourth due item with unknown timeliness. The missed rate fell by 33⅓ percentage points among known outcomes.
>
> At the November 2 cutoff, you had marked two of three known declarations done for the first due cohort and three of three for the second. One declaration was unknown each week. Those are your declarations about the work due that week. The records do not show the day you completed it.
>
> The first accepted plan overlapped recorded busy time for 90 of 180 scheduled study minutes. The second overlapped for 30 of 150. Both used complete busy coverage, but they used different snapshots. The proposed plans had zero observed overlap in their hypothetical schedules.
>
> Three of four completed work scopes had comparable forecasts and recorded actuals each week. The actual fell inside its forecast range for one of three pairs in the first week and three of three in the second. The mean absolute error of the explicit point forecasts fell from 20 to 10 minutes. One completed scope lacked a comparable pair each week.
>
> The first week recorded four requests, five attempts and two confirmed effects. The second recorded three requests, three attempts and three effects. You recorded 25 manual minutes across two sessions in the first week and 10 across two sessions in the second. That is a 15-minute difference in recorded coordination. Its cause is unknown.
>
> The windows ran from local midnight October 19 to October 26, and from October 26 to November 2, in New York. They contained 168 and 169 elapsed hours. Both the state and evidence cutoffs were midnight November 2.

Receipt `http-baseline.json`. Report ID `962a0ba608b042b5f0505812553f7d9ada9be7a07a010743a8da59f54bebae28`.

### Week with sparse observations

> For October 26 through November 1 in the sparse synthetic record, both known deadline outcomes were on time. The other two outcomes are unknown. At the November 2 cutoff, both known personal declarations were marked done, with two unknown. Only two of four completed work scopes had comparable effort records. Both actuals were in range, and the explicit point forecasts had a mean absolute error of 15 minutes. The saved plan had zero observed overlap with the available busy intervals. Busy coverage was partial, so the total overlap is unknown. Two manual sessions were recorded. One had a duration of six minutes and the other had no recorded duration.

Receipt `http-partial_observations-baseline.json`. Report ID `1e93ba83bfdcb4dde766f53ce1d254d080f6d10881caaeb76bb8ade79a621fab`.

### Later evidence

> With the state cutoff held at November 2 and evidence admitted through November 4, the corrected deadline moves one missed item from the first week into the second. The two due cohorts now contain three and five items. The first week has zero missed among two known outcomes, and the second has one missed among four known outcomes. One outcome remains unknown in each week. Across both weeks the missed rate is still one of six known outcomes. The changed deadline affects where the work is counted. Recorded effort and coordination activity are unchanged.

Receipt `http-correction_after_cutoff-baseline.json`. Report ID `a06e6a176eaa3a363cb92f2e068921ffa77325f1ac0aa48fcb8ad1a7795b76a7`. A separate HTTP test exercised a linked, immutable restatement after an explicit duration correction. Both versions are in `http-owned-duration.json`.

| Host check | Local review |
| --- | --- |
| HF01 quantities and scope | Pass. Counts, durations and cohort sizes match the three selected synthetic courses. |
| HF02 denominators and missing coverage | Pass. Rates retain known denominators and unknowns. Partial busy coverage limits the overlap claim. |
| HF03 basis of progress | Pass. Personal done declarations are attributed to their due cohort at the cutoff. |
| HF04 basis of effort and activity | Pass. Scheduled, forecast, actual and manual minutes have distinct labels. |
| HF05 time and corrections | Pass. The answer preserves both cutoffs, the clock change and the corrected due cohort. |
| HF06 comparison units | Pass. Missed-rate change uses percentage points. Duration changes use minutes. |
| HF07 strength of claims | Pass. Synthetic scope is explicit. Causation and grade improvement are not claimed. |
| HF08 usefulness with missing data | Pass. The sparse answer gives available results and identifies the absent busy intervals and duration. |

This review covers these Codex interpretations of the local plugin responses. For installed-client acceptance, point an isolated client at the tested build, issue the same synthetic requests and score that client's actual replies. No production deployment, live coursework, external calendar operation or database migration was used.

## Reproduce the checks

Use the repository's configured Python environment. Set `BRIDGE_TEST_ANALYTICS_ZIP` to the original specification ZIP, whose SHA-256 is `91c493d36496f5145025c1207058f7ae91e18833fad6690e10d4a8243db1b33f`. Set `BRIDGE_TEST_ANALYTICS_OUTPUT` to an empty private output directory to retain JSON receipts.

```powershell
$stage6Tests = (Get-ChildItem tests/test_analytics*.py).FullName
python -m pytest -q -rs @stage6Tests
```

The package validator verified 45 file checksums, 33 JSON files, 13 deterministic rebuilds/scenarios, 1,312 independent expected-value comparisons, 13 metamorphic checks and five negative controls. On Windows its unmodified rebuild initially differed because the fixture writer used platform-native line endings. Repeating validation with UTF-8 text writes set to LF matched the original bytes. The run checked its four embedded source files and twelve literal quotes. Optional comparisons against a separate original upstream source archive were outside the run.

The checkout was on `codex/visual-pdf-reading` at base `5bd086356e730b01b5a9f1be9de106446ef049c6`, with existing working-tree changes. The tested source file manifest and Stage 6 test hashes are in `tested-build.json`. The implementation patch isolates the Stage 6 modules, integration points, schemas, tests and guide from other work in the checkout.
