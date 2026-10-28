# Institution administrator guide

Canvas Bridge is a student-directed, Canvas-read-only MCP service under local
development. Rowan is a candidate mentioned in the specification, not a supported
or approved institution. There has been no institutional application or outreach.

Before a pilot, approve the institution registry entry, canonical HTTPS origin,
student OAuth developer key, enabled scopes, exact callback and privacy
arrangements. The registry accepts only operator-reviewed institutions. A URL
entered by a student never grants arbitrary outbound access.

Review [the scope matrix](capability-scope-matrix.md). The academic adapter has no
coursework-submission write, roster, grade-editing, quiz-attempt or administration route. Powerful
upstream credentials do not enable these features. Mixed staff/student course
roles currently fail closed.

Canvas callbacks use the deployment resource base followed by
`/settings/canvas/callback/` and the SHA-256 digest of the institution ID, a NUL
separator and canonical origin. Register that exact institution-specific URI.
Secrets are supplied through private environment references, not registry values.
Review [OAuth capabilities and least privilege](identity-oauth-hardening.md)
before configuring PKCE, refresh rotation, scopes or enabled workflows. Missing
protocol evidence disables OAuth linking. These settings do not replace the
independently established and signed approvals enforced by the policy gateway.

The connector verifies `/users/self/profile` server-side, then binds the token
to that institutional user and connector principal. Other students must use
their own OAuth grants. Account emails are not used to merge identities.

Review recipients (Canvas, the service, authenticated ChatGPT tool results),
region, retained fields, incident ownership, logs, backups, deletion fencing and
the actual ChatGPT workspace data controls before real student data is processed.
OAuth does not establish all legal/privacy requirements, and this project does
not claim automatic FERPA certification.

Emergency controls: disable the institution registry entry, stop API/worker
processes, and revoke affected grants as appropriate. A provider outage must not
be reported as successful revocation. Define a support path before a pilot.
