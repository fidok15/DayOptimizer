"""End-to-end replan idempotency: planning the same day twice, with the first
run's blocks applied to the calendar, must not create or move anything more."""
from datetime import date, datetime, timedelta
from pathlib import Path

from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import plan_day, _project
from dayoptimizer.core.rules import load_rules

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
DAY = date(2026, 7, 3)
D = datetime(2026, 7, 3, 0, 0).astimezone()

def test_plan_day_second_pass_is_a_noop():
    events = [Event(id="w", calendar="Work", title="Sprint",
                    start=D.replace(hour=9), end=D.replace(hour=12))]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85,
                           body_battery_start=80, hrv_status="BALANCED")
    now = D.replace(hour=7)

    first = plan_day(DAY, events, garmin, RULES, now=now, week_gym_count=0)
    assert any(c.kind == "create" for c in first)  # first pass builds the day

    # apply the plan the way the calendar would end up: creates/moves projected
    # onto the event list, then split at midnight — the planned day's window
    # only sees events starting before midnight, the rest live on the next day
    projected = _project(events, first)
    midnight_next = D + timedelta(days=1)
    day_events = [e for e in projected if e.start < midnight_next]
    next_day = [e for e in projected if e.start >= midnight_next]

    second = plan_day(DAY, day_events, garmin, RULES, now=now,
                      next_day_events=next_day, week_gym_count=0)
    offenders = [c for c in second if c.kind in ("move", "create")]
    assert offenders == [], [f"{c.kind} {c.title} -> {c.new_start}" for c in offenders]


def test_plan_day_second_pass_is_a_noop_on_rest_day():
    # same two-pass idempotency, but with is_workday=False: the first pass
    # must build a work-free rest-day structure and the second pass must
    # neither re-create anything nor suddenly add Own work.
    events = [Event(id="w", calendar="Work", title="Sprint",
                    start=D.replace(hour=9), end=D.replace(hour=12))]
    garmin = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85,
                           body_battery_start=80, hrv_status="BALANCED")
    now = D.replace(hour=7)

    first = plan_day(DAY, events, garmin, RULES, now=now, week_gym_count=0,
                     is_workday=False)
    assert any(c.kind == "create" for c in first)  # rest day still gets structure
    assert not any(c.title == "Own work" for c in first)

    projected = _project(events, first)
    midnight_next = D + timedelta(days=1)
    day_events = [e for e in projected if e.start < midnight_next]
    next_day = [e for e in projected if e.start >= midnight_next]

    second = plan_day(DAY, day_events, garmin, RULES, now=now,
                      next_day_events=next_day, week_gym_count=0, is_workday=False)
    offenders = [c for c in second if c.kind in ("move", "create")]
    assert offenders == [], [f"{c.kind} {c.title} -> {c.new_start}" for c in offenders]
