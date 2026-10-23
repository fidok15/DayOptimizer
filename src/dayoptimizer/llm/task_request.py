"""The tasks of a parsed message (DayRequest.tasks) -> Tasks. The model gives
days as words and copies the time-of-day words ('po południu', 'za 2h',
'po pracy'); the dates and times are worked out here so the model never does
calendar arithmetic."""
from __future__ import annotations
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from dayoptimizer.core.models import Task
from dataclasses import replace
from dayoptimizer.llm.backend import _DAY_WORDS, TaskFix, TaskRequest, resolve_day  # noqa: F401  (TaskRequest re-exported)

DEFAULT_MINUTES = 60

# part of the day -> (from hour, to hour); None = when the user's day starts
_PARTS = [
    (r"po ?połud|popołud|afternoon", (12, 18)),
    (r"wieczor|wieczór|evening|tonight", (18, 22)),
    (r"\brano\b|\bz rana\b|przed ?połud|morning", (None, 12)),
]


# the message asks to split the work: only then may a task get min chunks (models invent them)
_SPLIT = re.compile(r"\bpo\s+\d+\s*(?:min|h\b|godz)|kawał|częściach|\bczęści\b|podziel|rozbij|\bna raty|w blokach"
                    r"|chunk|\bsplit|\bpieces\b|\bin parts\b|\d+\s*(?:min|h)\w*\s+(?:each|at a time)", re.I)


def asks_split(text: str) -> bool:
    return bool(_SPLIT.search(text))


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
                      events: list[tuple[str, datetime]] = (),
                      awake: Callable[[date], tuple[time, time]] = lambda d: (time(5), time(23, 59))
                      ) -> tuple[Task | None, str | None]:
    """The task, or why there is none (said back to the user). `events` are
    today's (title, end), for 'po <event>'. `awake(day)` is the user's waking
    hours (Rules.awake): a task's day never reaches into their sleep. No length
    said = DEFAULT_MINUTES."""
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
        day = resolve_day(req.due_day or "today", today)
        due = datetime.combine(day, _hhmm(req.due_time) or awake(day)[1]).astimezone()
    not_before = None
    if req.not_before_day:
        # from when the user's day starts: never in the night before it, while they sleep
        day = resolve_day(req.not_before_day, today)
        not_before = datetime.combine(day, awake(day)[0]).astimezone()
    low = (req.when or "").lower()
    part = next((hours for pattern, hours in _PARTS if re.search(pattern, low)), None)
    if part:
        day = resolve_day(req.due_day or req.not_before_day or "today", today)
        if not (req.due_day or req.not_before_day) and datetime.combine(day, time(part[1])).astimezone() <= now:
            day += timedelta(days=1)  # 'rano' said in the afternoon: tomorrow morning
        not_before = datetime.combine(day, awake(day)[0] if part[0] is None else time(part[0])).astimezone()
        if not _hhmm(req.due_time):
            due = datetime.combine(day, min(time(part[1]), awake(day)[1])).astimezone()
    elif (minutes := _offset(low)) is not None:
        not_before = now + timedelta(minutes=minutes)
    elif (end := _after_event(low, list(events))) is not None:
        not_before = end
    chunk = req.min_chunk_minutes
    if not chunk or chunk <= 0 or chunk >= duration:
        chunk = None
    return Task(id=task_id, title=title[:100], category=req.category, duration_min=duration,
                due=due, not_before=not_before, min_chunk_min=chunk, priority=req.priority), None


_DROP = re.compile(r"\b(?:usu[nń]|skasuj|wywal|odpu[sś][cć]|nie r[oó]b|drop|skip|delete|remove|forget)\w*")
# what may stand next to it: 'usuń przerwę' is about a routine block, that goes to the model
_FILLER = re.compile(r"\b(?:to|it|go|j[aą]|je|tego|this|that|the|task|zadanie|po prostu|just)\b|\W")


def _minutes(low: str) -> int | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(h\b|godz|hours?|min)", low)
    if m:
        return round(float(m.group(1).replace(",", ".")) * (1 if m.group(2).startswith("min") else 60))
    if re.search(r"p[oó][lł] godziny|half an hour", low):
        return 30
    if re.search(r"\bgodzin(?:a|ę|y|ą|ie)?\b|\ban hour\b|\bone hour\b", low):
        return 60
    return None


def quick_fix(reply: str) -> TaskFix | None:
    """The reply about a task that didn't fit, read by code when that's easy
    (drop it / a length / pieces / one day word); None = ask the model."""
    low = reply.lower().strip()
    if _DROP.search(low) and not _FILLER.sub("", _DROP.sub("", low)):
        return TaskFix(action="drop_task")
    n = _minutes(low)
    days = [d for pattern, d in _DAY_WORDS if re.search(pattern, low)]
    clock = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", low)
    if n and not days and not clock:
        return TaskFix(action="allow_split", chunk_minutes=n) if asks_split(low) else TaskFix(action="new_duration", minutes=n)
    if len(days) == 1 and not n:
        return TaskFix(action="new_deadline", day=days[0], time=clock.group(0) if clock else None)
    return None


def apply_fix(task: Task, fix: TaskFix, now: datetime) -> tuple[Task | None, str]:
    """The task changed as the fix says, and what was understood ("move 'X'
    deadline to Fri 23:59"); (None, "") when the fix says nothing usable."""
    t = f"'{task.title}'"
    if fix.action == "drop_task":
        return replace(task, done=True), f"drop {t}"
    if fix.action == "new_duration" and fix.minutes and 0 < fix.minutes < 24 * 60:
        chunk = task.min_chunk_min if (task.min_chunk_min or 0) < fix.minutes else None
        return replace(task, duration_min=fix.minutes, min_chunk_min=chunk), f"make {t} {fix.minutes} min"
    if fix.action == "allow_split":
        n = fix.chunk_minutes if fix.chunk_minutes and fix.chunk_minutes > 0 else 60
        if n < task.duration_min:
            return replace(task, min_chunk_min=n), f"split {t} into pieces of at least {n} min"
    if fix.action == "new_deadline" and (fix.day or _hhmm(fix.time)):
        day = resolve_day(fix.day, now.date()) if fix.day else (task.due or now).date()
        due = datetime.combine(day, _hhmm(fix.time) or time(23, 59)).astimezone()
        return replace(task, due=due), f"move {t} deadline to {due:%a %d.%m %H:%M}"
    if fix.action == "take_routine":
        blocks = [b.strip() for b in fix.blocks if b.strip()] or ["*"]
        said = "any flexible routine block" if blocks == ["*"] else " and ".join(blocks)
        return replace(task, may_take=blocks), f"let {t} take {said}"
    return None, ""
