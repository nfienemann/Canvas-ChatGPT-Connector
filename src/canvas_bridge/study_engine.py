"""Deterministic, deliberately narrow evidence extraction and practice construction.

Conversational explanation stays with the client. These patterns establish quoted
definition candidates, not independently verified scientific truth or mastery.
"""

import re
import unicodedata
from datetime import timedelta

from canvas_bridge.evidence import fingerprint

DEFINITION = re.compile(
    r"(?:^|(?<=[.!?])\s+|\n)([A-Za-z][\w ()/,-]{1,70}?)\s+(?:is defined as|refers to|means|is)\s+([^\n.!?]{12,500}[.!?]?)",
    re.M,
)
AMBIGUOUS = re.compile(
    r"\b(?:may|might|possibly|uncertain|disputed|sometimes|not always|not known|unclear)\b", re.I
)


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().strip(" .!?").split())


def extract_concepts(documents, requested=()):
    concepts = []
    for doc in documents:
        for passage in doc["passages"]:
            for match in DEFINITION.finditer(passage["text"]):
                name, definition = match.group(1).strip(), match.group(2).strip()
                if requested and normalized(name) not in {normalized(n) for n in requested}:
                    continue
                quote = match.group(0).strip()
                # Context remains source-specific even for an identical term.
                ident = fingerprint([doc["material_id"], doc["content_hash"], name, definition])[
                    :40
                ]
                if len(concepts) >= 40 or any(c["id"] == ident for c in concepts):
                    continue
                concepts.append(
                    {
                        "id": ident,
                        "name": name,
                        "definition": definition,
                        "course_id": doc["course_id"],
                        "material_id": doc["material_id"],
                        "context": doc["title"],
                        "source_passage": quote,
                        "locator": passage["locator"],
                        "content_hash": doc["content_hash"],
                        "source_id": doc["source_id"],
                        "classification": "source_definition_candidate",
                        "figures": [],
                        "related_assessments": [],
                        "assessment_links_status": "not_checked",
                        "figure_links_status": "not_checked",
                        "prerequisite_concepts": [],
                        "ambiguity": ["The source qualifies this definition."]
                        if AMBIGUOUS.search(quote)
                        else [],
                        "limitations": [
                            "Definition quoted from this source; scientific correctness is not independently verified."
                        ],
                    }
                )
    for concept in concepts:
        alternatives = [
            c
            for c in concepts
            if normalized(c["name"]) == normalized(concept["name"])
            and c["definition"] != concept["definition"]
        ]
        if alternatives:
            concept["ambiguity"].append(
                "The term has different source definitions; keep course contexts separate."
            )
    return concepts


def relationships(concepts, documents):
    links = []
    # A shared spelling is a discovery aid, never a scientific relationship.
    for i, a in enumerate(concepts):
        for b in concepts[i + 1 :]:
            if a["course_id"] != b["course_id"] and normalized(a["name"]) == normalized(b["name"]):
                links.append(
                    {
                        "from_concept": a["id"],
                        "to_concept": b["id"],
                        "relationship": "shared_term_only",
                        "conceptual_relationship_verified": False,
                        "source_ids": [a["source_id"], b["source_id"]],
                        "explanation": "Similar terminology is a prompt to compare the source contexts, not evidence of equivalence.",
                    }
                )
    # Only source-local explicit prerequisites are promoted to an academic edge.
    for doc in documents:
        local = [c for c in concepts if c["material_id"] == doc["material_id"]]
        for a in local:
            for b in local:
                if a["id"] == b["id"]:
                    continue
                pattern = re.compile(
                    r"(?<!\w)Understanding "
                    + re.escape(a["name"])
                    + r" requires "
                    + re.escape(b["name"])
                    + r"[.!](?!\w)",
                    re.I,
                )
                for passage in doc["passages"]:
                    match = pattern.search(passage["text"])
                    if match:
                        a["prerequisite_concepts"].append(b["id"])
                        links.append(
                            {
                                "from_concept": a["id"],
                                "to_concept": b["id"],
                                "relationship": "source_stated_prerequisite",
                                "conceptual_relationship_verified": False,
                                "source_ids": [doc["source_id"]],
                                "source_passage": match.group(0),
                                "locator": passage["locator"],
                                "explanation": "This source explicitly states the prerequisite; broader applicability is unknown.",
                            }
                        )
    return links[:60]


def questions(concepts, preferences):
    eligible = [c for c in concepts if not c["ambiguity"]]
    if preferences.focus:
        eligible = [
            c
            for c in eligible
            if normalized(c["name"]) in {normalized(n) for n in preferences.focus}
        ]
    count = min(10, max(1, preferences.session_minutes // 5))
    result = []
    for c in eligible[:count]:
        # If a definition leaks its own answer or two terms share this definition,
        # it cannot serve as a unique objective recall question.
        if normalized(c["name"]) in normalized(c["definition"]):
            continue
        if sum(normalized(x["definition"]) == normalized(c["definition"]) for x in concepts) != 1:
            continue
        open_ended = (
            preferences.question_format == "open_ended" or preferences.difficulty == "advanced"
        )
        prompt = (
            f"Explain the definition from {c['context']} and distinguish what the passage supports from what it leaves unknown: {c['name']}."
            if open_ended
            else f"In {c['context']}, which term is defined as: {c['definition']}"
        )
        options = []
        expected = c["definition"] if open_ended else c["name"]
        form = "open_ended" if open_ended else "recall"
        if preferences.question_format == "multiple_choice" and not open_ended:
            names = list(
                dict.fromkeys([c["name"], *[x["name"] for x in eligible if x["id"] != c["id"]][:3]])
            )
            if len(names) < 2:
                continue
            names.sort(key=lambda name: fingerprint([c["id"], name]))
            options = [{"label": chr(65 + i), "text": name} for i, name in enumerate(names)]
            expected = next(o["label"] for o in options if o["text"] == c["name"])
            form = "multiple_choice"
            prompt += " Respond with the option letter."
        result.append(
            {
                "id": fingerprint([c["id"], prompt, options])[:40],
                "concept_id": c["id"],
                "course_id": c["course_id"],
                "material_id": c["material_id"],
                "prompt": prompt,
                "generated_practice": True,
                "not_instructor_exam": True,
                "format": form,
                "options": options,
                "expected_answer": expected,
                "source_passage": c["source_passage"],
                "source_id": c["source_id"],
                "locator": c["locator"],
                "rubric": [
                    "Use the meaning stated in the cited passage.",
                    "Separate source statements from inference and acknowledge missing context.",
                ]
                if open_ended
                else [],
                "verification": "exact_source_definition",
            }
        )
    return result


def evaluate(question, response, previously_attempted=False):
    if question["format"] not in {"recall", "multiple_choice"}:
        outcome, state = "requires_review", "attempted_unresolved"
    elif normalized(response.response) == normalized(question["expected_answer"]):
        outcome = "correct"
        state = (
            "correct_with_assistance"
            if response.assistance_used or previously_attempted
            else "correct_independently"
        )
    elif question["format"] == "multiple_choice" and normalized(response.response) in {
        normalized(o["label"]) for o in question["options"]
    }:
        outcome, state = "incorrect", "attempted_incorrect"
    else:
        # Free text can contain an unlisted synonym. Do not turn mismatch into a
        # proven misconception or an automatic mastery judgment.
        outcome, state = "answer_mismatch_review_needed", "attempted_unresolved"
    return {
        "question_id": question["id"],
        "concept_id": question["concept_id"],
        "outcome": outcome,
        "practice_state": state,
        "self_reported_confidence": response.self_reported_confidence,
        "assistance_used": response.assistance_used or previously_attempted,
        "independence_basis": "student_report_not_observed",
        "mastery": "not_established",
        "expected_answer": question["expected_answer"],
        "source_passage": question["source_passage"],
        "source_id": question["source_id"],
        "rubric": question["rubric"],
        "locator": question["locator"],
    }


def review_recommendation(record, preferences, now):
    if not preferences.recommend_reviews:
        return {"status": "not_requested", "scheduled": False}
    from datetime import datetime

    elapsed = max(0, (now - datetime.fromisoformat(record["attempted_at"])).total_seconds() / 86400)
    interval = preferences.practice_frequency_days * (
        3 if record["practice_state"] == "correct_independently" else 1
    )
    earliest = max(now, datetime.fromisoformat(record["attempted_at"]) + timedelta(days=interval))
    windows = sorted(
        (w for w in preferences.availability if w.end > earliest), key=lambda w: w.start
    )
    slot = next(
        (
            max(w.start, earliest)
            for w in windows
            if (w.end - max(w.start, earliest)).total_seconds() >= preferences.session_minutes * 60
        ),
        None,
    )
    return {
        "status": "proposal" if slot else "availability_required",
        "scheduled": False,
        "recommended_at": slot.isoformat() if slot else None,
        "elapsed_days": round(elapsed, 2),
        "interval_days": interval,
        "heuristic": "Base frequency after assisted/unresolved practice; three times that interval after independently reported correct recall.",
        "limitations": [
            "A transparent review heuristic, not a validated individual memory prediction."
        ],
    }
