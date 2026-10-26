"""Tasks in the planner: how much of each is left, how the model sees them,
and the checks on the blocks it places for them. llm/week_plan.py calls these;
everything here is pure so it can be tested without a model or a calendar."""
from __future__ import annotations

from datetime import date, datetime

from dayoptimizer.core.models import Event, Task, minutes


def remaining(tasks: list[Task], events: list[Event], now: datetime,
              planned: set[date] | frozenset[date] = frozenset()) -> dict[str, int]:
    """Minutes still to place for each open task: its length minus every block
    of it that stays in the calendar. Past and running blocks stay (a running
    one counts whole, the replan can't remove it), and so do future blocks on
    days not being replanned. Only future blocks on `planned` days are the old
    plan that gets replaced, so only they don't count."""
    left = {t.id: t.duration_min for t in tasks if not t.done}
    for e in events:
        if not (e.managed and e.task_id in left) or (e.start >= now and e.start.date() in planned):
            continue
        left[e.task_id] = max(0, left[e.task_id] - minutes(e.start, e.end))
    return left


def overdue(task: Task, now: datetime) -> bool:
    return task.due is not None and task.due <= now


def window(task: Task, now: datetime) -> tuple[datetime, datetime | None]:
    """Where the task's blocks may lie. An overdue task has no end: it goes as
    soon as possible instead of being refused."""
    start = max(now, task.not_before) if task.not_before else now
    end = None if task.due is None or overdue(task, now) else task.due
    return start, end


def task_lines(tasks: list[Task], left: dict[str, int], now: datetime,
               fits: dict[str, str] | None = None) -> list[str]:
    """One line per task with minutes left, as the model reads them; `fits`
    adds where in the planned days its window and the free time overlap."""
    lines = []
    for t in tasks:
        n = left.get(t.id, 0)
        if t.done or n <= 0:
            continue
        parts = [f"- [{t.id}] {t.title} ({t.category}) {n} min left"]
        if overdue(t, now):
            parts.append(f"OVERDUE since {t.due:%a %Y-%m-%d %H:%M}, place it first")
        elif t.due is not None:
            parts.append(f"due {t.due:%a %Y-%m-%d %H:%M}")
        else:
            parts.append("no deadline: as early as possible")
        if t.not_before is not None and t.not_before > now:
            parts.append(f"not before {t.not_before:%a %Y-%m-%d %H:%M}")
        split = t.min_chunk_min is not None and t.min_chunk_min < n
        parts.append(f"chunks >= {t.min_chunk_min} min" if split else f"in one piece (one block of {n} min)")
        parts.append(f"priority {t.priority}")
        if fits is not None and t.id in fits:
            parts.append(f"fits in: {fits[t.id]}")
        lines.append(", ".join(parts))
    return lines


def block_problem(task: Task | None, category: str, start: datetime, end: datetime,
                  left: int, now: datetime) -> str | None:
    """Why a block for this task can't stay, or None. `left` is what remains of
    the task before this block; no piece of a split task, the last one
    included, is shorter than its minimum chunk."""
    if task is None or task.done:
        return "is not an open task"
    if category != task.category:
        return f"must be in the task's category '{task.category}'"
    lo, hi = window(task, now)
    if start < lo:
        return f"starts before the task may start ({lo:%a %Y-%m-%d %H:%M})"
    if hi is not None and end > hi:
        return f"ends after the task's deadline ({hi:%a %Y-%m-%d %H:%M})"
    length = minutes(start, end)
    if length > left:
        return f"is {length} min but only {left} min of the task are left"
    chunk = task.min_chunk_min or task.duration_min
    if length < chunk and length != left:
        return f"is shorter than the task's minimum chunk of {chunk} min"
    if 0 < left - length < chunk:
        return f"leaves {left - length} min, a piece shorter than the task's minimum chunk of {chunk} min"
    return None


def unplaced(tasks: list[Task], left_after: dict[str, int], listed: set[str],
             last_day: date, now: datetime, before: dict[str, int] | None = None) -> list[str]:
    """Tasks that had to be finished within the planned days, still have
    minutes left, and were not listed as unscheduled: the model went quiet.
    With `before` (minutes left before planning), a task without a deadline
    that got only part of its time, or none, is reported too."""
    out = []
    for t in tasks:
        n = left_after.get(t.id, 0)
        if t.done or n <= 0 or t.id in listed:
            continue
        if overdue(t, now):
            out.append(f"{t.id}: {n} min of '{t.title}' left and it is overdue - "
                       "place them now or list the task in unscheduled")
        elif t.due is not None and t.due.date() <= last_day:
            out.append(f"{t.id}: {n} min of '{t.title}' left before {t.due:%a %Y-%m-%d %H:%M} - "
                       "place them or list the task in unscheduled")
        elif (t.due is None and before is not None
              and not (t.not_before and t.not_before.date() > last_day)):  # one that starts later had no chance
            had = before.get(t.id, 0)
            out.append(f"{t.id}: '{t.title}' (no deadline) got no time in the planned days" if n >= had else
                       f"{t.id}: '{t.title}' (no deadline): placed {had - n} of {had} min, {n} min don't fit "
                       "in the planned days")
    return out
