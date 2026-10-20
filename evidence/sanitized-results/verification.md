# Local verification — 2026-10-20

Environment: Windows, CPython 3.14.5, uv 0.13.4, PostgreSQL 17.11, locked
dependencies in `uv.lock`. All academic records and identities were synthetic.
The source manifest identifies the tested Python files with LF-normalized hashes.

| Check | Observed result |
|---|---|
| Full pytest suite with disposable PostgreSQL | **97 passed**, 0 failed, 0 skipped; 19.75 seconds |
| Statement coverage | **77%** (2,102 / 2,738 statements); not proof of full acceptance |
| Ruff lint and format | Passed |
| Frozen dependency sync | Passed |
| Source distribution and wheel build | Passed; migrations and institution fixtures included |
| Desktop runtime fixtures | 5 passed: independent working directory, poisoned operator environment, port collision, OS lock, restart preservation and folder preferences |
| Windows packaged demo | Native wizard and real MCP passed without Python on PATH; install, in-place upgrade and uninstall preserved data in an isolated test |
| Dependency advisory audit | 80 third-party distributions in the local build environment audited; no known vulnerabilities reported. This unpublished local project was skipped by the advisory service |
| PostgreSQL migrations | Upgrade, read/write, downgrade to base, upgrade again passed in random isolated test schemas |
| PostgreSQL concurrency | One of two conflicting local writes rejected; pooled connections did not cross owner scope |
| MCP HTTP client | Protocol 2025-11-25, 14 tools, 5 fictional obligations; workload and planning succeeded |
| Local settings browser | Keyboard synthetic sign-in and visual layout checked; screenshot retained |
| Lifecycle | Disconnect, account-wide deletion, pending OAuth cancellation, scope purge, export, encrypted backup, deletion-fenced restore and queued-job isolation fixtures passed |
| Planning | Capacity conservation, busy intervals, preserved pins, dependency order/cycles, unknown effort and urgent large-task fixtures passed |

## Published native demo packages

[Workflow 39489429523](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39489429523)
passed for source commit `bb3e957b7e01d2f4d490116729a8537c81e64c4c`.
The Ubuntu PostgreSQL job passed **97 tests in 10.10 seconds**, with **77%**
statement coverage (2,097 / 2,738), lint/format, dependency audit and Docker build.

The Windows x64 installer, macOS ARM64/Intel disk images and Linux x64 DEB each
passed packaged startup, the native wizard controls and a real authenticated
MCP read/planning check. The harness removed Python from the subprocess PATH and
used an unrelated working directory and a profile path containing spaces/Unicode.
Windows also passed an in-place upgrade and uninstall; Linux passed DEB removal.
Keys/data were retained across restart and the tested uninstall paths.

The [public preview](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases/tag/demo-bb3e957b7e01)
includes four platform verification reports, five native/portable downloads and
checksums. The four downloaded report hashes were verified, and all nine entries
in the published checksum file matched GitHub's asset digest metadata. See
[native-packages.json](native-packages.json) for exact assets, hashes and reports.

These are unsigned synthetic previews. CI does not establish trusted-publisher
approval, consumer-OS installation prompts, screen-reader accessibility, support
for every Linux distribution, live Canvas access or actual ChatGPT connectivity.
Publisher signing and Apple notarization remain release gates.

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

## Personal developer setup increment

On 2026-10-20, the full local suite passed **109 tests in 20.09 seconds** with
PostgreSQL 17.11 enabled and no skips. Statement coverage was 78% (2,207/2,841).
Ruff lint, format and `git diff --check` passed after a formatting-only correction.
No dependency or packaging change was made; native installers remain the earlier
synthetic preview release.

New fixtures cover personal-profile identity restriction, expected Canvas user
verification, encrypted import, no automatic course selection, wrong-origin and
wrong-profile rejection, duplicate import, deletion during verification,
PostgreSQL simultaneous imports, normal provider revocation, hidden-input
fallback refusal, redacted operator errors, and browser/MCP rejection of other
users. An optional eleven-tool read-only catalog omits saved-state write tools
from discovery and dispatch.

Rowan's public Canvas origin was verified using its official service page.
No personal token was supplied to this code, no real Canvas account was accessed,
and no actual ChatGPT conversation was tested. Identity-provider and secure
reachability setup remain prerequisites for that first private proof.

## Browser identity-provider compatibility increment

On 2026-10-20 the full local suite passed **124 tests in 19.42 seconds**, including
PostgreSQL tests, with no skips and 79% statement coverage (2,253/2,858). Ruff lint,
format and `git diff --check` passed. Fifteen new HTTP cases verify settings
OAuth PKCE, exact redirect/resource binding, replay rejection, provider-specific
callbacks, missing/wrong/duplicate issuer rejection, browser binding and rejection
of changed identity-provider configuration before code exchange.

The default callback still requires RFC 9207 `iss`. An explicit compatibility
mode uses issuer-specific redirect URIs under RFC 9700 section 4.4.2.2. WorkOS
configuration was documented at this checkpoint, but a live provider login and
an actual ChatGPT coursework read had not yet passed. No personal token or
academic records were used in these tests. Native demo packages are unchanged.

## Exact OAuth metadata identifiers

On 2026-10-20 the full local suite passed **132 tests in 16.54 seconds**, including
PostgreSQL tests, with no skips and 79% statement coverage (2,263/2,869). Discovery
now preserves configured resource and issuer strings exactly instead of allowing
the MCP SDK URL model to append a slash to bare origins. Eight new cases cover
bare origins, trailing slashes, resource paths, read-only and writable scopes,
CORS discovery and the unauthenticated challenge URL. The real HTTP MCP contract
also checks exact identifiers. This does not relax JWT issuer or audience checks.

The private HTTPS endpoint is reachable and rejects unauthenticated MCP requests.
At this checkpoint, provider sign-in, a personal Canvas connection and ChatGPT
coursework retrieval remained unverified. Subsequent evidence is recorded below.
No personal token or coursework appears in repository evidence.

## Subsequent private operator integration proof

The exact-identifier increment passed [Linux CI run 39495918923](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39495918923)
on commit `4fe8ac1230d13387b1bb857aa9515635cac48eb8`: **132 tests passed in
13.31 seconds**, 79% statement coverage, successful lint/format, no known
dependency vulnerabilities and a successful Docker build.

A separate, private Windows instance subsequently completed real WorkOS sign-in
and owner binding, encrypted operator-token storage, explicit course selection
and a nonempty Rowan workload read over public HTTPS using the official MCP
client. The service advertised eleven read-only tools, returned no tool error
and reported successful assignment-source coverage. Unauthenticated calls were
rejected with HTTP 401 and exact discovery identifiers. This is an operator-only
proof, not an institutional OAuth approval, an ordinary ChatGPT conversation,
complete obligation coverage or a public-support claim.

The initial console paste failed. A local operator window then verified masked
paste, empty-input rejection without a request, retry after rejection, explicit
account confirmation, invalidation after editing the token and clearing the
field after encrypted storage. Those UI checks used a synthetic backend and did
not read the system clipboard. The owner completed the actual private entry.
Credentials, identity IDs, academic records and private configuration remain
outside the repository and its evidence artifacts.

## Actual ChatGPT private first read

On 2026-10-20 the owner explicitly authorized installation and a read-only test
in their ChatGPT Pro account. A static public OAuth client used the exact callback
shown by ChatGPT, PKCE and the `academic:read` scope. The installed Canvas Bridge
plugin completed a real conversation. ChatGPT's execution panel identified
connection-status, course-list and workload calls; its response returned the
selected courses, upcoming deadlines, submission states, Canvas links and local
time-zone conversions. It reported complete selected assignment collections and
explicitly warned that syllabus-only or other obligations may be missing.

This proof requested no grades or writes. It does not verify every tool, mobile
clients, native Calendar composition, institutional OAuth or public eligibility.
The authenticated session, screenshots, endpoint configuration and coursework
remain in restricted private storage. Only this sanitized outcome is published.
No application code changed during the live setup. The existing 132-test local
and Linux CI results remain the applicable automated checks; the unchanged full
suite was not redundantly rerun for these documentation updates.

## Private connection lifecycle follow-up

The initial client omitted `offline_access`. Its first read passed, but a later
call required reauthentication because no refresh token was available. With the
owner's explicit approval, the corrected **Canvas Bridge Personal** plugin
requests this base scope alongside `academic:read`. The original temporary plugin
was uninstalled after the replacement successfully read the selected courses.
No additional academic operation was enabled.

A subsequent actual ChatGPT conversation completed connection-status and workload
calls more than six minutes after the replacement sign-in, following a full local
service restart, without another interactive login. It returned active connection
state and a nonempty workload, retaining the assignment-only coverage warning.
This is a short lifecycle proof, not a multi-day session or revocation guarantee.

The private Start menu launcher also passed full stop/start under Windows
PowerShell 5.1, the actual shortcut host. Two Windows process-wait behaviors were
corrected in that private launcher: waiting for all database descendants, and an
unset process exit code after waiting only for the launcher. The resulting checks
use the specific database cluster's status, recover public discovery and retain
HTTP 401 for unauthenticated MCP calls. These operator files remain private and
are not part of the downloadable synthetic demo packages.

The preceding documentation commit passed [Linux CI run 39498991158](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39498991158).
These follow-up repository changes are documentation only; no unchanged full
suite was manually repeated.
