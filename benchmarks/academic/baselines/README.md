# Stable benchmark baselines

No previous stable benchmark result exists at introduction. The laboratory reports
that absence explicitly. A current run is not automatically relabeled as a previous
stable version, and a self-comparison is not improvement evidence.

After a release owner reviews a real full-corpus run, preserve its `report.json`
as `stable.json` here. Review the recorded code fingerprint, exact corpus hash,
all failed/pending categories, source-stability flag and independent review
records. Keep the original execution artifact and record the approval/reference
in the release review. Do not edit recorded answers or metrics to make a baseline
pass. Commit baseline promotion as an explicit reviewable change.

The full CI workflow compares against this file when present. Release/tag runs
require it; a missing file fails the release gate. Comparisons require the same
corpus and task-set hashes. For a new corpus version, rerun both implementations
on that corpus before making paired claims; don't subtract incomparable scores.

Keep model/alternative-tool results separate. They require actual version,
configuration, run and input-export receipts. Alternative tools additionally
require installation and authorization evidence. The importer records those as
external attestations, not an assertion that this agent installed or verified a
competitor. Never include private records, credentials or raw operator logs here.
