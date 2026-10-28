"""Conservative, contextual English rule candidates; unknown wording never grants access.

This is deliberately not a general language-model interpretation service. Recognized
clauses retain their original passage. Authority, scope and completeness are evaluated
separately. Prompt instructions, quotations and illustrative policies cannot grant use.
"""

import re

from canvas_bridge.integrity.models import LEARNING, SUBSTANTIVE, PolicySource, Rule
from canvas_bridge.integrity.models import Activity as A

AI = re.compile(
    r"\b(?:ai|genai|generative artificial intelligence|artificial intelligence|chatgpt)\b", re.I
)
INJECTION = re.compile(
    r"ignore (?:all |previous |the |academic )?(?:instructions|polic|integrity|checks)|system prompt|developer override|bypass",
    re.I,
)
ILLUSTRATION = re.compile(
    r"sample (?:syllabus|polic|statement)|illustrative|for example|hypothetical|quoted|quotation",
    re.I,
)
ADOPTION = re.compile(
    r"\b(?:we|i|this course|the instructor) (?:hereby )?adopts?\b|\b(?:policy|statement) (?:is|has been) adopted for this course\b",
    re.I,
)


def enumerated_denial(line):
    """Narrow only a completely recognized prohibition, never an unknown remainder."""
    match = re.fullmatch(r"(?:generative )?ai (?:must not|may not) (.+?)[.!]?", line)
    if not match:
        return None
    activities = set()
    for clause in re.split(r",\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+", match[1]):
        clause = clause.strip().rstrip(".!;")
        for pattern, values in (
            (
                r"draft (?:submission prose|submissions?|answers?)",
                {A.DRAFT, A.SOLVE, A.DISCUSSION, A.ANSWER},
            ),
            (r"produce (?:a )?substantive outline", {A.OUTLINE}),
            (r"rewrite (?:the )?(?:memo|submission|report|essay)", {A.REWRITE}),
            (r"generate assessed (?:diagrams?|slides?)", {A.DELIVERABLE}),
        ):
            if re.fullmatch(pattern, clause):
                activities.update(values)
                break
        else:
            return None
    return activities or None


def parse(source: PolicySource) -> list[Rule]:
    if source.authority == "illustrative":
        return []
    result = []
    if len(source.parts) > 200 or any(len(p.get("text", "")) > 100_000 for p in source.parts):
        result.append(
            Rule(
                effect="ambiguous",
                activities=SUBSTANTIVE | LEARNING,
                source_id=source.id,
                source_version=source.version,
                locator="Interpretation coverage",
                passage="",
                condition="Source exceeds the bounded interpretation budget; review unread content.",
            )
        )
    for part in source.parts[:200]:
        text = part.get("text", "")[:100_000]
        # Do not detach quoted/illustrative clauses from the context labeling them.
        for paragraph in re.split(r"\n\s*\n", text):
            relevant = AI.search(paragraph)
            if not relevant:
                continue
            if ILLUSTRATION.search(paragraph) and not ADOPTION.search(paragraph):
                continue
            injected = bool(INJECTION.search(paragraph))
            for original in re.split(r"(?<=[.!?])\s+|\n", paragraph):
                line = original.strip()
                if not line or not AI.search(line):
                    continue
                if len(line) > 2500:
                    result.append(
                        Rule(
                            effect="ambiguous",
                            activities=SUBSTANTIVE,
                            source_id=source.id,
                            source_version=source.version,
                            locator=part.get("locator", "Text"),
                            passage=line[:2500],
                            condition="Policy sentence exceeds the reviewed interpretation budget.",
                        )
                    )
                    continue
                lower = line.casefold().replace("’", "'")
                if re.search(
                    r"(?:with |there is |contains )no (?:explicit )?ai (?:rule|policy|guidance|statement)",
                    lower,
                ):
                    continue
                if line.startswith((">", '"', "“")):
                    continue
                all_activities = (
                    SUBSTANTIVE | LEARNING
                    if re.search(
                        r"\b(?:all|any) (?:use of )?(?:generative )?ai|in this course|course learning",
                        lower,
                    )
                    else SUBSTANTIVE
                )
                exam_only = bool(
                    re.search(
                        r"during (?:the |any )?(?:quiz|exam|test)|on (?:the )?(?:final exam|quiz|examination)",
                        lower,
                    )
                )
                assessment_only = bool(
                    re.search(
                        r"\b(?:assignment|assessed|submission|coursework|course work)\b", lower
                    )
                )
                part_locator = part.get("locator", "Text")

                def add(
                    effect,
                    activities,
                    condition=None,
                    *,
                    exam=exam_only,
                    locator=part_locator,
                    passage=line,
                    assessed=assessment_only,
                ):
                    result.append(
                        Rule(
                            effect=effect,
                            activities=frozenset(activities),
                            source_id=source.id,
                            source_version=source.version,
                            locator=locator,
                            passage=passage,
                            assessment_only=assessed,
                            exam_only=exam,
                            condition=condition,
                        )
                    )

                # Negation and conditional prohibitions require a reviewer; keyword
                # matching must not turn "not prohibited" into a confirmed ban.
                if injected and not re.search(
                    r"prohibit|forbid|banned|not allowed|must not|may not", lower
                ):
                    add(
                        "ambiguous",
                        all_activities,
                        "Untrusted instruction text requires policy review.",
                    )
                    continue
                if re.search(
                    r"(?:must|requires?|responsible for).{0,65}(?:obtain|seek|instructor).{0,45}permission|instructor permission (?:is )?required|(?:with|unless|except|only if|provided|subject to).{0,65}(?:permission|instructor approval)|without.{0,35}(?:permission|instructor approval)",
                    lower,
                ):
                    add("permission_required", SUBSTANTIVE)
                    # A conditional allowance is not the instructor permission it
                    # requires. Do not turn its narrower activity into a grant.
                    continue
                if re.search(r"not (?:prohibited|forbidden|banned)|does not prohibit", lower):
                    add("ambiguous", all_activities)
                    continue
                if re.search(r"unless|except (?:when|with|for)|if .*prohibit", lower):
                    add(
                        "ambiguous",
                        all_activities,
                        "The exception to this restriction requires policy review.",
                    )
                    continue
                if re.search(
                    r"only (?:institution[ -])?approved|institution-approved|university-approved",
                    lower,
                ):
                    add(
                        "approved_tool_required",
                        SUBSTANTIVE,
                        "Verified approval of this tool is required.",
                    )
                if re.search(
                    r"\b(?:cit(?:e|ed|ation)|disclos(?:e|ed|ure)|attribut(?:e|ed|ion))\b", lower
                ):
                    add(
                        "disclosure",
                        SUBSTANTIVE,
                        "Disclose the AI assistance and cite it as required by the source; verify references.",
                    )
                if re.search(r"prepare for (?:the )?exam.{0,40}(?:but )?not during", lower):
                    add("allow", {A.EXAM_PREPARATION}, exam=False)
                    add("deny", SUBSTANTIVE, exam=True)
                    continue
                positive = bool(
                    re.search(
                        r"\b(?:may|can)\s+(?!not\b)|\bis (?:explicitly )?(?:allowed|permitted)\b",
                        lower,
                    )
                )
                primary_denial = bool(
                    re.search(
                        r"\b(?:must not|may not|prohibit(?:ed|s)?|forbid(?:den|s)?|banned|not allowed|not permitted)\b",
                        lower,
                    )
                )
                if (
                    positive
                    and not primary_denial
                    and re.search(
                        r"(?:only|limited to).{0,35}(?:spelling|grammar|proofread|mechanical)|\b(?:spelling and grammar|grammar and spelling|mechanical corrections?) only\b",
                        lower,
                    )
                ):
                    add("allow", {A.GRAMMAR}, "Mechanical corrections only.")
                    add("deny", SUBSTANTIVE - {A.GRAMMAR})
                    continue
                if "brainstorm" in lower and positive and not primary_denial:
                    add(
                        "allow",
                        {A.BRAINSTORM},
                        "Brainstorming only; this does not authorize a substantive outline or draft.",
                    )
                    if re.search(
                        r"not (?:for )?(?:writing|draft|submission)|forbid.{0,25}(?:draft|writ)|but not",
                        lower,
                    ):
                        add(
                            "deny",
                            {A.DRAFT, A.REWRITE, A.DISCUSSION, A.CODE, A.ANSWER, A.DELIVERABLE},
                        )
                    elif "only" in lower:
                        add("deny", SUBSTANTIVE - {A.BRAINSTORM})
                    continue
                if re.search(
                    r"\b(?:prohibit(?:ed|s)?|forbid(?:den|s)?|banned|not (?:allowed|permitted)|must not|may not|no (?:generative )?ai)\b",
                    lower,
                ):
                    specific = SUBSTANTIVE if exam_only else all_activities
                    if re.search(r"\b(?:code|coding|programming)\b", lower):
                        specific = {A.CODE, A.DEBUG}
                    specific = enumerated_denial(lower) or specific
                    add("deny", specific)
                    continue
                if re.search(
                    r"\b(?:may be used|may use|is (?:explicitly )?(?:allowed|permitted)|tools (?:may|can) be used)\b",
                    lower,
                ):
                    scoped = set()
                    for pattern, activities in (
                        (r"research", {A.RESEARCH}),
                        (r"feedback", {A.FEEDBACK}),
                        (r"data analysis", {A.ANALYSIS}),
                        (r"debug", {A.DEBUG}),
                        (r"outline", {A.OUTLINE}),
                        (r"grammar|spelling|proofread", {A.GRAMMAR}),
                        (r"code generation|write code|generate code", {A.CODE}),
                    ):
                        if re.search(pattern, lower):
                            scoped.update(activities)
                    if scoped:
                        add(
                            "allow",
                            scoped,
                            "Permission applies only to the activities named in this passage.",
                        )
                        if "only" in lower:
                            add("deny", SUBSTANTIVE - scoped)
                        continue
                    if re.search(
                        r"\b(?:only|if|when|provided|approved|permission)\b", lower
                    ) and not re.search(r"cit(?:e|ed)|disclos|attribut", lower):
                        add(
                            "ambiguous",
                            SUBSTANTIVE,
                            "The conditions on this permission require policy review.",
                        )
                    elif re.search(r"\bfor\b", lower) and not re.search(
                        r"for (?:this |the |all |any )?(?:assignment|course|coursework|course work)\b",
                        lower,
                    ):
                        add("ambiguous", SUBSTANTIVE)
                    else:
                        add("allow", SUBSTANTIVE)
                    continue
                if re.search(
                    r"independent work|unaided|human.authorship|own work|should|might|may", lower
                ):
                    add("ambiguous", SUBSTANTIVE)
    return result
