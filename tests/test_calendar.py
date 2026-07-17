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
