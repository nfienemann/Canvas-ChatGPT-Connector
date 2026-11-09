# U04 - Find evidence without exact wording

Priority: high | Status: development specification, not implemented evidence
Read README.md first. Outcome: relevant passages are found with fewer student reformulations.

## 1. Reuse and scope

Inspect current search/read/index/continuation paths. Public and installed contracts specify literal matching [README R4]; preserve it. Add ranked conceptual retrieval over permitted extracted content, not another chatbot.

Independent search works with Canvas disabled. Future institutional scopes retain separate authorization. No autonomous downloads, cross-user index or mandatory paid embeddings.

## 2. Retrieval behavior

Accept query, permitted course/document scope and literal/conceptual mode; old callers keep old behavior. Resolve course selections from actual access. Explicit cross-course scope must label each result’s course.

The conceptual path should combine the original query with bounded acronym/synonym expansion, token normalization, title/heading/caption matches and an existing or lightweight lexical ranker. Preserve scientific symbols and exact phrase options. Use small inspectable term mappings initially; do not require a vector database to ship this improvement.

Limit expansion to eight alternative terms/phrases initially. Show the expansion and why a passage matched; ranking scores are not probabilities of correctness. A host may suggest query alternatives, but server-validated scope and limits still apply. User/document text cannot change search permissions or request tools.

Return evidence, not an unsupported answer. Deduplicate overlapping passages without losing versions or contradictions. Diversify relevant hits. Ambiguous queries expose alternatives or seek clarification rather than silently switching disciplines.

Optional local embeddings/reranking require a frozen benchmark improvement, reviewed license/provenance, resource budget and vector lifecycle. No automatic model downloads; remote inference is outside this release.

## 3. Evidence and search contracts

Reuse the result envelope. Add mode, effective scope, expansion provenance, index/ranker versions, inventory hash and coverage by representation. Each hit carries a stable source ID/version, course, exact locator, passage/offset, evidence kind, ranking reason and a supported read continuation. Suggested default: ten hits, maximum twenty, within existing smaller budgets.

Source text, speaker notes, captions, OCR and reviewed visual interpretations are different evidence kinds. Captions may locate a figure but cannot establish its data or labels. Return a visual-inspection continuation when supported; never claim that a text hit means pixels were inspected. Do not create visual interpretations in this increment merely to populate an index.

Normalization must retain a mapping to original characters so quotes and offsets remain accurate with Unicode, ligatures and Greek symbols. Preserve the document's actual slide/page/cell identifiers. DOCX sections are not rendered pages. Formula text is not a recalculated result.

The manifest distinguishes searched, failed and unread permitted representations. Completion describes only bounded scope. No matches cannot establish absence from figures or unsearched content; failed extraction is not an empty success.

## 4. Authorization, lifecycle and performance

Filter authorized scope before retrieval/ranking, then recheck before output. Do not reveal foreign/restricted filenames, hit counts or matching terms. Caches and vectors are owner/course/source-version scoped; authorization cannot be inferred from an earlier cache fill. Source deletion/revocation must invalidate postings, snippets, cursors and derived vectors under the existing lifecycle controls.

Bind continuation to owner, scope, query/mode, expansions, source inventory, parser/ranker versions and expiry. Changed sources return a refresh action. Resume without duplicate hits or silent skipped ranges. A forged cursor or foreign source handle cannot cause a broader search.

Preserve cached-only and bounded unread-extraction behavior. Report remaining work; conceptual mode cannot silently download a course. Independent retries/cache misses must make no provider calls.

Target warm p95 under two seconds on a documented 100-document synthetic corpus; report hardware/index/concurrency. Separate cold-extraction budgets. Exhaustion is partial, never silently complete. Keep literal fallback and reversible feature flags.

## 5. Acceptance tests

U04-A1: A query about the experimental control retrieves a passage that names its specific control group without repeating the query wording. Return the actual passage and source location, not generated supporting text.

U04-A2: Resolve scoped acronym expansions and common paraphrases. Confusable terms across biology and computing remain course-qualified; short ambiguous queries do not silently cross course boundaries.

U04-A3: Exact phrases, negation, Greek letters, micro signs and normalized ligatures return correct original offsets. Existing literal-search fixtures do not regress.

U04-A4: An image-only slide with an informative caption is returned as a candidate for visual review, not as evidence of an unseen plot value. Unsupported representations remain gaps.

U04-A5: Foreign-owner matches, revoked sources and stale cached snippets never appear in counts or content. Injected “ignore filters” instructions cannot widen the scope or cause external requests.

U04-A6: Continue a multi-page ranked result, interrupt/restart and change a source version. Resume consistently or request refresh; never duplicate a passage, reuse stale citations or claim complete coverage after failure.

U04-A7: Delete a source and test a deletion-fenced restore. Its postings, vectors and cached excerpts remain unavailable. Re-import without permission does not resurrect restricted derived results.

U04-A8: Run identical independent searches with the Canvas adapter disabled and a network tripwire. Zero provider calls, deterministic lexical ranking and bounded output are required. Timeout/exhaustion reports partial coverage honestly.

## 6. Frozen benchmark and release gate

Before tuning, freeze 40 fictional queries with gold evidence: ten exact, twelve paraphrase, six acronym, six disambiguation and six genuinely unanswerable. Keep gold answers outside imported documents. The 34 answerable queries must include distractors and several file formats. Supplement with access-control tests; those are not retrieval-success samples.

Proposed release targets: correct evidence in the top five for at least 29 of 34 answerable queries; ten of ten exact matches preserved; all six unanswerable cases avoid invented support. Report baseline and candidate results by category, not only an aggregate. Inspect failed queries and latency/cost tradeoffs; use a separate held-out set for changes made after seeing failures.

Pilot reformulations and time-to-evidence under identical conditions. Report the sample, not learning-gain claims. Ship only an improvement to a nonliteral query class that preserves literal and security gates; installing embeddings is not success.
