# Stress corpus follow-up — October 28, 2026

This follows the [initial repair](stress-repair-2026-10-28.md), which left three
failed and nineteen blocked cases. Original fixture bytes and gold expectations
remain unchanged. Institutional access remains disabled.

## Product changes

- Requirement modifiers now apply to their own sentence or semicolon clause.
  Citations preserve source offsets, recognized date spans remain intact, and
  figure recommendations are distinguished from mandatory requirements.
- Integrity parsing recognizes fully enumerated prohibitions without turning
  them into a ban on a separately permitted activity. Unknown list entries stay
  conservative. Suffix wording such as "spelling and grammar only" permits only
  mechanical correction; negation, conditional permission, authority checks,
  disclosure, scope and downstream enforcement remain in place.
- Mixed provider/local integrity sources resolve each selected local document
  through current ownership and provenance before institutional classification.
  Local documents cannot acquire instructor authority or override a restriction.
- A grade group can explicitly declare `drop_basis: percentage` to drop the
  lowest exact score/possible-points ratios. The default `equal_points` still
  refuses unequal denominators. This does not implement Canvas retained-grade
  optimization. Never-drop exclusions remain enforced; zero denominators,
  drop-highest rules and required-score solving with drops remain unsupported.
  The additive field is in the published `independent-academic-1` JSON schemas.
- Repeated local DST times retain both possible UTC instants, with no selected
  deadline. Discussion post and reply dates can produce separate candidates.
  Candidates still require source applicability and assessment confirmation.
- Internal process scopes now include optional section and subject fields;
  exact-scope reconciliation rejects amendments for another section or subject.
  These fields do not grant authority and need no database schema migration.
- Local document reads preserve already extracted table cells and coordinates,
  with whole-table output budgets and explicit omissions. Table extraction is
  not visual interpretation. Study preparation preserves its wait-for-response
  action through the final output filter without releasing answer keys.

## Expanded execution and its limits

The explicit corpus harness now exercises active recall, scoped deadline facts,
disposable account deletion/export and backup restoration, and real PDF image
delivery. DE-01/02/03 use hash-bound passages and explicitly fictional provider
authority through the process reconciliation API; they do not establish a new
general prose parser or installed-client deadline adapter. OP-03 uses only a
disposable synthetic database and encrypted backup.

For VI-01/02, the Windows PDF renderer delivered an original-page PNG through
HTTP MCP. Codex inspected the actual pixels. The saved observation records the
PDF and PNG SHA-256 hashes; repeated runs require both hashes to match. This is
model observation of that specific synthetic image, not automatic backend
interpretation or acceptance of the installed personal client. Without the
observation file, these cases remain BLOCKED.

```powershell
.venv\Scripts\python.exe scripts/run_stress_repair.py --output .local/stress-followup-reproduction --visual-observations .local/stress-followup-visual-observation.json
.venv\Scripts\python.exe -m pytest -q -p canvas_bridge.compliance.pytest_plugin --compliance-results .local/stress-followup-reproduction-full.json
```

Use fresh output names. Per-case receipts record inputs, outputs, source hashes,
limits and case status. Encrypted study session capabilities are redacted from
receipts. Source fingerprints must remain unchanged during an acceptance run.

AI-19 requires genuine UI acknowledgment; no consent is manufactured. VI-08
requires supported original PPTX slide rendering and observed pixels; independent
rendering currently supports PDF only. OP-07 requires a separate disposable OS
installation and appropriate current/previous packages for deployment recovery.
These checks cannot be replaced by a unit-test assertion or changes to gold.

The [verification report](../evidence/sanitized-results/stress-followup-2026-10-28.md)
records final counts and separates local product results from installed checks.
Existing release, source-sharing, deletion, authorization and independent-review
gates remain in force. No production migration, approval, OAuth reconnection,
personal import, credential refresh, external write or publication is performed.
