"""Source-preserving date candidates; no inferred year, locale, zone or DST fold."""

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MONTHS = {
    name: number
    for number, names in enumerate(
        (
            "january jan",
            "february feb",
            "march mar",
            "april apr",
            "may",
            "june jun",
            "july jul",
            "august aug",
            "september sept sep",
            "october oct",
            "november nov",
            "december dec",
        ),
        1,
    )
    for name in names.split()
}
MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
DAY = r"\d{1,2}(?:st|nd|rd|th)?"
YEAR = r"(?:,?\s+\d{4})?"
CLOCK = r"(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?)"
ZONE = r"(?:Z|[+-]\d{2}:?\d{2}|UTC|GMT|(?:[A-Za-z_+-]+/)+[A-Za-z0-9_+-]+|(?-i:[A-Z]{2,5}))"
DATES = re.compile(
    r"(?<![\w/])(?P<day>\d{4}-\d{2}-\d{2}|"
    + MONTH
    + r"\s+"
    + DAY
    + YEAR
    + "|"
    + DAY
    + r"\s+"
    + MONTH
    + YEAR
    + r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?=$|[^\w/]|T\d)"
    + r"(?:(?:T|[ \t,]+(?:at\s+)?)(?P<clock>"
    + CLOCK
    + r")(?=$|[^\w]|Z\b)"
    + r"(?:[ \t]*(?P<zone>"
    + ZONE
    + r")(?![\w/]))?)?",
    re.I,
)


def parse_day(raw):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw)
    if "/" in raw:
        raise ValueError("Numeric month/day order is not established; no locale was inferred.")
    tokens = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw, flags=re.I)
    tokens = re.sub(r"[.,]", "", tokens).lower().split()
    if len(tokens) != 3:
        raise ValueError("Year is not stated in this passage; no year was inferred.")
    month, day = (tokens[0], tokens[1]) if tokens[0] in MONTHS else (tokens[1], tokens[0])
    return date(int(tokens[2]), MONTHS[month], int(day))


def parse_clock(raw):
    value = re.sub(r"[.\s]", "", raw).lower()
    suffix = value[-2:] if value.endswith(("am", "pm")) else None
    if suffix:
        value = value[:-2]
    fields = [int(v) for v in value.split(":")]
    hour = fields[0]
    if suffix:
        if not 1 <= hour <= 12:
            raise ValueError("Invalid 12-hour clock time.")
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    return time(hour, fields[1] if len(fields) > 1 else 0, fields[2] if len(fields) > 2 else 0)


class AmbiguousWallTime(ValueError):
    def __init__(self, choices):
        super().__init__(
            "Source wall time repeats at a daylight-saving transition; no instant was selected."
        )
        self.possible_utc = [value.isoformat().replace("+00:00", "Z") for value in sorted(choices)]


def resolve_zone(wall, raw):
    if raw.upper() in {"Z", "UTC", "GMT"}:
        return wall.replace(tzinfo=UTC)
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", raw):
        digits = raw[1:].replace(":", "")
        hours, minutes = int(digits[:2]), int(digits[2:])
        if hours > 23 or minutes > 59 or raw in {"-00:00", "-0000"}:
            raise ValueError("Invalid or unknown source UTC offset.")
        offset = timedelta(hours=hours, minutes=minutes) * (-1 if raw[0] == "-" else 1)
        return wall.replace(tzinfo=timezone(offset))
    if "/" not in raw:
        raise ValueError(
            "Timezone abbreviation is ambiguous; an explicit offset or IANA zone is required."
        )
    try:
        zone = ZoneInfo(raw)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Source timezone is not recognized.") from exc
    choices = {}
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold)
        instant = candidate.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            choices[instant] = candidate
    if len(choices) > 1:
        raise AmbiguousWallTime(choices)
    if not choices:
        raise ValueError(
            "Source wall time is ambiguous or nonexistent at a daylight-saving transition."
        )
    return next(iter(choices.values()))


def parse_candidate(match):
    raw_clock, raw_zone = match.group("clock"), match.group("zone")
    result = {
        "raw_date": match.group(),
        "date": None,
        "precision": "local_datetime" if raw_clock else "date",
        "timezone": raw_zone,
        "local_datetime": None,
        "normalization_status": "unresolved",
        "uncertainty": [],
    }
    try:
        day = parse_day(match.group("day"))
        if raw_clock:
            wall = datetime.combine(day, parse_clock(raw_clock))
            result["local_datetime"] = wall.isoformat()
            if not raw_zone:
                raise ValueError(
                    "Source clock time has no timezone; the course or student timezone was not substituted."
                )
            result["date"] = resolve_zone(wall, raw_zone).isoformat()
            result["precision"] = "timestamp"
        else:
            result["date"] = day.isoformat()
            result["uncertainty"].append(
                "Date only; time of day and source timezone are not stated."
            )
        result["normalization_status"] = "normalized"
    except AmbiguousWallTime as exc:
        result["possible_utc"] = exc.possible_utc
        result["normalization_status"] = "ambiguous"
        result["uncertainty"].append(str(exc))
    except (ValueError, OverflowError) as exc:
        result["uncertainty"].append(str(exc))
    return result


def compare_deadline(obligation, due, course_timezone):
    """Return comparison evidence, never an amended deadline or a claim of authority."""
    result = {"outcome": "indeterminate", "basis": None, "timezone": None}
    if not obligation["date"]:
        result["reason"] = "The source date/time could not be normalized without assumptions."
        return result
    source_timestamp = obligation["precision"] == "timestamp"
    canvas_timestamp = due["kind"] == "timestamp"
    if source_timestamp and canvas_timestamp:
        left = datetime.fromisoformat(obligation["date"])
        right = datetime.fromisoformat(due["timestamp"])
        different = left.astimezone(UTC) != right.astimezone(UTC)
        result.update(basis="explicit_instants", timezone="explicit source offsets")
    else:
        if source_timestamp or canvas_timestamp:
            try:
                zone = ZoneInfo(course_timezone) if course_timezone else None
            except (ValueError, ZoneInfoNotFoundError):
                zone = None
            if zone is None:
                result["reason"] = "Date-only comparison needs a verified course timezone."
                result["timezone_required"] = True
                return result
            left = (
                datetime.fromisoformat(obligation["date"]).astimezone(zone).date().isoformat()
                if source_timestamp
                else obligation["date"]
            )
            right = (
                datetime.fromisoformat(due["timestamp"]).astimezone(zone).date().isoformat()
                if canvas_timestamp
                else due["local_date"]
            )
            result["timezone"] = course_timezone
        else:
            left, right = obligation["date"], due["local_date"]
        different = left != right
        result.update(
            basis="calendar_date_only", source_calendar_date=left, canvas_calendar_date=right
        )
        result["time_agreement_established"] = False
    result["outcome"] = "different" if different else "same_at_available_precision"
    return result
