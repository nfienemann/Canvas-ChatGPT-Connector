# Subprocessor Inventory review template

Status: **UNVERIFIED — deployment-specific review required.**

| Candidate role | Source implementation context | Actual entity / region / contract |
|---|---|---|
| Upstream LMS | Institution-configured authorized Canvas endpoint | UNVERIFIED; identify provider and institution arrangement |
| AI recipient | Requesting MCP client; content and workspace approval required | UNVERIFIED; identify actual plan, workspace and handling terms |
| Application identity | Configured OAuth issuer | UNVERIFIED; identify operator and approved issuer configuration |
| Hosting, database, backup | Operator-managed deployment; encrypted local storage paths | UNVERIFIED; list every actual service and region |
| Diagnostics/support | Minimal non-sensitive events intended | UNVERIFIED; inspect actual sinks and support access |

These are candidate roles, not a claim that any company is an appointed
subprocessor. The offline entry point does not contact an LMS or model API.

Review owner / date / source commit and artifact hash: UNVERIFIED.
Deployment, institution, jurisdiction and intended recipients: UNVERIFIED.

List each actual service and legal entity, role, regions, data categories, access, retention, contractual reference and approval. OSS libraries are dependencies, not automatically subprocessors.

Maintained implementation reference: `docs/data-flow-retention.md`. This reference is a starting point, not completed acceptance.

| Assertion or inventory item | Evidence ID and exact source | Verification performed | Residual gap / owner / due date |
|---|---|---|---|
| UNVERIFIED | UNVERIFIED | Not performed | Assign during review |

Decision and bounded scope: UNVERIFIED.
Re-review trigger: change of source, recipient, provider policy, deployment, data category, dependency, retention or trust boundary.
Store confidential attachments separately under authorized administrator access; include only non-sensitive evidence IDs here.
A completed technical review does not grant external authorization.
