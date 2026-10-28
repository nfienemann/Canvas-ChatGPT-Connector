"""Evidence sufficiency and scoped reconciliation; no implicit recency authority."""

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import ResolutionDecision, UncertaintyAssessment


def assess_coverage(coverage, decision_class, *, now, contested=False):
    if decision_class not in {"policy", "deadline", "summary", "graduation"}:
        raise ValueError("Unknown evidence requirement.")
    reasons, missing, steps = [], [], []
    if not coverage:
        return UncertaintyAssessment(
            status="insufficient", reasons=("NO_EVIDENCE",), next_steps=("request_source",)
        )
    for item in coverage:
        if item.source.expires_at <= now or item.source.observed_at > now:
            reasons.append("SOURCE_STALE")
        if not item.complete or item.extraction != "complete":
            reasons.append("COVERAGE_INCOMPLETE")
            if item.total:
                missing.extend(
                    f"{item.source.id}:{item.unit}:{i}"
                    for i in range(1, item.total + 1)
                    if i not in item.seen
                )
            else:
                missing.append(f"{item.source.id}:extent_unknown")
        if item.unreadable or item.extraction == "unreadable":
            reasons.append("EXTRACTION_UNREADABLE")
            steps.append("render_and_review_source")
    if contested:
        reasons.append("CONFLICTING_EVIDENCE")
        steps.append("seek_authoritative_clarification")
    if reasons:
        steps.append("inspect_missing_evidence_or_abstain")
    status = (
        "contested"
        if contested
        else "stale"
        if "SOURCE_STALE" in reasons
        else "provisional"
        if reasons and decision_class == "summary"
        else "insufficient"
        if reasons
        else "sufficient"
    )
    # Sufficiency describes observation, never permission or official graduation.
    return UncertaintyAssessment(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        missing=tuple(missing),
        next_steps=tuple(dict.fromkeys(steps)),
    )


def reconcile(claims, *, now, authority_order=()):
    """authority_order comes from reviewed server configuration, never source text.

    Explicit supersession also requires same verified issuer, exact scope/field,
    complete coverage, current validity and strictly later effective time.
    """
    claims = tuple(claims)
    if not claims:
        return ResolutionDecision(status="unresolved", candidates=(), reasons=("NO_EVIDENCE",))
    keys = {(c.coverage.source.scope, c.entity, c.field) for c in claims}
    if len(keys) != 1 or len({c.id for c in claims}) != len(claims):
        raise ValueError("Reconciliation requires unique claims in one exact scope and field.")
    if len(set(authority_order)) != len(authority_order):
        raise ValueError("Authority order must be unique.")
    active = [
        c
        for c in claims
        if c.coverage.source.observed_at <= now < c.coverage.source.expires_at
        and (c.effective_at is None or c.effective_at <= now)
    ]
    superseded = set()
    for new in active:
        for old in active:
            if (
                old.id in new.supersedes
                and new.issuer
                and new.issuer == old.issuer
                and new.authority == old.authority != "unverified"
                and new.coverage.complete
                and new.coverage.extraction == "complete"
                and new.effective_at
                and old.effective_at
                and old.effective_at < new.effective_at
            ):
                superseded.add(old.id)
    remaining = [c for c in active if c.id not in superseded]
    eligible = [
        c
        for c in remaining
        if c.coverage.complete and c.coverage.extraction == "complete" and c.basis == "observed"
    ]
    selected, reasons = None, []
    if len(active) != len(claims):
        reasons.append("STALE_OR_FUTURE_EVIDENCE")
    if len(eligible) != len(remaining):
        reasons.append("UNVERIFIED_OR_INCOMPLETE_EVIDENCE")
    values = {fingerprint(c.value) for c in remaining}
    if len(values) == 1 and eligible and len(eligible) == len(remaining):
        selected = sorted(eligible, key=lambda c: c.id)[0].id
        reasons.append("EXPLICIT_SUPERSESSION" if superseded else "CONSISTENT_OBSERVATIONS")
    elif len(values) > 1:
        ranked = [
            (authority_order.index(c.authority), c)
            for c in eligible
            if c.authority in authority_order and c.authority != "unverified"
        ]
        if ranked:
            best = min(rank for rank, _ in ranked)
            winners = [c for rank, c in ranked if rank == best]
            if len({fingerprint(c.value) for c in winners}) == 1:
                selected = sorted(winners, key=lambda c: c.id)[0].id
                reasons.append("CONFIGURED_AUTHORITY_RULE")
        if not selected:
            reasons.append("CONTESTED_CLAIMS")
    return ResolutionDecision(
        status="resolved" if selected else "stale" if not active else "unresolved",
        selected=selected,
        candidates=claims,
        superseded=tuple(sorted(superseded)),
        reasons=tuple(reasons),
        clarification=None
        if selected
        else f"Which {claims[0].field} applies to this item? Review the cited sources and any explicit update.",
    )
