"""resolve_date: turn "tomorrow", "Monday", "in 2 weeks", "Nov 23" into an exact date.

Owner: Karthik. Plain code, no LLM: date arithmetic is exactly what models get wrong.
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

TZ = ZoneInfo("America/Los_Angeles")  # San Francisco
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _today() -> date:
    return datetime.now(TZ).date()


def _result(d: date, today: date, expression: str, ambiguous_with: Optional[date] = None) -> dict:
    out = {
        "expression": expression,
        "date": d.isoformat(),
        "weekday": d.strftime("%A"),
        "days_from_today": (d - today).days,
        "today": today.isoformat(),
        "in_past": d < today,
    }
    if ambiguous_with:
        out["ambiguous"] = True
        out["alternative_date"] = ambiguous_with.isoformat()
        out["note"] = (f"'{expression}' could mean {d.isoformat()} or "
                       f"{ambiguous_with.isoformat()}. Confirm with the paralegal.")
    return out


def resolve_date(expression: str) -> dict:
    """Convert a date phrase to an exact calendar date (YYYY-MM-DD), San Francisco time.

    Always call this for any date the paralegal gives that isn't already YYYY-MM-DD,
    such as "tomorrow", "Monday", "next Friday", "in 10 days", "Nov 23", or "11/23".

    Args:
        expression: The date phrase exactly as the paralegal wrote it.

    Returns:
        `date` (YYYY-MM-DD), `weekday`, `days_from_today`, `in_past`, and `today`. If the phrase
        could mean two dates, `ambiguous` is true with `alternative_date`: confirm before using.
    """
    today = _today()
    text = re.sub(r"\s+", " ", expression.strip().lower())

    # Relative words are searched for inside the phrase, so "hearing date tomorrow" works.
    if re.search(r"\bday after tomorrow\b", text):
        return _result(today + timedelta(days=2), today, expression)
    if re.search(r"\btomorrow\b", text):
        return _result(today + timedelta(days=1), today, expression)
    if re.search(r"\byesterday\b", text):
        return _result(today - timedelta(days=1), today, expression)
    if re.search(r"\b(today|tonight)\b", text):
        return _result(today, today, expression)

    m = re.search(r"\bin (\d+|a|an|one|two|three) (day|week|month)s?\b", text)
    if m:
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1)) or int(m.group(1))
        days = {"day": 1, "week": 7, "month": 30}[m.group(2)] * n
        return _result(today + timedelta(days=days), today, expression)

    m = re.search(
        r"\b(this |next |coming |this coming )?"
        r"(mon|tue|wed|thu|fri|sat|sun)(day|sday|nesday|rsday|urday)?\b", text)
    if m and not re.search(r"\d", text):
        target = [w[:3] for w in WEEKDAYS].index(m.group(2))
        ahead = (target - today.weekday()) % 7 or 7  # always a future day
        upcoming = today + timedelta(days=ahead)
        prefix = (m.group(1) or "").strip()
        if prefix == "next" and ahead < 7:
            # "next Monday" said on a Saturday: this coming Monday, or the one after?
            return _result(upcoming, today, expression, ambiguous_with=upcoming + timedelta(days=7))
        return _result(upcoming, today, expression)

    if re.search(r"\bnext (week|month)\b", text):
        return {"error": f"{expression!r} is not a single date. Ask for the exact day."}

    if not re.search(r"\d", text):
        return {"error": f"Could not read {expression!r} as a date. Ask for YYYY-MM-DD."}
    try:
        has_year = bool(re.search(r"\b\d{4}\b", text))
        d = dateparser.parse(
            text, default=datetime(today.year, today.month, today.day), fuzzy=True
        ).date()
    except (ValueError, OverflowError):
        return {"error": f"Could not read {expression!r} as a date. Ask for YYYY-MM-DD."}
    if not has_year and d < today:
        # "Nov 3" with no year: a future hearing (next year) or a past event (this year)?
        return _result(d.replace(year=d.year + 1), today, expression, ambiguous_with=d)
    return _result(d, today, expression)
