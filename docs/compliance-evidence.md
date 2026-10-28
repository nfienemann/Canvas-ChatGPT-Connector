# Security and governance evidence

This is a developer/reviewer subsystem. It produces technical evidence and never
grants provider, institution, content-owner or platform permission, chooses a
license, or determines legal compliance. It exposes no MCP operation.

## Regenerate a review package

Run from a known source checkout, using Python 3.13 or 3.14 and the locked project
environment. The report command requires that checkout; installing the wheel alone
does not supply a reviewed repository or execution evidence.

```console
uv sync --frozen
uv run canvas-bridge compliance-report --validate-only
uv run pytest -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/review-input/tests.json
uv run python -m canvas_bridge.compliance.checks lint --output .local/review-input/checks/lint.json
uv run canvas-bridge compliance-report --category synthetic_demo --results .local/review-input/tests.json --checks .local/review-input/checks --output .local/review-package
```

Use a new receipt filename and output directory for each run. Files are never
overwritten. `report.md` and `report.json` share the same facts. Repeating generation
with unchanged inputs on the same UTC date produces the same report. The command
does not read `.env`, credentials, private approval bundles, databases, course files,
or raw authentication/test logs; the supplied category is a review label, not an
attestation about a running deployment. Provider capabilities are implementation
inventory, and live activation is explicitly not attested.

The fixed check runner supports `lint`, `format`, `bandit`,
`python_vulnerabilities`, `node_vulnerabilities`, `licenses`, `secret_history`,
`secret_source`, `container_config`, `container_image` and `container_runtime`. Run each with its own
`--output` receipt. There is no arbitrary-command option. Dependency/scanner
installation may contact public package/advisory services; none of these commands
retrieves LMS records. Image checks require the existing `canvas-bridge:ci` build;
Linux scanner/image evidence cannot be claimed on an unsupported Windows host.

Receipt JSON contains only source identity, check ID, status, counts and public
advisory IDs. Scanner output stays in temporary private files and is discarded.
The unpublished first-party project is explicitly marked for source security
review instead of being treated as a public dependency advisory entry. This
exception checks the installed project version against the checkout. Any other
skipped package makes the dependency check inconclusive; zero known dependency
advisories never means the application's own code is vulnerability-free.
The pytest plugin removes parameter values, captured output, failure messages and
local paths. Setup/teardown errors override a passed call; skipped and interrupted
cases never satisfy a control. The report rejects unknown fields or test references.
Filtered runs, including individual parameter selections, can report their actual
outcomes but cannot certify a control's complete regression selection.
Missing receipts appear as NOT_RUN. Wrong source/commit, changes during execution,
future dates or results more than seven days old appear stale. Neither a test file
nor an old Markdown claim establishes TESTED.

## Source identity and trust

Reports identify the application version, Git commit, dirty state and a SHA-256
snapshot of tracked/nonignored source, tests, migrations, build/CI configuration,
governance definitions and review documentation. The scope is
`reviewed-source-v1`; text line endings normalize to LF. Ignored operator files and
generated historical reports are outside the scope. An uncommitted snapshot is
explicitly labeled and blocks release; retain the diff for local reproduction.

Approval/manual-review attestation values are excluded from the code snapshot to
avoid circular hashes; their definitions remain included. The full parsed register
has a separate `registry_sha256` in every report. An approval's `scope_digest`
binds the release target and source snapshot. Manual reviews bind the source digest
and expire. These are review metadata, not cryptographic authority. Local receipts
are unsigned execution claims; verify them against the exact CI run/commit or by
supervised reproduction before relying on them. CI artifacts have a 30-day lifetime.
Local report directories are explicit reviewer exports; retain or archive them
under the review owner's documented evidence policy, not as student-data caches.

The human-maintained [control register](../governance/controls.json) records
implementation status separately from observed verification. Technical controls
start IMPLEMENTED_UNVERIFIED. Only current execution of every named case/check
produces TESTED in a report. Required manual checks and residual limitations remain
visible even then. External-authority controls retain REQUIRES_EXTERNAL_APPROVAL;
their independent approval and manual-review registers govern release. The legacy
`scripts/build_evidence.py` now produces a source index, never VERIFIED from file
presence.

## Approvals and release targets

All approval entries currently say MISSING. This means evidence has not been
established in this register; it is not a claim about unseen private correspondence.
Authorized administrators may maintain non-sensitive evidence IDs, scope, effective
and expiry dates and verification status through reviewed repository changes.
Keep underlying correspondence in the existing protected administrator evidence
store. Do not paste it into the registry or report. Ordinary model instructions
cannot edit the register through a tool or install runtime grants.

GRANTED requires verified bounded evidence for the exact target/source scope.
RESTRICTED, EXPIRED, REJECTED, unverified, future or mismatched grants block the
target. Restriction conditions need explicit review; the report does not interpret
them permissively. Runtime enforcement continues to use the existing signed
approval gateway independently. A reporting change cannot activate an adapter.

| Target | Independent release requirements |
|---|---|
| Offline open-source core | Adopted license and notices, repository/history/fixture content review, security assessment, exact offline artifact/launcher review, applicable rights-holder decisions and technical checks. Hosted image checks do not certify an offline package. |
| Authorized institutional pilot | Applicable upstream method approval, each institution's permission, content and AI recipient arrangements, approved deployment manifest, operations owners and platform-specific security evidence. |
| Public connected plugin | Pilot requirements plus publication eligibility/approval, public privacy/support practices, actual platform flows, reviewed demo account and operational readiness. |

Use `--enforce-release offline_core` (or another target) to return exit code 2 when
its gate is blocked; the report is still written. `--require-technical` also returns
2 for incomplete or failed technical evidence. Ordinary report generation exits
0 when generation succeeds, regardless of release readiness. Invalid evidence or
an unsafe output destination exits 1. No command publishes or deploys anything.

The project currently has no adopted open-source license, documented actual
external approvals, appointed public security contact or independently accepted
production security assessment. Passing all tests does not clear these gaps.

## Policy updates

The register maps a reviewed subset of the Instructure API Policy, Rowan AI and LMS
integration policies, and OpenAI Plugin guidelines. Each entry supplies the exact
source, section, published effective date when available, revision, review date
and next-review date. An unstated effective date remains null with an explanation;
the reviewer date is never substituted. Rowan mappings are candidate-specific,
not universal requirements for other institutions. These are technical
interpretations, not legal findings.

At the review date or on an announced change, retrieve the official source, compare
the relevant sections, record the revision and applicability decision in a reviewed
change, and reassess affected controls and grants. Overdue policy reviews block
connected targets. The report performs no automatic web fetch and never broadens
permissions because a policy page changed. Updating a review date without reading
the source is not a completed review.

## Reproducible fictional walkthrough

```console
uv run pytest -q tests/test_compliance_walkthroughs.py -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/walkthrough-input/tests.json
uv run canvas-bridge compliance-report --results .local/walkthrough-input/tests.json --output .local/walkthrough-package
uv run canvas-academic demo-grade
```

The seven named scenarios show an unauthorized source blocked, another fictional
student's identifiers withheld, an 85% permitted calculation, revoked input denied,
restricted file transfer denied, deterministic cache expiration, and source text
failing to enable an unauthorized provider. They exercise real local policy/service
code with synthetic dependencies. They are not deployed ChatGPT or institutional
acceptance. Running only these cases leaves unrelated controls unverified.

`governance/demo/academic.json` is wholly fictional. The fixed PPTX fixture is
generated by `scripts/generate_presentation_fixture.py`. The fixture catalog pins
allowed standalone fixture paths and bytes; unexpected files or changed bytes fail
validation. Editor lockfiles are ignored and never copied into evidence. Updating a
catalog requires source/provenance review; a hash is change detection, not proof that
a file contains no PII. Code-generated fixtures and the whole Git history remain
subject to secret scanning and mandatory human content review.

## Reviewer documents and CI

The fifteen [review templates](review-templates/system-architecture.md) are listed
in the registry and linked in each report. They point to maintained implementation
documents and mark deployment assertions UNVERIFIED until the appropriate reviewer
completes them. Use non-sensitive references for security findings and approvals.

CI validates the registry, enforcement/test references, fixture catalog and template
coverage; executes the full security/privacy/egress/authorization regressions;
records fixed dependency, license, secret and build checks; and uploads only the
sanitized readiness report, including on failed runs. Missing steps remain missing.
CI technical readiness is never legal self-certification. Requested public desktop
preview builds now enforce the offline distribution gate before downstream build
and publication jobs. Existing published artifacts are not retroactively certified;
new publication remains blocked while licensing/review evidence is missing.
