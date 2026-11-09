# Course-file retrieval after an endpoint denial

In bounded mode, `list_course_files` accepts an optional `filename`. Matching ignores case, separators and an optional supported extension. Use the returned `file_id` with `read_course_file`. A name can match multiple files. A filtered or partial inventory cannot establish that a missing file is absent.

## What Bridge checks

* Bridge verifies the connection owner, current selected course, institution configuration, and the permission for each specific API route. Content release still goes through academic-integrity, sharing and privacy checks.
* A denied course-file list can coexist with successful module items, individual folders, assignment links or course-qualified file metadata. In a name search, Bridge can consult up to 200 recent owned course index entries and prioritize eight matching references. It verifies those references against Canvas before counting them as fresh.
* Folder recovery verifies the folder's course binding before using the folder-files endpoint. Bounded recovery spends at most four folder pages and 24 additional Canvas HTTP attempts after an incomplete or unmatched named listing, within the existing overall deadline and governor. Resumable mode supports continuation across additional branches and pages.
* Assignment discovery uses authorized attachment IDs and same-origin file anchors. It requests assignment metadata without the submission expansion. A module item, attachment ID or prior index entry supplies a candidate for lookup. Byte retrieval separately requires current file metadata and explicit student visibility. Hidden, locked and explicitly unpublished files are withheld.
* The process keeps at most 256 route observations with a 20-second lifetime. Keys distinguish owner, institution, connection, credential, scope epoch and exact route/page. A recent verified inventory 403 can suppress an identical request. Successful observations never substitute for authorization. File content and file-object permissions are not cached by this mechanism.
* Expiry-based credential refresh, provider cooldowns and bounded transient retries remain under the existing Canvas client and transaction governor. A denied download can renew its metadata once. Only a changed, reauthorized download URL qualifies for a second transfer attempt.

## Reading the result

A partial inventory includes `data.inventory_recovery` with its request ID, authorized course reference, retrieval methods, bounded failure details, verified-file count and coverage. Up to 16 failure details are returned, with a truncation indicator. Folder and object identifiers appear as opaque Bridge references when appropriate. Historical name hints that failed verification do not disclose the stored file identifier in the recovery report. `document_content_included=false` distinguishes discovery from delivery. A denied tool call carries its reviewed cause, method evidence, delivery state and request ID under `data.diagnostic`. Unverified source identifiers are withheld from the public error envelope and operator logs.

| Evidence | Interpretation and next action |
|---|---|
| `RESOURCE_PERMISSION_DENIED` with HTTP 403 and `origin=canvas_api` | Canvas rejected that GET. Check the student's resource visibility and the developer key and granted scope for that exact endpoint. |
| `UPSTREAM_SCOPE_INSUFFICIENT` | Canvas supplied an explicit Bearer insufficient-scope challenge. Have the operator compare the approved endpoint scope with the effective grant. |
| `MISSING_RESOURCE_CAPABILITY` without upstream status | Bridge's configured route or capability check stopped the operation locally. Inspect the connector configuration. |
| `RESOURCE_UNAVAILABLE` with 404 | Check the course-qualified reference and publication state. The response alone cannot distinguish absence from concealed access. |
| `UPSTREAM_AUTH_EXPIRED` | Follow secure Canvas connection recovery for a locally observed expiry. |
| `UPSTREAM_CREDENTIAL_REJECTED` | Canvas explicitly rejected the credential. Follow the configured secure Canvas recovery flow or contact its operator. |
| `UPSTREAM_THROTTLED`, 429 or a provider cooldown | Honor the supplied delay before resuming. A recognized Canvas throttle-shaped 403 is handled by the same governor. |
| Restricted source or egress decision | Follow the indicated review. Another discovery route cannot authorize release. |

A bare 403 cannot identify a hidden Files navigation item, an unpublished file, a course restriction or a missing OAuth scope. Compare independent endpoint results and, when necessary, the student view and Canvas administrator configuration. The Files API documents distinct course, folder and individual-file routes. The OAuth bearer specification defines the explicit insufficient-scope signal. [Canvas Files API](https://canvas.instructure.com/doc/api/files.html) · [RFC 6750 §3.1](https://www.rfc-editor.org/rfc/rfc6750#section-3.1)
