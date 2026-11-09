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


IDENTIFIER = re.compile(
    r"\b(quiz|exam|paper|project|assignment|lab|test|discussion)[\s#:-]*(\d+)\b(?!\.\d)", re.I
)


# An abbreviated range or list names multiple assessments, even if only one
# of the numbers has a type prefix ("Quiz 12 or 13").
IDENTIFIER_SERIES = re.compile(IDENTIFIER.pattern + r"\s*(?:[-–/,]|and|or|to)\s*\d", re.I)


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


# Portable assignment documents use a course-qualified key in their identity header.
ASSESSMENT_KEY = r"[A-Z]{2,10}\d{2,4}-A\d{2,4}"
BRIEF_HEADER = re.compile(rf"^({ASSESSMENT_KEY})\s*\|\s*([A-Z]+\d+)\s*\|")


def deadline_amendment(line, dates):
    """Return the shared title only for an unqualified, same-sentence replacement."""
    if len(dates) < 2:
        return False, None
    prefix = line[: dates[0].start()].strip()
    between = line[dates[0].end() : dates[1].start()].strip()
    original = re.search(r"\b(?:was\s+)?(?:originally\s+)?due(?:\s+on)?$", prefix, re.I)
    moved = re.search(
        r"\bdeadline (?:was |has been )?(?:extended|moved|changed) from$", prefix, re.I
    )
    revision = re.search(r"\b(?:extended|moved|changed|now due)\b", between, re.I)
    if moved and not re.search(ASSESSMENT_KEY, prefix):
        title = prefix[: moved.start()].strip()
        connector = r"to"
    elif original and ("originally" in original[0].lower() or revision):
        title = prefix[: original.start()].strip()
        connector = (
            r",?\s*(?:but|and)\s+(?:(?:the |its )?deadline\s+)?"
            r"(?:(?:has been|was|is)\s+(?:extended|moved|changed)\s+to|is now due(?: on)?)"
        )
    else:
        return False, None
    if (
        len(dates) == 2
        and IDENTIFIER.fullmatch(title)
        and not line[dates[1].end() :].strip(" .")
        and re.fullmatch(connector, between, re.I)
    ):
        return True, title
    return True, None


def dated_obligations(documents):
    results = []
    for document in documents:
        brief_keys = {
            header[1]
            for _, text, _ in passages(document)
            if (header := BRIEF_HEADER.match(text)) and header[1].split("-")[0] == header[2]
        }
        previous_addressed = None
        for part, line, offset in requirement_clauses(document):
            keys = set(re.findall(rf"\b{ASSESSMENT_KEY}\b", line))
            addressed = None
            if re.match(r"^Deadline\s*:", line, re.I) and len(brief_keys) == 1:
                addressed = next(iter(brief_keys))
            elif len(keys) == 1 and re.search(
                r"\b(?:now due|moved? from|moves from|deadline moves)\b", line, re.I
            ):
                addressed = next(iter(keys))
            historical_schedule = bool(
                previous_addressed
                and re.match(
                    r"^(?:The )?(?:earlier|original) course schedule (?:lists|listed)\b", line, re.I
                )
            )
            # A later sentence may explicitly identify the original schedule date
            # as superseded without repeating the amendment's assignment key.
            stated_historical = re.search(
                r"\bdate in the original .{0,40}schedule is superseded\b", line, re.I
            )
            if historical_schedule and not keys:
                addressed = previous_addressed
            previous_addressed = addressed
            if not addressed and not (ASSESSMENT.search(line) or IDENTIFIER.search(line)):
                continue
            matches = list(DATES.finditer(line))
            amendment, amended_title = deadline_amendment(line, matches)
            former_id = None
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
                        "title": amended_title or title[:500],
                        **({"replaces_obligation_id": former_id} if former_id else {}),
                        **({"assessment_id": addressed} if addressed else {}),
                        "interpretation_status": "historical"
                        if historical_schedule
                        or stated_historical
                        or (amended_title and index == 0)
                        or (
                            addressed
                            and index == 0
                            and len(matches) == 2
                            and re.search(r"\bfrom\b", line[: match.start()], re.I)
                        )
                        else "unresolved_amendment"
                        if amendment and not amended_title
                        else "deterministic_candidate",
                        **parsed,
                        "date_offset": offset + match.start(),
                        "evidence": source,
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
                        "deadline_wording": bool(re.search(r"\b(?:due|deadline)\b", line, re.I)),
                        "assignment_deadline_confirmed": False,
                        "student_confirmation_needed": True,
                    }
                )
                if amended_title and index == 0:
                    former_id = results[-1]["id"]
    return results


def match_obligation(obligation, items):
    course = obligation["evidence"].get("course_id")
    items = [item for item in items if course is None or item.get("course_id") == course]
    if key := obligation.get("assessment_id"):
        matched = [item for item in items if item["id"] == key]
        return (
            (matched[0], "explicit_assignment_id", [])
            if len(matched) == 1
            else (None, "no_match", [])
        )
    title = normalized(obligation["title"])
    exact = [i for i in items if normalized(i["title"]) == title]
    identifiers = IDENTIFIER.findall(obligation["title"].casefold())
    if identifiers:
        matching = []
        for item in items:
            other = IDENTIFIER.findall(item["title"].casefold())
            if set(other).intersection(identifiers):
                matching.append((item, other))
        candidates = [{"work_id": item["id"], "title": item["title"]} for item, _ in matching]
        if len(identifiers) == 1 and len(matching) == 1:
            item, other = matching[0]
            has_series = IDENTIFIER_SERIES.search(obligation["title"]) or IDENTIFIER_SERIES.search(
                item["title"]
            )
            if identifiers == other and not has_series:
                method = "exact_title" if item in exact else "unique_embedded_identifier"
                return item, method, candidates
        if candidates:
            return None, "ambiguous", candidates
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
    groups = {}
    activities = [o for o in obligations if o["candidate_kind"] == "classroom_activity"]
    obligations = [o for o in obligations if o["candidate_kind"] != "classroom_activity"]
    for obligation in obligations:
        if obligation["interpretation_status"] == "historical":
            continue
        item, match, candidates = match_obligation(obligation, items)
        if obligation["interpretation_status"] == "unresolved_amendment":
            item, match = None, "ambiguous"
        # Preserve each occurrence and its citation in obligations. Only group
        # identical wording for the same assessment (or the same unmatched title).
        key = (
            item["id"] if item else None,
            obligation["evidence"]["course_id"],
            obligation["evidence"]["passage"],
            obligation["raw_date"],
        )
        group = groups.setdefault(
            key, {"work_id": item["id"] if item else None, "match": match, "occurrences": []}
        )
        if match == "unique_embedded_identifier":
            identifier = IDENTIFIER.search(obligation["title"])
            group.update(
                matched_identifier=identifier.group(),
                assignment_title=item["title"],
                interpretation="Unique assessment identifier among retrieved assignments. Deadline applicability requires review.",
            )
        group["occurrences"].append(
            {"obligation_id": obligation["id"], "evidence": obligation["evidence"]}
        )
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
                {
                    "obligation_id": obligation["id"],
                    "work_id": item["id"],
                    "match": match,
                    **comparison,
                }
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
                        "kind": "candidate_date_difference"
                        if match == "unique_embedded_identifier"
                        and not obligation["deadline_wording"]
                        else "conflicting_deadlines",
                        "certainty": "supported_source_difference",
                        "canvas_date" if source_label == "Canvas" else "reference_date": due,
                        "comparison_timezone": comparison["timezone"],
                        "impact": "The sources report different dates; applicability or an amendment may explain this.",
                        "next_action": "Check the cited versions and ask which deadline applies.",
                    }
                )
    # Present one finding per duplicate group, before the caller caps findings.
    # Comparisons and graph observations retain the original occurrence IDs.
    first_by_id = {
        occurrence["obligation_id"]: group["occurrences"][0]["obligation_id"]
        for group in groups.values()
        for occurrence in group["occurrences"]
    }
    findings = [f for f in findings if f["id"] == first_by_id[f["id"]]]
    return {
        "obligations": obligations,
        "obligation_groups": list(groups.values()),
        "classroom_activities": activities,
        "findings": findings,
        "comparisons": comparisons,
        "limitations": [
            "Recognizes ISO and English full/abbreviated month dates near an assessment term; numeric month/day order, missing years, ambiguous zones and DST transitions require review.",
            "Missing matches do not prove an assessment is absent. Ambiguous titles and missing years require review.",
            "Date-only passages do not establish a time or timezone. No source automatically overrides another.",
        ],
    }


WORD_COUNT = re.compile(r"\b(\d[\d,]*)(?:\s*(?:[-–]|to)\s*(\d[\d,]*))?\s*[- ]?\s*words?\b", re.I)


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


def reported_word_ranges(document):
    # An expressly unresolved pair remains disputed even when the two
    # intervals touch or one source is labeled archived. Bind the statement
    # to its two stated ranges and the same assessment only.
    reported_ranges = {}
    for part, line, offset in passages(document):
        if re.search(
            r"\b(?:does not|doesn't) (?:explicitly )?resolve (?:that|the|this) (?:length )?conflict\b",
            line,
            re.I,
        ):
            ranges = list(
                re.finditer(
                    r"\b(\d{1,3}(?:,\d{3}){1,2}|\d{1,7})\s*(?:[-–]|to)\s*(\d{1,3}(?:,\d{3}){1,2}|\d{1,7})\b",
                    line,
                    re.I,
                )
            )
            if len(ranges) != 2:
                continue
            first, second = ranges
            # The second range can elide "words" in a direct comparison.
            if not re.match(r"\s+words?\b", line[first.end() :], re.I):
                continue
            if not re.match(r"\s+words?\b", line[second.end() :], re.I) and not re.fullmatch(
                r"\s+words?,?\s+(?:while|but|whereas) (?:the )?(?:archived |older |current )?(?:rubric|brief|template) (?:states|requires|specifies)\s+",
                line[first.end() : second.start()],
                re.I,
            ):
                continue
            pair = tuple(tuple(int(n.replace(",", "")) for n in match.groups()) for match in ranges)
            if all(low <= high for low, high in pair) and pair[0] != pair[1]:
                reported_ranges[pair] = citation(document, part, line, offset)
    return reported_ranges


def requirements(document):
    rules = []
    header_keys = set()
    for _, text, _ in passages(document):
        if header := BRIEF_HEADER.match(text):
            header_keys.add(header[1])
        elif re.match(r"^Source ID .+ \| Assessments ", text):
            header_keys.update(re.findall(ASSESSMENT_KEY, text.split("| Assessments ")[-1]))
    archived_document = any(
        re.match(r"^#\s+Archived\b", text, re.I) for _, text, _ in passages(document)
    )
    reported_ranges = reported_word_ranges(document)
    for part, line, offset in requirement_clauses(document):
        start = len(rules)
        historical = (
            archived_document
            or bool(re.search(r"^the older .+? template is superseded by\b", line, re.I))
            or bool(
                re.match(
                    r"^(?:(?:the|an?)\s+)?(?:archived|earlier|previous|superseded)\s+(?:rubric|handout|assignment|requirement|instructions?)\b",
                    line,
                    re.I,
                )
            )
        )
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
        counts = list(WORD_COUNT.finditer(line))
        for index, match in enumerate(counts):
            # Each separately counted discussion component needs its own draft.
            scope = None
            if re.search(r"\brepl(?:y|ies)\b", line, re.I):
                prefix = line[counts[index - 1].end() if index else 0 : match.start()]
                scope = (
                    "reply"
                    if index or re.search(r"\brepl(?:y|ies)\b", prefix, re.I)
                    else "initial_post"
                )
            elif re.search(r"\binitial post\b", line, re.I):
                scope = "initial_post"
            low = int(match.group(1).replace(",", ""))
            high = int((match.group(2) or match.group(1)).replace(",", ""))
            qualifier = line[counts[index - 1].end() if index else 0 : match.start()]
            if re.search(r"\b(?:at least|minimum)\b", qualifier, re.I):
                high = None
            if re.search(r"\b(?:at most|maximum|up to)\b", qualifier, re.I):
                low = 0
            rules.append(
                {
                    "type": "word_count",
                    "scope": scope,
                    "minimum": low,
                    "maximum": high,
                    "mandatory": not optional and not ambiguous,
                    "interpretation_status": "ambiguous"
                    if ambiguous
                    else "explicit_numeric_candidate",
                    "evidence": citation(document, part, line, offset),
                }
            )
        submission = re.search(
            r"\b(?:submit|upload)\b|^format\s*:|^(?=(?:PDF|DOCX|PPTX|TXT|XLSX|CSV)\s+format\b)",
            line,
            re.I,
        )
        if submission or historical and re.search(r"\bhandout stated\b", line, re.I):
            instruction = line[submission.end() :] if submission else line
            segments = re.split(
                r"\s+(?:and|plus)\s+(?=(?:one\s+|an?\s+)?(?:PDF|DOCX|PPTX|TXT|XLSX|CSV)\b)",
                instruction,
                flags=re.I,
            )
            for segment in segments:
                formats = sorted(
                    {
                        fmt.lower()
                        for fmt in re.findall(r"\b(?:PDF|DOCX|PPTX|TXT|XLSX|CSV)\b", segment, re.I)
                    }
                )
                if formats:
                    rules.append(
                        {
                            "type": "submission_format",
                            "formats": formats,
                            "scope": segment.strip(" .,:") if len(segments) > 1 else None,
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
        target = re.match(rf"^For ({ASSESSMENT_KEY})\b", line)
        assignment = (
            target[1] if target else next(iter(header_keys)) if len(header_keys) == 1 else None
        )
        for rule in rules[start:]:
            if assignment:
                rule["assessment_id"] = assignment
                if rule["type"] == "word_count":
                    for pair, witness in reported_ranges.items():
                        bounds = (rule["minimum"], rule["maximum"])
                        if bounds in pair:
                            rule["reported_alternative"] = {
                                "range": list(pair[1 - pair.index(bounds)]),
                                "evidence": witness,
                            }
            if historical:
                rule.update(mandatory=False, interpretation_status="historical")
    return rules


def instruction_findings(documents, draft=None, *, draft_complete=True):
    rules = [rule for doc in documents for rule in requirements(doc)]
    conflicts = []
    for index, left in enumerate(rules):
        for right in rules[index + 1 :]:
            if left["type"] != right["type"]:
                continue
            if (
                left.get("assessment_id")
                and right.get("assessment_id")
                and left["assessment_id"] != right["assessment_id"]
            ):
                continue
            if (
                left["evidence"]["course_id"]
                and right["evidence"]["course_id"]
                and left["evidence"]["course_id"] != right["evidence"]["course_id"]
            ):
                continue
            if left.get("scope") != right.get("scope"):
                continue
            reported = (
                left.get("assessment_id")
                and left.get("assessment_id") == right.get("assessment_id")
                and any(
                    rule.get("reported_alternative", {}).get("range")
                    == [other.get("minimum"), other.get("maximum")]
                    for rule, other in ((left, right), (right, left))
                )
            )
            if not reported and (not left["mandatory"] or not right["mandatory"]):
                continue
            if left["type"] == "word_count":
                conflict = reported or max(left["minimum"], right["minimum"]) > min(
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
                        **(
                            {
                                "evidence": next(
                                    rule["reported_alternative"]["evidence"]
                                    for rule in (left, right)
                                    if rule.get("reported_alternative")
                                )
                            }
                            if reported
                            else {}
                        ),
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
    disputed = [rule for conflict in conflicts for rule in (conflict["left"], conflict["right"])]
    review = None
    if draft is not None:
        words = len(re.findall(r"\b\w+(?:['’-]\w+)*\b", draft))
        review = {
            "word_count": words,
            "classification": "deterministic_calculation_on_student_input",
            "checks": [
                {
                    "rule": rule,
                    "satisfies_stated_count": None
                    if not draft_complete
                    or rule in disputed
                    or rule.get("scope")
                    or (
                        "excluding" in rule["evidence"]["passage"].lower()
                        and re.search(
                            r"(?im)^\s*(?:#{1,6}\s*)?(?:references|appendix|exhibits?|tables?)\b",
                            draft,
                        )
                    )
                    else words >= rule["minimum"]
                    and (rule["maximum"] is None or words <= rule["maximum"]),
                }
                for rule in rules
                if rule["type"] == "word_count" and rule["mandatory"]
            ],
            "grade_prediction": None,
            "limitations": [
                "Count covers the supplied text. A partial draft, multiple drafts, separate post and reply bodies, or excluded sections require review.",
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
    """the and with this that from have will your course exam quiz paper study students should were there which their these those using into about between through than then also each only more some when what they been used material assignment syllabus results methods discussion introduction figure table references professor instructor doctor canvas lecture chapter reading readings
    student email office hours spring summer autumn winter monday tuesday wednesday thursday friday
    university copyright reserved rights semester schedule submit submission deadline access available
    please following questions information important document module class details example examples
    include includes learning objective objectives explain describe compare required assigned pages
    first second third other would could because however their those where there these which while
    about often several across within during before after based general given different private redacted person withheld content privacy uncertainty""".split()
)


def repeated_concepts(documents):
    # Keep offsets for at most three sources per term. Materializing every possible
    # citation is expensive for a pack of long papers; only the winners need one.
    counts, occurrences = Counter(), {}
    names = set()
    for doc in documents:
        for part in doc["parts"]:
            for match in re.finditer(
                r"\b(?i:professor|prof\.|dr\.|instructor)[: ]+((?:[A-Z][a-z]+[ \t]*){1,3})",
                part["text"],
            ):
                names.update(match[1].casefold().split())
    for doc in documents:
        seen = set()
        for part in doc["parts"]:
            for match in re.finditer(r"\b[a-zA-Z]{5,}\b", part["text"]):
                word = match.group().lower()
                if word in STOPWORDS or word in names or word in seen:
                    continue
                seen.add(word)
                samples = occurrences.setdefault(word, [])
                if len(samples) < 3:
                    samples.append((doc, part, max(0, match.start() - 60)))
        counts.update(seen)
    return [
        {
            "term": word,
            "documents": count,
            "classification": "deterministic_keyword_overlap",
            "evidence": [
                citation(doc, part, part["text"][start : start + 220], start)
                for doc, part, start in occurrences[word]
            ],
            "exam_coverage_confirmed": False,
        }
        for word, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:15]
        if count >= 2
    ]
