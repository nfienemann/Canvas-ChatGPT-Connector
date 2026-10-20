# Local verification — 2026-10-20

Environment: Windows, CPython 3.14.5, uv 0.13.4, PostgreSQL 17.11, locked
dependencies in `uv.lock`. All academic records and identities were synthetic.
The source manifest identifies the tested Python files with LF-normalized hashes.

| Check | Observed result |
|---|---|
| Full pytest suite with disposable PostgreSQL | **92 passed**, 0 failed, 0 skipped; 11.04 seconds |
| Statement coverage | **78%** (1,851 / 2,366 statements); not proof of full acceptance |
| Ruff lint and format | Passed |
| Frozen dependency sync | Passed |
| Source distribution and wheel build | Passed |
| Dependency advisory audit | 73 third-party distributions audited; no known vulnerabilities reported. This unpublished local project was skipped by the advisory service |
| PostgreSQL migrations | Upgrade, read/write, downgrade to base, upgrade again passed in random isolated test schemas |
| PostgreSQL concurrency | One of two conflicting local writes rejected; pooled connections did not cross owner scope |
| MCP HTTP client | Protocol 2025-11-25, 14 tools, 5 fictional obligations; workload and planning succeeded |
| Local settings browser | Keyboard synthetic sign-in and visual layout checked; screenshot retained |
| Lifecycle | Disconnect, account-wide deletion, pending OAuth cancellation, scope purge, export, encrypted backup, deletion-fenced restore and queued-job isolation fixtures passed |
| Planning | Capacity conservation, busy intervals, preserved pins, dependency order/cycles, unknown effort and urgent large-task fixtures passed |

The local PostgreSQL runtime and database, keys, tokens, logs, raw test reports
and build outputs are excluded from source publication. The API runs on
loopback and uses fictional data. No real university or Calendar was contacted.

The browser check found an Origin-null form issue under the page's no-referrer
policy. The fix accepts that case only with a same-origin Fetch Metadata header
and a matching CSRF nonce; the automated browser-route test covers it.

This report does **not** establish actual ChatGPT conversations, live Canvas OAuth,
individual/section/group date equivalence, Calendar interoperability, WCAG
conformance, screen-reader/mobile usability, production SLOs, a real parser
sandbox, hosted recovery, institutional approval or public Directory eligibility.
Container execution and GitHub CI are separately recorded when observed.
See the requirement ledger and release gates rather than treating 92 passing
fixtures as completion of every scenario in the specification.

The first Linux CI run found a test-clock assumption: assigning monotonic zero
did not expire a five-minute cache on a newly booted runner. The regression now
ages the recorded load time by 301 seconds. Application behavior is unchanged.

## Earlier independent Linux CI

[GitHub Actions run 39479498970](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39479498970)
passed on commit `207d8d24e459de6ff138a9718cec4d41012f10b9`:

- Ubuntu 24.04, Python 3.14.8 and PostgreSQL 17.11.
- 81 tests passed in 7.22 seconds, with no skips; 76% statement coverage.
- Frozen install, Ruff lint/format and dependency advisory audit passed.
- The nonroot Docker image built successfully as `canvas-bridge:ci`.

Image construction is verified. A hosted deployment, containerized service
operation with real credentials, and live integration remain unverified.

## Account lifecycle increment

The local 92-test run above includes the account-wide deletion implementation.
It covers two institutions, another unaffected principal, pending authorization,
deletion during both token exchange and profile retrieval, bounded remote
revocation failure, and the PostgreSQL link/delete race. Restore fixtures reject
pre-deletion connections and permit a newly authorized post-deletion connection.
Term retirement also purges cached course records and snapshots.

The live local demonstration was migrated to `9b2a41e5021c`. Keyboard sign-in and
the updated account controls were inspected in the browser; the new screenshot
records the visible confirmation checkbox and independent-copy disclosure.

The increment also passed [Linux CI run 39486541840](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39486541840)
on commit `ac4e4e45bcb40b8245c06099ce16ea045d64dbfd`: **92 passed in 7.85
seconds**, 78% statement coverage, successful lint/format, no known dependency
vulnerabilities, and a successful Docker image build.
