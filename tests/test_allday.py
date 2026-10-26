"""All-day events with a time in the title ("Dentist 14:00"): the planner plans
around that time and proposes, with approval, to make the event timed."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from dayoptimizer import cli, paths
from dayoptimizer.core.allday import time_in_title
from dayoptimizer.core.calendar import CalendarClient
from dayoptimizer.core.models import Event
from dayoptimizer.core.rules import load_rules
from dayoptimizer.core.storage import Storage

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")


def test_time_in_title_guesses_and_flags_doubt():
    assert (time_in_title("Dentysta 14:00").start, time_in_title("Dentysta 14:00").sure) == (time(14), True)
    assert time_in_title("Meeting 14-15:30").end == time(15, 30)
    assert time_in_title("Exam 12.10").sure is False
    assert time_in_title("Room 14").sure is False
    assert time_in_title("Holiday") is None


def _plan(title):
    paths.ensure_private_dir()
    day = date.today() + timedelta(days=3)
    day_start = datetime.combine(day, time(0)).astimezone()
    marker = Event(id="dent", calendar="Work", title=title, start=day_start,
                   end=day_start + timedelta(days=1), all_day=True)
    calendar = MagicMock()
    calendar.list_events.side_effect = lambda s, e: [marker] if s == day_start and e == day_start + timedelta(days=1) else []
    storage = Storage(paths.db_path())
    asked = []
    changes, applied, _ = cli._run_plan(day, calendar, storage, RULES, confirm=lambda c: asked.append(c) or False)
    storage.close()
    return day_start, changes, asked, calendar


def test_run_plan_plans_around_and_asks_to_make_it_timed():
    day_start, changes, asked, calendar = _plan("Dentist 14:00")
    mine = [c for c in changes if c.event_id == "dent"]
    assert len(mine) == 1 and mine[0].kind == "move" and mine[0].requires_approval
    assert (mine[0].new_start, mine[0].new_end) == (day_start + timedelta(hours=14), day_start + timedelta(hours=15))
    assert "make it a 14:00–15:00 event" in mine[0].reason and asked == mine
    calendar.move_event.assert_not_called()
    busy = (day_start + timedelta(hours=14), day_start + timedelta(hours=15))
    assert not [c for c in changes if c.kind == "create" and c.new_start < busy[1] and c.new_end > busy[0]]


def test_run_plan_says_when_the_title_is_only_a_guess():
    _, changes, _, _ = _plan("Exam 12.10")
    assert "that's a guess" in next(c for c in changes if c.event_id == "dent").reason


def test_move_event_makes_an_all_day_event_timed():
    ev = MagicMock()
    ev.isAllDay.return_value = True
    store = SimpleNamespace(eventWithIdentifier_=lambda i: ev, saveEvent_span_error_=lambda e, s, x: (True, None))
    client = CalendarClient.__new__(CalendarClient)
    client._store = store
    client._nsdate = lambda dt: dt
    start = datetime(2026, 10, 7, 14).astimezone()
    client.move_event("dent", start, start + timedelta(hours=1))
    ev.setAllDay_.assert_called_once_with(False)
    ev.setStartDate_.assert_called_once_with(start)
