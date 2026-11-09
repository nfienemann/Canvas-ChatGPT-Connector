# Progressive course PDF extraction · November 4, 2026

Local synthetic validation on Windows, using the working tree based on
`5bd0863`. The PDF contained 30 generated text pages. No coursework, live
Canvas connection, external ChatGPT session, or deployment was used.

## Timings

The Windows AppContainer timing test measured elapsed wall time for one run.
Cold includes trusted runtime preparation. Warm worker measurements start a
new isolated process. The service measurements include synthetic provider
authorization and an already-prepared runtime.

| Operation | Seconds |
| --- | ---: |
| Cold runtime, page 25 | 8.98 |
| Ready runtime, page 25 | 0.65 |
| Ready runtime, pages 1–4 | 0.63 |
| Authorized page 25, extraction cache miss | 1.36 |
| Authorized page 25, extraction cache hit | 0.30 |

The cache hit launched zero workers. In the same test, a trusted synthetic
stall on page 3 reached the real worker deadline. The parent recovered pages
1–2 and removed the job directory. Additional passing runs measured 16.95
and 27.77 seconds for the cold call including preparation. A separate cold
run reached the 15-second worker deadline before completing page 25. These
are individual observations; the worker wall and CPU limits remain 15 and
10 seconds respectively.

## Regression evidence

- A 30-page test recorded calls to page text extraction. A direct read of
  page 25 touched only that page's text. A subsequent complete read visited
  every page once across both requests, including overlapping and character
  continuations.
- Tests covered a cross-page annotation alias, an interrupted output record,
  an empty checkpoint, cached-only search with a gap, a skipped page followed
  by successful later reads, aggregate text limits, a changed source hash
  under unchanged metadata, and permission revocation.
- A 180-test reader, search and diagnostics run initially reported 175 passed
  and five failures. A later 13-test run covered all five failing cases and
  passed. It included the Windows sandbox boundary, result-stage errors,
  synthetic HTTP search, the interrupted-worker fixture and diagnostic logging.
- A separate 132-test run across academic, privacy and figure consumers
  reported 130 passes and two figure discovery failures. After restoring
  caption searches across the configured candidate range, both figure tests
  passed on rerun, including the synthetic MCP transport.
- The new sandbox timing test runs on supported Windows and Linux hosts.
  Reproduce with `python -m pytest -q -s tests/test_progressive_pdf.py::test_real_sandbox_progressive_pdf_timings`.
  This Windows host had no installed WSL distribution or container runtime.
  Linux timings, production load and live-client behavior remain unverified.
