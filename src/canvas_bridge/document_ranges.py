"""Bounded public diagnostics for authorized, version-checked documents."""

from canvas_bridge.domain import DomainError


def range_message(first, last, count):
    return f"Requested range {first} to {last}. Choose a range within 1 to {count}."


def safe_range_fields(data):
    first, last, count = (data.get(k) for k in ("page_start", "page_end", "page_count"))
    if (
        all(type(n) is int for n in (first, last, count))
        and 1 <= first <= last <= 200
        and 1 <= count < last
    ):
        return {"page_start": first, "page_end": last, "page_count": count}
    return {}


def validate_document_range(first, last, count):
    if type(count) is not int or not 1 <= count <= 200:
        raise DomainError(
            "unsupported_feature",
            "A usable document length could not be established.",
            reason_code="DOCUMENT_LENGTH_UNAVAILABLE",
        )
    if last > count:
        raise DomainError(
            "needs_input",
            range_message(first, last, count),
            reason_code="DOCUMENT_RANGE_OUT_OF_BOUNDS",
            details={"page_start": first, "page_end": last, "page_count": count},
        )
