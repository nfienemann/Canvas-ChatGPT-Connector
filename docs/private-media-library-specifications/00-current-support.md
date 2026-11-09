# Current private library support

Assessed October 29, 2026, America/New_York. Repository base commit: `5bd086356e730b01b5a9f1be9de106446ef049c6`. The checkout contains substantial pre-existing tracked and untracked changes, including usefulness features. Findings describe inspected working-tree code, not just that commit or a deployed release. Source hashes in `evidence/source-inventory.json` preserve the inspected state.

## What exists and what is missing

| Capability | Observed support | Evidence and boundary |
|---|---|---|
| Account-owned independent documents | Implemented in repository | `IndependentResource` stores owner, version hash, encrypted provenance/content and expiry; `independent.py` enforces ownership and source permissions. |
| Use without an LMS connection | Implemented contract and exposed tools | Independent readers and workflows consume the authenticated Bridge owner. No active Canvas connection is required by their contract. No source workflow was run during this assessment. |
| Upload from a device | Authenticated settings routes | `/settings/documents` and `/settings/documents/import`; explicit ownership, processing and sharing choices; CSRF and bounded bytes. |
| Document types | PDF, DOCX, PPTX, XLSX, UTF-8 TXT and Markdown | Original bytes and extracted representation are stored. This is not a generic image/audio/video importer. |
| Existing limits | 20 stored documents per owner; expiry at most 24 hours | `independent.py`; `independent_retention_hours` defaults to 24 and cannot exceed 24. Source-dependent continuity can end at source expiry. |
| Single-document size | 10,000,000 bytes; PPTX 25,000,000 bytes | `document_policy.local_import_limit`; do not confuse the separate 32 MiB PPTX parser source ceiling with the upload limit. |
| Batch and ZIP import | Additional implementation, disabled by default | `/settings/materials`, `usefulness/imports.py`, `usefulness_features_enabled=false`. 10 MB per member/document, 50 MB ZIP, 100 entries, 200 MB declared expanded total, 50:1 ratio, at most 20 accepted documents. Nested/encrypted archives and unsafe paths are rejected. |
| Cited reading and search | Exposed installed tools and repository code | Installed `list_local_documents`, `get_local_document_status`, `read_local_document`, `search_local_documents`, `prepare_local_study_materials`. Installed search description is single-document; newer checkout adds bounded multi-document/conceptual lexical search. Deployment parity is unverified. |
| Visual reading | Separate permission and capability | Installed renderer description says PDF. Checkout implements PDF plus configured PPTX conversion. Actual pixels, host delivery and model inspection were not tested here. |
| Academic use | Independent workflow exposed | Planning, assessment evidence, requirements, grade scenarios, deadline reconciliation, consistency and calendar proposals. Permission and supported structured inputs still matter. |
| Chat attachment ingestion | Missing from installed tool surface | No import/upload tool was exposed. `list_local_documents` explicitly says chat attachments are not automatically transferred. Repository upload paths are browser driven. |
| Durable library and originals retrieval | Missing end-to-end capability | Original bytes exist in short-lived encrypted rows. There is no exposed local-library original-download tool, durable object store, long-term versions, general media catalogue or user storage quota contract. |
| Backups | Independent imports excluded | `lifecycle.retained` keeps only the institutional-lineage kind from `independent_resources`; document contents are not durable recoverable backups. A durable library requires an explicit new backup design. |

The connected status tool responded successfully with a cached status snapshot reporting the institutional connection disconnected, its authentication revoked and live integration disabled. That is a returned status observation, not a fresh upstream check or a read of coursework. The assessment did not list the user's documents, read academic content, exercise upload, inspect private operator configuration, restart a service or run product tests.

## Why the chat upload does not solve the problem

Chat storage and Bridge storage are separate. Bridge must receive a supported file reference with a usable transfer capability, or receive bytes directly, then validate and persist them under the authenticated owner. A chat file ID alone, a `sandbox:` path, a local filename, or a model's summary is insufficient.

OpenAI documents explicit top-level tool file inputs through `_meta["openai/fileParams"]`, using required `download_url` and `file_id` fields and optional declared `mime_type` and `file_name` fields. It also documents optional widget upload, file-library selection and temporary download helpers. These are integration hooks, not automatic synchronization or proof this installed plugin supports them. [OpenAI plugin reference](https://developers.openai.com/plugins/reference#file-apis), checked October 29, 2026.

## Reuse rather than rebuild

Extend `independent.py`, `independent_ui.py`, `usefulness/imports.py`, `usefulness/ui.py`, `app.py`, `storage.py`, `auth.py`, `document_policy.py`, parser/render workers, egress projection and lifecycle controls. Preserve old document IDs through an explicit mapping. Do not replace working independent academic algorithms or create a second authentication service.

There is no defensible single completion percentage: temporary document storage and analysis are substantially present; durable storage, native intake, broader media and operational recovery are separate missing capabilities. The first release should make the existing independent workflow persistent and easy to supply with files.
