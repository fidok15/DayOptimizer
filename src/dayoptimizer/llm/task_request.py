"""'raport na piątek, 3h, kawałki min godzinę, ważne' -> Tasks. The model
fills TaskList, one TaskRequest per piece of work (days as words, like
DayRequest); the dates are worked out here so the model never does calendar
arithmetic."""
from __future__ import annotations
import re
from datetime import date, datetime, time
from typing import Literal
from pydantic import BaseModel
from dayoptimizer.core.models import Task
from dayoptimizer.llm.backend import DayWord, resolve_day


class TaskRequest(BaseModel):
    title: str = ""
    category: str = ""
    duration_minutes: int | None = None
    due_day: DayWord | None = None
    due_time: str | None = None
    not_before_day: DayWord | None = None
    min_chunk_minutes: int | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class TaskList(BaseModel):
    tasks: list[TaskRequest] = []
    reply: str | None = None


TASK_SYSTEM = (
    "You turn a user's message about work into tasks for the DayOptimizer planner, which will "
    "place them into free time. The message may name one piece of work or several; return one "
    "task per piece, in the order said. Details said once for all of them ('każde 2h', 'all for "
    "tomorrow') go into every task they cover. The message may be in any language; keep the "
    "titles in that language. Each task:\n"
    "- title: the work alone, without its day, time or length.\n"
    "- category: exactly one of the listed categories, the closest fit for what the work is.\n"
    "- duration_minutes: total time the work takes: '3h' = 180, 'półtorej godziny' = 90, "
    "'45 min' = 45. Empty if not said.\n"
    "- due_day: the day it must be done by, as a word (today, tomorrow, day_after_tomorrow or a "
    "weekday name); empty when there is no deadline. 'na piątek' / 'by Friday' = friday. "
    "due_time: HH:MM when a time is said ('do 17' = 17:00), else empty.\n"
    "- not_before_day: the day work may start, only when the message says so "
    "('od środy', 'not before Wednesday').\n"
    "- min_chunk_minutes: when the user allows splitting, the shortest piece "
    "('w kawałkach min. godzinę' = 60, 'in 30-minute chunks' = 30). Empty when not said.\n"
    "- priority: high for 'ważne', 'pilne', 'important', 'urgent'; low for 'kiedyś', "
    "'low priority', 'when there's time'; otherwise normal.\n"
    "If the message isn't about work to do, return no tasks and a short reply.\n"
    "Example, categories Work, Learn, Home: 'raport kwartalny na piątek do 17, 3h, kawałki min "
    "godzinę, ważne' -> "
    '{"tasks":[{"title":"raport kwartalny","category":"Work","duration_minutes":180,'
    '"due_day":"friday","due_time":"17:00","min_chunk_minutes":60,"priority":"high"}]}\n'
    "Example: 'jutro muszę zrobić pranie i nauczyć się do kolokwium, każde 2h' -> "
    '{"tasks":[{"title":"pranie","category":"Home","duration_minutes":120,"due_day":"tomorrow"},'
    '{"title":"nauka do kolokwium","category":"Learn","duration_minutes":120,"due_day":"tomorrow"}]}'
)


def task_prompt(text: str, now: str, categories: list[str]) -> str:
    return f"now: {now}\ncategories: {', '.join(categories)}\nmessage: {text}"


def _hhmm(value: str | None) -> time | None:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (value or "").strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def task_from_request(req: TaskRequest, categories: list[str], today: date,
                      task_id: str) -> tuple[Task | None, str | None]:
    """The task, or why there is none (said back to the user)."""
    title = req.title.strip()
    if not title:
        return None, "Say what the task is, e.g. 'report for Friday, 3h'."
    if not req.duration_minutes or req.duration_minutes <= 0:
        return None, f"How long will '{title}' take? Add it, e.g. '{title}, 2h'."
    if req.duration_minutes >= 24 * 60:
        return None, "A task must be shorter than 24 hours; split it into several tasks."
    if req.category not in categories:
        return None, f"'{req.category}' is not one of your categories ({', '.join(categories)})."
    due = None
    if req.due_day:
        due = datetime.combine(resolve_day(req.due_day, today), _hhmm(req.due_time) or time(23, 59)).astimezone()
    not_before = None
    if req.not_before_day:
        not_before = datetime.combine(resolve_day(req.not_before_day, today), time(0)).astimezone()
    chunk = req.min_chunk_minutes
    if not chunk or chunk <= 0 or chunk >= req.duration_minutes:
        chunk = None
    return Task(id=task_id, title=title[:100], category=req.category, duration_min=req.duration_minutes,
                due=due, not_before=not_before, min_chunk_min=chunk, priority=req.priority), None
