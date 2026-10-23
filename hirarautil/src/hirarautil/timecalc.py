"""time_now and date_calc: the clock and the calendar, done right.

A language model does not know today's date, and calendar arithmetic (month
ends, leap years, DST, business days) is exactly where it makes mistakes.
Standard library only: ``zoneinfo`` for IANA time zones.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_SPAN_DAYS = 200 * 366


class TimeError(ValueError):
    """Caller-facing time / date failure."""


def get_zone(name: str | None) -> ZoneInfo | timezone:
    key = (name or "UTC").strip()
    if key.upper() in ("UTC", "Z", "GMT"):
        return timezone.utc
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        hint = [z for z in available_timezones() if key.lower() in z.lower()][:5]
        more = f"; did you mean {', '.join(sorted(hint))}?" if hint else ""
        raise TimeError(f"unknown time zone {key!r} (use an IANA name like Asia/Yangon){more}") from exc


def _zone_name(tz) -> str:
    return "UTC" if tz is timezone.utc else str(tz)


def describe(moment: datetime) -> dict:
    """Everything an agent tends to need about one instant."""
    tz = moment.tzinfo
    offset = moment.utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hh, mm = divmod(abs(total) // 60, 60)
    iso_year, iso_week, _ = moment.isocalendar()
    return {
        "iso": moment.isoformat(timespec="seconds"),
        "date": moment.date().isoformat(),
        "time": moment.strftime("%H:%M:%S"),
        "timezone": _zone_name(tz),
        "abbreviation": moment.tzname(),
        "utc_offset": f"{sign}{hh:02d}:{mm:02d}",
        "dst": bool(moment.dst()) if moment.dst() is not None else False,
        "weekday": WEEKDAYS[moment.weekday()],
        "iso_week": iso_week,
        "iso_year": iso_year,
        "day_of_year": moment.timetuple().tm_yday,
        "quarter": (moment.month - 1) // 3 + 1,
        "unix": int(moment.timestamp()),
    }


def time_now(timezones: list[str] | str | None = None, *, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    names = [timezones] if isinstance(timezones, str) else (timezones or ["UTC"])
    if len(names) > 50:
        raise TimeError("at most 50 time zones per call")
    zones = [describe(current.astimezone(get_zone(n))) for n in names]
    return {
        "utc": current.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "unix": int(current.timestamp()),
        "zones": zones,
        "text": "; ".join(f"{z['timezone']}: {z['weekday']} {z['date']} {z['time']} "
                          f"({z['abbreviation']}, UTC{z['utc_offset']})" for z in zones),
        "error": None,
    }


# --- parsing ---------------------------------------------------------------------

def parse_moment(value: str | None, tz, *, now: datetime) -> datetime:
    """ISO 8601 date or date-time, a unix timestamp, or now/today/tomorrow/yesterday.

    A value without an offset is read in ``tz``; one with an offset keeps it
    and is then shown in ``tz``.
    """
    text = (value or "now").strip()
    low = text.lower()
    base = now.astimezone(tz)
    if low == "now":
        return base
    midnight = base.replace(hour=0, minute=0, second=0, microsecond=0)
    words = {"today": 0, "tomorrow": 1, "yesterday": -1}
    if low in words:
        return _from_wall(midnight.replace(tzinfo=None) + timedelta(days=words[low]), tz)
    if low.lstrip("-").isdigit() and len(low.lstrip("-")) >= 9:
        return datetime.fromtimestamp(int(low), timezone.utc).astimezone(tz)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError as exc:
        raise TimeError(
            f"cannot read {value!r}; use ISO 8601 like 2026-03-31 or 2026-03-31T14:30, "
            "a unix timestamp, or now / today / tomorrow / yesterday"
        ) from exc
    if parsed.tzinfo is None:
        return _from_wall(parsed, tz)
    return parsed.astimezone(tz)


def _from_wall(naive: datetime, tz) -> datetime:
    """Attach a zone to a wall-clock time, normalising one that DST skipped."""
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(timezone.utc).astimezone(tz)


# --- arithmetic --------------------------------------------------------------------

def add_months(moment: datetime, months: int) -> datetime:
    """Calendar months, clamping to the month's last day (Jan 31 + 1 = Feb 28/29)."""
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    if not 1 <= year <= 9999:
        raise TimeError("result is outside years 1..9999")
    day = min(moment.day, calendar.monthrange(year, month + 1)[1])
    return moment.replace(year=year, month=month + 1, day=day)


def _holidays(values) -> set[date]:
    out = set()
    for v in values or []:
        try:
            out.add(date.fromisoformat(str(v)[:10]))
        except ValueError as exc:
            raise TimeError(f"holiday {v!r} is not an ISO date") from exc
    return out


def _weekend(days) -> set[int]:
    if days is None:
        return {5, 6}
    out = set()
    for d in days:
        name = str(d).strip().lower()
        matches = [i for i, w in enumerate(WEEKDAYS) if w.lower().startswith(name[:3])]
        if not matches:
            raise TimeError(f"unknown weekday {d!r}")
        out.add(matches[0])
    return out


def is_business(d: date, weekend: set[int], holidays: set[date]) -> bool:
    return d.weekday() not in weekend and d not in holidays


def add_business_days(moment: datetime, count: int, weekend, holidays) -> datetime:
    if len(weekend) >= 7:
        raise TimeError("weekend covers every day")
    step = 1 if count >= 0 else -1
    remaining = abs(count)
    current = moment
    guard = 0
    while remaining:
        current = _from_wall(current.replace(tzinfo=None) + timedelta(days=step), current.tzinfo)
        if is_business(current.date(), weekend, holidays):
            remaining -= 1
        guard += 1
        if guard > MAX_SPAN_DAYS:
            raise TimeError("business-day span too large")
    return current


def count_business_days(a: date, b: date, weekend, holidays) -> int:
    """Business days in [a, b) (or negative when b is before a)."""
    if abs((b - a).days) > MAX_SPAN_DAYS:
        raise TimeError("span too large")
    lo, hi, sign = (a, b, 1) if a <= b else (b, a, -1)
    days = (hi - lo).days
    full, rest = divmod(days, 7)
    count = full * (7 - len(weekend))
    for i in range(rest):
        if (lo + timedelta(days=full * 7 + i)).weekday() not in weekend:
            count += 1
    count -= sum(1 for h in holidays if lo <= h < hi and h.weekday() not in weekend)
    return sign * count


def calendar_diff(a: datetime, b: datetime) -> dict:
    """Years / months / days between two moments, calendar-aware."""
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if add_months(a, months) > b:
        months -= 1
    anchor = add_months(a, months)
    rest = b - anchor
    years, months = divmod(months, 12)
    return {"years": sign * years, "months": sign * months, "days": sign * rest.days,
            "hours": sign * (rest.seconds // 3600), "minutes": sign * (rest.seconds % 3600 // 60)}


def date_calc(
    operation: str,
    *,
    date_value: str | None = None,
    other: str | None = None,
    timezone_name: str | None = None,
    to_timezones: list[str] | str | None = None,
    years: int = 0,
    months: int = 0,
    weeks: int = 0,
    days: float = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    business_days: int = 0,
    holidays: list[str] | None = None,
    weekend: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    current = now or datetime.now(timezone.utc)
    tz = get_zone(timezone_name)
    op = (operation or "").strip().lower()
    moment = parse_moment(date_value, tz, now=current)
    hol = _holidays(holidays)
    wk = _weekend(weekend)

    if op == "info":
        info = describe(moment)
        d = moment.date()
        month_end = calendar.monthrange(d.year, d.month)[1]
        info.update({
            "is_leap_year": calendar.isleap(d.year),
            "days_in_month": month_end,
            "week_start": (d - timedelta(days=d.weekday())).isoformat(),
            "week_end": (d + timedelta(days=6 - d.weekday())).isoformat(),
            "month_start": d.replace(day=1).isoformat(),
            "month_end": d.replace(day=month_end).isoformat(),
            "is_business_day": is_business(d, wk, hol),
        })
        return {"operation": op, "result": info, "text": f"{info['weekday']} {info['iso']}",
                "error": None}

    if op == "add":
        result = moment
        if years or months:
            result = add_months(result, int(years) * 12 + int(months))
        if weeks or days:
            # Calendar days keep the wall-clock time across a DST change.
            result = _from_wall(result.replace(tzinfo=None)
                                + timedelta(weeks=weeks, days=days), tz)
        if hours or minutes or seconds:
            # Elapsed time is exact: add in UTC.
            result = (result.astimezone(timezone.utc)
                      + timedelta(hours=hours, minutes=minutes, seconds=seconds)).astimezone(tz)
        if business_days:
            result = add_business_days(result, int(business_days), wk, hol)
        out = describe(result)
        return {"operation": op, "start": moment.isoformat(timespec="seconds"), "result": out,
                "text": f"{out['weekday']} {out['iso']}", "error": None}

    if op == "diff":
        if not other:
            raise TimeError("diff needs other (the second date)")
        end = parse_moment(other, tz, now=current)
        delta = end - moment
        parts = calendar_diff(moment, end)
        result = {
            "start": moment.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "total_seconds": int(delta.total_seconds()),
            "total_hours": round(delta.total_seconds() / 3600, 2),
            "total_days": round(delta.total_seconds() / 86400, 4),
            "calendar_days": (end.date() - moment.date()).days,
            "weeks": round((end.date() - moment.date()).days / 7, 2),
            "business_days": count_business_days(moment.date(), end.date(), wk, hol),
            "calendar": parts,
        }
        text = (f"{parts['years']}y {parts['months']}m {parts['days']}d {parts['hours']}h; "
                f"{result['calendar_days']} calendar days, {result['business_days']} business days")
        return {"operation": op, "result": result, "text": text, "error": None}

    if op == "convert":
        names = [to_timezones] if isinstance(to_timezones, str) else (to_timezones or [])
        if not names:
            raise TimeError("convert needs to_timezones")
        if len(names) > 50:
            raise TimeError("at most 50 time zones per call")
        zones = [describe(moment.astimezone(get_zone(n))) for n in names]
        return {"operation": op, "source": describe(moment), "result": zones,
                "text": "; ".join(f"{z['timezone']}: {z['date']} {z['time']} {z['abbreviation']}"
                                  for z in zones), "error": None}

    raise TimeError("operation must be info, add, diff or convert")


__all__ = ["TimeError", "date_calc", "describe", "get_zone", "time_now"]
