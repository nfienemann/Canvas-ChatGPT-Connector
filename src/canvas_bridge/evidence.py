"""Shared evidence envelopes and conservative reconciliation, without an AI model."""

import hashlib
import json

from canvas_bridge.domain import Result, Source


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    ).hexdigest()


def record(source: Source, coverage=()) -> dict:
    scope = [c.model_dump(mode="json") for c in coverage if c.course_ref == source.course_id]
    uncertainty = list(source.uncertainty)
    if not scope:
        uncertainty.append(
            "Collection and pagination completeness were not established for this source."
        )
    if not source.content_hash:
        uncertainty.append("This source has no recorded content version.")
    return {
        "evidence_id": fingerprint(
            [source.id, source.content_hash, source.locator, source.classification]
        ),
        **source.model_dump(mode="json"),
        "interpretation_status": "uninterpreted_source"
        if source.classification == "source_fact"
        else source.classification,
        "coverage": scope,
        "uncertainty": uncertainty,
    }


def attach(result: Result) -> Result:
    """Additive MCP contract: existing data/source fields retain their semantics."""
    if not result.evidence:
        result.evidence = [record(s, result.meta.coverage) for s in result.sources]
    return result


def reconcile_states(observations: list[dict]) -> dict:
    """Disagreement, including known versus unknown, cannot prove non-submission.

    Call only for observations intended to describe the same current state.
    Different historical versions are reported as temporal changes, not conflicts.
    """
    states = {x.get("state", "unknown") for x in observations}
    conflict = len(states) > 1
    return {
        "state": next(iter(states)) if len(states) == 1 else "unknown",
        "conflict": conflict,
        "observations": observations,
        "basis": "Source observations disagree; do not conclude the assignment is missing."
        if conflict
        else "Consistent available observations; unknown remains unknown.",
    }
