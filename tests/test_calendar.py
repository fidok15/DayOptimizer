from datetime import datetime, timezone
from dayoptimizer.core.calendar import ek_to_event, normalize_calendar

def test_ek_to_event_maps_fields():
    e = ek_to_event("ABC-123", "Gym", "Leg day",
                    datetime(2026, 7, 3, 17, tzinfo=timezone.utc),
                    datetime(2026, 7, 3, 18, tzinfo=timezone.utc), None)
    assert e.id == "ABC-123" and e.calendar == "Gym" and e.location is None

def test_normalize_calendar_strips_emoji_and_spaces():
    assert normalize_calendar("🔨 Work ") == "Work"
    assert normalize_calendar("👥 Meeting") == "Meeting"
    assert normalize_calendar("🎧 Free time") == "Free time"
    assert normalize_calendar("Public Holidays") == "Public Holidays"
    assert normalize_calendar("Important") == "Important"

def test_ek_to_event_normalizes_calendar():
    e = ek_to_event("X", "💪 Gym", "Workout",
                    datetime(2026, 7, 3, 17, tzinfo=timezone.utc),
                    datetime(2026, 7, 3, 18, tzinfo=timezone.utc), None)
    assert e.calendar == "Gym"

def test_ek_to_event_defaults_all_day_false():
    e = ek_to_event("ABC-123", "Gym", "Leg day",
                    datetime(2026, 7, 3, 17, tzinfo=timezone.utc),
                    datetime(2026, 7, 3, 18, tzinfo=timezone.utc), None)
    assert e.all_day is False

def test_ek_to_event_maps_all_day_true():
    e = ek_to_event("VAC-1", "Work", "Vacation",
                    datetime(2026, 7, 13, 0, tzinfo=timezone.utc),
                    datetime(2026, 8, 24, 23, 59, tzinfo=timezone.utc), None,
                    all_day=True)
    assert e.all_day is True


class _Src:
    def __init__(self, kind, ok):
        self.kind, self.ok = kind, ok

    def sourceType(self):
        return self.kind


class _Cal:
    def __init__(self, title="", source=None):
        self._title, self._source, self._color = title, source, None

    def title(self):
        return self._title

    def setTitle_(self, t):
        self._title = t

    def color(self):
        return self._color

    def setColor_(self, c):
        self._color = c

    def setSource_(self, s):
        self._source = s

    def source(self):
        return self._source


class _Store:
    def __init__(self, calendars, sources):
        self.calendars, self._sources, self.saved = calendars, sources, []

    def calendarsForEntityType_(self, _):
        return list(self.calendars)

    def defaultCalendarForNewEvents(self):
        return self.calendars[0] if self.calendars else None

    def sources(self):
        return self._sources

    def saveCalendar_commit_error_(self, cal, commit, err):
        if cal.source().ok:
            self.calendars.append(cal)
            self.saved.append((cal.title(), cal.source().kind))
            return True, None
        return False, "not allowed"


def _client(store):
    from types import SimpleNamespace
    from dayoptimizer.core.calendar import CalendarClient
    c = CalendarClient.__new__(CalendarClient)
    c._store = store
    c._EventKit = SimpleNamespace(EKEntityTypeEvent=0, EKSourceTypeLocal=0, EKSourceTypeCalDAV=2,
                                  EKCalendar=SimpleNamespace(calendarForEntityType_eventStore_=lambda t, s: _Cal()))
    return c


def test_ensure_calendar_skips_existing_and_falls_back_to_a_writable_account():
    import pytest
    google, icloud = _Src(2, False), _Src(2, True)
    store = _Store([_Cal("🔨 Work ", google)], [google, icloud, _Src(0, True)])
    client = _client(store)
    assert client.ensure_calendar("Work") is False
    assert client.ensure_calendar("Choir", "#4f9d8a") is True
    assert store.saved == [("Choir", 2)] and store.calendars[-1].color() is not None
    locked = _client(_Store([], [_Src(2, False)]))
    with pytest.raises(KeyError, match="couldn't be created"):
        locked.ensure_calendar("Gym")


def test_set_color_recolours_only_when_different(monkeypatch):
    from dayoptimizer.core import calendar as cal_mod
    monkeypatch.setattr(cal_mod, "_nscolor", lambda c: c)
    monkeypatch.setattr(cal_mod, "_hex", lambda c: c)
    google = _Src(2, True)
    work = _Cal("🔨 Work ", google)
    work.setColor_("#c2c2c2")
    store = _Store([work], [google])
    client = _client(store)
    assert client.set_color("Work", "#C2C2C2") is False
    assert client.set_color("Work", "#4fb286") is True and work.color() == "#4fb286"
    assert client.set_color("Nope", "#4fb286") is False


from dayoptimizer.core.calendar import task_id_from_notes


def test_task_id_from_notes():
    assert task_id_from_notes("Planned by DayOptimizer\nTask: t12") == "t12"
    assert task_id_from_notes("Planned by DayOptimizer") is None
    assert task_id_from_notes("") is None


def test_ek_to_event_carries_task_id():
    e = ek_to_event("X", "Work", "Report", datetime(2026, 7, 3, 9), datetime(2026, 7, 3, 10), None,
                    managed=True, task_id="t3")
    assert e.task_id == "t3" and e.managed


def test_access_already_given_is_not_asked_again_and_the_store_is_shared(monkeypatch):
    import sys
    from types import SimpleNamespace
    from dayoptimizer.core.calendar import CalendarClient
    made, asked = [], []
    store = SimpleNamespace(requestFullAccessToEventsWithCompletion_=lambda h: asked.append(h))
    ek = SimpleNamespace(EKEntityTypeEvent=0, EKAuthorizationStatusFullAccess=3, EKEventStore=SimpleNamespace(
        alloc=lambda: SimpleNamespace(init=lambda: made.append(1) or store),
        authorizationStatusForEntityType_=lambda t: 3))
    monkeypatch.setitem(sys.modules, "EventKit", ek)
    monkeypatch.setattr(CalendarClient, "_shared", None)
    assert all(CalendarClient().request_access() for _ in range(20))
    assert made == [1] and asked == []


def test_every_write_is_journaled_and_taken_back_and_redone(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from dayoptimizer.core import calendar as cal_mod

    class Date:
        def __init__(self, dt):
            self.dt = dt

        def timeIntervalSince1970(self):
            return self.dt.timestamp()

    class Ev:
        n = 0

        def __init__(self):
            Ev.n += 1
            self.id, self.title_, self.notes_, self.cal = f"e{Ev.n}", "", None, None

        def eventIdentifier(self): return self.id
        def title(self): return self.title_
        def setTitle_(self, t): self.title_ = t
        def notes(self): return self.notes_
        def setNotes_(self, n): self.notes_ = n
        def calendar(self): return self.cal
        def setCalendar_(self, c): self.cal = c
        def startDate(self): return self.start
        def setStartDate_(self, d): self.start = d
        def endDate(self): return self.end
        def setEndDate_(self, d): self.end = d
        def isAllDay(self): return False

    class Store(_Store):
        def __init__(self):
            super().__init__([_Cal("Learn")], [])
            self.events = {}

        def eventWithIdentifier_(self, i): return self.events.get(i)
        def saveEvent_span_error_(self, ev, span, err):
            self.events[ev.id] = ev
            return True, None

        def removeEvent_span_error_(self, ev, span, err):
            del self.events[ev.id]
            return True, None

    store = Store()
    client = _client(store)
    client._EventKit.EKEvent = SimpleNamespace(eventWithEventStore_=lambda s: Ev())
    monkeypatch.setattr(client, "_nsdate", Date)
    monkeypatch.setattr(cal_mod, "JOURNAL", [])
    at = lambda h: datetime(2026, 10, 26, h).astimezone()
    kept = client.create_event("Learn", "Study", at(8), at(9))
    moved = client.create_event("Learn", "AWS", at(10), at(11), task_id="t1")
    gone = client.create_event("Learn", "ML", at(12), at(13))
    cal_mod.JOURNAL.clear()  # an earlier run
    client.move_event(moved, at(15), at(16))
    client.delete_event(gone)
    added = client.create_event("Learn", "audio", at(17), at(18))
    steps = list(cal_mod.JOURNAL)
    assert [s["undo"] for s in steps] == ["move", "create", "remove"]  # how to take back each, in order
    cal_mod.JOURNAL.clear()
    for s in reversed(steps):
        client.take_back(s)
    titles = {e.title_: (e.start.dt.hour, e.notes_) for e in store.events.values()}
    assert added not in store.events and kept in store.events
    assert titles["AWS"][0] == 10 and titles["ML"] == (12, cal_mod.MARKER)  # back as a planner block
    redo = list(cal_mod.JOURNAL)
    for s in reversed(redo):  # undoing the undo redoes it
        client.take_back(s)
    assert {e.title_ for e in store.events.values()} == {"Study", "AWS", "audio"}
