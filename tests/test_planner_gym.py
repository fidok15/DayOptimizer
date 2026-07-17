from datetime import datetime, date, timedelta
from pathlib import Path
from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import schedule_gym, plan_day
from dayoptimizer.core.rules import load_rules

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
D = datetime(2026, 7, 3, 0, 0).astimezone()
DAY_START = D.replace(hour=6)
DAY_END = D.replace(hour=23)

def _ev(eid, cal, h1, h2, title="x", m1=0, m2=0):
    return Event(id=eid, calendar=cal, title=title,
                 start=D.replace(hour=h1, minute=m1), end=D.replace(hour=h2, minute=m2))

def test_schedule_gym_creates_on_good_recovery_ending_by_21():
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = schedule_gym([], RULES, DAY_START, DAY_END, D.replace(hour=7), good, week_gym_count=1)
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "create" and c.category == "Gym" and c.title == "Workout"
    assert c.new_end <= D.replace(hour=21)
    assert c.new_end - c.new_start == timedelta(minutes=RULES.gym_duration_minutes)
    assert "workout 2/3" in c.reason

def test_schedule_gym_noop_when_weekly_quota_reached():
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = schedule_gym([], RULES, DAY_START, DAY_END, D.replace(hour=7), good,
                           week_gym_count=RULES.gym_per_week)
    assert changes == []

def test_schedule_gym_noop_on_low_body_battery():
    low = GarminSummary(date="2026-07-03", body_battery_start=25, hrv_status="BALANCED")
    changes = schedule_gym([], RULES, DAY_START, DAY_END, D.replace(hour=7), low, week_gym_count=0)
    assert changes == []

def test_schedule_gym_noop_when_gym_already_today():
    events = [_ev("g", "Gym", 10, 11, title="Workout")]
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = schedule_gym(events, RULES, DAY_START, DAY_END, D.replace(hour=7), good, week_gym_count=0)
    assert changes == []

def test_schedule_gym_wires_into_plan_day_without_duplicating_adjust_gym():
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = plan_day(date(2026, 7, 3), [], good, RULES, now=D.replace(hour=7), week_gym_count=0)
    gym_creates = [c for c in changes if c.kind == "create" and c.category == "Gym"]
    assert len(gym_creates) == 1

def test_schedule_gym_noop_when_nothing_left_in_the_past():
    # `now` is already past the 21:00 cutoff -> no viable slot remains today
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = schedule_gym([], RULES, DAY_START, DAY_END, D.replace(hour=21, minute=30),
                           good, week_gym_count=0)
    assert changes == []

def test_schedule_gym_garmin_none_is_treated_as_ok():
    changes = schedule_gym([], RULES, DAY_START, DAY_END, D.replace(hour=7), None, week_gym_count=0)
    assert len(changes) == 1

def test_schedule_gym_noop_when_day_starts_after_cutoff():
    # day window starting at/after the 21:00 workout cutoff excludes workout
    # hours entirely -> deliberate skip, no exception
    good = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    changes = schedule_gym([], RULES, D.replace(hour=22), D.replace(hour=23, minute=30),
                           D.replace(hour=22), good, week_gym_count=0)
    assert changes == []
