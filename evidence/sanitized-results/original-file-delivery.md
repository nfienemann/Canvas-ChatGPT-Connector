# Original delivery verification — October 22, 2026

Tested locally on Windows. Existing uncommitted work was preserved. No live
service restart, catalog refresh, scope change or credential change occurred.
No real academic records, IDs, credentials or signed URLs are included here.

## Actual checks

| Command / check | Outcome |
|---|---|
| `pytest tests/test_course_files.py -q` | 58 passed |
| `pytest tests/test_file_delivery_contract.py -q --tb=short` | 11 passed: official MCP client and simulated widget outcomes |
| `pytest -q --tb=short` | 662 passed, 22 skipped; one stale catalog-count assertion failed (29 versus new 31), subsequently corrected |
| Targeted reader/permission/delivery regression command below | 286 passed, 2 skipped after correcting the catalog assertion |
| `pytest tests/test_file_delivery.py tests/test_file_delivery_contract.py tests/test_desktop.py tests/test_release_boundaries.py -q --tb=short` | Final delivery, UI and desktop checks: 68 passed |
| `npm run build` in `ui/page-reader` | Both assets built with pinned dependencies |
| `.venv/Scripts/python.exe -m ruff check src tests scripts/build_desktop.py` | Passed |
| `git -c core.safecrlf=false diff --check` | Passed |

Python commands used `.venv/Scripts/python.exe -m pytest`. Full-run skips require
Linux, a disposable PostgreSQL database, or optional OCR runtime. No migration
was added. The full suite was not repeated after the narrow catalog correction;
affected checks were rerun. A Windows UTF-8 issue in the Node harness was fixed
before its passing run.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_file_delivery.py tests/test_file_delivery_contract.py tests/test_personal.py tests/test_course_files.py tests/test_file_reading.py tests/test_file_reading_contract.py tests/test_docx_reading.py tests/test_spreadsheet_reading.py tests/test_visual_files.py tests/test_visual_ui.py tests/test_permission_consistency.py tests/test_permission_consistency_contract.py -q --tb=short
```

## Byte preservation and client evidence

The deterministic synthetic workbook includes formulas, cached values, formatting,
relationships and hidden content. Chromium 146 downloaded it through the new
loopback HTTP capability endpoint with no failure and suggested filename
`Synthetic PCR Δ.xlsx`. The saved file was **3,259 bytes**, SHA-256
`7bc72ab2d4b7737786f1d60f3afaffad729f96836cf1c7b4d2676be09fdeed7a`, exactly
matching the prepared original. This is external browser evidence, not ChatGPT.

The live acceptance workbook was rediscovered with current opaque IDs through the
installed connector. Despite partial collection coverage, individual authorization
succeeded. A private operator used new local code to fetch, stage and deliver it
through the in-process ASGI HTTP endpoint. A separate authorized upstream response
matched its version, bytes and digest. Size remained **9,912 bytes**. The live digest,
copy and report remain outside Git. Selection/credential/connection fingerprints
were unchanged. The deployed reader returned `ok`, XLSX, one sheet, and the same
raw-byte hash. This does not prove the new tool is deployed.

| Surface | Download | Byte match | Native attachment |
|---|---|---|---|
| ChatGPT web | Not tested: browser profile signed out | Not established | Not established |
| ChatGPT desktop/mobile | Not tested | Not established | Not established |
| Chromium external browser | Synthetic pass | Exact | No |
| Official MCP and HTTP clients | Synthetic pass | Exact | Not applicable |
| Live operator / in-process HTTP | Pass | Exact | No |

MCP negotiated **2025-11-25** using installed/locked Python SDK **1.30.0**.
Existing Apps SDK **2.0.3** supplies optional `downloadFile`; no SDK migration.
Browser inventory initially timed out; the CLI then confirmed a signed-out ChatGPT
profile. No login or ChatGPT write followed. SDK documentation and simulated host
tests do not prove a real ChatGPT handoff.

The full ChatGPT definition of done remains pending. Restart the existing service,
refresh connector metadata, and run the repeat prompt in
`docs/original-file-delivery.md` from a signed-in client. Record actual capability,
saved filename/length/hash, current reference comparison, rejection/timeout,
expiry and fresh download. Test web plus mobile before cross-device claims.

## Subsequent owner report — October 22, 2026

The owner reported in **Fetch downloadable file** that the browser download
worked after selecting **Visit Site**. The referenced screenshot was inspected
and shows an ngrok free-service interstitial. The owner also quoted the widget's
message that in-chat download was unavailable and that the private, expiring
browser link required the server to remain online. This adds user-reported
private-use success to the earlier checks above; it does not establish a client
build, negotiated capability record, downloaded-byte match or native attachment.
No new live download or service/catalog change was performed for this roadmap
update. The earlier restart/catalog instructions describe the earlier session;
recheck deployed state before any future deployment action.

See [C12-D01–C12-D06](../implementation-tickets.md#public-release-download-roadmap--october-22-2026)
for planned work and exit evidence. The private screenshot, hostname, IP, download
URL and academic file are not copied into the repository. This documentation-only
update does not upgrade public-release gates or rerun the historical tests above.

Roadmap-update checks: scoped `git -c core.safecrlf=false diff --check`, local
Markdown link/anchor validation, and six unique ticket headings passed. Existing
Markdown hard line breaks are preserved. No application tests were run for this
documentation-only change.
