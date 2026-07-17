from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import check_free_time, ensure_meals, fill_day, plan_day
from dayoptimizer.core.rules import load_rules

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
D = datetime(2026, 7, 3, 0, 0).astimezone()

def _ev(eid, cal, h1, h2, title="x", m1=0, m2=0):
    return Event(id=eid, calendar=cal, title=title,
                 start=D.replace(hour=h1, minute=m1), end=D.replace(hour=h2, minute=m2))

def _overlap(a, b):
    return a.new_start < b.new_end and b.new_start < a.new_end

def test_fill_day_adds_deep_work_with_buffers():
    events = [_ev("w", "Work", 9, 12)]
    changes = fill_day(events, RULES, D.replace(hour=6), D.replace(hour=22), now=D.replace(hour=6))
    deep = [c for c in changes if c.category == "Learn"]
    assert len(deep) == RULES.deep_work_blocks_per_day
    for c in deep:
        # buffer: never glued to the Work block
        assert not (c.new_start < D.replace(hour=12, minute=15) and c.new_end > D.replace(hour=8, minute=45))
    creates = [c for c in changes if c.kind == "create"]
    for i, a in enumerate(creates):
        for b in creates[i + 1:]:
            assert not _overlap(a, b), f"{a.title} overlaps {b.title}"

def test_fill_day_adds_wind_down_at_end():
    changes = fill_day([], RULES, D.replace(hour=6), D.replace(hour=22, minute=30), now=D.replace(hour=20))
    wd = next(c for c in changes if "Wind-down" in c.title)
    assert wd.new_end == D.replace(hour=22, minute=30)
    assert wd.category == "Free time"

def test_fill_day_adds_free_time_block():
    changes = fill_day([], RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    ft = [c for c in changes if c.category == "Free time" and "Wind-down" not in c.title]
    assert len(ft) == 1
    assert (ft[0].new_end - ft[0].new_start) >= timedelta(minutes=RULES.min_free_minutes)

def test_fill_day_nothing_in_the_past():
    now = D.replace(hour=14)
    changes = fill_day([], RULES, D.replace(hour=6), D.replace(hour=23), now=now)
    for c in changes:
        assert c.new_start >= now

def test_fill_day_skips_planner_blocks_that_already_exist():
    # regression: on replan, fill_day re-created Wind-down/Deep work/Free time
    # next to the copies it made last time — existing titles must be counted
    events = [_ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down"),
              _ev("d1", "Learn", 9, 10, m2=30, title="Deep work"),
              _ev("d2", "Learn", 11, 12, m2=30, title="Deep work"),
              _ev("ft", "Free time", 14, 15, title=RULES.free_time_activity)]
    changes = fill_day(events, RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    titles = [c.title for c in changes if c.kind == "create"]
    assert "Wind-down" not in titles
    assert "Deep work" not in titles
    assert RULES.free_time_activity not in titles

def test_fill_day_tops_up_missing_deep_work_blocks():
    # one Deep work already on the calendar, quota is 2 -> exactly one more
    events = [_ev("d1", "Learn", 9, 10, m2=30, title="Deep work")]
    changes = fill_day(events, RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    deep = [c for c in changes if c.kind == "create" and c.title == "Deep work"]
    assert len(deep) == RULES.deep_work_blocks_per_day - 1

# --- Own work fills the whole slot, not fixed 60-min chunks with gaps -----

def test_fill_day_own_work_fills_a_3h_slot_as_one_block():
    # regression: fill_day used to chunk a free slot into fixed 60-min "Own
    # work" blocks separated by the inter-block buffer — users saw
    # "1h, 15-min gap, 1h, 15-min gap" instead of one continuous block.
    rules = replace(RULES, deep_work_blocks_per_day=0)
    events = [
        _ev("ft", "Free time", 6, 7, title=rules.free_time_activity),
        _ev("m", "Meeting", 10, 22, m1=30, title="Standup"),
        _ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down"),
    ]
    changes = fill_day(events, rules, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    own_work = [c for c in changes if c.title == "Own work"]
    assert len(own_work) == 1
    assert own_work[0].new_start == D.replace(hour=7, minute=15)
    assert own_work[0].new_end == D.replace(hour=10, minute=15)
    assert own_work[0].new_end - own_work[0].new_start == timedelta(hours=3)

def test_fill_day_own_work_fills_every_remaining_slot_continuously():
    # two separate free slots -> two continuous Own work blocks, each
    # spanning its whole slot (no gaps carved out of either).
    rules = replace(RULES, deep_work_blocks_per_day=0)
    events = [
        _ev("ft", "Free time", 6, 7, title=rules.free_time_activity),
        _ev("m1", "Meeting", 9, 10, title="Standup"),
        _ev("m2", "Meeting", 13, 14, title="Review"),
        _ev("m3", "Meeting", 14, 22, m1=30, title="Afternoon block"),
        _ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down"),
    ]
    changes = fill_day(events, rules, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    own_work = sorted((c for c in changes if c.title == "Own work"), key=lambda c: c.new_start)
    assert len(own_work) == 2
    assert own_work[0].new_start == D.replace(hour=7, minute=15)
    assert own_work[0].new_end == D.replace(hour=8, minute=45)
    assert own_work[1].new_start == D.replace(hour=10, minute=15)
    assert own_work[1].new_end == D.replace(hour=12, minute=45)

def test_fill_day_own_work_skips_slots_under_60_minutes():
    rules = replace(RULES, deep_work_blocks_per_day=0)
    events = [
        _ev("ft", "Free time", 6, 7, title=rules.free_time_activity),
        # only a 30-min gap remains between the free-time block (padded to
        # 7:15) and the next fixed event (padded start 7:45)
        _ev("m", "Meeting", 8, 22, title="Standup"),
        _ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down"),
    ]
    changes = fill_day(events, rules, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    assert [c for c in changes if c.title == "Own work"] == []

def test_fill_day_skips_own_work_when_not_a_workday():
    rules = replace(RULES, deep_work_blocks_per_day=0)
    events = [
        _ev("ft", "Free time", 6, 7, title=rules.free_time_activity),
        _ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down"),
    ]
    changes = fill_day(events, rules, D.replace(hour=6), D.replace(hour=23),
                       now=D.replace(hour=6), is_workday=False)
    assert [c for c in changes if c.title == "Own work"] == []


def test_fill_day_is_workday_default_true_unchanged_behavior():
    events = [_ev("ft", "Free time", 6, 7, title=RULES.free_time_activity),
              _ev("wd", "Free time", 22, 22, m1=15, m2=59, title="Wind-down")]
    changes = fill_day(events, RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=6))
    own_work = [c for c in changes if c.title == "Own work"]
    assert own_work  # unchanged default behavior — Own work still gets filled


def test_fill_day_rest_day_still_gets_deep_work_and_free_time():
    # rest day: no Own work, but the rest of the structure (deep work, free
    # time) is still planned — a holiday isn't an empty day.
    changes = fill_day([], RULES, D.replace(hour=6), D.replace(hour=22, minute=30),
                       now=D.replace(hour=6), is_workday=False)
    assert [c for c in changes if c.title == "Own work"] == []
    assert any(c.category == "Learn" for c in changes)
    assert any("Wind-down" in c.title for c in changes)


def test_ensure_meals_shifts_dinner_after_blocked_window():
    # GDG 16-21 blocks the entire dinner window (18:30-21:00) -> dinner moves past 21:00
    events = [_ev("gdg", "Meeting", 16, 21, title="GDG")]
    changes = ensure_meals(events, RULES, date(2026, 7, 3), now=D.replace(hour=15),
                           day_end=D.replace(hour=23))
    dinner = next(c for c in changes if c.title == "Dinner")
    assert dinner.kind == "create"
    assert dinner.new_start >= D.replace(hour=21)
    assert "moved" in dinner.reason.lower()

def test_check_free_time_counts_free_time_events():
    # day is packed, but an explicit Free time block >= minimum exists -> no warning
    events = [_ev("a", "Work", 6, 21), _ev("f", "Free time", 21, 22, m2=30)]
    assert check_free_time(events, RULES, D.replace(hour=6), D.replace(hour=22, minute=30)) == []

def test_plan_day_generates_full_day_gdg_scenario():
    # today's scenario: 11:50, GDG 16-21, lunch already exists
    events = [_ev("gdg", "Meeting", 16, 21, title="GDG — workshop"),
              _ev("ob", "Food", 12, 13, m1=30, m2=15, title="Lunch")]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=int(5.83 * 3600), sleep_score=72,
                           body_battery_start=24, hrv_status="UNBALANCED")
    changes = plan_day(date(2026, 7, 3), events, garmin, RULES, now=D.replace(hour=11, minute=50))
    creates = [c for c in changes if c.kind == "create"]
    cats = {c.category for c in creates}
    assert "Learn" in cats                      # deep work in the 13:15-16 window
    assert "Sleep" in cats                      # sleep as an event
    dinner = next(c for c in creates if c.title == "Dinner")
    assert dinner.new_start >= D.replace(hour=21)
    deep = next(c for c in creates if c.category == "Learn")
    assert D.replace(hour=13) <= deep.new_start <= D.replace(hour=16)
    for i, a in enumerate(creates):
        for b in creates[i + 1:]:
            assert not _overlap(a, b), f"{a.title} overlaps {b.title}"

def test_plan_day_skips_sleep_event_when_already_present():
    events = [_ev("s", "Sleep", 23, 23, m2=59, title="Sleep")]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    changes = plan_day(date(2026, 7, 3), events, garmin, RULES, now=D.replace(hour=20))
    assert not any(c.kind == "create" and c.category == "Sleep" for c in changes)
