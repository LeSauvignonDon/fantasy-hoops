"""Dates, fantasy weeks and transaction timestamps.

Yahoo shows dates without a year ("Oct 24, 10:23 am") in the time zone set
in your Yahoo account. An NBA season spans two calendar years, so we infer
the year from the month: Aug-Dec belong to the season's start year,
Jan-Jul to the next one.

Rust wants transaction timestamps as RFC 3339 text, e.g.
``2026-10-24T10:23:00-07:00`` (see ``Transaction::timestamp``).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"

# "Oct 24, 10:23 am", "Oct 24 10:23am", "Sat, Oct 24, 10:23 AM"
_ABS_TIME_RE = re.compile(_MON + r"\s+(\d{1,2}),?\s+(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.I)
# "Today, 10:23 am", "Yesterday 9:05 pm"
_REL_TIME_RE = re.compile(r"(Today|Yesterday),?\s+(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.I)
# "Oct 24" with no time (some Yahoo layouts)
_ABS_DATE_RE = re.compile(_MON + r"\s+(\d{1,2})\b", re.I)
# "Week 2 (Oct 27 - Nov 2)", "Week 2: Oct 27 – 2", "Week 2 Oct 27 - Nov 2"
_WEEK_RANGE_RE = re.compile(
    r"Week\s+(\d{1,2})\W{0,4}\s*" + _MON + r"\s+(\d{1,2})\s*[-\u2013\u2014]\s*(?:" + _MON + r"\s+)?(\d{1,2})",
    re.I,
)


def season_start_year(today: date) -> int:
    """The calendar year an NBA season started in (2026-27 season -> 2026)."""
    return today.year if today.month >= 8 else today.year - 1


def infer_year(month: int, start_year: int) -> int:
    return start_year if month >= 8 else start_year + 1


def _month(name: str) -> int:
    return MONTHS[name[:3].title()]


def parse_week_ranges(text: str, start_year: int) -> dict[int, tuple[date, date]]:
    """Find every "Week N (Mon D - Mon D)" in ``text``.

    Returns ``{week: (first_day, last_day)}``. Later duplicates are ignored.
    """
    out: dict[int, tuple[date, date]] = {}
    for m in _WEEK_RANGE_RE.finditer(text or ""):
        week = int(m.group(1))
        m1, d1 = _month(m.group(2)), int(m.group(3))
        m2 = _month(m.group(4)) if m.group(4) else m1
        d2 = int(m.group(5))
        try:
            first = date(infer_year(m1, start_year), m1, d1)
            last = date(infer_year(m2, start_year), m2, d2)
        except ValueError:
            continue
        if last < first:  # "Dec 29 - 4" style wrap without a month name
            continue
        out.setdefault(week, (first, last))
    return out


def week_for_date(
    d: date,
    week_ranges: dict[int, tuple[date, date]],
    fallback_week1_start: date | None = None,
) -> int | None:
    """Which fantasy week contains day ``d``?

    1. Use the scraped ranges if one contains ``d``.
    2. Otherwise assume 7-day weeks starting at ``fallback_week1_start``
       (or the start of scraped week 1).
    Returns None if neither works or ``d`` is before week 1.
    """
    for week, (first, last) in sorted(week_ranges.items()):
        if first <= d <= last:
            return week
    start = fallback_week1_start or (week_ranges[1][0] if 1 in week_ranges else None)
    if start is None or d < start:
        return None
    # Week 1 is often longer (season starts mid-week); align on known ranges
    # if we have any, otherwise plain 7-day steps.
    if week_ranges:
        last_week, (_, last_day) = max(week_ranges.items(), key=lambda kv: kv[1][1])
        if d > last_day:
            return last_week + 1 + (d - last_day - timedelta(days=1)).days // 7
    return 1 + (d - start).days // 7


def _to_24h(hour: int, ampm: str) -> int:
    hour %= 12
    return hour + 12 if ampm.lower() == "p" else hour


def parse_transaction_time(text: str, now: datetime, start_year: int) -> datetime | None:
    """Parse Yahoo's transaction time text into an aware datetime.

    ``now`` must be timezone-aware; its zone is used for the result and for
    "Today"/"Yesterday". Returns None if no date is found.
    """
    tz = now.tzinfo
    text = text or ""
    m = _REL_TIME_RE.search(text)
    if m:
        day = now.date() - timedelta(days=1 if m.group(1).lower() == "yesterday" else 0)
        return datetime(day.year, day.month, day.day,
                        _to_24h(int(m.group(2)), m.group(4)), int(m.group(3)), tzinfo=tz)
    m = _ABS_TIME_RE.search(text)
    if m:
        month = _month(m.group(1))
        try:
            return datetime(infer_year(month, start_year), month, int(m.group(2)),
                            _to_24h(int(m.group(3)), m.group(5)), int(m.group(4)), tzinfo=tz)
        except ValueError:
            return None
    m = _ABS_DATE_RE.search(text)
    if m:
        month = _month(m.group(1))
        try:
            return datetime(infer_year(month, start_year), month, int(m.group(2)), 12, 0, tzinfo=tz)
        except ValueError:
            return None
    return None


def rfc3339(dt: datetime) -> str:
    """``2026-10-24T10:23:00-07:00`` (same style as the fixture)."""
    return dt.isoformat(timespec="seconds")


def now_in(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def parse_week_spec(spec: str, current_week: int) -> list[int]:
    """'all' | 'current' | 'last2' | 'last3' | '1-4' | '3,5,7' -> sorted weeks <= current."""
    spec = (spec or "").strip().lower()
    if spec in ("", "last2"):
        weeks = {current_week, current_week - 1}
    elif spec == "current":
        weeks = {current_week}
    elif spec == "all":
        weeks = set(range(1, current_week + 1))
    elif spec.startswith("last") and spec[4:].isdigit():
        n = int(spec[4:])
        weeks = set(range(current_week - n + 1, current_week + 1))
    else:
        weeks = set()
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                weeks.update(range(int(a), int(b) + 1))
            elif part:
                weeks.add(int(part))
    return sorted(w for w in weeks if 1 <= w <= current_week)
