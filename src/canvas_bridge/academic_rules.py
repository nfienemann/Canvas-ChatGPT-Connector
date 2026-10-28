"""Deterministic candidate extraction. Quoted course content is never an instruction.

Narrow grammars deliberately leave natural-language ambiguity to ChatGPT and
the student. A detected inconsistency is not proof of an instructor mistake.
"""

import re
from collections import Counter
from difflib import SequenceMatcher

from canvas_bridge.academic_dates import DATES, compare_deadline, parse_candidate
from canvas_bridge.evidence import fingerprint

ASSESSMENT = re.compile(
    r"\b(exam|quiz|paper|essay|project|assignment|presentation|lab|report|test|final|midterm|discussion|post|replies)\b",
    re.I,
)


def normalized(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def citation(document, part, passage, offset=0):
    return {
        "source_id": document["id"],
        "source_url": document["url"],
        "document_version": document["version"],
        "source_version": document.get("source_version"),
        "source_type": document["source_type"],
        "course_id": document["course_id"],
        "retrieved_at": document["retrieved_at"],
        "source_updated_at": document.get("source_updated_at"),
        "locator": part["locator"],
        "offset": offset,
        "passage": passage[:1500],
        "extraction_status": "complete_text" if document["complete"] else "partial_text",
        "classification": "source_fact",
        "untrusted_content": True,
    }


def passages(document):
    for part in document["parts"]:
        # Do not flatten whole paragraphs into invented source relationships.
        for match in re.finditer(r"[^\n]+", part["text"]):
            line = match.group().strip()
            if line:
                yield part, line, match.start() + len(match.group()) - len(match.group().lstrip())


def dated_obligations(documents):
    results = []
    for document in documents:
        for part, line, offset in requirement_clauses(document):
            if not ASSESSMENT.search(line):
                continue
            matches = list(DATES.finditer(line))
            for index, match in enumerate(matches):
                parsed = parse_candidate(match)
                title = (
                    (line[: match.start()] + line[match.end() :])
                    if len(matches) == 1
                    else line[matches[index - 1].end() if index else 0 : match.start()]
                )
                title = title.strip(" :–—-.,")
                title = re.sub(r"\b(?:due|on|date|scheduled for)\b", "", title, flags=re.I).strip(
                    " :–—-.,"
                )
                source = citation(document, part, line, offset)
                results.append(
                    {
                        "id": fingerprint(
                            [
                                document["course_id"],
                                document["id"],
                                document["version"],
                                part["locator"],
                                offset + match.start(),
                                match.group(),
                            ]
                        ),
                        "title": title[:500],
                        **parsed,
                        "date_offset": offset + match.start(),
                        "evidence": source,
                        "interpretation_status": "deterministic_candidate",
                        "candidate_kind": "classroom_activity"
                        if re.search(
                            r"\b(?:lecture|discussion|practice|workshop|activity|activities|lab session|in.class)\b",
                            line,
                            re.I,
                        )
                        and not re.search(
                            r"\b(?:due|submit|upload|deadline|requires?.{0,60}(?:post|replies))\b",
                            line,
                            re.I,
                        )
                        else "assessment_date_candidate",
                        "assignment_deadline_confirmed": False,
                        "student_confirmation_needed": True,
                    }
                )
    return results


def match_obligation(obligation, items):
    title = normalized(obligation["title"])
    exact = [i for i in items if normalized(i["title"]) == title]
    if len(exact) == 1:
        return exact[0], "exact_title", []
    candidates = []
    for item in items:
        other = normalized(item["title"])
        numbers, other_numbers = re.findall(r"\d+", title), re.findall(r"\d+", other)
        if numbers != other_numbers:
            continue
        a, b = ASSESSMENT.search(title), ASSESSMENT.search(other)
        if a and b and a.group().lower() != b.group().lower():
            continue
        score = SequenceMatcher(None, title, other).ratio()
        if score >= 0.6:
            candidates.append(
                {"work_id": item["id"], "title": item["title"], "similarity": round(score, 3)}
            )
    return None, "ambiguous" if candidates or exact else "no_match", candidates


def deadline_findings(documents, items, timezone, assignments_complete, *, source_label="Canvas"):
    findings, obligations, comparisons = [], dated_obligations(documents), []
    activities = [o for o in obligations if o["candidate_kind"] == "classroom_activity"]
    obligations = [o for o in obligations if o["candidate_kind"] != "classroom_activity"]
    for obligation in obligations:
        item, match, candidates = match_obligation(obligation, items)
        base = {
            "id": obligation["id"],
            "obligation": obligation,
            "match": match,
            "candidates": candidates,
            "work_id": item["id"] if item else None,
            "interpretation": "No source is assumed to supersede another.",
        }
        if not item:
            findings.append(
                {
                    **base,
                    "kind": "ambiguous_match"
                    if match == "ambiguous"
                    else "syllabus_only_candidate"
                    if source_label == "Canvas"
                    else "unmatched_source_candidate",
                    "certainty": "ambiguous",
                    "impact": "Confirm the assessment and its applicable date.",
                    "next_action": "Match this passage to the assessment with the instructor or student.",
                    "collection_complete": assignments_complete,
                }
            )
            continue
        due = item["effective_due"]
        base["canvas_evidence" if source_label == "Canvas" else "reference_evidence"] = item[
            "source"
        ]
        if due["kind"] == "known_none":
            findings.append(
                {
                    **base,
                    "kind": "missing_canvas_deadline"
                    if source_label == "Canvas"
                    else "missing_reference_deadline",
                    "certainty": "confirmed_field_absence",
                    "impact": f"{source_label} data has no due date; the source passage may establish an obligation.",
                    "next_action": "Verify which source date applies; do not treat this as unscheduled or automatically upcoming.",
                }
            )
        elif due["kind"] not in {"timestamp", "local_date"}:
            findings.append(
                {
                    **base,
                    "kind": "unavailable_canvas_deadline"
                    if source_label == "Canvas"
                    else "unavailable_reference_deadline",
                    "certainty": "insufficient_evidence",
                    "impact": f"{source_label} deadline could not be established.",
                    "next_action": "Refresh or inspect the assignment.",
                }
            )
        else:
            comparison = compare_deadline(obligation, due, timezone)
            if source_label != "Canvas" and "canvas_calendar_date" in comparison:
                comparison["reference_calendar_date"] = comparison.pop("canvas_calendar_date")
            comparisons.append(
                {"obligation_id": obligation["id"], "work_id": item["id"], **comparison}
            )
            base["comparison"] = comparison
            if comparison["outcome"] == "indeterminate":
                findings.append(
                    {
                        **base,
                        "kind": "timezone_unresolved"
                        if comparison.get("timezone_required")
                        else "source_date_unresolved",
                        "certainty": "insufficient_evidence",
                        "impact": comparison["reason"],
                        "next_action": "Review the cited date, year and timezone before comparing deadlines.",
                    }
                )
            elif comparison["outcome"] == "different":
                findings.append(
                    {
                        **base,
                        "kind": "conflicting_deadlines",
                        "certainty": "supported_source_difference",
                        "canvas_date" if source_label == "Canvas" else "reference_date": due,
                        "comparison_timezone": comparison["timezone"],
                        "impact": "The sources report different dates; applicability or an amendment may explain this.",
                        "next_action": "Check the cited versions and ask which deadline applies.",
                    }
                )
    return {
        "obligations": obligations,
        "classroom_activities": activities,
        "findings": findings,
        "comparisons": comparisons,
        "limitations": [
            "Recognizes ISO and English full/abbreviated month dates near an assessment term; numeric month/day order, missing years, ambiguous zones and DST transitions require review.",
            "Missing matches do not prove an assessment is absent. Ambiguous titles and missing years require review.",
            "Date-only passages do not establish a time or timezone. No source automatically overrides another.",
        ],
    }


WORD_COUNT = re.compile(r"\b(\d[\d,]*)(?:\s*[-–]\s*(\d[\d,]*))?\s*[- ]?\s*words?\b", re.I)


def requirement_clauses(document):
    for part, line, offset in passages(document):
        # Preserve source offsets while keeping neighboring recommendations from
        # modifying unrelated requirements. Decimal points are not boundaries.
        dates = [m.span() for m in DATES.finditer(line)]
        starts = [0] + [
            m.end()
            for m in re.finditer(r"(?<=[;.!?])\s+", line)
            if not any(a <= m.start() < b for a, b in dates)
        ]
        for start, end in zip(starts, [*starts[1:], len(line)], strict=True):
            raw = line[start:end]
            clause = raw.strip()
            if clause:
                yield part, clause, offset + start + len(raw) - len(raw.lstrip())


def requirements(document):
    rules = []
    for part, line, offset in requirement_clauses(document):
        optional = bool(
            re.search(
                r"\b(?:recommend|recommended|suggest|suggested|optional|example|approximately|about)\b",
                line,
                re.I,
            )
        )
        ambiguous = bool(
            re.search(r"\b(?:not|rather than|no longer|between|versus|vs\.?|or)\b", line, re.I)
        )
        if re.search(r"\bfigures?\b", line, re.I) and re.search(
            r"\b(?:required|mandatory|recommend(?:ed)?|optional)\b", line, re.I
        ):
            rules.append(
                {
                    "type": "figure_requirement",
                    "mandatory": not optional and not ambiguous,
                    "interpretation_status": "recommended"
                    if optional
                    else "ambiguous"
                    if ambiguous
                    else "explicit_requirement",
                    "evidence": citation(document, part, line, offset),
                }
            )
        for match in WORD_COUNT.finditer(line):
            low = int(match.group(1).replace(",", ""))
            high = int((match.group(2) or match.group(1)).replace(",", ""))
            if re.search(r"\b(?:at least|minimum)\b", line, re.I):
                high = None
            if re.search(r"\b(?:at most|maximum|up to)\b", line, re.I):
                low = 0
            rules.append(
                {
                    "type": "word_count",
                    "minimum": low,
                    "maximum": high,
                    "mandatory": not optional and not ambiguous,
                    "interpretation_status": "ambiguous"
                    if ambiguous
                    else "explicit_numeric_candidate",
                    "evidence": citation(document, part, line, offset),
                }
            )
        formats = sorted(set(re.findall(r"\b(?:PDF|DOCX|PPTX|TXT)\b", line, re.I)))
        if formats and re.search(r"\b(?:submit|upload|format)\b", line, re.I):
            rules.append(
                {
                    "type": "submission_format",
                    "formats": [f.lower() for f in formats],
                    "mandatory": not optional
                    and not re.search(r"\b(?:not|no longer)\b", line, re.I),
                    "evidence": citation(document, part, line, offset),
                }
            )
        criterion = re.fullmatch(
            r"\s*([A-Za-z][A-Za-z -]{1,60})\s*:\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\.?", line
        )
        if criterion and 0 <= float(criterion.group(2)) <= 100:
            rules.append(
                {
                    "type": "criterion_weight",
                    "criterion": normalized(criterion.group(1)),
                    "percent": criterion.group(2),
                    "mandatory": not optional,
                    "evidence": citation(document, part, line, offset),
                }
            )
    return rules


def instruction_findings(documents, draft=None):
    rules = [rule for doc in documents for rule in requirements(doc)]
    conflicts = []
    for index, left in enumerate(rules):
        for right in rules[index + 1 :]:
            if left["type"] != right["type"] or not left["mandatory"] or not right["mandatory"]:
                continue
            if left["type"] == "word_count":
                conflict = max(left["minimum"], right["minimum"]) > min(
                    left["maximum"] if left["maximum"] is not None else float("inf"),
                    right["maximum"] if right["maximum"] is not None else float("inf"),
                )
            elif left["type"] == "submission_format":
                conflict = not set(left["formats"]) & set(right["formats"])
            elif left["type"] == "criterion_weight":
                from decimal import Decimal

                conflict = left["criterion"] == right["criterion"] and Decimal(
                    left["percent"]
                ) != Decimal(right["percent"])
            else:
                continue
            if conflict:
                amendment = any(
                    re.search(
                        r"\b(?:replaces|supersedes|instead of|updated requirement)\b",
                        r["evidence"]["passage"],
                        re.I,
                    )
                    for r in (left, right)
                )
                conflicts.append(
                    {
                        "kind": "instruction_conflict",
                        "rule_type": left["type"],
                        "left": left,
                        "right": right,
                        "certainty": "amendment_candidate"
                        if amendment
                        else "unresolved_contradiction",
                        "impact": "Following one stated requirement may conflict with another.",
                        "next_action": "Confirm the scope of the amendment."
                        if amendment
                        else "Ask which cited requirement applies; no instructor error is presumed.",
                    }
                )
    review = None
    if draft is not None:
        words = len(re.findall(r"\b\w+(?:['’-]\w+)*\b", draft))
        review = {
            "word_count": words,
            "classification": "deterministic_calculation_on_student_input",
            "checks": [
                {
                    "rule": rule,
                    "satisfies_stated_count": words >= rule["minimum"]
                    and (rule["maximum"] is None or words <= rule["maximum"]),
                }
                for rule in rules
                if rule["type"] == "word_count" and rule["mandatory"]
            ],
            "grade_prediction": None,
            "limitations": [
                "Mechanical word count only; references and appendices are included.",
                "ChatGPT must review qualitative rubric criteria with citations; no instructor grade is predicted.",
            ],
        }
    return {
        "rules": rules,
        "conflicts": conflicts,
        "draft_review": review,
        "limitations": [
            "Deterministic conflict checks cover explicit word counts, submission formats and same-named percentage criteria; qualitative grading criteria need source-grounded review.",
            "Recommendations and examples are not treated as mandatory. Related sources are not automatically applicable policies.",
        ],
    }


STOPWORDS = set(
    "the and with this that from have will your course exam quiz paper study students should were there which their these those using into about between through than then also each only more some when what they been used material assignment syllabus results methods discussion introduction figure table references".split()
)


def repeated_concepts(documents):
    counts, citations = Counter(), {}
    for doc in documents:
        seen = set()
        for part in doc["parts"]:
            for m in re.finditer(r"\b[a-zA-Z]{5,}\b", part["text"]):
                word = m.group().lower()
                if word in STOPWORDS or word in seen:
                    continue
                seen.add(word)
                start = max(0, m.start() - 60)
                citations.setdefault(word, []).append(
                    citation(doc, part, part["text"][start : start + 220], start)
                )
        counts.update(seen)
    return [
        {
            "term": word,
            "documents": count,
            "classification": "deterministic_keyword_overlap",
            "evidence": citations[word][:3],
            "exam_coverage_confirmed": False,
        }
        for word, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        if count >= 2
    ][:15]
