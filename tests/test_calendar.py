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
        self._title, self._source, self.color = title, source, None

    def title(self):
        return self._title

    def setTitle_(self, t):
        self._title = t

    def setColor_(self, c):
        self.color = c

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
    assert client.ensure_calendar("Work") is False  # emoji-prefixed name counts
    assert client.ensure_calendar("Choir", "#4f9d8a") is True
    assert store.saved == [("Choir", 2)] and store.calendars[-1].color is not None
    locked = _client(_Store([], [_Src(2, False)]))
    with pytest.raises(KeyError, match="couldn't be created"):
        locked.ensure_calendar("Gym")
