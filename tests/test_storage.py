import json
from datetime import UTC, datetime

from dayoptimizer.core.models import Event, GarminSummary, PlannedChange
from dayoptimizer.core.storage import Storage


def _event(eid: str) -> Event:
    return Event(id=eid, calendar="Gym", title="Workout",
                 start=datetime(2026, 7, 3, 17, tzinfo=UTC),
                 end=datetime(2026, 7, 3, 18, tzinfo=UTC))

def test_garmin_roundtrip(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.save_garmin(GarminSummary(date="2026-07-03", sleep_seconds=25000, sleep_score=71))
    got = s.get_garmin("2026-07-03")
    assert got is not None and got.sleep_score == 71
    assert s.get_garmin("2000-01-01") is None

def test_garmin_upsert_and_history(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.save_garmin(GarminSummary(date="2026-07-02", sleep_score=50))
    s.save_garmin(GarminSummary(date="2026-07-03", sleep_score=80))
    s.save_garmin(GarminSummary(date="2026-07-03", sleep_score=81))
    hist = s.garmin_history(days=7)
    assert [g.date for g in hist] == ["2026-07-03", "2026-07-02"]
    assert hist[0].sleep_score == 81

def test_sync_events_returns_only_new(tmp_path):
    s = Storage(tmp_path / "t.db")
    new = s.sync_events([_event("a"), _event("b")])
    assert {e.id for e in new} == {"a", "b"}
    new = s.sync_events([_event("a"), _event("b"), _event("c")])
    assert {e.id for e in new} == {"c"}

def test_sync_events_returns_rescheduled_existing_event(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T10:00")])
    moved = _ev("a", "2026-07-12T12:00")
    changed = s.sync_events([moved])
    assert {e.id for e in changed} == {"a"}

def test_sync_events_does_not_flag_unchanged_events(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T10:00")])
    changed = s.sync_events([_ev("a", "2026-07-12T10:00")])
    assert changed == []

def test_sync_events_title_only_change_is_not_rescheduled(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T10:00")])
    renamed = _ev("a", "2026-07-12T10:00")
    renamed.title = "Renamed Standup"
    changed = s.sync_events([renamed])
    assert changed == []

def test_change_log(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.log_change("Moved Gym to 17:00", "low Body Battery")
    rows = s.recent_changes()
    assert len(rows) == 1 and "Gym" in rows[0][1]

def test_state_roundtrip_and_default(tmp_path):
    s = Storage(tmp_path / "t.db")
    assert s.get_state("x") is None
    assert s.get_state("x", "missing") == "missing"
    s.set_state("x", "1")
    s.set_state("x", "2")
    assert s.get_state("x") == "2"

def _ev(id, day_hour):
    start = datetime.fromisoformat(day_hour).astimezone()
    return Event(id=id, calendar="Meeting", title="Standup",
                 start=start, end=start.replace(minute=30))

def test_events_on_filters_and_sorts(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("b", "2026-07-12T14:00"), _ev("a", "2026-07-12T09:00"),
                   _ev("c", "2026-07-13T09:00")])
    todays = s.events_on("2026-07-12")
    assert [e.id for e in todays] == ["a", "b"]

def test_sync_events_prunes_cancelled_events_inside_window(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T09:00"), _ev("b", "2026-07-12T14:00"),
                   _ev("c", "2026-07-13T09:00")])
    ws = datetime.fromisoformat("2026-07-12T00:00").astimezone()
    we = datetime.fromisoformat("2026-07-13T00:00").astimezone()
    s.sync_events([_ev("a", "2026-07-12T09:00")], window_start=ws, window_end=we)
    assert [e.id for e in s.events_on("2026-07-12")] == ["a"]
    assert [e.id for e in s.events_on("2026-07-13")] == ["c"]

def test_sync_events_without_window_never_prunes(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T09:00")])
    s.sync_events([])
    assert [e.id for e in s.events_on("2026-07-12")] == ["a"]

def test_events_on_tolerates_cached_rows_missing_all_day_key(tmp_path):
    s = Storage(tmp_path / "t.db")
    start = datetime.fromisoformat("2026-07-12T09:00").astimezone()
    payload = {"id": "old1", "calendar": "Meeting", "title": "Standup",
               "start": start.isoformat(), "end": start.replace(minute=30).isoformat(),
               "location": None}
    s._conn.execute(
        "INSERT INTO events_cache(id, data, last_seen) VALUES(?, ?, ?)",
        ("old1", json.dumps(payload), start.isoformat()))
    s._conn.commit()
    todays = s.events_on("2026-07-12")
    assert len(todays) == 1
    assert todays[0].all_day is False

def test_known_calendars_returns_sorted_distinct_names(tmp_path):
    s = Storage(tmp_path / "t.db")
    work1 = Event(id="a", calendar="Work", title="Standup",
                 start=datetime.fromisoformat("2026-07-12T09:00").astimezone(),
                 end=datetime.fromisoformat("2026-07-12T09:30").astimezone())
    gym = Event(id="b", calendar="Gym", title="Workout",
               start=datetime.fromisoformat("2026-07-12T18:00").astimezone(),
               end=datetime.fromisoformat("2026-07-12T19:00").astimezone())
    work2 = Event(id="c", calendar="Work", title="Review",
                 start=datetime.fromisoformat("2026-07-13T09:00").astimezone(),
                 end=datetime.fromisoformat("2026-07-13T09:30").astimezone())
    s.sync_events([work1, gym, work2])
    assert s.known_calendars() == ["Gym", "Work"]

def test_known_calendars_empty_when_no_events(tmp_path):
    s = Storage(tmp_path / "t.db")
    assert s.known_calendars() == []

def test_last_synced_reports_stamp_for_date(tmp_path):
    s = Storage(tmp_path / "t.db")
    assert s.last_synced("2026-07-12") is None
    s.sync_events([_ev("a", "2026-07-12T09:00")])
    assert s.last_synced("2026-07-12") is not None
    assert s.last_synced("2026-07-13") is None

def test_pending_roundtrip(tmp_path):
    s = Storage(tmp_path / "t.db")
    c = PlannedChange(kind="move", category="Work", title="Report",
                      reason="collides with 'Standup' (Meeting)", event_id="x1",
                      new_start=datetime.fromisoformat("2026-07-12T15:00").astimezone(),
                      new_end=datetime.fromisoformat("2026-07-12T16:00").astimezone(),
                      requires_approval=True)
    pid = s.save_pending(c)
    loaded = s.get_pending([pid])
    assert loaded[0][0] == pid and loaded[0][1] == c
    s.delete_pending([pid])
    assert s.get_pending() == []

def test_save_pending_replaces_same_event_id_and_kind(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.save_pending(PlannedChange(kind="move", category="Work", title="X", reason="first",
                                 event_id="e1", requires_approval=True))
    s.save_pending(PlannedChange(kind="move", category="Work", title="Y", reason="r",
                                 event_id="e2", requires_approval=True))
    s.save_pending(PlannedChange(kind="move", category="Work", title="X", reason="replan",
                                 event_id="e1", requires_approval=True))
    pending = s.get_pending()
    assert len(pending) == 2
    assert next(c for _, c in pending if c.event_id == "e1").reason == "replan"
    s.save_pending(PlannedChange(kind="create", category="Food", title="L", reason="r"))
    s.save_pending(PlannedChange(kind="create", category="Food", title="L", reason="r"))
    assert len(s.get_pending()) == 4

def test_get_pending_empty_ids_is_not_all(tmp_path):
    """An empty id list must select nothing — only None/omitted means 'all'.
    (Regression: `if ids:` treated [] like None, turning 'apply nothing'
    into 'apply everything'.)"""
    s = Storage(tmp_path / "t.db")
    s.save_pending(PlannedChange(kind="move", category="Work", title="X",
                                 reason="r", event_id="e1"))
    assert s.get_pending([]) == []
    assert len(s.get_pending(None)) == 1
    assert len(s.get_pending()) == 1

def test_delete_pending_empty_ids_deletes_nothing(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.save_pending(PlannedChange(kind="move", category="Work", title="X",
                                 reason="r", event_id="e1"))
    s.delete_pending([])
    assert len(s.get_pending()) == 1

def test_damaged_db_is_set_aside_and_recreated(tmp_path):
    db = tmp_path / "t.db"
    db.write_text("not a database")
    s = Storage(db)
    s.save_garmin(GarminSummary(date="2026-07-03", sleep_score=70))
    assert s.get_garmin("2026-07-03").sleep_score == 70
    assert len(list(tmp_path.glob("t.db.corrupt-*"))) == 1
    assert db.stat().st_mode & 0o777 == 0o600


from dayoptimizer.core.models import Task


def _task(tid="t1", **kw):
    return Task(id=tid, title="Report", category="Work", duration_min=180,
                due=datetime(2030, 10, 18, 17, tzinfo=UTC), **kw)


def test_task_roundtrip_and_ids(tmp_path):
    s = Storage(tmp_path / "t.db")
    assert s.next_task_id() == "t1"
    s.save_task(_task(min_chunk_min=60, priority="high"))
    got = s.get_task("t1")
    assert got == _task(min_chunk_min=60, priority="high")
    assert s.next_task_id() == "t2"
    assert s.get_task("t9") is None
    s._conn.execute("DELETE FROM tasks")  # an emptied table must not hand out t1 again
    assert s.next_task_id() == "t2"


def test_open_tasks_sorted_and_done_left_out(tmp_path):
    s = Storage(tmp_path / "t.db")
    for tid in ("t10", "t2", "t3"):
        s.save_task(_task(tid))
    assert s.mark_task_done("t3") is True
    assert s.mark_task_done("t99") is False
    assert [t.id for t in s.open_tasks()] == ["t2", "t10"]


def test_old_rows_without_task_id_still_load(tmp_path):
    s = Storage(tmp_path / "t.db")
    old_event = {"id": "a", "calendar": "Gym", "title": "Workout", "start": "2026-07-03T17:00:00+00:00",
                 "end": "2026-07-03T18:00:00+00:00", "location": None, "all_day": False, "managed": False}
    s._conn.execute("INSERT INTO events_cache(id, data, last_seen) VALUES(?, ?, ?)",
                    ("a", json.dumps(old_event), "2026-07-03"))
    old_change = {"kind": "move", "category": "Gym", "title": "Workout", "reason": "r", "event_id": "a",
                  "new_start": None, "new_end": None, "requires_approval": True}
    s._conn.execute("INSERT INTO pending_changes(ts, data) VALUES(?, ?)", ("2026-07-03", json.dumps(old_change)))
    s._conn.commit()
    assert s.events_on("2026-07-03")[0].task_id is None
    assert s.get_pending()[0][1].task_id is None
