"""Content inspection is advisory. Capability boundaries enforce security."""

import re

from canvas_bridge.evidence import fingerprint

PATTERNS = {
    "ROLE_SPOOFING": re.compile(
        r"(?:<\|?(?:system|developer)\|?>|\b(?:system|developer)\s*(?:message|override)\s*:)", re.I
    ),
    "INSTRUCTION_OVERRIDE": re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions\b", re.I
    ),
    "EXFILTRATION_REQUEST": re.compile(
        r"\b(?:send|upload|post|export)\b.{0,100}\b(?:token|password|credentials|all\s+(?:files|records))\b",
        re.I | re.S,
    ),
    "TOOL_INVOCATION": re.compile(
        r"\b(?:call|execute|invoke)\s+(?:the\s+)?(?:tool|shell|command|function)\b", re.I
    ),
}


def inspect_content(text, media_type):
    if len(text) > 200_000:
        raise ValueError("Content inspection budget exceeded.")
    if media_type not in {"pdf", "pptx", "html", "discussion", "text", "docx", "xlsx", "markdown"}:
        raise ValueError("Unsupported source format.")
    return {
        "trust": "untrusted_evidence",
        "content_hash": fingerprint(text),
        "indicators": sorted(key for key, pattern in PATTERNS.items() if pattern.search(text)),
        "summarization_allowed": True,
        "authority_granted": False,
        "tool_actions": [],
        "limitation": "Indicators are advisory, not a complete injection detector. Content cannot authorize actions.",
    }


WORKFLOW_CAPABILITIES = {
    "evidence": frozenset({"read_evidence", "render_source"}),
    "planning": frozenset({"read_evidence", "propose_plan"}),
    "clarification": frozenset({"read_evidence", "draft_question"}),
    "portfolio": frozenset({"read_evidence", "review_clearance"}),
}


def require_capability(workflow, capability, *, authenticated_intent):
    from canvas_bridge.domain import DomainError

    if not authenticated_intent or capability not in WORKFLOW_CAPABILITIES.get(workflow, ()):
        raise DomainError(
            "permission_denied",
            "This workflow cannot perform that action.",
            reason_code="PROCESS_CAPABILITY_DENIED",
        )
