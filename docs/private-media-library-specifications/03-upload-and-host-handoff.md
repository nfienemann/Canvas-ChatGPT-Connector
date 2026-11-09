# Upload and host handoff

## Baseline device upload

The user opens Add files from a Bridge response or the signed-in settings surface. The page shows selected files, destination collection, exact byte limits, retention choice and separate processing/sharing controls. Default persistence for a newly selected library upload is until user deletion; the button explicitly says Save to private library. Sharing is unchecked unless an existing valid grant covers the concrete selection and requested use. No LMS connection or course selection is required.

1. The browser authenticates to Bridge. A server-issued intake binds the owner, session, selected manifest, retention choice, purpose, consent version and idempotency key. The request cannot choose an owner.
2. Reserve the sum of selected original bytes and item slots atomically. For an unknown host file size, reserve its displayed server-approved maximum; reconcile to actual size at publication. Client maxima cannot exceed effective server limits. Reject over-quota items before transfer, with per-file outcomes. Do not evict old files automatically.
3. Stream each original to a private quarantine object. A visible progress indicator counts transferred bytes, not extracted pages. Validate actual byte counts; client size, extension, MIME and digest are claims to verify.
4. Finalization verifies checksum, type, structural limits, scanner result and current consent/session generation. Publish an immutable version only after all required intake checks succeed. Extraction runs separately after publication when processing is permitted.
5. Return a durable receipt with item/version IDs, byte count, original checksum, retention, storage state, processing state, coverage, warnings and next action. The chat gets only recipient-permitted metadata.
6. Retry resumes the same intake or reads its receipt. A lost completion response must not create a second version. Cancel aborts incomplete items and releases reservations; already published items remain, with an explicit Delete action.

For the first slice, sequential chunks use an upload offset and expected offset check. Default chunks are 8 MiB, with a smaller final chunk. A request at the wrong offset returns the authoritative offset without appending. Resending an already accepted chunk with the same checksum returns its receipt; different bytes at that offset return conflict. No multipart parallelism is required until its ordering/accounting tests pass.

Filename collisions do not overwrite. Display separate items or offer Replace with an explicit target version. Batch failures do not erase successful files. Unsafe archive structure rejects the entire archive before publishing children; safe archives with unsupported members report those members as excluded. ZIP contents still need the same per-item processing/sharing decisions, with a batch grant allowed after showing the manifest.

## Explicit host transfer

OpenAI's documented integration uses top-level `openai/fileParams` inputs with `download_url` and `file_id`; optional declared fields are `mime_type` and `file_name`. Optional widget helpers are `selectFiles()`, `uploadFile()` and `getFileDownloadUrl()`. Feature-detect them and test the selected host. [OpenAI plugin reference](https://developers.openai.com/plugins/reference#file-apis).

The proposed descriptor is `contracts/submit-library-files.tool.json`. It is a Bridge mutation and is not registered in a read-only MCP deployment. It accepts an existing authorized intake, host file references and an idempotency key. The intake is created by a genuine authenticated selection/save action, or an equivalently verified host action if that mechanism is established. A model-created intake ID or consent boolean is insufficient.

Use two distinct paths:

- **New device file in a supported widget:** show Bridge retention and sharing choices, obtain the concrete user selection, then transfer through the supported host adapter or directly through the authenticated Bridge byte-upload service if the tested widget CSP/auth/CORS permits it.
- **Existing host file:** let the user select the exact file through the supported picker or file-input action. Explain that Save to Bridge creates a separate retained copy. Create/bind the intake and acquire those exact bytes. Host storage retention and Bridge retention are independent.

Selection identifiers must match the intake's expected file references where the host supplies stable references. Verify size/digest against the concrete selection manifest when available. When identity cannot be adequately bound through a host, use the authenticated browser transfer path. Do not assume a widget can read a transcript's attachments, scrape the conversation, access a host filesystem path or enumerate every file in a user's host library.

## Temporary URL acquisition boundary

The host adapter is a narrow private ingress client. Its signed URL is a short-lived transfer capability, never a persistent source locator or ownership proof. It MUST:

- Require an authenticated principal, a current owner-bound intake, the configured exact host adapter and a supported selected-file shape.
- Accept only HTTPS and the reviewed host delivery domains/path policy for that adapter. Do not invent permissive wildcard domains. Missing deployment allowlists disable the adapter while leaving browser uploads usable.
- Block user-info URLs, IP literals, local/private/link-local/reserved destinations, metadata services and DNS rebinding. Revalidate each redirect and resolved address, pin the validated destination for connection, limit redirects to two and never forward Bridge/Canvas cookies or authorization headers.
- Stream to quarantine with connection/read/total timeouts and actual-byte caps. Reject a reported size above quota; enforce the reservation even if the server omits or lies about Content-Length. Validate type from bytes.
- Never echo or log the URL; keep it transient in the fetch operation, not normal job payloads. Redact file references from exception tracing. Do not store a signed URL as the durable library source.
- On expiry, return `transfer_expired` with the existing intake state. Obtain a newly authorized reference through the host or browser; do not search private host APIs. Once publication succeeds, later host URL expiry must not affect Bridge reads.

Host fields alone do not prove a file's institutional origin or rights. Store the acquisition channel as `host_file_handoff` and keep user attestation and known source lineage separate. Never mark content as institutionally approved because it arrived through a trusted chat host.

## Capability negotiation and fallback

`get_library_status` reports `device_upload`, `host_file_inputs`, `host_file_picker`, `original_download`, `inline_images` and `audio_video` with `supported`, `unsupported`, `unverified` or `temporarily_unavailable`. Server configuration defines approved adapters; widget feature detection reports availability only. Neither proves a successful transfer or model visibility.

When file handoff is unavailable: “This file is attached to the chat but is not saved in Bridge. Open Add files, choose it on your device, and save it to your private library.” Provide the server-issued settings route, preserving return context without embedding bearer credentials in a link. If an upload is still pending, say so and poll bounded status; do not claim access from a filename.

Every flow needs keyboard navigation, labeled controls, screen-reader progress/status, focus on errors, mobile file-selection acceptance and a text equivalent to the inline card. Do not navigate away from an unsaved selection without preserving it or a clear cancellation result.
