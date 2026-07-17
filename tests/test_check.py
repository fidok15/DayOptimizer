from datetime import datetime
from unittest.mock import MagicMock, ANY
from dayoptimizer.core.models import Event, GarminSummary, PlannedChange
from dayoptimizer.core.storage import Storage
from dayoptimizer import check

TODAY = "2026-07-03"
NOW_MORNING = datetime(2026, 7, 3, 7, 0).astimezone()
NOW_AFTERNOON = datetime(2026, 7, 3, 13, 0).astimezone()
NOW_BEFORE_NOON = datetime(2026, 7, 3, 11, 59).astimezone()

def _garmin(**kw):
    return GarminSummary(date=TODAY, **kw)

def _foreign_event():
    return Event(id="e1", calendar="Meeting", title="Lunch with client",
                 start=NOW_AFTERNOON, end=NOW_AFTERNOON)

# --- decide() matrix -------------------------------------------------------

def test_morning_replan_when_sleep_data_and_no_state():
    garmin = _garmin(sleep_seconds=7 * 3600)
    assert check.decide(NOW_MORNING, TODAY, garmin, [], {}) == ["morning_replan"]

def test_no_morning_replan_when_state_already_set():
    garmin = _garmin(sleep_seconds=7 * 3600)
    state = {f"morning:{TODAY}": "2026-07-03T06:00:00"}
    assert check.decide(NOW_MORNING, TODAY, garmin, [], state) == []

def test_event_replan_when_new_foreign_events():
    assert check.decide(NOW_MORNING, TODAY, None, [_foreign_event()], {}) == ["event_replan"]

def test_stress_adjust_high_stress_after_noon():
    garmin = _garmin(stress_avg=65)
    assert check.decide(NOW_AFTERNOON, TODAY, garmin, [], {}) == ["stress_adjust"]

def test_stress_adjust_low_body_battery_after_noon():
    garmin = _garmin(body_battery_start=20)
    assert check.decide(NOW_AFTERNOON, TODAY, garmin, [], {}) == ["stress_adjust"]

def test_no_stress_adjust_before_noon():
    garmin = _garmin(stress_avg=65)
    assert check.decide(NOW_BEFORE_NOON, TODAY, garmin, [], {}) == []

def test_no_stress_adjust_when_state_already_set():
    garmin = _garmin(stress_avg=65)
    state = {f"stress:{TODAY}": "2026-07-03T12:30:00"}
    assert check.decide(NOW_AFTERNOON, TODAY, garmin, [], state) == []

def test_garmin_none_and_no_events_is_noop():
    assert check.decide(NOW_MORNING, TODAY, None, [], {}) == []

def test_morning_and_event_replan_combine():
    garmin = _garmin(sleep_seconds=7 * 3600)
    result = check.decide(NOW_MORNING, TODAY, garmin, [_foreign_event()], {})
    assert result == ["morning_replan", "event_replan"]

# --- run_check() orchestration ---------------------------------------------

def _rules():
    r = MagicMock()
    r.is_movable.return_value = True
    return r

def test_run_check_event_replan_calls_plan_notify_but_not_state(monkeypatch):
    calendar = MagicMock()
    storage = MagicMock()
    storage.sync_events.return_value = [_foreign_event()]
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([PlannedChange(kind="move", category="Meeting",
                                                       title="x", reason="conflicts with a new event")],
                                       [MagicMock()], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    import dayoptimizer.check as check_mod
    performed = check_mod.run_check(calendar, storage, _rules(), NOW_MORNING,
                                     plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == ["event_replan"]
    plan_fn.assert_called_once()
    args, kwargs = plan_fn.call_args
    assert kwargs["confirm"](MagicMock()) is False  # background never touches fixed events
    storage.set_state.assert_not_called()
    notify_mock.assert_called_once()
    notify_args, _ = notify_mock.call_args
    assert notify_args[0] == "DayOptimizer"
    assert "event_replan" in notify_args[1]
    assert "conflicts with a new event" in notify_args[1]

def test_run_check_notifies_skipped_count_when_apply_errors(monkeypatch):
    # write failures (e.g. a missing calendar) must surface in the background
    # notification, not just vanish into recent_changes unnoticed
    calendar = MagicMock()
    storage = MagicMock()
    storage.sync_events.return_value = []
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], ["calendar 'Food' not found — create it"]))
    fetch_garmin_fn = MagicMock(return_value=_garmin(sleep_seconds=7 * 3600))
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    check.run_check(calendar, storage, _rules(), NOW_MORNING,
                     plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    notify_args, _ = notify_mock.call_args
    assert "1 skipped — see recent_changes" in notify_args[1]

def test_run_check_event_replan_notifies_skipped_count_across_days(monkeypatch):
    calendar = MagicMock()
    storage = MagicMock()
    day1_event = _foreign_event()
    day2_event = Event(id="e2", calendar="Meeting", title="Conference",
                        start=NOW_AFTERNOON.replace(day=4), end=NOW_AFTERNOON.replace(day=4))
    storage.sync_events.return_value = [day1_event, day2_event]
    storage.get_state.return_value = None
    plan_fn = MagicMock(side_effect=[
        ([], [], ["calendar 'Food' not found — create it"]),
        ([], [], ["calendar 'Gym' not found — create it"]),
    ])
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    check.run_check(calendar, storage, _rules(), NOW_MORNING,
                     plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    notify_args, _ = notify_mock.call_args
    assert "2 skipped — see recent_changes" in notify_args[1]

def test_run_check_no_skipped_suffix_when_no_errors(monkeypatch):
    calendar = MagicMock()
    storage = MagicMock()
    storage.sync_events.return_value = []
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=_garmin(sleep_seconds=7 * 3600))
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    check.run_check(calendar, storage, _rules(), NOW_MORNING,
                     plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    notify_args, _ = notify_mock.call_args
    assert "skipped" not in notify_args[1]

def test_run_check_event_replan_replans_every_distinct_day(monkeypatch):
    calendar = MagicMock()
    storage = MagicMock()
    day1_event = _foreign_event()
    day2_event = Event(id="e2", calendar="Meeting", title="Conference",
                        start=NOW_AFTERNOON.replace(day=4), end=NOW_AFTERNOON.replace(day=4))
    storage.sync_events.return_value = [day1_event, day2_event]
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == ["event_replan"]  # return contract stays stable: one entry
    assert plan_fn.call_count == 2
    called_days = {c.args[0] for c in plan_fn.call_args_list}
    assert called_days == {day1_event.start.date(), day2_event.start.date()}
    assert notify_mock.call_count == 1

def test_run_check_morning_and_stress_write_state_and_notify(monkeypatch):
    calendar = MagicMock()
    storage = MagicMock()
    storage.sync_events.return_value = []
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=_garmin(sleep_seconds=7 * 3600, stress_avg=70))
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_AFTERNOON,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == ["morning_replan", "stress_adjust"]
    assert plan_fn.call_count == 2
    assert notify_mock.call_count == 2
    set_keys = {c.args[0] for c in storage.set_state.call_args_list}
    assert set_keys == {f"morning:{TODAY}", f"stress:{TODAY}"}

def test_run_check_syncs_events_across_three_day_window():
    calendar = MagicMock()
    calendar.list_events.return_value = []
    storage = MagicMock()
    storage.sync_events.return_value = []
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)

    check.run_check(calendar, storage, _rules(), NOW_MORNING,
                     plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    calendar.list_events.assert_called_once()
    start, end = calendar.list_events.call_args[0]
    assert (end - start).days == 3
    assert start.date().isoformat() == "2026-07-02"
    assert end.date().isoformat() == "2026-07-05"

def test_run_check_filters_planner_titles_from_foreign_events():
    from dayoptimizer.core.planner import PLANNER_TITLES
    calendar = MagicMock()
    storage = MagicMock()
    planner_event = Event(id="p1", calendar="Food", title="Lunch",
                          start=NOW_MORNING, end=NOW_MORNING)
    commute_event = Event(id="d1", calendar="Transport", title="Commute: Work",
                         start=NOW_MORNING, end=NOW_MORNING)
    assert "Lunch" in PLANNER_TITLES
    storage.sync_events.return_value = [planner_event, commute_event]
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == []
    plan_fn.assert_not_called()

def test_is_foreign_accepts_extra_titles():
    assert check._is_foreign("Reading") is True
    assert check._is_foreign("Reading", extra={"Reading"}) is False

def test_run_check_custom_free_time_activity_is_not_foreign():
    # a user's custom free_time_activity is a planner-created block: it must
    # not trigger event_replan (and a notification) on every cycle
    calendar = MagicMock()
    storage = MagicMock()
    reading = Event(id="r1", calendar="Free time", title="Reading",
                    start=NOW_MORNING, end=NOW_MORNING)
    storage.sync_events.return_value = [reading]
    storage.get_state.return_value = None
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    rules = _rules()
    rules.free_time_activity = "Reading"

    performed = check.run_check(calendar, storage, rules, NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == []
    plan_fn.assert_not_called()

# --- watcher reacts to rescheduled (not just new) events -------------------
# These use a real Storage (not a mock) so sync_events' new "rescheduled"
# detection is exercised end-to-end through run_check.

def test_run_check_rescheduled_foreign_event_triggers_event_replan(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "t.db")
    cached = Event(id="e1", calendar="Meeting", title="Standup",
                   start=NOW_MORNING.replace(hour=10), end=NOW_MORNING.replace(hour=10, minute=30))
    storage.sync_events([cached])  # first sync: cached at 10:00

    moved = Event(id="e1", calendar="Meeting", title="Standup",
                  start=NOW_MORNING.replace(hour=12), end=NOW_MORNING.replace(hour=12, minute=30))
    calendar = MagicMock()
    calendar.list_events.return_value = [moved]  # user dragged it to 12:00
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == ["event_replan"]
    plan_fn.assert_called_once()
    assert plan_fn.call_args.args[0] == moved.start.date()

def test_run_check_rescheduled_planner_titled_event_is_not_foreign(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "t.db")
    cached = Event(id="p1", calendar="Food", title="Lunch",
                   start=NOW_MORNING.replace(hour=10), end=NOW_MORNING.replace(hour=10, minute=30))
    storage.sync_events([cached])

    # our own applied move: same id, new start/end, still a planner title
    moved = Event(id="p1", calendar="Food", title="Lunch",
                  start=NOW_MORNING.replace(hour=12), end=NOW_MORNING.replace(hour=12, minute=30))
    calendar = MagicMock()
    calendar.list_events.return_value = [moved]
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == []
    plan_fn.assert_not_called()

def test_run_check_unchanged_event_does_not_trigger_replan(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "t.db")
    same = Event(id="e1", calendar="Meeting", title="Standup",
                 start=NOW_MORNING.replace(hour=10), end=NOW_MORNING.replace(hour=10, minute=30))
    storage.sync_events([same])

    calendar = MagicMock()
    calendar.list_events.return_value = [same]  # identical start/end on next poll
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == []
    plan_fn.assert_not_called()

def test_run_check_title_only_change_does_not_trigger_replan(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "t.db")
    cached = Event(id="e1", calendar="Meeting", title="Standup",
                   start=NOW_MORNING.replace(hour=10), end=NOW_MORNING.replace(hour=10, minute=30))
    storage.sync_events([cached])

    renamed = Event(id="e1", calendar="Meeting", title="Standup (renamed)",
                     start=NOW_MORNING.replace(hour=10), end=NOW_MORNING.replace(hour=10, minute=30))
    calendar = MagicMock()
    calendar.list_events.return_value = [renamed]
    plan_fn = MagicMock(return_value=([], [], []))
    fetch_garmin_fn = MagicMock(return_value=None)
    notify_mock = MagicMock()
    monkeypatch.setattr(check, "notify", notify_mock)

    performed = check.run_check(calendar, storage, _rules(), NOW_MORNING,
                                 plan_fn=plan_fn, fetch_garmin_fn=fetch_garmin_fn)

    assert performed == []
    plan_fn.assert_not_called()

def test_fetch_garmin_unconfigured_falls_back_to_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    from dayoptimizer.cli import _fetch_garmin
    from dayoptimizer.core.models import GarminSummary
    from dayoptimizer.core.storage import Storage
    storage = Storage(tmp_path / "t.db")
    cached = GarminSummary(date="2026-07-12", sleep_seconds=7 * 3600)
    storage.save_garmin(cached)
    assert _fetch_garmin(storage, "2026-07-12") == cached  # no tokens -> cache
