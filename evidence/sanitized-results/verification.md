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

## Course file inventory and bounded transport

The next source increment adds accessible file inventory, course-qualified
material identities, links from module entries to file/page references, and one
overall outline request budget. Hidden or locked file metadata is excluded;
unavailable collections remain explicitly partial. A fresh denied file fetch
clears any previously derived text. Page-only search excludes files until file
extraction is available.

An internal downloader now validates current course-file metadata, each exact
HTTPS destination, redirects, transfer type, length and signature. It uses the
existing public-IP DNS-pinned transport with a separate HTTP session. Tests
exercise hostile redirect destinations, stripping cookies and ambient HTTP
authentication, never restoring a bearer after a redirect, truncated/oversized
bodies, timeout and cancellation cleanup. Signed URLs stay out of persisted
materials, tool responses and backups. This transport is not yet used by MCP
file retrieval, and these checks do not establish live storage-host behavior.

Local Windows Python 3.14.5 verification: **191 tests passed in 21.08 seconds**,
including disposable PostgreSQL 17.11 migrations and restore tests, with no
skipped tests. Statement coverage was **80%**. Ruff lint and formatting checks
passed for 77 files. Migration rollback retained existing page records and
removed only derived file records; restoring older page records without a kind
field retained their page semantics.

Live binary extraction remains disabled. An accessible file returns an explicit
unsupported extraction result and stable Canvas link, never a claim that its
PDF/DOCX/PPTX contents were read. No actual course document was downloaded for
these synthetic tests, and this increment is not full R20/R21 acceptance.

The additive migration was also applied to the private owner database after an
encrypted pre-migration PostgreSQL archive was created and its decrypted bytes
verified. The existing service remained running, public metadata stayed available,
and unauthenticated MCP requests remained rejected. The running service was not
restarted to load the new file-inventory code during the owner's ongoing use.

## Phase 1 isolated file reading and actual ChatGPT proof

This later increment supersedes the disabled-extraction state above for the
private Windows source service. It adds `list_course_files`, `read_course_file`,
`search_course_files` and `get_file_extraction_status`, preserving existing tools.
PDF/TXT/Markdown use a credential-free Windows AppContainer worker and bounded,
versioned, page-aware chunks. Office/OCR/visual interpretation remain unavailable.

Final local run on Windows Python 3.14.5: **218 passed in 25.76 seconds**, no
failures or skips, **80% statement coverage**. Disposable PostgreSQL migration,
rollback and lifecycle tests were included. Ruff lint, formatting (85 Python
files) and `git diff --check` passed. Tests include actual Windows isolation
canaries for private files, environment secrets, network, child processes,
runtime writes, memory and timeout, as well as synthetic transport/refresh,
authorization, indexed/unindexed search, Unicode offsets, parser upgrades,
versions, PDF pages, scans, corruption and continuation. Two Windows isolation
tests explicitly skip on other operating systems.

With explicit owner authorization, the private database migration was applied
after an encrypted PostgreSQL backup and archive verification. Exact approved
storage hosts and a numeric file-bound hostname template were configured only
in private operator configuration. The existing launcher restarted the service.

The installed connector resolved the requested module PDF despite the general
course Files collection being denied. The actual 2,727,815-byte file traversed
three approved storage redirects and yielded **15 pages / 74,408 characters**.
Five `fetch_course_material` responses returned its complete text with consistent
content hash, page attribution and continuation. No manual student upload occurred.

After refreshing the installed plugin's catalog, a new actual ChatGPT Pro
conversation answered the owner's acceptance question from that PDF. It covered
the scientific subject, objective, experimental methods, major results and
conclusions, linked the Canvas source, cited PDF pages and explicitly excluded
visual interpretation and unread supplementary files. A follow-up invoked all
four new tools successfully: module listing, parsed/indexed status, a page-specific
read and text search. Two unread companion papers stayed unindexed and were not
downloaded. The UI tool trace and completed response were inspected; screenshots
and academic contents remain private and are not committed.

The proof is limited to this authorized personal connection and Windows host.
It is not institutional OAuth approval, other-university verification, Linux/macOS
parser support, Phase 2/3 delivery or public release acceptance. See
`docs/file-reading.md` and the remaining release gates.

## Live integration hardening

The following increment addresses the owner's seven reported findings. A private
read-only diagnostic confirmed the actual query-contract discrepancy: the list
included the owner's submission, the original single-assignment request omitted
it, and adding the documented submission inclusion returned the same workflow.
The diagnostic also distinguished an actual empty string description from an
omitted field. No raw academic records or credentials were committed.

`tests/test_integration_findings.py` adds **26 regression cases** covering all
findings, including metadata-only outlines, wrong module IDs, file resolution
beyond the first 100 inventory entries, unread-file search boundaries, complete
history baselines, undated scheduling and missing/contradictory submission data.
The synthetic provider now honors Canvas's submission-inclusion parameter so
future single-object/list query drift cannot silently pass fixture tests.

Final local Windows Python 3.14.5 run: **244 tests passed in 27.70 seconds**, no
failures or skips, **81% statement coverage**. Disposable PostgreSQL migrations,
rollback, privacy/lifecycle tests, real Windows sandbox checks and official HTTP
MCP contract tests were included. Ruff lint/format and diff checks passed. An
initial oversized pytest parameter name caused Windows test-setup errors; concise
test IDs fixed that harness issue before the successful full run.

After restarting the existing private launcher, actual installed-connector calls
confirmed matching workload/detail submission states, explicit empty-description
coverage, eleven null due dates with unknown scheduling, a precise pre-baseline
history limitation with cached freshness, and working PDF text/page attribution.
The outline reported denied Pages/Files collections explicitly while resolving
the authorized module files. All academic requests remained GET-only; no Canvas
content or grades were changed. New additive JSON response fields need no schema
migration. See `docs/live-integration-findings.md` for classification and root causes.

## Grade auditing and syllabus reconciliation

This increment adds four native read-only tools and a deterministic Decimal
calculation engine. `tests/test_grade_audit.py` adds **30 regression cases**,
covering all 17 requested grading edge cases plus PDF syllabus/page provenance,
version-bound policy reviews, explicit refusal, access withdrawal, cross-user and
cross-course isolation, request limits and timeout handling. The official HTTP
MCP client verifies actual tool schemas, annotations and calculation/refusal
responses. Existing tools and the original points helper remain compatible.

Local Windows Python 3.14.5 full run: **274 passed in 31.76 seconds**, no failures
or skips, **82% statement coverage**, including disposable PostgreSQL and real
Windows sandbox checks. The new acquisition/calculation/policy modules reached
84%/91%/90% statement coverage respectively. Ruff lint, formatting and diff checks
passed. The first focused test run exposed a missing imported HTTP-server test
fixture (24 passed, one setup error); importing the existing fixture fixed it.
One formatting check was corrected without a behavioral change. No unchanged
second full-suite run was performed.

An owner-authorized live GET-only check retrieved Canvas grading configuration,
own enrollment fields and list/detail evidence from the selected course. All
eleven returned assessments were ungraded, and the reported percentage was
unavailable. The engine correctly refused to manufacture a current percentage.
A separate live audit retrieved two syllabus sources through the existing
material infrastructure, returned source-bound rule candidates, and classified
the result as insufficient evidence: no posted scores and incomplete/ambiguous
policy mappings. No actual grades, source passages, private identifiers, tokens,
signed URLs or screenshots are committed in this evidence.

The existing private launcher restarted successfully with the four new tools.
No database migration, identity scope change or notification was introduced.
After refreshing the installed connector, an actual ChatGPT Pro conversation
invoked connection status and the new grade audit. The inspected tool activity
and final answer distinguished current versus final Canvas fields, reported
indeterminate independent calculations, cited the actual syllabus PDF/page,
listed unconfirmed rule candidates and identified missing scores and mappings.
It did not supply a policy review or accuse the instructor of an error. Private
UI proof remains outside the repository. An expanded HTTP contract check then
exercised all four new tools; the focused 30-case suite passed again.
The verified arithmetic subset and remaining policy/notification limitations are
documented in `docs/grade-auditing.md`. This is not proof of all grading policies,
instructor verification, institutional approval or a generally released service.


## Academic intelligence: ten-feature increment

Implemented the dependency-ordered increment documented in
`docs/academic-intelligence.md`. Five additional read-only MCP tools compose the
existing authorization, file, snapshot, grade and planning infrastructure. No
new model service, database table, Calendar credential grant or student setup
flow was introduced.

The new synthetic acceptance suite contains **35 cases**. It verifies exact
missing-deadline evidence, DOCX/PPTX extraction and real Windows AppContainer
execution, earliest observed metadata changes and stable dedupe keys, the
84-versus-91 grade example, rubric/instruction contradictions, explicit priority
tradeoffs, assessment-associated PDF retrieval, Calendar deduplication/DST/stale
inputs and a course with exactly five planted supported findings. Shared adapters
continue to exercise pagination, permission loss, ownership isolation, token
renewal and parser/network failure behavior. Native HTTP MCP tests invoke all
five new tools, with read-only annotations and unauthorized-request checks.

Full local Windows run: **309 passed in 41.35 seconds**, no failures or skips,
**83% statement coverage**, including PostgreSQL and the Windows sandbox. Lint
and format checks passed. Initial regression runs caught two compatibility
issues: an omitted submission's evidence label was overwritten by a conflict
label, and student-marked-done online work lost its submission-verification
reminder. Both were corrected: missing evidence remains missing, contradictions
are additive, and completed work is not allocated study sessions. The initial
full run had 308 passes and that one planning failure; the final full run is green.
The previous unchanged 274-test baseline was not redundantly rerun before work.

Calendar's existing native connection successfully returned a read-only profile
and busy intervals. No events were created, edited or deleted. This verifies the
available read connection, not approved Calendar write/read-back behavior.


The restarted private service then completed an actual selected-course audit.
It reported available assignment evidence separately from partial announcements
and material inventory, kept all null due dates as timing unknown, distinguished
empty descriptions from full requirements, and reported unresolved reading
references without labeling them required. A source syllabus was read. The
updated v3 sandbox also reread the authorized acceptance paper: all **15 PDF
pages / 74,408 characters in five bounded chunks**, with scientific sections
present. Actual source text and private identifiers remain outside Git.


A final dependency audit found eight advisories in optional packaging Pillow
12.3.0. The packaging constraint/lock were upgraded to Pillow 13.0.0; the
subsequent audit reported **no known vulnerabilities**. Five desktop regressions
passed in 4.12 seconds, and PNG/ICO/ICNS generation and decoding were verified
with the upgraded library. The service extraction dependencies did not change.
See the [upstream security release](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html).


After refreshing the installed connector, an actual ChatGPT conversation invoked
`audit_course_consistency` and `prepare_for_assessment`. Its inspected final
answer cited Canvas assignments/modules, kept undated quizzes from being called
upcoming, reported missing requirements and unresolved references neutrally, and
refused to identify a next quiz without reliable timing evidence. Grades were
excluded. A private screenshot remains outside the repository. This proves the
new native workflow and honest refusal, not complete coverage of the live course.


The same actual ChatGPT conversation subsequently used Google Calendar
availability/event searches, a fresh selected-course Canvas workload, and
`propose_calendar_sync`. The inspected activity identified both plugins and the
new proposal tool. Its final answer described one deadline reminder proposal,
reported duplicate/mapping checks and an overlap with an existing commitment,
and explicitly stated that nothing was created or changed. This establishes
native read/proposal composition; explicit approved create/update/read-back and
autonomous synchronization remain untested and are not claimed. Private UI
proof is stored outside Git; no actual event titles or coursework were committed.

## 2026-10-20: Source-linked course obligations

The unchanged 309-test baseline at `b175fae` was reused. A new
`get_course_obligations` tool adds bounded assignment/classic-quiz/discussion-topic/
Canvas-calendar discovery through three reviewed GET routes. Explicit source
relationships deduplicate records; titles alone do not. Assignment-effective dates,
unknown completion, source differences, per-description states and partial coverage
remain distinct. No planner, peer-post, question, attempt or calendar-write route
was added. Existing workload and planning contracts were preserved.

There are **28 new regression cases** in `tests/test_obligations.py`, including
real HTTP MCP transport, safe quiz instructions when assignment text is empty,
same-title and contradictory aliases, denied/expired access, owner isolation,
epoch fencing, pagination confinement, source-version continuation, bounded
responses, date-only events and the DST half-open-window boundary. The final
Windows suite passed **337 tests in 45.96 seconds**, with no failures or skips,
**84% total statement coverage** and **93% obligation-module coverage**. PostgreSQL
and the Windows AppContainer checks were included. Ruff lint and all 103 Python
files' format checks passed. An intermediate run had 336 passes and one test-only
NameError introduced while moving fixture assertions; it was corrected before the
successful final full run. No application change was needed for that failure.

The authorized private selected-course read completed assignment and both Canvas
calendar collections. Classic quizzes were permission-denied, and one discussion
had no posting timestamp, so no quiz/topic instructions were asserted readable.
This verifies honest graceful limitations against the actual account, not complete
course coverage. Private results are retained outside Git. The local service was
restarted using its existing scoped launcher. No Canvas content, grades, Calendar
events or institutional OAuth settings were changed.

After catalog refresh, an actual ChatGPT conversation invoked the new inventory,
followed continuation through the selected course, cited the assignment source,
and explicitly refused to invent unread quiz instructions or upcoming dates. Its
live answer exposed an overly general omitted-discussion warning. The projection
now returns per-reason counts (including missing posting time), with no withheld
resource identities or text. A new regression brought the increment to **29
cases**, all passing in **3.30 seconds** after that additive clarification. The
337-test full run above precedes this final reason-label change; CI validates the
final tree. Private conversation screenshots remain outside Git.


## 2026-10-20: Linux document isolation

A credential-free Linux worker adds Landlock ABI 3+ filesystem restrictions,
default-deny seccomp, hard resource limits and fail-closed kernel prerequisites.
The dispatcher preserves Windows AppContainer behavior. A separate public runtime
cache supports read-only images with bounded non-executable document scratch.
No MCP tools, Canvas routes, OAuth scopes or database migrations were added.

The initial Linux branch run `39514505600` passed 345 tests (four Windows-specific
cases skipped) and dependency auditing, but its container smoke test failed.
Trusted native libraries were being loaded from non-executable temporary storage.
Separating the prebuilt runtime into the read-only image corrected that failure.
Run [39515236580](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39515236580)
at `dba7e4d` passed **347 tests, four skipped, in 53.02 seconds**, **80% total
statement coverage**, Ruff, dependency audit (no known vulnerabilities), image
build and the strict unprivileged text-extraction container check.

The Windows targeted regression run passed **62 tests, 12 Linux kernel cases
skipped, in 15.46 seconds**. Tests included actual Windows AppContainer file and
Office extraction. Linux canaries exercise private-file/environment/descriptor,
network, child-process, runtime-write, CPU, memory, output and wall-time isolation;
missing kernel protections fail rather than skip on Linux.

The final hardening change limits Linux writes to one precreated output file,
preventing input modification and arbitrary file creation. Run
[39515513203](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39515513203)
at `acd3fe8` passed **347 tests, four Windows-only skips, in 42.69 seconds**, with
80% total statement coverage. All 13 Linux sandbox cases passed. The built image
separately extracted PDF, TXT, Markdown, DOCX and PPTX using the service extraction
entry point, verified PDF page attribution and cleaned each job directory. It
used no network, no capabilities, no-new-privileges, default Docker seccomp,
a read-only root and a bounded non-executable tmpfs. Ruff, image build and
dependency auditing passed; no known vulnerabilities were reported. The final
acceptance-record update changes documentation only, so the unchanged source
suite is not rerun for that update.

Actual Linux student-course reads, hosted service
deployment, other CPU architectures and independent security review remain
unverified. No student data or secrets were used in these tests.


## 2026-10-20: Planning date and elapsed-capacity corrections

The prior full suite at `edf364e` was reused as the unchanged baseline. Executing
the baseline planner with synthetic inputs reproduced allocation after a date-only
due date and 120 scheduled minutes inside a spring-DST window containing only 60
elapsed minutes. A shared timing calculation now preserves source precision,
requires applicable per-work timezones for date-only fields, exposes conservative
planning bounds, enforces opening/closing constraints for pins and automatic
blocks, and computes elapsed UTC capacity. Missing timing yields an explicit
unresolved result. The Calendar composition path uses the same calculation.

The increment adds **26 regression cases** in `tests/test_planning_dates.py`.
The focused run passed **82 tests in 13.56 seconds**. The full Windows run passed
**365 tests with 12 Linux-only skips in 46.34 seconds**, with **82% total statement
coverage**, **95% planner coverage** and **99% timing-module coverage**. PostgreSQL,
Windows AppContainer and actual HTTP MCP tests were included. Ruff and formatting
checks passed for all 111 Python files. Source dates and submission states are not
modified; automated tests use fictional records and request no Canvas writes.

Linux [CI run 39516486216](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39516486216)
passed **373 tests with four Windows-only skips in 55.95 seconds**, with **81%
total statement coverage**, at source commit `96af218`. Checks included lint/formatting,
dependency auditing, image build and all five isolated document formats in the
restricted container. Dependency auditing found no known vulnerabilities.

The private source service was restarted using its existing scoped launcher.
The installed native connector returned a fresh complete assignment collection
for all four selected courses, then returned a study recommendation with the new
source-linked timing records. It returned `availability_unknown` and no blocks,
as no study availability was supplied. No date-only deadline was present in that
live window: date-only and DST acceptance remain synthetic. The ChatGPT plugin
catalog was refreshed, and its visible planning-tool description included the
new timezone/boundary contract. Private proof files remain outside Git. No plan
was saved, and no Canvas content, grades or Calendar events were changed.

The final acceptance-record commit changes documentation only; the unchanged
source suite is not rerun for that update.
No new tool, OAuth scope, Canvas route, database migration or Calendar write is
introduced. See [planning date boundaries](../../docs/planning-date-bounds.md)
for inputs, source-versus-calculation provenance, known limits and root causes.

## 2026-10-20: Selected activity study planning

`propose_course_study_plan` bridges the bounded course inventory into the shared
deterministic allocator. The snapshot-based planner remains compatible. Source
versions and current selected-course access are checked, linked aliases schedule
once, suggested activities remain review entries, and calendar event preparation
retains its own target instead of inventing an assignment due date. Source and
coverage changes require a fresh inventory. No extra credential, route, table,
Canvas write, saved plan or Calendar event is introduced.

The increment adds **26 synthetic regression cases** in
`tests/test_activity_planning.py`. The focused run passed **81 tests in 6.01
seconds**. The first full run found an outdated read-only catalog count (25
instead of 26); the catalog assertion now verifies the new tool and unchanged
read-only annotations. After correction, the full Windows/PostgreSQL suite passed
**391 tests, 12 Linux-only skips, in 50.01 seconds**, with **82% total statement
coverage**, **97% new activity-planning coverage**, **96% shared planner coverage**
and **97% timing coverage**. Actual HTTP MCP and Windows AppContainer cases were
included. Ruff and formatting passed for all 114 Python files.

Acceptance covers mixed activity allocation, linked-record deduplication,
same-title course isolation, later inventory pages, explicit source conflicts,
unknown effort/participation, completed work, own progress, authorization errors,
selection races, partial coverage, changed sources, timeout cancellation, response
bounds, all-day event preparation and DST. It does not establish institution-wide
availability, New Quizzes, group-child participation, persisted new-activity
progress or new-activity Calendar writes. See
[activity study planning](../../docs/activity-study-planning.md).

Linux [CI run 39517914326](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39517914326)
at `cc158f4` passed **399 tests with four Windows-only skips in 53.91 seconds**,
with **81% total statement coverage** and **97% new activity-planning coverage**.
Lint, formatting, dependency auditing and the image build passed. Dependency
auditing reported no known vulnerabilities. The restricted image independently
extracted PDF, TXT, Markdown, DOCX and PPTX fixtures and cleaned every job.

The private service was restarted using its scoped launcher. The installed
ChatGPT plugin catalog was refreshed and visibly contained **26 read-only tools**,
including the new activity planner. A native ChatGPT conversation then read the
selected Stem Cell Engineering inventory and called the new tool with a returned
assignment ID/version as `suggested_review`, no windows and no effort estimates.
It reported `needs_input`, `selection_needs_review`, one review entry, zero
selected activities and zero blocks. A separate authorized private service check
asserted the same response shape and preserved source/coverage evidence.

The actual course read enumerated 11 assignments, completed both calendar
collections, received a classic-quiz permission denial and withheld one discussion
with unavailable posting-time evidence. These limitations survived planning.
Standalone quiz/discussion/event allocation acceptance remains synthetic; this
live test proves the review behavior and native integration, not availability of
those resource types at Rowan. No grades were read, no Canvas content was changed,
and no plan or Calendar event was saved. Screenshots and aggregate proof remain
in the private operator directory outside Git. The final proof-record update
changes documentation only, so the unchanged full source suite is not rerun.

## 2026-10-20: Authenticated search of unread documents

The prior verified 391-test suite was reused as the unchanged baseline. The
confirmed unread-file search gap is now addressed by optional
`search_course_files(include_unread=true)`: authenticated discovery, bounded
three-file batches, existing isolated extraction, and encrypted file/page
continuation. Default cached-only behavior is preserved. The shared reader also
preserves available Canvas modification timestamps in its source evidence.

The increment adds **28 regression cases** in `tests/test_document_search.py`.
The focused file/search/hardening run passed 77 tests before three additional
continuation/Unicode cases; the final new-search-only run passed **28 tests in
4.55 seconds**. After the final source-provenance and indexed-state corrections, the full
Windows/PostgreSQL suite passed **419 tests, 12 Linux-only skips, in 58.50
seconds**, with **83% total statement coverage**, **92% new search-module
coverage** and **88% shared file-reader coverage**. Ruff and formatting passed.
Actual HTTP MCP and Windows AppContainer tests were included.

Synthetic acceptance found scientific text inside an unread PDF, returned its
page and hash, and reused the extraction cache. Further cases cover multi-page
and multi-document continuation without repeated downloads, query/scope/parser/
inventory version binding, expired/tampered/foreign cursors, incomplete inventory,
scanned/unsupported/failed files, disabled extraction, unknown versions, timeout,
source changes during reading, hidden resources, cross-course duplicate names,
signed-URL rotation and literal Unicode offsets. Reconnect failures now discard
prior cached-search hits; partially parsed cached documents report partial data.
No test changes Canvas, grades or Calendar data. See
[document search](../../docs/document-search.md) for scope and resource limits.
