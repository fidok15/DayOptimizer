"""The tasks of a parsed message (DayRequest.tasks) -> Tasks. The model gives
days as words and copies the time-of-day words ('po południu', 'za 2h',
'po pracy'); the dates and times are worked out here so the model never does
calendar arithmetic."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from dayoptimizer.core.models import Task, at
from dayoptimizer.llm.backend import TaskFix, TaskRequest, day_words, resolve_day

DEFAULT_MINUTES = 60

# part of the day -> (from hour, to hour); None = when the user's day starts
_PARTS = [
    (r"po ?połud|popołud|afternoon", (12, 18)),
    (r"wieczor|wieczór|evening|tonight", (18, 22)),
    (r"\brano\b|\bz rana\b|przed ?połud|morning", (None, 12)),
]


# 'między 14 a 16' / 'od 14 do 16' / 'between 2 and 4 pm' is not: 24h clock only
_BETWEEN = re.compile(r"\b(?:pomi[eę]dzy|mi[eę]dzy|od|between|from)\s+([01]?\d|2[0-3])(?::([0-5]\d))?\s*"
                      r"(?:a|i|do|and|to|-)\s*([01]?\d|2[0-4])(?::([0-5]\d))?\b")


# the message asks to split the work: only then may a task get min chunks (models invent them)
_SPLIT = re.compile(r"\bpo\s+\d+\s*(?:min|h\b|godz)|kawał|częściach|\bczęści\b|podziel|rozbij|\bna raty|w blokach"
                    r"|chunk|\bsplit|\bpieces\b|\bin parts\b|\d+\s*(?:min|h)\w*\s+(?:each|at a time)", re.I)


def asks_split(text: str) -> bool:
    return bool(_SPLIT.search(text))


_LENGTH = r"(\d+(?:[.,]\d+)?)\s*(h\b|godz\w*|hours?\b|min\w*)"
_PIECE = re.compile(rf"\bpo\s+{_LENGTH}|{_LENGTH}\s*(?:chunks?|pieces?|blocks?|each|at a time|kawałk\w*)", re.I)


_TIMES = {"dwa": 2, "dwie": 2, "trzy": 3, "cztery": 4, "pięć": 5, "piec": 5, "pięc": 5,
          "two": 2, "twice": 2, "three": 3, "four": 4, "five": 5}


def repeats(text: str) -> tuple[int | None, int | None]:
    """(total, one session) minutes for work said as sessions: '3 razy po godzinie' -> (180, 60),
    'English 3 times for an hour' / '3x 45 min' -> (180, 60) / (135, 45)."""
    low = text.lower()
    m = re.search(rf"\b(\d+|{'|'.join(_TIMES)})\s*(?:razy|x|times)\b|\b(twice)\b", low)
    if not m:
        return None, None
    n = _TIMES.get(m.group(1) or m.group(2)) or int(m.group(1))
    one = _minutes(low[m.end():]) or _minutes(low[:m.start()])
    return (n * one, one) if one and 1 < n <= 14 else (None, None)


def split_lengths(text: str) -> tuple[int | None, int | None]:
    """(total, piece) minutes said in a message that asks to split the work:
    '6h do czwartku, w kawałkach po 2h' -> (360, 120); 'thesis, 6h, in 2h chunks' -> (360, 120)."""
    def mins(n, unit):
        return round(float(n.replace(",", ".")) * (1 if unit.lower().startswith("min") else 60))
    piece = _PIECE.search(text)
    if not piece:
        return None, None
    n, unit = (piece.group(1), piece.group(2)) if piece.group(1) else (piece.group(3), piece.group(4))
    totals = {mins(m.group(1), m.group(2)) for m in re.finditer(_LENGTH, text, re.I)
              if not piece.start() <= m.start() < piece.end()
              and not re.search(r"\b(?:za|in)\s+$", text[:m.start()], re.I)}  # 'za 3h' / 'in 3h': when, not how long
    return (totals.pop() if len(totals) == 1 else None), mins(n, unit)


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


# Polish words for routine blocks drawn in English ('po śniadaniu' = after Breakfast)
_ALIASES = {"śnia": ("brea",), "obia": ("dinn", "lunc"), "kola": ("supp", "dinn"), "prac": ("work",),
            "siło": ("gym",), "tren": ("gym",), "nauk": ("stud", "lear"), "zaję": ("stud", "lect")}


def _fold(word: str) -> str:
    """'siłownię' -> 'silowni': Polish letters aside, people type without them."""
    import unicodedata
    return unicodedata.normalize("NFKD", word.replace("ł", "l")).encode("ascii", "ignore").decode()


_FOLDED_ALIASES = {_fold(k): v for k, v in _ALIASES.items()}


def stems(text: str) -> set[str]:
    """4-letter stems of the words, plus the English routine names they stand for ('śniadanie' ~ Breakfast)."""
    out = set()
    for w in re.findall(r"\w{2,}", text.lower()):
        s = _fold(w)[:4]
        out |= {s, *_FOLDED_ALIASES.get(s, ())}
    return out


_WITHOUT = re.compile(r"\b(?:bez|without|no|skip|odpu[sś][cć]\w*|nie\s+id[eę]\s+na)\s+(\w+)")


def skipped_routine(text: str, typical_week: dict, days: list[date], today: date) -> dict[date, list[str]]:
    """Routine blocks the message leaves out ('bez siłowni', 'no gym', 'bez siłowni i śniadania'):
    on the day its clause names (or an earlier clause), else on every planned day. {day: [block label]}."""
    from dayoptimizer.llm.backend import WEEKDAYS, day_words, next_week
    out: dict[date, list[str]] = {}
    cur, prev = None, False
    # a list after 'bez' runs on over 'i'/'and' only, never past a comma or a sentence
    for clause in (c for part in re.split(r"[,;.!?\n]", text.lower())
                   for c in [None, *re.split(r"\s(?:i|a|oraz|and|or|ani)\s", part)]):
        if clause is None:
            prev = False
            continue
        said = {next_week(d, today) if d in WEEKDAYS and re.search(r"\b(?:next|przysz\w*|nast[eę]pn\w*)\b", clause)
                else resolve_day(d, today) for p, d in day_words() if re.search(p, clause)}
        cur = said or cur
        found = _WITHOUT.findall(clause)
        # 'bez siłowni i śniadania': the word after 'i' is left out too; 'i 2h nauki' is a task, not that
        if not found and prev and not said and not re.search(r"\d", clause):
            found = re.findall(r"\w+", clause)[:1]
        prev = bool(found)
        words = set().union(*(stems(w) for w in found))
        for d in days:
            if not words or (cur and d not in cur):
                continue
            for b in typical_week.get(d.weekday(), []):
                if words & (stems(b.label) | stems(b.category)) and b.label not in out.get(d, []):
                    out.setdefault(d, []).append(b.label)
    return out


def stands_in(title: str, category: str, block) -> bool:
    """The user's own event is that routine block this time ('śniadanie' in Food = Breakfast):
    every word of its title names the block ('Breakfast shopping' is not breakfast)."""
    label = stems(block.label)
    words = re.findall(r"\w{2,}", title.lower())
    return block.category == category and bool(words) and all(stems(w) & label for w in words)


def _after_event(low: str, events: list[tuple[str, datetime]], day: date) -> datetime | None:
    """'po pracy' / 'after the lecture' -> the end of that day's event or routine block of that name."""
    m = re.search(r"\b(?:po|after)\s+(?:the\s+)?(\w+)", low)
    if not m:
        return None
    # ponytail: 4-letter stem match for Polish cases (pracy ~ Praca); a lemmatizer if it misfires
    stems = (m.group(1)[:4], *_ALIASES.get(m.group(1)[:4], ()))
    # the last one that day: 'po pracy' is after the day's work, not after its first block
    return max((end for title, end in events
                if end.date() == day and any(w[:4] in stems for w in re.findall(r"\w+", title.lower()))), default=None)


def task_from_request(req: TaskRequest, categories: list[str], now: datetime | date, task_id: str,
                      events: list[tuple[str, datetime]] = (),
                      awake: Callable[[date], tuple[time, time]] = lambda d: (time(5), time(23, 59))
                      ) -> tuple[Task | None, str | None]:
    """The task, or why there is none (said back to the user). `events` are
    (title, end) of today's calendar and the routine's coming days, for 'po <event>'
    (also with a part of the day: 'rano po śniadaniu'). `awake(day)` is the user's waking
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
    if (m := _BETWEEN.search(low)) and (int(m[1]), int(m[2] or 0)) < (int(m[3]), int(m[4] or 0)):
        day = resolve_day(req.due_day or req.not_before_day or "today", today)
        midnight = datetime.combine(day, time(0)).astimezone()
        not_before = at(midnight, int(m[1]) * 60 + int(m[2] or 0))
        if not _hhmm(req.due_time):
            due = at(midnight, int(m[3]) * 60 + int(m[4] or 0))
    elif part:
        day = resolve_day(req.due_day or req.not_before_day or "today", today)
        if not (req.due_day or req.not_before_day) and datetime.combine(day, time(part[1])).astimezone() <= now:
            day += timedelta(days=1)  # 'rano' said in the afternoon: tomorrow morning
        not_before = datetime.combine(day, awake(day)[0] if part[0] is None else time(part[0])).astimezone()
        if not _hhmm(req.due_time):
            due = datetime.combine(day, min(time(part[1]), awake(day)[1])).astimezone()
    elif (minutes := _offset(low)) is not None:
        not_before = now + timedelta(minutes=minutes)
    end = _after_event(low, list(events), (not_before or due or now).date())
    if end is not None and (due is None or end < due) and (not_before is None or end > not_before):
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
    days = [d for pattern, d in day_words() if re.search(pattern, low)]
    clock = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", low)
    if n and not days and not clock:
        return TaskFix(action="allow_split", chunk_minutes=n) if asks_split(low) else TaskFix(action="new_duration", minutes=n)
    # 'next Friday' / 'przyszły piątek' is the next calendar week's: the model reads that
    if len(days) == 1 and not n and not re.search(r"\b(?:next|przysz\w*|nast[eę]pn\w*)\b", low):
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
