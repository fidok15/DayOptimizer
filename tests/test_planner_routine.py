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


def test_routine_training_reacts_to_recovery():
    from dayoptimizer.core.models import Activity, GarminSummary
    from datetime import timedelta
    # the watch recorded a run in the Friday 18:00 block on past Fridays: it's a legs session
    history = [Activity(id=str(d), type_key="running", name="Evening run",
                        start=D.replace(month=6, day=d, hour=18, minute=5),
                        end=D.replace(month=6, day=d, hour=19),
                        aerobic_te=3.0) for d in (19, 26)]  # the two Fridays before
    race = Activity(id="race", type_key="running", name="Half marathon",
                    start=D.replace(day=1, hour=15), end=D.replace(day=1, hour=17), aerobic_te=5.0)
    rules = dataclasses.replace(RULES, typical_week={4: [RoutineBlock(18 * 60, 19 * 60, "Gym", "Run")]})
    poor = GarminSummary(date="2026-07-03", recovery_minutes=50 * 60,
                         recovery_measured_at=(D.replace(hour=7)).isoformat())

    changes = plan_day(DAY, [], poor, rules, now=EARLY, activities=history + [race])
    note = next(c for c in changes if c.title == "Run")
    assert note.kind == "note" and "Half marathon" in note.reason and "walk" in note.reason

    # same recovery, but the block is upper body: it stays, flagged as easy
    upper = [Activity(id="u", type_key="lap_swimming", name="Swim",
                      start=D.replace(month=6, day=26, hour=18, minute=5), end=D.replace(month=6, day=26, hour=19),
                      aerobic_te=3.0)]
    changes = plan_day(DAY, [], poor, rules, now=EARLY, activities=upper + [race])
    kept = next(c for c in changes if c.title == "Run")
    assert kept.kind == "create" and "keep it easy" in kept.reason

    # recovered: nothing added to the reason
    fresh = dataclasses.replace(poor, recovery_minutes=60)
    kept = next(c for c in plan_day(DAY, [], fresh, rules, now=EARLY, activities=history + [race])
                if c.title == "Run")
    assert kept.kind == "create" and "—" not in kept.reason

    # respect_recovery: false leaves training alone
    off = dataclasses.replace(rules, respect_recovery=False)
    kept = next(c for c in plan_day(DAY, [], poor, off, now=EARLY, activities=history + [race]) if c.title == "Run")
    assert kept.kind == "create" and "recovery" not in kept.reason


def _with_notes(raw, week):
    from dayoptimizer.core.constraints import parse_rules
    return dataclasses.replace(RULES, note_rules=parse_rules(raw), typical_week=week)


def test_note_rule_moves_a_block_out_of_a_forbidden_window():
    # "no lunch before 14:00", but the routine has it at 12:00
    rules = _with_notes([{"type": "not_before", "category": "Food", "time": "14:00",
                          "source": "no lunch before 14"}],
                        {4: [RoutineBlock(12 * 60, 12 * 60 + 45, "Food", "Lunch")]})
    lunch = next(c for c in plan_day(DAY, [], None, rules, now=EARLY) if c.title == "Lunch")
    assert (lunch.kind, f"{lunch.new_start:%H:%M}") == ("create", "14:00")
    assert "no lunch before 14" in lunch.reason


def test_keep_free_window_is_as_binding_as_an_event():
    rules = _with_notes([{"type": "keep_free", "weekday": "fri", "start": "18:00", "end": "21:00",
                          "source": "family time"}],
                        {4: [RoutineBlock(18 * 60, 19 * 60, "Gym", "Workout"),
                             RoutineBlock(19 * 60, 20 * 60, "Work", "Emails")]})
    changes = plan_day(DAY, [], None, rules, now=EARLY)
    gym = next(c for c in changes if c.title == "Workout")
    # flexible: moved to the nearest time outside the window (17:00 is nearer than 21:00)
    assert gym.kind == "create" and f"{gym.new_start:%H:%M}" == "17:00"
    assert gym.new_end <= D.replace(hour=18) or gym.new_start >= D.replace(hour=21)
    emails = next(c for c in changes if c.title == "Emails")
    assert emails.kind == "note" and "family time" in emails.reason  # fixed: only flagged


def test_min_gap_and_weekly_limit_skip_the_block():
    week = {4: [RoutineBlock(18 * 60, 19 * 60, "Gym", "Workout")]}
    gap = _with_notes([{"type": "min_gap_days", "category": "Gym", "days": 2,
                        "source": "no training two days in a row"}], week)
    note = next(c for c in plan_day(DAY, [], None, gap, now=EARLY,
                                    history={"Gym": [date(2026, 7, 2)]}) if c.title == "Workout")
    assert note.kind == "note" and "two days in a row" in note.reason
    # two days off is enough: the block is placed
    assert next(c for c in plan_day(DAY, [], None, gap, now=EARLY,
                                    history={"Gym": [date(2026, 7, 1)]}) if c.title == "Workout").kind == "create"
    weekly = _with_notes([{"type": "max_per_week", "category": "Gym", "count": 2, "source": "gym 2x a week"}], week)
    note = next(c for c in plan_day(DAY, [], None, weekly, now=EARLY,
                                    history={"Gym": [date(2026, 6, 29), date(2026, 7, 1)]}) if c.title == "Workout")
    assert note.kind == "note" and "gym 2x a week" in note.reason


def test_a_title_repeated_in_one_day_is_placed_every_time():
    split = [RoutineBlock(0, 7 * 60, "Sleep", "Sleep"), RoutineBlock(9 * 60, 12 * 60, "Work", "Work"),
             RoutineBlock(13 * 60, 17 * 60, "Work", "Work"), RoutineBlock(23 * 60, 24 * 60, "Sleep", "Sleep")]
    rules = dataclasses.replace(BASE, typical_week={4: split})
    assert _created(plan_day(DAY, [], None, rules, now=D)) == [
        ("Sleep", "00:00", "07:00"), ("Work", "09:00", "12:00"), ("Work", "13:00", "17:00"), ("Sleep", "23:00", "00:00")]
    # replan with everything on the calendar: nothing new
    on_cal = [_ev("s1", "Sleep", 0, 7, "Sleep"), _ev("w1", "Work", 9, 12, "Work"),
              _ev("w2", "Work", 13, 17, "Work"), _ev("s2", "Sleep", 23, 23, "Sleep", m2=59)]
    assert _created(plan_day(DAY, on_cal, None, rules, now=D)) == []
    # at 12:30 the morning block has passed: the afternoon one still isn't doubled
    assert _created(plan_day(DAY, on_cal[:2], None, rules, now=D.replace(hour=12, minute=30))) == [
        ("Work", "13:00", "17:00"), ("Sleep", "23:00", "00:00")]
    assert _created(plan_day(DAY, on_cal, None, rules, now=D.replace(hour=12, minute=30))) == []


def test_a_block_pushed_by_a_new_event_still_obeys_the_notes():
    # languages 20:00-21:00 already on the calendar, "not after 21:00"; a new
    # meeting lands on it: the block moves to the nearest time that keeps the
    # rule (earlier), never past 21:00
    rules = _with_notes([{"type": "not_after", "category": "Learn", "time": "21:00", "source": "no study after 21"}],
                        {})
    events = [_ev("l", "Learn", 20, 21, "English"), _ev("m", "Meeting", 20, 21, "Ania", m1=15)]
    moves = [c for c in plan_day(DAY, events, None, rules, now=EARLY) if c.kind == "move"]
    assert [(c.title, f"{c.new_start:%H:%M}", f"{c.new_end:%H:%M}") for c in moves] == [("English", "19:15", "20:15")]
