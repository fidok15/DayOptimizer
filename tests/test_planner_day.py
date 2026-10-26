from datetime import date, datetime, timedelta
from pathlib import Path

from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import adjust_gym, check_free_time, ensure_meals, insert_transport, plan_day
from dayoptimizer.core.rules import load_rules

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
D = datetime(2026, 7, 3, 0, 0).astimezone()

def _ev(eid, cal, h1, h2, title="x", m1=0, m2=0, location=None):
    return Event(id=eid, calendar=cal, title=title, location=location,
                 start=D.replace(hour=h1, minute=m1), end=D.replace(hour=h2, minute=m2))

def test_ensure_meals_creates_missing_dinner():
    events = [_ev("b", "Food", 8, 8, m2=30, title="Breakfast"),
              _ev("l", "Food", 13, 13, m2=45, title="Lunch")]
    changes = ensure_meals(events, RULES, date(2026, 7, 3))
    assert len(changes) == 1
    assert changes[0].kind == "create" and changes[0].category == "Food"
    assert changes[0].new_start.hour >= 18

def test_ensure_meals_skips_past_windows_and_past_slots():
    now = D.replace(hour=11, minute=50)
    changes = ensure_meals([], RULES, date(2026, 7, 3), now=now)
    names = [c.title for c in changes]
    assert "Breakfast" not in names
    lunch = next(c for c in changes if c.title == "Lunch")
    assert lunch.new_start >= now

def test_ensure_meals_noop_when_all_present():
    events = [_ev("b", "Food", 8, 8, m2=30), _ev("l", "Food", 13, 13, m2=45),
              _ev("d", "Food", 19, 19, m2=30)]
    assert ensure_meals(events, RULES, date(2026, 7, 3)) == []

def test_adjust_gym_moves_on_low_battery():
    events = [_ev("g", "Gym", 10, 11), _ev("w", "Work", 12, 16)]
    low = GarminSummary(date="2026-07-03", body_battery_start=25)
    changes = adjust_gym(events, low, RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=7))
    assert len(changes) == 1 and changes[0].kind == "move"
    assert changes[0].new_start > D.replace(hour=16)

def test_adjust_gym_user_fixed_gym_requires_approval():
    import dataclasses

    from dayoptimizer.core.rules import CategoryRule
    fixed_gym = dataclasses.replace(
        RULES, categories={**RULES.categories, "Gym": CategoryRule(movable=False, priority=5)})
    events = [_ev("g", "Gym", 10, 11, title="Climbing with Alex"), _ev("w", "Work", 12, 16)]
    low = GarminSummary(date="2026-07-03", body_battery_start=25)
    changes = adjust_gym(events, low, fixed_gym, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=7))
    assert len(changes) == 1 and changes[0].kind == "move"
    assert changes[0].requires_approval

def test_adjust_gym_planner_created_workout_moves_freely_even_when_gym_fixed():
    import dataclasses

    from dayoptimizer.core.rules import CategoryRule
    fixed_gym = dataclasses.replace(
        RULES, categories={**RULES.categories, "Gym": CategoryRule(movable=False, priority=5)})
    events = [_ev("g", "Gym", 10, 11, title="Workout"), _ev("w", "Work", 12, 16)]
    low = GarminSummary(date="2026-07-03", body_battery_start=25)
    changes = adjust_gym(events, low, fixed_gym, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=7))
    assert len(changes) == 1 and changes[0].kind == "move"
    assert not changes[0].requires_approval

def test_adjust_gym_noop_when_recovered():
    events = [_ev("g", "Gym", 10, 11)]
    ok = GarminSummary(date="2026-07-03", body_battery_start=80, hrv_status="BALANCED")
    assert adjust_gym(events, ok, RULES, D.replace(hour=6), D.replace(hour=23), now=D.replace(hour=7)) == []

def test_insert_transport_before_located_event(monkeypatch):
    monkeypatch.setitem(RULES.transport_routes, "Campus", 25)
    events = [_ev("w", "Work", 10, 12, location="University Campus")]
    changes = insert_transport(events, RULES)
    there, back = changes
    assert there.category == back.category == "Transport"
    assert there.new_end == events[0].start and back.new_start == events[0].end

def test_one_trip_there_before_the_first_class_and_one_back_after_the_last(monkeypatch):
    monkeypatch.setitem(RULES.transport_routes, "School", 45)
    classes = [_ev("a", "School", 8, 9, title="Lecture - Maths"),
               _ev("b", "School", 11, 12, title="Lab - Maths", location="Main Street 7"),
               _ev("c", "School", 17, 18, title="Lab - Physics")]
    changes = insert_transport(classes + [_ev("d", "Work", 19, 20)], RULES)
    trips = [(f"{c.new_start:%H:%M}", f"{c.new_end:%H:%M}", c.title) for c in changes]
    assert trips == [("07:15", "08:00", "Commute: Lecture - Maths"), ("18:00", "18:45", "Commute: back from Lab - Physics")]
    made = [_ev(f"t{i}", "Transport", 0, 0) for i in range(2)]
    for ev, c in zip(made, changes, strict=True):
        ev.start, ev.end = c.new_start, c.new_end
    assert insert_transport(classes + made, RULES) == []

def test_check_free_time_warns_on_packed_day():
    events = [_ev("a", "Work", 6, 14), _ev("b", "Learn", 14, 22, m2=30)]
    changes = check_free_time(events, RULES, D.replace(hour=6), D.replace(hour=23))
    assert len(changes) == 1 and changes[0].kind == "note"

def test_plan_day_does_not_recreate_sleep_existing_on_next_day():
    from datetime import timedelta
    next_sleep = Event(id="s", calendar="Sleep", title="Sleep",
                       start=D + timedelta(days=1),
                       end=D.replace(hour=8) + timedelta(days=1))
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    changes = plan_day(date(2026, 7, 3), [], garmin, RULES, now=D.replace(hour=20),
                       next_day_events=[next_sleep])
    assert not any(c.kind == "create" and c.category == "Sleep" for c in changes)

def test_plan_day_previous_night_sleep_does_not_suppress_tonight():
    from datetime import timedelta
    last_night = Event(id="s0", calendar="Sleep", title="Sleep",
                       start=D.replace(hour=23, minute=30) - timedelta(days=1),
                       end=D.replace(hour=8))
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    changes = plan_day(date(2026, 7, 3), [last_night], garmin, RULES,
                       now=D.replace(hour=20), next_day_events=[])
    assert any(c.kind == "create" and c.category == "Sleep" for c in changes)

def test_ensure_meals_counts_shifted_meal_by_title():
    events = [_ev("b", "Food", 16, 16, m2=30, title="Breakfast")]
    changes = ensure_meals(events, RULES, date(2026, 7, 3), now=D.replace(hour=6),
                           day_start=D.replace(hour=6), day_end=D.replace(hour=23))
    assert not any(c.title == "Breakfast" and c.kind == "create" for c in changes)

def test_plan_day_returns_combined_changes():
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 11, 12)]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=5 * 3600, sleep_score=45)
    changes = plan_day(date(2026, 7, 3), events, garmin, RULES, now=D.replace(hour=7))
    kinds = {c.kind for c in changes}
    assert "move" in kinds
    assert any(c.category == "Sleep" for c in changes)
    assert any(c.category == "Food" for c in changes)


def test_plan_day_projects_gym_move_before_meals():
    events = [_ev("w", "Work", 9, 12, m2=30), _ev("g", "Gym", 12, 13)]
    changes = plan_day(date(2026, 7, 3), events, None, RULES, now=D.replace(hour=7))

    intervals = [(c.new_start, c.new_end) for c in changes
                 if c.kind in ("move", "create") and c.new_start is not None]
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            s1, e1 = intervals[i]
            s2, e2 = intervals[j]
            assert not (s1 < e2 and s2 < e1), (
                f"overlapping changes: {intervals[i]} vs {intervals[j]}"
            )

    gym_move = next(c for c in changes if c.kind == "move" and c.event_id == "g")
    food_creates = [c for c in changes if c.kind == "create" and c.category == "Food"]
    assert food_creates
    for f in food_creates:
        assert not (gym_move.new_start < f.new_end and f.new_start < gym_move.new_end)


def test_plan_day_dedupes_multiple_moves_same_event():
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 11, 12)]
    low = GarminSummary(date="2026-07-03", body_battery_start=25)
    changes = plan_day(date(2026, 7, 3), events, low, RULES, now=D.replace(hour=7))
    gym_moves = [c for c in changes if c.kind == "move" and c.event_id == "g"]
    assert len(gym_moves) == 1


def test_plan_day_respects_configured_day_end():
    import dataclasses
    from datetime import time
    short_day = dataclasses.replace(RULES, day_end=time(21, 30))
    events = [_ev("w", "Work", 9, 12)]
    changes = plan_day(date(2026, 7, 3), events, None, short_day, now=D.replace(hour=7))
    cutoff = D.replace(hour=21, minute=30)
    offenders = [c for c in changes
                 if c.category != "Sleep" and c.new_end is not None and c.new_end > cutoff]
    assert not offenders, offenders


def test_plan_day_is_workday_false_skips_own_work():
    events = [_ev("w", "Work", 9, 12)]
    changes = plan_day(date(2026, 7, 3), events, None, RULES, now=D.replace(hour=7),
                       is_workday=False)
    assert not any(c.title == "Own work" for c in changes)


def test_plan_day_is_workday_default_true_unchanged():
    events = [_ev("w", "Work", 9, 12)]
    changes = plan_day(date(2026, 7, 3), events, None, RULES, now=D.replace(hour=7))
    assert any(c.title == "Own work" for c in changes)


def test_plan_day_respects_configured_day_start():
    import dataclasses
    from datetime import time
    late_day = dataclasses.replace(RULES, day_start=time(9, 0))
    events = [_ev("w", "Work", 10, 12)]
    changes = plan_day(date(2026, 7, 3), events, None, late_day, now=D.replace(hour=7))
    floor = D.replace(hour=9)
    offenders = [c for c in changes if c.new_start is not None and c.new_start < floor]
    assert not offenders, offenders


def test_wind_down_sits_right_before_sleep_or_not_at_all():
    for evening_busy in (False, True):
        events = [_ev("w", "Work", 9, 12)] + ([_ev("m", "Meeting", 18, 21)] if evening_busy else [])
        changes = plan_day(date(2026, 7, 3), events, None, RULES, now=D.replace(hour=7),
                           week_gym_count=RULES.gym_per_week)
        sleep = next(c for c in changes if c.title == "Sleep")
        wind_down = [c for c in changes if c.title == "Wind-down"]
        assert len(wind_down) == (0 if evening_busy else 1)
        for wd in wind_down:
            assert sleep.new_start - wd.new_end <= timedelta(minutes=RULES.buffer_minutes)


def test_plan_never_creates_blocks_in_categories_the_user_does_not_have():
    import dataclasses
    only_work = dataclasses.replace(RULES, categories={"Work": RULES.categories["Work"]})
    changes = plan_day(date(2026, 7, 3), [], None, only_work, now=D.replace(hour=6))
    assert {c.category for c in changes if c.kind == "create"} <= {"Work"}
