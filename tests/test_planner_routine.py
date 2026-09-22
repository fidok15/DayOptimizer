"""The user's typical week drives the plan when there is one."""
import dataclasses
from datetime import date, datetime
from pathlib import Path
from dayoptimizer.core.models import Event
from dayoptimizer.core.planner import plan_day
from dayoptimizer.core.rules import RoutineBlock, _parse_typical_week, load_rules

BASE = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
DAY = date(2026, 7, 3)  # a Friday
D = datetime(2026, 7, 3, 0, 0).astimezone()
EARLY = D.replace(hour=5)

FRIDAY = [RoutineBlock(7 * 60, 7 * 60 + 30, "Food", "Breakfast"),
          RoutineBlock(9 * 60, 17 * 60, "Work", ""),
          RoutineBlock(18 * 60, 19 * 60 + 30, "Gym", "Push day"),
          RoutineBlock(23 * 60, 24 * 60, "Sleep", "")]
RULES = dataclasses.replace(BASE, typical_week={4: FRIDAY})


def _ev(eid, cal, h1, h2, title="x", m1=0, m2=0):
    return Event(id=eid, calendar=cal, title=title, start=D.replace(hour=h1, minute=m1), end=D.replace(hour=h2, minute=m2))


def _created(changes):
    return [(c.title, f"{c.new_start:%H:%M}", f"{c.new_end:%H:%M}") for c in changes if c.kind == "create"]


def test_empty_calendar_gets_the_routine_and_nothing_generic():
    changes = plan_day(DAY, [], None, RULES, now=EARLY)
    assert _created(changes) == [("Breakfast", "07:00", "07:30"), ("Work", "09:00", "17:00"),
                                 ("Push day", "18:00", "19:30"), ("Sleep", "23:00", "00:00")]
    assert all(not c.requires_approval for c in changes if c.kind == "create")


def test_flexible_block_moves_to_nearest_free_time():
    dentist = _ev("d", "Important", 18, 19, title="Dentist")
    changes = plan_day(DAY, [dentist], None, RULES, now=EARLY)
    gym = next(c for c in changes if c.title == "Push day")
    assert (f"{gym.new_start:%H:%M}", f"{gym.new_end:%H:%M}") == ("19:00", "20:30")
    assert "Dentist" in gym.reason


def test_fixed_block_clash_is_only_noted():
    trip = _ev("t", "Important", 8, 10, title="Trip")
    changes = plan_day(DAY, [trip], None, RULES, now=EARLY)
    work = [c for c in changes if c.title == "Work"]
    assert [c.kind for c in work] == ["note"] and "Trip" in work[0].reason


def test_replan_is_idempotent_and_skips_the_past():
    first = plan_day(DAY, [], None, RULES, now=EARLY)
    on_calendar = [Event(id=str(i), calendar=c.category, title=c.title, start=c.new_start, end=c.new_end)
                   for i, c in enumerate(first) if c.kind == "create"]
    assert _created(plan_day(DAY, on_calendar, None, RULES, now=EARLY)) == []
    assert ("Breakfast", "07:00", "07:30") not in _created(plan_day(DAY, [], None, RULES, now=D.replace(hour=8)))


def test_day_left_empty_in_the_routine_stays_empty():
    # the user drew Friday only: an empty Saturday is their choice, no generic filler
    assert _created(plan_day(date(2026, 7, 4), [], None, RULES, now=D.replace(day=4, hour=5))) == []


def test_without_any_routine_generic_rules_still_apply():
    assert _created(plan_day(DAY, [], None, BASE, now=EARLY))


def test_parse_typical_week_from_config():
    week = _parse_typical_week({"fri": [{"start": "23:00", "end": "24:00", "category": "Sleep"},
                                        {"start": "09:00", "end": "08:00", "category": "Bad"}],
                                "xyz": []})
    assert week == {4: [RoutineBlock(1380, 1440, "Sleep", "")]}
