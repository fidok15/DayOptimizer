"""All-day events that are really timed: people put "Dentist 14:00" in as an
all-day event and keep the time in the title. The planner would otherwise see
no busy time at all, so it reads the time from the title, plans around it and
proposes (with approval) to turn the event into a real timed one. When the
title is ambiguous ("Room 14", "Exam 12.10") it still plans around the guess
but says it isn't sure."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dayoptimizer.core.models import Event, PlannedChange

DEFAULT_MINUTES = 60

_H = r"([01]?\d|2[0-3])"
_M = r"([0-5]\d)"
_RANGE = re.compile(rf"(?<![\d.:]){_H}(?:[:.]{_M})?\s*[-–—]\s*{_H}(?:[:.]{_M})?(?![\d.:])")
_CLOCK = re.compile(rf"(?<![\d.:]){_H}([:.]){_M}(?![\d.:])")
_MARKED = re.compile(rf"(?:\b(?:o|at|godz\.?|od|from)\s+|@\s*){_H}(?![\d.:])", re.IGNORECASE)
_SUFFIX = re.compile(rf"(?<![\d.:])(1[0-2]|0?\d)\s*(am|pm)\b|(?<![\d.:]){_H}\s*h\b", re.IGNORECASE)
_BARE = re.compile(rf"(?<![\d.:]){_H}(?![\d.:])")


@dataclass
class TitleTime:
    start: time
    end: time | None
    sure: bool


def time_in_title(title: str) -> TitleTime | None:
    """The time a title names, or None. `sure` is False when it may well mean
    something else: a bare number, a dd.mm-looking "12.10", an hour before 6
    without minutes, or several different times."""
    if m := _RANGE.search(title):
        h1, m1, h2, m2 = m.groups()
        start, end = time(int(h1), int(m1 or 0)), time(int(h2), int(m2 or 0))
        if end > start:
            return TitleTime(start, end, m1 is not None or m2 is not None or int(h1) >= 6)
    clocks = [(int(h), sep, int(mi)) for h, sep, mi in _CLOCK.findall(title)]
    if clocks:
        h, sep, mi = clocks[0]
        looks_like_date = sep == "." and 1 <= h <= 31 and 1 <= mi <= 12
        sure = not looks_like_date and len({(c[0], c[2]) for c in clocks}) == 1
        return TitleTime(time(h, mi), None, sure)
    if m := _SUFFIX.search(title):
        if m.group(1):
            h = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "pm" else 0)
        else:
            h = int(m.group(3))
        return TitleTime(time(h), None, True)
    if m := _MARKED.search(title):
        h = int(m.group(1))
        return TitleTime(time(h), None, h >= 6)
    bare = _BARE.findall(title)
    if len(bare) == 1:
        return TitleTime(time(int(bare[0])), None, False)
    return None


def _last_day(e: Event) -> date:
    return (e.end - timedelta(microseconds=1)).date() if e.end.time() == time() else e.end.date()


def timed_all_day(events: list[Event], day: date) -> list[tuple[Event, TitleTime]]:
    """(the timed event the title describes, the parse) for single-day all-day
    events on `day` whose title names a time. Multi-day markers ("Conference
    9:00" over three days) are left alone."""
    out = []
    for e in events:
        if not e.all_day or e.start.date() != day or _last_day(e) != day:
            continue
        tt = time_in_title(e.title)
        if tt is None:
            continue
        start = datetime.combine(day, tt.start).astimezone()
        end = (datetime.combine(day, tt.end).astimezone() if tt.end
               else start + timedelta(minutes=DEFAULT_MINUTES))
        out.append((Event(id=e.id, calendar=e.calendar, title=e.title, start=start, end=end,
                          location=e.location), tt))
    return out


def conversion(timed: Event, tt: TitleTime) -> PlannedChange:
    """The proposal to make the all-day event a real timed one: always needs the user's OK."""
    span = f"{timed.start:%H:%M}–{timed.end:%H:%M}"
    if tt.sure:
        reason = f"all-day event with a time in its title: make it a {span} event"
    else:
        reason = (f"all-day event; its title may mean {span}, but that's a guess — accept to "
                  "make it timed, or fix it in Calendar. Planned around it meanwhile")
    return PlannedChange(kind="move", category=timed.calendar, title=timed.title, reason=reason,
                         event_id=timed.id, new_start=timed.start, new_end=timed.end,
                         requires_approval=True)


if __name__ == "__main__":
    cases = {
        "Dentysta 14:00": (time(14), None, True),
        "Dentist 9.30": (time(9, 30), None, True),
        "Meeting 14-15:30": (time(14), time(15, 30), True),
        "Call 14:00–15:00": (time(14), time(15), True),
        "Lekarz o 14": (time(14), None, True),
        "Dinner at 7pm": (time(19), None, True),
        "Gym 18h": (time(18), None, True),
        "Room 14": (time(14), None, False),
        "Exam 12.10": (time(12, 10), None, False),
        "Call o 3": (time(3), None, False),
        "Train 9:00 or 11:00": (time(9), None, False),
        "Holiday": None,
        "Score 3-4": (time(3), time(4), False),
    }
    for title, want in cases.items():
        got = time_in_title(title)
        got = got and (got.start, got.end, got.sure)
        assert got == want, (title, got, want)
    print("ok")
