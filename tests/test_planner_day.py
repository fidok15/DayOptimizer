from datetime import datetime, date
from pathlib import Path
from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import ensure_meals, adjust_gym, insert_transport, check_free_time, plan_day
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
    # 11:50: breakfast window (07-10) is already over -> skipped; lunch window (12:30-15:30) is still ahead -> created
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
    assert changes[0].new_start > D.replace(hour=16)  # later = more recovery

def test_adjust_gym_user_fixed_gym_requires_approval():
    # user marked Gym as fixed: a user-created gym event may be proposed to
    # move, but never applied without approval
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
    # "Workout" is a planner-created block — the planner's own to reschedule,
    # even inside a category the user marked fixed
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
    assert len(changes) == 1 and changes[0].category == "Transport"
    assert changes[0].new_end == events[0].start

def test_check_free_time_warns_on_packed_day():
    events = [_ev("a", "Work", 6, 14), _ev("b", "Learn", 14, 22, m2=30)]
    changes = check_free_time(events, RULES, D.replace(hour=6), D.replace(hour=23))
    assert len(changes) == 1 and changes[0].kind == "note"

def test_plan_day_does_not_recreate_sleep_existing_on_next_day():
    # regression: a planner-created Sleep block often starts at/after midnight,
    # i.e. among the NEXT day's events — invisible to the planned day's event
    # window, so every replan re-created it. next_day_events closes that hole.
    from datetime import timedelta
    next_sleep = Event(id="s", calendar="Sleep", title="Sleep",
                       start=D + timedelta(days=1),
                       end=D.replace(hour=8) + timedelta(days=1))
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    changes = plan_day(date(2026, 7, 3), [], garmin, RULES, now=D.replace(hour=20),
                       next_day_events=[next_sleep])
    assert not any(c.kind == "create" and c.category == "Sleep" for c in changes)

def test_plan_day_previous_night_sleep_does_not_suppress_tonight():
    # last night's sleep (ending this morning) overlaps today's event window
    # but is a DIFFERENT night — tonight's sleep must still be created
    from datetime import timedelta
    last_night = Event(id="s0", calendar="Sleep", title="Sleep",
                       start=D.replace(hour=23, minute=30) - timedelta(days=1),
                       end=D.replace(hour=8))
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    changes = plan_day(date(2026, 7, 3), [last_night], garmin, RULES,
                       now=D.replace(hour=20), next_day_events=[])
    assert any(c.kind == "create" and c.category == "Sleep" for c in changes)

def test_ensure_meals_counts_shifted_meal_by_title():
    # regression: a Breakfast an earlier replan shifted to 16:00 sits outside
    # its window — the overlap check missed it and every replan created another
    events = [_ev("b", "Food", 16, 16, m2=30, title="Breakfast")]
    changes = ensure_meals(events, RULES, date(2026, 7, 3), now=D.replace(hour=6),
                           day_start=D.replace(hour=6), day_end=D.replace(hour=23))
    assert not any(c.title == "Breakfast" and c.kind == "create" for c in changes)

def test_plan_day_returns_combined_changes():
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 11, 12)]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=5 * 3600, sleep_score=45)
    changes = plan_day(date(2026, 7, 3), events, garmin, RULES, now=D.replace(hour=7))
    kinds = {c.kind for c in changes}
    assert "move" in kinds          # gym conflict
    assert any(c.category == "Sleep" for c in changes)  # sleep suggestion
    assert any(c.category == "Food" for c in changes)   # missing meals


def test_plan_day_projects_gym_move_before_meals():
    # Gym conflicts with fixed Work; resolve_conflicts moves Gym right into
    # the lunch window. ensure_meals must see the moved Gym (not the
    # original position) so it doesn't schedule lunch on top of it.
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
    # Gym conflicts with fixed Work (resolve_conflicts moves it) AND body
    # battery is low (adjust_gym also wants to move it later). Only one
    # move change for the gym event id should survive.
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 11, 12)]
    low = GarminSummary(date="2026-07-03", body_battery_start=25)
    changes = plan_day(date(2026, 7, 3), events, low, RULES, now=D.replace(hour=7))
    gym_moves = [c for c in changes if c.kind == "move" and c.event_id == "g"]
    assert len(gym_moves) == 1


def test_plan_day_respects_configured_day_end():
    # day_end pulled in from rules (not hardcoded 23:00) — nothing the planner
    # places should end after it, except the Sleep window, which is anchored
    # to the wake-up time rather than to day_end.
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
    # symmetric to the day_end test: nothing starts before day_start. No Sleep
    # exemption needed here — suggest_sleep anchors bedtime to the wake time
    # (default 08:00 next day minus the sleep target), which lands around
    # midnight, well after a 09:00 day_start on the planned day.
    import dataclasses
    from datetime import time
    late_day = dataclasses.replace(RULES, day_start=time(9, 0))
    events = [_ev("w", "Work", 10, 12)]
    changes = plan_day(date(2026, 7, 3), events, None, late_day, now=D.replace(hour=7))
    floor = D.replace(hour=9)
    offenders = [c for c in changes if c.new_start is not None and c.new_start < floor]
    assert not offenders, offenders
