# Private text-review preparation — November 3, 2026

Owner requested actual course-document and assignment-instruction access. Live
file discovery remained blocked with EGRESS_CLASSIFICATION_UNKNOWN; the sampled
assignment-details request required fresh scope. No document/instruction text
was released through the installed connector in these tests.

Added signed exact-source/private-text review support and an operator-local
review helper outside the repository. It requires interactive inspection of
actual sanitized extracted text, an explicit rights/privacy attestation and a
written supporting reference. It does not infer a review from parser success,
file names, source text, model claims or a broad request. No real source reviews
were signed. No recipient retention/training/workspace facts were fabricated.

An unrelated private-library migration b39f81ca26de appeared during this work;
the live database remains a28e70b915cd. Startup preflight correctly blocked new
operator sessions. User requested preparation of upgrade steps. A private
interactive wrapper was prepared and PowerShell syntax validated. It uses the
supported target-bound backup-and-apply path, protects and verifies a local key
copy, preserves interactive confirmations and restarts only after success. It
has not been run. A local backup is not an independent physical recovery copy;
archive listing is not a restore rehearsal.

Initial focused tests: 89 passed. A later rerun encountered 16 fixture setup
errors from an unrelated indentation error in library/reading.py. Corrected the
misplaced account revision increment without changing its transaction semantics;
subsequent private-review and approval checks: 78 passed. Changed-source Ruff
checks passed. The private review helper compiled. A first packet preparation
produced no reviewable packet; subsequent attempts are blocked by the new schema
requirement. No completed live text acceptance or full-suite pass is claimed.


Upgrade recovery: listener enumeration returned empty while the verified Bridge
Python process tree retained two PostgreSQL shared advisory locks. The stop helper
now verifies the recorded parent/child executable paths, command lines and local
resource metadata before using that process tree as a fallback. Synthetic Windows
acceptance: 4 passed, including mismatch refusal. Used the verified fallback to
stop Bridge only; acquired the exclusive database lock with no other sessions.
Confirmed revision remains a28e70b915cd and no preflight blockers, then archived the
failed maintenance marker under an explicit resolved filename while holding the
exclusive lock. PostgreSQL was left running. No migration was applied; interactive
backup/maintenance/apply confirmations remain in force.


Post-upgrade follow-up: supported status reports current=head=b39f81ca26de,
no pending migration, no blockers, no maintenance hold and verified last upgrade.
Prepared and decrypted/validated an encrypted operator-local review packet with
one actual course document and one actual assignment-instruction source. A
per-owner request-limit denial on assignment preparation cleared after waiting;
assignment-only preparation preserved the existing document packet. No source
text was emitted in preparation diagnostics. No real review was signed.
Private Python helper compiled and PowerShell review launcher syntax validated.
Installed course listing remained live and confirmed all five selected. Two
bounded document-read tests returned STALE_SCOPE_SNAPSHOT, including after course
refresh, so live reviewed-text delivery remains unverified and needs follow-up.


Human operator completed local rights/privacy text review for two exact source
versions. Both signed reviews validate. Fixed review-helper output-channel mapping:
file responses are classified as text even when carried in structured MCP results.
The explicit human text-only approval was mapped to text channels for the same
source/hash and supporting references; no visual/original rights were added.
22 focused regressions passed and Ruff checks passed. Fresh local guarded reads
and egress releases passed for the reviewed assignment and a bounded document
text window (ok / ALLOW_REDACTED / nonempty content). Content is excluded here.
Installed-client attempts still returned STALE_SCOPE_SNAPSHOT. Automatic approval
review rejected the service stop/restart command with blocked by policy; no
restart was executed. Prepared and syntax-checked an operator restart helper,
including inherited-environment isolation/restoration, for user execution. Local
success does not establish installed-client text delivery.


STALE_SCOPE_SNAPSHOT investigation found rate-limit masking: the existing 120/hour
local owner allowance was exhausted; incomplete membership refresh invalidated
the lease, and integrity preflight then exposed STALE_SCOPE_SNAPSHOT. User explicitly
requested integer-maximum local limits. Their private configuration now selects
2,147,483,647 for minute/hour/day and nominal monthly ceilings; policy updates
preserve durable consumption. Other deployment defaults and technical/concurrency,
task, source and privacy gates remain. Added fresh membership preflight and
explicit incomplete-refresh reason propagation. Reduced integrity-only assignment
detail fan-out to the requested assessment and document discovery to policy hints
plus existing explicit links; unrelated workflows are unchanged.

Validation: 33 focused tests passed; 83 broader integrity/governor/integration
tests passed, with one disposable PostgreSQL environment skip. Both actual reviewed
sources passed the FULL local tool path including authorize_tool, before_tool,
reader, request fence and egress: ok, ALLOW_REDACTED, nonempty content. No source
text is included here. Installed-client verification awaits operator restart; no
installed success or full-suite pass is claimed at this point.


After the operator's confirmed restart, installed connector retests returned ok
for BOTH human-reviewed sources: live assignment details and the bounded document
text window. Both passed privacy filtering and ALLOW_REDACTED release. Neither
returned STALE_SCOPE_SNAPSHOT. The assignment's linked file remained separately
denied; this does not establish its contents were read. The PDF text sample was
publisher/footer text, so readable full-article body extraction remains unverified.
Source names, content, identifiers and real academic states are excluded here.
Private maximum owner minute/hour/day and nominal monthly limits were independently
confirmed at 2,147,483,647 without resetting accounting. This closes the tested
installed-client stale-snapshot regression, not unrestricted coursework access or
universal document extraction/visual interpretation.
