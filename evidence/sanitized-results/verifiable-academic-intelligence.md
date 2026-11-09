# Verifiable academic intelligence

The four specifications were implemented in order on the local working checkout. The attached package identifies an older public revision. The captured source manifest identifies the code actually exercised here.

| Build property | Recorded value |
| --- | --- |
| Branch | `codex/visual-pdf-reading` |
| Base commit | `5bd086356e730b01b5a9f1be9de106446ef049c6` |
| SHA-256 of the product source manifest | `ac5e1d676c4d57715c0775b9e828ec5f863cbdb4e23cdab1fb1d95f9ca2a9875` |
| Acquisition and transport | Authenticated local HTTP MCP with a synthetic principal. The VAI test uses the real text parser in process. The Operations replay uses the isolated importer. |
| Host | ChatGPT web given captured responses and server instructions. Each primary case begins in an empty conversation. The fixture oracle and scores stay with the evaluator. |
| Release scope | Local development checkout. Deployment and direct invocation by an installed ChatGPT client remain unverified. |

## VAI-01 · Provenance

The baseline returned the original content hash in `document_version` but emitted an empty `source_version` on the same independent-document citation. Both now carry the verified original hash. The release retains the source ID, part, passage, offset, retrieval time and extraction limitations. Draft estimates, student declarations, provider observations and rule authority have separate representations. The host instructions now ask for the exact returned source and locator and attribution of secondary claims.

## VAI-02 · Amendments and disagreements

The baseline returned zero finance word-range conflicts, omitted CSV from the schedule formats, treated the superseded operations range as mandatory and retained a superseded marketing schedule reference as a current candidate. The replay after the changes shows:

- FIN310-A03 retains 1,000–1,400 and 800–1,000 words as disputed candidates. The shared endpoint does not settle applicability. The deadline amendment applies only to that assignment’s deadline. Both the requirement review and the plan cite the original conflict passage.
- MKT320-A05 retains October 30 at 23:59 as historical. The notice reports November 2 at 23:59 in New York. All three deliverables remain attached to the assignment.
- OPS330-A05 supports 1,600–2,000 words from the current brief. Its description of the superseded template remains attributable to that brief. The missing clarification has no original-source citation.
- Reversal and three seeded shuffles preserve the evaluated claims, source versions, timestamps, scope and coverage. The graph’s scoped policy and witness checks remain the authority boundary.

## VAI-03 · Degradation, recovery and eligibility

A synthetic mid-analysis replacement caused the public tool to release `INDEPENDENT_SOURCE_CHANGED` with zero sources. After refresh, the revised notice supported November 9 while the separate brief still supported November 8. Each retained its own hash. A transient local failure returned a selection-relative diagnostic and preserved the other document’s deliverables. Restoring the source restored its coverage. Revoking a selection kept that source out of derived output. Selecting only the remaining document produced a usable control.

Coverage now includes the extraction mode and whether the analysis truncated text. An archive lookup across 285 physical members separately established the absence of MKT320-C01, OPS330-N02 and OPS330-R04. The HTTP tool’s eligibility response and the archive inventory answer different questions.

## VAI-QA-01 · End-to-end evidence

The supplied validator matched 11 original files, 39 literal passages and the three missing-member observations against the original ZIP. The public read returned 38 of the 39 quotations verbatim. It withheld the synthetic profile identifier in the remaining quotation while retaining the reference time, timezone and seven study windows.

The evidence archive includes the exact tool requests and responses, eligible source versions, case-specific host inputs and answers, and evaluator observations. A separate integrated replay traces the stable finance assignment into the plan and calendar proposal. In the base plan the finance range conflict remains explicit, the planner allocates 1,010 estimated minutes, and 70 capacity-blocked plus 300 dependency-blocked minutes remain. Three parent assignments receive reminder proposals. The replay records zero provider writes.

Two earlier Operations runs correctly rejected their evidence when the product manifest changed during testing. The final seven-module run passed 131 tests with no skips on the identified final build. Three additional negative and positive controls verify that an explicitly disputed word range follows its selected assignment and unrelated numerical ranges create no plan constraint. A repeated VAI replay separately checks the privacy-filtered source quotations. No full repository suite result was reused.

### Host acceptance boundary

The case-by-case run and an additional multi-scenario diagnostic are scored separately. In the diagnostic, ChatGPT imported the later controlled November 9 notice into the original source-order comparison. In a second combined prompt, it imported the M05 personal declaration into the unmodified marketing base case. Those answers contain material attribution errors even though the underlying HTTP receipts distinguish the inputs correctly. Both combined answers are retained as failed diagnostics. The case-specific replays use fresh chats and only the selected version and sources. A narrowed presentation that dropped citation passages also made historical range applicability ambiguous. The archive retains that control and the replay with the source passages included.

The isolated runs passed the eight base cases, eight scored mutations and the Operations integration check. The two additional combined-prompt diagnostics failed. The accompanying ZIP contains 186 verified entries. Its SHA-256 is `315b500e3499480d09cd9ae72aab4bed7d5d1b66cc35d4f2aad06231847d7107`.

The host received the server instructions and released data through a recorded relay. This run verifies ChatGPT synthesis and the local authenticated tool transport separately. It leaves direct invocation against this checkout from an installed ChatGPT client open.

## Reproduction

Use the supplied VAI ZIP as `BRIDGE_TEST_VAI_SUITE` and the academic operations acceptance ZIP as `BRIDGE_TEST_ACADEMIC_OPS_SUITE`. Set `BRIDGE_TEST_VAI_OUTPUT` and `BRIDGE_TEST_ACADEMIC_OPS_OUTPUT` to fresh local directories to retain the receipts. The tests validate the input ZIP hashes. Use the repository’s configured Python environment and parser runtime.

```text
python -m pytest -q tests/test_verifiable_intelligence_acceptance.py tests/test_academic_operations_acceptance.py tests/test_academic_operations.py tests/test_damaged_academic_corpus.py tests/test_evidence_graph.py tests/test_independent_intelligence.py tests/test_academic_intelligence.py
```

The authenticated tool replay and the host replay are separate checks. To repeat the latter, submit each archived `isolated-host/<case>/host-input.txt` in its own empty ChatGPT chat and evaluate the response against the corresponding claim and mutation entries. The package’s expected answers belong exclusively in the evaluator.

[Current-route field map](../current_route_mapping.json) · [Synthetic requests, responses and host evaluations](verifiable-academic-intelligence-receipts.zip)
