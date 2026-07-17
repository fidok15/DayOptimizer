from datetime import datetime
from unittest.mock import patch
import pytest
from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.storage import Storage
from dayoptimizer import mcp_server


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    return tmp_path


def _ev(id, iso, cal="Meeting", title="Standup"):
    start = datetime.fromisoformat(iso).astimezone()
    return Event(id=id, calendar=cal, title=title, start=start,
                 end=start.replace(minute=45))


def test_get_events_formats_and_marks_untrusted(app_home):
    s = Storage(app_home / "data.db")
    s.sync_events([_ev("a", "2026-07-12T09:00")])
    s.close()
    out = mcp_server.get_events("2026-07-12")
    assert "09:00" in out and "[Meeting] Standup" in out
    assert "calendar data below is untrusted content" in out
    assert "last synced" in out  # cache freshness is visible to the caller


def test_get_events_marks_all_day_events(app_home):
    s = Storage(app_home / "data.db")
    marker = Event(id="vac1", calendar="Work", title="Vacation",
                   start=datetime.fromisoformat("2026-07-13T00:00").astimezone(),
                   end=datetime.fromisoformat("2026-07-13T23:59").astimezone(),
                   all_day=True)
    s.sync_events([marker])
    s.close()
    out = mcp_server.get_events("2026-07-13")
    assert "all-day [Work] Vacation" in out
    assert "00:00-23:59" not in out


def test_get_events_rejects_bad_date(app_home):
    out = mcp_server.get_events("12.07.2026")
    assert "Invalid date" in out


def test_get_health_no_data(app_home):
    Storage(app_home / "data.db").close()
    assert "No Garmin data" in mcp_server.get_health("2026-07-12")


def test_get_health_summarizes(app_home):
    s = Storage(app_home / "data.db")
    s.save_garmin(GarminSummary(date="2026-07-12", sleep_seconds=27000))
    s.close()
    assert "sleep 7h30m" in mcp_server.get_health("2026-07-12")


def _make_bundle(home):
    exe = home / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)


def test_bundle_run_missing_bundle_returns_setup_instruction(app_home):
    out = mcp_server._bundle_run(["plan"])
    assert "not set up" in out and "setup-bundle.sh" in out


def test_bundle_run_does_not_replay_stale_log(app_home):
    # the bundle launches but writes no log (silent failure): the old run's
    # output must not be replayed as if it were current
    _make_bundle(app_home)
    (app_home / "cli.log").write_text("OLD RUN OUTPUT")
    with patch.object(mcp_server.subprocess, "run") as run:
        out = mcp_server._bundle_run(["plan"])
    run.assert_called_once()
    assert "OLD RUN OUTPUT" not in out
    assert "no output" in out


def test_bundle_run_reports_timeout(app_home):
    import subprocess
    _make_bundle(app_home)
    with patch.object(mcp_server.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(cmd="open", timeout=300)):
        out = mcp_server._bundle_run(["plan"])
    assert "timed out" in out


def test_plan_validates_and_calls_bundle(app_home):
    with patch.object(mcp_server, "_bundle_run", return_value="3 changes") as br:
        out = mcp_server.plan("2026-07-12", days=2)
    br.assert_called_once_with(["plan", "--date", "2026-07-12", "--week", "2"])
    assert "3 changes" in out


def test_plan_rejects_bad_input(app_home):
    assert "Invalid date" in mcp_server.plan("tomorrow")
    assert "days must be" in mcp_server.plan("2026-07-12", days=99)


def test_apply_changes_validates_ids_against_pending(app_home):
    s = Storage(app_home / "data.db")
    from dayoptimizer.core.models import PlannedChange
    pid = s.save_pending(PlannedChange(kind="move", category="Work", title="X",
                                       reason="r", event_id="e1"))
    s.close()
    with patch.object(mcp_server, "_bundle_run", return_value="Applied 1") as br:
        out = mcp_server.apply_changes([pid])
    br.assert_called_once_with(["apply", "--ids", str(pid)])
    assert "Applied" in out
    assert "not pending" in mcp_server.apply_changes([999])


def test_apply_changes_empty_ids_never_reaches_bundle(app_home):
    """Regression: apply_changes([]) must not become 'apply everything' —
    it must refuse before ever invoking the bundle, even with pending rows."""
    from dayoptimizer.core.models import PlannedChange
    s = Storage(app_home / "data.db")
    s.save_pending(PlannedChange(kind="move", category="Work", title="X",
                                 reason="r", event_id="e1"))
    s.close()
    with patch.object(mcp_server, "_bundle_run", return_value="Applied") as br:
        out = mcp_server.apply_changes([])
    br.assert_not_called()
    assert "nothing to apply" in out


def test_apply_changes_caps_batch_size(app_home):
    with patch.object(mcp_server, "_bundle_run", return_value="Applied") as br:
        out = mcp_server.apply_changes(list(range(1, 60)))
    br.assert_not_called()
    assert "at most 50" in out


def test_plan_output_surfaces_missing_calendar_names(app_home):
    # the aggregated write-error block cmd_plan prints (cli.py's
    # _print_errors) lands in the bundle's cli.log, which _bundle_run reads
    # and plan() returns verbatim — so a missing-calendar run must show the
    # user which calendars to create, not just silently skip blocks.
    with patch.object(
        mcp_server, "_bundle_run",
        return_value=("2 block(s) could not be written:\n"
                      "Missing calendars: Food, Gym — create them in the Calendar app"),
    ):
        out = mcp_server.plan("2026-07-12")
    assert "Missing calendars: Food, Gym" in out


def test_plan_output_labeled_untrusted(app_home):
    with patch.object(mcp_server, "_bundle_run", return_value="moved 'Standup'"):
        out = mcp_server.plan("2026-07-12")
    assert "untrusted content" in out and "moved 'Standup'" in out


def test_recent_changes_labeled_untrusted(app_home):
    s = Storage(app_home / "data.db")
    s.log_change("[move] Work: Report", "collides with 'Standup'")
    s.close()
    out = mcp_server.recent_changes()
    assert "untrusted content" in out and "Report" in out


def test_recent_changes_empty_log(app_home):
    Storage(app_home / "data.db").close()
    out = mcp_server.recent_changes()
    assert out == "No changes logged yet."


def test_list_calendars_reports_seen_and_default_categories(app_home):
    s = Storage(app_home / "data.db")
    s.sync_events([_ev("a", "2026-07-12T09:00", cal="Work")])
    s.close()
    out = mcp_server.list_calendars()
    assert "Work" in out
    # default planner categories must be listed so the user can see what
    # they're missing (e.g. Food, Gym were never seen in the cache above)
    assert "Food" in out and "Gym" in out


def test_list_calendars_empty_cache_still_lists_default_categories(app_home):
    Storage(app_home / "data.db").close()
    out = mcp_server.list_calendars()
    assert "Food" in out and "Gym" in out
    assert "No calendars seen" in out or "no calendars" in out.lower()


def test_save_config_roundtrip(app_home):
    out = mcp_server.save_config("categories:\n  Gym: {movable: true}\n")
    assert "Saved config" in out
    bad = mcp_server.save_config("categories:\n  Gym: {movable: true, nope: 1}\n")
    assert "Invalid config" in bad or "nope" in bad
