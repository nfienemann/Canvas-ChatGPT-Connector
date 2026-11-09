# Private reader download task allowance

The private-development governor previously allowed six download HTTP attempts
per tool call. Each redirect consumes an attempt. A policy-document preflight
and a requested document can require eight attempts together when both use three
redirects. This can deny the first reading call of a day; it is not evidence of
a daily limit or timeout.

The private-development policy now permits 24 download HTTP attempts per call,
allowing six four-hop transfers within the existing overall task limits. Every
hop remains accounted. Overall request, unit, byte, time, owner and concurrency
limits and authorization remain enforced. Production defaults are unchanged.
No schema migration or usage-history reset is required.

Validation: the focused governor, integration, course-file and personal-development
run reported 142 passed, one failed, one skipped. The new stress fixture initially
hit the independent default owner-per-minute limit. After explicitly configuring
its synthetic owner limit, all 16 personal-development tests passed. The skip
requires a disposable PostgreSQL database. Ruff checks passed. No full-suite run
was performed for this policy-only change.

The regression exercises redirected policy/reading transfers, exhaustion of the
new cap, separate budgets for fresh calls, and retained accounting across policy
updates. Fixtures contain no real coursework.

Deployment remains incomplete: automatic approval review rejected the private
service restart with "blocked by policy". No restart or live verification of the
updated policy was completed in this task.

Follow-up: after the operator reported restarting the service, the same native
plugin file-read request returned `ok` with live freshness and usable first-page
text. The previous task-budget failure did not recur. This verifies the affected
read path after restart, not full-document visual review or general release
readiness. No academic content or private identifiers are included here.
