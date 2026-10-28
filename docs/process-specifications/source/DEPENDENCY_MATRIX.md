# Dependency Matrix

| Spec | Depends on | Feeds into |
|---|---|---|
| CB-01 | CB-03, CB-12 | CB-02, CB-04, CB-11 |
| CB-02 | CB-01, CB-04 | CB-07, CB-09 |
| CB-03 | CB-12, coverage metadata | CB-01, CB-07, CB-10, integrity engine |
| CB-04 | CB-06, revisions | CB-02, CB-05, CB-15 |
| CB-05 | CB-06, canonical records | CB-07, CB-08, CB-10 |
| CB-06 | authorization registry, provenance | All persisted derived outputs |
| CB-07 | CB-03, CB-05, integrity engine | CB-02, CB-09, CB-17 |
| CB-08 | CB-05, CB-03 | CB-09, CB-17 |
| CB-09 | CB-02, CB-07 | Planning outputs |
| CB-10 | CB-03, CB-05 | Advising projections |
| CB-11 | CB-01, CB-03 | Resolution evidence |
| CB-12 | tool security baseline | Every ingestion workflow |
| CB-13 | versioned persistence | All stateful features |
| CB-14 | fixtures, harness | Every release gate |
| CB-15 | CB-04, CB-06, CB-13 | Portability, trust |
| CB-16 | CB-12, privacy-safe telemetry | Support and reliability |
| CB-17 | CB-06, CB-07, integrity engine | Portfolio publish/export |

**Critical path:** CB-12 → CB-03 → CB-01 → CB-06/CB-04 → CB-02 → CB-07 → CB-09. Parallel lanes: CB-14 continuously; CB-13/15 on storage maturity; CB-08/10/17 afterward.
