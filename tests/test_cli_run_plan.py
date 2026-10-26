"""_run_plan must treat all-day events as calendar markers, never as busy
time or scheduling anchors. Regression: a multi-week all-day event (e.g. a
vacation marker) previously made suggest_sleep anchor on 00:00 (a bogus late
night/early morning "Sleep" block) and free_slots see zero free time for the
whole day ("day overloaded")."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from dayoptimizer import cli, paths
from dayoptimizer.core.models import Event
from dayoptimizer.core.planner import plan_day as real_plan_day
from dayoptimizer.core.rules import load_rules
from dayoptimizer.core.storage import Storage

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")


def _weekday_on_or_after(base: date, weekday: int) -> date:
    return base + timedelta(days=(weekday - base.weekday()) % 7)


def _spy_plan_day(monkeypatch, captured: dict):
    def spy(*args, **kwargs):
        captured["is_workday"] = kwargs.get("is_workday", True)
        return real_plan_day(*args, **kwargs)
    monkeypatch.setattr(cli, "plan_day", spy)


def test_run_plan_filters_all_day_events_from_planner_inputs():
    paths.ensure_private_dir()
    day = date.today() + timedelta(days=3)
    day_start = datetime.combine(day, time(0)).astimezone()
    marker = Event(id="vac1", calendar="Work", title="Vacation",
                   start=day_start, end=day_start + timedelta(hours=23, minutes=59),
                   all_day=True)

    def list_events(start, end):
        if start == day_start and end == day_start + timedelta(days=1):
            return [marker]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())

    changes, applied, errors = cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    overloaded = [c for c in changes
                  if c.category == "Free time" and "overloaded" in c.reason]
    assert overloaded == []
    creates = [c for c in changes if c.kind == "create"]
    assert any(c.category == "Food" for c in creates)

    cached = storage.events_on(day.isoformat())
    assert any(e.id == "vac1" and e.all_day for e in cached)
    storage.close()


def test_run_plan_all_day_event_never_anchors_sleep_via_tomorrow_fixed():
    paths.ensure_private_dir()
    day = date.today() + timedelta(days=3)
    day_start = datetime.combine(day, time(0)).astimezone()
    tomorrow_start = day_start + timedelta(days=1)
    marker = Event(id="vac1", calendar="Work", title="Vacation",
                   start=tomorrow_start, end=tomorrow_start + timedelta(days=40),
                   all_day=True)

    def list_events(start, end):
        if start == tomorrow_start and end == tomorrow_start + timedelta(days=1):
            return [marker]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())

    changes, applied, errors = cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    sleep_notes = [c for c in changes if c.category == "Sleep"]
    assert sleep_notes
    sleep = sleep_notes[0]
    assert sleep.new_end.date() == day + timedelta(days=1)
    assert sleep.new_end.time() >= time(5, 0)
    storage.close()


def test_run_plan_saturday_is_not_a_workday(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 5)
    calendar = MagicMock()
    calendar.list_events.side_effect = lambda start, end: []
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is False
    storage.close()


def test_run_plan_weekday_with_default_work_days_is_a_workday(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 2)
    calendar = MagicMock()
    calendar.list_events.side_effect = lambda start, end: []
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is True
    storage.close()


def test_run_plan_holiday_all_day_event_end_at_next_midnight_is_not_a_workday(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 2)
    day_start = datetime.combine(day, time(0)).astimezone()
    holiday = Event(id="h1", calendar="Public Holidays", title="Some Holiday",
                    start=day_start, end=day_start + timedelta(days=1), all_day=True)

    def list_events(start, end):
        if start == day_start and end == day_start + timedelta(days=1):
            return [holiday]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is False
    storage.close()


def test_run_plan_holiday_all_day_event_end_at_2359_is_not_a_workday(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 3)
    day_start = datetime.combine(day, time(0)).astimezone()
    holiday = Event(id="h2", calendar="Holidays", title="Another Holiday",
                    start=day_start, end=day_start + timedelta(hours=23, minutes=59),
                    all_day=True)

    def list_events(start, end):
        if start == day_start and end == day_start + timedelta(days=1):
            return [holiday]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is False
    storage.close()


def test_run_plan_non_holiday_calendar_all_day_event_is_still_a_workday(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 4)
    day_start = datetime.combine(day, time(0)).astimezone()
    vacation = Event(id="v1", calendar="Work", title="Vacation",
                     start=day_start, end=day_start + timedelta(days=1), all_day=True)

    def list_events(start, end):
        if start == day_start and end == day_start + timedelta(days=1):
            return [vacation]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is True
    storage.close()


def test_run_plan_holiday_next_day_not_falsely_flagged(monkeypatch):
    paths.ensure_private_dir()
    day = _weekday_on_or_after(date.today() + timedelta(days=3), 2)
    next_day = day + timedelta(days=1)
    day_start = datetime.combine(day, time(0)).astimezone()
    next_day_start = day_start + timedelta(days=1)
    holiday = Event(id="h3", calendar="Public Holidays", title="Some Holiday",
                    start=day_start, end=next_day_start, all_day=True)

    def list_events(start, end):
        if start == next_day_start and end == next_day_start + timedelta(days=1):
            return [holiday]
        return []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    cli._run_plan(next_day, calendar, storage, RULES, confirm=lambda c: False)

    assert captured["is_workday"] is True
    storage.close()


def test_run_plan_multi_day_holiday_span_covers_all_days_but_not_the_end(monkeypatch):
    paths.ensure_private_dir()
    span_start = datetime.combine(date(2029, 1, 1), time(0)).astimezone()
    span_end = span_start + timedelta(days=3)
    holiday = Event(id="h4", calendar="Public Holidays", title="Long Holiday",
                    start=span_start, end=span_end, all_day=True)

    def list_events(start, end):
        return [holiday] if start < span_end and end > span_start else []

    calendar = MagicMock()
    calendar.list_events.side_effect = list_events
    storage = Storage(paths.db_path())
    captured: dict = {}
    _spy_plan_day(monkeypatch, captured)

    expected = {date(2029, 1, 1): False, date(2029, 1, 2): False,
                date(2029, 1, 3): False, date(2029, 1, 4): True}
    for day, want in expected.items():
        cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: False)
        assert captured["is_workday"] is want, f"{day} expected is_workday={want}"
    storage.close()
