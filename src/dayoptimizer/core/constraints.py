"""Rules compiled from the user's free-text notes.

The LLM translates a note like "no lunch before 14:00" into one of the few
rule types below, ONCE, when the routine is saved. Planning then stays
deterministic: no tokens, works offline, same input means same plan. A note
that fits no rule type stays plain text for the assistant to read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

TYPES = ("not_before", "not_after", "keep_free", "min_gap_days", "max_per_week", "skippable")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

@dataclass(frozen=True)
class NoteRule:
    type: str
    source: str = ""
    category: str | None = None
    minutes: int | None = None
    start: int | None = None
    end: int | None = None
    weekday: int | None = None
    days: int | None = None
    count: int | None = None
    prefix: str | None = None

def _minutes(value) -> int | None:
    try:
        h, m = str(value).split(":")
        total = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None
    return total if 0 <= total <= 1440 else None

def parse_rules(raw) -> list[NoteRule]:
    """Config rows -> rules, skipping anything malformed (the file is editable
    by hand, and a typo must not break planning)."""
    out = []
    for row in raw or []:
        if not isinstance(row, dict) or row.get("type") not in TYPES:
            continue
        kind, source = row["type"], str(row.get("source") or "")
        category = row.get("category")
        category = str(category) if category else None
        if kind in ("not_before", "not_after"):
            minutes = _minutes(row.get("time"))
            if minutes is not None:
                out.append(NoteRule(kind, source, category, minutes=minutes))
        elif kind == "keep_free":
            start, end = _minutes(row.get("start")), _minutes(row.get("end"))
            day = row.get("weekday")
            day = WEEKDAYS.index(day) if isinstance(day, str) and day in WEEKDAYS else None
            if start is not None and end is not None and end > start:
                out.append(NoteRule(kind, source, category, start=start, end=end, weekday=day))
        elif kind in ("min_gap_days", "max_per_week"):
            try:
                number = int(row.get("days") if kind == "min_gap_days" else row.get("count"))
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 14 and category:
                out.append(NoteRule(kind, source, category,
                                    **({"days": number} if kind == "min_gap_days" else {"count": number})))
        elif kind == "skippable":
            prefix = str(row.get("prefix") or "").strip()
            if 0 < len(prefix) <= 20:  # no category: that prefix in any calendar
                out.append(NoteRule(kind, source, category, prefix=prefix))
    return dedupe(out)

def dedupe(rules: list[NoteRule]) -> list[NoteRule]:
    """One limit of a kind per category: a second not_before for the same
    category usually means the model misread a sentence, and stacking them
    silently shrinks the day to nothing. The first one wins."""
    seen: set[tuple] = set()
    out = []
    for r in rules:
        key = (r.type, r.category)
        if r.type in ("not_before", "not_after", "min_gap_days", "max_per_week"):
            if key in seen:
                continue
            seen.add(key)
        elif r.type == "skippable":
            if (key, r.prefix) in seen:
                continue
            seen.add((key, r.prefix))
        out.append(r)
    return out

def _applies(rule: NoteRule, category: str) -> bool:
    return rule.category is None or rule.category == category

def allowed_window(rules: list[NoteRule], category: str) -> tuple[int, int]:
    """(earliest, latest) minutes a block of this category may occupy."""
    earliest, latest = 0, 1440
    for r in rules:
        if not _applies(r, category):
            continue
        if r.type == "not_before" and r.minutes is not None:
            earliest = max(earliest, r.minutes)
        elif r.type == "not_after" and r.minutes is not None:
            latest = min(latest, r.minutes)
    return earliest, latest

def free_windows(rules: list[NoteRule], weekday: int, category: str) -> list[tuple[int, int]]:
    """Windows to keep empty on this weekday, as (start, end) minutes."""
    return [(r.start, r.end) for r in rules
            if r.type == "keep_free" and _applies(r, category)
            and r.weekday in (None, weekday) and r.start is not None and r.end is not None]

def window_rule(rules: list[NoteRule], category: str, start: int, end: int,
                weekday: int | None = None) -> NoteRule | None:
    """The rule a block at [start, end) breaks, if any — for the explanation."""
    for r in rules:
        if not _applies(r, category):
            continue
        if r.type == "not_before" and r.minutes is not None and start < r.minutes:
            return r
        if r.type == "not_after" and r.minutes is not None and end > r.minutes:
            return r
        if (r.type == "keep_free" and weekday is not None and r.weekday in (None, weekday)
                and r.start is not None and start < r.end and end > r.start):
            return r
    return None

def gap_rule(rules: list[NoteRule], category: str, day: date, history: dict[str, list[date]]) -> NoteRule | None:
    """min_gap_days broken by what the category already has in the days before."""
    for r in rules:
        if r.type != "min_gap_days" or not _applies(r, category) or not r.days:
            continue
        recent = [d for d in history.get(category, []) if 0 < (day - d).days < r.days]
        if recent:
            return r
    return None

def week_rule(rules: list[NoteRule], category: str, day: date, history: dict[str, list[date]],
              planned: int = 0) -> NoteRule | None:
    """max_per_week already reached this week (Mon-Sun) for this category."""
    week_start = day - timedelta(days=day.weekday())
    for r in rules:
        if r.type != "max_per_week" or not _applies(r, category) or r.count is None:
            continue
        done = len({d for d in history.get(category, []) if week_start <= d < day})
        if done + planned >= r.count:
            return r
    return None

def describe(rule: NoteRule) -> str:
    """One line a person can check, e.g. 'Gym: at most 3 times a week'."""
    who = rule.category or "Everything"
    if rule.type == "not_before":
        return f"{who}: not before {rule.minutes // 60:02d}:{rule.minutes % 60:02d}"
    if rule.type == "not_after":
        return f"{who}: not after {rule.minutes // 60:02d}:{rule.minutes % 60:02d}"
    if rule.type == "keep_free":
        when = WEEKDAYS[rule.weekday].capitalize() if rule.weekday is not None else "Every day"
        span = f"{rule.start // 60:02d}:{rule.start % 60:02d}-{rule.end // 60:02d}:{rule.end % 60:02d}"
        subject = "" if rule.category is None else f" of {rule.category}"
        return f"{when} {span}: kept free{subject}"
    if rule.type == "min_gap_days":
        return f"{who}: at least {rule.days - 1} rest day(s) between"
    if rule.type == "skippable":
        return f"{rule.category or 'Any calendar'}: events starting with \"{rule.prefix}\" may be planned over"
    return f"{who}: at most {rule.count} time(s) a week"

def skippable(rules: list[NoteRule], event) -> bool:
    """An event the user said may be planned over ("lectures, titles starting
    with 'Lecture -', can be skipped"): it neither blocks time nor gets moved."""
    title = event.title.strip().lower()
    return any(r.type == "skippable" and _applies(r, event.calendar)
               and title.startswith(r.prefix.lower()) for r in rules)

def explain(rule: NoteRule) -> str:
    return f"your note \"{rule.source}\"" if rule.source else f"your rule ({rule.type})"
