from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
import yaml
from dayoptimizer.core.constraints import parse_rules

@dataclass
class CategoryRule:
    movable: bool
    priority: int = 5

@dataclass
class MealWindow:
    name: str
    start: time
    end: time
    duration_minutes: int

@dataclass
class RoutineBlock:
    """One block of the user's typical week, in minutes since midnight (end <= 1440)."""
    start: int
    end: int
    category: str
    title: str

    @property
    def label(self) -> str:
        return self.title or self.category

_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DEFAULT_WORK_DAYS = frozenset({0, 1, 2, 3, 4})
_DEFAULT_HOLIDAY_CALENDARS = ["Public Holidays", "Holidays"]

@dataclass
class Rules:
    categories: dict[str, CategoryRule]
    gym_per_week: int
    meal_windows: list[MealWindow]
    min_free_minutes: int
    deep_work_minutes: int
    sleep_target_hours: float
    morning_buffer_minutes: int
    transport_routes: dict[str, int] = field(default_factory=dict)
    deep_work_blocks_per_day: int = 2
    buffer_minutes: int = 15
    wind_down_minutes: int = 45
    free_time_activity: str = "Free time"
    gym_duration_minutes: int = 75
    day_start: time = time(6, 0)
    day_end: time = time(23, 0)
    note_rules: list = field(default_factory=list)  # compiled from the user's notes
    respect_recovery: bool = True
    recovery_lighter_hours: int = 24
    recovery_skip_hours: int = 48
    work_days: frozenset[int] = field(default_factory=lambda: _DEFAULT_WORK_DAYS)
    holiday_calendars: list[str] = field(default_factory=lambda: list(_DEFAULT_HOLIDAY_CALENDARS))
    # weekday (0 = Monday) -> the user's routine for that day, from the setup page
    typical_week: dict[int, list[RoutineBlock]] = field(default_factory=dict)

    @property
    def has_routine(self) -> bool:
        return any(self.typical_week.values())

    @property
    def routine_titles(self) -> frozenset[str]:
        return frozenset(b.label for blocks in self.typical_week.values() for b in blocks)

    def is_movable(self, category: str) -> bool:
        rule = self.categories.get(category)
        return rule.movable if rule else False  # unknown categories are fixed

    def priority(self, category: str) -> int:
        rule = self.categories.get(category)
        return rule.priority if rule else 5

def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))

def _parse_work_days(names: list[str]) -> frozenset[int]:
    result = set()
    for name in names:
        key = str(name).strip().lower()
        if key not in _WEEKDAY_NAMES:
            raise ValueError(
                f"invalid work_days entry {name!r} — valid values are "
                f"{', '.join(_WEEKDAY_NAMES)}")
        result.add(_WEEKDAY_NAMES.index(key))
    return frozenset(result)

def load_config_data(path: str | Path, user_path: str | Path | None = None) -> dict:
    """Base config merged with the user's private config.local.yaml from the
    app dir (~/.dayoptimizer) — private per-user overrides never enter a repo."""
    from dayoptimizer.paths import user_config_path
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    user_path = user_config_path() if user_path is None else Path(user_path)
    if user_path.exists():
        local = yaml.safe_load(user_path.read_text()) or {}
        for section, val in local.items():
            if isinstance(val, dict) and isinstance(data.get(section), dict):
                data[section].update(val)
            else:
                data[section] = val
    # a user may drop a default category by mapping it to null
    data["categories"] = {k: v for k, v in data.get("categories", {}).items() if v is not None}
    return data

def _day_window(d: dict) -> tuple[time, time]:
    day_start = _parse_time(d["day_start"]) if "day_start" in d else time(6, 0)
    day_end = _parse_time(d["day_end"]) if "day_end" in d else time(23, 0)
    if day_start >= day_end:
        # inverted/degenerate window — e.g. a partial user override merged with
        # the default for the other bound (validate_config only sees the user's
        # snippet, so it cannot catch this). The planner must stay functional
        # in background runs, so fall back to the defaults instead of raising.
        return time(6, 0), time(23, 0)
    return day_start, day_end

def _minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)

def _parse_typical_week(week) -> dict[int, list[RoutineBlock]]:
    out: dict[int, list[RoutineBlock]] = {}
    for name, blocks in (week or {}).items():
        if name not in _WEEKDAY_NAMES or not isinstance(blocks, list):
            continue
        parsed = [RoutineBlock(_minutes(b["start"]), _minutes(b["end"]), b["category"], b.get("title") or "")
                  for b in blocks if isinstance(b, dict) and {"start", "end", "category"} <= b.keys()]
        out[_WEEKDAY_NAMES.index(name)] = sorted((b for b in parsed if b.end > b.start), key=lambda b: b.start)
    return out

def load_rules(path: str | Path, user_path: str | Path | None = None) -> Rules:
    data = load_config_data(path, user_path)
    cats = {
        name: CategoryRule(movable=c.get("movable", False), priority=c.get("priority", 5))
        for name, c in data["categories"].items()
    }
    meals = [
        MealWindow(m["name"], _parse_time(m["start"]), _parse_time(m["end"]), m["duration_minutes"])
        for m in data["day_rules"]["meal_windows"]
    ]
    d = data["day_rules"]
    day_start, day_end = _day_window(d)
    work_days = (_parse_work_days(d["work_days"]) if "work_days" in d
                 else _DEFAULT_WORK_DAYS)
    holiday_calendars = data.get("holiday_calendars", list(_DEFAULT_HOLIDAY_CALENDARS))
    return Rules(
        categories=cats,
        gym_per_week=d["gym_per_week"],
        meal_windows=meals,
        min_free_minutes=d["min_free_minutes"],
        deep_work_minutes=d["deep_work_minutes"],
        sleep_target_hours=d["sleep_target_hours"],
        morning_buffer_minutes=d["morning_buffer_minutes"],
        transport_routes=data.get("transport_routes", {}),
        deep_work_blocks_per_day=d.get("deep_work_blocks_per_day", 2),
        buffer_minutes=d.get("buffer_minutes", 15),
        wind_down_minutes=d.get("wind_down_minutes", 45),
        free_time_activity=d.get("free_time_activity", "Free time"),
        gym_duration_minutes=d.get("gym_duration_minutes", 75),
        day_start=day_start,
        day_end=day_end,
        note_rules=parse_rules(data.get("note_rules")),
        respect_recovery=d.get("respect_recovery", True),
        recovery_lighter_hours=d.get("recovery_lighter_hours", 24),
        recovery_skip_hours=d.get("recovery_skip_hours", 48),
        work_days=work_days,
        holiday_calendars=holiday_calendars,
        typical_week=_parse_typical_week(data.get("typical_week")),
    )
