"""Conservative text-to-rule candidates. Text is evidence, never executable policy."""

import re
from decimal import Decimal

from canvas_bridge.grading_engine import GradePolicy, PolicyReview, digest

SPECIAL = {
    "extra_credit": r"extra[ -]credit|bonus points?",
    "attendance_participation": r"attendance|participation",
    "late_penalty": r"late (?:work|submission|penalt)|deduct",
    "curve_adjustment": r"curv(?:e|ed|ing)|grade adjustment|round(?:ing|ed)?",
    "exam_replacement": r"replac(?:e|es|ement)|substitut",
    "special_condition": r"must pass|minimum.{0,30}(?:exam|grade)|at least.{0,30}(?:exam|grade)|amend|supersed",
    "drop_rule": r"drop(?:ped|ping)?|lowest|highest",
}


def name_key(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def extract_policy(
    documents: list[dict],
    canvas: GradePolicy,
    limitations: list[str],
    review: PolicyReview | None = None,
) -> tuple[dict, GradePolicy]:
    rules = []
    blockers = list(limitations)
    names = {}
    for g in canvas.groups:
        names.setdefault(name_key(g.name), []).append(g.id)
    for doc in documents:
        if not doc["complete"]:
            blockers.append(f"{doc['id']}: source extraction is incomplete.")
        for part in doc["parts"]:
            offset = 0
            for line in part["text"].splitlines(keepends=True):
                quote = line.strip()
                location = {
                    "locator": part["locator"],
                    "offset": offset + len(line) - len(line.lstrip()),
                }
                offset += len(line)
                if not quote:
                    continue
                if len(quote) > 1000:
                    blockers.append(
                        f"{doc['id']}: a text line exceeds the safe rule-parsing budget; its grading relevance is unresolved."
                    )
                    continue
                found = []
                match = re.fullmatch(
                    r"\s*(.+?)\s*(?::|[-–—]|\s)\s*(\d{1,3}(?:\.\d{1,4})?)\s*%\s*[.;]?\s*", quote
                )
                if match:
                    label, weight = match.groups()
                    ids = names.get(name_key(label), [])
                    if re.fullmatch(r"[A-F][+-]?", label.strip(), re.I):
                        found.append(
                            (
                                "letter_threshold",
                                {"letter": label.strip(), "percent": weight},
                                False,
                            )
                        )
                    else:
                        found.append(
                            (
                                "category_weight",
                                {
                                    "category": label,
                                    "weight": weight,
                                    "group_id": ids[0] if len(ids) == 1 else None,
                                },
                                len(ids) == 1,
                            )
                        )
                if re.fullmatch(
                    r"(?:the |your )?(?:course |final )?grade (?:is |will be )?(?:based on |calculated (?:as|using) )?(?:total )?points earned\s*(?:/|divided by)\s*(?:total )?points possible[.!]?",
                    quote,
                    re.I,
                ):
                    found.append(("points_method", {"method": "points"}, True))
                drop = re.fullmatch(
                    r"(.+?):\s*drop (?:the )?(?:lowest (\d+)|(\d+) lowest)(?: scores?| assignments?)?[.!]?",
                    quote,
                    re.I,
                )
                if drop:
                    ids = names.get(name_key(drop[1]), [])
                    count = int(drop[2] or drop[3])
                    found.append(
                        (
                            "drop_lowest",
                            {"count": count, "group_id": ids[0] if len(ids) == 1 else None},
                            len(ids) == 1 and count <= 100,
                        )
                    )
                if not found:
                    for kind, pattern in SPECIAL.items():
                        if re.search(pattern, quote, re.I):
                            found.append((kind, {"interpretation": "not_modeled"}, False))
                    if not found and re.search(
                        r"\d.*%|\b(?:grading|grade weights?|total points)\b", quote, re.I
                    ):
                        found.append(
                            (
                                "uninterpreted_grading_passage",
                                {"interpretation": "requires_review"},
                                False,
                            )
                        )
                for kind, value, supported in found:
                    if len(rules) >= 100:
                        blockers.append("Rule extraction exceeded the 100-rule budget.")
                        break
                    rule = {
                        "rule_type": kind,
                        "value": value,
                        "source_document": doc["id"],
                        "source_url": doc["url"],
                        "source_location": location,
                        "document_version": doc["version"],
                        "source_passage": quote[:1000],
                        "passage_truncated": len(quote) > 1000,
                        "interpretation_status": "deterministic_candidate"
                        if supported
                        else "unsupported_or_ambiguous",
                        "student_confirmation_needed": True,
                        "supported": supported and len(quote) <= 1000,
                    }
                    rule["id"] = digest(rule)[:40]
                    rules.append(rule)
    descriptors = [
        {k: d[k] for k in ("id", "title", "url", "version", "complete")} for d in documents
    ]
    version = digest(
        {
            "documents": descriptors,
            "rules": rules,
            "canvas_groups": [g.model_dump(mode="json") for g in canvas.groups],
        }
    )
    interpreted = GradePolicy(
        basis="syllabus", version=version, groups=[g.model_copy(deep=True) for g in canvas.groups]
    )
    # Canvas drop settings must never silently become syllabus policy.
    for g in interpreted.groups:
        g.drop_lowest = g.drop_highest = 0
        g.never_drop = []
        g.weight = None
    if not documents:
        blockers.append("No readable syllabus source was located or supplied.")
    unsupported = [r["id"] for r in rules if not r["supported"]]
    if unsupported:
        blockers.append(
            "Some grading passages are unsupported or ambiguously mapped: " + ", ".join(unsupported)
        )
    weights = {}
    drops = {}
    for rule in rules:
        if not rule["supported"]:
            continue
        if rule["rule_type"] == "category_weight":
            weights.setdefault(rule["value"]["group_id"], set()).add(
                Decimal(rule["value"]["weight"])
            )
        if rule["rule_type"] == "drop_lowest":
            drops.setdefault(rule["value"]["group_id"], set()).add(rule["value"]["count"])
    points = any(r["rule_type"] == "points_method" for r in rules)
    if (weights and points) or any(len(v) != 1 for v in (*weights.values(), *drops.values())):
        blockers.append(
            "Conflicting policies or versions; no automatic latest-document precedence is applied."
        )
    elif weights:
        interpreted.method = "weighted"
        if set(weights) != {g.id for g in interpreted.groups}:
            blockers.append(
                "Syllabus categories do not map uniquely and completely to Canvas categories."
            )
        for group in interpreted.groups:
            if group.id in weights:
                group.weight = next(iter(weights[group.id]))
    elif points:
        interpreted.method = "points"
    else:
        blockers.append("No complete supported grading method was extracted.")
    for group in interpreted.groups:
        if group.id in drops and len(drops[group.id]) == 1:
            group.drop_lowest = next(iter(drops[group.id]))
    supported_ids = {r["id"] for r in rules if r["supported"]}
    reviewed = bool(
        review
        and review.policy_version == version
        and set(review.confirmed_rule_ids) == supported_ids
        and review.complete_policy_confirmed
        and review.applicability_confirmed
    )
    if not reviewed:
        blockers.append(
            "Student review of this exact policy version, interpretation, completeness, and applicability is required; never infer that review from a request for a calculation."
        )
    else:
        interpreted.empty_categories = review.empty_categories
        for rule in rules:
            if rule["supported"]:
                rule["interpretation_status"] = "student_confirmed_interpretation"
                rule["student_confirmation_needed"] = False
    interpreted.rule_ids = sorted(supported_ids)
    interpreted.blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": "1.0",
        "policy_version": version,
        "documents": descriptors,
        "rules": rules,
        "interpretation": "student_reviewed" if reviewed else "unverified_candidates",
        "missing_information": interpreted.blockers,
        "coverage": {
            "announcements": "not_retrieved",
            "linked_documents": "only_explicit_or_discovered_syllabus_materials",
            "version_precedence": "not_assumed",
            "instructor_verification": "not_available",
        },
        "review_instructions": "Only submit PolicyReview after the student confirms the listed interpretations, all applicable grading rules, and absence/resolution of amendments. Confirmation is an assumption, not institutional verification.",
    }, interpreted
