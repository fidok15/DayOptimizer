from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


def at(midnight: datetime, m: float) -> datetime:
    """`m` minutes after `midnight` by the clock: 18:30 stays 18:30 on the day the clocks change."""
    return (midnight.replace(tzinfo=None) + timedelta(minutes=m)).astimezone()

def minutes(start: datetime, end: datetime) -> int:
    """Minutes from `start` to `end` by the clock (an hour off elapsed time across a clock change)."""
    return int((end.astimezone().replace(tzinfo=None) - start.astimezone().replace(tzinfo=None)).total_seconds() // 60)

@dataclass
class Event:
    id: str
    calendar: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    all_day: bool = False
    managed: bool = False
    task_id: str | None = None
    suggested: bool = False  # a planner block suggested for free time (llm/fillers.py)

@dataclass
class GarminSummary:
    date: str
    sleep_seconds: int | None = None
    sleep_score: int | None = None
    body_battery_start: int | None = None
    hrv_status: str | None = None
    stress_avg: int | None = None
    resting_hr: int | None = None
    recovery_minutes: int | None = None
    recovery_measured_at: str | None = None
    readiness_score: int | None = None
    readiness_level: str | None = None

@dataclass
class Activity:
    """A workout the watch recorded. `type_key` is Garmin's own (running,
    strength_training, ...); the training effects say how hard it was."""
    id: str
    type_key: str
    name: str
    start: datetime
    end: datetime
    aerobic_te: float = 0.0
    anaerobic_te: float = 0.0

@dataclass
class PlannedChange:
    kind: Literal["move", "create", "delete", "note"]
    category: str
    title: str
    reason: str
    event_id: str | None = None
    new_start: datetime | None = None
    new_end: datetime | None = None
    requires_approval: bool = False
    task_id: str | None = None
    suggested: bool = False


@dataclass
class Task:
    """Work with a length the planner places into free time, before `due`
    and not before `not_before`. `min_chunk_min` None = one piece."""
    id: str
    title: str
    category: str
    duration_min: int
    due: datetime | None = None
    not_before: datetime | None = None
    min_chunk_min: int | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    done: bool = False
    # routine block titles the user let it take when nothing can move ([] or ["*"] = any flexible one)
    may_take: list[str] | None = None
