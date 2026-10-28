# Access Control Matrix review template

Status: **UNVERIFIED — deployment-specific review required.**

| Role | Implemented boundary to verify | Authority it does not receive |
|---|---|---|
| Authenticated application user | Own identity, institution, connection and selected courses | Another user's resources or vendor/institution approval |
| Model through MCP | Individually exposed bounded tools and deterministic policy checks | Approval mutation, arbitrary HTTP/SQL, Canvas writes or unrestricted deletion |
| Authorized approval administrator | Existing signed approval and protected evidence management | Automatic confirmation that an external organization granted permission |
| Document worker | Bounded bytes in a scoped isolated job directory | Service credentials, unrestricted host files or external network access |
| Local console owner | Explicitly supplied permitted bytes, local recipient only | Institutional approval or external-sharing permission from ownership attestation |
| Release reviewer | Source-bound technical evidence and documented sign-offs | Authority belonging to providers, institutions or platform administrators |

Review owner / date / source commit and artifact hash: UNVERIFIED.
Deployment, institution, jurisdiction and intended recipients: UNVERIFIED.

Map user/admin/worker/model roles to resources, read/write operations, institution, course, purpose and recipient restrictions.

Maintained implementation reference: `docs/capability-scope-matrix.md`. This reference is a starting point, not completed acceptance.

| Assertion or inventory item | Evidence ID and exact source | Verification performed | Residual gap / owner / due date |
|---|---|---|---|
| UNVERIFIED | UNVERIFIED | Not performed | Assign during review |

Decision and bounded scope: UNVERIFIED.
Re-review trigger: change of source, recipient, provider policy, deployment, data category, dependency, retention or trust boundary.
Store confidential attachments separately under authorized administrator access; include only non-sensitive evidence IDs here.
A completed technical review does not grant external authorization.
