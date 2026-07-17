from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

@dataclass
class Event:
    id: str
    calendar: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    all_day: bool = False  # calendar marker (vacation/holiday/birthday): never
                            # busy time and never a scheduling anchor

@dataclass
class GarminSummary:
    date: str
    sleep_seconds: int | None = None
    sleep_score: int | None = None
    body_battery_start: int | None = None
    hrv_status: str | None = None
    stress_avg: int | None = None
    resting_hr: int | None = None

@dataclass
class PlannedChange:
    kind: Literal["move", "create", "note"]
    category: str
    title: str
    reason: str
    event_id: str | None = None
    new_start: datetime | None = None
    new_end: datetime | None = None
    requires_approval: bool = False
