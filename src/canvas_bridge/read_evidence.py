"""Evidence for bounded, authorized Canvas responses."""

from datetime import datetime

from canvas_bridge.domain import Coverage, Meta, utcnow

REUSED_PAGE_ORIGINS = {"cache", "coalesced", "conditional_revalidation"}


def read_observation(receipts, pages, now):
    """Oldest observation and greatest reuse age across the accepted responses."""
    if not pages:
        return "not_refreshed", None, None
    if len(receipts) != pages:
        return "unknown", None, None
    times, reused = [], []
    for receipt in receipts:
        origin = receipt.get("source")
        try:
            stamp = datetime.fromisoformat(receipt.get("retrieved_at"))
        except (TypeError, ValueError):
            return "unknown", None, None
        if stamp.tzinfo is None or (origin != "upstream" and origin not in REUSED_PAGE_ORIGINS):
            return "unknown", None, None
        times.append(stamp)
        if origin in REUSED_PAGE_ORIGINS:
            reused.append(stamp)
    age = max(0, int((now - min(reused)).total_seconds())) if reused else 0
    return "cached" if reused else "live", min(times), age


def collection_scope(course_id, resource, collection, *, reasons=()):
    exhausted = collection.pages > 0 and collection.complete and not collection.failure
    if exhausted and not reasons:
        state = "complete"
    elif collection.failure == "permission_denied":
        state = "permission_denied"
    elif collection.failure == "not_refreshed":
        state = "not_refreshed"
    elif collection.failure == "unsupported_feature":
        state = "unsupported"
    else:
        state = "partial" if collection.pages else "unavailable"
    return Coverage(
        course_ref=course_id,
        resource=resource,
        state=state,
        pages_consumed=collection.pages,
        pagination_complete=exhausted,
        warning=", ".join(sorted(reasons)) or None,
        **collection.failure_fields(),
    )


def read_meta(receipts, responses, coverage):
    freshness, stamp, _ = read_observation(receipts, responses, utcnow())
    meta = Meta(
        freshness=freshness,
        coverage=coverage,
        upstream_cache=[r for r in receipts if r.get("source") in REUSED_PAGE_ORIGINS][:100],
    )
    if stamp:
        meta.retrieved_at = stamp
    return meta
