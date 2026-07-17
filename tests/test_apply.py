import argparse
from datetime import datetime
from unittest.mock import MagicMock
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.apply import apply_changes

def _move(approval=False):
    return PlannedChange(kind="move", category="Gym", title="Workout", reason="test",
                         event_id="g1", requires_approval=approval,
                         new_start=datetime(2026, 7, 3, 17), new_end=datetime(2026, 7, 3, 18))

def test_flexible_move_applied_without_confirm():
    cal, store = MagicMock(), MagicMock()
    confirm = MagicMock(return_value=False)  # would deny if asked
    applied, errors = apply_changes([_move(approval=False)], cal, store, confirm)
    cal.move_event.assert_called_once()
    confirm.assert_not_called()
    assert len(applied) == 1
    assert errors == []
    store.log_change.assert_called_once()

def test_fixed_move_denied_by_user_not_applied():
    cal, store = MagicMock(), MagicMock()
    applied, errors = apply_changes([_move(approval=True)], cal, store, confirm=lambda c: False)
    cal.move_event.assert_not_called()
    assert applied == []
    assert errors == []
    store.log_change.assert_called_once()
    assert "[pending" in store.log_change.call_args[0][0]

def test_create_calls_calendar_create():
    cal, store = MagicMock(), MagicMock()
    ch = PlannedChange(kind="create", category="Food", title="Lunch", reason="meal window",
                       new_start=datetime(2026, 7, 3, 13), new_end=datetime(2026, 7, 3, 13, 45))
    applied, errors = apply_changes([ch], cal, store, confirm=lambda c: True)
    cal.create_event.assert_called_once_with("Food", "Lunch", ch.new_start, ch.new_end)
    assert len(applied) == 1
    assert errors == []

def test_missing_calendar_logs_error_and_continues():
    # first-run users may lack a calendar named after a category: the change
    # is skipped with a logged hint, and the remaining changes still apply
    cal, store = MagicMock(), MagicMock()
    bad = PlannedChange(kind="create", category="Learn", title="Deep work", reason="focus",
                        new_start=datetime(2026, 7, 3, 9), new_end=datetime(2026, 7, 3, 10, 30))
    good = PlannedChange(kind="create", category="Food", title="Lunch", reason="meal",
                         new_start=datetime(2026, 7, 3, 13), new_end=datetime(2026, 7, 3, 13, 45))
    def create_event(category, *a):
        if category == "Learn":
            raise KeyError("Calendar 'Learn' not found")
    cal.create_event.side_effect = create_event
    applied, errors = apply_changes([bad, good], cal, store, confirm=lambda c: True)
    assert [c.category for c in applied] == ["Food"]
    logged = [c.args for c in store.log_change.call_args_list if c.args[0].startswith("[error]")]
    assert len(logged) == 1
    assert "Learn" in logged[0][0] and "not found" in logged[0][1]
    # the caller (cli, check) must be able to see this failure too — it is
    # no longer swallowed into the storage log alone
    assert len(errors) == 1
    assert "Learn" in errors[0] and "not found" in errors[0]

def test_note_only_logged_never_written():
    cal, store = MagicMock(), MagicMock()
    ch = PlannedChange(kind="note", category="Sleep", title="Sleep window", reason="target 8h")
    applied, errors = apply_changes([ch], cal, store, confirm=lambda c: True)
    cal.move_event.assert_not_called()
    cal.create_event.assert_not_called()
    store.log_change.assert_called_once()
    assert applied == []
    assert errors == []

def _real_storage():
    from dayoptimizer import paths
    from dayoptimizer.core.storage import Storage
    paths.ensure_private_dir()
    return Storage(paths.db_path())

def test_print_pending_lists_ids_and_details(capsys):
    from dayoptimizer import cli
    storage = _real_storage()
    ch = PlannedChange(kind="move", category="Work", title="Standup", reason="conflict with Meeting",
                       event_id="w1", requires_approval=True,
                       new_start=datetime(2026, 7, 14, 9), new_end=datetime(2026, 7, 14, 9, 30))
    pid = storage.save_pending(ch)
    cli._print_pending(storage)
    out = capsys.readouterr().out
    assert "Pending approval" in out
    assert f"#{pid}" in out
    assert "[move]" in out  # kind must survive rich markup
    assert "Work: Standup" in out
    assert "2026-07-14 09:00" in out
    assert "conflict with Meeting" in out

def test_cmd_plan_survives_markup_like_event_titles(monkeypatch, capsys):
    # calendar titles are untrusted text: "[/inject]" must print literally,
    # not crash rich with a MarkupError mid-plan
    from dayoptimizer import cli, paths
    paths.ensure_private_dir()
    ch = PlannedChange(kind="move", category="Meeting", title="[/inject]", reason="conflict",
                       event_id="e1", new_start=datetime(2026, 7, 14, 9),
                       new_end=datetime(2026, 7, 14, 10))
    stub_cal = MagicMock()
    stub_cal.request_access.return_value = True
    monkeypatch.setattr(cli, "CalendarClient", MagicMock(return_value=stub_cal))
    monkeypatch.setattr(cli, "_run_plan", lambda *a, **k: ([ch], [ch], []))
    cli.cmd_plan(argparse.Namespace(date="2026-07-14", week=None), rules=MagicMock(), config={})
    out = capsys.readouterr().out
    assert "[/inject]" in out
    assert "[move]" in out  # kind tag must survive as literal text


def test_print_pending_silent_when_empty(capsys):
    from dayoptimizer import cli
    storage = _real_storage()
    cli._print_pending(storage)
    assert capsys.readouterr().out == ""

def test_confirm_without_stdin_denies_instead_of_crashing(monkeypatch):
    # bundle-invoked runs have no stdin: console.input raises EOFError there,
    # and the change must park for approval instead of crashing the plan
    from dayoptimizer import cli
    def no_stdin(*a, **k):
        raise EOFError
    monkeypatch.setattr(cli.console, "input", no_stdin)
    assert cli._confirm(_move(approval=True)) is False


def test_fixed_conflict_approval_pipeline_end_to_end(monkeypatch):
    """The full approval pipeline: a fixed-vs-fixed conflict makes plan_day
    emit a requires_approval move; apply_changes with a denying confirm parks
    it in real Storage; cmd_apply then applies it and clears pending."""
    from datetime import date
    from pathlib import Path
    from dayoptimizer import cli
    from dayoptimizer.core.models import Event
    from dayoptimizer.core.planner import plan_day
    from dayoptimizer.core.rules import load_rules

    rules = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
    day = datetime(2026, 7, 3, 0, 0).astimezone()
    work = Event(id="w", calendar="Work", title="Deep review",
                 start=day.replace(hour=9), end=day.replace(hour=12))
    meeting = Event(id="m", calendar="Meeting", title="Standup",
                    start=day.replace(hour=11), end=day.replace(hour=12))
    changes = plan_day(date(2026, 7, 3), [work, meeting], None, rules,
                       now=day.replace(hour=7))
    proposals = [c for c in changes if c.kind == "move" and c.requires_approval]
    assert len(proposals) == 1
    prop = proposals[0]
    assert "approval required" in prop.reason

    storage = _real_storage()
    cal = MagicMock()
    apply_changes(changes, cal, storage, confirm=lambda c: False)  # returns (applied, errors)
    moved_ids = {call.args[0] for call in cal.move_event.call_args_list}
    assert prop.event_id not in moved_ids  # fixed event untouched without consent
    pending = storage.get_pending()
    assert len(pending) == 1
    pid, saved = pending[0]
    assert saved == prop
    storage.close()

    # the user approves: cmd_apply writes it to the calendar and clears pending
    stub_cal = MagicMock()
    stub_cal.request_access.return_value = True
    monkeypatch.setattr(cli, "CalendarClient", MagicMock(return_value=stub_cal))
    cli.cmd_apply(argparse.Namespace(ids=str(pid)), rules=rules, config={})
    stub_cal.move_event.assert_called_once_with(prop.event_id, prop.new_start, prop.new_end)
    storage = _real_storage()
    assert storage.get_pending() == []
    storage.close()


def test_cmd_apply_missing_calendar_logs_error_and_applies_the_rest(monkeypatch, capsys):
    # approving pending ids must not die on a missing category calendar: the
    # failing row is logged with a hint and the other ids still apply
    from dayoptimizer import cli
    storage = _real_storage()
    ok = PlannedChange(kind="move", category="Meeting", title="Standup", reason="r",
                       event_id="e1", requires_approval=True,
                       new_start=datetime(2026, 7, 14, 9), new_end=datetime(2026, 7, 14, 10))
    bad = PlannedChange(kind="create", category="Learn", title="Deep work", reason="r",
                        requires_approval=True,
                        new_start=datetime(2026, 7, 14, 11), new_end=datetime(2026, 7, 14, 12))
    pid_ok, pid_bad = storage.save_pending(ok), storage.save_pending(bad)
    storage.close()
    stub_cal = MagicMock()
    stub_cal.request_access.return_value = True
    stub_cal.create_event.side_effect = KeyError("Calendar 'Learn' not found")
    monkeypatch.setattr(cli, "CalendarClient", MagicMock(return_value=stub_cal))
    cli.cmd_apply(argparse.Namespace(ids=f"{pid_ok},{pid_bad}"), rules=MagicMock(), config={})
    stub_cal.move_event.assert_called_once_with(ok.event_id, ok.new_start, ok.new_end)
    out = capsys.readouterr().out
    # the failure must be visible to the user immediately, not just logged
    # silently to storage — this is the whole point of the fix
    assert f"#{pid_bad} failed: calendar 'Learn' not found" in out
    assert "Applied 1 of 2" in out
    storage = _real_storage()
    # the failed row is removed too: it cannot succeed until the user creates
    # the calendar, and a later replan regenerates the proposal
    assert storage.get_pending() == []
    logs = storage.recent_changes()
    assert any(desc.startswith("[error]") and "not found" in reason
               for _, desc, reason in logs)
    storage.close()


def test_cmd_plan_prints_pending_after_planning(monkeypatch, capsys):
    from dayoptimizer import cli
    storage = _real_storage()
    ch = PlannedChange(kind="move", category="Important", title="Dentist", reason="fixed conflict",
                       event_id="i1", requires_approval=True,
                       new_start=datetime(2026, 7, 14, 11), new_end=datetime(2026, 7, 14, 12))
    pid = storage.save_pending(ch)
    storage.close()
    stub_cal = MagicMock()
    stub_cal.request_access.return_value = True
    monkeypatch.setattr(cli, "CalendarClient", MagicMock(return_value=stub_cal))
    monkeypatch.setattr(cli, "_run_plan", lambda *a, **k: ([], [], []))
    cli.cmd_plan(argparse.Namespace(date="2026-07-14", week=None), rules=MagicMock(), config={})
    out = capsys.readouterr().out
    assert "Pending approval" in out
    assert f"#{pid}" in out


def test_cmd_plan_prints_aggregated_write_errors(monkeypatch, capsys):
    # this is the core fix: a first-run user whose calendars don't match the
    # planner's categories must SEE that blocks were skipped, not just have
    # them silently vanish into the SQLite change log
    from dayoptimizer import cli, paths
    paths.ensure_private_dir()
    stub_cal = MagicMock()
    stub_cal.request_access.return_value = True
    monkeypatch.setattr(cli, "CalendarClient", MagicMock(return_value=stub_cal))
    errors = [
        "calendar 'Food' not found — create or rename a calendar with this name in the Calendar app",
        "calendar 'Gym' not found — create or rename a calendar with this name in the Calendar app",
        "calendar 'Food' not found — create or rename a calendar with this name in the Calendar app",
    ]
    monkeypatch.setattr(cli, "_run_plan", lambda *a, **k: ([], [], errors))
    cli.cmd_plan(argparse.Namespace(date="2026-07-14", week=None), rules=MagicMock(), config={})
    out = capsys.readouterr().out
    assert "3 block(s) could not be written:" in out
    # deduped and aggregated into one line naming both missing calendars
    assert "Missing calendars: Food, Gym" in out
    assert out.count("calendar 'Food' not found") == 0  # raw message not repeated per-line
