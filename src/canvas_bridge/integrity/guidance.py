"""Shared non-generative guidance; never grants source or instructor permission."""


def safe_guidance():
    return {
        "permitted_alternatives": [
            "administration",
            "requirements",
            "assignment_planning",
            "seek_instructor_clarification",
        ],
        "applicable_limits": [
            "Administrative alternatives require independently authorized sources and sharing permission.",
            "Only the exact permitted activity is allowed; brainstorming does not permit submission drafting.",
            "Acknowledging uncertainty is not instructor permission and cannot override a prohibition.",
            "This guidance does not generate assessed submission content or send any message.",
        ],
        "evidence_needed": [
            "Current applicable course and assessment AI-use rules with source locations and complete coverage.",
            "Verified instructor clarification covering the exact activity, assessment and any conflicting rules.",
        ],
        "clarification_suggestions": [
            "Ask which AI activities are permitted for this assessment and which outputs must remain your own work.",
            "Ask which rule controls any conflict and what disclosure or citation is required. Review and send any request yourself.",
        ],
    }
