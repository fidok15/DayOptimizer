import json
from datetime import datetime, timezone
from dayoptimizer.core.models import Event, GarminSummary, PlannedChange
from dayoptimizer.core.storage import Storage

def _event(eid: str) -> Event:
    return Event(id=eid, calendar="Gym", title="Workout",
                 start=datetime(2026, 7, 3, 17, tzinfo=timezone.utc),
                 end=datetime(2026, 7, 3, 18, tzinfo=timezone.utc))

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
    s.save_garmin(GarminSummary(date="2026-07-03", sleep_score=81))  # upsert
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
    # a user drags a Calendar block around: same id, new start/end. The
    # watcher must see it, not silently upsert it as if nothing happened.
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
    # only start/end define "rescheduled" — a rename must not trigger a replan
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
    s.set_state("x", "2")  # upsert
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
    # "b" was cancelled: syncing the window without it must drop it from cache
    s.sync_events([_ev("a", "2026-07-12T09:00")], window_start=ws, window_end=we)
    assert [e.id for e in s.events_on("2026-07-12")] == ["a"]
    assert [e.id for e in s.events_on("2026-07-13")] == ["c"]  # outside window untouched

def test_sync_events_without_window_never_prunes(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.sync_events([_ev("a", "2026-07-12T09:00")])
    s.sync_events([])  # backward-compatible call: no window, no pruning
    assert [e.id for e in s.events_on("2026-07-12")] == ["a"]

def test_events_on_tolerates_cached_rows_missing_all_day_key(tmp_path):
    # cache rows written before the all_day field existed lack the key —
    # events_on must not crash and must default all_day to False.
    s = Storage(tmp_path / "t.db")
    start = datetime.fromisoformat("2026-07-12T09:00").astimezone()
    payload = {"id": "old1", "calendar": "Meeting", "title": "Standup",
               "start": start.isoformat(), "end": start.replace(minute=30).isoformat(),
               "location": None}  # no "all_day" key — simulates a pre-migration row
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
    # replans re-propose the same unresolved conflict: the newer proposal must
    # replace the older row, not accumulate near-identical pending entries
    s = Storage(tmp_path / "t.db")
    s.save_pending(PlannedChange(kind="move", category="Work", title="X", reason="first",
                                 event_id="e1", requires_approval=True))
    s.save_pending(PlannedChange(kind="move", category="Work", title="Y", reason="r",
                                 event_id="e2", requires_approval=True))
    s.save_pending(PlannedChange(kind="move", category="Work", title="X", reason="replan",
                                 event_id="e1", requires_approval=True))
    pending = s.get_pending()
    assert len(pending) == 2  # e1 replaced, e2 untouched
    assert next(c for _, c in pending if c.event_id == "e1").reason == "replan"
    # rows without an event_id (creates) are never deduped
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
