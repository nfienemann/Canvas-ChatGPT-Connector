# Security gates and vulnerability remediation

The project license remains an owner decision in `LICENSE-STATUS.md`. These
controls screen technical dependencies and protect builds; they do not grant a
project license, provider approval, institutional approval or legal compliance.

## Repeatable gates

CI runs a locked `uv sync`, `uv pip check`, reviewed-registry/artifact-integrity
validation, Ruff security rules, Bandit medium/high severity and confidence,
full synthetic tests, `pip-audit` and `npm audit` including development packages.
Gitleaks scans all available Git refs/history (`fetch-depth: 0`) and a fresh
snapshot of tracked/nonignored source, with full output redaction. No private
ignored operator directories are copied into the snapshot. Its one allowlist is
restricted to SHA-256 entries in the source manifest, not general test secrets.

Critical Python authentication, networking and parser dependencies are pinned in
`pyproject.toml`; all resolved packages/artifacts remain hash-bound in `uv.lock`.
The build backend, uv installer, scanner releases, GitHub actions and image bases
are pinned. `scripts/security_tools.py` checks an embedded SHA-256 for the exact
release archive before reading its exact executable member. Cache modification
cannot bypass that check. Changing the scanner pin requires independent review
of its official release/checksum and rerunning tamper fixtures.

Trivy checks build/container misconfiguration and high/critical vulnerabilities
in the actual built image; failures block the dependent preview job. Image SBOM
generation records OS packages/native libraries, separately from the Python and
Node lock inventory. No blanket ignore-unfixed option is used. Image/kernel scans
require Linux CI and are not implied by passing local Windows tests.

Useful local commands, in the repository's activated environment:

```powershell
uv lock --check
uv pip check
ruff check .
bandit -r src -ll -ii
pip-audit --local
npm --prefix ui/page-reader audit
uv export --locked --all-groups --format cyclonedx1.5 --output-file .local/python-sbom.json
python scripts/supply_chain.py --python-sbom .local/python-sbom.json
python scripts/security_tools.py gitleaks git . --redact=100 --no-banner --log-opts=--all
```

`--stage` on the inventory command creates a **new** `.local/security/source`
snapshot for directory scanners. It refuses to reuse a directory so removed
files cannot linger in a scan. Use a new `--output` directory for another run.
Keep raw scanner reports local/restricted; CI publishes only dependency inventory
and SBOM JSON for 30 days. Even redacted reports may reveal internal paths.

The Python+Node CycloneDX 1.5 SBOM uses uv's locked Python graph plus Node
integrity hashes and dependency edges. It covers all lockfile platforms/groups,
not just installed runtime packages. License metadata screening reports packages
not installed on the current platform explicitly. The source SBOM does **not**
claim to inventory the OS, optional LibreOffice/Tesseract runtime, every PDFium
vendored library or a built desktop executable. Each distribution requires its
actual image/platform inventory, native notices, signature and scanner results.

## License screening and conditions

The metadata policy admits MIT variants, BSD variants, Apache-2.0, ISC, 0BSD and
PSF-2.0. Unknown/nonstandard expressions and unreviewed licenses fail the gate;
even an OR expression must contain only reviewed choices. Exact-version
metadata mappings for Colorama and HTTPX were checked against their bundled
BSD-3-Clause text. License files and their hashes are recorded in `licenses.json`.

MPL-2.0 (certifi/Hypothesis) and LGPL-3.0-only (psycopg and its binary wheel) are
conditional: preserve notices and applicable source/modification/relinking rights;
do not assume proprietary distribution or static bundling is automatically
compatible. The `pypdfium2==5.14.0` exception records a mixed native bundle,
whose installed distribution includes BSD/Apache/CC-BY and separate PDFium,
FreeType, ICU, JPEG, PNG and other vendor notices. Preserve **all** bundled
notices. A changed version/metadata requires another review; missing notice
files fails the exception. These screens do not replace review of native
distribution terms or the owner's eventual project-license choice.

Desktop builds already collect the installed distributions' license files,
Python/Tcl notices and project license status. PyInstaller's bootloader exception,
optional converter binaries, OS-specific dependencies and release packaging need
their own artifact review before public distribution. A passing hosted-source
license check is not that approval.

The platform CI job also screens its installed packaging dependencies. Exact
PyInstaller 6.22.0 and hooks-contrib 2026.9 metadata are conditional build-tool
exceptions, with bundled license files required. PyInstaller's `COPYING.txt`
contains a bootloader exception; the hooks distribution has mixed Apache/GPL
terms. Preserve those texts with artifacts and review modified/redistributed
build-tool code separately. The exceptions do not admit arbitrary GPL packages
or automatically license this application's source or every bundled library.

## Patch and disclosure procedure

1. Triage an advisory against the exact lock/image/runtime version, enabled path,
   exploit prerequisites and existing sandbox boundary. Do not dismiss a parser
   issue solely because workers are isolated. Assign an owner and urgency from
   the [incident severity table](runbooks/incidents.md); active exploitation or a
   trust-boundary bypass requires containment before release.
2. Obtain the fix from the authoritative maintainer. Update the narrow package
   pin and lock, review source/registry/hash and transitive changes, inspect
   licenses, and rebuild worker runtimes. Never disable TLS, isolation, integrity
   checks or approval enforcement to complete an upgrade.
3. Run a synthetic reproducer when safe, the relevant negative tests, full suite
   when changed behavior warrants it, dependency/static/secret/config/image gates,
   and native platform tests. Regenerate SBOMs and verify the distributable hash.
4. Release only through the existing authorized workflow after the release gates
   pass. If no safe fix exists, disable the affected capability and document the
   restriction. An exception needs a named reviewer, bounded scope, expiry and
   compensating control; do not silently suppress a finding.
5. For a secret, keep its value out of reports. Confirm whether it was functional,
   revoke/rotate with the real issuer, examine access scope and run the incident
   process. History removal alone is not revocation. Rewriting public history
   requires a separate reviewed coordination step; this work did not rewrite it.

CI checks happen on pushes/PRs. They are not continuous monitoring; an operator
must own advisory intake and regular reassessment before an external deployment.
Dependency source/hash validation detects substitution and tampering, not every
malicious change from an otherwise trusted maintainer.

References: [uv locked installs](https://docs.astral.sh/uv/concepts/projects/sync/),
[Gitleaks](https://github.com/gitleaks/gitleaks),
[Trivy filesystem and SBOM scanning](https://trivy.dev/docs/latest/target/filesystem/).
