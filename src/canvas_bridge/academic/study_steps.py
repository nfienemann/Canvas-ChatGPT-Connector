"""Deadline projection for independent assignment decompositions."""

import re
from collections import defaultdict

from canvas_bridge.academic_rules import (
    ASSESSMENT_KEY,
    BRIEF_HEADER,
    citation,
    passages,
    reported_word_ranges,
)
from canvas_bridge.domain import FactDate


def step_parents(dataset):
    """Prefer explicit edges. Recognize the earlier qualified 'KEY / step' encoding
    only when both the numbered key and title independently name the same parent.
    Ordinary child activities (such as a reply with its own due date) stay separate.
    """
    parents = {}
    for row in dataset.work:
        if row.activity_kind == "study_step":
            parents[row.key] = row.parent_key
        elif row.activity_kind == "assignment" and not row.parent_key:
            match = re.fullmatch(rf"({ASSESSMENT_KEY})-S[1-9]\d*", row.key)
            if match and row.title.startswith(match[1] + " / "):
                parents[row.key] = match[1]
    return parents


def calendar_items(items, parents):
    deadlines = [item for item in items if item.id not in parents]
    explicit = {item.id for item in deadlines}
    groups = defaultdict(list)
    for item in items:
        if item.id in parents and parents[item.id] not in explicit:
            groups[parents[item.id]].append(item)
    # Legacy imports can carry just the child records. A shared cutoff supports
    # a reviewable proposal only. Conflicting or absent dates supply no reminder.
    for key, children in sorted(groups.items()):
        first = min(children, key=lambda item: item.id)
        due = first.effective_due
        if any(child.effective_due != due for child in children):
            due = FactDate()
        source = first.source.model_copy(
            update={
                "locator": "Shared planning cutoff for " + key,
                "classification": "assistant_inference",
                "uncertainty": [
                    "Confirm the parent deadline against its source before using this reminder."
                ],
            }
        )
        deadlines.append(
            first.model_copy(
                update={
                    "id": key,
                    "source_id": key,
                    "title": key,
                    "source": source,
                    "effective_due": due,
                    "personal_progress": "unknown",
                    "effort_remaining": None,
                    "prerequisites": [],
                }
            )
        )
    return deadlines, sorted(groups)


def brief_keys(lines):
    return {
        m[1]
        for _, line, _ in lines
        if (m := BRIEF_HEADER.match(line)) and m[1].split("-")[0] == m[2]
    }


def source_steps(documents):
    """Extract bounded review candidates from explicit sections of selected briefs.
    Each paragraph or deliverable remains traceable to the text that supplied it.
    """
    rows = []
    for doc in documents:
        if doc["role"] != "instructions":
            continue
        lines = list(passages(doc))
        keys = brief_keys(lines)
        if len(keys) != 1:
            continue
        parent = keys.pop()
        section = ""
        for part, line, offset in lines:
            if line.startswith("#"):
                section = line.strip("# ").casefold()
            elif section in {"assignment requirements", "required submission"}:
                rows.append(
                    {
                        "parent_key": parent,
                        "kind": "deliverable"
                        if section == "required submission"
                        else "student_work",
                        "evidence": citation(doc, part, line, offset),
                    }
                )
                if len(rows) == 50:
                    return {"steps": rows, "coverage": "bounded_review_required"}
    return {"steps": rows, "coverage": "selected_sections_only"}


def reported_plan_conflicts(dataset, documents):
    """Keep expressly unresolved brief constraints with the selected assignment."""
    work_keys = {row.key for row in dataset.work if row.activity_kind == "assignment"}
    conflicts = []
    for doc in documents:
        if doc["role"] != "instructions":
            continue
        keys = brief_keys(passages(doc))
        if len(keys) != 1 or not keys <= work_keys:
            continue
        for ranges, witness in reported_word_ranges(doc).items():
            conflicts.append(
                {
                    "parent_key": next(iter(keys)),
                    "rule_type": "word_count",
                    "status": "unresolved_contradiction",
                    "candidates": [{"minimum": low, "maximum": high} for low, high in ranges],
                    "evidence": witness,
                }
            )
    return conflicts


def review_step_evidence(dataset, documents):
    """Check cited quotes against currently selected parts, including their version.
    A matching passage grounds review. It cannot verify an estimate or completion.
    """
    parts = {
        (doc["id"], doc["version"], part["locator"]): part["text"]
        for doc in documents
        for part in doc["parts"]
    }
    scoped = {doc["id"]: brief_keys(passages(doc)) for doc in documents}
    reviewed = []
    for row in dataset.work:
        if row.activity_kind != "study_step":
            continue
        verified = []
        for anchor in row.evidence:
            doc_id = anchor.get("document_id")
            if scoped.get(doc_id) and scoped[doc_id] != {row.parent_key}:
                continue
            content = parts.get((doc_id, anchor.get("content_hash"), anchor.get("locator")))
            quote = anchor.get("quote")
            if not content or not isinstance(quote, str) or not quote.strip():
                continue
            start = anchor.get("start")
            if start is None and content.count(quote) == 1:
                start = content.index(quote)
            if type(start) is int and start >= 0 and content.startswith(quote, start):
                end = start + len(quote)
                if anchor.get("end", end) == end:
                    verified.append(
                        {
                            "document_id": doc_id,
                            "content_hash": anchor["content_hash"],
                            "locator": anchor["locator"],
                            "start": start,
                            "end": end,
                        }
                    )
        reviewed.append(
            {
                "work_id": row.key,
                "parent_key": row.parent_key,
                "evidence": verified,
                "status": "cited_passages_located"
                if verified and len(verified) == len(row.evidence)
                else "source_review_required",
            }
        )
    return reviewed
