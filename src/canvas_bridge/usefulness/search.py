"""Deterministic lexical retrieval with mapped Unicode offsets and sealed cursors."""

import math
import re
import unicodedata
from binascii import Error as Base64Error
from datetime import timedelta

from cryptography.exceptions import InvalidTag

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.evidence import fingerprint

RANKER = "bounded-lexical-1"
# Inspectable, deliberately small; ambiguous expansions require course context.
TERMS = {
    "experimental control": ("control group", "vehicle-treated", "untreated", "placebo"),
    "control group": ("vehicle-treated", "untreated", "placebo"),
    "diffusion": ("concentration gradient", "passive transport"),
    "atp": ("adenosine triphosphate",),
    "dna": ("deoxyribonucleic acid",),
    "pcr": ("polymerase chain reaction",),
    "ecm": ("extracellular matrix",),
    "ram": ("random access memory",),
    "cpu": ("central processing unit",),
    "cell energy": ("mitochondria", "adenosine triphosphate"),
    "negative feedback": ("inhibits", "homeostasis"),
    "effect size": ("magnitude", "difference between groups"),
    "deadline": ("due", "submit by"),
    "requirements": ("must", "required"),
    "peer review": ("review a classmate", "review another"),
}


def normalized(text):
    chars, offsets = [], []
    for i, char in enumerate(text):
        for c in unicodedata.normalize("NFKC", char).casefold():
            chars.append(c)
            offsets.append(i)
    return "".join(chars), offsets


def expansion(query):
    norm, _ = normalized(query)
    terms = []
    for key, alternatives in TERMS.items():
        if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", norm):
            terms.extend(alternatives)
    return list(dict.fromkeys(terms))[:8]


def locator(page, number, kind):
    if kind == "pptx":
        return f"Slide {page.get('slide', page.get('page', number))}"
    if kind == "pdf":
        return f"PDF page {page.get('page', number)}"
    return page.get("locator") or f"{'Section' if kind == 'docx' else 'Part'} {number}"


def ranked_passages(rows, query, mode):
    alternatives = expansion(query) if mode == "conceptual" else []
    q, _ = normalized(query)
    exact = q.startswith('"') and q.endswith('"')
    if exact:
        q, alternatives = q[1:-1], []
    tokens = set(re.findall(r"\w+", q)) - {"the", "a", "an", "of", "in", "is", "what", "about"}
    hits, coverage = [], []
    remaining, passages_left = 1_000_000, 5000
    for row in rows:
        parsed = row.content["parsed"]
        pages = parsed.get("pages", [])
        unread = [i for i, p in enumerate(pages, 1) if p.get("state") != "extracted"]
        coverage.append(
            {
                "document_id": row.id,
                "content_hash": row.version_hash,
                "coverage": parsed.get("coverage", "partial"),
                "unread_parts": unread,
                "bounded_omissions": len(pages) > 200
                or any(len(p.get("text", "")) > 200_000 for p in pages),
                "representations": "extracted_text_only",
                "visual_inspection_status": "not_performed",
            }
        )
        for part, page in enumerate(pages[:200], 1):
            text = page.get("text", "")
            if remaining <= 0 or passages_left <= 0:
                coverage[-1]["bounded_omissions"] = True
                break
            bounded = text[: min(200_000, remaining)]
            remaining -= len(bounded)
            if len(bounded) < len(text):
                coverage[-1]["bounded_omissions"] = True
            # Whole source offsets are retained; no normalized text is quoted.
            for match in re.finditer(r"[^\n]+", bounded):
                if passages_left <= 0:
                    coverage[-1]["bounded_omissions"] = True
                    break
                passages_left -= 1
                line = match.group()
                norm, offsets = normalized(line)
                reasons = []
                positions = []
                if mode == "literal":
                    literal = query.casefold()
                    folded = line.casefold()
                    at = folded.find(literal)
                    if at < 0:
                        continue
                    # NFKC is reserved for conceptual mode; literal legacy behavior stays intact.
                    # Casefold alone also expands some codepoints; find the
                    # source boundary without changing literal matching rules.
                    folded_offsets = [i for i, c in enumerate(line) for _ in c.casefold()]
                    positions.append((at, at + len(literal)))
                    offsets = folded_offsets
                    reasons.append("literal_phrase")
                    score = 100.0
                else:
                    at = norm.find(q)
                    if at >= 0:
                        reasons.append("exact_phrase")
                        positions.append((at, at + len(q)))
                    matched = [t for t in alternatives if t in norm]
                    for term in matched:
                        index = norm.find(term)
                        positions.append((index, index + len(term)))
                    found = tokens & set(re.findall(r"\w+", norm))
                    # Preserve negation in multi-token queries and exact quotes.
                    if exact and at < 0:
                        continue
                    if {"not", "no", "without"} & tokens - found:
                        continue
                    if at < 0 and not matched and len(found) < max(1, math.ceil(len(tokens) * 0.6)):
                        continue
                    if matched:
                        reasons.append("expanded_term: " + ", ".join(matched))
                    if found:
                        reasons.append("query_tokens: " + ", ".join(sorted(found)))
                    score = (100 if at >= 0 else 0) + len(matched) * 12 + len(found) * 3
                    score += 2 if match.start() == 0 else 0
                start, end = match.start(), match.end()
                if len(line) > 1600:
                    first = offsets[positions[0][0]] if positions else 0
                    left = max(0, first - 200)
                    start, end = start + left, min(end, start + left + 1600)
                quote = text[start:end]
                hits.append(
                    {
                        "document_id": row.id,
                        "content_hash": row.version_hash,
                        "course": row.content.get("course", "independent"),
                        "part": part,
                        "locator": locator(page, part, row.content["format"]),
                        "start": start,
                        "end": end,
                        "quote": quote,
                        "evidence_kind": "extracted_text",
                        "ranking_score": score,
                        "ranking_reason": reasons,
                        "read_continuation": {
                            "document_id": row.id,
                            "start_part": part,
                            "limit": 1,
                            "start_offset": start,
                            "characters": min(end - start, 18000),
                        },
                        "visual_inspection_status": "not_performed",
                    }
                )
    hits.sort(key=lambda h: (-h["ranking_score"], h["document_id"], h["part"], h["start"]))
    # Diversify equally scored evidence without dropping contradictory passages.
    hits = list(
        {(h["document_id"], h["content_hash"], h["part"], h["start"]): h for h in hits}.values()
    )
    diversified = []
    for score in sorted({h["ranking_score"] for h in hits}, reverse=True):
        buckets = {}
        for hit in hits:
            if hit["ranking_score"] == score:
                buckets.setdefault(hit["document_id"], []).append(hit)
        while any(buckets.values()):
            for bucket in buckets.values():
                if bucket:
                    diversified.append(bucket.pop(0))
    return diversified, alternatives, coverage


def seal_cursor(bridge, owner, binding, offset):
    return bridge.vault.seal(
        {
            "binding": binding,
            "offset": offset,
            "expires": (bridge.retention.clock() + timedelta(minutes=15)).isoformat(),
        },
        owner,
        "usefulness-cursor",
    )


def cursor_offset(bridge, owner, cursor, binding):
    if not cursor:
        return 0
    from datetime import datetime

    try:
        value = bridge.vault.open(cursor, owner, "usefulness-cursor")
        if (
            value["binding"] != binding
            or datetime.fromisoformat(value["expires"]) <= bridge.retention.clock()
        ):
            raise ValueError
        offset = value["offset"]
        if type(offset) is not int or not 0 <= offset <= 100_000:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, InvalidTag, Base64Error):
        raise DomainError(
            "source_changed",
            "Search scope or sources changed; start a fresh search.",
            reason_code="DOCUMENT_SEARCH_SCOPE_CHANGED",
        ) from None


async def search(
    bridge, owner, document_ids, query, *, mode="conceptual", course=None, cursor=None, limit=10
):
    from canvas_bridge.integrity.surfaces import before_tool

    if mode == "conceptual" and not bridge.settings.conceptual_search_enabled:
        raise DomainError(
            "unsupported_feature",
            "Conceptual search is disabled; use literal mode.",
            reason_code="LOCAL_CONCEPTUAL_SEARCH_DISABLED",
        )
    if not document_ids or len(document_ids) > 20 or not query.strip():
        raise DomainError(
            "needs_input",
            "Select one to twenty imported documents and provide a nonblank query.",
            reason_code="LOCAL_SEARCH_INPUT_REQUIRED",
        )
    rows = []
    for ident in dict.fromkeys(document_ids):
        row = bridge.independent.require(owner, ident)
        if course is not None and row.content.get("course", "independent") != course:
            raise DomainError(
                "permission_denied",
                "The selected source is unavailable in this scope.",
                reason_code="INDEPENDENT_SOURCE_UNAVAILABLE",
            )
        await before_tool(bridge, owner, "read_local_document", {"document_id": ident})
        bridge.egress.release(
            bridge.independent.read(owner, ident, status=True),
            owner,
            {"document_id": ident},
            tool_name="get_local_document_status",
        )
        rows.append(row)
    hits, expansions, coverage = ranked_passages(rows, query, mode)
    binding = fingerprint(
        [
            owner,
            query,
            mode,
            course,
            expansions,
            RANKER,
            [(r.id, bridge.independent.evidence(r).semantic_hash) for r in rows],
        ]
    )
    offset = cursor_offset(bridge, owner, cursor, binding)
    chosen = hits[offset : offset + limit]
    for row in rows:
        current = bridge.independent.require(owner, row.id)
        if current.version_hash != row.version_hash:
            raise DomainError(
                "source_changed",
                "A source changed; repeat the search.",
                reason_code="DOCUMENT_SEARCH_SCOPE_CHANGED",
            )
    result = Result(
        status="partial_data"
        if any(
            c["coverage"] not in {"complete", "text_only"}
            or c["unread_parts"]
            or c["bounded_omissions"]
            for c in coverage
        )
        else "ok",
        summary="Ranked source passages. Scores measure lexical relevance, not correctness or visual understanding.",
        data={
            "hits": chosen,
            "mode": mode,
            "expansions": expansions,
            "expansion_provenance": "reviewed_local_terms_v1",
            "ranker_version": RANKER,
            "inventory_hash": binding,
            "coverage": coverage,
            "effective_scope": {"document_ids": [r.id for r in rows], "course": course},
            "next_cursor": seal_cursor(bridge, owner, binding, offset + len(chosen))
            if offset + len(chosen) < len(hits)
            else None,
            "limitations": [
                "Only extracted text was searched; no match cannot establish absence from images or unread content."
            ],
        },
        sources=[bridge.independent.evidence(r) for r in rows],
    )
    return bridge.egress.release(
        result, owner, {"document_ids": document_ids}, tool_name="search_local_documents"
    )
