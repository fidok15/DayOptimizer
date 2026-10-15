"""The tasks of a parsed message (DayRequest.tasks) -> Tasks. The model gives
days as words and copies the time-of-day words ('po południu', 'za 2h',
'po pracy'); the dates and times are worked out here so the model never does
calendar arithmetic."""
from __future__ import annotations
import re
from datetime import date, datetime, time, timedelta
from dayoptimizer.core.models import Task
from dayoptimizer.llm.backend import TaskRequest, resolve_day  # noqa: F401  (TaskRequest re-exported)

DEFAULT_MINUTES = 60

# part of the day -> (from hour, to hour)
_PARTS = [
    (r"po ?połud|popołud|afternoon", (12, 18)),
    (r"wieczor|wieczór|evening|tonight", (18, 22)),
    (r"\brano\b|\bz rana\b|przed ?połud|morning", (0, 12)),
]


def _hhmm(value: str | None) -> time | None:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (value or "").strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _offset(low: str) -> int | None:
    """'za 2h' / 'in 30 min' / 'za godzinę' -> minutes from now."""
    m = re.search(r"\b(?:za|in)\s+(\d+)\s*(h|godz|hours?|min)", low)
    if m:
        return int(m.group(1)) * (1 if m.group(2).startswith("min") else 60)
    if re.search(r"\bza pół godziny|\bin half an hour", low):
        return 30
    if re.search(r"\bza godzin|\bin an hour", low):
        return 60
    return None


def _after_event(low: str, events: list[tuple[str, datetime]]) -> datetime | None:
    """'po pracy' / 'after the lecture' -> the end of today's event of that name."""
    m = re.search(r"\b(?:po|after)\s+(?:the\s+)?(\w+)", low)
    if not m:
        return None
    # ponytail: 4-letter stem match for Polish cases (pracy ~ Praca); a lemmatizer if it misfires
    stem = m.group(1)[:4]
    return next((end for title, end in events
                 if any(w[:4] == stem for w in re.findall(r"\w+", title.lower()))), None)


def task_from_request(req: TaskRequest, categories: list[str], now: datetime | date, task_id: str,
                      events: list[tuple[str, datetime]] = ()) -> tuple[Task | None, str | None]:
    """The task, or why there is none (said back to the user). `events` are
    today's (title, end), for 'po <event>'. No length said = DEFAULT_MINUTES."""
    if not isinstance(now, datetime):
        now = datetime.combine(now, time(0))
    now = now.astimezone()
    today = now.date()
    title = req.title.strip()
    if not title:
        return None, "Say what the task is, e.g. 'report for Friday, 3h'."
    duration = req.duration_minutes if req.duration_minutes and req.duration_minutes > 0 else DEFAULT_MINUTES
    if duration >= 24 * 60:
        return None, "A task must be shorter than 24 hours; split it into several tasks."
    if req.category not in categories:
        return None, f"'{req.category}' is not one of your categories ({', '.join(categories)})."
    due = None
    if req.due_day or _hhmm(req.due_time):
        due = datetime.combine(resolve_day(req.due_day or "today", today),
                               _hhmm(req.due_time) or time(23, 59)).astimezone()
    not_before = None
    if req.not_before_day:
        not_before = datetime.combine(resolve_day(req.not_before_day, today), time(0)).astimezone()
    low = (req.when or "").lower()
    part = next((hours for pattern, hours in _PARTS if re.search(pattern, low)), None)
    if part:
        day = resolve_day(req.due_day or req.not_before_day or "today", today)
        if not (req.due_day or req.not_before_day) and datetime.combine(day, time(part[1])).astimezone() <= now:
            day += timedelta(days=1)  # 'rano' said in the afternoon: tomorrow morning
        not_before = datetime.combine(day, time(part[0])).astimezone()
        if not _hhmm(req.due_time):
            due = datetime.combine(day, time(part[1])).astimezone()
    elif (minutes := _offset(low)) is not None:
        not_before = now + timedelta(minutes=minutes)
    elif (end := _after_event(low, list(events))) is not None:
        not_before = end
    chunk = req.min_chunk_minutes
    if not chunk or chunk <= 0 or chunk >= duration:
        chunk = None
    return Task(id=task_id, title=title[:100], category=req.category, duration_min=duration,
                due=due, not_before=not_before, min_chunk_min=chunk, priority=req.priority), None
