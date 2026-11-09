# Course content portability

Open **Settings → Add course materials** with independent review workflows enabled. Choose the term, course and purpose before importing a ZIP. Treat a packet covering several courses as separate course selections. A filename or folder label cannot establish institutional authority.

## Import and recover materials

The packet preview shows one outcome for each selected member. A recognized move keeps the document and work identities and adds the original path to location history. A source revision retains the earlier bytes, hash, locator and acquisition time within the original retention window. Affected reviews become stale, including their dependent work. Inspect the earlier personal progress in the review form and explicitly choose the previously reviewed activity when recording revised requirements.

Choose a candidate for an ambiguous match and review the updated preview. A conflicting mapping stays pending. A packet can contain 100 archive entries, up to 20 supported documents, at most 10 MB per document and 50 MB compressed. The existing expansion and per-format processing limits also apply. Temporary storage holds up to 20 documents per owner. The importer checks normalized archive paths and retains accepted logical paths up to 2,048 characters. It never uses the member path as a filesystem destination.

Enter expected logical paths, one per line, to track missing materials. An authenticated programmatic caller of the same settings route may also supply an expected SHA-256 for a path. An omitted file remains usable while the retained source is eligible. A wrong recovery hash stays in review. A recovered quotation retains the identity of the document that contains it. Deletion invalidates dependent state and installs scoped hash and binding fences for 91 days. An older workspace export expires within 30 days.

## Export and restore

Choose **Export or restore a course workspace**, choose the course, then select individual documents, process records and optional personal preferences. Include original bytes explicitly if needed. The download contains a bounded `course-workspace-1` manifest with an embedded `academic-process-export-1` selection. Source and record dependencies, original expiry, historical revisions, byte hashes, sizes, omissions and reference-only payloads travel with the selection. Store the downloaded file privately.

Select the bundle in the destination settings. Review each create, reuse, replacement, unresolved dependency, blocked source and historical plan. An existing edit requires a separate replacement choice and fresh preview. Reselect the exact file to confirm. Eligible records and their resolved parents, documents and preferences commit in one transaction. The receipt distinguishes a complete selection from a partial restore. A retry with the same confirmation and operation key returns the original receipt.

| Selection | Destination behavior |
| --- | --- |
| Independently owned source | Restore eligible original bytes or match an independently acquired current binding. Filtered originals can travel as references. The preview shows the exact runtime ID map. |
| Reviewed assignments and personal progress | Restore the existing review schema, work keys, citations and declaration basis. The destination uses its own storage revisions. Typed review citations can be remapped to a new document ID. A nested structure without a verified mapping stays unresolved. |
| Dependent study history and personal preferences | Restore eligible dependency-closed records and explicitly selected independent preferences. The shorter applicable expiry controls use. |
| Saved plans and calendar references | Retain the exported historical plan in the bundle. Run planning again with current sources, time and availability. A current event marker and provider version govern any later calendar proposal. |
| Local and Canvas identity association | Use the existing academic-process identity preview and confirmation, with `associate_local_course` enabled. Both adapter scopes, an explicit course code, compatible term and entity kind, and independently authorized sources are required. For an assignment, select an existing reviewed local work key and the actual Canvas work ID. A read projects one confirmed parent and its two dated assertions. A conflicting date holds the calendar proposal for review. Removing the link restores the separate inventory. |

Mixed-origin export uses the existing institutional user-download policy and privacy filter. A permitted link exports its public representation and local version metadata. Other institutional state, raw LMS payloads and unresolvable links receive an explicit omission or blocked outcome. Restored local documents and study records start with sharing disabled in a paired destination. Renewing consent uses the current source and recipient policies.

## Trusted source continuity

The signed-in issuer and subject determine the owner. The destination checks the digest against an independently retained issuance receipt, checks the principal generation and consults current source and deletion state again at commit. A matching owner, correct ZIP checksum, or copied vault key alone cannot establish continuity.

The default authority is the current store. A separately initialized destination can pair with an existing authoritative SQLite installation by setting `BRIDGE_PORTABILITY_ORIGIN_SQLITE` to its **live database** in trusted operator configuration. The destination must already have the corresponding database encryption setup. The origin opens read-only with SQLite rollback-journal mode `DELETE`. Its shared read transaction spans the destination commit. Configure an authoritative store whose deletion history is current. A backup or file supplied by the importing student is unsuitable. Missing authority, incompatible storage, expired evidence or a different generation blocks restoration.

Separate PostgreSQL installations, independent cloud deployments and transfers between different issuer/subject pairs have no paired-authority adapter in this version. The existing operator backup/recovery flow remains separate from a student workspace export.

[Executed acceptance and evidence](../evidence/sanitized-results/course-content-portability.md)
