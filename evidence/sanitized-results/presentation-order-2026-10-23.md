# Sectioned presentation repair — October 23, 2026

## Acceptance state

The owner-supplied whole-deck acceptance remains **NOT PASSED**. Local text
extraction is repaired, but the original still cannot render because its package
contains unsupported EMF media. No scientific interpretation of the requested
slide or complete visual review is established. This is a local implementation
and private operator validation record, not installed-plugin deployment evidence.

## Confirmed cause

The authorized original was freshly resolved through the existing connection,
course and file checks. Its source version, byte count and original-byte SHA-256
were independently matched against the supplied acceptance fixture. Raw bytes,
IDs, hashes, text and diagnostic artifacts remain in private operator storage.

Credential-free AppContainer inspection found 54 entries in the presentation's
actual slide list and 54 additional numeric references in PowerPoint section
extensions. None of the actual slides is hidden. The old parser recursively
selected every element with local name `sldId`, then rejected a section reference
because it did not contain a relationship ID. Its failure location was verified
against the original inside the sandbox. Both extraction and conversion preflight
use this enumeration routine; native LibreOffice conversion had not been reached.

Section references are a separate schema structure, as documented by Microsoft's
[CT_Section specification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-pptx/5bb610d5-ced8-44ed-a4b6-cd3d5f938906).
The fix reads only the direct, namespace-qualified presentation slide list and
its matching relationship-ID attributes. Missing/duplicate lists, malformed
entries, missing parts, duplicate slide paths, external targets and unsafe paths
remain rejected. Hidden slides stay in source order; both `0` and `false` are
recognized. Parser and converter identities advance to invalidate old results.

## Diagnostics repaired

- Conversion failures no longer assert that text extraction is available.
  `text_fallback.status` is `available`, `failed` or `not_checked`, based on the
  current source version, parser and cached extraction evidence. Availability is
  scoped to the requested slide's text; it never establishes visual coverage.
  Known failures preserve their extraction reason. Empty, unreadable or missing
  slide text is not advertised as a usable fallback. Stale evidence is not used.
- Successful and failed presentation responses now carry aggregate evidence for
  authorization, source retrieval and rasterization. Cache hits explicitly cite
  version-checked cached derivatives. Host delivery, model visibility and
  interpretation remain unknown on the server.
- Sanitized invalid-reference/archive reasons survive the conversion wrapper.
  Failed per-slide extraction no longer sets `text_complete_in_response=true`.

## Private local verification

All seven continuation batches were read using their returned arguments and
content hash, checking the source version throughout. They returned 54 ordered
slide records, without unreadable or truncated extraction records. This is
embedded-text coverage only: 20 records contain just a printed slide number.
The requested slide is one such record, so its scientific content remains unknown.

The next conversion attempt stops in full-source media preflight with
`PPTX_UNSUPPORTED_MEDIA`, identifying `emf`. Structural inspection found seven
EMF package members, including comment-bearing metafiles. No EMF validation was
removed, no image was silently omitted and no unsandboxed converter was used.
This remaining format support requires its own bounded parsing and fidelity work;
simply accepting the extension would not constitute a validated repair.

Authorization/credential/epoch/course-selection fingerprints were unchanged
before and after each private probe. Source files, permissions, saved renderer
settings, Calendar records and Canvas records were not changed. Read caches and
private diagnostic artifacts were created through the normal local read paths.
The final installed connection-status check also retained the original selected
scope snapshot and four selected courses; saved-state writes and notifications
remained disabled. That status check does not by itself prove item-level access.

## Checks

- Focused parser/subset/derivative/render regression run: 94 passed, two opt-in
  native skips (before the final additional regression cases).
- Explicit native AppContainer checks: three passed, including a sectioned deck,
  hidden-slide mapping, footer number preservation and verified PDF/PNG output.
- Local Topic 8 control: all five slide text records retrieved; original slide 1
  converted and rendered at 1600 x 900, with a prepared native MCP image block.
  Codex inspected the saved image through the local image tool. This confirms
  model-visible pixels for the local control, not a new installed-plugin call.
  Its aggregate server source/render stages are established while delivery and
  model interpretation remain unknown on the server, as required.
- Full suite: **872 passed, 25 skipped in 249.16 seconds**. Skips cover Linux
  kernel checks, disposable PostgreSQL, opt-in native conversion and unavailable
  OCR configuration. The three native conversion cases passed separately above.
- Targeted Ruff lint passed. Formatting passes for eight touched code/test files;
  the existing unrelated inventory tuple in `course_files.py` still fails its
  file-wide formatting check and was left unchanged. `git diff --check` passed.

No deployment or installed-client acceptance is claimed. The owner-reported
same-session native Topic 8 image success remains separate historical evidence.
The private service was not restarted; loading the updated parser and converter
identities requires a coordinated restart before installed-plugin verification.
