# Private course-content governance repair

An explicit, default-off personal-mode grant binds owner-attested permission to
the existing signed sharing record, exact selected courses, registered ChatGPT
client, owner, issuer, and structured/text/visual channels. It does not assert
independently verified institutional correspondence or invent per-source reviews.
Canvas authorization, known restrictive classifications, source-version checks,
privacy filtering, and independent sharing policy remain enforced. Hosted mode,
other recipients, original downloads, and full-governance overrides are excluded.

A separate repair restores a missing legacy text digest only from the exact
authenticated, encrypted original review evidence. A changed extraction remains
subject to the current release policy.

Validation: 28 focused private-grant tests passed, including a native MCP contract
using synthetic workbook bytes and retained Canvas lock denials. Seven synthetic
review-binding repair cases passed. The existing environment-approval contract
passed after its test-only HTTP timeout was aligned with the workflow duration.
The full synthetic suite completed with **2,361 passed, 31 skipped, 2 failed,
1 error**. The unsuccessful cases were presentation fixture setup reporting
`GOVERNOR_UNAVAILABLE`, a missing figure render receipt, and an MCP HTTP timeout.
All three passed in an isolated rerun (**3 passed in 46.18 seconds**) without
additional code changes. This does not turn the full run into a clean pass.
Concurrent workspace changes and runtime contention remain validation limits.

Private live probes established native assignment content, native PDF text, and
one returned PNG successfully decoded from the plugin image block. A linked
handout remained denied by source authorization. These probes are not exhaustive
file coverage. A new complete inventory/read/render pass is in progress; the
private checkpoint and request identifiers are outside the repository.

The resumed native pass subsequently read all returned text windows and decoded
all five returned page images for one PDF. Its reader-reported partial extraction
remains partial. The runner now retains a fixed `READER_PARTIAL_COVERAGE` reason
and coverage enum without content. All **38 Node audit tests passed** after this
diagnostic-only change; no service permission behavior changed.

The next file's native rendering request encountered a transport failure without
a server request ID. The checkpoint retains decoded coverage and an explicit
transport hold. Discovery and full-file coverage remain unfinished; the audit is
not clean. Resume through the native tool after recovery, using the saved course,
file, and page continuations. Do not replace the plugin read with local source access.

The resumed sweep reached every selected course's discovery traversal and
decoded all returned images for a one-page PDF and an eleven-slide deck. The
deck retains the reader's partial-content classification. A transport failure on
one slide recovered through a bounded retry at the saved page; prior decoded
pages were preserved. Discovery gaps and unfinished reads still prevent a clean
audit.

A native extraction-status request then reproduced classification denial for
an otherwise authorized private file. The explicit private grant now covers
that metadata-only route, requiring source-version identity and structured
channel permission, without requiring already-extracted bytes. Text/image byte
identity requirements are unchanged. A synthetic MCP contract also exposed a
Canvas status denial being replaced by a classification error; the MCP status
route now passes the original denial through the existing safe-error boundary.
The internal status helper retains its existing inaccessible-state result.
**79 focused tests passed**, including cold/warm status, real MCP framing,
revocation/lock denials, file reading, egress contracts and scope refresh.
Lint and formatting checks passed. These changes postdate the full-suite result
above; native retesting remains separately tracked in the private audit.

Native retesting now establishes metadata availability for an unindexed file,
a successful first reader response, indexed status afterward, and a repeated
reader response with the same content hash and chunk ID. These are first-window
cache probes, not complete coverage of that deck. The denied handout's native
status now retains `RESOURCE_PERMISSION_DENIED`. The strengthened synthetic
MCP case passed and verifies exactly one parser invocation across cold/warm
reads, followed by retained Canvas lock denial.

The runner supports a text-first ordering while keeping PDFs/decks pending until
all required images decode. Its default complete read behavior is unchanged.
All **39 Node audit tests passed**, including proof that deferring visual work
cannot yield a fully-read file or clean report.

A bounded native-image decoder now has ten synthetic tests covering RGB/RGBA,
every PNG row filter, full pixel output, CRC and Adler corruption, truncation,
unsupported metadata, oversized dimensions and multiple image blocks. All
**49 combined Node audit/decoder tests passed**. Six synthetic cases also passed
inside the tool runtime without browser text codecs. The future visual adapter
retains the existing Pillow fallback; live-image acceptance remains a separate
separate check. This optimization does not fetch original documents or change
Canvas authorization, egress policy, or audit coverage requirements.

That live check subsequently passed on a native returned PNG: both the bounded
in-host decoder and Pillow decoded it, and the returned content hash matched
the audited file. The private probe records the native request ID. This was a
repeat validation of an already covered page and added no coverage. Future
visual batches may use the validated fast path with Pillow fallback.

Separate text and visual checkpoints permit a bounded overlapping visual sweep
over already text-complete files. The merge keeps current source identities,
inventory gaps, reader partial flags and denials intact; foreign connections,
changed identities and invalid page evidence are rejected. **57 combined Node
tests passed**, and a synthetic merge/reconciliation also passed in the actual
tool runtime. Live branch results remain separate until both workers stop and
their identities can be reconciled; they are not duplicate additional files.

Compact checkpoint transport replaces repeated full-state tool payloads with
metadata deltas. Revision/preimage checks prevent stale writers from replacing
newer state, and repeated acknowledgements cannot duplicate operations. All
**63 combined Node tests passed**, including the atomic filesystem adapter;
synthetic host execution passed separately. Both native workers were explicitly
stopped before their stable checkpoints were reconciled and backed up privately.
The matching visual evidence merged without rejections, and native work resumed
with compact saves. These changes affect audit persistence only.

A separate inventory regression reproduced an unknown-visibility row being
filtered out while its branch was reported complete. Missing or malformed
current-user visibility now marks that branch partial with
`UNKNOWN_AUTHORIZATION_FAILURE`; explicit denials remain filtered and no
permission check is relaxed. **27 inventory tests passed**, followed by a
**passing synthetic public MCP regression** confirming that the gap survives
the privacy boundary without releasing the filtered file's metadata. Deployment
and a fresh native inventory pass for this change remain pending while the
existing readers/renderers continue.

Before deployment, an integration regression caught inventory diagnostics
rewriting an already-saved request event. Diagnostics now append separate
annotation records. **64 combined Node tests passed**, and compact discovery
also passed in the actual tool runtime. The workers were then stopped and their
checkpoints reconciled without identity rejections. The service was restarted;
its shell wrapper needed separate cleanup after the helper exited, but the
new application process subsequently served fresh authenticated native inventory
requests with ChatGPT as recipient. The complete refreshed inventory pass is
in progress alongside resumed page rendering; this is not final audit acceptance.

A subsequent shared transport timeout held both workers. A native connection
probe succeeded, followed by a bounded retry of the saved PPTX slide: the native
reader returned the slide and its image decoded successfully. Discovery then
resumed from its saved continuation. Checkpoint reconciliation now retains the
higher retry counter from either worker, preventing a merge from resetting the
retry budget. **65 combined Node regression tests passed**. Access denials were
not cleared as part of transport recovery.

The audit now uses the dedicated public standard-resolution slide reader for
known PPTX sources. **69 combined Node tests passed**, covering routing, denial
preservation, slide identity and bounded numeric timing diagnostics. A native
standard-resolution retry returned and decoded a slide that previously exceeded
the high-resolution image limit, with ChatGPT as recipient. That request took
about 118 seconds; a separate serial high-resolution request had timed out at
120 seconds. This establishes a supported recovery for one image-limit failure,
not full deck coverage or resolution of the transport delays. The remaining
inventory and reader audit is unfinished.

A resumed inventory request encountered `AUTHORIZATION_BUSY` while the standard
slide worker continued. The connection guard intentionally serializes reads and
membership refreshes and limits the wait to 60 seconds. The inventory cursor
was preserved; subsequent native dispatch will be serial for this connection.
This is a recorded contention/recovery case, not a missing Canvas permission
and not a reason to bypass the guard. The standard worker has since reached
20 decoded slides in the current 54-slide deck; full coverage remains pending.

A synthetic regression reproduced a course-list freshness gap: `ok` plus complete
pagination could previously mark an unrefreshed enumeration complete. The audit
now requires live/synthetic freshness and reflects incomplete course enumeration
in each reported inventory row. Missing, cached and not-refreshed cases fail
closed; fresh live and synthetic cases remain accepted. **74 combined Node tests
passed**. The running native pass had already returned live course enumeration;
the correction changes reporting requirements without discarding its evidence.

The refreshed traversal reached all five selected courses. Two inventories were
complete; three retained explicit permission-denied gaps. The handoff to text
reading then exposed a compact-checkpoint defect: a final no-change flush could
republish an old revision, correctly rejected by the next writer. A regression
reproduced that conflict. `flush()` now retains the acknowledged revision after
successful saves; failed saves cannot advance it. **76 combined Node tests
passed**, and the handoff passed in the actual tool runtime. The authoritative
checkpoint retained completed discovery. The uncheckpointed native read remains
uncredited and is scheduled for a bounded retry through the plugin.

That bounded native retry subsequently succeeded and its complete text window
was saved under the new checkpoint revision. The PDF remains pending until its
page images are verified; the recovered text read is not full-file acceptance.

The first ten-file native text batch subsequently completed, and the next batch
committed a live reader response under a new checkpoint revision without a stale
writer conflict. This verifies the repaired handoff with native calls as well as
synthetic fixtures. Remaining text continuations and visual checks still prevent
final audit acceptance.

A later native response exposed a reporting defect: a content-free safe error
retained `partial_data`, and the audit classified it as partial reading despite
having no coverage. Two synthetic cases reproduced the issue, including a later
error after actual prior coverage. The reader now preserves the safe reason code
and prior source identity, counts a first error as failed, and retains partial
only when prior coverage exists. **78 combined Node tests passed**. The affected
native file is queued for one supported retry after the active writer stops;
this reporting repair does not change service authorization or release policy.
